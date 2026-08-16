"""
分析报告管理API路由
"""
import json
import logging
import re
from datetime import datetime
from typing import Any
from app.utils.timezone import now_tz

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.database import get_mongo_db
from ..utils.timezone import to_config_tz
from .auth_db import get_current_user

logger = logging.getLogger("webapi")

# ============================================================
# 报告结构化字段抽取：从多份子报告 markdown 中解析核心字段
# ============================================================

# 数值 / 价格类字段的别名
_PRICE_FIELDS = [
    (["理想买入"], "理想买入"),
    (["二次买入"], "二次买入"),
    (["止损价格", "止损位", "止损线"], "止损价格"),
    (["止盈目标", "目标价格", "目标价"], "止盈目标"),
    (["支撑位", "支撑"], "支撑位"),
    (["阻力位", "压力位"], "阻力位"),
]

_SCORE_FIELDS = [
    (["置信度"], "置信度"),
    (["风险等级"], "风险等级"),
    (["技术面评分"], "技术面评分"),
    (["基本面评分"], "基本面评分"),
    (["情绪面评分"], "情绪面评分"),
    (["消息面评分"], "消息面评分"),
    (["资金面评分"], "资金面评分"),
    (["政策面评分"], "政策面评分"),
    (["解禁面评分"], "解禁面评分"),
]


def _iter_text(reports: dict[str, Any]):
    """依次取出 reports 中所有字符串子报告，按优先级排序"""
    order = [
        "final_trade_decision", "trader_investment_plan",
        "investment_plan", "research_team_decision",
        "risk_control_decision", "risk_management_decision",
    ]
    for key in order:
        v = reports.get(key)
        if isinstance(v, str):
            yield v
    for k, v in reports.items():
        if k not in order and isinstance(v, str):
            yield v


def _clean_report_text(text: str) -> str:
    """
    清理报告文本，移除开头的思考过程、寒暄语、工具调用痕迹等无关内容。
    确保报告从正式内容（评分标题、章节标题等）开始。
    """
    if not text or not isinstance(text, str):
        return text
    
    lines = text.split("\n")
    cleaned_lines = []
    found_start = False
    
    # 判断一行是否是报告正式开始的标志
    def is_formal_start(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        # markdown 标题（## 或 ### 开头）
        if re.match(r'^#{1,6}\s+', stripped):
            return True
        # 评分标题行（包含"评分："或"评分:"）
        if re.search(r'面评分\s*[:：]', stripped):
            return True
        # 带编号的正式章节
        return bool(re.match(r'^\d+[\.、]\s+', stripped) and len(stripped) > 10)
    
    # 判断一行是否是应该跳过的寒暄/思考内容
    def is_filler(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True  # 空行在开头跳过
        # 跳过分隔线
        if re.match(r'^[-=*_]{3,}$', stripped):
            return True
        filler_patterns = [
            r'^好的', r'^让我', r'^现在', r'^我来', r'^开始', r'^首先',
            r'分析.*报告', r'撰写.*报告', r'整理.*报告', r'生成.*报告',
            r'数据.*齐全', r'数据.*获取', r'获取.*数据', r'收集.*数据',
            r'接下来', r'下面.*分析', r'以下.*分析', r'这是', r'以下是',
            r'根据.*分析', r'基于.*分析',
            r'^ok', r'^sure', r'^certainly', r'^let me', r'^i will',
            r'工具调用', r'调用.*工具', r'执行.*工具',
        ]
        for pat in filler_patterns:
            if re.search(pat, stripped, re.IGNORECASE):
                # 但如果是正式章节标题的一部分，就不跳过
                return not is_formal_start(stripped)
        return False
    
    for line in lines:
        if found_start:
            cleaned_lines.append(line)
        else:
            if is_formal_start(line):
                found_start = True
                cleaned_lines.append(line)
            elif is_filler(line):
                continue
            else:
                # 遇到既不是正式开始也不是寒暄语的内容，就从这里开始
                # 可能是正文的第一段，保留
                found_start = True
                cleaned_lines.append(line)
    
    if not cleaned_lines:
        return text
    
    return "\n".join(cleaned_lines)


def _match_price(text: str, aliases: list[str]) -> str | None:
    """
    在文本中查找诸如 `理想买入\n10.70 元` 或 `7. 支撑位：10.88元` 的价格。
    返回价格字符串（如 "10.70 元"），找不到返回 None。
    """
    if not text:
        return None

    for alias in aliases:
        # 尝试 "N. 名称：价格 元（注释）"
        pattern1 = re.compile(
            r"(?:^|\n)\s*\*?\s*(?:\d+[\.、]\s*)?\*?\s*" + re.escape(alias) +
            r"\s*\*?\s*[:：]\s*([^\n，。；,;（(]{0,80})",
        )
        m = pattern1.search(text)
        if m:
            val = m.group(1).strip()
            if "不适用" in val:
                continue
            num = re.search(r"(\d+(?:\.\d+)?)", val)
            if num:
                return f"{num.group(1)} 元"
            if val and len(val) < 40:
                return val

        # 尝试单独行：`**8. 止盈目标**` / `**6. 理想买入**` 之后跟着一行价格
        pattern2 = re.compile(
            r"(?:^|\n)\s*\*+\s*(?:\d+[\.、]\s*)?" + re.escape(alias) +
            r"\s*\*+\s*\n\s*([^\n，。；,;（(]{0,80})",
        )
        m = pattern2.search(text)
        if m:
            val = m.group(1).strip(" *\n")
            if "不适用" in val:
                continue
            num = re.search(r"(\d+(?:\.\d+)?)", val)
            if num:
                return f"{num.group(1)} 元"
            if val and len(val) < 40:
                return val

        # 简化版：在一段内出现 `名称：数值元`
        pattern3 = re.compile(
            re.escape(alias) + r"\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?",
        )
        m = pattern3.search(text)
        if m:
            return f"{m.group(1)} 元"

    return None


def _match_score(text: str, aliases: list[str]) -> str | None:
    """从文本中抽取类似 `置信度：0.75` 或 `**11. 置信度**`\n0.75 的数值"""
    if not text:
        return None
    lines = text.split("\n")
    n = len(lines)

    for alias in aliases:
        # 方式 A：在一行内出现 "名称：数值"（支持列表项前缀、markdown标题、emoji、/100后缀）
        for line in lines:
            stripped = line.strip()
            # 使用 search 而非 match，支持前缀为 emoji、markdown 标题标记等
            # 匹配形如 "技术面评分：58/100"、"📊 技术面评分: 75"、"## 技术面评分 80分" 等
            m = re.search(
                re.escape(alias) +
                r"\s*[:：\s]\s*(-?\d+(?:\.\d+)?|高|中|低|中等|较高|较低)(?:\s*/\s*100|\s*分)?\b",
                stripped,
            )
            if m:
                return m.group(1)

        # 方式 B：标题行 + 下一行是数字
        for i, line in enumerate(lines):
            stripped = line.strip().strip("*# \t")
            if alias in stripped:
                normalized = stripped.strip("*# \t")
                if alias in normalized:
                    for j in range(i + 1, min(i + 3, n)):
                        next_line = lines[j].strip().strip("* \t-•")
                        if not next_line:
                            continue
                        m = re.match(
                            r"(-?\d+(?:\.\d+)?|高|中|低|中等|较高|较低)(?:\s*/\s*100|\s*分)?\b",
                            next_line,
                        )
                        if m:
                            return m.group(1)
                        break
                    break

    return None


def _extract_holder_empty_advice(text: str, field_name: str) -> str | None:
    """
    提取持仓者建议或空仓者建议。
    匹配格式如：
      - "1.  **对于当前持仓者（首要任务）：**" + 列表项
      - "持仓者：xxx"
      - "对于空仓者：xxx"
      - "止损价格（建议给现持仓者）：xxx"
      - "理想买入（不建议，仅作空仓者观察参考）：xxx"
    
    收集从标题行之后的所有内容（包括列表项），直到遇到下一个章节标题或文档结束。
    """
    if not text:
        return None
    
    lines = text.split("\n")
    n = len(lines)
    
    # 持仓者关键词（精确匹配）
    holder_patterns = [
        r"^持仓者[：:：]",
        r"^对于.*持仓者[：:：]",
        r"^当前持仓者[：:：]",
        r"^持有者[：:：]",
        r"持仓者建议[：:：]",
        r"建议给现持仓者",
        r"（建议给现持仓者）",
        r"（持仓者.*建议）",
    ]
    # 空仓者关键词（精确匹配）
    empty_patterns = [
        r"^空仓者[：:：]",
        r"^对于.*空仓者[：:：]",
        r"^未持仓者[：:：]",
        r"^观望者[：:：]",
        r"空仓建议[：:：]",
        r"空仓者观察",
        r"空仓者.*参考",
        r"仅作.*空仓者",
        r"空仓者.*观望",
        r"空仓者.*买入",
        r"不建议.*空仓者",
    ]
    
    patterns = holder_patterns if field_name == "持仓者建议" else empty_patterns
    # 排除关键词
    if field_name == "持仓者建议":
        exclude_patterns = [r"^空仓者", r"空仓者[：:：]", r"观望者[：:：]", r"仅作.*空仓者", r"不建议.*空仓者", r"空仓者.*观望", r"空仓者.*买入"]
    else:
        exclude_patterns = [r"^持仓者", r"持仓者[：:：]", r"持有者[：:：]", r"建议给现持仓者", r"（建议给现持仓者）"]
    
    collected = []
    
    # 方法1：找章节标题
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in patterns:
            if re.search(pat, stripped):
                start_idx = i
                break
        if start_idx is not None:
            break
    
    if start_idx is not None:
        # 收集从 start_idx+1 开始的内容
        for j in range(start_idx + 1, n):
            line = lines[j]
            stripped = line.strip()
            
            # 遇到任何标题行（# 到 ######）停止
            if re.match(r"^#{1,6}\s+", stripped):
                break
            
            # 持仓者遇到"对于空仓者"或"空仓者"停止
            if field_name == "持仓者建议" and re.search(r"(对于空仓者|空仓者[：:：])", stripped):
                break
            
            # 跳过纯标题行（如 "1. xxx：" 或 "#### xxx"）
            if re.match(r"^\d+[\.、]\s*", stripped) and re.search(r"[：:：]$", stripped):
                continue
            
            if stripped:
                collected.append(stripped)
    else:
        # 方法2：对于结构化列表格式，收集所有包含关键词且不包含排除关键词的行
        for _i, line in enumerate(lines):
            stripped = line.strip()
            
            # 检查是否包含关键词
            has_keyword = False
            for pat in patterns:
                if re.search(pat, stripped):
                    has_keyword = True
                    break
            
            # 检查是否包含排除关键词
            has_exclude = False
            for pat in exclude_patterns:
                if re.search(pat, stripped):
                    has_exclude = True
                    break
            
            if has_keyword and not has_exclude:
                # 清理并添加
                cleaned = re.sub(r"\*+", "", stripped)
                cleaned = re.sub(r"^[\•\-\*\d\.]+\s*", "", cleaned)
                if cleaned and len(cleaned) > 5:
                    collected.append(cleaned)
    
    if not collected:
        return None
    
    # 清理内容
    content = "\n".join(collected)
    # 移除 markdown 加粗符号
    content = re.sub(r"\*+", "", content)
    # 移除列表标记
    content = re.sub(r"^[\•\-\*\d\.]+\s*", "", content, flags=re.MULTILINE)
    content = content.strip()
    
    if not content:
        return None
    
    # 限制长度
    max_chars = 1000
    if len(content) > max_chars:
        # 在句号处截断
        pos = content.rfind("。", 0, max_chars)
        content = content[:pos + 1] if pos > max_chars // 2 else content[:max_chars] + "…"
    
    return content


def _normalize_rating(val: str) -> str:
    v = str(val).strip()
    for kw in ["评级", "操作建议", "投资建议", "建议", "行动评级"]:
        if v.startswith(kw):
            v = v[len(kw):].lstrip("：:、•·- ")
            v = v.strip()
            break
    v = v.strip("，。；：:、•·()（）【】 ")
    en_map = {
        "BUY": "买入", "SELL": "卖出", "HOLD": "持有",
        "STRONG_BUY": "买入", "STRONG_SELL": "卖出",
        "STRONG BUY": "买入", "STRONG SELL": "卖出",
        "OVERWEIGHT": "增持", "UNDERWEIGHT": "减持",
        "NEUTRAL": "持有", "WAIT": "持有",
        "ADD": "增持", "REDUCE": "减持",
        "ACCUMULATE": "增持", "SELL SHORT": "卖出",
        "MARKET PERFORM": "持有", "MARKET OUTPERFORM": "增持",
        "MARKET UNDERPERFORM": "减持", "EQUAL WEIGHT": "持有",
        "OUTPERFORM": "增持", "UNDERPERFORM": "减持",
    }
    v_upper = v.upper().strip()
    if v_upper in en_map:
        return en_map[v_upper]
    for en_key, cn_val in en_map.items():
        if en_key in v_upper:
            return cn_val
    cn_aliases = [
        ("强烈买入", "买入"),
        ("强烈卖出", "卖出"),
        ("清仓", "卖出"),
        ("超配", "增持"),
        ("低配", "减持"),
        ("标配", "持有"),
        ("买入", "买入"),
        ("增持", "增持"),
        ("加仓", "增持"),
        ("卖出", "卖出"),
        ("减持", "减持"),
        ("减仓", "减持"),
        ("持有", "持有"),
        ("观望", "持有"),
        ("中性", "持有"),
    ]
    for alias, final in cn_aliases:
        if alias in v:
            return final
    return "持有"


def extract_structured_fields(reports: dict[str, Any]) -> dict[str, Any]:
    """
    遍历 reports 中的所有子报告（以及可能存在的 decision 字典），
    抽取可用于前端展示的结构化字段。字段会被合并到报告详情顶层，
    以便前端 `pickField(report, [...])` 工作。

    **统一的评级/操作建议**：`评级`、`操作建议`、`action` 三个字段完全一致，
    优先级为：final_trade_decision 文本 > trader_investment_plan 文本 >
    research_team_decision 文本 > decision 对象字典 > 全文兜底。

    **六张核心洞察卡片**：每张卡片的内容明确来源于对应研究报告章节，
    按以下优先级提取：章节标题精确匹配 → 关键字段匹配 → 对应模块正文精选。

    返回字段（中文命名，便于前端直接展示）：
      - 置信度 / 技术面评分 / 基本面评分 / 情绪面评分 / 政策面评分
      - 风险等级
      - 评级 / 操作建议 / action（三者完全一致）
      - 理想买入 / 二次买入 / 止损价格 / 止盈目标 / 支撑位 / 阻力位
      - 核心洞察 / 投资逻辑 / 情绪分析 / 趋势预测 / 策略点位 / 风险提示
    """
    result: dict[str, Any] = {}
    if not isinstance(reports, dict) or not reports:
        return result

    # 0) 清理所有报告文本，移除开头的思考过程、寒暄语等无关内容
    cleaned_reports: dict[str, Any] = {}
    for k, v in reports.items():
        if isinstance(v, str):
            cleaned_reports[k] = _clean_report_text(v)
        else:
            cleaned_reports[k] = v
    reports = cleaned_reports

    # 0) 先从高优先级文本模块提取操作建议（评级），比 decision 字典更权威
    priority_modules = [
        "final_trade_decision", "trader_investment_plan",
        "investment_plan", "research_team_decision",
        "risk_control_decision", "risk_management_decision",
    ]

    def _priority_texts():
        for key in priority_modules:
            v = reports.get(key)
            if isinstance(v, str):
                yield v

    # 从优先级最高的模块开始提取，找到第一个非空的评级
    text_rating = None
    for module_text in _priority_texts():
        val = _match_rating(module_text, ["决策", "操作建议", "评级", "投资建议", "建议", "行动评级"])
        if val:
            text_rating = _normalize_rating(val)
            break

    # 1) 从 decision 字典取值（来自 trading_graph 的结构化输出）
    decision_obj = reports.get("decision")
    if isinstance(decision_obj, dict) and decision_obj:
        conf_val = (
            decision_obj.get("confidence_score")
            or decision_obj.get("confidence")
            or decision_obj.get("score")
        )
        if conf_val is not None and conf_val != "":
            try:
                if isinstance(conf_val, (int, float)) and 0 < conf_val <= 1:
                    result["置信度"] = round(conf_val * 100, 1)
                else:
                    result["置信度"] = round(float(conf_val), 1)
            except (TypeError, ValueError):
                pass
        if "风险等级" not in result:
            rl_val = decision_obj.get("risk_level")
            if rl_val:
                result["风险等级"] = str(rl_val)
        # 仅当文本模块未提取到操作建议时，才使用 decision 字典
        if text_rating is None:
            act = (
                decision_obj.get("action")
                or decision_obj.get("recommendation")
                or decision_obj.get("rating")
            )
            if act:
                text_rating = _normalize_rating(str(act))

    # 统一设置评级 / 操作建议 / action，三者保持完全一致
    if text_rating:
        result["评级"] = text_rating
        result["操作建议"] = text_rating
        result["action"] = text_rating

    # 1a) 使用多维度重新计算置信度（优先级高于从 decision 提取的）
    confidence_result = _calculate_confidence(reports)
    if confidence_result and confidence_result.get("score", 0) > 0:
        result["置信度"] = confidence_result["score"]
        result["置信度详情"] = confidence_result.get("details", [])

    # 1b) 从 decision 字典提取价格类字段（与评级无关，独立提取）
    if isinstance(decision_obj, dict) and decision_obj:
        tp = decision_obj.get("target_price") or decision_obj.get("price_target")
        if tp is not None and tp != "":
            try:
                result["止盈目标"] = f"{round(float(tp), 2)} 元"
            except (TypeError, ValueError):
                result["止盈目标"] = str(tp)
        sl = decision_obj.get("stop_loss") or decision_obj.get("stop_loss_price")
        if sl is not None and sl != "":
            try:
                result["止损价格"] = f"{round(float(sl), 2)} 元"
            except (TypeError, ValueError):
                result["止损价格"] = str(sl)
        buy1 = decision_obj.get("ideal_buy") or decision_obj.get("buy_price")
        if buy1 is not None and buy1 != "":
            try:
                result["理想买入"] = f"{round(float(buy1), 2)} 元"
            except (TypeError, ValueError):
                result["理想买入"] = str(buy1)
        buy2 = decision_obj.get("second_buy")
        if buy2 is not None and buy2 != "":
            try:
                result["二次买入"] = f"{round(float(buy2), 2)} 元"
            except (TypeError, ValueError):
                result["二次买入"] = str(buy2)
        sup = decision_obj.get("support_level") or decision_obj.get("support")
        if sup is not None and sup != "":
            try:
                result["支撑位"] = f"{round(float(sup), 2)} 元"
            except (TypeError, ValueError):
                result["支撑位"] = str(sup)
        res_val = decision_obj.get("resistance_level") or decision_obj.get("resistance")
        if res_val is not None and res_val != "":
            try:
                result["阻力位"] = f"{round(float(res_val), 2)} 元"
            except (TypeError, ValueError):
                result["阻力位"] = str(res_val)

    # 价格字段和评分字段
    price_aliases = [
        (["理想买入"], "理想买入"),
        (["二次买入"], "二次买入"),
        (["止损价格", "止损位", "止损线"], "止损价格"),
        (["止盈目标", "目标价格", "目标价"], "止盈目标"),
        (["支撑位", "支撑"], "支撑位"),
        (["阻力位", "压力位"], "阻力位"),
    ]
    score_aliases = [
        (["置信度"], "置信度", None),
        (["风险等级"], "风险等级", None),
        (["技术面评分"], "技术面评分", "market_report"),
        (["基本面评分"], "基本面评分", "fundamentals_report"),
        (["情绪面评分"], "情绪面评分", "sentiment_report"),
        (["消息面评分"], "消息面评分", "news_report"),
        (["资金面评分"], "资金面评分", "hot_money_report"),
        (["政策面评分"], "政策面评分", "policy_report"),
        (["解禁面评分"], "解禁面评分", "lockup_report"),
    ]

    # 2b) 价格字段
    for aliases, field_name in price_aliases:
        if result.get(field_name):
            continue
        for module_text in _priority_texts():
            val = _match_price(module_text, aliases)
            if val and not result.get(field_name):
                result[field_name] = val
                break
        if field_name not in result:
            for v in reports.values():
                if isinstance(v, str):
                    val = _match_price(v, aliases)
                    if val:
                        result[field_name] = val
                        break

    # 2c) 评分/置信度/风险
    for aliases, field_name, primary_source in score_aliases:
        if result.get(field_name):
            continue
        # 优先从指定的主来源模块提取（确保评分来自对应分析师报告）
        if primary_source:
            primary_text = reports.get(primary_source)
            if isinstance(primary_text, str) and primary_text.strip():
                val = _match_score(primary_text, aliases)
                if val:
                    result[field_name] = val
                    continue
        # 再从高优先级模块提取
        for module_text in _priority_texts():
            val = _match_score(module_text, aliases)
            if val and not result.get(field_name):
                result[field_name] = val
                break
        if field_name not in result:
            for v in reports.values():
                if isinstance(v, str):
                    val = _match_score(v, aliases)
                    if val:
                        result[field_name] = val
                        break

    # 3) 最后从 combined_text 中尝试提取评级（例如 "1. 操作建议：买入"）
    if not result.get("评级"):
        combined_text = "\n".join(
            v for v in reports.values() if isinstance(v, str)
        )
        val = _match_rating(combined_text, ["操作建议", "评级", "投资建议", "建议", "行动评级"])
        if val:
            final_rating = _normalize_rating(val)
            result["评级"] = final_rating
            result["操作建议"] = final_rating
            result["action"] = final_rating

    # 4) 补充英文字段名兼容（便于前端老代码继续工作）
    if "止盈目标" in result:
        num = re.search(r"(\d+(?:\.\d+)?)", result["止盈目标"])
        if num:
            result["target_price"] = num.group(1)
    if "止损价格" in result:
        num = re.search(r"(\d+(?:\.\d+)?)", result["止损价格"])
        if num:
            result["stop_loss"] = num.group(1)

    # 5) 提取持仓者建议和空仓者建议（使用专门的提取函数）
    holder_modules = ["research_team_decision", "final_trade_decision", "trader_investment_plan", "investment_plan"]
    empty_modules = ["research_team_decision", "final_trade_decision", "trader_investment_plan", "investment_plan"]
    
    if not result.get("持仓者建议"):
        for key in holder_modules:
            module_text = reports.get(key)
            if isinstance(module_text, str):
                extracted = _extract_holder_empty_advice(module_text, "持仓者建议")
                if extracted:
                    result["持仓者建议"] = extracted
                    break
    
    if not result.get("空仓者建议"):
        for key in empty_modules:
            module_text = reports.get(key)
            if isinstance(module_text, str):
                extracted = _extract_holder_empty_advice(module_text, "空仓者建议")
                if extracted:
                    result["空仓者建议"] = extracted
                    break

    # 6) 多维度评分估算（技术面/基本面/情绪面/政策面/消息面/资金面/解禁面）
    #    如果已有明确评分则保留，否则基于报告倾向估算
    def _estimate_score_from_text(text: str) -> float | None:
        """基于文本的整体倾向估算评分（0-100分）"""
        if not text:
            return None
        bullish_words = [
            "看涨", "看好", "买入", "上涨", "上升", "突破", "利好", "强势", "多头", "机会",
            "bullish", "buy", "up", "rise", "gain", "breakout", "positive", "strong", "opportunity",
            "optimistic", "growth", "upgrade", "outperform", "overweight", "hold_buy"
        ]
        bearish_words = [
            "看跌", "看空", "卖出", "下跌", "下降", "破位", "利空", "弱势", "空头", "风险",
            "bearish", "sell", "down", "fall", "drop", "breakdown", "negative", "weak", "risk",
            "pessimistic", "decline", "downgrade", "underperform", "underweight", "hold_sell"
        ]
        text_lower = text.lower()
        bull_count = sum(1 for w in bullish_words if w.lower() in text_lower)
        bear_count = sum(1 for w in bearish_words if w.lower() in text_lower)
        if bull_count == 0 and bear_count == 0:
            return None
        diff = bull_count - bear_count
        if diff > 3:
            return 80.0
        elif diff > 0:
            return 70.0
        elif diff < -3:
            return 30.0
        elif diff < 0:
            return 40.0
        else:
            return 50.0

    def _parse_score_value(val: Any) -> float | None:
        """将评分值标准化为 0-100 分（百分制）"""
        if val is None or val == "":
            return None
        try:
            num = float(val)
            if 0 <= num <= 1:
                return round(num * 100, 1)
            elif 0 <= num <= 10:
                return round(num * 10, 1)
            elif 0 <= num <= 100:
                return round(num, 1)
            else:
                return None
        except (TypeError, ValueError):
            val_str = str(val).lower()
            if val_str in ["高", "较高", "强", "强势", "积极"]:
                return 80.0
            elif val_str in ["中", "中等", "中性", "一般"]:
                return 50.0
            elif val_str in ["低", "较低", "弱", "弱势", "消极"]:
                return 30.0
            return None

    dimension_config = [
        {
            "field": "技术面评分",
            "sources": ["market_report", "trader_investment_plan", "final_trade_decision", "investment_plan"],
            "analyst": "技术分析师",
            "basis": "基于技术指标（均线、KDJ、MACD、RSI等）、趋势形态、量价关系等综合评估，满分100分。分数越高表示技术形态越有利。"
        },
        {
            "field": "基本面评分",
            "sources": ["fundamentals_report", "bull_researcher", "bear_researcher", "research_team_decision", "final_trade_decision"],
            "analyst": "基本面分析师",
            "basis": "基于财务数据（营收、利润、ROE等）、行业地位、护城河、估值水平等综合评估，满分100分。分数越高表示基本面越健康。"
        },
        {
            "field": "情绪面评分",
            "sources": ["sentiment_report", "news_report", "hot_money_report", "bull_researcher", "final_trade_decision"],
            "analyst": "市场情绪分析师",
            "basis": "基于市场情绪指标、舆情热度、散户情绪逆向指标等综合评估，满分100分。分数越高表示市场情绪越积极。"
        },
        {
            "field": "消息面评分",
            "sources": ["news_report", "sentiment_report", "policy_report", "bull_researcher", "final_trade_decision"],
            "analyst": "新闻分析师",
            "basis": "基于公司公告、研报动态、新闻事件冲击、重要消息面影响等综合评估，满分100分。分数越高表示消息面越利好。"
        },
        {
            "field": "资金面评分",
            "sources": ["hot_money_report", "sentiment_report", "news_report", "trader_investment_plan", "final_trade_decision"],
            "analyst": "游资追踪师",
            "basis": "基于主力资金流向、龙虎榜数据、北向资金动向、机构持仓变化等综合评估，满分100分。分数越高表示资金面越充裕。"
        },
        {
            "field": "政策面评分",
            "sources": ["policy_report", "news_report", "bull_researcher", "research_team_decision", "final_trade_decision"],
            "analyst": "政策分析师",
            "basis": "基于产业政策、宏观调控、监管动向、行业利好/利空政策等综合评估，满分100分。分数越高表示政策环境越有利。"
        },
        {
            "field": "解禁面评分",
            "sources": ["lockup_report", "fundamentals_report", "news_report", "risk_control_decision", "final_trade_decision"],
            "analyst": "解禁追踪师",
            "basis": "基于限售股解禁规模、大股东减持计划、解禁压力与市场承接能力等综合评估，满分100分。分数越高表示解禁压力越小。"
        },
    ]

    dimension_details = []
    for dim in dimension_config:
        field_name = dim["field"]
        source_modules = dim["sources"]
        existing_val = result.get(field_name)
        parsed = _parse_score_value(existing_val)
        score = parsed
        source_type = "明确评分"
        if score is None:
            estimated = None
            for mod_key in source_modules:
                mod_text = reports.get(mod_key, "")
                if not (isinstance(mod_text, str) and mod_text.strip()):
                    continue
                # 跳过分析失败的错误报告
                if mod_text.strip().startswith("[分析失败") or mod_text.strip().startswith("[ERROR") or mod_text.strip().startswith("[error"):
                    continue
                est = _estimate_score_from_text(mod_text)
                if est is not None:
                    estimated = est
                    break
            # 如果所有来源都无法估算，使用整体评级作为兜底（50-75分区间，根据评级调整）
            if estimated is None:
                rating = result.get("评级", result.get("操作建议", ""))
                if rating == "买入":
                    estimated = 75.0
                    source_type = "整体评级推断"
                elif rating == "增持":
                    estimated = 70.0
                    source_type = "整体评级推断"
                elif rating == "持有":
                    estimated = 55.0
                    source_type = "整体评级推断"
                elif rating == "减持":
                    estimated = 40.0
                    source_type = "整体评级推断"
                elif rating == "卖出":
                    estimated = 30.0
                    source_type = "整体评级推断"
                else:
                    estimated = 50.0
                    source_type = "默认中性"
            if estimated is not None:
                score = estimated
                if source_type == "明确评分":
                    source_type = "估算评分"
        if score is not None:
            result[field_name] = score
            dimension_details.append({
                "name": field_name.replace("评分", ""),
                "field": field_name,
                "score": score,
                "max_score": 100,
                "analyst": dim["analyst"],
                "basis": dim["basis"],
                "source_type": source_type
            })

    result["维度评分详情"] = dimension_details

    # 仓位建议：当评级为"买入"时，自动调用 PositionSizer 计算"买多少"
    _inject_position_advice(result)

    return result


def _inject_position_advice(result: dict[str, Any]) -> None:
    """
    当评级为买入时，自动计算仓位建议并注入到 result 中。

    使用已抽取的"理想买入"或"支撑位"作为参考价格，
    账户大小默认10万元（散户标准账户），策略类型为 default。
    """
    action = result.get("评级") or result.get("操作建议") or result.get("action")
    if not action or "买入" not in str(action):
        return

    # 获取参考价格：优先用"理想买入"，其次"支撑位"，最后"二次买入"
    price_str = result.get("理想买入") or result.get("支撑位") or result.get("二次买入")
    if not price_str:
        return

    # 从字符串中提取数字（如 "10.70 元" -> 10.70）
    try:
        price_match = re.search(r"(\d+\.?\d*)", str(price_str))
        if not price_match:
            return
        price = float(price_match.group(1))
        if price <= 0:
            return
    except (ValueError, AttributeError):
        return

    try:
        from app.services.retail.position_sizer import StrategyType
        from app.services.retail.retail_strategy_service import get_retail_strategy_service

        service = get_retail_strategy_service()
        # 默认账户10万元，无持仓，default 策略
        advice = service.calculate_position(
            account_size=100000.0,
            holdings=[],
            symbol="",
            strategy=StrategyType.DEFAULT,
            price=price,
            win_rate=0.55,
            profit_loss_ratio=1.5,
        )
        result["仓位建议"] = advice.to_dict()
    except Exception as e:
        logger.warning(f"⚠️ 计算仓位建议失败: {e}")


def _calculate_confidence(reports: dict[str, Any]) -> dict[str, Any]:
    """
    基于多维度重新计算置信度（0-100分）
    
    维度：
    1. 数据完整性（30%）：分析师报告数量（最多7个）
    2. 多空一致性（25%）：看涨/看跌研究员的分歧程度
    3. 三方风控一致性（20%）：激进/中性/保守风控的一致性
    4. 数据来源丰富度（15%）：数据来源对照表记录数
    5. 最终决策明确性（10%）：最终决策是否清晰明确
    
    返回：
    {
        "score": 75.5,  # 总分
        "details": [     # 各维度详情
            {"name": "数据完整性", "score": 30, "max_score": 30, "description": "7个分析师报告全部生成"},
            ...
        ]
    }
    """
    if not isinstance(reports, dict) or not reports:
        return {"score": 0.0, "details": []}

    total_score = 0.0
    details = []

    # ===== 1. 数据完整性（30%）=====
    module_layers = [
        ("基础分析层", [
            "market_report", "fundamentals_report", "sentiment_report",
            "news_report", "policy_report", "hot_money_report", "lockup_report"
        ]),
        ("研究辩论层", ["bull_researcher", "bear_researcher", "research_team_decision"]),
        ("风控评估层", ["risky_analyst", "neutral_analyst", "safe_analyst", "risk_control_decision"]),
        ("交易决策层", ["trader_investment_plan", "final_trade_decision"]),
    ]
    total_modules = sum(len(mods) for _, mods in module_layers)
    completed_modules = 0
    layer_details = []
    for layer_name, mods in module_layers:
        layer_count = sum(
            1 for k in mods
            if k in reports and isinstance(reports[k], str) and reports[k].strip()
        )
        completed_modules += layer_count
        layer_details.append(f"{layer_name}{layer_count}/{len(mods)}")
    
    completion_rate = completed_modules / total_modules if total_modules > 0 else 0
    if completion_rate >= 0.9:
        score = 30
        desc = f"报告生成完整（{completed_modules}/{total_modules}），{'，'.join(layer_details)}，数据覆盖全面"
    elif completion_rate >= 0.75:
        score = 25
        desc = f"报告较完整（{completed_modules}/{total_modules}），{'，'.join(layer_details)}，数据较充分"
    elif completion_rate >= 0.6:
        score = 20
        desc = f"报告基本完整（{completed_modules}/{total_modules}），{'，'.join(layer_details)}，数据基本够用"
    elif completion_rate >= 0.4:
        score = 15
        desc = f"报告部分缺失（{completed_modules}/{total_modules}），{'，'.join(layer_details)}，数据覆盖有限"
    else:
        score = 10
        desc = f"报告缺失较多（{completed_modules}/{total_modules}），{'，'.join(layer_details)}，数据完整性较低"
    total_score += score
    details.append({
        "name": "数据完整性",
        "score": score,
        "max_score": 30,
        "description": desc
    })

    # ===== 2. 分析师一致性（25%）=====
    # 基于7位基础分析师的评级方向一致性来评估，而不是多空研究员（多空本来就该有分歧）
    analyst_modules = [
        "market_report", "fundamentals_report", "sentiment_report",
        "news_report", "policy_report", "hot_money_report", "lockup_report"
    ]

    def _rating_direction_from_text(text: str) -> int | None:
        if not text:
            return None
        rating = _match_rating(text, ["操作建议", "评级", "投资建议", "建议", "行动评级", "执行评级", "最终结论", "核心观点", "结论"])
        if rating:
            if "强烈买入" in rating or "买入" in rating or "加仓" in rating or "增持" in rating or "看多" in rating or "看涨" in rating:
                return 1
            if "强烈卖出" in rating or "卖出" in rating or "减仓" in rating or "减持" in rating or "看空" in rating or "看跌" in rating or "清仓" in rating:
                return -1
            if "持有" in rating or "观望" in rating or "中性" in rating:
                return 0
        bull_keywords = ["建议买入", "推荐买入", "给予买入", "买入评级", "增持评级", "看多", "看涨", "建议增持", "看好"]
        bear_keywords = ["建议卖出", "推荐卖出", "给予卖出", "卖出评级", "减持评级", "看空", "看跌", "建议减持", "清仓", "谨慎"]
        neutral_keywords = ["建议持有", "持有评级", "观望", "中性评级", "建议观望", "中性"]
        if any(kw in text for kw in bull_keywords):
            return 1
        if any(kw in text for kw in bear_keywords):
            return -1
        if any(kw in text for kw in neutral_keywords):
            return 0
        return None

    analyst_directions = []
    for mod in analyst_modules:
        text = reports.get(mod, "")
        if isinstance(text, str) and text.strip():
            direction = _rating_direction_from_text(text)
            if direction is not None:
                analyst_directions.append(direction)

    if len(analyst_directions) == 0:
        score = 8
        desc = "无法获取分析师评级方向，无法评估一致性"
    else:
        bull_count = sum(1 for d in analyst_directions if d == 1)
        bear_count = sum(1 for d in analyst_directions if d == -1)
        neutral_count = sum(1 for d in analyst_directions if d == 0)
        total = len(analyst_directions)
        max_count = max(bull_count, bear_count, neutral_count)
        agreement_rate = max_count / total

        if agreement_rate >= 0.8:
            score = 25
            desc = f"{total}位分析师观点高度一致（{bull_count}多/{neutral_count}中/{bear_count}空），可信度高"
        elif agreement_rate >= 0.6:
            score = 20
            desc = f"{total}位分析师观点较一致（{bull_count}多/{neutral_count}中/{bear_count}空），可信度较好"
        elif agreement_rate >= 0.4:
            score = 14
            desc = f"{total}位分析师存在一定分歧（{bull_count}多/{neutral_count}中/{bear_count}空），需综合判断"
        else:
            score = 8
            desc = f"{total}位分析师分歧较大（{bull_count}多/{neutral_count}中/{bear_count}空），需谨慎参考"
    total_score += score
    details.append({
        "name": "分析师一致性",
        "score": score,
        "max_score": 25,
        "description": desc
    })

    # ===== 3. 三方风控一致性（20%）=====
    risky_text = reports.get("risky_analyst", "")
    neutral_text = reports.get("neutral_analyst", "")
    safe_text = reports.get("safe_analyst", "")

    has_risky = bool(isinstance(risky_text, str) and risky_text.strip())
    has_neutral = bool(isinstance(neutral_text, str) and neutral_text.strip())
    has_safe = bool(isinstance(safe_text, str) and safe_text.strip())

    risk_count = sum([has_risky, has_neutral, has_safe])

    def _extract_risk_level(text: str) -> str | None:
        if not text:
            return None
        val = _match_score(text, ["风险等级", "风险评级", "风险评估", "风险级别"])
        if val:
            val_str = str(val).lower()
            if "高" in val_str or "high" in val_str:
                return "high"
            if "低" in val_str or "low" in val_str:
                return "low"
            if "中" in val_str or "medium" in val_str or "中等" in val_str:
                return "medium"
        high_keywords = ["高风险", "风险高", "风险较大", "风险很高", "高风险等级", "风险等级高"]
        low_keywords = ["低风险", "风险低", "风险较小", "风险很低", "低风险等级", "风险等级低"]
        medium_keywords = ["中风险", "中等风险", "风险适中", "风险一般", "中性风险", "风险中等"]
        if any(kw in text for kw in high_keywords):
            return "high"
        if any(kw in text for kw in low_keywords):
            return "low"
        if any(kw in text for kw in medium_keywords):
            return "medium"
        return None

    if risk_count == 0:
        score = 0
        desc = "无风控报告"
    elif risk_count == 1:
        score = 5
        desc = "仅1个风控视角，参考价值有限"
    else:
        risky_level = _extract_risk_level(risky_text) if has_risky else None
        neutral_level = _extract_risk_level(neutral_text) if has_neutral else None
        safe_level = _extract_risk_level(safe_text) if has_safe else None

        levels = [lv for lv in [risky_level, neutral_level, safe_level] if lv is not None]

        if len(levels) <= 1:
            score = 5 if risk_count == 1 else 15
            desc = f"{risk_count}个风控报告，但风险等级不明确"
        else:
            risk_score_map = {"low": 0, "medium": 1, "high": 2}
            level_names = {"low": "低风险", "medium": "中风险", "high": "高风险"}
            numeric_levels = [risk_score_map.get(lv, 1) for lv in levels]
            max_diff = max(numeric_levels) - min(numeric_levels)
            level_strs = [level_names.get(lv, lv) for lv in levels]

            if risk_count == 3:
                if max_diff <= 1:
                    score = 20
                    desc = f"三方风控观点一致（{'/'.join(level_strs)}），风险评估可靠"
                else:
                    score = 12
                    desc = f"三方风控存在合理分歧（{'/'.join(level_strs)}），体现了不同风险偏好视角的差异，属正常现象"
            else:
                if max_diff <= 1:
                    score = 15
                    desc = f"双方风控观点一致（{'/'.join(level_strs)}），风险评估较可靠"
                else:
                    score = 10
                    desc = f"双方风控存在分歧（{'/'.join(level_strs)}），需谨慎参考"
    total_score += score
    details.append({
        "name": "风控一致性",
        "score": score,
        "max_score": 20,
        "description": desc
    })

    # ===== 4. 数据来源丰富度（15%）=====
    analyst_modules = [
        "market_report", "fundamentals_report", "sentiment_report",
        "news_report", "policy_report", "hot_money_report", "lockup_report"
    ]
    
    total_data_points = 0
    valid_modules = 0
    total_chars = 0
    
    for mod in analyst_modules:
        text = reports.get(mod, "")
        if isinstance(text, str) and text.strip() and len(text.strip()) > 100:
            valid_modules += 1
            total_chars += len(text)
            
            data_point_count = 0
            data_point_count += len(re.findall(r'\d+\.?\d*%', text))
            data_point_count += len(re.findall(r'[\u4e00-\u9fa5]*价[格位]?[：:]\s*\d+\.?\d*', text))
            data_point_count += len(re.findall(r'\d+\.?\d*\s*元', text))
            data_point_count += len(re.findall(r'市盈率|市净率|ROE|毛利率|净利率|营收|净利润|增长率|换手率|成交量|成交额|涨跌幅', text))
            data_point_count += len(re.findall(r'[一二三四五六七八九十\d]+[日周月季年]', text))
            data_point_count += len(re.findall(r'数据来源|来自|根据|据|统计显示', text))
            
            total_data_points += max(data_point_count, 5)
    
    avg_chars_per_module = int(total_chars / valid_modules) if valid_modules > 0 else 0
    
    if total_data_points >= 100 and valid_modules >= 6 and avg_chars_per_module >= 2000:
        score = 15
        desc = f"数据丰富（约{total_data_points}个指标，{valid_modules}个分析模块），信息密度高，支撑充分"
    elif total_data_points >= 60 and valid_modules >= 5 and avg_chars_per_module >= 1500:
        score = 12
        desc = f"数据较丰富（约{total_data_points}个指标，{valid_modules}个分析模块），支撑较好"
    elif total_data_points >= 30 and valid_modules >= 4:
        score = 9
        desc = f"数据一般（约{total_data_points}个指标，{valid_modules}个分析模块），支撑有限"
    elif total_data_points >= 10 and valid_modules >= 2:
        score = 6
        desc = f"数据较少（约{total_data_points}个指标，{valid_modules}个分析模块），支撑不足"
    else:
        score = 3
        desc = f"数据匮乏（约{total_data_points}个指标，{valid_modules}个分析模块），需谨慎参考"
    total_score += score
    details.append({
        "name": "数据丰富度",
        "score": score,
        "max_score": 15,
        "description": desc
    })

    # ===== 5. 决策明确性（10%）=====
    final_modules = ["final_trade_decision", "trader_investment_plan", "research_team_decision", "investment_plan"]
    final_text = ""
    for key in final_modules:
        t = reports.get(key, "")
        if isinstance(t, str) and t.strip():
            final_text = t
            break

    if final_text:
        clarity_score = 0
        clarity_items = []

        rating_aliases = ["操作建议", "评级", "投资建议", "建议", "行动评级", "执行评级", "最终决策", "决策", "最终投资评级", "投资评级"]
        rating_val = _match_rating(final_text, rating_aliases)
        if rating_val:
            clarity_score += 3
            clarity_items.append("明确评级")
        else:
            if any(kw in final_text for kw in ["买入", "卖出", "持有", "增持", "减持", "清仓", "建仓"]):
                clarity_score += 2
                clarity_items.append("有决策方向")

        tp_aliases = ["止盈目标", "目标价格", "目标价", "目标价位", "止盈价位", "止盈价"]
        tp_val = _match_price(final_text, tp_aliases)
        if tp_val:
            clarity_score += 2
            clarity_items.append("目标价")

        sl_aliases = ["止损价格", "止损位", "止损线", "止损价位", "硬止损", "止损价"]
        sl_val = _match_price(final_text, sl_aliases)
        if sl_val:
            clarity_score += 2
            clarity_items.append("止损位")

        buy_aliases = ["理想买入", "买入价位", "建仓价", "买入价", "建仓价位", "二次买入"]
        buy_val = _match_price(final_text, buy_aliases)
        if buy_val:
            clarity_score += 1
            clarity_items.append("买入点")

        position_keywords = ["仓位", "建议仓位", "仓位比例", "仓位上限", "仓位建议"]
        has_position = False
        for kw in position_keywords:
            if kw in final_text and re.search(r'\d', final_text[max(0, final_text.find(kw)-20):final_text.find(kw)+50]):
                has_position = True
                break
        if has_position:
            clarity_score += 1
            clarity_items.append("仓位建议")
        elif "仓位" in final_text:
            clarity_score += 0.5
            clarity_items.append("仓位参考")

        clarity_score = min(clarity_score, 10)
        
        if clarity_score >= 8:
            score = 10
            desc = f"决策非常明确（{'+'.join(clarity_items)}），可操作性强"
        elif clarity_score >= 6:
            score = 8
            desc = f"决策较明确（{'+'.join(clarity_items)}），可操作性较好"
        elif clarity_score >= 4:
            score = 6
            desc = f"决策基本明确（{'+'.join(clarity_items)}），可操作性一般"
        elif clarity_score >= 2:
            score = 4
            desc = f"决策不够完整（{'+'.join(clarity_items)}），可操作性有限"
        else:
            score = 2
            desc = "决策信息不足，参考价值有限"
    else:
        score = 1
        desc = "缺少最终决策报告"
    total_score += score
    details.append({
        "name": "决策明确性",
        "score": score,
        "max_score": 10,
        "description": desc
    })

    final_score = round(min(max(total_score, 0.0), 100.0), 1)
    return {
        "score": final_score,
        "details": details
    }


def recompute_confidence(result_data: dict[str, Any]) -> dict[str, Any]:
    """根据 result_data 中的 reports 用当前算法重算置信度，修正历史入库的陈旧/错误值。

    历史分析任务入库时可能由旧版算法或结构不匹配计算出异常低的置信度（如 0.02），
    而当前算法对同一批完整报告可得到合理分数。读取时用当前算法重算，保证展示与算法一致。
    同时补充从 reports 提取的维度评分（技术面/基本面/情绪面/消息面/资金面/政策面/解禁面），
    供前端短线博弈/长线博弈各面分数展示。
    """
    if not isinstance(result_data, dict):
        return result_data
    reports = result_data.get("reports")
    if not isinstance(reports, dict) or not reports:
        return result_data
    conf = _calculate_confidence(reports)
    if conf:
        result_data["confidence_score"] = conf.get("score", result_data.get("confidence_score", 0.0))
        result_data["置信度详情"] = conf.get("details", [])
    # 补充维度评分（历史结果可能缺失，从 reports 现算）
    try:
        extracted = extract_structured_fields(reports)
        for field in ("技术面评分", "基本面评分", "情绪面评分", "消息面评分", "资金面评分", "政策面评分", "解禁面评分", "维度评分详情"):
            val = extracted.get(field)
            if val is not None and not result_data.get(field):
                result_data[field] = val
    except Exception:
        pass
    return result_data


def _match_rating(text: str, aliases: list[str]) -> str | None:
    """
    从文本中抽取"操作建议/评级"的关键字（买入/持有/卖出等）。
    优先级：精确匹配标题行（含下一行内容）> 标题行带冒号 > 研究经理结论搜索 > 关键词搜索
    """
    if not text:
        return None

    # 0) 最高优先级：匹配"最终定性评级"、"最终评级"等明确的最终结论格式
    # 注意：支持匹配带空白的评级（如"卖出 / 规避"），使用 .+? 非贪婪匹配
    highest_priority_patterns = [
        r"(?:^|\n)\s*\*+\s*最终定性评级\s*[:：]\s*(.+?)\s*\*+\s*$",
        r"(?:^|\n)\s*\*+\s*最终评级\s*[:：]\s*(.+?)\s*\*+\s*$",
        r"(?:^|\n)\s*\*+\s*最终投资评级\s*[:：]\s*(.+?)\s*\*+\s*$",
        r"(?:^|\n)\s*最终定性评级\s*[:：]\s*(.+?)(?:\s|\*|$)",
        r"(?:^|\n)\s*最终评级\s*[:：]\s*(.+?)(?:\s|\*|$)",
        # 兼容不带**的格式：**最终评级：卖出 / 规避**
        r"\*\*最终评级[：:]\s*(.+?)\s*\*\*",
        r"最终评级[：:]\s*([^\n]{1,30})",
    ]
    for pattern in highest_priority_patterns:
        try:
            m = re.search(pattern, text)
            if m:
                val = m.group(1).strip()
                val = re.sub(r'[\*_#\s]+', '', val).strip()
                if val and 0 < len(val) <= 20:
                    return val
        except re.error:
            continue

    # 0.5) 最可靠的格式：**数字. 操作建议** 后面跟换行后的内容
    #    例：**7. 操作建议**\n买入  或  **操作建议**\n强烈卖出
    for alias in aliases:
        patterns = [
            # 格式1：**7. 操作建议** 后换行跟评级词
            r"(?:^|\n)\s*\*\*\s*(?:\d+[\.、]\s*)?" + re.escape(alias) + r"\s*\*\*\s*[\r\n]+\s*([^\s，。；,;（(【【\*\#]{1,30})",
            # 格式2：**操作建议：**买入 （星号内带冒号）
            r"(?:^|\n)\s*\*\*\s*(?:\d+[\.、]\s*)?" + re.escape(alias) + r"\s*[:：]\s*\*\*\s*([^\s，。；,;（(]{1,30})",
            # 格式3：**7. 操作建议：** 强烈买入
            r"(?:^|\n)\s*\*\*\s*(?:\d+[\.、]\s*)?" + re.escape(alias) + r"[:：]\s*\*\*\s*([^\s，。；,;（(]{1,30})",
        ]
        for pattern in patterns:
            try:
                m = re.search(pattern, text)
                if m:
                    val = m.group(1).strip()
                    val = re.sub(r'[\*_#\s]+', '', val).strip()
                    if val and 0 < len(val) <= 20:
                        return val
            except re.error:
                continue

    # 1) 标题行带冒号的格式
    for alias in aliases:
        patterns = [
            r"(?:^|\n)\s*\*?\s*(?:\d+[\.、]\s*)?\*?\s*" + re.escape(alias) +
            r"\s*\*?\s*[:：]\s*([^\n，。；,;（(]{0,60})",
            r"(?:^|\n)\s*【" + re.escape(alias) + r"】\s*([^\n，。；,;（(]{0,60})",
            r"(?:^|\n)\s*\*\*" + re.escape(alias) + r"\*\*\s*[:：]\s*([^\n，。；,;（(]{0,60})",
            # 🔥 新增：**决策**：**卖出 (利用反弹减仓)** 格式（两个独立的**块，支持括号和空格）
            r"(?:^|\n)\s*\*\*" + re.escape(alias) + r"\*\*\s*[:：]\s*\*\*\s*([^\*]{1,60})\s*\*\*",
        ]
        for pattern in patterns:
            try:
                m = re.search(pattern, text)
                if m:
                    val = m.group(1).strip()
                    if val:
                        val = re.sub(r'[\*_#]+', '', val).strip()
                        if len(val) <= 20:
                            return val
                        # 如果内容太长，提取其中的评级关键词
                        for kw in ["强烈买入", "强烈卖出", "买入", "卖出", "持有", "观望", "减仓", "加仓"]:
                            if kw in val:
                                return kw
            except re.error:
                continue

    # 2) 搜索研究经理/最终决策中的结论
    # 注意：关键词顺序很重要，长的优先，且"卖出/减持"优先于"买入/增持"避免误匹配
    en_keywords = r"强烈卖出|强烈买入|卖出|减持|买入|增持|持有|观望|减仓|加仓|Strong Sell|Strong Buy|Underweight|Overweight|Sell|Buy|Hold|Neutral"
    manager_patterns = [
        r"最终定性评级[\s\S]{0,100}?(" + en_keywords + r")",
        r"定性评级[\s\S]{0,100}?(" + en_keywords + r")",
        r"研究经理.*结论[\s\S]{0,200}?(" + en_keywords + r")",
        r"最终决策[\s\S]{0,200}?(" + en_keywords + r")",
        r"最终投资决策[\s\S]{0,200}?(" + en_keywords + r")",
        r"总体裁决[\s\S]{0,200}?(" + en_keywords + r")",
        r"最终决定[\s\S]{0,200}?(" + en_keywords + r")",
        r"综合判断[\s\S]{0,100}?(" + en_keywords + r")",
        r"综合评估[\s\S]{0,100}?(" + en_keywords + r")",
        r"投资建议[\s\S]{0,100}?(" + en_keywords + r")",
        r"维持[\s\S]{0,10}?(" + en_keywords + r")",
    ]

    for pattern in manager_patterns:
        try:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        except re.error:
            continue

    # 3) 搜索明确的结论行
    conclusion_patterns = [
        r"(?:^|\n)\s*\*?结论\s*\*?[:：]\s*([^\n]{0,80})",
        r"(?:^|\n)\s*\*?总结\s*\*?[:：]\s*([^\n]{0,80})",
    ]

    all_rating_keywords = ["强烈买入", "强烈卖出", "买入", "卖出", "持有", "观望", "减仓", "加仓",
                           "Strong Buy", "Strong Sell", "Overweight", "Underweight", "Buy", "Sell", "Hold", "Neutral"]

    for pattern in conclusion_patterns:
        try:
            m = re.search(pattern, text)
            if m:
                val = m.group(1).strip()
                if val:
                    for keyword in all_rating_keywords:
                        if keyword.lower() in val.lower():
                            return keyword
        except re.error:
            continue

    # 4) 兜底：从文本中搜索评级词（优先匹配完整词）
    keywords = all_rating_keywords
    for keyword in keywords:
        pattern = r'(?:^|\s|[，。；！？\n])' + re.escape(keyword) + r'(?:$|\s|[，。；！？\n])'
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return keyword
        except re.error:
            continue

    return None


# 股票名称缓存
_stock_name_cache = {}

def get_stock_name(stock_code: str) -> str:
    """
    获取股票名称
    优先级：缓存 -> MongoDB（按数据源优先级） -> 默认返回股票代码
    """
    global _stock_name_cache

    # 检查缓存
    if stock_code in _stock_name_cache:
        return _stock_name_cache[stock_code]

    try:
        # 从 MongoDB 获取股票名称
        from ..core.database import get_mongo_db_sync
        from ..core.unified_config import UnifiedConfigManager

        db = get_mongo_db_sync()
        code6 = str(stock_code).zfill(6)

        # 🔥 按数据源优先级查询
        config = UnifiedConfigManager()
        data_source_configs = config.get_data_source_configs()

        # 提取启用的数据源，按优先级排序
        enabled_sources = [
            ds.type.lower() for ds in data_source_configs
            if ds.enabled and ds.type.lower() in ['tushare', 'akshare', 'baostock']
        ]

        if not enabled_sources:
            enabled_sources = ['tushare', 'akshare', 'baostock']

        # 按数据源优先级查询
        stock_info = None
        for data_source in enabled_sources:
            stock_info = db.stock_basic_info.find_one(
                {"$or": [{"symbol": code6}, {"code": code6}], "source": data_source}
            )
            if stock_info:
                logger.debug(f"✅ 使用数据源 {data_source} 获取股票名称 {code6}")
                break

        # 如果所有数据源都没有，尝试不带 source 条件查询（兼容旧数据）
        if not stock_info:
            stock_info = db.stock_basic_info.find_one(
                {"$or": [{"symbol": code6}, {"code": code6}]}
            )
            if stock_info:
                logger.warning(f"⚠️ 使用旧数据（无 source 字段）获取股票名称 {code6}")

        if stock_info and stock_info.get("name"):
            stock_name = stock_info["name"]
            _stock_name_cache[stock_code] = stock_name
            return stock_name

        # 如果没有找到，返回股票代码
        _stock_name_cache[stock_code] = stock_code
        return stock_code

    except Exception as e:
        logger.warning(f"⚠️ 获取股票名称失败 {stock_code}: {e}")
        return stock_code


# 统一构建报告查询：支持 _id(ObjectId) / analysis_id / task_id 三种
def _build_report_query(report_id: str) -> dict[str, Any]:
    ors = [
        {"analysis_id": report_id},
        {"task_id": report_id},
    ]
    try:
        from bson import ObjectId
        ors.append({"_id": ObjectId(report_id)})
    except Exception:
        pass
    return {"$or": ors}

router = APIRouter(prefix="/api/reports", tags=["reports"])

class ReportFilter(BaseModel):
    """报告筛选参数"""
    search_keyword: str | None = None
    market_filter: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    stock_code: str | None = None
    report_type: str | None = None

class ReportListResponse(BaseModel):
    """报告列表响应"""
    reports: list[dict[str, Any]]
    total: int
    page: int
    page_size: int

@router.get("/list", response_model=dict[str, Any])
async def get_reports_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search_keyword: str | None = Query(None, description="搜索关键词"),
    market_filter: str | None = Query(None, description="市场筛选（A股/港股/美股）"),
    start_date: str | None = Query(None, description="开始日期"),
    end_date: str | None = Query(None, description="结束日期"),
    stock_code: str | None = Query(None, description="股票代码"),
    user: dict = Depends(get_current_user)
):
    """获取分析报告列表"""
    try:
        logger.info(f"🔍 获取报告列表: 用户={user['id']}, 页码={page}, 每页={page_size}, 市场={market_filter}")

        db = get_mongo_db()

        # 构建查询条件
        query = {}

        # 搜索关键词
        if search_keyword:
            query["$or"] = [
                {"stock_symbol": {"$regex": search_keyword, "$options": "i"}},
                {"analysis_id": {"$regex": search_keyword, "$options": "i"}},
                {"summary": {"$regex": search_keyword, "$options": "i"}}
            ]

        # 市场筛选
        if market_filter:
            query["market_type"] = market_filter

        # 股票代码筛选
        if stock_code:
            query["stock_symbol"] = stock_code

        # 日期范围筛选
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["analysis_date"] = date_query

        logger.info(f"📊 查询条件: {query}")

        # 计算总数
        total = await db.analysis_reports.count_documents(query)

        # 分页查询
        skip = (page - 1) * page_size
        cursor = db.analysis_reports.find(query).sort("created_at", -1).skip(skip).limit(page_size)

        # 先收集所有文档，不做耗时的数据库查询
        raw_docs = []
        stock_codes_to_lookup = set()
        async for doc in cursor:
            raw_docs.append(doc)

            # 收集需要查询的股票代码
            stock_code_item = doc.get("stock_symbol", "")
            stock_name_item = doc.get("stock_name", "")
            if not stock_name_item or stock_name_item == stock_code_item:
                stock_codes_to_lookup.add(stock_code_item)

            # 收集 reports 中可能有的股票代码
            reports_data = doc.get("reports", {})
            if isinstance(reports_data, dict):
                for _k, v in reports_data.items():
                    if isinstance(v, str) and len(v) > 50:
                        codes_in_text = re.findall(r'\b\d{6}\b', v)
                        for code in codes_in_text:
                            if 6 <= len(code) <= 10:
                                stock_codes_to_lookup.add(code)

        # 🔥 批量查询股票名称（性能优化：将 N 次查询合并为 1 次）
        code_to_name = {}
        if stock_codes_to_lookup:
            code6_list = [str(code).zfill(6) for code in stock_codes_to_lookup]
            cursor = db.stock_basic_info.find(
                {"$or": [{"symbol": {"$in": code6_list}}, {"code": {"$in": code6_list}}]},
                {"symbol": 1, "code": 1, "name": 1}
            )
            async for info in cursor:
                code = info.get("symbol") or info.get("code", "")
                name = info.get("name", "")
                if code and name:
                    code_to_name[code.zfill(6)] = name
                    code_to_name[code] = name

        # 处理每个报告
        reports = []
        for doc in raw_docs:
            stock_code_item = doc.get("stock_symbol", "")
            stock_name_item = doc.get("stock_name", "")
            code6 = str(stock_code_item).zfill(6)

            # 股票名称：优先用批量查询结果，其次用 MongoDB 缓存
            stock_name = code_to_name.get(code6) or code_to_name.get(stock_code_item, "")
            if not stock_name or stock_name == stock_code_item:
                stock_name = get_stock_name(stock_code_item)

            # 市场类型
            code_str = str(stock_code_item).strip()
            if code_str.isdigit() or code_str.endswith(".SH") or code_str.endswith(".SZ"):
                market_type = "A股"
            elif "." in code_str and not code_str.startswith(tuple("0123456789")):
                market_type = "美股"
            else:
                market_type = "A股"

            # 创建时间
            created_at = doc.get("created_at", now_tz())
            created_at_tz = to_config_tz(created_at)

            # 决策建议：列表页简化提取，避免完整结构化解析以提升性能
            action = ""
            reports_dict = doc.get("reports", {}) if isinstance(doc.get("reports"), dict) else {}
            _decision = doc.get("decision") or doc.get("detailed_analysis") or doc.get("final_decision") or doc.get("state") or {}
            
            # 🔥 优先从报告文本提取（final_trade_decision 最权威），再回退到 decision 对象
            if reports_dict:
                for key in ["final_trade_decision", "trader_investment_plan", "research_team_decision"]:
                    text = reports_dict.get(key, "")
                    if text:
                        rating = _match_rating(text, ["决策", "操作建议", "评级", "投资建议"])
                        if rating:
                            action = _normalize_rating(rating)
                            break
            # 如果报告文本中未提取到，再从 decision 对象提取
            if not action and isinstance(_decision, dict) and _decision:
                action = _normalize_rating(_decision.get("action", ""))

            # 置信度：直接从数据库字段获取，转换为百分比（0-100）
            confidence_score = doc.get("confidence_score", 0.0)
            try:
                conf_val = float(confidence_score) if confidence_score else 0.0
                if 0 < conf_val <= 1:
                    confidence_percent = round(conf_val * 100, 1)
                elif 0 < conf_val <= 100:
                    confidence_percent = round(conf_val, 1)
                else:
                    confidence_percent = 0.0
            except (TypeError, ValueError):
                confidence_percent = 0.0

            report = {
                "id": str(doc["_id"]),
                "analysis_id": doc.get("analysis_id", ""),
                "title": f"{stock_name}({stock_code_item}) 分析报告",
                "stock_code": stock_code_item,
                "stock_name": stock_name,
                "market_type": market_type,
                "action": action,
                "confidence": confidence_percent,
                "confidence_score": confidence_percent,
                "created_at": created_at_tz.isoformat() if created_at_tz else str(created_at),
                "analysis_date": doc.get("analysis_date", ""),
                "summary": doc.get("summary", ""),
                "source": doc.get("source", "unknown"),
                "task_id": doc.get("task_id", "")
            }
            reports.append(report)

        logger.info(f"✅ 查询完成: 总数={total}, 返回={len(reports)}")

        return {
            "success": True,
            "data": {
                "reports": reports,
                "total": total,
                "page": page,
                "page_size": page_size
            },
            "message": "报告列表获取成功"
        }

    except Exception as e:
        logger.error(f"❌ 获取报告列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{report_id}/detail")
async def get_report_detail(
    report_id: str,
    user: dict = Depends(get_current_user)
):
    """获取报告详情"""
    try:
        logger.info(f"🔍 获取报告详情: {report_id}")

        db = get_mongo_db()

        # 支持 ObjectId / analysis_id / task_id
        query = _build_report_query(report_id)
        doc = await db.analysis_reports.find_one(query)

        if not doc:
            # 兜底：从 analysis_tasks.result 中还原报告详情
            logger.info(f"⚠️ 未在analysis_reports找到，尝试从analysis_tasks还原: {report_id}")
            tasks_doc = await db.analysis_tasks.find_one(
                {"$or": [{"task_id": report_id}, {"result.analysis_id": report_id}]},
                {"result": 1, "task_id": 1, "stock_code": 1, "created_at": 1, "completed_at": 1}
            )
            if not tasks_doc or not tasks_doc.get("result"):
                raise HTTPException(status_code=404, detail="报告不存在")

            r = tasks_doc["result"] or {}
            created_at = tasks_doc.get("created_at")
            updated_at = tasks_doc.get("completed_at") or created_at

            # 转换时区：数据库中是 UTC 时间，转换为 UTC+8
            created_at_tz = to_config_tz(created_at)
            updated_at_tz = to_config_tz(updated_at)

            def to_iso(x):
                if hasattr(x, "isoformat"):
                    return x.isoformat()
                return x or ""

            stock_symbol = r.get("stock_symbol", r.get("stock_code", tasks_doc.get("stock_code", "")))
            stock_name = r.get("stock_name")
            # 🔥 如果 stock_name 缺失或等于股票代码（错误数据），重新获取
            if not stock_name or stock_name == stock_symbol:
                stock_name = get_stock_name(stock_symbol)

            report = {
                "id": tasks_doc.get("task_id", report_id),
                "analysis_id": r.get("analysis_id", ""),
                "stock_symbol": stock_symbol,
                "stock_name": stock_name,  # 🔥 添加股票名称字段
                "model_info": r.get("model_info", "Unknown"),  # 🔥 添加模型信息字段
                "analysis_date": r.get("analysis_date", ""),
                "status": r.get("status", "completed"),
                "created_at": to_iso(created_at_tz),
                "updated_at": to_iso(updated_at_tz),
                "analysts": r.get("analysts", []),
                "summary": r.get("summary", ""),
                "reports": r.get("reports", {}),
                "source": "analysis_tasks",
                "task_id": tasks_doc.get("task_id", report_id),
                "recommendation": r.get("recommendation", ""),
                "confidence_score": r.get("confidence_score", 0.0),
                "risk_level": r.get("risk_level", "中等"),
                "key_points": r.get("key_points", []),
                "execution_time": r.get("execution_time", 0),
                "tokens_used": r.get("tokens_used", 0)
            }
            # 🔥 合并顶层的 decision/detailed_analysis 到 reports，便于统一抽取
            _decision = r.get("decision") or r.get("detailed_analysis") or r.get("final_decision")
            _combined_for_extract = dict(report["reports"])
            if isinstance(_decision, dict) and _decision:
                _combined_for_extract["decision"] = _decision
            # 🔥 清理所有文本报告，移除开头的思考过程、寒暄语等
            _cleaned_reports = {}
            for _k, _v in report["reports"].items():
                if isinstance(_v, str):
                    _cleaned_reports[_k] = _clean_report_text(_v)
                else:
                    _cleaned_reports[_k] = _v
            report["reports"] = _cleaned_reports
            # 🔥 从 markdown 子报告中抽取结构化字段（核心洞察、策略点位等）
            _extracted = extract_structured_fields(_combined_for_extract)
            # 🔥 关键修复：提取出的结构化字段（尤其是 action/评级/操作建议）始终覆盖已有值
            # 因为报告文本中的决策是最权威的，数据库顶层的字段可能是旧的或错误的
            for _k, _v in _extracted.items():
                if _v is not None:
                    report[_k] = _v

            # 🔥 计算置信度详情（多维度评分依据）
            try:
                _confidence_result = _calculate_confidence(_combined_for_extract)
                if _confidence_result and _confidence_result.get("score"):
                    report["confidence_score"] = _confidence_result["score"]
                    report["置信度详情"] = _confidence_result["details"]
                    logger.info(f"🎯 [报告详情] 计算置信度得分: {_confidence_result['score']}")
            except Exception as _conf_err:
                logger.warning(f"⚠️ [报告详情] 计算置信度失败: {_conf_err}")
        else:
            # 转换为详细格式（analysis_reports 命中）
            stock_symbol = doc.get("stock_symbol", "")
            stock_name = doc.get("stock_name")
            # 🔥 如果 stock_name 缺失或等于股票代码（错误数据），重新获取
            if not stock_name or stock_name == stock_symbol:
                stock_name = get_stock_name(stock_symbol)

            # 获取时间（数据库中是 UTC 时间，需要转换为 UTC+8）
            created_at = doc.get("created_at", now_tz())
            updated_at = doc.get("updated_at", now_tz())

            # 转换时区：数据库中是 UTC 时间，转换为 UTC+8
            created_at_tz = to_config_tz(created_at)
            updated_at_tz = to_config_tz(updated_at)

            report = {
                "id": str(doc["_id"]),
                "analysis_id": doc.get("analysis_id", ""),
                "stock_symbol": stock_symbol,
                "stock_name": stock_name,  # 🔥 添加股票名称字段
                "model_info": doc.get("model_info", "Unknown"),  # 🔥 添加模型信息字段
                "analysis_date": doc.get("analysis_date", ""),
                "status": doc.get("status", "completed"),
                "created_at": created_at_tz.isoformat() if created_at_tz else str(created_at),
                "updated_at": updated_at_tz.isoformat() if updated_at_tz else str(updated_at),
                "analysts": doc.get("analysts", []),
                "summary": doc.get("summary", ""),
                "reports": doc.get("reports", {}),
                "source": doc.get("source", "unknown"),
                "task_id": doc.get("task_id", ""),
                "recommendation": doc.get("recommendation", ""),
                "confidence_score": doc.get("confidence_score", 0.0),
                "risk_level": doc.get("risk_level", "中等"),
                "key_points": doc.get("key_points", []),
                "execution_time": doc.get("execution_time", 0),
                "tokens_used": doc.get("tokens_used", 0)
            }
            # 🔥 合并顶层的 decision/detailed_analysis 到 reports，便于统一抽取
            _decision = doc.get("decision") or doc.get("detailed_analysis") or doc.get("final_decision")
            _combined_for_extract = dict(report["reports"])
            if isinstance(_decision, dict) and _decision:
                _combined_for_extract["decision"] = _decision
            # 🔥 清理所有文本报告，移除开头的思考过程、寒暄语等
            _cleaned_reports = {}
            for _k, _v in report["reports"].items():
                if isinstance(_v, str):
                    _cleaned_reports[_k] = _clean_report_text(_v)
                else:
                    _cleaned_reports[_k] = _v
            report["reports"] = _cleaned_reports
            # 🔥 从 markdown 子报告中抽取结构化字段（核心洞察、策略点位、止盈止损等）
            _extracted = extract_structured_fields(_combined_for_extract)
            # 🔥 关键修复：提取出的结构化字段（尤其是 action/评级/操作建议）始终覆盖已有值
            # 因为报告文本中的决策是最权威的，数据库顶层的字段可能是旧的或错误的
            for _k, _v in _extracted.items():
                if _v is not None:
                    report[_k] = _v

            # 🔥 计算置信度详情（多维度评分依据）
            try:
                _confidence_result = _calculate_confidence(_combined_for_extract)
                if _confidence_result and _confidence_result.get("score"):
                    report["confidence_score"] = _confidence_result["score"]
                    report["置信度详情"] = _confidence_result["details"]
                    logger.info(f"🎯 [报告详情] 计算置信度得分: {_confidence_result['score']}")
            except Exception as _conf_err:
                logger.warning(f"⚠️ [报告详情] 计算置信度失败: {_conf_err}")

        return {
            "success": True,
            "data": report,
            "message": "报告详情获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取报告详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{report_id}/content/{module}")
async def get_report_module_content(
    report_id: str,
    module: str,
    user: dict = Depends(get_current_user)
):
    """获取报告特定模块的内容"""
    try:
        logger.info(f"🔍 获取报告模块内容: {report_id}/{module}")

        db = get_mongo_db()

        # 查询报告（支持多种ID）
        query = _build_report_query(report_id)
        doc = await db.analysis_reports.find_one(query)

        if not doc:
            raise HTTPException(status_code=404, detail="报告不存在")

        reports = doc.get("reports", {})

        if module not in reports:
            raise HTTPException(status_code=404, detail=f"模块 {module} 不存在")

        content = reports[module]

        # 清理报告内容，移除开头的思考过程、寒暄语等
        if isinstance(content, str):
            content = _clean_report_text(content)

        return {
            "success": True,
            "data": {
                "module": module,
                "content": content,
                "content_type": "markdown" if isinstance(content, str) else "json"
            },
            "message": "模块内容获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取报告模块内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    user: dict = Depends(get_current_user)
):
    """删除报告"""
    try:
        logger.info(f"🗑️ 删除报告: {report_id}")

        db = get_mongo_db()

        # 查询报告（支持多种ID）
        query = _build_report_query(report_id)
        result = await db.analysis_reports.delete_one(query)

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="报告不存在")

        logger.info(f"✅ 报告删除成功: {report_id}")

        return {
            "success": True,
            "message": "报告删除成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除报告失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    format: str = Query("markdown", description="下载格式: markdown, json, pdf, docx"),
    user: dict = Depends(get_current_user)
):
    """下载报告

    支持的格式:
    - markdown: Markdown 格式（默认，全中文标题）
    - json: JSON 格式（包含完整数据，中文字段友好）
    - docx: Word 文档格式（全中文）
    - pdf: PDF 格式（全中文）
    """
    try:
        logger.info(f"📥 下载报告: {report_id}, 格式: {format}")

        db = get_mongo_db()

        # 查询报告（支持多种ID）
        query = _build_report_query(report_id)
        doc = await db.analysis_reports.find_one(query)

        if not doc:
            raise HTTPException(status_code=404, detail="报告不存在")

        stock_symbol = doc.get("stock_symbol", "未知")
        analysis_date = doc.get("analysis_date", now_tz().strftime("%Y-%m-%d"))

        # 统一的英文 -> 中文报告字段映射（同步 report_exporter.py 中的定义）
        FIELD_MAP = {
            "analysis_id": "分析编号",
            "stock_symbol": "股票代码",
            "stock_name": "股票名称",
            "market_type": "市场类型",
            "analysis_date": "分析日期",
            "created_at": "创建时间",
            "updated_at": "更新时间",
            "analysts": "分析师团队",
            "status": "状态",
            "summary": "执行摘要",
            "executive_summary": "执行摘要",
            "recommendation": "投资建议",
            "confidence_score": "置信度",
            "confidence": "置信度",
            "risk_level": "风险等级",
            "key_points": "核心要点",
            "action": "操作建议",
            "target_price": "目标价",
            "stop_loss": "止损价",
            "execution_time": "执行耗时(秒)",
            "tokens_used": "Token消耗",
            "source": "数据来源",
            "task_id": "任务编号",
            "decision": "决策详情",
            "state": "分析状态",
            "detailed_analysis": "详细分析",
            "model_info": "模型信息",
            "reports": "各模块报告",
        }

        def translate_key(key: str) -> str:
            if key in FIELD_MAP:
                return FIELD_MAP[key]
            cleaned = key.replace("_report", "").replace("_analysis", "").replace("_state", "")
            if cleaned in FIELD_MAP:
                return FIELD_MAP[cleaned]
            return key

        if format == "json":
            # JSON格式下载：使用中文字段，保持易读性
            from urllib.parse import quote
            try:
                from app.utils.report_exporter import report_exporter
                title_map = report_exporter.MODULE_TITLE_MAP
            except Exception:
                title_map = {}

            def recursive_zh(obj: Any) -> Any:
                if isinstance(obj, dict):
                    return {
                        translate_key(str(k)) if not isinstance(k, str) else
                        (title_map.get(str(k), translate_key(str(k)))
                         if str(k) in title_map else translate_key(str(k))):
                            recursive_zh(v)
                        for k, v in obj.items()
                    }
                if isinstance(obj, list):
                    return [recursive_zh(x) for x in obj]
                return obj

            translated = recursive_zh(dict(doc))
            content = json.dumps(translated, ensure_ascii=False, indent=2, default=str)
            filename = f"{stock_symbol}_{analysis_date}_报告.json"
            media_type = "application/json"

            # 对中文文件名进行URL编码
            filename_encoded = quote(filename)

            # 返回文件流
            def generate():
                yield content.encode('utf-8')

            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
            )

        elif format == "markdown":
            # Markdown格式下载 — 使用统一的报告导出器（全中文标题）
            from urllib.parse import quote

            from app.utils.report_exporter import report_exporter
            content = report_exporter.generate_markdown_report(doc)
            filename = f"{stock_symbol}_{analysis_date}_报告.md"
            media_type = "text/markdown"

            # 对中文文件名进行URL编码
            filename_encoded = quote(filename)

            def generate():
                yield content.encode('utf-8')

            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
            )

        elif format == "docx":
            # Word 文档格式下载
            from urllib.parse import quote

            from app.utils.report_exporter import report_exporter

            try:
                # 生成 Word 文档（Markdown -> Docx，全中文）
                docx_content = report_exporter.generate_docx_report(doc)
                filename = f"{stock_symbol}_{analysis_date}_报告.docx"

                # 对中文文件名进行URL编码
                filename_encoded = quote(filename)

                # 返回文件流
                def generate():
                    yield docx_content

                return StreamingResponse(
                    generate(),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
                )
            except Exception as e:
                logger.error(f"❌ Word 文档生成失败: {e}")
                raise HTTPException(status_code=500, detail=f"Word 文档生成失败: {str(e)}")

        elif format == "pdf":
            # PDF 格式下载
            from urllib.parse import quote

            from app.utils.report_exporter import report_exporter

            try:
                # 生成 PDF 文档（基于中文 Markdown -> HTML -> PDF）
                pdf_content = report_exporter.generate_pdf_report(doc)
                # 清理文件名中的非ASCII字符
                safe_symbol = ''.join(c if ord(c) < 128 else 'stock' for c in str(stock_symbol))
                filename = f"{safe_symbol}_{analysis_date}_report.pdf"
                # 对中文文件名进行URL编码（用于 Content-Disposition）
                filename_zh = f"{stock_symbol}_{analysis_date}_报告.pdf"
                filename_zh_encoded = quote(filename_zh)

                # 返回文件流
                def generate():
                    yield pdf_content

                return StreamingResponse(
                    generate(),
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{filename_zh_encoded}"
                    }
                )
            except FileNotFoundError:
                logger.error("❌ wkhtmltopdf 命令未找到")
                raise HTTPException(
                    status_code=400,
                    detail="PDF 导出功能不可用：缺少 wkhtmltopdf。请先安装后再试。"
                )
            except Exception as e:
                logger.error(f"❌ PDF 文档生成失败: {e}")
                raise HTTPException(status_code=500, detail=f"PDF 文档生成失败: {str(e)}")

        else:
            raise HTTPException(status_code=400, detail=f"不支持的下载格式: {format}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 下载报告失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
