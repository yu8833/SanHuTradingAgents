"""信号跟踪 + 有效性回填（P1）。

设计文档《第六章·交易工具与日常流程》§4 缺口1：
- 新建 `signal_tracking` 集合：{signal_type, code, trigger_date, snapshot(BIAS/MA60/象限/信号价), status}
- 扫描时自动落库（三买三卖扫描完成后写入买点信号）
- 定时任务：每日/周度回填 N 个交易日后实际表现（收益率、是否触止损/止盈、胜负）
- 汇总：按信号类型的胜率/盈亏比
- API：GET /api/signal-tracking（列表）+ GET /api/signal-tracking/stats（统计）
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import get_mongo_db
from app.utils.trading_time import is_trading_day

logger = logging.getLogger(__name__)

COLLECTION = "signal_tracking"

# 跟踪的买点信号类型（S 系为卖出/减仓信号，不纳入正向收益跟踪）
_TRACKED_TYPES = {"B1", "B2", "B3", "B2G"}
_TYPE_LABELS = {
    "B1": "左侧买点", "B2": "突破买点", "B3": "回踩买点", "B2G": "GMMA加仓",
}

# 回填观察期（交易日数）
BACKFILL_DAYS = 5


def _signal_price(sig: dict, item: dict) -> float:
    """信号价：优先 trigger_price，其次当日收盘价。"""
    tp = sig.get("trigger_price")
    try:
        return float(tp) if tp else float(item.get("close") or 0)
    except (TypeError, ValueError):
        return float(item.get("close") or 0)


def _build_record(item: dict, sig: dict) -> dict:
    """把一条扫描信号转成 signal_tracking 记录。"""
    return {
        "signal_type": sig["type"],
        "signal_label": _TYPE_LABELS.get(sig["type"], sig.get("type_label", sig["type"])),
        "code": item["code"],
        "name": item.get("name", ""),
        "industry": item.get("industry", ""),
        "trigger_date": str(item.get("trigger_date") or "")[:10],
        "signal_price": _signal_price(sig, item),
        "snapshot": {
            "close": item.get("close"),
            "pct_chg": item.get("pct_chg"),
            "bias60": item.get("bias60"),
            "ma60": item.get("ma60"),
            "ma60_direction": item.get("ma60_direction"),
            "stop_price": item.get("stop_price"),
            "score": item.get("score"),
            "market_trend": item.get("market_trend"),
        },
        "status": "pending",
        "filled": None,
        "created_at": datetime.utcnow(),
        "filled_at": None,
    }


async def save_scan_signals(items: list[dict]) -> int:
    """把三买三卖扫描结果中的买点信号落库（按 类型+代码+触发日+信号价 去重）。"""
    if not items:
        return 0
    try:
        db = get_mongo_db()
        col = db[COLLECTION]
        saved = 0
        for item in items:
            for sig in item.get("signals") or []:
                if sig.get("type") not in _TRACKED_TYPES:
                    continue
                rec = _build_record(item, sig)
                if not rec["code"] or not rec["trigger_date"] or rec["signal_price"] <= 0:
                    continue
                dup = await col.find_one({
                    "signal_type": rec["signal_type"],
                    "code": rec["code"],
                    "trigger_date": rec["trigger_date"],
                    "signal_price": rec["signal_price"],
                })
                if dup:
                    continue
                await col.insert_one(rec)
                saved += 1
        if saved:
            logger.info(f"📋 信号跟踪落库: 新增 {saved} 条买点信号")
        return saved
    except Exception as e:
        logger.error(f"信号跟踪落库失败: {e}", exc_info=True)
        return 0


def _nth_trading_day_after(ref: date, n: int) -> date:
    """ref 之后第 n 个交易日（不含 ref 当日）。"""
    d = ref
    while n > 0:
        d += timedelta(days=1)
        if is_trading_day(d):
            n -= 1
    return d


async def backfill_due_signals(n_trading_days: int = BACKFILL_DAYS, limit: int = 300) -> int:
    """回填到期信号（触发日距今天至少 n 个交易日）的实际表现。

    从 stock_daily_quotes 取触发日之后 n 个交易日的日线，计算：
      - ret: 第 n 个交易日收盘相对信号价的收益率
      - max_gain / max_drawdown: 窗口内最大涨幅 / 最大回撤
      - hit_stop: 窗口内最低价是否触达止损位
      - outcome: 胜负（>0 win / <0 loss / 0 flat）
    """
    try:
        db = get_mongo_db()
        col = db[COLLECTION]
        qcol = db["stock_daily_quotes"]

        today = date.today()
        # 待回填判定在下方逐条进行（触发日距今天至少 n 个交易日才回填），
        # 这里仅按日期粗筛 pending 记录，避免拉取全部历史。
        pending = await col.find(
            {"status": "pending", "trigger_date": {"$ne": "", "$lte": today.isoformat()}}
        ).sort("trigger_date", 1).limit(limit).to_list(length=limit)

        filled = 0
        for rec in pending:
            tdate = rec.get("trigger_date") or ""
            try:
                t = date.fromisoformat(tdate)
            except ValueError:
                continue
            # 距今天至少 n 个交易日才回填
            elapsed = sum(1 for i in range(1, 60)
                          if is_trading_day(t + timedelta(days=i))
                          and (t + timedelta(days=i)) <= today)
            if elapsed < n_trading_days:
                continue

            code = rec.get("code")
            target_dates = [(_nth_trading_day_after(t, i)).isoformat()
                            for i in range(1, n_trading_days + 1)]
            rows = await qcol.find(
                {"code": code, "period": "daily",
                 "trade_date": {"$in": target_dates}},
                projection={"_id": 0, "trade_date": 1, "close": 1, "high": 1, "low": 1},
            ).to_list(length=60)
            rows = sorted(rows, key=lambda r: r.get("trade_date", ""))
            if len(rows) < n_trading_days:
                continue

            entry = rec.get("signal_price") or 0
            if entry <= 0:
                continue
            last_close = rows[-1].get("close")
            if not isinstance(last_close, (int, float)) or last_close <= 0:
                continue
            highs = [r.get("high") for r in rows if isinstance(r.get("high"), (int, float))]
            lows = [r.get("low") for r in rows if isinstance(r.get("low"), (int, float))]
            ret = round((last_close - entry) / entry * 100, 2)
            max_gain = round((max(highs) / entry - 1) * 100, 2) if highs else None
            max_drawdown = round((min(lows) / entry - 1) * 100, 2) if lows else None
            stop_price = (rec.get("snapshot") or {}).get("stop_price")
            hit_stop = bool(stop_price and lows and min(lows) <= float(stop_price))
            outcome = "win" if ret > 0 else ("loss" if ret < 0 else "flat")

            await col.update_one(
                {"_id": rec["_id"]},
                {"$set": {
                    "status": "filled",
                    "filled": {
                        "trade_days": n_trading_days,
                        "close_after": last_close,
                        "ret": ret,
                        "max_gain": max_gain,
                        "max_drawdown": max_drawdown,
                        "hit_stop": hit_stop,
                        "outcome": outcome,
                    },
                    "filled_at": datetime.utcnow(),
                }},
            )
            filled += 1

        if filled:
            logger.info(f"🔄 信号有效性回填: 完成 {filled} 条（观察期 {n_trading_days} 个交易日）")
        return filled
    except Exception as e:
        logger.error(f"信号有效性回填失败: {e}", exc_info=True)
        return 0


async def list_signals(signal_type: str | None = None, status: str | None = None,
                       code: str | None = None, limit: int = 100) -> list[dict]:
    """信号跟踪列表（按触发日倒序）。"""
    try:
        db = get_mongo_db()
        q: dict = {}
        if signal_type:
            q["signal_type"] = signal_type
        if status:
            q["status"] = status
        if code:
            q["code"] = code
        docs = await db[COLLECTION].find(q).sort("trigger_date", -1).limit(limit).to_list(length=limit)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception as e:
        logger.error(f"信号跟踪列表读取失败: {e}", exc_info=True)
        return []


async def get_signal_stats() -> dict:
    """按信号类型聚合已回填信号：数量/胜率/平均收益/触止损率。"""
    try:
        db = get_mongo_db()
        col = db[COLLECTION]
        cursor = col.aggregate([
            {"$match": {"status": "filled", "filled": {"$ne": None}}},
            {"$group": {
                "_id": "$signal_type",
                "count": {"$sum": 1},
                "win": {"$sum": {"$cond": [{"$eq": ["$filled.outcome", "win"]}, 1, 0]}},
                "loss": {"$sum": {"$cond": [{"$eq": ["$filled.outcome", "loss"]}, 1, 0]}},
                "flat": {"$sum": {"$cond": [{"$eq": ["$filled.outcome", "flat"]}, 1, 0]}},
                "hit_stop": {"$sum": {"$cond": [{"$eq": ["$filled.hit_stop", True]}, 1, 0]}},
                "avg_ret": {"$avg": "$filled.ret"},
            }},
            {"$sort": {"count": -1}},
        ])
        rows = await cursor.to_list(length=20)
        stats = []
        total = {"count": 0, "win": 0, "loss": 0, "flat": 0, "hit_stop": 0, "win_rate": 0}
        for r in rows:
            count = r["count"]
            win_rate = round(r["win"] / count * 100, 1) if count else 0
            hit_stop_rate = round(r["hit_stop"] / count * 100, 1) if count else 0
            stats.append({
                "signal_type": r["_id"],
                "label": _TYPE_LABELS.get(r["_id"], r["_id"]),
                "count": count,
                "win": r["win"], "loss": r["loss"], "flat": r["flat"],
                "win_rate": win_rate,
                "hit_stop_rate": hit_stop_rate,
                "avg_ret": round(r["avg_ret"], 2) if r["avg_ret"] is not None else 0,
            })
            for k in ("count", "win", "loss", "flat", "hit_stop"):
                total[k] += r[k]
        if total["count"]:
            total["win_rate"] = round(total["win"] / total["count"] * 100, 1)
        pending_count = await col.count_documents({"status": "pending"})
        return {
            "by_type": stats,
            "total": total,
            "pending_count": pending_count,
        }
    except Exception as e:
        logger.error(f"信号统计失败: {e}", exc_info=True)
        return {"by_type": [], "total": {}, "pending_count": 0}
