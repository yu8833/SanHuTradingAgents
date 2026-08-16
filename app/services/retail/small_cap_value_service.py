"""
小盘价值策略服务

策略逻辑：A股存在显著的小盘股流动性折价，市值10-30亿的优质公司估值偏低。
量化受容量限制很少配置30亿以下股票，公募有双十限制，散户独享"小而美"机会。

散户优势：流动性优势（机构不能买小盘股），持仓周期长（60-180天）。

扫描条件：
- 市值 10-30亿
- PE > 0 且 < 15
- PB > 0 且 < 2
- 换手率 > 0.3%（有流动性）
- 非ST股
- 近期涨幅适中（非暴涨暴跌）
"""

import asyncio
import logging
import time
from typing import Any
from app.utils.timezone import now_tz

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class SmallCapValueService(RetailScreeningBase):
    """小盘价值策略"""

    async def scan_small_cap_value(
        self, params: dict[str, Any] = None
    ) -> dict[str, Any]:
        """
        扫描小盘价值股

        参数：
            min_market_cap: float = 10  # 最小市值（亿）
            max_market_cap: float = 30  # 最大市值（亿）
            max_pe: float = 15  # 最大PE
            max_pb: float = 2   # 最大PB
            min_score: int = 40
            limit: int = 50
        """
        start_time = time.time()
        params = params or {}
        min_market_cap = params.get("min_market_cap", 10)
        max_market_cap = params.get("max_market_cap", 30)
        max_pe = params.get("max_pe", 15)
        max_pb = params.get("max_pb", 2)
        limit = params.get("limit", 50)

        # 1. 获取全部行情+估值
        screening_data = await self._get_screening_view_batch()

        # 2. 硬性筛选（规则引擎先过滤）
        candidates = []
        for code, data in screening_data.items():
            name = data.get("name", "")
            if "ST" in name:
                continue
            pe = data.get("pe", 0) or 0
            pb = data.get("pb", 0) or 0
            total_mv = data.get("total_mv", 0) or 0  # 单位：亿
            turnover = data.get("turnover_rate", 0) or 0
            close = data.get("close", 0) or 0

            if close <= 0:
                continue
            if pe <= 0 or pe > max_pe:
                continue
            if pb <= 0 or pb > max_pb:
                continue
            if total_mv < min_market_cap or total_mv > max_market_cap:
                continue
            if turnover < 0.3:
                continue

            candidates.append(code)

        logger.info(f"小盘价值扫描: {len(candidates)} 个候选股（硬性筛选后）")

        # 2.5 计算行业PE/PB统计值（用于行业中性化评分）
        industry_stats: dict[str, dict[str, list[float]]] = {}
        for code in candidates:
            sv = screening_data.get(code, {})
            industry = sv.get("industry", "") or "未知"
            pe = sv.get("pe", 0) or 0
            pb = sv.get("pb", 0) or 0
            if industry not in industry_stats:
                industry_stats[industry] = {"pe": [], "pb": []}
            if pe > 0:
                industry_stats[industry]["pe"].append(pe)
            if pb > 0:
                industry_stats[industry]["pb"].append(pb)

        # 3. 批量获取30日K线（用于评分）
        from datetime import datetime
        today = now_tz().strftime("%Y-%m-%d")
        quotes_map = await self._batch_get_quotes(
            candidates, today, days=30, concurrency=100
        )

        # 4. 评分
        semaphore = asyncio.Semaphore(50)
        items = []

        async def analyze_one(code: str):
            async with semaphore:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                result = self._analyze_stock(code, sv, quotes, max_pe, max_pb, industry_stats)
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
        self, code: str, sv: dict, quotes: list[dict], max_pe: float, max_pb: float,
        industry_stats: dict[str, dict[str, list[float]]] | None = None
    ) -> dict | None:
        """分析单只股票"""
        name = sv.get("name", "")
        industry = sv.get("industry", "") or "未知"
        pe = sv.get("pe", 0) or 0
        pb = sv.get("pb", 0) or 0
        total_mv = sv.get("total_mv", 0) or 0
        circ_mv = sv.get("circ_mv", 0) or 0
        turnover = sv.get("turnover_rate", 0) or 0
        close = sv.get("close", 0) or 0
        pct_chg = sv.get("pct_chg", 0) or 0
        volume = sv.get("volume", 0) or 0
        amount = sv.get("amount", 0) or 0

        if close <= 0:
            return None

        # K线分析（如果有数据）
        recent_5_pct = 0
        recent_20_pct = 0
        vol_ratio = 0
        if len(quotes) >= 20:
            closes = [q["close"] for q in quotes]
            volumes = [q.get("volume", 0) for q in quotes]
            recent_5_pct = (closes[-1] - closes[-6]) / closes[-6] if len(closes) > 6 else 0
            recent_20_pct = (closes[-1] - closes[-21]) / closes[-21] if len(closes) > 21 else 0
            recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
            prev_vol = sum(volumes[-20:-5]) / 15 if len(volumes) >= 20 else 1
            vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1

        # 信号判定
        signal_type = "价值持有"
        if recent_5_pct > 0.05:
            signal_type = "放量启动"
        elif recent_5_pct < -0.05:
            signal_type = "回调观察"
        elif vol_ratio > 1.5:
            signal_type = "资金关注"

        # 评分
        score = 0
        score_details = {}

        # PE评分（0-30分）：按行业内分位，分位越低分越高
        pe_percentile = 0.5
        if industry_stats and industry in industry_stats and pe > 0:
            industry_pes = industry_stats[industry]["pe"]
            if len(industry_pes) > 0:
                pe_percentile = sum(1 for p in industry_pes if p <= pe) / len(industry_pes)
                pe_score = max(0, min(30, (1 - pe_percentile) * 30))
            else:
                pe_score = max(0, min(30, (max_pe - pe) / max_pe * 30))
        elif pe > 0:
            pe_score = max(0, min(30, (max_pe - pe) / max_pe * 30))
        else:
            pe_score = 0
        score += pe_score
        score_details["PE评分"] = round(pe_score, 1)
        score_details["PE行业分位"] = round(pe_percentile, 2)

        # PB评分（0-25分）：按行业内分位，分位越低分越高
        pb_percentile = 0.5
        if industry_stats and industry in industry_stats and pb > 0:
            industry_pbs = industry_stats[industry]["pb"]
            if len(industry_pbs) > 0:
                pb_percentile = sum(1 for p in industry_pbs if p <= pb) / len(industry_pbs)
                pb_score = max(0, min(25, (1 - pb_percentile) * 25))
            else:
                pb_score = max(0, min(25, (max_pb - pb) / max_pb * 25))
        elif pb > 0:
            pb_score = max(0, min(25, (max_pb - pb) / max_pb * 25))
        else:
            pb_score = 0
        score += pb_score
        score_details["PB评分"] = round(pb_score, 1)
        score_details["PB行业分位"] = round(pb_percentile, 2)

        # 市值评分（0-15分）：市值越小分越高（越靠近10亿越好）
        mv_score = max(0, min(15, (30 - total_mv) / 20 * 15)) if total_mv > 0 else 0
        score += mv_score
        score_details["市值评分"] = round(mv_score, 1)

        # 换手率评分（0-15分）：适中最好
        if 0.5 <= turnover <= 5:
            turnover_score = 15
        elif 0.3 <= turnover < 0.5 or 5 < turnover <= 10:
            turnover_score = 10
        else:
            turnover_score = 5
        score += turnover_score
        score_details["流动性"] = turnover_score

        # 价格动能评分（0-15分）：温和上涨最好
        if 0 < recent_5_pct < 0.05:
            mom_score = 15
        elif -0.03 < recent_5_pct <= 0:
            mom_score = 10
        elif recent_5_pct >= 0.05:
            mom_score = 8  # 涨太多追高风险
        else:
            mom_score = 5
        score += mom_score
        score_details["价格动能"] = mom_score

        return {
            "code": code,
            "name": name,
            "industry": industry,
            "close": round(close, 2),
            "pct_chg": round(pct_chg, 2),
            "total_mv": round(total_mv, 2),
            "circ_mv": round(circ_mv, 2),
            "pe": round(pe, 2),
            "pb": round(pb, 2),
            "turnover_rate": round(turnover, 2),
            "volume": volume,
            "amount": amount,
            "recent_5d_pct": round(float(recent_5_pct), 4),
            "recent_20d_pct": round(float(recent_20_pct), 4),
            "vol_ratio": round(float(vol_ratio), 2),
            "signal_type": signal_type,
            "score": int(score),
            "score_details": score_details,
        }

    async def backtest(self, params: dict[str, Any] = None) -> dict[str, Any]:
        """回测"""
        params = params or {}

        async def scan_func(date_str: str) -> list[dict]:
            """回测扫描函数：使用历史数据，避免未来函数"""
            screening_data = await self._get_screening_view_for_date(date_str)
            max_pe = params.get("max_pe", 15)
            max_pb = params.get("max_pb", 2)
            candidates = []
            for code, data in screening_data.items():
                name = data.get("name", "")
                if "ST" in name:
                    continue
                pe = data.get("pe", 0) or 0
                pb = data.get("pb", 0) or 0
                total_mv = data.get("total_mv", 0) or 0
                if pe <= 0 or pe > max_pe:
                    continue
                if pb <= 0 or pb > max_pb:
                    continue
                if total_mv < 10 or total_mv > 30:
                    continue
                candidates.append(code)

            if not candidates:
                return []

            # 计算行业PE/PB统计值（用于行业中性化评分）
            industry_stats: dict[str, dict[str, list[float]]] = {}
            for code in candidates:
                sv = screening_data.get(code, {})
                industry = sv.get("industry", "") or "未知"
                pe = sv.get("pe", 0) or 0
                pb = sv.get("pb", 0) or 0
                if industry not in industry_stats:
                    industry_stats[industry] = {"pe": [], "pb": []}
                if pe > 0:
                    industry_stats[industry]["pe"].append(pe)
                if pb > 0:
                    industry_stats[industry]["pb"].append(pb)

            quotes_map = await self._batch_get_quotes(
                candidates, date_str, days=30, concurrency=50
            )
            items = []
            for code in candidates:
                sv = screening_data.get(code, {})
                quotes = quotes_map.get(code, [])
                result = self._analyze_stock(code, sv, quotes, max_pe, max_pb, industry_stats)
                if result:
                    items.append(result)
            return items

        return await self.run_backtest("small_cap_value", scan_func, params)


_service: SmallCapValueService | None = None


def get_small_cap_value_service() -> SmallCapValueService:
    global _service
    if _service is None:
        _service = SmallCapValueService()
    return _service
