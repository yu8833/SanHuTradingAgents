"""
量价配合策略服务

策略逻辑：基于成交量与价格的配合关系进行选股，识别健康的上涨趋势。

放量上涨：价格上涨且成交量放大（买入信号）
缩量回调：价格回调但成交量萎缩（健康回调，可逢低买入）

评分维度：
- 量价配合度：涨幅与成交量变化的相关性（0-30分）
- 量能等级：成交量相对于近20日均量的倍数（0-25分）
- 价格形态：阳线实体大小（0-20分）
- 相对位置：当前价格在近20日的位置（0-15分）
- 趋势延续：连续上涨天数（0-10分）
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class VolumePriceService(RetailScreeningBase):
    """量价配合策略"""

    async def scan_volume_price(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描量价配合候选股

        参数：
            min_score: int = 40  # 最低评分
            limit: int = 50  # 返回数量
            lookback_days: int = 60  # 历史数据天数
            min_volume_ratio: float = 1.2  # 最小放量比例
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
            f"量价配合扫描: {len(candidates)} 个候选股, 开始获取历史数据"
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
                if len(quotes) < 30:
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

    def _calc_correlation(self, x: np.ndarray, y: np.ndarray) -> float:
        """计算两个数组的皮尔逊相关系数"""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        valid_mask = (x != 0) & (y != 0)
        x_valid = x[valid_mask]
        y_valid = y[valid_mask]
        if len(x_valid) < 2:
            return 0.0
        return float(np.corrcoef(x_valid, y_valid)[0, 1])

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

        if len(closes) < 60 or len(volumes) < 60:
            return None

        # 计算MA60
        ma60 = np.convolve(closes, np.ones(60)/60, mode='valid')
        if len(ma60) < 1:
            return None

        # MA60大趋势过滤：只做上升趋势中的股票（收盘价 > MA60）
        ma60_last = float(ma60[-1])
        if close <= ma60_last:
            return None

        # 计算价格变化和成交量变化
        price_changes = np.diff(closes) / closes[:-1]
        volume_changes = np.diff(volumes) / np.maximum(volumes[:-1], 1)

        # 量价配合度评分（0-30分）
        correlation_score = 0.0
        correlation_value = 0.0
        if len(price_changes) >= 20 and len(volume_changes) >= 20:
            recent_price_changes = price_changes[-20:]
            recent_volume_changes = volume_changes[-20:]
            correlation = self._calc_correlation(recent_price_changes, recent_volume_changes)
            correlation_value = float(correlation)
            if correlation > 0:
                correlation_score = float(min(30, correlation * 50))

        # 量能等级评分（0-25分）
        volume_score = 0
        if len(volumes) >= 20:
            vol_ma20 = float(np.mean(volumes[-20:]))
            if vol_ma20 > 0:
                vol_ratio = float(volumes[-1] / vol_ma20)
                if vol_ratio >= 2.0:
                    volume_score = 25
                elif vol_ratio >= 1.5:
                    volume_score = 20
                elif vol_ratio >= 1.2:
                    volume_score = 15
                elif vol_ratio >= 1.0:
                    volume_score = 8
                elif vol_ratio >= 0.8:
                    volume_score = 4

        # 价格形态评分（0-20分）
        pattern_score = 0
        if len(quotes) >= 1:
            today = quotes[-1]
            today_open = today.get("open", close)
            today_close = today.get("close", close)
            today_high = today.get("high", close)
            today_low = today.get("low", close)

            if today_open > 0 and today_close > 0 and today_high > today_low:
                body = abs(today_close - today_open)
                range_ = today_high - today_low

                if body > 0 and range_ > 0:
                    body_ratio = body / range_
                    if today_close > today_open:
                        if body_ratio >= 0.7:
                            pattern_score = 20
                        elif body_ratio >= 0.5:
                            pattern_score = 15
                        elif body_ratio >= 0.3:
                            pattern_score = 10
                        else:
                            pattern_score = 5
                    elif today_close < today_open:
                        if body_ratio >= 0.7 and pct_chg > -2:
                            pattern_score = 15
                        elif body_ratio >= 0.5:
                            pattern_score = 10
                        else:
                            pattern_score = 5

        # 相对位置评分（0-15分）
        position_score = 0
        if len(closes) >= 20:
            recent_closes = closes[-20:]
            low_20 = float(np.min(recent_closes))
            high_20 = float(np.max(recent_closes))
            if high_20 > low_20:
                position = float((close - low_20) / (high_20 - low_20))
                if position >= 0.7 and position <= 0.95:
                    position_score = 15
                elif position >= 0.5 and position <= 0.7:
                    position_score = 10
                elif position >= 0.3 and position <= 0.5:
                    position_score = 5
                elif position > 0.95:
                    position_score = 3

        # 趋势延续评分（0-10分）
        trend_score = 0
        consecutive_up = 0
        for i in range(len(quotes)-1, max(0, len(quotes)-10), -1):
            q = quotes[i]
            pct = q.get("pct_chg", 0) or 0
            if pct > 0:
                consecutive_up += 1
            else:
                break

        if consecutive_up >= 5:
            trend_score = 10
        elif consecutive_up >= 3:
            trend_score = 7
        elif consecutive_up >= 2:
            trend_score = 4
        elif consecutive_up >= 1:
            trend_score = 2

        # 趋势强度评分（0-10分）：收盘价在MA60上方的比例
        trend_strength_score = 0
        if len(ma60) > 0 and len(closes) >= len(ma60):
            close_aligned = closes[-len(ma60):]
            above_ma60 = int(np.sum(close_aligned > ma60))
            trend_strength_ratio = float(above_ma60 / len(ma60)) if len(ma60) > 0 else 0.0
            trend_strength_score = min(10, trend_strength_ratio * 10)
        trend_strength_score = round(float(trend_strength_score), 1)

        # 信号类型判定
        signal_type = "无信号"
        if pct_chg > 0 and volume_score >= 15:
            signal_type = "放量上涨"
        elif pct_chg <= 0 and volume_score <= 5 and pct_chg > -3:
            signal_type = "缩量回调"
        elif pct_chg > 0 and volume_score >= 8:
            signal_type = "温和上涨"
        elif pct_chg > 0:
            signal_type = "上涨"
        elif pct_chg < 0:
            signal_type = "下跌"

        total_score = (
            correlation_score +
            volume_score +
            pattern_score +
            position_score +
            trend_score +
            trend_strength_score
        )

        score_details = {
            "量价配合度": round(correlation_score, 1),
            "量能等级": volume_score,
            "价格形态": pattern_score,
            "相对位置": position_score,
            "趋势延续": trend_score,
            "趋势强度": trend_strength_score,
        }

        if total_score < 20:
            return None

        # 计算近20日成交量倍数
        vol_ma20_final = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else 0.0
        vol_ratio_final = float(volumes[-1] / vol_ma20_final) if vol_ma20_final > 0 else 0.0

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
            "volume_ratio": round(vol_ratio_final, 2),
            "volume_multiple": round(vol_ratio_final, 2),
            "price_volume_correlation": round(correlation_value, 4),
            "consecutive_up_days": consecutive_up,
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
                if len(quotes) < 30:
                    continue
                result = self._analyze_stock(code, sv, quotes)
                if result:
                    items.append(result)
            return items

        return await self.run_backtest("volume_price", scan_func, params)


_service: Optional[VolumePriceService] = None


def get_volume_price_service() -> VolumePriceService:
    global _service
    if _service is None:
        _service = VolumePriceService()
    return _service