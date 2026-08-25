"""数据适配层 — 从 MongoDB stock_daily_quotes 读取日线行情并转为 pandas 面板。

移植自 tickflow-stock-panel 的 KlineRepository，但数据源改为本项目 MongoDB。
统一输出列: symbol, date, open, high, low, close, volume, amount, pct_chg。
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd

logger = logging.getLogger(__name__)

# 数据源优先级（与项目多源同步的偏好顺序一致）
DATA_SOURCE_PRIORITY = ["tushare", "baostock", "akshare"]

# 输出统一列
PANEL_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


def _parse_date(d) -> str:
    """将 date/datetime/str 转为 YYYY-MM-DD 字符串。"""
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def get_stock_list(db, market: str | None = None, limit: int = 100000) -> list[dict]:
    """从 stock_basic_info 获取股票列表（含 symbol 与 name）。"""
    collection = db["stock_basic_info"]
    query: dict = {}
    if market:
        query["market"] = market
    cursor = collection.find(
        query,
        {"_id": 0, "symbol": 1, "code": 1, "name": 1, "industry": 1},
    ).limit(limit)
    out: list[dict] = []
    for doc in cursor:
        symbol = doc.get("symbol") or doc.get("code")
        if not symbol:
            continue
        out.append({
            "symbol": str(symbol),
            "name": doc.get("name") or "",
            "industry": doc.get("industry") or "",
        })
    return out


def load_daily_panel(
    db,
    symbols: Iterable[str] | None,
    start_dt,
    end_dt,
    period: str = "daily",
) -> pd.DataFrame:
    """从 stock_daily_quotes 加载日线行情并转为 pandas 面板。

    - 按 (symbol, date) 去重，多数据源时优先保留 DATA_SOURCE_PRIORITY 靠前者。
    - 返回列: symbol, date, open, high, low, close, volume, amount, pct_chg。
    - 若某 symbol 无数据，返回空 DataFrame（不抛错）。
    """
    collection = db["stock_daily_quotes"]
    start_s = _parse_date(start_dt)
    end_s = _parse_date(end_dt)

    query: dict = {
        "period": period,
        "trade_date": {"$gte": start_s, "$lte": end_s},
    }
    if symbols is not None:
        sym_list = [str(s) for s in symbols if s]
        if not sym_list:
            return pd.DataFrame(columns=PANEL_COLUMNS)
        query["$or"] = [
            {"code": {"$in": sym_list}},
            {"symbol": {"$in": sym_list}},
        ]

    projection = {
        "_id": 0,
        "code": 1,
        "symbol": 1,
        "trade_date": 1,
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "volume": 1,
        "amount": 1,
        "pct_chg": 1,
        "data_source": 1,
    }

    # 按 (symbol, date) 去重，保留优先级最高的数据源
    # 为降低大回测(数十万行)时的内存峰值：rows 只存一份最终行，best 只存 key->(rows下标, src_rank)，
    # 高优先级数据后到时覆盖 rows 中该行，避免行数据被重复持有两份。
    best: dict[tuple, tuple[int, int]] = {}
    rows: list[dict] = []
    cursor = collection.find(query, projection)
    for doc in cursor:
        code = doc.get("code") or doc.get("symbol")
        code = str(code) if code else ""
        trade_date = doc.get("trade_date", "")
        if not code or not trade_date:
            continue
        key = (code, trade_date)
        src = doc.get("data_source", "")
        try:
            src_rank = DATA_SOURCE_PRIORITY.index(src) if src else len(DATA_SOURCE_PRIORITY)
        except ValueError:
            src_rank = len(DATA_SOURCE_PRIORITY)
        row = {
            "symbol": code,
            "date": trade_date,
            "open": doc.get("open"),
            "high": doc.get("high"),
            "low": doc.get("low"),
            "close": doc.get("close"),
            "volume": doc.get("volume"),
            "amount": doc.get("amount"),
            "pct_chg": doc.get("pct_chg"),
        }
        prev = best.get(key)
        if prev is None:
            best[key] = (len(rows), src_rank)
            rows.append(row)
        elif src_rank < prev[1]:
            # 更高优先级数据后到，覆盖该行
            rows[prev[0]] = row
            best[key] = (prev[0], src_rank)

    if not rows:
        return pd.DataFrame(columns=PANEL_COLUMNS)

    df = pd.DataFrame(rows, columns=PANEL_COLUMNS)

    # 数值化
    for col in ("amount",):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # 价格/涨跌幅/成交量用 float32：407万行 × 60列 的全市场面板可省一半内存，
    # 在 8GB 受限容器中避免指标计算/merge 阶段触发全局 OOM
    for col in ("open", "high", "low", "close", "pct_chg", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(
            "float32", copy=False
        )

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 补充涨跌幅：统一为小数口径（0.0057 = +0.57%），与 screener/策略/前端 fmtPctFromFraction 约定一致。
    # stock_daily_quotes 存的 pct_chg 是百分数（0.57 = +0.57%），先整体归一为小数；
    # 缺失处再用收盘价环比补齐（pct_change 天然为小数），避免混合口径导致数值放大 100 倍。
    df["pct_chg"] = df["pct_chg"] / 100.0
    if int(df["pct_chg"].notna().sum()) < len(df):
        computed = df.groupby("symbol")["close"].pct_change().astype("float32")
        df["pct_chg"] = df["pct_chg"].fillna(computed)
    return df


def load_symbol_history(
    db,
    symbol: str,
    start_dt,
    end_dt,
    period: str = "daily",
) -> pd.DataFrame:
    """加载单只股票的历史日线，返回降序或升序均可（调用方自行排序）。"""
    df = load_daily_panel(db, [symbol], start_dt, end_dt, period=period)
    return df