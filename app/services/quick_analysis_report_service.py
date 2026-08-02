"""
===================================
快速分析报告服务
===================================

基于数据准备 + 单次 LLM 调用生成高质量多维度分析报告。
参考 daily_stock_analysis 的 comprehensive_strategy 设计理念：
- 数据准备充分：技术面、基本面、资金情绪、行业板块、新闻
- 单次 LLM 调用：token 消耗少、速度快
- 六维度+多空辩论格式：覆盖全面、结构清晰
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QuickAnalysisReport:
    """快速分析完整报告"""
    
    stock_code: str = ""
    stock_name: str = ""
    current_price: float = 0.0
    price_change_pct: float = 0.0
    
    # 六维度分析（Markdown格式）
    dimension_analysis: str = ""
    
    # 多空辩论（Markdown格式）
    bull_bear_debate: str = ""
    
    # 最终结论
    final_conclusion: str = ""
    operation_advice: str = ""
    sentiment_score: int = 0
    
    # 原始数据（用于调试和结构化展示）
    technical_data: dict[str, Any] = field(default_factory=dict)
    fundamental_data: dict[str, Any] = field(default_factory=dict)
    news_data: list[dict[str, Any]] = field(default_factory=list)
    
    # 分析时间
    analysis_date: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "current_price": self.current_price,
            "price_change_pct": self.price_change_pct,
            "dimension_analysis": self.dimension_analysis,
            "bull_bear_debate": self.bull_bear_debate,
            "final_conclusion": self.final_conclusion,
            "operation_advice": self.operation_advice,
            "sentiment_score": self.sentiment_score,
            "technical_data": self.technical_data,
            "fundamental_data": self.fundamental_data,
            "news_count": len(self.news_data),
            "analysis_date": self.analysis_date,
            "report_markdown": self._build_markdown_report(),
        }
    
    def _build_markdown_report(self) -> str:
        """构建完整的 Markdown 格式报告"""
        parts = []
        
        # 标题
        parts.append(f"📊 {self.stock_name}（{self.stock_code}）全面投资分析报告")
        parts.append("")
        
        # 维度分析
        if self.dimension_analysis:
            parts.append("## 一、维度分析摘要")
            parts.append("")
            parts.append(self.dimension_analysis)
            parts.append("")
        
        # 多空辩论
        if self.bull_bear_debate:
            parts.append("## 二、多空辩论")
            parts.append("")
            parts.append(self.bull_bear_debate)
            parts.append("")
        
        # 最终决策 - 无论如何都要包含最终决策和风险提示
        parts.append("## 三、最终决策")
        parts.append("")
        
        if self.final_conclusion:
            parts.append(self.final_conclusion)
            parts.append("")
        else:
            # 如果没有详细结论，但有操作建议或评分
            if self.sentiment_score:
                parts.append(f"**综合评分：{self.sentiment_score}/100**")
                parts.append("")
            if self.operation_advice:
                parts.append(f"**操作建议：{self.operation_advice}**")
                parts.append("")
        
        # 关键价位提示（如果有）
        tech_data = self.technical_data or {}
        key_levels = []
        if tech_data.get('stop_loss'):
            key_levels.append(f"止损位：{tech_data['stop_loss']:.2f}")
        if tech_data.get('target'):
            key_levels.append(f"目标位：{tech_data['target']:.2f}")
        if tech_data.get('ma20'):
            key_levels.append(f"MA20支撑：{tech_data['ma20']:.2f}")
        
        if key_levels:
            parts.append(f"**关键价位：{' / '.join(key_levels)}**")
            parts.append("")
        
        # 生成具体的、个性化的核心风险提示
        core_risks = self._generate_specific_risks(tech_data, self.fundamental_data or {})
        
        if core_risks:
            parts.append("**⚠️ 核心风险提示：**")
            parts.append("")
            for risk in core_risks:
                parts.append(f"- {risk}")
            parts.append("")
        
        # 简短免责声明
        parts.append("*以上分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。*")
        parts.append("")
        
        return "\n".join(parts)
    
    def _generate_specific_risks(self, tech_data: dict, fundamental_data: dict) -> list:
        """生成具体的、个性化的风险提示"""
        risks = []
        
        current_price = tech_data.get('current_price', 0)
        tech_data.get('ma5', 0)
        ma20 = tech_data.get('ma20', 0)
        tech_data.get('ma60', 0)
        rsi_6 = tech_data.get('rsi_6', 50)
        tech_data.get('rsi_12', 50)
        bias_ma5 = tech_data.get('bias_ma5', 0)
        tech_data.get('bias_ma20', 0)
        volume_ratio = tech_data.get('volume_ratio', 1)
        turnover = fundamental_data.get('turnover_rate')
        pe = fundamental_data.get('pe_ttm') or fundamental_data.get('pe')
        trend_status = tech_data.get('trend_status', '')
        macd_status = tech_data.get('macd_status', '')
        tech_data.get('signal_type', '')
        resistance_levels = tech_data.get('resistance_levels', [])
        tech_data.get('support_levels', [])
        
        # 从 recent_trend 中获取近期高低点
        recent_trend = tech_data.get('recent_trend', {})
        recent_low = recent_trend.get('low_price', 0)
        recent_trend.get('high_price', 0)
        low_date = recent_trend.get('low_date', '')
        recent_trend.get('high_date', '')
        
        # 1. RSI超买风险
        if rsi_6 and isinstance(rsi_6, (int, float)) and rsi_6 > 75:
            risks.append(f"⚠️ RSI(6)={rsi_6:.1f}超买：短线存在技术性回调需求")
        elif rsi_6 and isinstance(rsi_6, (int, float)) and rsi_6 > 70:
            risks.append(f"⚠️ RSI(6)={rsi_6:.1f}接近超买区域：需警惕短期回调")
        
        # 2. 短期涨幅过大风险
        if recent_low and current_price and isinstance(recent_low, (int, float)) and isinstance(current_price, (int, float)) and recent_low > 0:
            gain_pct = (current_price - recent_low) / recent_low * 100
            date_str = f"从{low_date}低点" if low_date else "从近期低点"
            if gain_pct > 30:
                risks.append(f"⚠️ 短期涨幅已较大：{date_str}{recent_low:.2f}算起，至今已涨**+{gain_pct:.0f}%**，获利盘丰厚")
            elif gain_pct > 20:
                risks.append(f"⚠️ 短期涨幅较大：{date_str}{recent_low:.2f}算起，已涨+{gain_pct:.0f}%，注意追高风险")
        
        # 3. 乖离率过大风险
        if bias_ma5 and isinstance(bias_ma5, (int, float)) and abs(bias_ma5) > 8:
            risks.append(f"⚠️ 股价偏离MA5过大（{bias_ma5:+.2f}%）：存在向均线回归的技术需求")
        elif bias_ma5 and isinstance(bias_ma5, (int, float)) and abs(bias_ma5) > 5:
            risks.append(f"⚠️ 股价偏离MA5较大（{bias_ma5:+.2f}%）：短期有回调风险")
        
        # 4. 阻力位风险
        if resistance_levels and isinstance(resistance_levels, list) and current_price and isinstance(current_price, (int, float)):
            # 找到最近的阻力位
            nearest_resistance = None
            for r in sorted(resistance_levels):
                if r > current_price:
                    nearest_resistance = r
                    break
            if nearest_resistance and isinstance(nearest_resistance, (int, float)):
                diff_pct = (nearest_resistance - current_price) / current_price * 100
                if 0 < diff_pct < 5:
                    risks.append(f"⚠️ {nearest_resistance:.2f}元是明显阻力：接近前期高点，此处有套牢盘压力")
        
        # 5. MACD顶背离/死叉风险
        if "死叉" in str(macd_status) or "顶背离" in str(macd_status):
            risks.append(f"⚠️ MACD{macd_status}：中期趋势可能转弱")
        
        # 6. 估值过高风险
        if pe is not None and isinstance(pe, (int, float)) and pe > 80:
            risks.append(f"⚠️ 估值明显偏高（PE {pe:.1f}倍）：安全边际不足")
        elif pe is not None and isinstance(pe, (int, float)) and pe > 50:
            risks.append(f"⚠️ 估值偏高（PE {pe:.1f}倍）：需关注业绩是否能支撑")
        
        # 7. 换手率过高风险
        if turnover is not None and isinstance(turnover, (int, float)) and turnover > 15:
            risks.append(f"⚠️ 换手率过高（{turnover:.1f}%）：筹码松动明显，多空分歧大")
        elif turnover is not None and isinstance(turnover, (int, float)) and turnover > 10:
            risks.append(f"⚠️ 换手率偏高（{turnover:.1f}%）：短期波动可能加大")
        
        # 8. 成交量异常放大
        if volume_ratio and isinstance(volume_ratio, (int, float)) and volume_ratio > 3:
            risks.append(f"⚠️ 成交量异常放大（量比{volume_ratio:.1f}）：需警惕放量出货")
        
        # 9. 技术趋势向下风险
        if "空头" in str(trend_status):
            risks.append(f"⚠️ 技术趋势向下（{trend_status}）：下跌趋势中不宜抄底")
        
        # 10. 跌破关键均线风险
        if ma20 and current_price and isinstance(ma20, (int, float)) and isinstance(current_price, (int, float)) and ma20 > 0:
            if current_price < ma20:
                below_pct = (ma20 - current_price) / ma20 * 100
                if below_pct < 5:
                    risks.append(f"⚠️ 股价已跌破MA20（{ma20:.2f}）：中期趋势可能转弱")
        
        # 11. 创业板/科创板波动风险
        if self.stock_code and (self.stock_code.startswith('30') or self.stock_code.startswith('68')):
            board = "创业板" if self.stock_code.startswith('30') else "科创板"
            risks.append(f"⚠️ {board}±20%波动机制：一旦回调，单日跌幅可能很大")
        
        # 12. 消息面缺失风险
        if len(self.news_data or []) == 0:
            risks.append("⚠️ 公司新闻/公告缺失：无法确认走势背后的真实催化剂")
        
        # 最多显示6条最相关的风险
        return risks[:6]


class QuickAnalysisReportService:
    """快速分析报告服务"""
    
    def __init__(self):
        self._llm_client = None
        self._model_name = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """确保 LLM 客户端已初始化"""
        if self._initialized:
            return True
        
        try:
            self._init_llm_client()
            self._initialized = True
            return True
        except Exception as e:
            logger.warning(f"LLM 客户端初始化失败: {e}")
            self._initialized = False
            return False
    
    def _init_llm_client(self):
        """初始化 LLM 客户端（从系统配置中加载模型）"""
        try:
            from app.services.model_capability_service import get_model_capability_service
            from app.services.simple_analysis_service import get_provider_and_url_by_model_sync
            
            capability_service = get_model_capability_service()
            quick_model, _ = capability_service.recommend_default_models()
            
            if not quick_model:
                logger.warning("未找到推荐的快速分析模型")
                return
            
            provider_info = get_provider_and_url_by_model_sync(quick_model)
            if not provider_info or not provider_info.get("api_key"):
                logger.warning(f"模型 {quick_model} 没有有效 API Key")
                return
            
            provider = provider_info.get("provider", "")
            api_key = provider_info.get("api_key", "")
            base_url = provider_info.get("backend_url", "")
            
            # 根据 provider 类型创建对应的 LLM 客户端
            if provider in ["deepseek", "openai"]:
                from tradingagents.llm_clients.openai_client import DeepSeekChatOpenAI, NormalizedChatOpenAI
                if provider == "deepseek":
                    self._llm_client = DeepSeekChatOpenAI(
                        model=quick_model,
                        api_key=api_key,
                        base_url=base_url,
                        temperature=0.7,
                        max_tokens=4000,
                    )
                else:
                    self._llm_client = NormalizedChatOpenAI(
                        model=quick_model,
                        api_key=api_key,
                        base_url=base_url,
                        temperature=0.7,
                        max_tokens=4000,
                    )
            elif provider in ["qwen", "dashscope"]:
                try:
                    from tradingagents.llm_clients.dashscope_client import ChatDashScopeOpenAI
                    self._llm_client = ChatDashScopeOpenAI(
                        model=quick_model,
                        api_key=api_key,
                        base_url=base_url,
                        temperature=0.7,
                        max_tokens=4000,
                    )
                except ImportError:
                    from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI
                    self._llm_client = NormalizedChatOpenAI(
                        model=quick_model,
                        api_key=api_key,
                        base_url=base_url,
                        temperature=0.7,
                        max_tokens=4000,
                    )
            else:
                # 默认使用 OpenAI 兼容格式
                from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI
                self._llm_client = NormalizedChatOpenAI(
                    model=quick_model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=0.7,
                    max_tokens=4000,
                )
            
            self._model_name = quick_model
            logger.info(f"快速分析 LLM 客户端初始化成功: {quick_model} ({provider})")
            
        except Exception as e:
            logger.error(f"LLM 客户端初始化异常: {e}")
            raise
    
    def _collect_technical_data(self, stock_code: str) -> dict[str, Any]:
        """收集技术面数据"""
        try:
            from app.services.quick_analysis_service import get_quick_analysis_service
            service = get_quick_analysis_service()
            result = service.analyze(stock_code)
            result_dict = result.to_dict()
            
            # 获取K线数据用于更详细的分析
            try:
                from app.data_provider import get_kline
                df = get_kline(stock_code, limit=60)
                recent_trend = self._extract_recent_trend(df)
                volume_analysis = self._extract_volume_analysis(df)
            except Exception:
                recent_trend = {}
                volume_analysis = {}
            
            # 构建技术面摘要
            tech_summary = {
                "current_price": result_dict.get("current_price", 0),
                "price_change_pct": result_dict.get("price_change_pct", 0),
                "trend_status": result_dict.get("trend_status", ""),
                "trend_strength": result_dict.get("trend_strength", 0),
                "ma_alignment": result_dict.get("ma_alignment", ""),
                "ma5": result_dict.get("ma5", 0),
                "ma10": result_dict.get("ma10", 0),
                "ma20": result_dict.get("ma20", 0),
                "ma30": result_dict.get("ma30", 0) or result_dict.get("ma20", 0),
                "ma60": result_dict.get("ma60", 0),
                "bias_ma5": result_dict.get("bias_ma5", 0),
                "bias_ma10": result_dict.get("bias_ma10", 0),
                "bias_ma20": result_dict.get("bias_ma20", 0),
                "volume_status": result_dict.get("volume_status", ""),
                "volume_ratio": result_dict.get("volume_ratio", 0),
                "macd_status": result_dict.get("macd_status", ""),
                "macd_signal": result_dict.get("macd_signal", ""),
                "macd_dif": result_dict.get("macd_dif", 0),
                "macd_dea": result_dict.get("macd_dea", 0),
                "macd_bar": result_dict.get("macd_bar", 0),
                "rsi_status": result_dict.get("rsi_status", ""),
                "rsi_6": result_dict.get("rsi_6", 0),
                "rsi_12": result_dict.get("rsi_12", 0),
                "rsi_24": result_dict.get("rsi_24", 0),
                "buy_signal": result_dict.get("buy_signal", ""),
                "signal_score": result_dict.get("signal_score", 0),
                "support_levels": result_dict.get("support_levels", []),
                "resistance_levels": result_dict.get("resistance_levels", []),
                "stop_loss": result_dict.get("stop_loss", 0),
                "target": result_dict.get("target", 0),
                "signal_reasons": result_dict.get("signal_reasons", []),
                "risk_factors": result_dict.get("risk_factors", []),
                "summary": result_dict.get("summary", ""),
                "stock_name": result_dict.get("stock_name", ""),
                "recent_trend": recent_trend,
                "volume_analysis": volume_analysis,
            }
            
            return tech_summary
        except Exception as e:
            logger.error(f"收集技术面数据失败: {e}")
            return {}
    
    def _extract_recent_trend(self, df) -> dict[str, Any]:
        """提取近期走势数据"""
        if df is None or df.empty or len(df) < 10:
            return {}
        
        try:
            df = df.sort_values('date').reset_index(drop=True)
            recent = df.tail(20).copy()
            
            # 找到阶段低点和高点
            low_idx = recent['low'].idxmin()
            high_idx = recent['high'].idxmax()
            
            low_date = str(recent.loc[low_idx, 'date'])[:10]
            low_price = float(recent.loc[low_idx, 'low'])
            high_date = str(recent.loc[high_idx, 'date'])[:10]
            high_price = float(recent.loc[high_idx, 'high'])
            
            # 计算涨跌幅
            first_close = float(recent.iloc[0]['close'])
            last_close = float(recent.iloc[-1]['close'])
            period_change = (last_close - first_close) / first_close * 100 if first_close else 0
            
            # 最近几日走势
            last_5 = df.tail(5)
            daily_changes = []
            for i in range(1, len(last_5)):
                prev_close = float(last_5.iloc[i-1]['close'])
                curr_close = float(last_5.iloc[i]['close'])
                change_pct = (curr_close - prev_close) / prev_close * 100 if prev_close else 0
                date_str = str(last_5.iloc[i]['date'])[:10]
                daily_changes.append({
                    "date": date_str,
                    "change_pct": round(change_pct, 2),
                    "close": round(curr_close, 2),
                })
            
            return {
                "low_date": low_date,
                "low_price": round(low_price, 2),
                "high_date": high_date,
                "high_price": round(high_price, 2),
                "period_change_pct": round(period_change, 2),
                "daily_changes": daily_changes,
            }
        except Exception as e:
            logger.debug(f"提取近期走势失败: {e}")
            return {}
    
    def _extract_volume_analysis(self, df) -> dict[str, Any]:
        """提取量价分析数据"""
        if df is None or df.empty or len(df) < 20:
            return {}
        
        try:
            import numpy as np
            df = df.sort_values('date').reset_index(drop=True)
            recent = df.tail(20).copy()
            
            # 区分上涨日和下跌日的成交量
            up_days = recent[recent['close'] >= recent['open']]
            down_days = recent[recent['close'] < recent['open']]
            
            avg_up_volume = float(up_days['volume'].mean()) if len(up_days) > 0 else 0
            avg_down_volume = float(down_days['volume'].mean()) if len(down_days) > 0 else 0
            
            # 量价相关系数
            if len(recent) >= 5:
                volume_price_corr = float(np.corrcoef(
                    recent['volume'].values.astype(float),
                    recent['close'].values.astype(float)
                )[0, 1]) if len(recent) > 1 else 0
            else:
                volume_price_corr = 0
            
            # 量能趋势（最近5日 vs 前5日）
            if len(recent) >= 10:
                last_5_vol = float(recent.tail(5)['volume'].mean())
                prev_5_vol = float(recent.iloc[-10:-5]['volume'].mean())
                volume_trend = (last_5_vol - prev_5_vol) / prev_5_vol * 100 if prev_5_vol else 0
            else:
                volume_trend = 0
            
            return {
                "avg_up_volume": round(avg_up_volume, 0),
                "avg_down_volume": round(avg_down_volume, 0),
                "volume_price_correlation": round(volume_price_corr, 3),
                "volume_trend_pct": round(volume_trend, 2),
                "up_days_count": len(up_days),
                "down_days_count": len(down_days),
            }
        except Exception as e:
            logger.debug(f"提取量价分析失败: {e}")
            return {}
    
    def _collect_fundamental_data(self, stock_code: str) -> dict[str, Any]:
        """收集基本面数据 - 优先使用 DataSourceManager 实时获取，其次使用 MongoDB 缓存"""
        code6 = stock_code.zfill(6) if len(stock_code) < 6 else stock_code[-6:]
        result = {}
        
        # 1. 优先使用 DataSourceManager 实时获取基本面数据（来自 akshare/东方财富）
        try:
            from app.services.data_sources.manager import DataSourceManager
            ds_manager = DataSourceManager()
            realtime_data, source = ds_manager.get_stock_realtime_fundamental_with_fallback(code6)
            if realtime_data and source:
                logger.info(f"使用 {source} 实时获取 {code6} 基本面数据成功")
                result = {
                    "name": realtime_data.get("name", ""),
                    "price": realtime_data.get("price", 0),
                    "change_pct": realtime_data.get("change_pct", 0),
                    "pe": realtime_data.get("pe"),
                    "pb": realtime_data.get("pb"),
                    "pe_ttm": realtime_data.get("pe"),
                    "total_mv": realtime_data.get("total_mv"),
                    "circ_mv": realtime_data.get("circ_mv"),
                    "turnover_rate": realtime_data.get("turnover_rate"),
                    "volume_ratio": realtime_data.get("volume_ratio"),
                    "industry": realtime_data.get("industry", ""),
                    "amplitude": realtime_data.get("amplitude"),
                    "open": realtime_data.get("open"),
                    "high": realtime_data.get("high"),
                    "low": realtime_data.get("low"),
                    "pre_close": realtime_data.get("pre_close"),
                    "volume": realtime_data.get("volume"),
                    "amount": realtime_data.get("amount"),
                    "list_date": realtime_data.get("list_date", ""),
                    "data_source": source,
                }
                return result
        except Exception as e:
            logger.warning(f"DataSourceManager 实时获取 {code6} 基本面失败: {e}，尝试 MongoDB 缓存")
        
        # 2. 使用 MongoDB 缓存数据作为 fallback
        try:
            from app.core.database import get_mongo_db
            
            db = get_mongo_db()
            
            # 按优先级查询基础信息
            source_priority = ["tushare", "multi_source", "akshare", "baostock"]
            basic_info = None
            for src in source_priority:
                basic_info = db["stock_basic_info"].find_one(
                    {"code": code6, "source": src}, {"_id": 0}
                )
                if basic_info:
                    break
            
            if not basic_info:
                basic_info = db["stock_basic_info"].find_one({"code": code6}, {"_id": 0})
            
            # 查询财务数据
            financial_data = None
            for src in source_priority:
                financial_data = db["stock_financial_data"].find_one(
                    {"$or": [{"symbol": code6}, {"code": code6}], "data_source": src},
                    {"_id": 0},
                    sort=[("report_period", -1)],
                )
                if financial_data:
                    break
            
            # 实时PE/PB计算
            try:
                from tradingagents.dataflows.realtime_metrics import get_pe_pb_with_fallback
                realtime_metrics = get_pe_pb_with_fallback(code6, db.client)
                if not isinstance(realtime_metrics, dict):
                    realtime_metrics = {}
            except Exception:
                realtime_metrics = {}
            
            # 整合数据
            result = {
                "name": basic_info.get("name", "") if basic_info else "",
                "industry": basic_info.get("industry", "") if basic_info else "",
                "market": basic_info.get("market", "") if basic_info else "",
                "sector": basic_info.get("sector", "") if basic_info else "",
                "pe": realtime_metrics.get("pe") or (basic_info.get("pe") if basic_info else None),
                "pb": realtime_metrics.get("pb") or (basic_info.get("pb") if basic_info else None),
                "pe_ttm": realtime_metrics.get("pe_ttm") or (basic_info.get("pe_ttm") if basic_info else None),
                "total_mv": realtime_metrics.get("market_cap") or (basic_info.get("total_mv") if basic_info else None),
                "circ_mv": basic_info.get("circ_mv") if basic_info else None,
                "turnover_rate": basic_info.get("turnover_rate") if basic_info else None,
                "volume_ratio": basic_info.get("volume_ratio") if basic_info else None,
            }
            
            # 财务指标
            if financial_data:
                indicators = financial_data.get("financial_indicators", {}) or {}
                result.update({
                    "roe": indicators.get("roe") or financial_data.get("roe"),
                    "debt_ratio": indicators.get("debt_to_assets") or financial_data.get("debt_to_assets"),
                    "revenue": financial_data.get("revenue"),
                    "revenue_yoy": indicators.get("revenue_yoy") or financial_data.get("revenue_yoy"),
                    "net_profit": financial_data.get("net_profit"),
                    "net_profit_yoy": indicators.get("net_profit_yoy") or financial_data.get("net_profit_yoy"),
                    "gross_margin": indicators.get("gross_margin") or financial_data.get("gross_margin"),
                    "net_margin": indicators.get("net_margin") or financial_data.get("net_margin"),
                    "eps": indicators.get("eps") or financial_data.get("eps"),
                    "report_period": financial_data.get("report_period"),
                    "report_type": financial_data.get("report_type"),
                })
            
            return result
        except Exception as e:
            logger.error(f"收集基本面数据失败: {e}")
            return {}
    
    def _collect_news_data(self, stock_code: str, limit: int = 10) -> list[dict[str, Any]]:
        """收集新闻数据"""
        try:
            from app.core.database import get_mongo_db
            
            db = get_mongo_db()
            code6 = stock_code.zfill(6) if len(stock_code) < 6 else stock_code[-6:]
            
            # 从 stock_news 集合获取
            news_list = list(
                db["stock_news"].find(
                    {"$or": [{"code": code6}, {"symbol": code6}]},
                    {"_id": 0}
                )
                .sort("publish_time", -1)
                .limit(limit)
            )
            
            return news_list
        except Exception as e:
            logger.error(f"收集新闻数据失败: {e}")
            return []
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词 - 完全对齐 daily_stock_analysis 风格"""
        return """你是一位专业的A股投资分析师，擅长基于数据进行全面、客观的股票分析。

## 输出格式（严格遵守）

请严格按照以下格式输出，使用指定的emoji和排版风格：

# 📊 {股票名称}（{股票代码}）全面投资分析报告

## 一、维度分析摘要

📌 **维度一：宏观与行业（权重15%）—— 评分：X/10**
所属板块：{列出主要板块概念}
{行业分析内容}
{利好/利空调整说明}

📌 **维度二：公司基本面（权重20%）—— 评分：X/10 {⚠️ 或 ✅}**
| 指标 | 数据 | 评价 |
|------|------|------|
| PE | {数值}倍 | {评价} |
| PB | {数值}倍 | {评价} |
| 总市值 | {数值}亿 | {评价} |
| 流通市值 | {数值}亿 | {评价} |
| 板块概念 | {概念} | {正向/中性/负向} |
⚠️ 核心风险：{列出核心风险点}

📌 **维度三：技术面（权重25%）—— 评分：X/10 {✅ 亮点维度 或 ⚠️ 注意}**

**均线系统（{多头排列/空头排列/盘整}）：**

MA5  = {价格} ────┐
MA10 = {价格} ────┼── {多头排列/空头排列} {✅/❌}
MA20 = {价格} ────┘
MA30 = {价格}
MA60 = {价格}

**核心技术信号：**

| 指标 | 数值 | 信号 |
|------|------|------|
| 趋势状态 | {状态} | {顺势做多/观望/趋势向下} |
| 趋势强度 | {分数}/100 | {评价} |
| 价格 vs MA5 | {价格} vs {价格}（{乖离率}%） | {评价} |
| 价格 vs MA10 | {价格} vs {价格}（{乖离率}%） | {评价} |
| 价格 vs MA20 | {价格} vs {价格}（{乖离率}%） | {评价} |
| MACD | DIF={数值}, DEA={数值}, 柱线={数值} | {信号评价} |
| RSI(6) | {数值} | {中性偏多/中性偏空/超买/超卖} |
| 信号评分 | {分数}分（{信号}信号） | {✅/⚠️} |

**近期走势回顾：**
{用箭头和日期描述近期走势，如：
MM/DD 阶段低点 XX.XX ──→ MM/DD +X.XX% ──→ MM/DD 高点 XX.XX
                         ↓
                 MM/DD -X.XX% ──→ MM/DD -X.XX% ──→ MM/DD +X.XX% 回稳}

{修正/补充说明：如有特殊信号如MACD即将金叉等，在此说明}

📌 **维度四：资金与情绪（权重20%）—— 评分：X.X/10**
| 指标 | 数据 | 解读 |
|------|------|------|
| 换手率 | {数值}% | {交投活跃/清淡/正常} |
| 量比 | {数值} | {量能正常/放量/缩量} |
| 涨日量能 | {数值}万手/日 | {上涨放量/无量上涨} {✅/⚠️} |
| 跌日量能 | {数值}万手/日 | {下跌缩量/放量杀跌} {✅/⚠️} |
| 量价相关系数 | {数值} | {正相关/负相关/中性} |
| 主力资金流向 | {数据/不可用} | — |
✅ {量价配合评价，如：量价配合良好：上涨日放量、下跌日缩量，属于健康的资金行为。}

📌 **维度五：事件驱动（权重15%）—— 评分：X/10 {⚠️ 或 ✅}**
{如有新闻，列出关键新闻及其影响；如无新闻，说明情报搜索情况并建议自行查阅，列出需排查的风险：股东减持计划、业绩预警/预亏、监管问询/处罚、限售股解禁}

📌 **维度六：风险控制（权重5%）—— 评分调整：-X分**
| 风险项 | 级别 |
|--------|------|
| {风险1} | ⚠️⚠️ |
| {风险2} | ⚠️ |
| {风险3} | 注意 |

## 二、多空辩论

### 🟢 看多方观点
1. {观点1}
2. {观点2}
3. {观点3}
4. {观点4}
5. {观点5}

### 🔴 看空方观点
1. {观点1}
2. {观点2}
3. {观点3}
4. {观点4}

## 三、最终决策

**综合评分：{X}/100**
**操作建议：{强烈买入/可买入/持有/观望/减仓/卖出}**

**核心结论：{一句话总结}**

⚠️ **风险提示**：以上分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。

## 输出要求

1. **基于数据**：所有分析必须基于提供的真实数据，不得编造
2. **客观平衡**：多空观点都要有，避免一边倒，看多方至少4-5条，看空方至少3-4条
3. **结构清晰**：严格按照上述格式组织内容，包括表格、emoji、排版
4. **具体明确**：给出具体的价格、数值、判断
5. **风险提示**：必须包含风险提示
6. **评分合理**：维度评分0-10分，综合评分0-100分，基于数据给出
7. **格式准确**：均线系统的ASCII艺术图必须准确对齐

请直接输出完整的分析报告，不要包含其他说明文字。
        """
    def _build_user_prompt(
        self,
        stock_code: str,
        stock_name: str,
        tech_data: dict[str, Any],
        fundamental_data: dict[str, Any],
        news_data: list[dict[str, Any]],
    ) -> str:
        """构建用户提示词 - 提供结构化数据供LLM生成报告"""
        lines = []
        
        # 基本信息
        lines.append("## 股票基本信息")
        lines.append(f"- 股票代码：{stock_code}")
        lines.append(f"- 股票名称：{stock_name}")
        current_price = tech_data.get('current_price', 0)
        price_change_pct = tech_data.get('price_change_pct', 0)
        lines.append(f"- 当前价格：{current_price:.2f} 元")
        lines.append(f"- 涨跌幅：{price_change_pct:+.2f}%")
        lines.append("")
        
        # ===== 技术面数据 =====
        lines.append("## 技术面数据")
        lines.append("")
        
        # 趋势与均线
        lines.append("### 均线系统")
        ma5 = tech_data.get('ma5', 0)
        ma10 = tech_data.get('ma10', 0)
        ma20 = tech_data.get('ma20', 0)
        ma30 = tech_data.get('ma30', 0) or ma20
        ma60 = tech_data.get('ma60', 0)
        lines.append(f"- 趋势状态：{tech_data.get('trend_status', 'N/A')}")
        lines.append(f"- 趋势强度：{tech_data.get('trend_strength', 0)}/100")
        lines.append(f"- 均线排列：{tech_data.get('ma_alignment', 'N/A')}")
        lines.append(f"- MA5: {ma5:.2f}")
        lines.append(f"- MA10: {ma10:.2f}")
        lines.append(f"- MA20: {ma20:.2f}")
        lines.append(f"- MA30: {ma30:.2f}")
        lines.append(f"- MA60: {ma60:.2f}")
        bias_ma5 = tech_data.get('bias_ma5', 0)
        bias_ma10 = tech_data.get('bias_ma10', 0)
        bias_ma20 = tech_data.get('bias_ma20', 0)
        lines.append(f"- 乖离率 MA5: {bias_ma5:+.2f}%")
        lines.append(f"- 乖离率 MA10: {bias_ma10:+.2f}%")
        lines.append(f"- 乖离率 MA20: {bias_ma20:+.2f}%")
        
        # 买点判断
        if abs(bias_ma5) < 2:
            lines.append("- 买点判断：✅ 最佳买点区间（乖离率<2%）")
        elif abs(bias_ma5) < 5:
            lines.append("- 买点判断：⚠️ 可小仓介入（乖离率2-5%）")
        else:
            lines.append("- 买点判断：❌ 不宜追高（乖离率>5%）")
        lines.append("")
        
        # MACD
        lines.append("### MACD 指标")
        lines.append(f"- DIF: {tech_data.get('macd_dif', 0):.4f}")
        lines.append(f"- DEA: {tech_data.get('macd_dea', 0):.4f}")
        lines.append(f"- 柱线(MACD): {tech_data.get('macd_bar', 0):.4f}")
        lines.append(f"- 状态：{tech_data.get('macd_status', 'N/A')}")
        lines.append(f"- 信号：{tech_data.get('macd_signal', 'N/A')}")
        lines.append("")
        
        # RSI
        lines.append("### RSI 指标")
        lines.append(f"- RSI(6): {tech_data.get('rsi_6', 0):.1f}")
        lines.append(f"- RSI(12): {tech_data.get('rsi_12', 0):.1f}")
        lines.append(f"- RSI(24): {tech_data.get('rsi_24', 0):.1f}")
        lines.append(f"- 状态：{tech_data.get('rsi_status', 'N/A')}")
        lines.append("")
        
        # 量能
        lines.append("### 量能分析")
        lines.append(f"- 量能状态：{tech_data.get('volume_status', 'N/A')}")
        lines.append(f"- 量比：{tech_data.get('volume_ratio', 0):.2f}")
        
        # 量价分析（新增）
        vol_analysis = tech_data.get('volume_analysis', {})
        if vol_analysis:
            avg_up_vol = vol_analysis.get('avg_up_volume', 0)
            avg_down_vol = vol_analysis.get('avg_down_volume', 0)
            vol_price_corr = vol_analysis.get('volume_price_correlation', 0)
            up_days = vol_analysis.get('up_days_count', 0)
            down_days = vol_analysis.get('down_days_count', 0)
            
            # 转换为万手
            avg_up_vol_wan = avg_up_vol / 10000 if avg_up_vol else 0
            avg_down_vol_wan = avg_down_vol / 10000 if avg_down_vol else 0
            
            lines.append(f"- 涨日平均量能：{avg_up_vol_wan:.0f}万手/日（{up_days}天）")
            lines.append(f"- 跌日平均量能：{avg_down_vol_wan:.0f}万手/日（{down_days}天）")
            lines.append(f"- 量价相关系数：{vol_price_corr:.3f}")
            
            if avg_up_vol > 0 and avg_down_vol > 0:
                if avg_up_vol > avg_down_vol * 1.2:
                    lines.append("- 量价配合：✅ 上涨放量、下跌缩量，量价配合良好")
                elif avg_down_vol > avg_up_vol * 1.2:
                    lines.append("- 量价配合：⚠️ 放量下跌、缩量上涨，量价背离")
                else:
                    lines.append("- 量价配合：中性，量能变化不明显")
        lines.append("")
        
        # 支撑阻力
        lines.append("### 支撑与阻力")
        support_levels = tech_data.get('support_levels', [])
        resistance_levels = tech_data.get('resistance_levels', [])
        lines.append(f"- 支撑位：{support_levels}")
        lines.append(f"- 阻力位：{resistance_levels}")
        lines.append(f"- 止损参考：{tech_data.get('stop_loss', 0):.2f}")
        lines.append(f"- 目标参考：{tech_data.get('target', 0):.2f}")
        lines.append("")
        
        # 近期走势
        recent_trend = tech_data.get('recent_trend', {})
        if recent_trend:
            lines.append("### 近期走势（近20日）")
            low_date = recent_trend.get('low_date', '')
            low_price = recent_trend.get('low_price', 0)
            high_date = recent_trend.get('high_date', '')
            high_price = recent_trend.get('high_price', 0)
            period_change = recent_trend.get('period_change_pct', 0)
            lines.append(f"- 阶段低点：{low_date} {low_price:.2f} 元")
            lines.append(f"- 阶段高点：{high_date} {high_price:.2f} 元")
            lines.append(f"- 区间涨跌幅：{period_change:+.2f}%")
            
            daily_changes = recent_trend.get('daily_changes', [])
            if daily_changes:
                lines.append("- 近几日走势：")
                for day in daily_changes:
                    date_str = day.get('date', '')[5:]  # MM-DD
                    change = day.get('change_pct', 0)
                    close = day.get('close', 0)
                    lines.append(f"  {date_str}: {close:.2f} ({change:+.2f}%)")
            lines.append("")
        
        # 技术信号
        lines.append("### 综合信号")
        lines.append(f"- 买卖信号：{tech_data.get('buy_signal', 'N/A')}")
        lines.append(f"- 信号评分：{tech_data.get('signal_score', 0)}/100")
        lines.append("- 信号理由：")
        for reason in tech_data.get('signal_reasons', []):
            lines.append(f"  - {reason}")
        lines.append("- 风险因素：")
        for risk in tech_data.get('risk_factors', []):
            lines.append(f"  - {risk}")
        lines.append("")
        
        # ===== 基本面数据 =====
        lines.append("## 基本面数据")
        if fundamental_data:
            lines.append(f"- 所属行业：{fundamental_data.get('industry', 'N/A')}")
            lines.append(f"- 市场板块：{fundamental_data.get('market', 'N/A')}")
            sector = fundamental_data.get('sector', '')
            if sector:
                lines.append(f"- 所属概念：{sector}")
            
            pe = fundamental_data.get('pe_ttm') or fundamental_data.get('pe', 'N/A')
            pb = fundamental_data.get('pb', 'N/A')
            total_mv = fundamental_data.get('total_mv', 'N/A')
            circ_mv = fundamental_data.get('circ_mv', 'N/A')
            
            lines.append(f"- PE(TTM)：{pe}" + ("倍" if isinstance(pe, (int, float)) else ""))
            lines.append(f"- PB：{pb}" + ("倍" if isinstance(pb, (int, float)) else ""))
            lines.append(f"- 总市值：{total_mv} 亿元")
            lines.append(f"- 流通市值：{circ_mv} 亿元")
            
            # 盈利能力
            roe = fundamental_data.get('roe')
            gross_margin = fundamental_data.get('gross_margin')
            net_margin = fundamental_data.get('net_margin')
            if roe is not None:
                lines.append(f"- ROE：{roe}%")
            if gross_margin is not None:
                lines.append(f"- 毛利率：{gross_margin}%")
            if net_margin is not None:
                lines.append(f"- 净利率：{net_margin}%")
            
            # 成长性
            revenue_yoy = fundamental_data.get('revenue_yoy')
            net_profit_yoy = fundamental_data.get('net_profit_yoy')
            if revenue_yoy is not None:
                lines.append(f"- 营收增速：{revenue_yoy}%")
            if net_profit_yoy is not None:
                lines.append(f"- 净利润增速：{net_profit_yoy}%")
            
            debt_ratio = fundamental_data.get('debt_ratio')
            if debt_ratio is not None:
                lines.append(f"- 资产负债率：{debt_ratio}%")
            
            report_period = fundamental_data.get('report_period')
            if report_period:
                lines.append(f"- 财报期：{report_period}")
        else:
            lines.append("- 暂无基本面数据")
        lines.append("")
        
        # ===== 资金与情绪 =====
        lines.append("## 资金与情绪数据")
        turnover = fundamental_data.get('turnover_rate') if fundamental_data else None
        volume_ratio = tech_data.get('volume_ratio', 0)
        
        if turnover is not None:
            lines.append(f"- 换手率：{turnover}%")
            if isinstance(turnover, (int, float)):
                if turnover < 0.5:
                    lines.append("  解读：交投冷淡，可能处于底部区域")
                elif turnover < 2:
                    lines.append("  解读：正常交投水平")
                elif turnover < 5:
                    lines.append("  解读：交投活跃，关注资金动向")
                elif turnover < 10:
                    lines.append("  解读：高度活跃，短期波动可能加大")
                else:
                    lines.append("  解读：极度过热，注意短期顶部风险")
        else:
            lines.append("- 换手率：N/A")
        
        lines.append(f"- 量比：{volume_ratio:.2f}")
        lines.append("")
        
        # ===== 新闻数据 =====
        lines.append("## 近期新闻与事件")
        if news_data:
            lines.append(f"共获取 {len(news_data)} 条近期新闻：")
            for i, news in enumerate(news_data[:8]):
                title = news.get("title", "") or news.get("headline", "") or "无标题"
                publish_time = news.get("publish_time", "") or news.get("time", "") or ""
                source = news.get("source", "") or ""
                time_str = f"（{publish_time}）" if publish_time else ""
                source_str = f"[{source}]" if source else ""
                lines.append(f"{i+1}. {source_str}{title}{time_str}")
        else:
            lines.append("- 暂无近期新闻数据")
            lines.append("- 建议投资者自行查阅公司公告，排查以下风险：")
            lines.append("  - 股东减持计划")
            lines.append("  - 业绩预警/预亏")
            lines.append("  - 监管问询/处罚")
            lines.append("  - 限售股解禁")
        lines.append("")
        
        lines.append("请基于以上数据，严格按照系统提示中的输出格式生成完整的投资分析报告。")
        lines.append("注意：")
        lines.append("1. 均线系统的ASCII图必须对齐，MA5/MA10/MA20在左侧，用竖线连接后右侧写结论")
        lines.append("2. 技术面是权重最高的维度（25%），应重点分析")
        lines.append("3. 如果数据缺失，用合理的方式说明，不要编造数据")
        lines.append("4. 多空观点要平衡，都要基于数据")
        
        return "\n".join(lines)
    
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM 生成分析报告"""
        if not self._llm_client:
            raise RuntimeError("LLM 客户端未初始化")
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            
            response = self._llm_client.invoke(messages)
            content = response.content
            
            # 清理可能的包裹
            content = content.strip()
            if content.startswith("```markdown"):
                content = content[11:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            return content
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise
    
    def analyze(self, stock_code: str, stock_name: str | None = None) -> QuickAnalysisReport:
        """
        执行完整的快速分析
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称（可选）
            
        Returns:
            QuickAnalysisReport 完整分析报告
        """
        logger.info(f"开始快速分析报告: {stock_code}")
        
        report = QuickAnalysisReport()
        report.stock_code = stock_code
        report.analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        try:
            # 1. 收集技术面数据
            logger.info("  收集技术面数据...")
            tech_data = self._collect_technical_data(stock_code)
            report.technical_data = tech_data
            
            if tech_data:
                report.current_price = tech_data.get("current_price", 0)
                report.price_change_pct = tech_data.get("price_change_pct", 0)
                if not stock_name:
                    stock_name = tech_data.get("stock_name", "")
                report.stock_name = stock_name or stock_code
            
            # 2. 收集基本面数据
            logger.info("  收集基本面数据...")
            fundamental_data = self._collect_fundamental_data(stock_code)
            report.fundamental_data = fundamental_data
            
            if fundamental_data and not report.stock_name:
                report.stock_name = fundamental_data.get("name", "") or stock_code
            
            # 3. 收集新闻数据
            logger.info("  收集新闻数据...")
            news_data = self._collect_news_data(stock_code)
            report.news_data = news_data
            
            # 4. 尝试调用 LLM 生成完整报告
            llm_success = False
            llm_output_valid = False  # LLM输出是否包含有效内容
            if self._ensure_initialized() and self._llm_client:
                try:
                    logger.info("  调用 LLM 生成分析报告...")
                    system_prompt = self._build_system_prompt()
                    user_prompt = self._build_user_prompt(
                        stock_code, report.stock_name, tech_data, fundamental_data, news_data
                    )
                    
                    llm_output = self._call_llm(system_prompt, user_prompt)
                    
                    # 解析 LLM 输出
                    self._parse_llm_output(report, llm_output)
                    llm_success = True
                    
                    # 检查LLM输出是否包含有效内容（特别是操作建议）
                    if report.operation_advice or report.final_conclusion or report.dimension_analysis:
                        llm_output_valid = True
                        logger.info("  LLM 分析报告生成成功")
                    else:
                        logger.warning("  LLM 输出内容不完整，将使用降级报告")
                except Exception as e:
                    logger.warning(f"LLM 生成报告失败，降级使用程序化分析: {e}")
            
            # 5. 如果 LLM 失败或输出无效，使用程序化生成的降级报告
            if not llm_success or not llm_output_valid:
                if llm_success and not llm_output_valid:
                    logger.info("  触发降级报告: LLM输出内容不完整")
                self._generate_fallback_report(report, tech_data, fundamental_data, news_data)
            
            # 6. 确保 operation_advice 始终有值（基于信号类型或评分）
            if not report.operation_advice:
                signal_type = tech_data.get('signal_type', 'wait') if tech_data else 'wait'
                action_map = {
                    'strong_buy': '强烈买入',
                    'buy': '可买入',
                    'hold': '持有',
                    'wait': '观望',
                    'sell': '卖出',
                    'strong_sell': '强烈卖出',
                }
                report.operation_advice = action_map.get(signal_type, '观望')
                logger.info(f"  操作建议（基于信号类型）: {report.operation_advice}")
            
            logger.info(f"快速分析完成: {stock_code}")
            return report
            
        except Exception as e:
            logger.error(f"快速分析异常: {e}", exc_info=True)
            report.final_conclusion = f"分析异常: {str(e)}"
            return report
    
    def _parse_llm_output(self, report: QuickAnalysisReport, llm_output: str):
        """解析 LLM 输出，填充报告字段"""
        content = llm_output.strip()
        
        # 维度分析（从开头到"多空辩论"之前）
        dimension_part = ""
        debate_part = ""
        conclusion_part = ""
        
        # 查找各部分的分割点
        lower_content = content.lower()
        
        # 多空辩论位置
        debate_idx = -1
        for keyword in ["二、多空辩论", "## 二、多空辩论", "多空辩论", "🟢 看多方"]:
            idx = content.find(keyword)
            if idx != -1:
                debate_idx = idx
                break
        
        # 最终决策位置
        conclusion_idx = -1
        for keyword in ["三、最终决策", "## 三、最终决策", "最终决策", "最终结论", "综合评分", "操作建议"]:
            idx = content.find(keyword)
            if idx != -1:
                conclusion_idx = idx
                break
        
        dimension_part = content[:debate_idx].strip() if debate_idx != -1 else content
        
        if debate_idx != -1 and conclusion_idx != -1:
            debate_part = content[debate_idx:conclusion_idx].strip()
        elif debate_idx != -1:
            # 如果没有找到最终决策，则辩论之后的所有内容都作为最终决策
            debate_part = content[debate_idx:].strip()
            conclusion_part = ""  # 辩论部分已包含所有内容
        elif conclusion_idx != -1:
            debate_part = ""
            conclusion_part = content[conclusion_idx:].strip()
        
        if conclusion_idx != -1:
            conclusion_part = content[conclusion_idx:].strip()
        
        # 清理各部分的标题行和冗余内容
        def _clean_dimension_section(text: str) -> str:
            """清理维度分析部分，移除主标题和章节标题"""
            lines = text.split("\n")
            result_lines = []
            skip_next_empty = False
            for line in lines:
                stripped = line.strip()
                # 跳过主标题（包含"全面投资分析报告"的行）
                if "全面投资分析报告" in stripped:
                    skip_next_empty = True
                    continue
                # 跳过章节标题"一、维度分析摘要"
                if stripped.startswith("## 一、维度分析摘要") or stripped.startswith("# 一、维度分析摘要") or stripped == "一、维度分析摘要":
                    skip_next_empty = True
                    continue
                # 跳过下一部分的标题开头（"## 二、"等，这些是上一步切割残留的）
                if stripped.startswith("## 二") or stripped.startswith("# 二") or stripped == "二、多空辩论" or stripped == "##":
                    skip_next_empty = True
                    continue
                # 跳过后继的空行
                if skip_next_empty and stripped == "":
                    skip_next_empty = False
                    continue
                skip_next_empty = False
                result_lines.append(line)
            return "\n".join(result_lines).strip()
        
        def _clean_debate_section(text: str) -> str:
            """清理多空辩论部分，移除章节标题"""
            lines = text.split("\n")
            result_lines = []
            skip_next_empty = False
            for line in lines:
                stripped = line.strip()
                # 跳过章节标题
                if stripped.startswith("## 二、多空辩论") or stripped.startswith("# 二、多空辩论") or stripped == "二、多空辩论":
                    skip_next_empty = True
                    continue
                # 跳过下一部分的标题开头（"## 三、"等）
                if stripped.startswith("## 三") or stripped.startswith("# 三") or stripped == "三、最终决策" or stripped == "##":
                    skip_next_empty = True
                    continue
                # 跳过后继的空行
                if skip_next_empty and stripped == "":
                    skip_next_empty = False
                    continue
                skip_next_empty = False
                result_lines.append(line)
            return "\n".join(result_lines).strip()
        
        def _clean_conclusion_section(text: str) -> str:
            """清理最终决策部分，移除章节标题"""
            lines = text.split("\n")
            result_lines = []
            skip_next_empty = False
            for line in lines:
                stripped = line.strip()
                # 跳过章节标题
                if stripped.startswith("## 三、最终决策") or stripped.startswith("# 三、最终决策") or stripped == "三、最终决策":
                    skip_next_empty = True
                    continue
                # 跳过后继的空行
                if skip_next_empty and stripped == "":
                    skip_next_empty = False
                    continue
                skip_next_empty = False
                result_lines.append(line)
            return "\n".join(result_lines).strip()
        
        report.dimension_analysis = _clean_dimension_section(dimension_part)
        report.bull_bear_debate = _clean_debate_section(debate_part)
        report.final_conclusion = _clean_conclusion_section(conclusion_part)
        
        # 提取操作建议（从结论部分）
        advice_patterns = [
            "操作建议", "操作策略", "投资建议", "建议",
        ]
        for pattern in advice_patterns:
            idx = conclusion_part.find(pattern)
            if idx != -1:
                # 提取冒号或空格后的内容
                after = conclusion_part[idx + len(pattern):]
                after = after.lstrip("：: \t")
                # 取第一行
                first_line = after.split("\n")[0].strip()
                # 移除markdown格式标记
                first_line = first_line.replace("**", "").strip()
                if first_line:
                    report.operation_advice = first_line[:50]
                    break
        
        # 尝试提取评分
        score_patterns = ["综合评分", "总分", "评分", "sentiment_score"]
        for pattern in score_patterns:
            idx = lower_content.find(pattern)
            if idx != -1:
                after = lower_content[idx:]
                import re
                match = re.search(r'(\d{1,3})\s*(?:分|/100)?', after)
                if match:
                    score = int(match.group(1))
                    if 0 <= score <= 100:
                        report.sentiment_score = score
                        break
    
    def _generate_fallback_report(
        self,
        report: QuickAnalysisReport,
        tech_data: dict[str, Any],
        fundamental_data: dict[str, Any],
        news_data: list[dict[str, Any]],
    ):
        """生成降级版报告（当 LLM 不可用时）- 格式对齐 daily_stock_analysis 风格"""
        
        
        # ===== 维度分析 =====
        dim_parts = []
        
        # 维度一：宏观与行业
        industry = fundamental_data.get("industry", "未知") if fundamental_data else "未知"
        sector = fundamental_data.get("sector", "") if fundamental_data else ""
        market = fundamental_data.get("market", "") if fundamental_data else ""
        
        macro_score = 6
        macro_reasons = []
        if sector and ("新能源" in sector or "半导体" in sector or "AI" in sector or "机器人" in sector):
            macro_score = 7
            macro_reasons.append("属于热门赛道")
        
        dim_parts.append(f"📌 **维度一：宏观与行业（权重15%）—— 评分：{macro_score}/10**")
        dim_parts.append(f"所属板块：{industry}" + (f"、{sector}" if sector else ""))
        if market:
            dim_parts.append(f"市场板块：{market}")
        if macro_reasons:
            dim_parts.append(f"{' '.join(macro_reasons)}")
        dim_parts.append(f"利好调整：行业政策扶持 +{macro_score - 5}")
        dim_parts.append("")
        
        # 维度二：公司基本面
        pe = fundamental_data.get("pe_ttm") or fundamental_data.get("pe") if fundamental_data else None
        pb = fundamental_data.get("pb") if fundamental_data else None
        total_mv = fundamental_data.get("total_mv") if fundamental_data else None
        circ_mv = fundamental_data.get("circ_mv") if fundamental_data else None
        roe = fundamental_data.get("roe") if fundamental_data else None
        revenue_yoy = fundamental_data.get("revenue_yoy") if fundamental_data else None
        net_profit_yoy = fundamental_data.get("net_profit_yoy") if fundamental_data else None
        
        # 基本面评分
        fund_score = 5
        fund_warning = ""
        core_risks = []
        
        if pe is not None and isinstance(pe, (int, float)):
            if pe < 20:
                fund_score += 2
            elif pe > 50:
                fund_score -= 2
                fund_warning = " ⚠️"
                core_risks.append(f"PE {pe:.1f}倍明显偏高")
        
        if roe is not None and isinstance(roe, (int, float)):
            if roe > 15:
                fund_score += 2
            elif roe < 5:
                fund_score -= 1
        
        if total_mv is not None and isinstance(total_mv, (int, float)) and 100 < total_mv < 1000:
            fund_score += 0.5
        
        fund_score = max(1, min(10, fund_score))
        
        dim_parts.append(f"📌 **维度二：公司基本面（权重20%）—— 评分：{fund_score}/10{fund_warning}**")
        dim_parts.append("")
        dim_parts.append("| 指标 | 数据 | 评价 |")
        dim_parts.append("|------|------|------|")
        
        pe_str = f"{pe:.2f}倍" if pe is not None else "N/A"
        pe_eval = "偏低" if (pe and pe < 20) else ("偏高 ⚠️" if (pe and pe > 50) else "中等")
        dim_parts.append(f"| PE | {pe_str} | {pe_eval} |")
        
        pb_str = f"{pb:.2f}倍" if pb is not None else "N/A"
        pb_eval = "偏低" if (pb and pb < 2) else ("偏高" if (pb and pb > 8) else "中等")
        dim_parts.append(f"| PB | {pb_str} | {pb_eval} |")
        
        mv_str = f"{total_mv:.2f}亿" if total_mv is not None else "N/A"
        mv_eval = "中盘股" if (total_mv and 100 < total_mv < 1000) else ("大盘股" if (total_mv and total_mv >= 1000) else "小盘股")
        dim_parts.append(f"| 总市值 | {mv_str} | {mv_eval} |")
        
        circ_str = f"{circ_mv:.2f}亿" if circ_mv is not None else "N/A"
        circ_eval = "流动性好" if (circ_mv and circ_mv > 50) else "流动性一般"
        dim_parts.append(f"| 流通市值 | {circ_str} | {circ_eval} |")
        
        sector_str = sector or industry or "N/A"
        dim_parts.append(f"| 板块概念 | {sector_str} | 正向 |")
        dim_parts.append("")
        
        if core_risks:
            dim_parts.append(f"⚠️ 核心风险：{'；'.join(core_risks)}")
        else:
            dim_parts.append("⚠️ 核心风险：数据有限，建议进一步核查基本面")
        dim_parts.append("")
        
        # 维度三：技术面
        ma5 = tech_data.get('ma5', 0) if tech_data else 0
        ma10 = tech_data.get('ma10', 0) if tech_data else 0
        ma20 = tech_data.get('ma20', 0) if tech_data else 0
        ma30 = tech_data.get('ma30', 0) if tech_data else ma20
        ma60 = tech_data.get('ma60', 0) if tech_data else 0
        current_price = tech_data.get('current_price', 0) if tech_data else 0
        bias_ma5 = tech_data.get('bias_ma5', 0) if tech_data else 0
        bias_ma10 = tech_data.get('bias_ma10', 0) if tech_data else 0
        bias_ma20 = tech_data.get('bias_ma20', 0) if tech_data else 0
        trend_status = tech_data.get('trend_status', '') if tech_data else ''
        trend_strength = tech_data.get('trend_strength', 0) if tech_data else 0
        signal_score = tech_data.get('signal_score', 50) if tech_data else 50
        buy_signal = tech_data.get('buy_signal', '') if tech_data else ''
        
        tech_score = round(signal_score / 10, 1)
        tech_highlight = " ✅ 亮点维度" if tech_score >= 7 else (" ⚠️" if tech_score < 5 else "")
        
        dim_parts.append(f"📌 **维度三：技术面（权重25%）—— 评分：{tech_score}/10{tech_highlight}**")
        dim_parts.append("")
        
        # 均线系统 ASCII 图
        is_bull = ma5 > ma10 > ma20
        ma_status = "多头排列" if is_bull else ("空头排列" if ma5 < ma10 < ma20 else "盘整")
        ma_check = " ✅" if is_bull else (" ❌" if ma5 < ma10 < ma20 else "")
        
        dim_parts.append(f"**均线系统（{ma_status}）：**")
        dim_parts.append("")
        dim_parts.append(f"MA5  = {ma5:.2f} ────┐")
        dim_parts.append(f"MA10 = {ma10:.2f} ────┼── {ma_status}{ma_check}")
        dim_parts.append(f"MA20 = {ma20:.2f} ────┘")
        dim_parts.append(f"MA30 = {ma30:.2f}")
        dim_parts.append(f"MA60 = {ma60:.2f}")
        dim_parts.append("")
        
        # 核心技术信号表
        dim_parts.append("**核心技术信号：**")
        dim_parts.append("")
        dim_parts.append("| 指标 | 数值 | 信号 |")
        dim_parts.append("|------|------|------|")
        
        trend_signal = "顺势做多" if "多头" in trend_status else ("趋势向下" if "空头" in trend_status else "观望")
        dim_parts.append(f"| 趋势状态 | {trend_status} | {trend_signal} |")
        dim_parts.append(f"| 趋势强度 | {trend_strength}/100 | {'良好' if trend_strength >= 60 else ('一般' if trend_strength >= 40 else '较弱')} |")
        
        ma5_status = "✅ 最佳买点区间（<2%）" if abs(bias_ma5) < 2 else (f"偏离 {bias_ma5:+.2f}%" if abs(bias_ma5) < 5 else "⚠️ 偏离过大")
        dim_parts.append(f"| 价格 vs MA5 | {current_price:.2f} vs {ma5:.2f}（{bias_ma5:+.2f}%） | {ma5_status} |")
        
        ma10_status = "MA10支撑有效" if current_price > ma10 and bias_ma10 > -2 else "跌破MA10"
        dim_parts.append(f"| 价格 vs MA10 | {current_price:.2f} vs {ma10:.2f}（{bias_ma10:+.2f}%） | {ma10_status} |")
        
        ma20_status = "回踩确认" if current_price > ma20 else "跌破MA20 ⚠️"
        dim_parts.append(f"| 价格 vs MA20 | {current_price:.2f} vs {ma20:.2f}（{bias_ma20:+.2f}%） | {ma20_status} |")
        
        macd_status = tech_data.get('macd_status', '') if tech_data else ''
        macd_dif = tech_data.get('macd_dif', 0) if tech_data else 0
        macd_dea = tech_data.get('macd_dea', 0) if tech_data else 0
        macd_bar = tech_data.get('macd_bar', 0) if tech_data else 0
        tech_data.get('macd_signal', '') if tech_data else ''
        dim_parts.append(f"| MACD | DIF={macd_dif:.2f}, DEA={macd_dea:.2f}, 柱线{macd_bar:+.2f} | {macd_status} |")
        
        rsi_6 = tech_data.get('rsi_6', 0) if tech_data else 0
        rsi_status = "中性偏多" if rsi_6 >= 55 else ("中性偏空" if rsi_6 <= 45 else "中性")
        dim_parts.append(f"| RSI(6) | {rsi_6:.1f} | {rsi_status} |")
        
        signal_icon = "✅" if signal_score >= 60 else ("⚠️" if signal_score < 40 else "")
        dim_parts.append(f"| 信号评分 | {signal_score}分（{buy_signal}信号） | {signal_icon} |")
        dim_parts.append("")
        
        # 近期走势回顾
        recent_trend = tech_data.get('recent_trend', {}) if tech_data else {}
        if recent_trend:
            dim_parts.append("**近期走势回顾：**")
            dim_parts.append("")
            low_date = recent_trend.get('low_date', '')[5:]  # MM-DD
            low_price = recent_trend.get('low_price', 0)
            high_date = recent_trend.get('high_date', '')[5:]
            high_price = recent_trend.get('high_price', 0)
            recent_trend.get('period_change_pct', 0)
            
            # 参考项目格式：阶段低点 → 高点 → 回调
            daily_changes = recent_trend.get('daily_changes', [])
            if daily_changes and len(daily_changes) >= 3:
                # 计算从低点到高点的涨幅
                if low_price and high_price:
                    (high_price - low_price) / low_price * 100 if low_price else 0
                else:
                    pass
                
                # 构建走势描述
                first_line = f"{low_date} 阶段低点 {low_price:.2f} ──→ {high_date} 高点 {high_price:.2f}"
                dim_parts.append(first_line)
                
                # 如果有回调（最后几天是下跌的），添加第二行
                if len(daily_changes) >= 3:
                    last_3 = daily_changes[-3:]
                    down_days = [d for d in last_3 if d.get('change_pct', 0) < 0]
                    if len(down_days) >= 2:
                        # 有回调，添加箭头和回调描述
                        last_change = daily_changes[-1]
                        last_date = last_change.get('date', '')[5:]
                        last_close = last_change.get('close', 0)
                        last_change.get('change_pct', 0)
                        
                        # 从高点到最新的跌幅
                        high_to_now_pct = (last_close - high_price) / high_price * 100 if high_price else 0
                        
                        dim_parts.append("                         ↓")
                        callback_desc = f"                 {high_date} 高点后回调 {high_to_now_pct:+.2f}% ──→ {last_date} {last_close:.2f} 回稳"
                        dim_parts.append(callback_desc)
            else:
                dim_parts.append(f"{low_date} 阶段低点 {low_price:.2f} ──→ {high_date} 高点 {high_price:.2f}")
            dim_parts.append("")
        
        # MACD 修正/补充说明
        macd_dif = tech_data.get('macd_dif', 0) if tech_data else 0
        macd_dea = tech_data.get('macd_dea', 0) if tech_data else 0
        macd_bar = tech_data.get('macd_bar', 0) if tech_data else 0
        macd_status = tech_data.get('macd_status', '') if tech_data else ''
        
        if macd_dif != 0 or macd_dea != 0:
            # 判断是否即将金叉/死叉
            dif_dea_diff = abs(macd_dif - macd_dea)
            if dif_dea_diff < 0.3 and macd_bar > 0 and macd_dif < 0:
                dim_parts.append(f"修正：MACD虽仍为{macd_status}，但DIF线（{macd_dif:.2f}）正快速向DEA线（{macd_dea:.2f}）收敛，零轴下方金叉即将形成，这是趋势即将转强的信号。")
                dim_parts.append("")
            elif dif_dea_diff < 0.3 and macd_bar < 0 and macd_dif > 0:
                dim_parts.append(f"注意：MACD虽仍为{macd_status}，但DIF线（{macd_dif:.2f}）正快速向DEA线（{macd_dea:.2f}）收敛，零轴上方死叉即将形成，注意回调风险。")
                dim_parts.append("")
        
        dim_parts.append("")
        
        # 维度四：资金与情绪
        turnover = fundamental_data.get("turnover_rate") if fundamental_data else None
        volume_ratio = tech_data.get("volume_ratio", 0) if tech_data else 0
        vol_analysis = tech_data.get("volume_analysis", {}) if tech_data else {}
        
        cap_score = 5.5
        if turnover is not None and isinstance(turnover, (int, float)):
            if 1 <= turnover <= 3:
                cap_score = 6
            elif 3 < turnover <= 7:
                cap_score = 7
            elif turnover > 10:
                cap_score = 4.5
        
        dim_parts.append(f"📌 **维度四：资金与情绪（权重20%）—— 评分：{cap_score}/10**")
        dim_parts.append("")
        dim_parts.append("| 指标 | 数据 | 解读 |")
        dim_parts.append("|------|------|------|")
        
        turnover_str = f"{turnover:.2f}%" if turnover is not None else "N/A"
        turnover_eval = "交投活跃" if (turnover and turnover > 3) else ("正常交投" if (turnover and turnover > 1) else "交投清淡")
        dim_parts.append(f"| 换手率 | {turnover_str} | {turnover_eval} |")
        
        dim_parts.append(f"| 量比 | {volume_ratio:.2f} | {'量能正常' if 0.8 < volume_ratio < 1.5 else ('放量' if volume_ratio >= 1.5 else '缩量')} |")
        
        avg_up_vol = vol_analysis.get('avg_up_volume', 0)
        avg_down_vol = vol_analysis.get('avg_down_volume', 0)
        avg_up_wan = avg_up_vol / 10000 if avg_up_vol else 0
        avg_down_wan = avg_down_vol / 10000 if avg_down_vol else 0
        
        up_vol_status = "上涨放量 ✅" if avg_up_vol > avg_down_vol * 1.1 else "无量上涨"
        down_vol_status = "下跌缩量 ✅" if avg_up_vol > avg_down_vol * 1.1 else "放量杀跌"
        dim_parts.append(f"| 涨日量能 | {avg_up_wan:.0f}万手/日 | {up_vol_status} |")
        dim_parts.append(f"| 跌日量能 | {avg_down_wan:.0f}万手/日 | {down_vol_status} |")
        
        vol_price_corr = vol_analysis.get('volume_price_correlation', 0)
        corr_eval = "中性偏正" if vol_price_corr > 0.3 else ("中性偏负" if vol_price_corr < -0.3 else "中性")
        dim_parts.append(f"| 量价相关系数 | {vol_price_corr:.3f} | {corr_eval} |")
        
        dim_parts.append("| 主力资金流向 | 数据不可用 | — |")
        dim_parts.append("")
        
        if avg_up_vol > avg_down_vol * 1.1:
            dim_parts.append("✅ 量价配合良好：上涨日放量、下跌日缩量，属于健康的资金行为。")
        else:
            dim_parts.append("⚠️ 量价配合一般，需进一步观察资金动向。")
        dim_parts.append("")
        
        # 维度五：事件驱动
        news_count = len(news_data)
        news_score = 5 if news_count > 0 else 5
        news_warning = " ⚠️" if news_count == 0 else ""
        
        dim_parts.append(f"📌 **维度五：事件驱动（权重15%）—— 评分：{news_score}/10{news_warning}**")
        if news_count == 0:
            dim_parts.append("⚠️ 情报搜索失败，无法获取最新新闻、公告、减持、业绩预告等关键信息。建议投资者自行查阅公司公告，排查以下风险：")
            dim_parts.append("")
            dim_parts.append("- 股东减持计划")
            dim_parts.append("- 业绩预警/预亏")
            dim_parts.append("- 监管问询/处罚")
            dim_parts.append("- 限售股解禁")
        else:
            dim_parts.append(f"近期有 {news_count} 条相关新闻，建议详细查阅评估影响。")
        dim_parts.append("")
        
        # 维度六：风险控制
        risk_list = []
        risk_levels = []
        
        if pe is not None and isinstance(pe, (int, float)) and pe > 50:
            risk_list.append(f"PE {pe:.1f}倍明显偏高")
            risk_levels.append("⚠️⚠️")
        
        if news_count == 0:
            risk_list.append("缺乏新闻数据，无法排除利空")
            risk_levels.append("⚠️")
        
        if turnover is not None and isinstance(turnover, (int, float)) and turnover > 5:
            risk_list.append(f"换手率{turnover:.1f}%，筹码活跃不稳定")
            risk_levels.append("注意")
        
        if "空头" in trend_status or signal_score < 40:
            risk_list.append("技术趋势偏弱，下行风险")
            risk_levels.append("注意")
        
        if not risk_list:
            risk_list.append("暂无明显风险点")
            risk_levels.append("低")
        
        risk_penalty = min(len(risk_list) * 0.5, 2)
        
        dim_parts.append(f"📌 **维度六：风险控制（权重5%）—— 评分调整：-{risk_penalty}分**")
        dim_parts.append("")
        dim_parts.append("| 风险项 | 级别 |")
        dim_parts.append("|--------|------|")
        for i, risk in enumerate(risk_list):
            level = risk_levels[i] if i < len(risk_levels) else "注意"
            dim_parts.append(f"| {risk} | {level} |")
        dim_parts.append("")
        
        report.dimension_analysis = "\n".join(dim_parts)
        
        # ===== 多空辩论 =====
        bull_points = []
        bear_points = []
        
        is_bullish = "多头" in trend_status if trend_status else False
        is_bearish = "空头" in trend_status if trend_status else False
        
        if tech_data:
            if is_bullish:
                bull_points.append(f"技术面{trend_status}，顺势做多信号明确")
            elif is_bearish:
                bear_points.append(f"技术面{trend_status}，趋势向下风险较大")
            
            if abs(bias_ma5) < 2:
                if bias_ma5 < 0:
                    bull_points.append(f"股价低于MA5仅{bias_ma5:+.2f}%（乖离率<2%），属于最佳买点")
                else:
                    bull_points.append(f"股价贴近MA5（乖离率{bias_ma5:+.2f}%），趋势健康")
            elif bias_ma5 > 5:
                bear_points.append(f"股价偏离MA5过大（{bias_ma5:+.2f}%），短期回调风险")
            
            if rsi_6 < 30:
                bull_points.append("RSI进入超卖区间，反弹概率增加")
            elif rsi_6 > 70:
                bear_points.append("RSI进入超买区间，回调风险增加")
            
            # 从信号理由中提取看多观点
            signal_reasons = tech_data.get("signal_reasons", [])
            for reason in signal_reasons:
                if "✅" in reason or "买入" in reason or "支撑" in reason:
                    clean = reason.replace("✅ ", "").replace("✅", "").strip()
                    if clean and clean not in bull_points:
                        bull_points.append(clean)
            
            # 从风险因素中提取看空观点
            risk_factors = tech_data.get("risk_factors", [])
            for risk in risk_factors:
                clean = risk.replace("⚠️ ", "").replace("⚠ ", "").replace("⚠️", "").replace("⚠", "").strip()
                # 避免矛盾的风险描述（如多头趋势下的"空头排列"）
                if is_bullish and ("空头" in clean or "下跌趋势" in clean):
                    continue
                if is_bearish and ("多头" in clean or "上涨趋势" in clean):
                    continue
                if clean and clean not in bear_points:
                    bear_points.append(clean)
        
        # MACD 相关观点
        if tech_data:
            macd_bar = tech_data.get('macd_bar', 0)
            macd_dif = tech_data.get('macd_dif', 0)
            macd_dea = tech_data.get('macd_dea', 0)
            if macd_dif != 0 or macd_dea != 0:
                if macd_dif > macd_dea and macd_bar > 0:
                    bull_points.append("MACD多头排列，红柱放大，动能增强")
                elif macd_dif < macd_dea and macd_bar < 0:
                    bear_points.append("MACD空头排列，绿柱放大，动能减弱")
                elif abs(macd_dif - macd_dea) < 0.1 and macd_bar > 0:
                    bull_points.append("MACD即将金叉，趋势可能转强")
                elif abs(macd_dif - macd_dea) < 0.1 and macd_bar < 0:
                    bear_points.append("MACD即将死叉，注意回调风险")
        
        if fundamental_data:
            if pe is not None and isinstance(pe, (int, float)):
                if pe < 20:
                    bull_points.append(f"估值较低（PE {pe:.1f}），安全边际较高")
                elif pe > 50:
                    bear_points.append(f"估值偏高（PE {pe:.1f}），需要高成长消化")
            
            if roe is not None and isinstance(roe, (int, float)) and roe > 15:
                bull_points.append(f"盈利能力优秀（ROE {roe:.1f}%）")
            elif roe is not None and isinstance(roe, (int, float)) and roe < 5:
                bear_points.append(f"盈利能力较弱（ROE {roe:.1f}%）")
            
            if revenue_yoy is not None and isinstance(revenue_yoy, (int, float)) and revenue_yoy > 20:
                bull_points.append(f"营收高速增长（{revenue_yoy:.1f}%）")
            elif revenue_yoy is not None and isinstance(revenue_yoy, (int, float)) and revenue_yoy < 0:
                bear_points.append(f"营收下滑（{revenue_yoy:.1f}%）")
            
            if net_profit_yoy is not None and isinstance(net_profit_yoy, (int, float)) and net_profit_yoy > 30:
                bull_points.append(f"净利润高速增长（{net_profit_yoy:.1f}%）")
            elif net_profit_yoy is not None and isinstance(net_profit_yoy, (int, float)) and net_profit_yoy < 0:
                bear_points.append(f"净利润下滑（{net_profit_yoy:.1f}%）")
        
        if sector and ("新能源" in sector or "半导体" in sector or "机器人" in sector or "AI" in sector):
            bull_points.append(f"多重热门赛道：{sector}，题材丰富")
        
        # 补充通用观点
        if is_bullish and signal_score >= 60:
            bear_points.append("短期涨幅较大，注意获利回吐压力")
            bear_points.append("需警惕大盘系统性风险对个股的影响")
        elif is_bearish:
            bull_points.append("恐慌性下跌后可能存在超跌反弹机会")
            bull_points.append("长期投资者可逢低分批建仓")
        
        if news_count == 0:
            bear_points.append("缺乏最新新闻数据，无法排除潜在利空")
        
        if not bull_points:
            bull_points.append("技术面信号中性，等待明确方向")
        if not bear_points:
            bear_points.append("暂无明显利空因素，但需警惕系统性风险")
        
        # 去重
        bull_points = list(dict.fromkeys(bull_points))
        bear_points = list(dict.fromkeys(bear_points))
        
        # 确保至少各有 4 条
        default_bull = [
            "技术面趋势向好",
            "量价配合健康",
            "估值处于合理区间",
            "行业前景向好",
        ]
        default_bear = [
            "需警惕大盘系统性风险",
            "短期波动风险不可忽视",
            "注意仓位控制",
            "关注后续数据验证",
        ]
        for point in default_bull:
            if len(bull_points) >= 5:
                break
            if point not in bull_points:
                bull_points.append(point)
        for point in default_bear:
            if len(bear_points) >= 4:
                break
            if point not in bear_points:
                bear_points.append(point)
        
        debate_parts = []
        debate_parts.append("### 🟢 看多方观点")
        for i, point in enumerate(bull_points[:5], 1):
            debate_parts.append(f"{i}. {point}")
        debate_parts.append("")
        debate_parts.append("### 🔴 看空方观点")
        for i, point in enumerate(bear_points[:4], 1):
            debate_parts.append(f"{i}. {point}")
        debate_parts.append("")
        
        report.bull_bear_debate = "\n".join(debate_parts)
        
        # ===== 最终决策 =====
        final_score = signal_score
        signal = buy_signal or "观望"
        
        conclusion_parts = []
        conclusion_parts.append("## 三、最终决策")
        conclusion_parts.append("")
        conclusion_parts.append(f"**综合评分：{final_score}/100**")
        conclusion_parts.append(f"**操作建议：{signal}**")
        conclusion_parts.append("")
        
        # 更详细的操作建议
        advice_detail = ""
        if signal in ["买入", "强烈买入", "增持", "加仓"]:
            if bias_ma5 is not None and abs(bias_ma5) < 2:
                advice_detail = "当前股价贴近MA5，处于较好的买点位置，可考虑分批建仓。"
            elif bias_ma5 is not None and bias_ma5 > 5:
                advice_detail = "短期涨幅较大，建议等待回调后再介入，避免追高。"
            else:
                advice_detail = "趋势向好，可逢低布局，设置好止损位。"
        elif signal in ["卖出", "减持", "减仓"]:
            advice_detail = "趋势走弱，建议减仓或离场观望，控制风险。"
        elif signal in ["持有"]:
            advice_detail = "趋势仍在，可继续持有，但需密切关注关键支撑位。"
        else:
            advice_detail = "方向不明朗，建议观望等待明确信号。"
        
        if advice_detail:
            conclusion_parts.append(f"**操作策略：{advice_detail}**")
            conclusion_parts.append("")
        
        summary = tech_data.get('summary', '') if tech_data else ''
        if summary:
            conclusion_parts.append(f"**核心结论：{summary}**")
        else:
            conclusion_parts.append(f"**核心结论：技术面{trend_status}，{signal}。**")
        conclusion_parts.append("")
        
        # 核心风险总结（从各维度汇总）
        core_risks = []
        if pe is not None and isinstance(pe, (int, float)) and pe > 50:
            core_risks.append(f"估值偏高（PE {pe:.1f}倍）")
        if "空头" in trend_status:
            core_risks.append("技术趋势向下")
        if turnover is not None and isinstance(turnover, (int, float)) and turnover > 10:
            core_risks.append(f"换手率过高（{turnover:.1f}%），筹码不稳定")
        if news_count == 0:
            core_risks.append("缺乏最新消息面数据")
        
        if core_risks:
            conclusion_parts.append("**核心风险：**")
            for risk in core_risks:
                conclusion_parts.append(f"- ⚠️ {risk}")
            conclusion_parts.append("")
        
        # 关键价位提示
        key_levels = []
        if tech_data.get('stop_loss'):
            key_levels.append(f"止损位：{tech_data['stop_loss']:.2f}")
        if tech_data.get('target'):
            key_levels.append(f"目标位：{tech_data['target']:.2f}")
        if ma20:
            key_levels.append(f"MA20支撑：{ma20:.2f}")
        
        if key_levels:
            conclusion_parts.append(f"**关键价位：{' / '.join(key_levels)}**")
            conclusion_parts.append("")
        
        conclusion_parts.append("⚠️ **风险提示**：以上分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。")
        conclusion_parts.append("")
        
        report.final_conclusion = "\n".join(conclusion_parts)
        report.operation_advice = signal
        report.sentiment_score = final_score


# 单例模式
_service: QuickAnalysisReportService | None = None


def get_quick_analysis_report_service() -> QuickAnalysisReportService:
    """获取快速分析报告服务单例"""
    global _service
    if _service is None:
        _service = QuickAnalysisReportService()
    return _service
