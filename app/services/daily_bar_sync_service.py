"""当日日线同步：让「今天这根 K 线」在盘中与收盘后尽快落库。

背景
----
stock_daily_quotes 的正式写入路径是 Tushare 夜间逐股增量同步（默认 23:00），
且 tushare_sync_service._latest_settled_trade_day() 在 18:30 前把「应有数据日」
回退到上一交易日，因此当日日线在收盘后数小时才可见：
- 盘中和收盘后的买卖分析全部基于 T-1；
- market_quotes 的日终校准因「当日日线覆盖率不足 60%」被跳过，收盘价停留在盘中快照。

策略（两条通道写同一批唯一键，不会产生 (code, trade_date) 重复记录）
------------------------------------------------------------------
1. 盘中（09:30–15:00）：用 market_quotes 实时快照合成临时日线，
   标记 provisional=True / bar_origin="market_snapshot"，每 15 分钟刷新。
2. 收盘后（≥15:05）：一次 pro.daily(trade_date) 拉全市场官方日线，
   ReplaceOne 覆盖同名 key，provisional 标记随整条文档一起被替换掉；
   成功后立即触发 market_quotes 日终校准，把收盘前快照改成官方收盘价。
"""

import asyncio
import logging
from datetime import time as dtime

from pymongo import UpdateOne

from app.core.database import get_mongo_db
from app.services.data_sources.tushare_adapter import TushareAdapter
from app.services.historical_data_service import get_historical_data_service
from app.utils.timezone import now_tz
from app.utils.trading_time import get_market_trade_date, is_trading_day

logger = logging.getLogger(__name__)

# 开盘后才开始合成盘中临时日线
SESSION_OPEN = dtime(9, 30)
# 15:05 起尝试拉取官方日线（Tushare 通常在收盘后陆续发布）
OFFICIAL_READY = dtime(15, 5)
# 官方日线覆盖率低于该值视为未发布完成，等待下一轮重试
MIN_OFFICIAL_ROWS = 4000
_BATCH_SIZE = 500

_DAILY_COLLECTION = "stock_daily_quotes"
_QUOTES_COLLECTION = "market_quotes"


def _norm_date(trade_date: str | None) -> str:
    """统一为 YYYY-MM-DD；None 取当前市场参考交易日。"""
    if not trade_date:
        return get_market_trade_date(now_tz()).strftime("%Y-%m-%d")
    s = str(trade_date).replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(trade_date)


async def _official_codes(db, trade_date: str) -> set[str]:
    """当日已有官方（非 provisional）日线的代码集合。"""
    codes: set[str] = set()
    cursor = db[_DAILY_COLLECTION].find(
        {
            "period": "daily",
            "trade_date": trade_date,
            "data_source": "tushare",
            "provisional": {"$ne": True},
        },
        {"_id": 0, "symbol": 1, "code": 1},
    )
    async for doc in cursor:
        code = doc.get("symbol") or doc.get("code")
        if code:
            codes.add(str(code).zfill(6))
    return codes


async def sync_official(trade_date: str | None = None) -> dict:
    """拉取指定交易日的全市场官方日线并落库（一次 API 调用）。

    与夜间逐股增量同步写同一唯一键
    (symbol, trade_date, data_source='tushare', period='daily')，
    夜间同步会原样覆盖，不会产生重复记录。
    """
    db = get_mongo_db()
    td = _norm_date(trade_date)
    existing = await db[_DAILY_COLLECTION].count_documents(
        {
            "period": "daily",
            "trade_date": td,
            "data_source": "tushare",
            "provisional": {"$ne": True},
        }
    )
    if existing >= MIN_OFFICIAL_ROWS:
        return {
            "status": "skipped",
            "trade_date": td,
            "source": "official",
            "written": 0,
            "reason": f"当日官方日线已有 {existing} 条",
        }

    adapter = TushareAdapter()
    df = await asyncio.to_thread(adapter.get_daily_by_date, td.replace("-", ""))
    if df is None:
        logger.warning(f"当日日线：Tushare {td} 接口调用失败，等待下一轮重试")
        return {"status": "error", "trade_date": td, "source": "official",
                "written": 0, "reason": "接口调用失败"}
    if df.empty:
        logger.info(f"当日日线：Tushare {td} 尚未发布，等待下一轮重试")
        return {"status": "pending", "trade_date": td, "source": "official",
                "written": 0, "reason": "数据源尚未发布"}

    # 复用数据完整性服务已有的单日全市场入库实现（含单位换算与 OHLC 校验）
    from app.services.data_integrity_service import DataIntegrityService

    svc = DataIntegrityService()
    rows = svc._extract_quote_rows(df, td, set())
    res = await svc._write_quote_rows(rows)
    written = res.get("written", 0)
    coverage = len(rows)
    status = "success" if coverage >= MIN_OFFICIAL_ROWS else "partial"
    logger.info(
        f"当日日线：{td} 官方日线写入 {written} 条（覆盖 {coverage} 只，{status}）"
    )

    calibrated = 0
    if status == "success":
        try:
            from app.services.quotes_ingestion_service import QuotesIngestionService

            calibrated = await QuotesIngestionService().calibrate_to_daily_close(td)
        except Exception as e:
            logger.warning(f"当日日线：日终校准失败（忽略，15:40 任务会重试）: {e}")

        # 校准完成即用日线重算当日市场温度：19:50 的固化任务若在盘中快照上跑过，
        # 会出现 finalized=true 但成交额/涨跌家数停留在盘中口径的问题，必须覆盖纠正。
        try:
            from app.services.market_metrics import recompute_market_metrics

            metrics = await recompute_market_metrics(td)
            if not metrics.get("ok"):
                logger.warning(f"当日日线：温度重算未完成（{metrics.get('reason')}）")
        except Exception as e:
            logger.warning(f"当日日线：温度重算失败（忽略）: {e}")

    return {
        "status": status,
        "trade_date": td,
        "source": "official",
        "written": written,
        "coverage": coverage,
        "calibrated": calibrated,
        "errors": res.get("errors") or [],
    }


async def sync_provisional(trade_date: str | None = None) -> dict:
    """用 market_quotes 实时快照合成当日临时日线。

    写入保持 data_source='tushare'（与正式数据同键，正式数据会原地覆盖），
    另加 provisional=True / bar_origin='market_snapshot' / snapshot_at 供追溯。
    """
    db = get_mongo_db()
    td = _norm_date(trade_date)
    compact = td.replace("-", "")

    official = await _official_codes(db, td)
    if len(official) >= MIN_OFFICIAL_ROWS:
        return {
            "status": "skipped",
            "trade_date": td,
            "source": "snapshot",
            "written": 0,
            "reason": f"当日官方日线已就绪（{len(official)} 条）",
        }

    quotes = await db[_QUOTES_COLLECTION].find(
        {"trade_date": compact},
        {
            "_id": 0, "code": 1, "open": 1, "high": 1, "low": 1, "close": 1,
            "pre_close": 1, "pct_chg": 1, "volume": 1, "amount": 1, "updated_at": 1,
        },
    ).to_list(None)
    if not quotes:
        return {
            "status": "empty",
            "trade_date": td,
            "source": "snapshot",
            "written": 0,
            "reason": "当日实时行情快照缺失",
        }

    service = await get_historical_data_service()
    snapshot_at = now_tz()
    ops = []
    skipped = 0
    for q in quotes:
        code = str(q.get("code") or "").zfill(6)
        if len(code) != 6 or not code.isdigit():
            skipped += 1
            continue
        close = q.get("close")
        if not close or close <= 0:
            skipped += 1
            continue
        if code in official:
            skipped += 1
            continue
        row = {
            # _standardize_record 优先从行内读取日期；缺省会落到「今天」，
            # 手动补历史日期时必须显式带上 trade_date。
            "trade_date": td,
            "open": q.get("open") or close,
            "high": q.get("high") or close,
            "low": q.get("low") or close,
            "close": close,
            "pre_close": q.get("pre_close"),
            "pct_chg": q.get("pct_chg"),
            "volume": q.get("volume"),
            "amount": q.get("amount"),
        }
        doc = service._standardize_record(code, row, "tushare", "CN", "daily", td)
        # 兜底：文档日期必须与幂等键中的 trade_date 一致，否则会产生跨日脏记录
        doc["trade_date"] = td
        doc["provisional"] = True
        doc["bar_origin"] = "market_snapshot"
        doc["snapshot_at"] = snapshot_at
        doc["quote_updated_at"] = q.get("updated_at")

        # 盘中每 15 分钟刷新一次，若用 ReplaceOne 会整条重写并连带更新全部索引项。
        # 这里只 $set OHLCV 等非键字段：幂等键（symbol/code/trade_date/period/data_source）
        # 不变，索引无需重写；created_at/version 只在首次插入时写。
        set_on_insert = {
            k: doc.get(k)
            for k in ("code", "full_symbol", "market", "created_at", "version")
        }
        set_fields = {
            k: v
            for k, v in doc.items()
            if k not in set_on_insert
            and k not in ("symbol", "trade_date", "period", "data_source")
        }
        ops.append(
            UpdateOne(
                {
                    "symbol": code,
                    "trade_date": td,
                    "data_source": "tushare",
                    "period": "daily",
                },
                {"$set": set_fields, "$setOnInsert": set_on_insert},
                upsert=True,
            )
        )

    written = 0
    for i in range(0, len(ops), _BATCH_SIZE):
        res = await db[_DAILY_COLLECTION].bulk_write(ops[i:i + _BATCH_SIZE], ordered=False)
        written += res.upserted_count + res.modified_count

    logger.info(
        f"当日日线：{td} 盘中临时日线刷新 {written} 条"
        f"（快照 {len(quotes)} 只，跳过 {skipped} 只）"
    )
    return {
        "status": "success",
        "trade_date": td,
        "source": "snapshot",
        "written": written,
        "skipped": skipped,
        "snapshot_at": snapshot_at.isoformat(),
    }


async def run_daily_bar_sync(
    trade_date: str | None = None,
    force_official: bool = False,
) -> dict:
    """按当前时间选择通道：盘中合成临时日线，收盘后拉官方日线（失败降级快照）。"""
    now = now_tz()
    td = _norm_date(trade_date)
    if not is_trading_day(td):
        return {"status": "skipped", "trade_date": td, "reason": "非交易日"}

    if force_official:
        res = await sync_official(td)
        if res["status"] in ("pending", "error"):
            snap = await sync_provisional(td)
            res["provisional"] = snap
        return res

    if now.time() < SESSION_OPEN:
        return {"status": "skipped", "trade_date": td, "reason": "未开盘"}

    if now.time() < OFFICIAL_READY:
        return await sync_provisional(td)

    res = await sync_official(td)
    if res["status"] in ("pending", "error"):
        # 官方日线尚未发布：先用快照兜底，下一轮 cron 继续重试官方数据
        res["provisional"] = await sync_provisional(td)
    return res
