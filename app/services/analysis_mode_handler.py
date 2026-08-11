"""
分析模式处理器
策略模式实现速览模式和深度分析模式的解耦
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AnalysisModeHandler(ABC):
    """分析模式处理器基类"""

    def __init__(
        self,
        task_id: str,
        user_id: str,
        stock_code: str,
        stock_name: str,
        analysis_date: str,
        request_params: Any,
        update_progress: Callable
    ):
        self.task_id = task_id
        self.user_id = user_id
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.analysis_date = analysis_date
        self.request_params = request_params
        self.update_progress = update_progress
        self.start_time = datetime.now()

    @abstractmethod
    async def execute(self) -> dict[str, Any]:
        """执行分析"""
        pass

    @abstractmethod
    async def save_result(self, result: dict[str, Any]) -> bool:
        """保存结果"""
        pass

    @abstractmethod
    async def send_notification(self, result: dict[str, Any]) -> bool:
        """发送通知"""
        pass

    def get_execution_time(self) -> float:
        """获取执行时间"""
        return (datetime.now() - self.start_time).total_seconds()


class QuickAnalysisHandler(AnalysisModeHandler):
    """快速分析处理器"""

    async def execute(self) -> dict[str, Any]:
        """执行快速分析"""
        logger.info(f"🚀 [快速模式] 开始分析: {self.stock_code}")

        # 更新进度
        self.update_progress(5, "📊 快速分析中...", "quick_analysis")

        # 执行快速分析
        try:
            from app.services.quick_analysis_service import get_quick_analysis_service
            quick_service = get_quick_analysis_service()
            quick_result = quick_service.analyze(self.stock_code, self.stock_name)
            quick_result_dict = quick_result.to_dict()

            logger.info(f"✅ [快速模式] 分析完成: {quick_result.buy_signal}, 评分: {quick_result.signal_score}")

            self.update_progress(95, "📊 整理分析结果", "result_processing")

            return {
                'mode': 'quick',
                'stock_code': self.stock_code,
                'stock_name': self.stock_name,
                'quick_result': quick_result_dict,
                'analysis_date': self.analysis_date,
                'execution_time': self.get_execution_time(),
            }
        except Exception as e:
            logger.error(f"❌ [速览模式] 分析失败: {e}")
            raise

    async def save_result(self, result: dict[str, Any]) -> bool:
        """保存速览分析结果"""
        from datetime import datetime

        from app.services.simple_analysis_service import get_mongo_pool

        try:
            db = get_mongo_pool().get_db()

            # 更新任务记录
            db.analysis_tasks.update_one(
                {"task_id": self.task_id},
                {"$set": {
                    "result": result,
                    "quick_result": result.get('quick_result'),
                    "mode": "quick",
                    "status": "completed",
                    "progress": 100,
                }}
            )

            # 保存到报告列表
            report_doc = {
                "task_id": self.task_id,
                "user_id": self.user_id,
                "stock_code": self.stock_code,
                "stock_name": self.stock_name,
                "mode": "quick",
                "quick_result": result.get('quick_result'),
                "analysis_date": self.analysis_date,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "status": "completed",
            }
            db.reports.insert_one(report_doc)

            logger.info(f"✅ [速览模式] 结果已保存: {self.task_id}")
            return True

        except Exception as e:
            logger.error(f"❌ [速览模式] 保存结果失败: {e}")
            return False

    async def send_notification(self, result: dict[str, Any]) -> bool:
        """发送快速分析完成通知"""
        try:
            from app.services.notifications_service import get_notifications_service
            notif_service = get_notifications_service()

            await notif_service.create_notification(
                user_id=self.user_id,
                type="analysis_complete",
                title="快速分析完成",
                content=f"{self.stock_code} 快速分析完成",
                data={"task_id": self.task_id, "stock_code": self.stock_code}
            )

            return True
        except Exception as e:
            logger.warning(f"⚠️ [快速模式] 发送通知失败: {e}")
            return False


class DeepAnalysisHandler(AnalysisModeHandler):
    """深度分析处理器"""

    def __init__(
        self,
        task_id: str,
        user_id: str,
        stock_code: str,
        stock_name: str,
        analysis_date: str,
        request_params: Any,
        update_progress: Callable,
        quick_result_dict: dict | None = None
    ):
        super().__init__(task_id, user_id, stock_code, stock_name, analysis_date, request_params, update_progress)
        self.quick_result_dict = quick_result_dict

    async def execute(self) -> dict[str, Any]:
        """执行深度分析"""
        logger.info(f"🚀 [深度模式] 开始分析: {self.stock_code}")

        # 初始化分析引擎
        self.update_progress(9, "🚀 初始化AI分析引擎", "engine_initialization")

        from app.services.simple_analysis_service import SimpleAnalysisService
        service = SimpleAnalysisService()
        config = service._prepare_config(
            self.request_params.quick_analysis_model,
            self.request_params.deep_analysis_model,
            self.request_params.quick_model_config if hasattr(self.request_params, 'quick_model_config') else None,
            self.request_params.deep_model_config if hasattr(self.request_params, 'deep_model_config') else None
        )

        # 创建进度回调
        def graph_progress_callback(message: str):
            logger.info(f"📊 [深度模式] {message}")

        trading_graph = service._get_trading_graph(config, callbacks=[graph_progress_callback])

        # 获取交易日期范围
        from tradingagents.utils.dataflow_utils import get_trading_date_range
        data_start_date, data_end_date = get_trading_date_range(self.analysis_date, lookback_days=10)

        logger.info(f"📅 [深度模式] 分析目标日期: {self.analysis_date}")
        logger.info(f"📅 [深度模式] 数据查询范围: {data_start_date} 至 {data_end_date}")

        # 开始分析
        self.update_progress(10, "🤖 开始多智能体协作分析", "agent_analysis")

        state, decision = trading_graph.propagate(
            self.stock_code,
            self.analysis_date,
            quick_analysis_result=self.quick_result_dict
        )

        logger.info("✅ [深度模式] propagate 执行完成")

        # 处理结果
        self.update_progress(90, "处理分析结果...", "result_processing")

        # 提取报告
        reports = self._extract_reports(state)

        # 提取决策
        trade_decision = self._extract_decision(decision)

        return {
            'mode': 'deep',
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'quick_result': self.quick_result_dict,
            'analysis_date': self.analysis_date,
            'execution_time': self.get_execution_time(),
            'reports': reports,
            'decision': trade_decision,
            'state': state if isinstance(state, dict) else vars(state) if hasattr(state, '__dict__') else str(state),
        }

    def _extract_reports(self, state: Any) -> dict[str, Any]:
        """从state中提取报告"""
        reports = {}

        report_fields = [
            'market_report',
            'sentiment_report',
            'news_report',
            'fundamentals_report',
            'policy_report',
            'hot_money_report',
            'lockup_report',
            'investment_plan',
            'trader_investment_plan',
            'final_trade_decision'
        ]

        for field in report_fields:
            if hasattr(state, field):
                value = getattr(state, field, "")
            elif isinstance(state, dict) and field in state:
                value = state[field]
            else:
                value = ""
            reports[field] = value

        return reports

    def _extract_decision(self, decision: Any) -> dict[str, Any] | None:
        """从decision中提取决策信息"""
        if decision is None:
            return None

        if isinstance(decision, dict):
            return decision
        elif hasattr(decision, '__dict__'):
            return vars(decision)

        return str(decision)

    async def save_result(self, result: dict[str, Any]) -> bool:
        """保存深度分析结果"""
        from datetime import datetime

        from app.services.simple_analysis_service import get_mongo_pool

        try:
            db = get_mongo_pool().get_db()

            # 更新任务记录
            db.analysis_tasks.update_one(
                {"task_id": self.task_id},
                {"$set": {
                    "result": result,
                    "quick_result": result.get('quick_result'),
                    "reports": result.get('reports'),
                    "decision": result.get('decision'),
                    "mode": "deep",
                    "status": "completed",
                    "progress": 100,
                }}
            )

            # 保存到报告列表
            report_doc = {
                "task_id": self.task_id,
                "user_id": self.user_id,
                "stock_code": self.stock_code,
                "stock_name": self.stock_name,
                "mode": "deep",
                "quick_result": result.get('quick_result'),
                "reports": result.get('reports'),
                "decision": result.get('decision'),
                "analysis_date": self.analysis_date,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "status": "completed",
            }
            db.reports.insert_one(report_doc)

            logger.info(f"✅ [深度模式] 结果已保存: {self.task_id}")
            return True

        except Exception as e:
            logger.error(f"❌ [深度模式] 保存结果失败: {e}")
            return False

    async def send_notification(self, result: dict[str, Any]) -> bool:
        """发送深度分析完成通知"""
        try:
            from app.services.notifications_service import get_notifications_service
            notif_service = get_notifications_service()

            decision = result.get('decision', {})
            action = decision.get('action', '分析') if isinstance(decision, dict) else '分析'

            await notif_service.create_notification(
                user_id=self.user_id,
                type="analysis_complete",
                title="深度分析完成",
                content=f"{self.stock_code} 深度分析完成，建议: {action}",
                data={"task_id": self.task_id, "stock_code": self.stock_code}
            )

            return True
        except Exception as e:
            logger.warning(f"⚠️ [深度模式] 发送通知失败: {e}")
            return False


class AnalysisModeFactory:
    """分析模式工厂"""

    @staticmethod
    def create_handler(
        mode: str,
        task_id: str,
        user_id: str,
        stock_code: str,
        stock_name: str,
        analysis_date: str,
        request_params: Any,
        update_progress: Callable,
        quick_result_dict: dict | None = None
    ) -> AnalysisModeHandler:
        """创建分析模式处理器"""

        if mode == 'quick':
            return QuickAnalysisHandler(
                task_id=task_id,
                user_id=user_id,
                stock_code=stock_code,
                stock_name=stock_name,
                analysis_date=analysis_date,
                request_params=request_params,
                update_progress=update_progress
            )
        elif mode == 'deep':
            return DeepAnalysisHandler(
                task_id=task_id,
                user_id=user_id,
                stock_code=stock_code,
                stock_name=stock_name,
                analysis_date=analysis_date,
                request_params=request_params,
                update_progress=update_progress,
                quick_result_dict=quick_result_dict
            )
        else:
            logger.warning(f"⚠️ 未知分析模式: {mode}，使用深度模式")
            return DeepAnalysisHandler(
                task_id=task_id,
                user_id=user_id,
                stock_code=stock_code,
                stock_name=stock_name,
                analysis_date=analysis_date,
                request_params=request_params,
                update_progress=update_progress,
                quick_result_dict=quick_result_dict
            )
