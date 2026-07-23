"""
极端情绪反转策略服务

策略逻辑：寻找连续跌停后恐慌超跌的股票，当基本面未实质性恶化时，博弈超跌反弹。

散户优势：量化在暴跌时受风控约束减仓，机构受净值压力不敢接刀，
逆向买入需要行为优势而非信息优势。

扫描条件：
- 近期出现连续跌停（≥2个）
- 累计跌幅大（从高点跌超30%或近期连跌超15%）
- 估值处于历史低位（PE/PB分位≤20%）
- 非ST股、非退市风险股
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class ExtremeReversalService(RetailScreeningBase):
    """极端情绪反转策略"""

    async def scan_extreme_reversal(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描极端反转候选股

        参数：
            min_consecutive_down: int = 2  # 最少连续下跌天数
            min_total_drop_pct: float = 0.15  # 最小累计跌幅
            min_score: int = 40  # 最低评分
            limit: int = 50  # 返回数量
        """
        start_time = time.time()
        params = params or {}
        min_consecutive_down = params.get("min_consecutive_down", 2)
        min_total_drop_pct = params.get("min_total_drop_pct", 0.15)
        min_score = params.get("min_score", 40)
        limit = params.get("limit", 50)

        # 1. 获取全部股票的当前行情+估值
        screening_data = await self._get_screening_view_batch()

        # 2. 筛选候选：有跌幅信号的股票（当日跌幅<-5% 或 近期持续下跌）
        candidates = []
        for code, data in screening_data.items():
            pct_chg = data.get("pct_chg", 0) or 0
            # 当日大跌（<-5%）或停牌前有跌幅
            if pct_chg < -5:
                candidates.append(code)

        # 如果候选太少，放宽条件：取所有PE>0的股票
        if len(candidates) < 50:
            candidates = [
                code
                for code, data in screening_data.items()
                if data.get("pe", 0) and data["pe"] > 0
            ][:500]

        logger.info(
            f"极端反转扫描: {len(candidates)} 个候选股, 开始获取历史数据"
        )

        # 3. 批量获取历史K线（60天）
        today = datetime.now().strftime("%Y-%m-%d")
        quotes_map = await self._batch_get_quotes(
            candidates, today, days=60, concurrency=100
        )

        # 4. 逐个分析
        semaphore = asyncio.Semaphore(50)
        items = []

        async def analyze_one(code: str):
            async with semaphore:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                if len(quotes) < 20:
                    return None

                result = self._analyze_stock(
                    code, sv, quotes, min_consecutive_down, min_total_drop_pct
                )
                if result and result["score"] >= min_score:
                    return result
                return None

        tasks = [analyze_one(c) for c in candidates]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                items.append(r)

        # 5. 排序+截断
        items.sort(key=lambda x: x["score"], reverse=True)
        items = items[:limit]

        # 6. 风险过滤（排除高风险股票，保留的附加风险信息）
        items = await self._apply_risk_filter(items, screening_data)

        took_ms = int((time.time() - start_time) * 1000)
        return {
            "total": len(items),
            "items": items,
            "took_ms": took_ms,
            "params": params,
            "scanned_count": len(candidates),
        }

    def _analyze_stock(
        self,
        code: str,
        sv: dict,
        quotes: List[dict],
        min_consecutive_down: int,
        min_total_drop_pct: float,
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

        if close <= 0:
            return None

        # 排除ST
        if "ST" in name or "*ST" in name:
            return None

        closes = np.array([q["close"] for q in quotes], dtype=float)
        pct_chgs = np.array([q.get("pct_chg", 0) for q in quotes], dtype=float)

        # 1. 检测连续下跌
        consecutive_down = 0
        for p in reversed(pct_chgs):
            if p < 0:
                consecutive_down += 1
            else:
                break

        # 2. 累计跌幅（近20天）
        lookback = min(20, len(closes))
        if lookback < 5:
            return None
        recent_closes = closes[-lookback:]
        total_drop_pct = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]

        # 3. 跌停天数
        limit_down_days = sum(
            1 for p in pct_chgs[-10:] if self._is_limit_down(p, market)
        )

        # 4. 从60日高点的回撤
        high_60 = float(np.max(closes))
        drawdown_from_high = (close - high_60) / high_60

        # 5. 估值分位（简化：用PE/PB绝对值判断）
        pe_percentile = 0.5  # 默认中位
        if pe > 0:
            if pe < 10:
                pe_percentile = 0.1
            elif pe < 20:
                pe_percentile = 0.25
            elif pe < 30:
                pe_percentile = 0.5
            else:
                pe_percentile = 0.8

        pb_percentile = 0.5
        if pb > 0:
            if pb < 1:
                pb_percentile = 0.1
            elif pb < 2:
                pb_percentile = 0.3
            elif pb < 3:
                pb_percentile = 0.5
            else:
                pb_percentile = 0.8

        # 6. 信号判定
        signal_type = "观察"
        if limit_down_days >= 2 and drawdown_from_high < -0.15:
            signal_type = "恐慌超跌"
        elif consecutive_down >= min_consecutive_down and total_drop_pct < -min_total_drop_pct:
            signal_type = "连续下跌"
        elif drawdown_from_high < -0.30:
            signal_type = "高位回撤"

        # 7. 评分
        score = 0
        score_details = {}

        # 连续下跌评分（0-30分）
        down_score = min(30, consecutive_down * 8)
        score += down_score
        score_details["连续下跌"] = down_score

        # 累计跌幅评分（0-25分）
        drop_score = min(25, abs(total_drop_pct) * 100)
        score += drop_score
        score_details["累计跌幅"] = round(drop_score, 1)

        # 跌停天数评分（0-20分）
        ld_score = min(20, limit_down_days * 10)
        score += ld_score
        score_details["跌停天数"] = ld_score

        # 估值评分（0-15分）
        val_score = 0
        if pe_percentile <= 0.25:
            val_score += 8
        if pb_percentile <= 0.3:
            val_score += 7
        score += val_score
        score_details["估值低位"] = val_score

        # 回撤评分（0-10分）
        dd_score = min(10, abs(drawdown_from_high) * 20)
        score += dd_score
        score_details["高位回撤"] = round(dd_score, 1)

        if score < 20:
            return None

        return {
            "code": code,
            "name": name,
            "industry": industry,
            "close": round(close, 2),
            "pct_chg": round(pct_chg, 2),
            "consecutive_down_days": consecutive_down,
            "total_drop_pct": round(float(total_drop_pct), 4),
            "limit_down_days": limit_down_days,
            "drawdown_from_high": round(float(drawdown_from_high), 4),
            "pe": round(pe, 2) if pe > 0 else None,
            "pb": round(pb, 2) if pb > 0 else None,
            "total_mv": round(total_mv, 2),
            "pe_percentile": pe_percentile,
            "pb_percentile": pb_percentile,
            "signal_type": signal_type,
            "score": int(score),
            "score_details": score_details,
            "high_60": round(high_60, 2),
        }

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """回测"""
        params = params or {}

        async def scan_func(date_str: str) -> List[dict]:
            """回测扫描函数：在指定日期扫描"""
            # 获取该日期之前的所有股票行情
            screening_data = await self._get_screening_view_batch()
            candidates = list(screening_data.keys())[:300]

            quotes_map = await self._batch_get_quotes(
                candidates, date_str, days=60, concurrency=50
            )

            items = []
            for code in candidates:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                if len(quotes) < 20:
                    continue
                result = self._analyze_stock(
                    code, sv, quotes,
                    params.get("min_consecutive_down", 2),
                    params.get("min_total_drop_pct", 0.15),
                )
                if result:
                    items.append(result)
            return items

        return await self.run_backtest("extreme_reversal", scan_func, params)


_service: Optional[ExtremeReversalService] = None


def get_extreme_reversal_service() -> ExtremeReversalService:
    global _service
    if _service is None:
        _service = ExtremeReversalService()
    return _service
