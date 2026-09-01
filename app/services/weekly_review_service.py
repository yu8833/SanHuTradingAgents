"""周度复盘自动化（P3）。

设计文档《第六章·交易工具与日常流程》§4 缺口3：
- 定量统计：本周收益率（vs 沪深300）、交易笔数、胜率、持仓全红率
- 持仓全红率 = 盈利持仓数 / 总持仓数（教材 5.3 核心指标）
- 对比沪深300：Tushare 指数日线（pro.index_daily）优先，AKShare stock_zh_index_daily(sh000300) 兜底
- 信号有效性：复用 P1 signal_tracking 聚合统计
- 落库 weekly_reviews（user_id + week_start 唯一），周五盘后自动生成
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime, timedelta

from app.core.database import get_mongo_db
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

COLLECTION = "weekly_reviews"
HS300_CODE = "sh000300"


def _week_bounds() -> tuple[str, str]:
    """本周窗口 [周一 00:00, 今天]，返回 YYYY-MM-DD。"""
    today = now_tz().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), today.isoformat()


def _last_friday_before(week_start: date) -> date:
    """week_start 之前的最近一个周五（基准日）。"""
    d = week_start - timedelta(days=1)
    while d.weekday() != 4:  # 4 = Friday
        d -= timedelta(days=1)
    return d


def _fetch_hs300_weekly_return(week_start_str: str, today_str: str) -> dict:
    """沪深300 本周涨跌幅：Tushare 指数日线优先（设计文档 §4 缺口3），AKShare 兜底。失败返回 unavailable。"""
    week_start = date.fromisoformat(week_start_str)
    prev_friday = _last_friday_before(week_start)
    start_ts = prev_friday.strftime("%Y%m%d")
    end_ts = today_str.replace("-", "")

    # 1) Tushare 指数日线（优先）
    rows = _hs300_tushare_rows(start_ts, end_ts)
    # 2) AKShare 兜底
    if not rows:
        rows = _hs300_akshare_rows(prev_friday.isoformat())
    if not rows:
        return {"available": False, "message": "沪深300日线不可用"}

    # rows = [(date_iso, close)]，升序
    week_rows = [c for d, c in rows if d >= week_start.isoformat()]
    if not week_rows:
        return {"available": False, "message": "本周无沪深300数据"}
    last_close = week_rows[-1]
    # 基准：上周五收盘，缺失则用本周第一根
    base_close = next((c for d, c in rows if d == prev_friday.isoformat()), week_rows[0])
    if base_close <= 0:
        return {"available": False, "message": "沪深300基准价无效"}
    return {
        "available": True,
        "ret_pct": round((last_close / base_close - 1) * 100, 2),
        "last_close": round(last_close, 2),
        "base_close": round(base_close, 2),
    }


def _hs300_tushare_rows(start_ts: str, end_ts: str) -> list[tuple[str, float]]:
    """Tushare 指数日线（pro.index_daily，000300.SH）。失败/无 token 返回 []。"""
    try:
        import os
        import tushare as ts
        token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
        if not token:
            return []
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.index_daily(
            ts_code="000300.SH", start_date=start_ts, end_date=end_ts,
            fields="trade_date,close",
        )
        if df is None or len(df) == 0 or "trade_date" not in df.columns or "close" not in df.columns:
            return []
        df = df.sort_values("trade_date")
        out: list[tuple[str, float]] = []
        for _, r in df.iterrows():
            d = str(r["trade_date"])[:8]
            out.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(r["close"])))
        return out
    except Exception as e:
        logger.warning(f"沪深300 Tushare 指数日线获取失败: {e}")
        return []


def _hs300_akshare_rows(floor_date: str) -> list[tuple[str, float]]:
    """AKShare sh000300 日线兜底。失败返回 []。"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=HS300_CODE)
        if df is None or len(df) == 0 or "date" not in df.columns or "close" not in df.columns:
            return []
        df = df.copy()
        df["date"] = df["date"].astype(str).str[:10]
        df = df[df["date"] >= floor_date]
        return [(str(r["date"]), float(r["close"])) for _, r in df.iterrows()]
    except Exception as e:
        logger.warning(f"沪深300 AKShare 日线获取失败: {e}")
        return []


async def _fetch_week_trades(user_id: str, week_start_str: str) -> list[dict]:
    """本周 paper_trades 成交记录。"""
    db = get_mongo_db()
    q = {
        "user_id": user_id,
        "$or": [
            {"timestamp": {"$gte": week_start_str}},
            {"trade_date": {"$gte": week_start_str}},
        ],
    }
    docs = await db["paper_trades"].find(q).to_list(None)
    return docs


async def _fetch_open_positions(user_id: str) -> list[dict]:
    """当前未平仓持仓（含最新价/盈亏）。"""
    db = get_mongo_db()
    positions = await db["paper_positions"].find({
        "user_id": user_id, "quantity": {"$gt": 0}
    }).to_list(None)
    out = []
    for p in positions:
        qty = int(p.get("quantity", 0))
        cost = float(p.get("avg_cost", 0.0) or 0.0)
        if qty <= 0:
            continue
        last = await _fetch_last_close(p.get("code", ""))
        mkt = round((last or cost) * qty, 2)
        pnl = round(((last or cost) - cost) * qty, 2)
        out.append({
            "code": p.get("code", ""),
            "name": p.get("stock_name", p.get("code", "")),
            "quantity": qty,
            "avg_cost": cost,
            "last_price": last,
            "market_value": mkt,
            "unrealized_pnl": pnl,
            "profitable": bool(last is not None and last > cost),
        })
    return out


async def _fetch_last_close(code: str) -> float | None:
    """轻量取最新价：market_quotes 优先。"""
    try:
        db = get_mongo_db()
        q = await db["market_quotes"].find_one(
            {"$or": [{"code": code}, {"symbol": code}]},
            {"_id": 0, "close": 1},
        )
        if q and q.get("close"):
            price = float(q["close"])
            return price if price > 0 else None
    except Exception:
        pass
    return None


async def generate_weekly_review(user_id: str) -> dict:
    """生成本周复盘（定量统计 + 持仓全红率 + 沪深300对比 + 信号有效性），落库并返回。"""
    db = get_mongo_db()
    week_start_str, today_str = _week_bounds()
    week_start_date = date.fromisoformat(week_start_str)

    trades = await _fetch_week_trades(user_id, week_start_str)
    trade_count = len(trades)

    # 胜率：本周卖出记录（含 pnl）
    sells = [t for t in trades if t.get("side") == "sell" and t.get("pnl") is not None]
    win_count = sum(1 for t in sells if float(t.get("pnl", 0)) > 0)
    win_rate = round(win_count / len(sells) * 100, 1) if sells else None
    realized_pnl = round(sum(float(t.get("pnl", 0)) for t in sells), 2)

    # 持仓全红率 = 盈利持仓数 / 总持仓数
    positions = await _fetch_open_positions(user_id)
    holding_count = len(positions)
    profitable_count = sum(1 for p in positions if p["profitable"])
    all_red_rate = round(profitable_count / holding_count * 100, 1) if holding_count else None

    # 本周收益率（近似）：本周已实现盈亏 / 当前总权益
    # 当前总权益 = 账户现金 + 持仓市值（CNY 口径）
    acc = await db["paper_accounts"].find_one({"user_id": user_id})
    cash = acc.get("cash", {}) if acc else {}
    if not isinstance(cash, dict):
        cash = {"CNY": float(cash), "HKD": 0.0, "USD": 0.0}
    cash_cny = float(cash.get("CNY", 0.0) or 0.0)
    positions_value = sum(p["market_value"] for p in positions)
    equity_now = cash_cny + positions_value
    weekly_return = round(realized_pnl / equity_now * 100, 2) if equity_now > 0 else None

    # 沪深300 对比（后台线程拉取，避免阻塞）
    benchmark = await asyncio.to_thread(_fetch_hs300_weekly_return, week_start_str, today_str)
    benchmark_ret = benchmark.get("ret_pct") if benchmark.get("available") else None
    excess_return = (
        round(weekly_return - benchmark_ret, 2)
        if weekly_return is not None and benchmark_ret is not None else None
    )

    # 信号有效性（P1 聚合）
    from app.services.signal_tracking_service import get_signal_stats
    signal_stats = await get_signal_stats()

    review = {
        "user_id": user_id,
        "week_start": week_start_str,
        "week_end": today_str,
        "generated_at": datetime.utcnow(),
        "quant": {
            "weekly_return": weekly_return,
            "trade_count": trade_count,
            "win_rate": win_rate,
            "win_count": win_count,
            "sell_count": len(sells),
            "realized_pnl": realized_pnl,
            "holding_count": holding_count,
            "profitable_count": profitable_count,
            "all_red_rate": all_red_rate,
        },
        "benchmark": benchmark,
        "excess_return": excess_return,
        "signal_stats": signal_stats,
        "positions_snapshot": positions,
    }

    await db[COLLECTION].replace_one(
        {"user_id": user_id, "week_start": week_start_str},
        review,
        upsert=True,
    )
    logger.info(f"📊 周度复盘已生成: user={user_id} week={week_start_str} "
                f"收益率={weekly_return}% vs 沪深300={benchmark_ret}%")
    review.pop("_id", None)
    return review


async def get_latest_review(user_id: str) -> dict | None:
    """最近一期周度复盘。"""
    try:
        db = get_mongo_db()
        doc = await db[COLLECTION].find_one(
            {"user_id": user_id}, sort=[("week_start", -1)]
        )
        if doc:
            doc.pop("_id", None)
        return doc
    except Exception as e:
        logger.error(f"周度复盘读取失败: {e}", exc_info=True)
        return None


async def list_reviews(user_id: str, limit: int = 12) -> list[dict]:
    """历史周度复盘列表（按周倒序，仅返回摘要字段）。"""
    try:
        db = get_mongo_db()
        cursor = db[COLLECTION].find({"user_id": user_id}).sort("week_start", -1).limit(limit)
        items = []
        async for doc in cursor:
            doc.pop("_id", None)
            items.append(doc)
        return items
    except Exception as e:
        logger.error(f"周度复盘历史读取失败: {e}", exc_info=True)
        return []
