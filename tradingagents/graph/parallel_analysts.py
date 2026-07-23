import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Callable

from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage, AIMessage
from langgraph.prebuilt import ToolNode

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.social_media_analyst import create_social_media_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.policy_analyst import create_policy_analyst
from tradingagents.agents.analysts.hot_money_tracker import create_hot_money_tracker
from tradingagents.agents.analysts.lockup_watcher import create_lockup_watcher
from tradingagents.dataflows.data_source_logger import get_current_logger, set_current_logger, DataSourceLogger
from tradingagents.agents.utils.data_integrity import (
    DataIntegrityEvaluator,
    DataAvailability,
    DataIntegrityLevel,
    BatchIntegrityManager,
    ANALYST_NAMES_CN,
)

logger = logging.getLogger(__name__)


ANALYST_CREATORS = {
    "market": create_market_analyst,
    "social": create_social_media_analyst,
    "news": create_news_analyst,
    "fundamentals": create_fundamentals_analyst,
    "policy": create_policy_analyst,
    "hot_money": create_hot_money_tracker,
    "lockup": create_lockup_watcher,
}

ANALYST_REPORT_FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "policy": "policy_report",
    "hot_money": "hot_money_report",
    "lockup": "lockup_report",
}

ANALYST_DATA_SOURCE_NAMES = {
    "market": "技术分析师",
    "social": "市场情绪分析师",
    "news": "新闻分析师",
    "fundamentals": "基本面分析师",
    "policy": "政策分析师",
    "hot_money": "游资追踪师",
    "lockup": "解禁追踪师",
}


def _extract_report_from_result(result: Any, report_field: str) -> str:
    if isinstance(result, dict) and report_field in result:
        val = result[report_field]
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _has_tool_calls(message: Any) -> bool:
    if not hasattr(message, 'tool_calls'):
        return False
    tc = getattr(message, 'tool_calls', None)
    return tc is not None and len(tc) > 0


def _get_message_content(message: Any) -> str:
    if hasattr(message, 'content'):
        content = getattr(message, 'content', '')
        return content if isinstance(content, str) else str(content)
    return ""


def run_single_analyst(
    analyst_type: str,
    analyst_node: Callable,
    tool_node: ToolNode,
    state: Dict[str, Any],
    max_iterations: int = 10,
) -> Dict[str, Any]:
    """
    执行单个分析师的分析任务

    Returns:
        Dict[str, Any]: 包含报告和完整性信息的字典
            - report_field: 分析报告内容
            - integrity_report: 数据完整性报告（新增）
    """
    company = state.get("company_of_interest", "")
    analyst_name = ANALYST_DATA_SOURCE_NAMES.get(analyst_type, analyst_type)

    data_logger = DataSourceLogger(stock_code=company, analyst_name=analyst_name)
    set_current_logger(data_logger)

    # 创建数据完整性评估器
    integrity_evaluator = DataIntegrityEvaluator(analyst_type)

    current_state = dict(state)
    report_field = ANALYST_REPORT_FIELDS.get(analyst_type, f"{analyst_type}_report")
    report = ""
    error_msg = ""
    tool_errors: List[str] = []  # 跟踪工具调用失败

    try:
        for i in range(max_iterations):
            logger.debug(f"🔄 [{analyst_type}] 第 {i+1} 次迭代")

            try:
                result = analyst_node(current_state)
            except Exception as e:
                error_msg = f"分析师调用异常: {str(e)}"
                logger.error(f"❌ [{analyst_type}] {error_msg}", exc_info=True)
                # 记录失败
                integrity_evaluator.record_failure(
                    tool_name="analyst_node",
                    error_message=str(e),
                    status=DataAvailability.ERROR
                )
                break

            node_report = _extract_report_from_result(result, report_field)
            if node_report:
                report = node_report
                logger.debug(f"✅ [{analyst_type}] 从 node 返回中获取报告，长度: {len(report)}")
                break

            if "messages" in result and result["messages"]:
                new_msgs = result["messages"]
                if isinstance(new_msgs, list):
                    current_state["messages"] = current_state["messages"] + new_msgs
                else:
                    current_state["messages"] = current_state["messages"] + [new_msgs]

            if not current_state.get("messages"):
                error_msg = "消息队列为空"
                logger.error(f"❌ [{analyst_type}] {error_msg}")
                break

            last_message = current_state["messages"][-1]

            if _has_tool_calls(last_message):
                tool_calls = last_message.tool_calls
                new_tool_messages = []
                tools_by_name = getattr(tool_node, 'tools_by_name', {})

                logger.debug(f"🔧 [{analyst_type}] 执行 {len(tool_calls)} 个工具调用")

                for tc in tool_calls:
                    tool_name = tc.get('name', '') if isinstance(tc, dict) else getattr(tc, 'name', '')
                    tool_args = tc.get('args', {}) if isinstance(tc, dict) else getattr(tc, 'args', {})
                    tool_id = tc.get('id', '') if isinstance(tc, dict) else getattr(tc, 'id', '')

                    tool = tools_by_name.get(tool_name)
                    if tool:
                        try:
                            tool_output = tool.invoke(tool_args)

                            # 检查输出是否为空或无效
                            if tool_output and str(tool_output).strip():
                                integrity_evaluator.record_success(tool_name, str(tool_output)[:100])
                                new_tool_messages.append(
                                    ToolMessage(content=str(tool_output), tool_call_id=tool_id)
                                )
                            else:
                                integrity_evaluator.record_empty_result(tool_name)
                                new_tool_messages.append(
                                    ToolMessage(content=f"[{tool_name} 返回空数据]", tool_call_id=tool_id)
                                )
                                tool_errors.append(f"{tool_name}: 空结果")

                        except TimeoutError as e:
                            error_msg = f"Tool call timeout: {str(e)}"
                            logger.warning(f"⏱️ [{analyst_type}] 工具 {tool_name} 调用超时: {e}")
                            integrity_evaluator.record_timeout(tool_name, str(e))
                            new_tool_messages.append(
                                ToolMessage(content=error_msg, tool_call_id=tool_id)
                            )
                            tool_errors.append(f"{tool_name}: 超时")

                        except Exception as e:
                            error_msg = f"Tool call error: {str(e)}"
                            logger.warning(f"⚠️ [{analyst_type}] 工具 {tool_name} 调用失败: {e}")
                            integrity_evaluator.record_failure(tool_name, str(e))
                            new_tool_messages.append(
                                ToolMessage(content=error_msg, tool_call_id=tool_id)
                            )
                            tool_errors.append(f"{tool_name}: {str(e)}")
                    else:
                        error_msg = f"Tool not found: {tool_name}"
                        logger.warning(f"⚠️ [{analyst_type}] 未找到工具: {tool_name}")
                        integrity_evaluator.record_failure(tool_name, error_msg, DataAvailability.UNAVAILABLE)
                        new_tool_messages.append(
                            ToolMessage(content=error_msg, tool_call_id=tool_id)
                        )
                        tool_errors.append(tool_name)

                current_state["messages"] = current_state["messages"] + new_tool_messages
            else:
                content = _get_message_content(last_message)
                if content and len(content.strip()) > 20:
                    report = content.strip()
                    logger.debug(f"✅ [{analyst_type}] 从最后一条消息提取报告，长度: {len(report)}")
                else:
                    error_msg = f"最后一条消息内容过短或为空（长度: {len(content)}）"
                    logger.warning(f"⚠️ [{analyst_type}] {error_msg}")
                break

        if not report and not error_msg:
            error_msg = f"达到最大迭代次数 ({max_iterations}) 仍未生成报告"
            logger.warning(f"⚠️ [{analyst_type}] {error_msg}")

            if current_state.get("messages"):
                for msg in reversed(current_state["messages"]):
                    content = _get_message_content(msg)
                    if content and len(content.strip()) > 50:
                        report = content.strip()
                        logger.info(f"🔧 [{analyst_type}] 兜底：从历史消息中提取报告，长度: {len(report)}")
                        break

        if not report and error_msg:
            report = f"[分析未能完成: {error_msg}]"

    except Exception as e:
        report = f"[分析异常: {str(e)}]"
        logger.error(f"❌ [{analyst_type}] 执行异常: {e}", exc_info=True)
        integrity_evaluator.record_failure("analyst_execution", str(e))
    finally:
        set_current_logger(None)

    # 获取数据完整性报告
    integrity_report = integrity_evaluator.assess_integrity()

    # 根据数据完整性级别标记报告
    quality_prefix = ""
    if integrity_report.integrity_level == DataIntegrityLevel.COMPLETE_FAILURE:
        quality_prefix = "[❌ 分析失败] "
        logger.error(f"❌ [{analyst_type}] 分析完全失败")
    elif integrity_report.integrity_level == DataIntegrityLevel.CRITICAL_MISSING:
        quality_prefix = "[⚠️ 关键数据缺失] "
        logger.warning(f"⚠️ [{analyst_type}] 关键数据缺失: {integrity_report.core_tool_results}")
    elif integrity_report.integrity_level == DataIntegrityLevel.PARTIAL:
        quality_prefix = "[🔶 部分数据缺失] "
        logger.warning(f"🔶 [{analyst_type}] 部分数据缺失")

    if tool_errors:
        report = f"{quality_prefix}{report}"

    logger.info(f"📊 [{analyst_type}] 最终报告长度: {len(report)}, 完整性: {integrity_report.quality_label}")

    # 返回包含完整性和报告的字典
    return {
        report_field: report,
        "_integrity_report": integrity_report,
    }


def create_parallel_analysts_node(
    quick_thinking_llm: Any,
    tool_nodes: Dict[str, ToolNode],
    selected_analysts: List[str],
):
    analyst_instances = {}
    for analyst_type in selected_analysts:
        creator = ANALYST_CREATORS.get(analyst_type)
        if creator:
            analyst_instances[analyst_type] = creator(quick_thinking_llm)

    def parallel_analysts_node(state: AgentState) -> dict:
        logger.info(f"🚀 开始并行执行 {len(selected_analysts)} 位分析师: {selected_analysts}")

        base_state = dict(state)

        results = {}

        # 创建批量完整性管理器
        batch_manager = BatchIntegrityManager()

        with ThreadPoolExecutor(max_workers=len(selected_analysts)) as executor:
            future_to_analyst = {}
            for analyst_type in selected_analysts:
                analyst_node = analyst_instances.get(analyst_type)
                tool_node = tool_nodes.get(analyst_type)
                if analyst_node and tool_node:
                    future = executor.submit(
                        run_single_analyst,
                        analyst_type,
                        analyst_node,
                        tool_node,
                        base_state,
                    )
                    future_to_analyst[future] = analyst_type
                else:
                    logger.warning(f"⚠️ 分析师 {analyst_type} 缺少 node 或 tool_node，跳过")
                    report_field = ANALYST_REPORT_FIELDS.get(analyst_type, f"{analyst_type}_report")
                    results[report_field] = f"[分析师 {analyst_type} 未初始化]"
                    # 记录未初始化状态
                    evaluator = batch_manager.get_evaluator(analyst_type)
                    evaluator.record_failure("analyst_init", "未初始化", DataAvailability.ERROR)

            for future in as_completed(future_to_analyst):
                analyst_type = future_to_analyst[future]
                try:
                    result = future.result()
                    results.update(result)

                    # 收集完整性报告
                    if "_integrity_report" in result:
                        batch_manager._reports[analyst_type] = result["_integrity_report"]
                        del results["_integrity_report"]  # 不需要传给后续节点

                    logger.info(f"✅ 分析师 {analyst_type} 完成")
                except Exception as e:
                    logger.error(f"❌ 分析师 {analyst_type} 执行失败: {e}", exc_info=True)
                    report_field = ANALYST_REPORT_FIELDS.get(analyst_type, f"{analyst_type}_report")
                    results[report_field] = f"[分析失败: {str(e)}]"
                    # 记录失败状态
                    evaluator = batch_manager.get_evaluator(analyst_type)
                    evaluator.record_failure("analyst_execution", str(e))

        for analyst_type in selected_analysts:
            report_field = ANALYST_REPORT_FIELDS.get(analyst_type, f"{analyst_type}_report")
            if report_field not in results:
                results[report_field] = f"[分析师 {analyst_type} 未执行]"
                logger.warning(f"⚠️ 分析师 {analyst_type} 未产生结果，填充占位")

        messages = state.get("messages", [])
        results["messages"] = messages

        # 生成整体数据质量摘要
        batch_manager._reports = {
            k: v for k, v in batch_manager._reports.items()
            if k in selected_analysts
        }
        quality_summary = batch_manager.generate_summary_report()
        can_proceed, proceed_reason = batch_manager.should_proceed_to_debate()

        # 将完整性信息添加到 state
        results["_data_quality_summary"] = quality_summary
        results["_can_proceed_to_debate"] = can_proceed
        results["_debate_proceed_reason"] = proceed_reason
        results["_overall_quality_score"] = batch_manager.get_overall_quality()[0]

        # 记录日志
        logger.info(f"✅ 所有分析师并行执行完成，共 {len(selected_analysts)} 位")
        logger.info(f"📊 整体数据质量: {batch_manager.get_overall_quality()[1]}")
        if not can_proceed:
            logger.warning(f"⚠️ 数据质量不足，可能影响后续分析: {proceed_reason}")

        return results

    return parallel_analysts_node
