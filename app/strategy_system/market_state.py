"""
大盘状态统一事实源（single source of truth）

背景：此前系统内有两套互相冲突的大盘判断口径：
1. MarketRegimeDetector（retail）：中期趋势 = 沪深300 vs MA250，波动 = 指数波动率分位，
   宽度 = 当日涨家占比，情绪 = 融资余额 / 换手率 → 被「常用策略」页头使用；
2. screener.compute_market_context：短期趋势 = 近 5 日全市场涨家占比，波动 = 个股日均振幅
   → 被策略筛选 / 行情适配使用。
两者尺度不同（年线 vs 5 日），于是同一时刻页面显示「熊市阴跌」而筛选认为「偏强」，
用户无法判断该信谁。本模块把两者合并为同一口径，并补齐缺失画像「熊市反弹」。

输出：
- portrait：画像（牛市普涨 / 牛市强趋势 / 震荡蓄势 / 震荡分化 / 熊市阴跌 /
  熊市恐慌 / 熊市反弹 / 高波动市）
- dims：四维中文标签（趋势 / 波动 / 宽度 / 情绪），直接驱动前端「大盘×策略适配矩阵」
- metrics：两端原始指标（可追溯，不加工）
- reasons：判定依据，每条一句话，便于用户理解「为什么是当前画像」
- advice：一句话操作建议（唯一下发源，前后端不再各写一份）
- data_quality / missing：数据源降级情况（akshare 失败不再静默变成 0 / 3800）

口径（与各自原实现保持一致，避免二义）：
- 中期趋势 mid_trend：沪深300 收盘 vs MA250，偏离 ±5%
- 短期趋势 short_trend：近 5 个交易日全市场涨家占比（≥55% 偏强 / ≤45% 偏弱）
- 波动 volatility：个股日均振幅（≥2.5% 或宽度摆动 ≥18pp 为高，≤1.5% 且 ≤10pp 为低）
  与指数波动率分位（≥0.8 高 / ≤0.3 低）取更保守的一档
- 宽度 breadth：近 5 日涨家占比（≥55% 普涨 / ≤45% 分化 / 其余中性）
- 情绪 sentiment：融资余额 5 日变化 + 换手率相对 20 日均值；任一数据缺失即为 None（未知），
  不再用 0 冒充「中性」

缓存：本模块不额外加缓存层。日线重活分别由
collect_market_regime_data_with_sources（日级 6h / 实时 60s）与
compute_market_context（6h，进程内）各自缓存；这里只做合并与判定，
保证盘中「指数点位 / 市场宽度」跟着实时数据走。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.retail.market_regime_detector import MarketRegimeDetector
from app.strategy_system import screener
from app.strategy_system.market_portrait import PORTRAIT_ADVICE, derive_portrait
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

# 短期趋势阈值（与 screener.compute_market_context 完全一致）
SHORT_BULL_RATIO = 0.55
SHORT_BEAR_RATIO = 0.45
# 高 / 低波动阈值（与 compute_market_context 一致；低波动为本次新增，用于「震荡蓄势」）
HIGH_VOL_AVG_ABS = 2.5
HIGH_VOL_SWING = 0.18
LOW_VOL_AVG_ABS = 1.5
LOW_VOL_SWING = 0.10
# 中期趋势偏离阈值（与 MarketRegimeDetector._detect_trend 一致）
MID_TREND_BAND = 0.05

_MID_TREND_CN = {"bull": "牛市", "bear": "熊市", "range": "震荡"}
_SHORT_TREND_CN = {"bull": "偏强", "sideways": "中性", "bear": "偏弱"}
_VOL_CN = {"high": "高波动", "normal": "正常", "low": "低波动"}
_BREADTH_CN = {"broad": "普涨", "neutral": "中性", "narrow": "分化"}
_SENTIMENT_CN = {"euphoric": "狂热", "neutral": "中性", "panic": "恐慌"}


def _f(v: Any) -> float | None:
    """安全转 float：None / 空串 / 非法值统一返回 None（便于区分「缺失」与「0」）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _short_volatility(avg_abs: float | None, breadth_swing: float | None) -> str:
    """个股日均振幅 + 涨跌家数摆动 → 高 / 正常 / 低波动。"""
    if avg_abs is None and breadth_swing is None:
        return "unknown"
    if (avg_abs is not None and avg_abs >= HIGH_VOL_AVG_ABS) or (
        breadth_swing is not None and breadth_swing >= HIGH_VOL_SWING
    ):
        return "high"
    low_abs = avg_abs is not None and avg_abs <= LOW_VOL_AVG_ABS
    low_swing = breadth_swing is not None and breadth_swing <= LOW_VOL_SWING
    if low_abs and low_swing:
        return "low"
    return "normal"


def _index_volatility(percentile: float | None) -> str | None:
    """指数波动率历史分位 → 高 / 正常 / 低。"""
    if percentile is None:
        return None
    if percentile >= 0.8:
        return "high"
    if percentile <= 0.3:
        return "low"
    return "normal"


def _merge_volatility(short_vol: str, index_vol: str | None) -> str:
    """取两套波动口径中更保守的一档：任一为高即高；两者都低才低。"""
    if short_vol == "high" or index_vol == "high":
        return "high"
    if short_vol == "unknown" and index_vol is None:
        return "unknown"
    if short_vol == "low" and index_vol in (None, "low"):
        return "low"
    if short_vol == "unknown":
        return index_vol or "unknown"
    if short_vol == "low" and index_vol == "normal":
        return "normal"
    return "normal"


async def build_market_state(db) -> dict:
    """构建统一大盘状态。

    Args:
        db: 同步 MongoDB 句柄（compute_market_context 为同步重聚合，内部走线程池）
    """
    # ---- 1. 中期数据（akshare：指数日线 + 融资余额 + 换手率） ----
    raw: dict = {}
    collector_error: str | None = None
    try:
        from app.services.retail.market_data_collector import (
            collect_market_regime_data_with_sources,
        )

        raw = await collect_market_regime_data_with_sources()
    except Exception as e:  # akshare 整段不可用：不阻塞，降级为纯本地口径
        logger.warning(f"采集大盘日线数据失败，降级为本地口径: {e}")
        collector_error = str(e)
    sources = raw.get("sources") or {}

    # ---- 2. 短期数据（本地日线聚合：5 日涨家占比 + 个股日均振幅） ----
    try:
        ctx = await asyncio.to_thread(screener.compute_market_context, db)
    except Exception as e:
        logger.warning(f"本地行情聚合失败: {e}")
        ctx = {}

    # ---- 3. 中期趋势：沪深300 vs MA250 ----
    price = _f(raw.get("index_price"))
    ma250 = _f(raw.get("index_ma250"))
    # 日线（MA250）与实时点位都成功才算指数可用；任一失败则不拿兜底值 3800 冒充
    index_ok = (
        bool(sources.get("index"))
        and bool(sources.get("index_price"))
        and price is not None
        and price > 0
        and ma250 is not None
        and ma250 > 0
    )
    deviation: float | None = None
    mid_trend = "unknown"
    if index_ok:
        deviation = (price - ma250) / ma250
        if deviation > MID_TREND_BAND:
            mid_trend = "bull"
        elif deviation < -MID_TREND_BAND:
            mid_trend = "bear"
        else:
            mid_trend = "range"

    # ---- 4. 短期趋势 / 波动 / 宽度 ----
    up_ratio = _f(ctx.get("up_ratio"))
    short_trend = str(ctx.get("trend") or "unknown")
    if short_trend not in ("bull", "bear", "sideways"):
        short_trend = "sideways"
    avg_abs = _f(ctx.get("avg_abs"))
    breadth_swing = _f(ctx.get("breadth_swing"))
    vol_pct = _f(raw.get("volatility_percentile")) if sources.get("index") else None
    volatility = _merge_volatility(_short_volatility(avg_abs, breadth_swing), _index_volatility(vol_pct))

    if up_ratio is None:
        breadth = "neutral"
    elif up_ratio >= SHORT_BULL_RATIO:
        breadth = "broad"
    elif up_ratio <= SHORT_BEAR_RATIO:
        breadth = "narrow"
    else:
        breadth = "neutral"

    # ---- 5. 情绪：融资余额 + 换手率（缺失即 None，不再冒充 0） ----
    margin = _f(raw.get("margin_balance_change_pct"))
    turnover = _f(raw.get("turnover_ratio"))
    turnover_ma20 = _f(raw.get("turnover_ma20"))
    sentiment: str | None = None
    detector = MarketRegimeDetector()
    try:
        level = detector.detect_sentiment(margin, turnover, turnover_ma20)
        sentiment = level.value if level is not None else None
    except Exception as e:
        logger.warning(f"情绪维度判定失败，按未知处理: {e}")

    # ---- 6. 汇总裁剪 ----
    portrait = derive_portrait(
        mid_trend,
        volatility=volatility,
        breadth=breadth,
        sentiment=sentiment,
        short_trend=short_trend,
    )
    dims: dict[str, str] = {}
    if mid_trend in _MID_TREND_CN:
        dims["trend"] = _MID_TREND_CN[mid_trend]
    if volatility in _VOL_CN:
        dims["vol"] = _VOL_CN[volatility]
    dims["breadth"] = _BREADTH_CN[breadth]
    dims["sentiment"] = _SENTIMENT_CN.get(sentiment or "", "未知")

    reasons: list[str] = []
    if deviation is not None:
        reasons.append(
            f"沪深300 {price:.2f} vs 年线(MA250) {ma250:.2f}，偏离 {deviation * 100:+.1f}%"
            f" → 中期{_MID_TREND_CN[mid_trend]}"
        )
    else:
        reasons.append("沪深300 日线不可用 → 中期趋势未知，用短期宽度代理")
    if up_ratio is not None:
        reasons.append(
            f"近5日涨家占比 {up_ratio:.0%}（涨 {ctx.get('up_count')} / 跌 {ctx.get('down_count')}）"
            f" → 短期{_SHORT_TREND_CN[short_trend]}"
        )
    if avg_abs is not None:
        reasons.append(
            f"近20日个股日均振幅 {avg_abs:.2f}%、涨跌家数日均摆动 "
            f"{(breadth_swing or 0) * 100:.0f}pp → {_VOL_CN.get(volatility, '未知波动')}"
        )
    if margin is None:
        reasons.append("融资余额数据缺失 → 情绪未知（不再按中性处理）")
    else:
        dev_txt = (
            f"，换手率较20日均值 {(turnover - turnover_ma20) / turnover_ma20 * 100:+.0f}%"
            if turnover is not None and turnover_ma20
            else "，换手率无历史均值（按融资余额单独判定）"
        )
        reasons.append(
            f"融资余额近5日 {margin * 100:+.1f}%{dev_txt} → 情绪{_SENTIMENT_CN.get(sentiment or '', '未知')}"
        )
    if portrait == "熊市反弹":
        reasons.append("中期仍在年线下方但短期宽度转强 → 熊市反弹（仅小仓做超跌反弹）")

    missing: list[str] = []
    if not index_ok:
        missing.append("index_daily")
    if margin is None:
        missing.append("margin_balance_change_pct")
    if turnover is None:
        missing.append("turnover_ratio")
    if up_ratio is None:
        missing.append("up_ratio")
    if collector_error:
        missing.append("akshare")
    if collector_error:
        reasons.append(f"akshare 采集异常（{collector_error[:80]}）→ 数据质量降级")

    return {
        "as_of": ctx.get("as_of"),
        "generated_at": now_tz().isoformat(),
        "portrait": portrait,
        "dims": dims,
        "advice": PORTRAIT_ADVICE.get(portrait, "顺势控制仓位，等待方向明确"),
        "reasons": reasons,
        "metrics": {
            "index_price": price,
            "index_ma250": ma250,
            "index_deviation_pct": round(deviation * 100, 2) if deviation is not None else None,
            "volatility_percentile": vol_pct,
            "mid_trend": mid_trend,
            "short_trend": short_trend,
            "short_detail": ctx.get("detail"),
            "up_ratio": up_ratio,
            "breadth_ratio": _f(raw.get("breadth_ratio")),
            "up_count": ctx.get("up_count"),
            "down_count": ctx.get("down_count"),
            "avg_abs": avg_abs,
            "breadth_swing": breadth_swing,
            "last_day_avg_pct": ctx.get("pct_chg"),
            "margin_balance_change_pct": margin,
            "turnover_ratio": turnover,
            "turnover_ma20": turnover_ma20,
            "volatility": volatility,
            "breadth": breadth,
            "sentiment": sentiment,
        },
        "data_quality": "ok" if not missing else "degraded",
        "missing": missing,
        # 短期口径的原始上下文（保留 advice/detail 供行情条复用，避免再各自拼文案）
        "short_context": {
            "trend": ctx.get("trend"),
            "trend_label": ctx.get("trend_label"),
            "volatility": ctx.get("volatility"),
            "advice": ctx.get("advice"),
            "detail": ctx.get("detail"),
        },
        "cache": bool(ctx.get("cache")),
    }
