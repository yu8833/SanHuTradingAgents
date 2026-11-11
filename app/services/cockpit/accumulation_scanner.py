"""积累区扫描器（交易驾驶舱 · 左侧观察 · 区块 03）

每日盘后扫描全市场，找出「筑底积累区」的股票，再与三买三卖 B1 左侧买点取交集
（03 = B1 ∩ 积累区）：B1 是全集口径的全市场左侧信号，积累区四条件是精选条件，
两者叠加后入池的才是「既有左侧信号、又满足吸筹形态」的标的。

积累区四条件：
- 近 20 日不创 60 日新低（收盘口径，容差 2%）
- 20 日年化波动率处于自身 250 日 <40% 分位（波动收敛）
- 近 15 日均振幅 / 60 日均振幅 ≤ 0.9（振幅收敛）
- 20 日日均成交额 ≥ 1 亿（流动性）
- 剔除 ST/退市股、上市不足约 60 个交易日的次新股

B1 交集由 three_buys_three_sells_service 批量扫描完成（与 Candidate 页同一真源）。
当前为经验参数（params_version=exp-v2），页面统一标注「经验参数 · 待回测校准」。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.core.collections import Collections
from app.core.database import get_mongo_db_sync
from app.strategy_system.data_adapter import get_stock_list, load_daily_panel
from app.strategy_system.indicators import compute_all
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

# 经验默认值（2026-11-10 经 800 只样本联合分布校准：熊市阴跌环境下约 20 余只入池）
ACCUM_DEFAULTS = {
    "warmup_days": 420,  # 加载窗口（自然日，≈287 交易日）
    "no_new_low_long": 60,  # 长窗口（交易日）
    "no_new_low_short": 20,  # 短窗口内不得创新低
    "no_new_low_tolerance": 0.98,  # 容差 2%（威科夫 Spring：允许轻微下探旧低后收回）
    "vol_pctile_window": 250,  # 波动率历史分位窗口（交易日）
    "vol_pctile_max": 0.40,  # 低于自身 250 日中位偏严（指标自然分布 p50=0.5）
    "converge_days": 15,  # 振幅收敛窗口
    "converge_base_days": 60,  # 振幅收敛基准窗口
    "converge_ratio_max": 0.9,  # 近 15 日振幅收缩 ≥10%（指标自然 p10≈0.82，0.6 全市场仅 0.3% 通过）
    "min_avg_amount": 1e8,  # 20 日日均成交额 ≥ 1 亿元
    "min_panel_rows": 80,  # 面板行数 ≥80 ≈ 上市满 60 交易日（剔除次新）
    "trigger_short": 20,  # 突破触发价：短窗口高点
    "trigger_long": 60,  # 突破触发价：长窗口高点
    "expire_ttl_days": 7,  # expired 文档保留天数
}

PARAMS_VERSION = "exp-v2"

# 扫描所需的指标列（keep_columns 裁剪，压缩内存与耗时）
_KEEP_COLUMNS = {"amplitude", "annual_vol_20d", "ma5", "ma20"}

_ST_TOKENS = ("ST", "退")


def _select_candidates(df: pd.DataFrame, info_map: dict[str, dict]) -> list[dict]:
    """纯函数：从指标面板中筛选积累区候选，便于单元测试。

    Args:
        df: compute_all 输出的全市场面板（按 symbol/date 排序），
            需含 close/high/low/amount/amplitude/annual_vol_20d/ma5 列。
        info_map: {symbol: {"name":..., "industry":...}} 股票基础信息。

    Returns:
        候选列表，每个元素为池文档的指标部分。
    """
    if df.empty:
        return []

    p = ACCUM_DEFAULTS
    candidates: list[dict] = []

    for symbol, g in df.groupby("symbol", sort=False):
        g = g.sort_values("date")
        rows = len(g)
        if rows < p["min_panel_rows"]:
            continue

        name = (info_map.get(symbol) or {}).get("name", "")
        if any(tok in name for tok in _ST_TOKENS):
            continue

        close = g["close"].astype(float)
        high = g["high"].astype(float)
        amount = g["amount"].astype(float)

        n_long = p["no_new_low_long"]
        n_short = p["no_new_low_short"]

        close_long = close.tail(n_long)
        low_60d_close = close_long.min()
        # 旧低形成区：60 日窗口的前段（不含近 20 日）
        low_prior_close = float(close_long.head(n_long - n_short).min())
        close_20d_min = float(close.tail(n_short).min())
        # 条件一：近 20 日收盘最低不跌破前段旧低（容差 0.5%）。
        # 注意必须与「前段旧低」比较——若与含近 20 日的整窗最低比较则恒真，条件失效。
        if not (close_20d_min >= low_prior_close * p["no_new_low_tolerance"]):
            continue

        # 条件二：20 日年化波动率的 250 日分位 < 30%
        vol = g["annual_vol_20d"].astype(float).dropna().tail(p["vol_pctile_window"])
        if len(vol) < 60:  # 历史分位样本不足
            continue
        vol_current = vol.iloc[-1]
        vol_pctile = float((vol < vol_current).mean())
        if vol_pctile >= p["vol_pctile_max"]:
            continue

        # 条件三：振幅收敛（近 15 日均振幅 / 60 日均振幅 ≤ 0.6）
        amp = g["amplitude"].astype(float).dropna()
        amp_short = amp.tail(p["converge_days"]).mean()
        amp_base = amp.tail(p["converge_base_days"]).mean()
        if not amp_base or amp_base <= 0:
            continue
        converge_ratio = float(amp_short / amp_base)
        if converge_ratio > p["converge_ratio_max"]:
            continue

        # 条件四：流动性（20 日日均成交额 ≥ 1 亿）
        avg_amount_20d = float(amount.tail(20).mean())
        if avg_amount_20d < p["min_avg_amount"]:
            continue

        # 横盘天数：自最近一次收盘创 60 日新低以来的交易日数
        is_new_low = (close_long <= low_60d_close * 1.0001).values
        if is_new_low.any():
            sideways_days = int(is_new_low[::-1].argmax())
        else:
            sideways_days = n_long
        sideways_days = max(sideways_days, n_short)

        # 突破触发价：近 20 日高点与前段（60 日窗口前 40 日）高点取更紧者（盘中高点口径）。
        # 注意前段窗口须剔除近 20 日——否则 60 日高点恒 ≥ 20 日高点，取紧分支失效。
        high_20d = float(high.tail(p["trigger_short"]).max())
        high_prior = float(high.tail(p["trigger_long"]).head(p["trigger_long"] - p["trigger_short"]).max())
        if high_20d <= high_prior:
            trigger_price, trigger_basis = high_20d, "high_20d"
        else:
            trigger_price, trigger_basis = high_prior, "high_60d"
        if trigger_price <= 0:
            continue

        last_close = float(close.iloc[-1])
        range_low = float(g["low"].astype(float).tail(n_short).min())
        ma5_val = g["ma5"].astype(float).dropna()
        ma20_val = g["ma20"].astype(float).dropna() if "ma20" in g.columns else ma5_val.iloc[0:0]
        candidates.append(
            {
                "code": str(symbol),
                "name": name,
                "industry": (info_map.get(symbol) or {}).get("industry", "") or "",
                "sideways_days": sideways_days,
                "volatility_pctile": round(vol_pctile, 4),
                "converge_ratio": round(converge_ratio, 4),
                "avg_amount_20d": avg_amount_20d,
                "avg_amount_5d": float(amount.tail(5).mean()),
                "trigger_price": round(trigger_price, 3),
                "trigger_basis": trigger_basis,
                "range_low": round(range_low, 3),
                "close": last_close,
                "ma5": round(float(ma5_val.iloc[-1]), 3) if not ma5_val.empty else None,
                "ma20": round(float(ma20_val.iloc[-1]), 3) if not ma20_val.empty else None,
                "distance_to_trigger": round(last_close / trigger_price - 1, 4),
            }
        )

    return candidates


def _load_and_select(trade_date: str) -> tuple[list[dict], dict]:
    """同步重活：加载面板 → 计算指标 → 筛选候选（在线程池中执行）。"""
    db = get_mongo_db_sync()
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=ACCUM_DEFAULTS["warmup_days"])

    df = load_daily_panel(
        db,
        symbols=None,
        start_dt=start_dt,
        end_dt=end_dt,
        adjust="hfq",
    )
    if df.empty:
        return [], {"panel_rows": 0, "symbols": 0}

    df = compute_all(df, keep_columns=_KEEP_COLUMNS)
    stock_list = get_stock_list(db)
    info_map = {
        str(s.get("symbol")): {
            "name": s.get("name", ""),
            # 统一用同花顺 90 行业（与主线方向资金流口径一致）
            "industry": s.get("ths_industry") or s.get("industry", ""),
        }
        for s in stock_list
        if s.get("symbol")
    }
    candidates = _select_candidates(df, info_map)
    stats = {
        "panel_rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "candidates": len(candidates),
    }
    return candidates, stats


async def _attach_b1_signals(candidates: list[dict]) -> tuple[list[dict], dict, set[str]]:
    """积累区候选 ∩ 三买三卖 B1 左侧买点（03 = B1 ∩ 积累区）。

    复用全市场信号真源（scan_three_buys_three_sells 支持 pool 白名单），
    只在积累区候选内批量扫描，避免全市场重算。
    失败时降级为「不附加 B1」并保留原始候选（宁可多展示，不漏掉跟踪）；
    返回的 non_b1_codes 用于把「B1 消失」与「积累区破坏」区分出池原因。
    """
    stats = {"accum_count": len(candidates), "b1_count": 0, "b1_scan_failed": False}
    if not candidates:
        return [], stats, set()
    try:
        from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service

        svc = get_three_buys_three_sells_service()
        result = await svc.scan_three_buys_three_sells(
            {
                "pool": [c["code"] for c in candidates],
                "include_signaless": True,
                "min_score": 0,
                "enable_dg_filter": False,
                "enable_liquidity_filter": False,
            }
        )
    except Exception as exc:
        logger.warning(f"B1 交集扫描失败（降级保留积累区候选）: {exc}")
        stats["b1_scan_failed"] = True
        return candidates, {**stats, "b1_count": len(candidates)}, set()

    b1_map: dict[str, dict] = {}
    for item in result.get("items") or []:
        b1 = next((s for s in (item.get("signals") or []) if s.get("type") == "B1"), None)
        if not b1:
            continue
        b1_map[str(item.get("code"))] = {
            "bias60": b1.get("bias60"),
            "position_pct": b1.get("position_pct"),
            "stop_loss_price": b1.get("stop_loss_price") or item.get("stop_price"),
            "score": item.get("score"),
            "signal_label": b1.get("type_label") or "B1 左侧买点",
        }

    out: list[dict] = []
    for c in candidates:
        b1 = b1_map.get(c["code"])
        if not b1:
            continue
        out.append(
            {
                **c,
                "signal_type": "B1",
                "signal_label": b1["signal_label"],
                "bias60": b1["bias60"],
                "position_pct": b1["position_pct"],
                "b1_stop_loss_price": b1["stop_loss_price"],
                "signal_score": b1["score"],
            }
        )
    stats["b1_count"] = len(out)
    non_b1_codes = {c["code"] for c in candidates} - set(b1_map)
    return out, stats, non_b1_codes


async def _ensure_indexes(db) -> None:
    pool = db[Collections.cockpit_watch_pool]
    await pool.create_index("code", unique=True)
    await pool.create_index([("status", 1), ("distance_to_trigger", 1)])
    # expired 文档 7 天后自动清理（expired_at 为 null 的活跃文档不过期）
    await pool.create_index(
        "expired_at",
        expireAfterSeconds=ACCUM_DEFAULTS["expire_ttl_days"] * 86400,
        partialFilterExpression={"status": "expired"},
    )


async def run_daily_accumulation_scan(db, trade_date: str) -> dict:
    """每日 18:30 盘后执行：全市场扫描积累区 → 与 B1 取交集 → 全量 diff upsert 观察池。"""
    started = now_tz()
    loop = asyncio.get_running_loop()
    accum_candidates, stats = await loop.run_in_executor(None, _load_and_select, trade_date)
    candidates, b1_stats, non_b1_codes = await _attach_b1_signals(accum_candidates)
    stats = {**stats, **b1_stats}

    await _ensure_indexes(db)
    pool = db[Collections.cockpit_watch_pool]
    now_utc = now_tz().astimezone(timezone.utc)  # aware UTC 写入（项目时间约定）

    existing = await pool.find({}, {"code": 1, "status": 1, "first_seen_date": 1}).to_list(None)
    existing_map = {d["code"]: d for d in existing if d.get("code")}
    new_codes = {c["code"] for c in candidates}

    inserted = updated = expired = 0
    for c in candidates:
        old = existing_map.get(c["code"])
        doc_update = {
            **c,
            "trade_date": trade_date,
            "last_scan_date": trade_date,
            "params_version": PARAMS_VERSION,
            "updated_at": now_utc,
        }
        if old is None:
            doc_update.update(
                {
                    "first_seen_date": trade_date,
                    "status": "watching",
                    "expired_reason": None,
                    "expired_at": None,
                    "created_at": now_utc,
                }
            )
            await pool.update_one({"code": c["code"]}, {"$set": doc_update}, upsert=True)
            inserted += 1
        else:
            # 已触发状态保留（信号区按交易日过滤展示），仅刷新指标
            keep_status = old.get("status") if old.get("status") == "triggered" else "watching"
            doc_update["status"] = keep_status
            await pool.update_one({"code": c["code"]}, {"$set": doc_update}, upsert=True)
            updated += 1

    # 出池：条件破坏的既有条目标记 expired
    for code, old in existing_map.items():
        if code in new_codes or old.get("status") == "expired":
            continue
        expired_reason = (
            "B1 左侧信号消失（不再是 BIAS60 深度超跌的左侧买点）"
            if code in non_b1_codes
            else "条件破坏（创新低/波动放大/流动性不足）"
        )
        await pool.update_one(
            {"code": code},
            {
                "$set": {
                    "status": "expired",
                    "expired_reason": expired_reason,
                    "expired_at": now_utc,
                    "updated_at": now_utc,
                }
            },
        )
        expired += 1

    duration_ms = int((now_tz() - started).total_seconds() * 1000)
    summary = {
        "trade_date": trade_date,
        "inserted": inserted,
        "updated": updated,
        "expired": expired,
        "total": len(candidates),
        "params_version": PARAMS_VERSION,
        **stats,
    }

    # 执行摘要（项目惯例：写 scheduler_executions）
    try:
        await db[Collections.scheduler_executions].insert_one(
            {
                "job_id": "cockpit_accumulation_scan",
                "job_name": "驾驶舱积累区盘后扫描",
                "status": "success",
                "started_at": started,
                "completed_at": now_tz(),
                "duration_ms": duration_ms,
                "result": summary,
                "created_at": now_utc,
            }
        )
    except Exception as exc:  # 摘要写入失败不影响主流程
        logger.warning(f"写入 scheduler_executions 失败: {exc}")

    logger.info(
        f"✅ 积累区扫描完成: {trade_date} 候选 {len(candidates)} 只 "
        f"(新增 {inserted} / 更新 {updated} / 出池 {expired})，耗时 {duration_ms}ms"
    )
    return summary
