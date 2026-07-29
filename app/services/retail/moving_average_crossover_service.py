"""
均线交叉策略服务

策略逻辑：基于均线金叉/死叉信号进行选股，结合成交量、趋势和位置综合评分。

金叉：短期均线上穿长期均线（MA5上穿MA10，或MA10上穿MA20）
死叉：短期均线下穿长期均线（MA5下穿MA10，或MA10下穿MA20）

评分维度：
- 金叉强度：两条均线距离变化率（0-30分）
- 成交量配合：金叉时放量（0-25分）
- 趋势方向：股价在MA60上方（0-20分）
- MACD辅助：MACD正值且红柱增长（0-15分）
- 位置：从低位启动（0-10分）
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class MovingAverageCrossoverService(RetailScreeningBase):
    """均线交叉策略"""

    async def scan_moving_average_crossover(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描均线交叉候选股

        参数：
            min_score: int = 40  # 最低评分
            limit: int = 50  # 返回数量
            lookback_days: int = 60  # 历史数据天数
        """
        start_time = time.time()
        params = params or {}
        limit = params.get("limit", 50)
        lookback_days = params.get("lookback_days", 60)

        screening_data = await self._get_screening_view_batch()

        sorted_codes = sorted(
            screening_data.keys(),
            key=lambda c: screening_data[c].get("amount", 0) or 0,
            reverse=True
        )
        candidates = sorted_codes

        logger.info(
            f"均线交叉扫描: {len(candidates)} 个候选股, 开始获取历史数据"
        )

        today = datetime.now().strftime("%Y-%m-%d")
        quotes_map = await self._batch_get_quotes(
            candidates, today, days=lookback_days, concurrency=100
        )

        semaphore = asyncio.Semaphore(200)
        items = []

        async def analyze_one(code: str):
            async with semaphore:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                if len(quotes) < 40:
                    return None

                result = self._analyze_stock(code, sv, quotes)
                return result

        tasks = [analyze_one(c) for c in candidates]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                items.append(r)

        items.sort(key=lambda x: x["score"], reverse=True)
        items = items[:limit]

        items = await self._apply_risk_filter(items, screening_data)

        took_ms = int((time.time() - start_time) * 1000)
        return {
            "total": len(items),
            "items": items,
            "took_ms": took_ms,
            "params": params,
            "scanned_count": len(candidates),
        }

    def _calc_ma_vectorized(self, closes: np.ndarray, periods: List[int]) -> Dict[int, np.ndarray]:
        """向量化计算多个周期的均线"""
        result = {}
        for period in periods:
            if len(closes) >= period:
                result[period] = np.convolve(closes, np.ones(period)/period, mode='valid')
            else:
                result[period] = np.array([])
        return result

    def _calc_macd(self, closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[tuple]:
        """计算MACD指标"""
        if len(closes) < slow + signal:
            return None

        ema_fast = self._calc_ema(closes, fast)
        ema_slow = self._calc_ema(closes, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self._calc_ema(macd_line, signal)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def _calc_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _analyze_stock(
        self,
        code: str,
        sv: dict,
        quotes: List[dict],
    ) -> Optional[dict]:
        """分析单只股票"""
        name = sv.get("name", "")
        industry = sv.get("industry", "")
        market = sv.get("market", "主板")
        pe = sv.get("pe", 0) or 0
        pb = sv.get("pb", 0) or 0
        total_mv = sv.get("total_mv", 0) or 0
        close = sv.get("close", 0) or 0
        pct_chg = sv.get("pct_chg", 0) or 0
        volume = sv.get("volume", 0) or 0

        if close <= 0:
            return None

        if "ST" in name or "*ST" in name:
            return None

        closes = np.array([q["close"] for q in quotes], dtype=float)
        volumes = np.array([q.get("volume", 0) for q in quotes], dtype=float)

        ma_dict = self._calc_ma_vectorized(closes, [5, 10, 20, 60])

        ma5 = ma_dict[5]
        ma10 = ma_dict[10]
        ma20 = ma_dict[20]
        ma60 = ma_dict[60]

        if len(ma5) < 3 or len(ma10) < 3 or len(ma20) < 3 or len(ma60) < 3:
            return None

        # MA60大趋势过滤：只做上升趋势中的股票（收盘价 > MA60）
        if close <= ma60[-1]:
            return None

        signal_type = "无信号"
        crossover_type = None

        # 检测金叉/死叉
        ma5_above_ma10 = ma5[-1] > ma10[-1]
        ma5_below_ma10 = ma5[-1] < ma10[-1]
        ma5_cross_ma10_prev = ma5[-2] <= ma10[-2] and ma5[-1] > ma10[-1]
        ma5_cross_ma10_below = ma5[-2] >= ma10[-2] and ma5[-1] < ma10[-1]

        ma10_above_ma20 = ma10[-1] > ma20[-1]
        ma10_below_ma20 = ma10[-1] < ma20[-1]
        ma10_cross_ma20_prev = ma10[-2] <= ma20[-2] and ma10[-1] > ma20[-1]
        ma10_cross_ma20_below = ma10[-2] >= ma20[-2] and ma10[-1] < ma20[-1]

        if ma5_cross_ma10_prev or ma10_cross_ma20_prev:
            signal_type = "金叉"
            crossover_type = "MA5上穿MA10" if ma5_cross_ma10_prev else "MA10上穿MA20"
        elif ma5_cross_ma10_below or ma10_cross_ma20_below:
            signal_type = "死叉"
            crossover_type = "MA5下穿MA10" if ma5_cross_ma10_below else "MA10下穿MA20"
        elif ma5_above_ma10 and ma10_above_ma20:
            signal_type = "多头排列"
        elif ma5_below_ma10 and ma10_below_ma20:
            signal_type = "空头排列"

        if signal_type == "无信号":
            return None

        # 金叉强度评分（0-30分）
        cross_strength_score = 0
        ma5_last = float(ma5[-1])
        ma5_prev = float(ma5[-2])
        ma10_last = float(ma10[-1])
        ma10_prev = float(ma10[-2])
        ma20_last = float(ma20[-1])
        ma20_prev = float(ma20[-2])
        if signal_type == "金叉":
            if ma5_cross_ma10_prev:
                diff_change = (ma5_last - ma10_last) - (ma5_prev - ma10_prev)
                diff_ratio = abs(diff_change) / max(ma10_last, 0.01)
                cross_strength_score = min(30, diff_ratio * 5000)
            else:
                diff_change = (ma10_last - ma20_last) - (ma10_prev - ma20_prev)
                diff_ratio = abs(diff_change) / max(ma20_last, 0.01)
                cross_strength_score = min(30, diff_ratio * 3000)
        elif signal_type == "死叉":
            if ma5_cross_ma10_below:
                diff_change = (ma10_last - ma5_last) - (ma10_prev - ma5_prev)
                diff_ratio = abs(diff_change) / max(ma10_last, 0.01)
                cross_strength_score = min(30, diff_ratio * 5000)
            else:
                diff_change = (ma20_last - ma10_last) - (ma20_prev - ma10_prev)
                diff_ratio = abs(diff_change) / max(ma20_last, 0.01)
                cross_strength_score = min(30, diff_ratio * 3000)
        cross_strength_score = round(float(cross_strength_score), 1)

        # 成交量配合评分（0-25分）
        volume_score = 0
        if len(volumes) >= 20:
            vol_ma20 = float(np.mean(volumes[-20:]))
            if vol_ma20 > 0:
                vol_ratio = float(volumes[-1] / vol_ma20)
                if signal_type == "金叉":
                    if vol_ratio >= 1.5:
                        volume_score = 25
                    elif vol_ratio >= 1.2:
                        volume_score = 18
                    elif vol_ratio >= 1.0:
                        volume_score = 10
                    else:
                        volume_score = 0
                elif signal_type == "死叉":
                    if vol_ratio >= 1.5:
                        volume_score = 20
                    elif vol_ratio >= 1.2:
                        volume_score = 15
                    else:
                        volume_score = 0
                else:
                    if vol_ratio >= 1.3:
                        volume_score = 15
                    elif vol_ratio >= 1.0:
                        volume_score = 8

        # 趋势方向评分（0-20分）
        trend_score = 0
        ma60_last = float(ma60[-1])
        if close > ma60_last:
            trend_score = 20
        elif close > ma60_last * 0.98:
            trend_score = 15
        elif close > ma60_last * 0.95:
            trend_score = 10
        else:
            trend_score = 0

        # MACD辅助评分（0-15分）
        macd_score = 0
        macd_result = self._calc_macd(closes)
        if macd_result:
            macd_line, signal_line, histogram = macd_result
            if len(histogram) >= 2:
                macd_line_last = float(macd_line[-1])
                hist_last = float(histogram[-1])
                hist_prev = float(histogram[-2])
                if signal_type == "金叉":
                    if macd_line_last > 0 and hist_last > hist_prev and hist_last > 0:
                        macd_score = 15
                    elif macd_line_last > 0 and hist_last > 0:
                        macd_score = 10
                    elif macd_line_last > 0:
                        macd_score = 5
                elif signal_type == "死叉":
                    if macd_line_last < 0 and hist_last < hist_prev and hist_last < 0:
                        macd_score = 15
                    elif macd_line_last < 0 and hist_last < 0:
                        macd_score = 10
                    elif macd_line_last < 0:
                        macd_score = 5

        # 位置评分（0-10分）
        position_score = 0
        if len(closes) >= 60:
            low_60 = float(np.min(closes[-60:]))
            high_60 = float(np.max(closes[-60:]))
            if high_60 > low_60:
                position = float((close - low_60) / (high_60 - low_60))
                if signal_type == "金叉":
                    if position <= 0.3:
                        position_score = 10
                    elif position <= 0.5:
                        position_score = 7
                    elif position <= 0.7:
                        position_score = 4
                    else:
                        position_score = 0
                elif signal_type == "死叉":
                    if position >= 0.7:
                        position_score = 10
                    elif position >= 0.5:
                        position_score = 7
                    elif position >= 0.3:
                        position_score = 4
                    else:
                        position_score = 0

        # 趋势强度评分（0-10分）：收盘价在MA60上方的比例
        trend_strength_score = 0
        if len(ma60) > 0 and len(closes) >= len(ma60):
            close_aligned = closes[-len(ma60):]
            above_ma60 = int(np.sum(close_aligned > ma60))
            trend_strength_ratio = float(above_ma60 / len(ma60)) if len(ma60) > 0 else 0.0
            trend_strength_score = min(10, trend_strength_ratio * 10)
        trend_strength_score = round(float(trend_strength_score), 1)

        total_score = (
            cross_strength_score +
            volume_score +
            trend_score +
            macd_score +
            position_score +
            trend_strength_score
        )

        score_details = {
            "金叉强度": round(cross_strength_score, 1),
            "成交量配合": volume_score,
            "趋势方向": trend_score,
            "MACD辅助": macd_score,
            "位置": position_score,
            "趋势强度": trend_strength_score,
        }

        if total_score < 20:
            return None

        return {
            "code": code,
            "name": name,
            "industry": industry,
            "close": round(close, 2),
            "pct_chg": round(pct_chg, 2),
            "pe": round(pe, 2) if pe > 0 else None,
            "pb": round(pb, 2) if pb > 0 else None,
            "total_mv": round(total_mv, 2),
            "signal_type": signal_type,
            "crossover_type": crossover_type,
            "score": int(total_score),
            "score_details": score_details,
            "ma5": round(float(ma5[-1]), 2),
            "ma10": round(float(ma10[-1]), 2),
            "ma20": round(float(ma20[-1]), 2),
            "ma60": round(float(ma60[-1]), 2),
            "volume": volume,
            "market": market,
        }

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """回测"""
        params = params or {}

        async def scan_func(date_str: str) -> List[dict]:
            screening_data = await self._get_screening_view_for_date(date_str)
            sorted_codes = sorted(
                screening_data.keys(),
                key=lambda c: screening_data[c].get("amount", 0) or 0,
                reverse=True
            )
            candidates = sorted_codes[:1500]

            if not candidates:
                return []

            quotes_map = await self._batch_get_quotes(
                candidates, date_str, days=60, concurrency=50
            )

            items = []
            for code in candidates:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                if len(quotes) < 40:
                    continue
                result = self._analyze_stock(code, sv, quotes)
                if result:
                    items.append(result)
            return items

        return await self.run_backtest("moving_average_crossover", scan_func, params)


_service: Optional[MovingAverageCrossoverService] = None


def get_moving_average_crossover_service() -> MovingAverageCrossoverService:
    global _service
    if _service is None:
        _service = MovingAverageCrossoverService()
    return _service