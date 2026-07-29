"""
困境反转策略服务

策略逻辑：寻找"最差时候已过去"的公司，在底部区域布局，等待业绩验证。
通过价格和成交量趋势判断拐点信号（财务数据有限，用价量行为作代理）。

散户优势：需要深度研究判断拐点，持仓周期长（30-90天），机构等不起。

扫描条件：
- 过去60日跌幅较大（从高点跌超20%）
- 但近10日出现企稳信号（成交量放大+价格止跌）
- 估值处于低位（PE<30 或 PB<2）
- 非ST股
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class TurnaroundService(RetailScreeningBase):
    """困境反转策略"""

    async def scan_turnaround(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描困境反转候选股

        参数：
            min_score: int = 40
            limit: int = 50
        """
        start_time = time.time()
        params = params or {}
        limit = params.get("limit", 50)

        # 1. 获取行情+估值
        screening_data = await self._get_screening_view_batch()

        # 2. 筛选候选：PE>0 的股票（排除亏损股，后续用价量判断拐点），按成交额降序（全市场覆盖）
        pe_positive_codes = [
            code
            for code, data in screening_data.items()
            if data.get("pe", 0) and data["pe"] > 0 and data.get("close", 0) > 0
        ]
        sorted_codes = sorted(
            pe_positive_codes,
            key=lambda c: screening_data[c].get("amount", 0) or 0,
            reverse=True
        )
        candidates = sorted_codes

        logger.info(f"困境反转扫描: {len(candidates)} 个候选股")

        # 3. 批量获取60日K线
        today = datetime.now().strftime("%Y-%m-%d")
        from datetime import datetime as dt
        quotes_map = await self._batch_get_quotes(
            candidates, today, days=60, concurrency=100
        )

        # 4. 分析
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

        # 风险过滤（排除高风险股票，保留的附加风险信息）
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
        self, code: str, sv: dict, quotes: List[dict]
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

        if close <= 0 or "ST" in name:
            return None

        closes = np.array([q["close"] for q in quotes], dtype=float)
        volumes = np.array([q.get("volume", 0) for q in quotes], dtype=float)
        pct_chgs = np.array([q.get("pct_chg", 0) for q in quotes], dtype=float)

        # 1. 从60日高点的回撤
        high_60 = float(np.max(closes))
        drawdown_from_high = (close - high_60) / high_60

        # 2. 近10日 vs 前10日对比（企稳信号）
        if len(closes) < 30:
            return None
        recent_10 = closes[-10:]
        prev_10 = closes[-20:-10]
        recent_avg = float(np.mean(recent_10))
        prev_avg = float(np.mean(prev_10))
        price_stabilize = (recent_avg - prev_avg) / prev_avg  # 近10日均价比前10日

        # 3. 成交量变化（放量企稳）
        recent_vol = float(np.mean(volumes[-10:]))
        prev_vol = float(np.mean(volumes[-20:-10]))
        vol_change = (recent_vol - prev_vol) / prev_vol if prev_vol > 0 else 0

        # 4. 近20日涨幅（从低点反弹幅度）
        low_20 = float(np.min(closes[-20:]))
        rebound_from_low = (close - low_20) / low_20 if low_20 > 0 else 0

        # 5. 近5日涨幅
        if len(closes) >= 6:
            recent_5_pct = (closes[-1] - closes[-6]) / closes[-6]
        else:
            recent_5_pct = 0

        # 6. 信号判定
        signal_type = "观察"
        if drawdown_from_high < -0.15 and price_stabilize > -0.02 and vol_change > 0.2:
            signal_type = "放量企稳"
        elif drawdown_from_high < -0.15 and price_stabilize > -0.01:
            signal_type = "价格企稳"
        elif rebound_from_low > 0.03 and recent_5_pct > -0.01:
            signal_type = "底部反弹"
        elif drawdown_from_high < -0.25:
            signal_type = "深度回调"

        # 7. 评分
        score = 0
        score_details = {}

        # 回撤评分（0-25分）：回撤越大分越高
        dd_score = min(25, abs(drawdown_from_high) * 50)
        score += dd_score
        score_details["回撤幅度"] = round(dd_score, 1)

        # 企稳评分（0-30分）：价格止跌+放量
        stab_score = 0
        if price_stabilize > -0.02:
            stab_score += 15
        if price_stabilize > 0:
            stab_score += 5
        if vol_change > 0.2:
            stab_score += 10
        score += stab_score
        score_details["企稳信号"] = stab_score

        # 反弹评分（0-20分）
        reb_score = min(20, rebound_from_low * 100)
        score += reb_score
        score_details["底部反弹"] = round(reb_score, 1)

        # 估值评分（0-15分）
        val_score = 0
        if 0 < pe < 15:
            val_score += 8
        elif 0 < pe < 30:
            val_score += 4
        if 0 < pb < 1.5:
            val_score += 7
        elif 0 < pb < 3:
            val_score += 3
        score += val_score
        score_details["估值水平"] = val_score

        # 近5日动能（0-10分）
        mom_score = max(0, min(10, recent_5_pct * 100))
        score += mom_score
        score_details["短期动能"] = round(mom_score, 1)

        if score < 15:
            return None

        # 估值水平描述
        if pe > 0 and pe < 15:
            val_level = "低估"
        elif pe > 0 and pe < 30:
            val_level = "合理"
        elif pe > 0:
            val_level = "偏高"
        else:
            val_level = "亏损"

        return {
            "code": code,
            "name": name,
            "industry": industry,
            "close": round(close, 2),
            "pct_chg": round(pct_chg, 2),
            "drawdown_from_high": round(float(drawdown_from_high), 4),
            "rebound_from_low": round(float(rebound_from_low), 4),
            "recent_20d_pct": round(float((closes[-1] - closes[-21]) / closes[-21]) if len(closes) > 21 else 0, 4),
            "vol_change": round(float(vol_change), 4),
            "price_stabilize": round(float(price_stabilize), 4),
            "pe": round(pe, 2) if pe > 0 else None,
            "pb": round(pb, 2) if pb > 0 else None,
            "total_mv": round(total_mv, 2),
            "valuation_level": val_level,
            "signal_type": signal_type,
            "score": int(score),
            "score_details": score_details,
            "high_60": round(high_60, 2),
            "low_20": round(low_20, 2),
        }

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """回测"""
        params = params or {}
        from datetime import datetime

        async def scan_func(date_str: str) -> List[dict]:
            """回测扫描函数：使用历史数据，避免未来函数"""
            screening_data = await self._get_screening_view_for_date(date_str)
            pe_positive_codes = [
                code
                for code, data in screening_data.items()
                if data.get("pe", 0) and data["pe"] > 0
            ]
            sorted_codes = sorted(
                pe_positive_codes,
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

        return await self.run_backtest("turnaround", scan_func, params)


_service: Optional[TurnaroundService] = None


def get_turnaround_service() -> TurnaroundService:
    global _service
    if _service is None:
        _service = TurnaroundService()
    return _service
