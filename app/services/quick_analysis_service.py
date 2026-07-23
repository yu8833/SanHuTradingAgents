# -*- coding: utf-8 -*-
"""
===================================
速览分析服务
===================================

快速生成股票技术面分析结论，用于：
1. 速览模式：直接展示分析结果
2. 深度模式：为基础分析提供数据

基于趋势交易理念的量化评分系统
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.services.stock_analyzer import (
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    BuySignal,
)
from app.data_provider import get_kline, get_realtime_quote

logger = logging.getLogger(__name__)


@dataclass
class QuickAnalysisResult:
    """速览分析结果"""
    
    # 基本信息
    stock_code: str = ""
    stock_name: str = ""
    current_price: float = 0.0
    price_change: float = 0.0    # 涨跌额
    price_change_pct: float = 0.0  # 涨跌幅 %
    
    # 趋势状态
    trend_status: str = ""        # 趋势状态描述
    trend_strength: float = 0.0   # 趋势强度 0-100
    ma_alignment: str = ""        # 均线排列描述
    
    # 技术指标
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma30: float = 0.0
    ma60: float = 0.0
    bias_ma5: float = 0.0         # 乖离率 %
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    
    # 量能
    volume_status: str = ""        # 量能状态
    volume_ratio: float = 0.0      # 量比
    
    # MACD
    macd_signal: str = ""
    macd_status: str = ""
    macd_dif: float = 0.0
    macd_dea: float = 0.0
    macd_bar: float = 0.0
    
    # RSI
    rsi_signal: str = ""
    rsi_status: str = ""
    rsi_6: float = 0.0
    rsi_12: float = 0.0
    rsi_24: float = 0.0
    
    # 操作建议
    buy_signal: str = ""          # 买卖信号（中文描述）
    signal_type: str = ""         # 信号类型: buy/strong_buy/sell/strong_sell/wait/hold
    confidence: float = 0.0        # 置信度 0-100
    signal_score: int = 0         # 综合评分 0-100
    
    # 关键价位
    support_levels: List[float] = field(default_factory=list)  # 支撑位
    resistance_levels: List[float] = field(default_factory=list)  # 阻力位
    stop_loss: float = 0.0        # 止损位
    target: float = 0.0           # 目标位
    
    # 原因和风险
    signal_reasons: List[str] = field(default_factory=list)  # 买入理由
    risk_factors: List[str] = field(default_factory=list)   # 风险因素
    
    # 一句话结论
    summary: str = ""              # 一句话总结
    
    # 时间
    analysis_date: str = ""        # 分析日期
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "current_price": self.current_price,
            "price_change": self.price_change,
            "price_change_pct": self.price_change_pct,
            "trend_status": self.trend_status,
            "trend_strength": self.trend_strength,
            "ma_alignment": self.ma_alignment,
            "ma5": self.ma5,
            "ma10": self.ma10,
            "ma20": self.ma20,
            "ma30": self.ma30,
            "ma60": self.ma60,
            "bias_ma5": self.bias_ma5,
            "bias_ma10": self.bias_ma10,
            "bias_ma20": self.bias_ma20,
            "volume_status": self.volume_status,
            "volume_ratio": self.volume_ratio,
            "macd_signal": self.macd_signal,
            "macd_status": self.macd_status,
            "macd_dif": self.macd_dif,
            "macd_dea": self.macd_dea,
            "macd_bar": self.macd_bar,
            "rsi_signal": self.rsi_signal,
            "rsi_status": self.rsi_status,
            "rsi_6": self.rsi_6,
            "rsi_12": self.rsi_12,
            "rsi_24": self.rsi_24,
            "buy_signal": self.buy_signal,
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "signal_score": self.signal_score,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "signal_reasons": self.signal_reasons,
            "risk_factors": self.risk_factors,
            "summary": self.summary,
            "analysis_date": self.analysis_date,
        }


class QuickAnalysisService:
    """速览分析服务"""
    
    def __init__(self):
        """初始化服务"""
        self.analyzer = StockTrendAnalyzer()
    
    def analyze(self, stock_code: str, stock_name: Optional[str] = None) -> QuickAnalysisResult:
        """
        执行快速分析
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称（可选，会自动获取）
            
        Returns:
            QuickAnalysisResult 快速分析结果
        """
        logger.info(f"开始快速分析: {stock_code}")
        
        # 1. 获取 K 线数据
        df = get_kline(stock_code, limit=100)
        if df is None or df.empty:
            logger.error(f"获取 {stock_code} K 线数据失败")
            result = QuickAnalysisResult()
            result.stock_code = stock_code
            result.stock_name = stock_name or stock_code
            result.summary = "数据获取失败，无法完成分析"
            result.risk_factors.append("数据获取失败")
            return result
        
        # 2. 获取实时行情
        realtime = get_realtime_quote(stock_code)
        
        # 3. 用实时行情补充 K 线数据（盘中技术指标更准确）
        if realtime and realtime.get('price') and realtime['price'] > 0:
            df = self._augment_with_realtime(df, realtime, stock_code)
        
        # 4. 执行技术分析
        trend_result = self.analyzer.analyze(df, stock_code)
        
        # 5. 构建快速结果
        result = self._build_result(trend_result, realtime, stock_name)
        
        logger.info(f"快速分析完成: {stock_code}, 信号={result.buy_signal}, 评分={result.signal_score}")
        
        return result
    
    def _augment_with_realtime(self, df, realtime: dict, code: str):
        """
        使用当日实时行情补齐历史 OHLCV，用于盘中 MA / MACD / RSI 等技术指标计算。
        参考 daily_stock_analysis 的 _augment_historical_with_realtime 实现。
        """
        if df is None or df.empty or 'close' not in df.columns:
            return df
        if not realtime or not realtime.get('price'):
            return df
        
        price = float(realtime['price'])
        if price <= 0:
            return df
        
        from datetime import datetime, date as date_type
        import pandas as pd
        
        # 获取最新K线日期
        last_val = df['date'].max()
        if hasattr(last_val, 'date'):
            last_date = last_val.date()
        elif isinstance(last_val, date_type):
            last_date = last_val
        else:
            last_date = pd.Timestamp(last_val).date()
        
        yesterday_close = float(df.iloc[-1]['close']) if len(df) > 0 else price
        open_p = realtime.get('open') or realtime.get('prev_close') or yesterday_close
        high_p = realtime.get('high') or price
        low_p = realtime.get('low') or price
        vol = realtime.get('volume') or 0
        amt = realtime.get('amount') or 0
        
        today = datetime.now().date()
        
        df = df.copy()
        if last_date >= today:
            # 更新最后一行
            idx = df.index[-1]
            df.loc[idx, 'close'] = price
            if open_p is not None:
                df.loc[idx, 'open'] = open_p
            if high_p is not None:
                df.loc[idx, 'high'] = high_p
            if low_p is not None:
                df.loc[idx, 'low'] = low_p
            if vol:
                df.loc[idx, 'volume'] = vol
            if amt:
                df.loc[idx, 'amount'] = amt
        else:
            # 追加一行当日实时K线
            new_row = {
                'date': today,
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': price,
                'volume': vol,
                'amount': amt,
            }
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)
        
        return df
    
    def _build_result(
        self,
        trend: TrendAnalysisResult,
        realtime: Optional[dict],
        stock_name: Optional[str] = None
    ) -> QuickAnalysisResult:
        """构建速览分析结果"""
        result = QuickAnalysisResult()
        
        # 基本信息
        result.stock_code = trend.code
        result.stock_name = stock_name or (realtime.get("name") if realtime else "")
        result.current_price = trend.current_price
        
        if realtime:
            result.price_change = realtime.get("change", 0)
            result.price_change_pct = realtime.get("change_pct", 0)
        
        # 趋势状态
        result.trend_status = trend.trend_status.value
        result.trend_strength = trend.trend_strength
        result.ma_alignment = trend.ma_alignment
        
        # 技术指标
        result.ma5 = trend.ma5
        result.ma10 = trend.ma10
        result.ma20 = trend.ma20
        result.ma30 = trend.ma30
        result.ma60 = trend.ma60
        result.bias_ma5 = trend.bias_ma5
        result.bias_ma10 = trend.bias_ma10
        result.bias_ma20 = trend.bias_ma20
        
        # 量能
        result.volume_status = trend.volume_status.value
        result.volume_ratio = trend.volume_ratio_5d
        
        # MACD
        result.macd_signal = trend.macd_signal
        result.macd_status = trend.macd_status.value
        result.macd_dif = trend.macd_dif
        result.macd_dea = trend.macd_dea
        result.macd_bar = trend.macd_bar
        
        # RSI
        result.rsi_signal = trend.rsi_signal
        result.rsi_status = trend.rsi_status.value
        result.rsi_6 = trend.rsi_6
        result.rsi_12 = trend.rsi_12
        result.rsi_24 = trend.rsi_24
        
        # 操作建议
        result.buy_signal = trend.buy_signal.value
        result.signal_type = self._get_signal_type(trend.buy_signal)
        result.signal_score = trend.signal_score
        result.confidence = self._calc_confidence(trend)
        
        # 关键价位
        result.support_levels = sorted(trend.support_levels, reverse=True)
        result.resistance_levels = sorted(trend.resistance_levels)
        result.stop_loss, result.target = self._calc_key_prices(trend)
        
        # 原因和风险
        result.signal_reasons = trend.signal_reasons
        result.risk_factors = trend.risk_factors
        
        # 一句话结论
        result.summary = self._generate_summary(trend)
        
        # 分析日期
        result.analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return result
    
    def _get_signal_type(self, buy_signal: Any) -> str:
        """
        将买卖信号转换为标准类型
        
        Args:
            buy_signal: BuySignal 枚举值
            
        Returns:
            str: 标准信号类型: buy/strong_buy/sell/strong_sell/wait/hold
        """
        if not buy_signal:
            return "hold"
        
        # 如果是 BuySignal 枚举
        if hasattr(buy_signal, 'value'):
            signal_str = buy_signal.value.lower() if isinstance(buy_signal.value, str) else str(buy_signal.value).lower()
        else:
            signal_str = str(buy_signal).lower()
        
        # 映射到标准类型
        if 'strong_buy' in signal_str or '强烈买入' in signal_str or '强烈买' in signal_str:
            return 'strong_buy'
        if 'buy' in signal_str or '买入' in signal_str or '可买入' in signal_str or '买' in signal_str:
            return 'buy'
        if 'strong_sell' in signal_str or '强烈卖出' in signal_str or '强烈卖' in signal_str:
            return 'strong_sell'
        if 'sell' in signal_str or '卖出' in signal_str:
            return 'sell'
        if 'wait' in signal_str or '观望' in signal_str:
            return 'wait'
        return 'hold'
    
    def _calc_confidence(self, trend: TrendAnalysisResult) -> float:
        """
        计算置信度
        
        基于信号强度和风险因素综合评估
        """
        base = trend.signal_score
        
        # 风险因素扣分
        risk_penalty = min(len(trend.risk_factors) * 5, 25)
        
        confidence = base - risk_penalty
        return max(0, min(100, confidence))
    
    def _calc_key_prices(self, trend: TrendAnalysisResult) -> tuple:
        """
        计算关键价位
        
        Returns:
            (stop_loss, target)
        """
        price = trend.current_price
        ma5 = trend.ma5
        ma10 = trend.ma10
        ma20 = trend.ma20
        
        # 止损位：使用 MA10 或 MA20
        if trend.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
            # 多头趋势：止损设在 MA10
            stop_loss = ma10 if ma10 > 0 else price * 0.95
        elif trend.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            # 空头趋势：止损设在 MA5 上方
            stop_loss = ma5 if ma5 > price else price * 1.05
        else:
            # 盘整：止损设在 MA20
            stop_loss = ma20 if ma20 > 0 else price * 0.95
        
        # 目标位：基于趋势强度和关键阻力位
        if trend.resistance_levels:
            # 使用最近的阻力位作为目标
            resist = min([r for r in trend.resistance_levels if r > price], default=price * 1.1)
        else:
            # 默认目标：上涨 10%
            resist = price * 1.1
        
        return round(stop_loss, 2), round(resist, 2)
    
    def _generate_summary(self, trend: TrendAnalysisResult) -> str:
        """
        生成一句话总结
        """
        parts = []
        
        # 趋势状态
        parts.append(trend.trend_status.value)
        
        # 量能
        volume_desc = {
            VolumeStatus.SHRINK_VOLUME_DOWN: "缩量回调",
            VolumeStatus.HEAVY_VOLUME_UP: "放量上涨",
            VolumeStatus.SHRINK_VOLUME_UP: "缩量上涨",
            VolumeStatus.HEAVY_VOLUME_DOWN: "放量下跌",
            VolumeStatus.NORMAL: "量能正常",
        }
        parts.append(volume_desc.get(trend.volume_status, ""))
        
        # 操作建议
        signal_desc = {
            BuySignal.STRONG_BUY: "强烈买入",
            BuySignal.BUY: "可买入",
            BuySignal.HOLD: "持有",
            BuySignal.WAIT: "观望",
            BuySignal.SELL: "卖出",
            BuySignal.STRONG_SELL: "强烈卖出",
        }
        parts.append(signal_desc.get(trend.buy_signal, ""))
        
        # 买点描述（如果有）
        bias = trend.bias_ma5
        if abs(bias) < 3:
            if bias < 0:
                parts.append(f"回踩买点")
            else:
                parts.append(f"贴近MA5")
        elif bias > 5:
            parts.append("⚠️偏离过大")
        
        return "，".join(filter(None, parts))


# 单例模式
_service: Optional[QuickAnalysisService] = None


def get_quick_analysis_service() -> QuickAnalysisService:
    """获取速览分析服务单例"""
    global _service
    if _service is None:
        _service = QuickAnalysisService()
    return _service


def quick_analyze(stock_code: str, stock_name: Optional[str] = None) -> QuickAnalysisResult:
    """
    便捷函数：执行速览分析
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称（可选）
        
    Returns:
        QuickAnalysisResult 速览分析结果
    """
    return get_quick_analysis_service().analyze(stock_code, stock_name)
