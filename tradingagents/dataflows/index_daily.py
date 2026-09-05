"""指数/K线日线数据工具 —— 供复盘持有期收益计算使用（替换 yfinance 拉取 A 股数据）。

背景：
- 复盘闭环（TradingAgentsGraph._fetch_returns → TradingMemoryLog）此前用 yfinance 拉
  A 股个股与沪深300（000300.SS）收盘序列。yfinance 境内不稳定/延迟，污染 Alpha 复盘。
- 本模块在 tradingagents 层自包含实现（不 import app，避免 app→tradingagents→app 循环），
  Tushare 指数日线优先（复用 weekly_review_service 范式）、AKShare 兜底；A 股个股走
  AKShare 前复权日线。非 A 股标的仍由调用方走 yfinance，不受影响。

接口：
- resolve_market(ticker) -> "A" | "US" | "HK" | "OTHER"
- get_index_daily_series(index_code, start_date, end_date) -> [(date_iso, close)]（升序）
- get_stock_daily_series(ticker, start_date, end_date) -> [(date_iso, close)]（升序）

错误语义：任何失败/空数据返回 []（而非抛异常），由调用方按"暂无数据、下次再试"处理。
"""

from __future__ import annotations

import logging
import os
import re
import time

logger = logging.getLogger(__name__)

# 沪深300 指数代码常量（AKShare 风格，与 app/services/retail/market_data_collector.py 口径一致）
HS300_INDEX_CODE = "sh000300"

# Tushare ts_code 的交易所后缀映射：akshare 前缀 -> ts_code 后缀
_TUSHARE_EXCHANGE_SUFFIX = {"sh": "SH", "sz": "SZ", "bj": "BJ"}

# 指数日线缓存（AKShare 全量拉取耗时，按 symbol 缓存 6 小时）
_CACHE_TTL_SECONDS = 6 * 3600
_idf_cache: dict[str, tuple[float, list]] = {}


def resolve_market(ticker: str) -> str:
    """按代码后缀判定市场：A / US / HK / OTHER。

    - `XXX.SS`·`XXX.SH`·`XXX.SZ`·`XXX.BJ` 及裸 6 位数字 → A（A股）
    - `XXX.HK` → HK
    - `XXX.US`·`XXX.T`·`XXX.TO`·`XXX.L`·`XXX.AX` 等 → US/US 系
    - 其余 → OTHER（未知市场）
    """
    t = (ticker or "").strip().upper()
    if re.fullmatch(r"\d{6}", t):
        return "A"
    if t.endswith((".SS", ".SH", ".SZ", ".BJ")):
        return "A"
    if t.endswith(".HK"):
        return "HK"
    if any(t.endswith(suf) for suf in (".US", ".T", ".TO", ".L", ".AX", ".PA", ".DE")):
        return "US"
    return "OTHER"


def _index_code_to_ts_code(index_code: str) -> str | None:
    """'sh000300' -> '000300.SH'；无法识别返回 None。"""
    m = re.fullmatch(r"(sh|sz|bj)(\d{6})", (index_code or "").strip().lower())
    if not m:
        return None
    prefix, num = m.group(1), m.group(2)
    suffix = _TUSHARE_EXCHANGE_SUFFIX.get(prefix)
    if not suffix:
        return None
    return f"{num}.{suffix}"


def _tushare_index_rows(ts_code: str, start_ts: str, end_ts: str) -> list:
    """Tushare 指数日线（pro.index_daily）。无 token/失败返回 []。"""
    try:
        import tushare as ts

        token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
        if not token:
            return []
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.index_daily(
            ts_code=ts_code,
            start_date=start_ts,
            end_date=end_ts,
            fields="trade_date,close",
        )
        if (
            df is None
            or len(df) == 0
            or "trade_date" not in df.columns
            or "close" not in df.columns
        ):
            return []
        df = df.sort_values("trade_date")
        out: list = []
        for _, r in df.iterrows():
            d = str(r["trade_date"]).strip()[:8]
            out.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(r["close"])))
        return out
    except Exception as e:
        logger.warning("沪深300 Tushare 指数日线获取失败: %s", e)
        return []


def _akshare_index_rows(index_code: str, start_date: str | None, end_date: str | None) -> list:
    """AKShare 指数日线（stock_zh_index_daily）兜底。失败返回 []。"""
    try:
        import akshare as ak

        df = ak.stock_zh_index_daily(symbol=index_code)
        if (
            df is None
            or len(df) == 0
            or "date" not in df.columns
            or "close" not in df.columns
        ):
            return []
        df = df.copy()
        df["date"] = df["date"].astype(str).str[:10]
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        return [(str(r["date"]), float(r["close"])) for _, r in df.iterrows()]
    except Exception as e:
        logger.warning("沪深300 AKShare 日线获取失败: %s", e)
        return []


def get_index_daily_series(
    index_code: str = HS300_INDEX_CODE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """获取指数在 [start_date, end_date] 区间的日收盘序列。

    Returns:
        [(date_iso, close)] 升序；空/失败返回 []（调用方保持"下次再试"语义）。
    """
    now = time.time()
    cached = _idf_cache.get(index_code)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return [row for row in cached[1] if _in_range(row[0], start_date, end_date)]

    ts_code = _index_code_to_ts_code(index_code)
    rows: list = []
    if ts_code:
        start_ts = (start_date or "19700101").replace("-", "")
        end_ts = (end_date or "20991231").replace("-", "")
        rows = _tushare_index_rows(ts_code, start_ts, end_ts)
    if not rows:
        rows = _akshare_index_rows(index_code, start_date, end_date)

    # 全量缓存（与调用区间解耦），取用时再按区间过滤
    if rows:
        _idf_cache[index_code] = (now, [row for row in rows])
    return [row for row in rows if _in_range(row[0], start_date, end_date)]


def get_stock_daily_series(
    ticker: str,
    start_date: str | None,
    end_date: str | None,
) -> list:
    """A 股个股日收盘序列（AKShare 前复权日线）。非 A 股/失败返回 []。"""
    if resolve_market(ticker) != "A":
        return []
    try:
        import akshare as ak

        code = _normalize_a_code(ticker)
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(start_date or "19700101").replace("-", ""),
            end_date=(end_date or "20991231").replace("-", ""),
            adjust="qfq",
        )
        if (
            df is None
            or len(df) == 0
            or "日期" not in df.columns
            or "收盘" not in df.columns
        ):
            return []
        df = df.copy()
        df["日期"] = df["日期"].astype(str).str[:10]
        return [
            (str(r["日期"]), float(r["收盘"]))
            for _, r in df.iterrows()
        ]
    except Exception as e:
        logger.warning("A股个股日线获取失败 %s: %s", ticker, e)
        return []


def _normalize_a_code(ticker: str) -> str:
    """A 股代码归一为纯 6 位数字（'688017.SH' / 'SH688017' / 'sh688017' → '688017'）。"""
    s = ticker.strip().upper()
    for suffix in (".SS", ".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


def _in_range(d: str, start_date: str | None, end_date: str | None) -> bool:
    return not ((start_date and d < start_date) or (end_date and d > end_date))