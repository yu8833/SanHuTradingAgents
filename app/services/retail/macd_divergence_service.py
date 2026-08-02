"""
MACD背离策略服务

策略逻辑：基于MACD与股价的背离信号进行选股，识别趋势反转机会。

底背离：股价创新低，但MACD不创新低（买入信号）
顶背离：股价创新高，但MACD不创新高（卖出信号）

评分维度：
- 背离强度：股价与MACD的背离程度（0-30分）
- 背离持续时间：背离出现后的天数（0-20分）
- 成交量确认：底背离时成交量萎缩（0-25分）
- 均线位置：底背离时股价接近MA60（0-15分）
- 趋势确认：背离后出现阳线（0-10分）
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import numpy as np

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class MacdDivergenceService(RetailScreeningBase):
    """MACD背离策略"""

    async def scan_macd_divergence(
        self, params: dict[str, Any] = None
    ) -> dict[str, Any]:
        """
        扫描MACD背离候选股

        参数：
            min_score: int = 40  # 最低评分
            limit: int = 50  # 返回数量
            lookback_days: int = 120  # 历史数据天数
            divergence_window: int = 30  # 背离检测窗口
        """
        start_time = time.time()
        params = params or {}
        limit = params.get("limit", 50)
        lookback_days = params.get("lookback_days", 120)

        screening_data = await self._get_screening_view_batch()

        sorted_codes = sorted(
            screening_data.keys(),
            key=lambda c: screening_data[c].get("amount", 0) or 0,
            reverse=True
        )
        candidates = sorted_codes

        logger.info(
            f"MACD背离扫描: {len(candidates)} 个候选股, 开始获取历史数据"
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
                if len(quotes) < 60:
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

    def _calc_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _calc_macd(self, closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple | None:
        """计算MACD指标"""
        if len(closes) < slow + signal:
            return None

        ema_fast = self._calc_ema(closes, fast)
        ema_slow = self._calc_ema(closes, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self._calc_ema(macd_line, signal)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def _calc_ma(self, closes: np.ndarray, period: int) -> np.ndarray | None:
        """计算均线"""
        if len(closes) < period:
            return None
        return np.convolve(closes, np.ones(period)/period, mode='valid')

    def _find_divergence(
        self,
        closes: np.ndarray,
        macd_histogram: np.ndarray,
        window: int = 30,
    ) -> dict | None:
        """
        检测MACD背离信号

        Returns:
            {
                'type': 'bottom' | 'top' | None,
                'strength': float,
                'duration_days': int,
                'price_extreme': float,
                'macd_extreme': float,
                'recent_price': float,
                'recent_macd': float,
            }
        """
        if len(closes) < window * 2 or len(macd_histogram) < window * 2:
            return None

        recent_window = closes[-window:]
        macd_recent = macd_histogram[-window:]

        if len(recent_window) < window or len(macd_recent) < window:
            return None

        recent_low = float(np.min(recent_window))
        recent_high = float(np.max(recent_window))
        recent_low_idx = int(np.argmin(recent_window))
        recent_high_idx = int(np.argmax(recent_window))

        prev_window = closes[-window*2:-window]
        macd_prev = macd_histogram[-window*2:-window]

        if len(prev_window) < window or len(macd_prev) < window:
            return None

        prev_low = float(np.min(prev_window))
        prev_high = float(np.max(prev_window))
        prev_low_idx = int(np.argmin(prev_window))
        prev_high_idx = int(np.argmax(prev_window))

        result = None

        # 底背离检测：股价创新低，MACD不创新低
        if recent_low < prev_low:
            recent_macd_at_low = macd_recent[recent_low_idx]
            prev_macd_at_low = macd_prev[prev_low_idx]

            if recent_macd_at_low > prev_macd_at_low:
                strength = float(abs(recent_macd_at_low - prev_macd_at_low) / max(abs(prev_macd_at_low), 0.01))
                duration = int(len(recent_window) - recent_low_idx)

                result = {
                    'type': 'bottom',
                    'strength': strength,
                    'duration_days': duration,
                    'price_extreme': recent_low,
                    'macd_extreme': float(recent_macd_at_low),
                    'prev_price_extreme': prev_low,
                    'prev_macd_extreme': float(prev_macd_at_low),
                    'recent_price': float(closes[-1]),
                    'recent_macd': float(macd_recent[-1]),
                }

        # 顶背离检测：股价创新高，MACD不创新高
        if recent_high > prev_high:
            recent_macd_at_high = macd_recent[recent_high_idx]
            prev_macd_at_high = macd_prev[prev_high_idx]

            if recent_macd_at_high < prev_macd_at_high:
                strength = float(abs(prev_macd_at_high - recent_macd_at_high) / max(abs(prev_macd_at_high), 0.01))
                duration = int(len(recent_window) - recent_high_idx)

                result = {
                    'type': 'top',
                    'strength': strength,
                    'duration_days': duration,
                    'price_extreme': recent_high,
                    'macd_extreme': float(recent_macd_at_high),
                    'prev_price_extreme': prev_high,
                    'prev_macd_extreme': float(prev_macd_at_high),
                    'recent_price': float(closes[-1]),
                    'recent_macd': float(macd_recent[-1]),
                }

        return result

    def _analyze_stock(
        self,
        code: str,
        sv: dict,
        quotes: list[dict],
    ) -> dict | None:
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

        macd_result = self._calc_macd(closes)
        if not macd_result:
            return None

        macd_line, signal_line, histogram = macd_result

        if len(histogram) < 60:
            return None

        ma60 = self._calc_ma(closes, 60)
        if ma60 is None or len(ma60) < 5:
            return None

        # MA60大趋势过滤：只做上升趋势中的股票（收盘价 > MA60）
        if close <= ma60[-1]:
            return None

        divergence = self._find_divergence(closes, histogram, window=30)

        if not divergence:
            return None

        signal_type = "底背离" if divergence["type"] == "bottom" else "顶背离"

        # 背离强度评分（0-30分）
        strength_score = float(min(30, divergence["strength"] * 100))

        # 背离持续时间评分（0-20分）
        duration_score = 0
        duration = divergence["duration_days"]
        if duration >= 5:
            duration_score = 20
        elif duration >= 3:
            duration_score = 15
        elif duration >= 2:
            duration_score = 10
        elif duration >= 1:
            duration_score = 5

        # 成交量确认评分（0-25分）
        volume_score = 0
        if len(volumes) >= 40:
            vol_ma20 = float(np.mean(volumes[-20:]))
            vol_ma40 = float(np.mean(volumes[-40:]))
            if vol_ma20 > 0 and vol_ma40 > 0:
                vol_ratio = float(vol_ma20 / vol_ma40)
                if divergence["type"] == "bottom":
                    if vol_ratio <= 0.6:
                        volume_score = 25
                    elif vol_ratio <= 0.8:
                        volume_score = 18
                    elif vol_ratio <= 1.0:
                        volume_score = 10
                    else:
                        volume_score = 0
                else:
                    if vol_ratio >= 1.5:
                        volume_score = 25
                    elif vol_ratio >= 1.3:
                        volume_score = 18
                    elif vol_ratio >= 1.1:
                        volume_score = 10
                    else:
                        volume_score = 0

        # 均线位置评分（0-15分）
        ma_position_score = 0
        ma60_last = float(ma60[-1])
        if divergence["type"] == "bottom":
            price_to_ma60_ratio = float(close / ma60_last)
            if price_to_ma60_ratio >= 0.95 and price_to_ma60_ratio <= 1.05:
                ma_position_score = 15
            elif price_to_ma60_ratio >= 0.90 and price_to_ma60_ratio <= 1.10:
                ma_position_score = 10
            elif price_to_ma60_ratio >= 0.85 and price_to_ma60_ratio <= 1.15:
                ma_position_score = 5
        else:
            price_to_ma60_ratio = float(close / ma60_last)
            if price_to_ma60_ratio >= 0.95 and price_to_ma60_ratio <= 1.05:
                ma_position_score = 15
            elif price_to_ma60_ratio >= 0.90 and price_to_ma60_ratio <= 1.10:
                ma_position_score = 10

        # 趋势确认评分（0-10分）
        trend_conf_score = 0
        if len(quotes) >= 2:
            today_open = quotes[-1].get("open", close)
            today_close = quotes[-1].get("close", close)
            yesterday_close = quotes[-2].get("close", close)

            if divergence["type"] == "bottom":
                if today_close > today_open and today_close > yesterday_close:
                    trend_conf_score = 10
                elif today_close > today_open:
                    trend_conf_score = 6
                elif today_close > yesterday_close:
                    trend_conf_score = 3
            else:
                if today_close < today_open and today_close < yesterday_close:
                    trend_conf_score = 10
                elif today_close < today_open:
                    trend_conf_score = 6
                elif today_close < yesterday_close:
                    trend_conf_score = 3

        # 趋势强度评分（0-10分）：收盘价在MA60上方的比例
        trend_strength_score = 0
        if len(ma60) > 0 and len(closes) >= len(ma60):
            close_aligned = closes[-len(ma60):]
            above_ma60 = int(np.sum(close_aligned > ma60))
            trend_strength_ratio = float(above_ma60 / len(ma60)) if len(ma60) > 0 else 0.0
            trend_strength_score = min(10, trend_strength_ratio * 10)
        trend_strength_score = round(float(trend_strength_score), 1)

        total_score = (
            strength_score +
            duration_score +
            volume_score +
            ma_position_score +
            trend_conf_score +
            trend_strength_score
        )

        score_details = {
            "背离强度": round(strength_score, 1),
            "背离持续时间": duration_score,
            "成交量确认": volume_score,
            "均线位置": ma_position_score,
            "趋势确认": trend_conf_score,
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
            "score": int(total_score),
            "score_details": score_details,
            "divergence_strength": round(divergence["strength"], 4),
            "divergence_duration": divergence["duration_days"],
            "price_extreme": round(divergence["price_extreme"], 2),
            "macd_extreme": round(divergence["macd_extreme"], 4),
            "ma60": round(float(ma60[-1]), 2),
            "macd_line": round(float(macd_line[-1]), 4) if len(macd_line) > 0 else None,
            "signal_line": round(float(signal_line[-1]), 4) if len(signal_line) > 0 else None,
            "histogram": round(float(histogram[-1]), 4) if len(histogram) > 0 else None,
            "volume": volume,
            "market": market,
        }

    async def backtest(self, params: dict[str, Any] = None) -> dict[str, Any]:
        """回测"""
        params = params or {}

        async def scan_func(date_str: str) -> list[dict]:
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
                candidates, date_str, days=120, concurrency=50
            )

            items = []
            for code in candidates:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                if len(quotes) < 60:
                    continue
                result = self._analyze_stock(code, sv, quotes)
                if result:
                    items.append(result)
            return items

        return await self.run_backtest("macd_divergence", scan_func, params)


_service: MacdDivergenceService | None = None


def get_macd_divergence_service() -> MacdDivergenceService:
    global _service
    if _service is None:
        _service = MacdDivergenceService()
    return _service