"""
市场环境过滤器

在跑任何策略前，先判断市场环境（趋势/波动率/宽度/情绪），
据此动态激活或关闭策略。不同策略在不同市场环境下表现差异极大，
没有环境过滤会导致策略在错误的时间运行。

四个维度：
1. 趋势（trend）：沪深300 vs 250日均线 → bull/bear/range
2. 波动率（volatility）：近20日波动率分位 → high/normal/low
3. 宽度（breadth）：站上均线的股票占比 → broad/narrow
4. 情绪（sentiment）：换手率/融资余额变化 → euphoric/neutral/panic
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set

from app.services.retail.position_sizer import StrategyType

logger = logging.getLogger(__name__)


class RegimeType(str, Enum):
    """市场趋势类型"""

    BULL = "bull"  # 牛市
    BEAR = "bear"  # 熊市
    RANGE = "range"  # 震荡市


class VolatilityLevel(str, Enum):
    """波动率水平"""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class MarketBreadth(str, Enum):
    """市场宽度"""

    BROAD = "broad"  # 普涨
    NARROW = "narrow"  # 分化


class SentimentLevel(str, Enum):
    """市场情绪"""

    EUPHORIC = "euphoric"  # 狂热
    NEUTRAL = "neutral"  # 中性
    PANIC = "panic"  # 恐慌


@dataclass
class MarketRegime:
    """市场环境综合判断结果"""

    trend: RegimeType
    volatility: VolatilityLevel
    breadth: MarketBreadth
    sentiment: SentimentLevel
    # 在当前环境下建议激活的策略
    active_strategies: List[StrategyType]
    # 环境判断的简要说明
    summary: str

    def to_dict(self) -> dict:
        return {
            "trend": self.trend.value,
            "volatility": self.volatility.value,
            "breadth": self.breadth.value,
            "sentiment": self.sentiment.value,
            "active_strategies": [s.value for s in self.active_strategies],
            "summary": self.summary,
        }

    def is_strategy_allowed(self, strategy: StrategyType) -> bool:
        """判断某策略在当前环境下是否被允许运行"""
        return strategy in self.active_strategies


# 市场宽度分位阈值
BREADTH_BROAD_THRESHOLD = 0.55  # 55%以上股票站上均线 → broad
BREADTH_NARROW_THRESHOLD = 0.35  # 35%以下 → narrow


class MarketRegimeDetector:
    """
    市场环境检测器

    纯计算模块，不直接依赖数据层。由调用方提供大盘指标数据，
    本模块负责综合判断并输出策略激活建议。
    """

    def detect(
        self,
        index_price: float,
        index_ma250: float,
        volatility_percentile: float,  # 0-1
        breadth_ratio: float,  # 0-1，站上均线的股票占比
        margin_balance_change_pct: float,  # 融资余额变化百分比
        turnover_ratio: float,  # 换手率
        turnover_ma20: float,  # 换手率20日均值
    ) -> MarketRegime:
        """
        综合判断市场环境

        Args:
            index_price: 指数当前价（如沪深300）
            index_ma250: 指数250日均线
            volatility_percentile: 近20日波动率在历史中的分位（0-1）
            breadth_ratio: 站上均线的股票占比（0-1）
            margin_balance_change_pct: 融资余额近5日变化百分比
            turnover_ratio: 当前换手率
            turnover_ma20: 换手率20日均值

        Returns:
            MarketRegime 市场环境综合判断
        """
        trend = self._detect_trend(index_price, index_ma250)
        volatility = self._detect_volatility(volatility_percentile)
        breadth = self._detect_breadth(breadth_ratio)
        sentiment = self._detect_sentiment(
            margin_balance_change_pct, turnover_ratio, turnover_ma20
        )

        active_strategies = self._select_strategies(
            trend, volatility, breadth, sentiment
        )

        summary = self._build_summary(
            trend, volatility, breadth, sentiment, active_strategies
        )

        return MarketRegime(
            trend=trend,
            volatility=volatility,
            breadth=breadth,
            sentiment=sentiment,
            active_strategies=active_strategies,
            summary=summary,
        )

    def _detect_trend(
        self, index_price: float, index_ma250: float
    ) -> RegimeType:
        """趋势判断：价格 vs 250日均线"""
        if index_ma250 <= 0:
            return RegimeType.RANGE
        deviation = (index_price - index_ma250) / index_ma250
        if deviation > 0.05:  # 高于均线5%以上
            return RegimeType.BULL
        elif deviation < -0.05:  # 低于均线5%以上
            return RegimeType.BEAR
        else:
            return RegimeType.RANGE

    def _detect_volatility(
        self, volatility_percentile: float
    ) -> VolatilityLevel:
        """波动率判断"""
        if volatility_percentile >= 0.8:  # 80分位以上
            return VolatilityLevel.HIGH
        elif volatility_percentile <= 0.3:  # 30分位以下
            return VolatilityLevel.LOW
        else:
            return VolatilityLevel.NORMAL

    def _detect_breadth(self, breadth_ratio: float) -> MarketBreadth:
        """市场宽度判断"""
        if breadth_ratio >= BREADTH_BROAD_THRESHOLD:
            return MarketBreadth.BROAD
        elif breadth_ratio <= BREADTH_NARROW_THRESHOLD:
            return MarketBreadth.NARROW
        else:
            # 中间区域，偏向 broad（避免过度保守）
            return MarketBreadth.BROAD if breadth_ratio >= 0.45 else MarketBreadth.NARROW

    def _detect_sentiment(
        self,
        margin_change_pct: float,
        turnover_ratio: float,
        turnover_ma20: float,
    ) -> SentimentLevel:
        """情绪判断：融资余额变化 + 换手率"""
        # 换手率相对均值
        turnover_deviation = 0.0
        if turnover_ma20 > 0:
            turnover_deviation = (turnover_ratio - turnover_ma20) / turnover_ma20

        # 狂热：融资余额大幅增加 + 换手率放大
        if margin_change_pct > 3.0 and turnover_deviation > 0.5:
            return SentimentLevel.EUPHORIC
        # 恐慌：融资余额大幅减少 + 换手率放大（抛售）或萎缩（冰点）
        elif margin_change_pct < -3.0:
            return SentimentLevel.PANIC
        else:
            return SentimentLevel.NEUTRAL

    def _select_strategies(
        self,
        trend: RegimeType,
        volatility: VolatilityLevel,
        breadth: MarketBreadth,
        sentiment: SentimentLevel,
    ) -> List[StrategyType]:
        """
        根据市场环境选择激活的策略

        核心逻辑：
        - 熊市+高波动+恐慌 → 极端反转（恐慌超跌有反弹机会）
        - 牛市+低波动+中性 → 小盘价值（小盘弹性大）
        - 震荡市 → 困境反转（需要深度研究）
        - 任何环境 → 转债（有债底保护，跨周期）
        """
        active: List[StrategyType] = []

        # 策略A极端反转：熊市+高波动+恐慌 时最有价值
        if (
            trend == RegimeType.BEAR
            and volatility == VolatilityLevel.HIGH
            and sentiment == SentimentLevel.PANIC
        ):
            active.append(StrategyType.EXTREME_REVERSAL)

        # 策略B困境反转：震荡市或熊市末期（波动率正常）
        if trend in (RegimeType.RANGE, RegimeType.BEAR) and volatility in (
            VolatilityLevel.NORMAL,
            VolatilityLevel.LOW,
        ):
            active.append(StrategyType.TURNAROUND)

        # 策略C小盘价值：牛市或震荡市偏强
        if trend in (RegimeType.BULL, RegimeType.RANGE) and breadth == MarketBreadth.BROAD:
            active.append(StrategyType.SMALL_CAP_VALUE)

        # 策略D转债：任何环境都可运行（有债底保护）
        active.append(StrategyType.CONVERTIBLE_ARBITRAGE)

        # 如果没有策略被激活（比如牛市+恐慌这种矛盾组合），默认激活转债
        if not active:
            active.append(StrategyType.CONVERTIBLE_ARBITRAGE)

        return active

    def _build_summary(
        self,
        trend: RegimeType,
        volatility: VolatilityLevel,
        breadth: MarketBreadth,
        sentiment: SentimentLevel,
        active: List[StrategyType],
    ) -> str:
        trend_map = {
            RegimeType.BULL: "牛市",
            RegimeType.BEAR: "熊市",
            RegimeType.RANGE: "震荡市",
        }
        vol_map = {
            VolatilityLevel.HIGH: "高波动",
            VolatilityLevel.NORMAL: "正常波动",
            VolatilityLevel.LOW: "低波动",
        }
        breadth_map = {
            MarketBreadth.BROAD: "普涨",
            MarketBreadth.NARROW: "分化",
        }
        sentiment_map = {
            SentimentLevel.EUPHORIC: "狂热",
            SentimentLevel.NEUTRAL: "中性",
            SentimentLevel.PANIC: "恐慌",
        }
        strategy_map = {
            StrategyType.EXTREME_REVERSAL: "极端反转",
            StrategyType.TURNAROUND: "困境反转",
            StrategyType.SMALL_CAP_VALUE: "小盘价值",
            StrategyType.CONVERTIBLE_ARBITRAGE: "转债博弈",
        }
        env_str = (
            f"{trend_map[trend]}+{vol_map[volatility]}+"
            f"{breadth_map[breadth]}+{sentiment_map[sentiment]}"
        )
        strategy_str = "、".join(strategy_map[s] for s in active)
        return f"当前市场环境：{env_str}。建议激活策略：{strategy_str}。"
