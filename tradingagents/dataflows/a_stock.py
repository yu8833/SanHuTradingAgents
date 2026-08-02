"""A-stock (China mainland) data vendor for TradingAgents.

Zero third-party data dependency (no akshare). All sources are direct HTTP APIs
or mootdx TCP.

Data sources:
- mootdx (TCP 7709): OHLCV K-lines, financial snapshots, F10 text
- Tencent Finance (HTTP GBK): PE/PB/market cap/turnover
- 东方财富 push2 / datacenter-web (direct HTTP): stock info, dragon-tiger, lockup
- 新浪财经 (direct HTTP): K-line fallback, financial statements
- 同花顺 (direct HTTP): consensus EPS, hot stocks, northbound capital flow
- 财联社 (direct HTTP): global news wire
"""

from __future__ import annotations

from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json as _json
import os
import logging
import math
import random
import re as _re
import socket
import time
import uuid
import urllib.request

import pandas as pd
import requests as _requests

try:
    from curl_cffi import requests as _curl_cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: ticker format & market detection
# ---------------------------------------------------------------------------

def _get_prefix(code: str) -> str:
    """6-digit A-stock code -> market prefix for Tencent API."""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


def _normalize_ticker(symbol: str) -> str:
    """Strip exchange prefix/suffix, return pure 6-digit code.

    Handles: '688017', 'SH688017', '688017.SH', 'sh688017'
    """
    s = symbol.strip().upper()
    # Remove .SH / .SZ / .BJ suffix
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Remove SH / SZ / BJ prefix
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return safe_ticker_component(s)


# ---------------------------------------------------------------------------
# 数据约束：安全格式化数值，避免离谱数据误导 LLM
# ---------------------------------------------------------------------------

# 常用指标的合理范围（超出范围标注为异常值）
_VALUE_CONSTRAINTS = {
    "pe": (-500, 1000),          # 市盈率
    "pe_ttm": (-500, 1000),      # 滚动市盈率
    "pe_static": (-500, 1000),   # 静态市盈率
    "pb": (-50, 100),            # 市净率
    "ps": (-100, 500),           # 市销率
    "roe": (-200, 200),          # 净资产收益率 (%)
    "roa": (-100, 100),          # 总资产收益率 (%)
    "gross_margin": (-100, 100), # 毛利率 (%)
    "net_margin": (-200, 100),   # 净利率 (%)
    "turnover_rate": (0, 100),   # 换手率 (%)
    "change_pct": (-20, 20),     # 涨跌幅 (%)
    "debt_ratio": (0, 100),      # 资产负债率 (%)
    "current_ratio": (0, 100),   # 流动比率
    "quick_ratio": (0, 50),      # 速动比率
}


def _safe_format_value(value, field_name: str, suffix: str = "") -> str:
    """安全格式化数值，超出合理范围的标注为异常值。

    Args:
        value: 待格式化的值
        field_name: 字段名（用于查找约束）
        suffix: 单位后缀（如 %、x 等）

    Returns:
        格式化后的字符串，异常值会标注 [异常值]
    """
    if value is None:
        return "N/A"

    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)

    import math
    if math.isnan(num) or math.isinf(num):
        return f"[异常值: NaN/Inf]"

    constraint = _VALUE_CONSTRAINTS.get(field_name)
    if constraint is None:
        return f"{num}{suffix}"

    min_val, max_val = constraint
    if num < min_val or num > max_val:
        return f"{num}{suffix} [异常值: 超出合理范围 {min_val}~{max_val}]"

    return f"{num}{suffix}"


# ---------------------------------------------------------------------------
# Stock name <-> code mapping (cached)
# ---------------------------------------------------------------------------

_name_to_code: dict[str, str] | None = None
_code_to_name: dict[str, str] | None = None


def _build_name_code_map() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code and code→name maps via mootdx (both SH & SZ markets)."""
    global _name_to_code, _code_to_name
    if _name_to_code is not None:
        return _name_to_code, _code_to_name

    client = _get_mootdx_client()
    n2c: dict[str, str] = {}
    c2n: dict[str, str] = {}

    try:
        for market in (0, 1):  # 0=SZ, 1=SH
            stocks = client.stocks(market=market)
            if stocks is None or stocks.empty:
                continue
            for _, row in stocks.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                if not _re.match(r"^[036]\d{5}$", code):
                    continue
                clean_name = name.replace(" ", "").replace("　", "")
                n2c[clean_name] = code
                c2n[code] = clean_name
    except Exception as e:
        # 网络抖动/通达信不可达时给出明确提示，而非冒泡成风马牛不相及的报错（#46/#66）
        raise ValueError(
            "无法通过 mootdx 解析股票名称（通达信服务暂时不可达）：%s。"
            "请稍后重试，或直接输入 6 位股票代码。" % e
        ) from e

    _name_to_code = n2c
    _code_to_name = c2n
    logger.info("Built stock name-code map: %d entries", len(n2c))
    return _name_to_code, _code_to_name


def resolve_ticker(user_input: str) -> str:
    """Resolve user input (code or Chinese name) to a 6-digit A-stock code.

    Accepts: '600379', 'SH600379', '600379.SH', '宝光股份'
    Returns: '600379'
    Raises: ValueError if not resolvable.
    """
    s = user_input.strip()
    if not s:
        raise ValueError("输入不能为空")

    has_chinese = any("一" <= ch <= "鿿" for ch in s)

    if not has_chinese:
        return _normalize_ticker(s)

    clean = s.replace(" ", "").replace("　", "")
    n2c, _ = _build_name_code_map()

    if clean in n2c:
        return n2c[clean]

    matches = {name: code for name, code in n2c.items() if clean in name}
    if len(matches) == 1:
        return next(iter(matches.values()))
    if len(matches) > 1:
        examples = ", ".join(f"{n}({c})" for n, c in list(matches.items())[:5])
        raise ValueError(f"'{s}' 匹配到多只股票: {examples}，请输入完整名称或代码")

    raise ValueError(f"找不到股票 '{s}'，请检查名称是否正确")


# ---------------------------------------------------------------------------
# mootdx client (singleton)
# ---------------------------------------------------------------------------

_mootdx_client = None

# 实测可用的通达信备选服务器（按延迟排序，2026-06 验证）。用于规避 mootdx
# 0.11.x 全新安装时 BESTIP.HQ 为空串导致的 `ValueError: not enough values to unpack`。
_TDX_SERVERS = [
    ("119.97.185.59", 7709), ("124.70.133.119", 7709), ("116.205.183.150", 7709),
    ("123.60.73.44", 7709), ("116.205.163.254", 7709), ("121.36.225.169", 7709),
    ("123.60.70.228", 7709), ("124.71.9.153", 7709), ("110.41.147.114", 7709),
    ("124.71.187.122", 7709),
]


def _probe_tdx(ip: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 握手探测通达信服务器是否可达。"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_mootdx_client():
    """Lazy-init 健壮版 mootdx Quotes client（TCP 连接，可复用）。

    规避 mootdx 0.11.x 全新安装的 BESTIP 空串 bug：先 TCP 探测内置服务器列表、
    用第一个可达的显式 server 绕过 BESTIP；三级 fallback（bestip 测速 → 裸 factory →
    明确 RuntimeError）保证 IP 老化/换网/老用户场景都能工作。
    """
    global _mootdx_client
    if _mootdx_client is not None:
        return _mootdx_client

    from mootdx.quotes import Quotes

    for ip, port in _TDX_SERVERS:
        if _probe_tdx(ip, port):
            _mootdx_client = Quotes.factory(market="std", server=(ip, port))
            return _mootdx_client
    try:
        _mootdx_client = Quotes.factory(market="std", bestip=True)  # fallback 1
        return _mootdx_client
    except Exception:
        pass
    try:
        _mootdx_client = Quotes.factory(market="std")  # fallback 2（老用户 config 已有 IP）
        return _mootdx_client
    except Exception as e:
        raise RuntimeError(
            "mootdx 通达信服务器均不可达（TCP 7709）。海外网络通常全部超时，"
            "请走国内代理或直接使用 6 位股票代码。原始错误：%s" % e
        ) from e


# ---------------------------------------------------------------------------
# Tencent Finance API
# ---------------------------------------------------------------------------

def _tencent_quote(codes: list[str]) -> dict[str, dict]:
    """Batch real-time quotes from Tencent Finance (qt.gtimg.cn).

    Returns dict[code] -> {name, price, pe_ttm, pb, mcap_yi, ...}
    """
    prefixed = [f"{_get_prefix(c)}{c}" for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    raw = resp.read().decode("gbk")

    result = {}
    for line in raw.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]  # strip sh/sz/bj prefix
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ---------------------------------------------------------------------------
# Eastmoney Datacenter unified helper (龙虎榜/解禁 etc.)
# ---------------------------------------------------------------------------

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# 东财防封：全局节流 + 会话复用 (Eastmoney anti-ban: throttle + Keep-Alive)
# ---------------------------------------------------------------------------
# 东财系 HTTP 接口（push2 / push2his / datacenter-web / search-api / np-weblist）
# 有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 / 5 分钟 ≥300 次 → 临时封 IP。
# 多 Agent 投研跑批量分析时会高频请求东财，是被封的头号元凶。所有 eastmoney.com
# 请求一律走 _em_get()：串行限流（最小间隔 + 随机抖动）+ 复用 Keep-Alive 会话 + 默认 UA。
# 注意：仅东财接口走此入口；mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等
# 不限流（实测不封 IP 或风控极弱）。批量任务可调大 EM_MIN_INTERVAL 进一步降速。
_EM_SESSION = _requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
# 两次东财请求最小间隔(秒)；批量多 Agent 场景可设环境变量 EM_MIN_INTERVAL=1.5~2 降速。
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]  # 模块级上次东财请求时间戳


def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。

    所有 eastmoney.com 接口都应通过它请求，避免多 Agent 高频拉数据被封 IP。
    串行限流：与上次东财请求间隔 < EM_MIN_INTERVAL 时 sleep 补足 + 0.1~0.5s 随机抖动。
    传入的 headers 会覆盖 session 默认 UA（用于保留各端点自己的 Referer/Origin）。

    优先使用 curl_cffi 模拟浏览器 TLS 指纹，绕过东财的 TLS 指纹反爬虫。
    """
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        merged_headers = {"User-Agent": _UA}
        if headers:
            merged_headers.update(headers)
        if _HAS_CURL_CFFI:
            return _curl_cffi_requests.get(
                url, params=params, headers=merged_headers,
                timeout=timeout, impersonate="chrome", **kwargs
            )
        else:
            return _EM_SESSION.get(
                url, params=params, headers=merged_headers, timeout=timeout, **kwargs
            )
    finally:
        _em_last_call[0] = time.time()


def _eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁 共用."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# 同花顺 EPS forecast helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _ths_eps_forecast(code: str) -> pd.DataFrame:
    """Fetch consensus EPS forecast from 同花顺 (direct HTTP).

    Returns DataFrame with columns roughly: 年度, 预测机构数, 最小值, 均值, 最大值.
    """
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://basic.10jqka.com.cn/",
    }
    r = _requests.get(url, headers=headers, timeout=15)
    r.encoding = "gbk"
    dfs = pd.read_html(r.text)
    # Find the table containing EPS data
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    # Fallback: return first table if exists
    return dfs[0] if dfs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Sina K-line fallback helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _sina_kline_fallback(code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Fetch daily K-line from Sina HTTP API as mootdx fallback.

    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.
    """
    prefix = "sh" if code.startswith("6") else "sz"
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    params = {
        "symbol": f"{prefix}{code}",
        "scale": "240",  # daily
        "ma": "no",
        "datalen": "800",
    }
    r = _requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = _json.loads(r.text)

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "Date": item["day"],
            "Open": float(item["open"]),
            "High": float(item["high"]),
            "Low": float(item["low"]),
            "Close": float(item["close"]),
            "Volume": int(item["volume"]),
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])

    if start_date:
        df = df[df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.to_datetime(end_date)]

    return df


def _last_ohlcv_date(df: pd.DataFrame) -> pd.Timestamp | None:
    """Return the latest OHLCV Date in a normalized dataframe."""
    if df is None or df.empty or "Date" not in df.columns:
        return None
    dates = pd.to_datetime(df["Date"], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max().normalize()


def _normalize_ohlcv_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV Date values to daily granularity."""
    if df is None or df.empty or "Date" not in df.columns:
        return df
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    return df.dropna(subset=["Date"])


def _needs_sina_supplement(df: pd.DataFrame, target_date: str | None) -> bool:
    """True when mootdx/cache data is older than the requested cutoff date."""
    if not target_date:
        return False
    last_date = _last_ohlcv_date(df)
    if last_date is None:
        return True
    target = pd.to_datetime(target_date).normalize()
    return last_date < target


def _merge_ohlcv(primary: pd.DataFrame, supplement: pd.DataFrame) -> pd.DataFrame:
    """Merge OHLCV frames, preferring supplement rows on duplicate dates."""
    frames = [frame for frame in (primary, supplement) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_ohlcv_dates(combined)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined = combined.sort_values("Date").reset_index(drop=True)
    return combined


def _supplement_stale_ohlcv_with_sina(
    code: str,
    df: pd.DataFrame,
    target_date: str | None,
    start_date: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Use Sina daily K-line to fill dates missing from mootdx/cache data."""
    if not _needs_sina_supplement(df, target_date):
        return df, False
    try:
        sina_df = _sina_kline_fallback(code, start_date, target_date)
    except Exception as e:
        logger.warning("sina K-line supplement failed for %s: %s", code, e)
        return df, False
    if sina_df.empty:
        return df, False
    merged = _merge_ohlcv(df, sina_df)
    return merged, _last_ohlcv_date(merged) != _last_ohlcv_date(df)


# ---------------------------------------------------------------------------
# OHLCV loading with cache (mootdx -> CSV)
# ---------------------------------------------------------------------------

def _load_ohlcv_astock(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via mootdx, cache to CSV, filter by curr_date.

    Mirrors stockstats_utils.load_ohlcv but uses mootdx instead of yfinance.
    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume
    """
    from .config import get_config

    code = _normalize_ticker(symbol)
    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{code}-astock-daily.csv")

    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if mtime.date() == datetime.now().date():
            data = pd.read_csv(cache_file, on_bad_lines="skip", encoding="utf-8")
            data = _normalize_ohlcv_dates(data)
            data, supplemented = _supplement_stale_ohlcv_with_sina(
                code, data, curr_date, start_date=None
            )
            if supplemented:
                data.to_csv(cache_file, index=False, encoding="utf-8")
            cutoff = pd.to_datetime(curr_date)
            return data[data["Date"] <= cutoff]

    # Fetch from mootdx — 800 daily bars (~3 years of trading days)
    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No OHLCV data from mootdx for {code}")

        # mootdx returns index named 'datetime' AND a column named 'datetime'
        # (plus year/month/day/hour/minute/volume). Drop duplicates before reset.
        df = df.drop(columns=["datetime", "year", "month", "day", "hour", "minute"], errors="ignore")
        df = df.reset_index()  # moves index 'datetime' → column 'datetime'
        rename_map = {
            "datetime": "Date",
            "open": "Open",
            "close": "Close",
            "high": "High",
            "low": "Low",
            "volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df = _normalize_ohlcv_dates(df)
    except Exception as e:
        logger.warning("mootdx OHLCV failed for %s: %s, trying sina HTTP fallback", code, e)
        # Fallback: Sina direct HTTP API
        try:
            df = _sina_kline_fallback(code)
            if df.empty:
                raise ValueError(f"No OHLCV data from sina for {code}")
        except Exception:
            raise ValueError(f"No OHLCV data from mootdx/sina for {code}")

    df, _ = _supplement_stale_ohlcv_with_sina(code, df, curr_date, start_date=None)

    # Cache to disk
    df.to_csv(cache_file, index=False, encoding="utf-8")

    # Filter by curr_date to prevent look-ahead bias
    cutoff = pd.to_datetime(curr_date)
    return df[df["Date"] <= cutoff]


# ===========================================================================
# 9 Vendor Methods (matching interface.py VENDOR_METHODS signatures)
# ===========================================================================


# ---- Real-time helper functions ----


def _get_sina_realtime_quote(code: str) -> Optional[Dict[str, Any]]:
    """从新浪财经获取单只股票的实时行情数据。

    Returns dict with keys: price, open, high, low, prev_close, volume, amount,
    date, time, name, code, etc.
    """
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        r = _requests.get(url, headers=headers, timeout=5)
        r.encoding = "gbk"
        text = r.text.strip()

        # Parse: var hq_str_sz301356="天振股份,26.67,26.68,27.05,27.20,26.55,..."
        if '="' not in text:
            return None
        content = text.split('="')[1].rstrip('";')
        if not content:
            return None
        fields = content.split(",")
        if len(fields) < 32:
            return None

        result = {
            "name": fields[0],
            "open": float(fields[1]) if fields[1] else 0.0,
            "prev_close": float(fields[2]) if fields[2] else 0.0,
            "price": float(fields[3]) if fields[3] else 0.0,
            "high": float(fields[4]) if fields[4] else 0.0,
            "low": float(fields[5]) if fields[5] else 0.0,
            "volume": float(fields[8]) if fields[8] else 0.0,
            "amount": float(fields[9]) if fields[9] else 0.0,
            "date": fields[30] if len(fields) > 30 else "",
            "time": fields[31] if len(fields) > 31 else "",
            "code": code,
        }

        # 只有价格有效才返回
        if result["price"] <= 0 or result["prev_close"] <= 0:
            return None

        return result
    except Exception as e:
        logger.debug(f"获取新浪实时行情失败 {code}: {e}")
        return None


def _augment_with_realtime(df: pd.DataFrame, rt: Dict[str, Any]) -> pd.DataFrame:
    """用实时行情数据补充 K 线数据（盘中/盘后使用最新价格更新当日K线）。

    - 如果最新K线日期就是今天，更新最后一行
    - 如果最新K线日期早于今天且今天是工作日，追加一行当日数据
    - 周末或节假日不追加新K线（当天不开市）
    """
    if df is None or df.empty or "Close" not in df.columns:
        return df
    if not rt or not rt.get("price"):
        return df

    price = float(rt["price"])
    if price <= 0:
        return df

    from datetime import datetime, date as date_type

    # 获取最新K线日期
    last_val = df["Date"].max()
    if hasattr(last_val, "date"):
        last_date = last_val.date()
    elif isinstance(last_val, date_type):
        last_date = last_val
    else:
        last_date = pd.Timestamp(last_val).date()

    yesterday_close = float(df.iloc[-1]["Close"]) if len(df) > 0 else price
    open_p = rt.get("open") or rt.get("prev_close") or yesterday_close
    high_p = rt.get("high") or price
    low_p = rt.get("low") or price
    vol = rt.get("volume") or 0
    amt = rt.get("amount") or 0

    today = datetime.now().date()

    # 检查是否交易日（排除周末和节假日）
    from app.utils.trading_time import is_trading_day

    is_weekday = is_trading_day(today)

    # 检查实时行情数据的日期是否与今日匹配
    rt_date_str = rt.get("date", "")
    rt_is_today = False
    if rt_date_str:
        try:
            rt_date = datetime.strptime(rt_date_str, "%Y-%m-%d").date()
            rt_is_today = rt_date == today
        except ValueError:
            rt_is_today = False

    # 周末不进行实时增强（当天不开市，实时行情返回的是最近交易日数据）
    if not is_weekday:
        logger.debug(f"跳过实时行情增强: 周末/节假日, today={today}")
        return df

    # 如果实时行情日期不是今日（可能是数据源延迟），跳过
    # 但如果价格有效且今日是工作日，仍尝试更新（兼容数据源日期格式不一致的情况）
    if rt_date_str and not rt_is_today:
        logger.debug(f"实时行情日期与今日不符: rt_date={rt_date_str}, today={today}")
        # 额外检查：如果实时行情的价格与最后一根K线收盘价差异很小，说明可能是同一交易日数据
        if abs(price - yesterday_close) < 0.001:
            return df

    df = df.copy()
    if last_date >= today:
        # 更新最后一行
        idx = df.index[-1]
        df.loc[idx, "Close"] = price
        if open_p is not None:
            df.loc[idx, "Open"] = open_p
        if high_p is not None:
            df.loc[idx, "High"] = high_p
        if low_p is not None:
            df.loc[idx, "Low"] = low_p
        if vol:
            df.loc[idx, "Volume"] = vol
    else:
        # 追加一行当日实时K线
        new_row = {
            "Date": pd.Timestamp(today),
            "Open": open_p,
            "High": high_p,
            "Low": low_p,
            "Close": price,
            "Volume": vol,
        }
        if "Amount" in df.columns:
            new_row["Amount"] = amt
        new_df = pd.DataFrame([new_row])
        df = pd.concat([df, new_df], ignore_index=True)

    return df


# ---- 1. get_stock_data ----


def get_stock_data(
    symbol: Annotated[str, "A-stock code (e.g. 688017, SH688017)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock price data via mootdx."""
    code = _normalize_ticker(symbol)

    data_source = "mootdx (TCP)"
    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No data from mootdx for {code}")

        # Drop duplicate datetime column + extra columns before reset_index
        df = df.drop(
            columns=["datetime", "year", "month", "day", "hour", "minute"],
            errors="ignore",
        )
        df = df.reset_index()  # index 'datetime' → column 'datetime'
        df = df.rename(
            columns={
                "datetime": "Date",
                "open": "Open",
                "close": "Close",
                "high": "High",
                "low": "Low",
                "volume": "Volume",
                "amount": "Amount",
            }
        )
        df = _normalize_ohlcv_dates(df)

    except Exception as e:
        logger.warning("mootdx K-line failed for %s: %s, trying sina HTTP fallback", code, e)
        # Fallback: Sina direct HTTP API
        try:
            df = _sina_kline_fallback(code, start_date, end_date)
            if df.empty:
                raise RuntimeError("K线数据获取失败：mootdx和新浪备用源均不可用，请检查网络连接")
            data_source = "sina HTTP (fallback)"
        except Exception as inner_e:
            raise RuntimeError(f"K线数据获取失败：mootdx和新浪备用源均不可用: {inner_e}") from inner_e

    df, supplemented = _supplement_stale_ohlcv_with_sina(code, df, end_date, start_date)
    if supplemented:
        data_source = f"{data_source} + sina HTTP supplement"

    # Filter by date range
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

    if df.empty:
        return (
            f"No data found for A-stock '{code}' "
            f"between {start_date} and {end_date}"
        )

    # 🔥 用实时行情补充当日数据（盘中分析时使用最新价格，而非仅上一交易日收盘价）
    rt_data = _get_sina_realtime_quote(code)
    if rt_data and rt_data.get("price") and rt_data["price"] > 0:
        df = _augment_with_realtime(df, rt_data)
        data_source = f"{data_source} + realtime (intraday)"

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    csv_out = df[["Date", "Open", "High", "Low", "Close", "Volume"]].to_csv(
        index=False
    )

    header = f"# Stock data for {code} (A-stock) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data source: {data_source}\n"
    header += (
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    return header + csv_out


# ---- 2. get_indicators ----

# Supported technical indicators with descriptions
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: Medium-term trend indicator.",
    "close_200_sma": "200 SMA: Long-term trend benchmark.",
    "close_10_ema": "10 EMA: Responsive short-term average.",
    "macd": "MACD: Momentum via EMA differences.",
    "macds": "MACD Signal: EMA smoothing of MACD line.",
    "macdh": "MACD Histogram: Gap between MACD and signal.",
    "rsi": "RSI: Momentum overbought/oversold indicator (70/30 thresholds).",
    "boll": "Bollinger Middle: 20 SMA basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: 2 std devs above middle.",
    "boll_lb": "Bollinger Lower Band: 2 std devs below middle.",
    "atr": "ATR: Average True Range volatility measure.",
    "vwma": "VWMA: Volume-weighted moving average.",
    "mfi": "MFI: Money Flow Index (volume + price momentum).",
}


def get_indicators(
    symbol: Annotated[str, "A-stock code"],
    indicator: Annotated[
        str, "technical indicator (e.g. rsi, macd, close_50_sma)"
    ],
    curr_date: Annotated[str, "Current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators using stockstats on mootdx OHLCV data."""
    from stockstats import wrap

    code = _normalize_ticker(symbol)

    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} not supported. "
            f"Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    try:
        data = _load_ohlcv_astock(code, curr_date)
        
        # 用实时行情补充当日数据（盘中分析时使用最新价格）
        rt_data = _get_sina_realtime_quote(code)
        if rt_data and rt_data.get("price") and rt_data["price"] > 0:
            data = _augment_with_realtime(data, rt_data)
        
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Trigger stockstats calculation
        df[indicator]

        # Build date -> value lookup
        ind_dict = {}
        for _, row in df.iterrows():
            d = row["Date"]
            v = row[indicator]
            ind_dict[d] = "N/A" if pd.isna(v) else str(round(float(v), 4))

        # Generate output for look_back window
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before = curr_dt - relativedelta(days=look_back_days)

        lines = []
        dt = curr_dt
        while dt >= before:
            ds = dt.strftime("%Y-%m-%d")
            val = ind_dict.get(ds, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{ds}: {val}")
            dt -= relativedelta(days=1)

        result = (
            f"## {indicator} values for {code} "
            f"from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + _INDICATOR_DESCRIPTIONS.get(indicator, "")
        )
        return result

    except Exception as e:
        raise RuntimeError(f"Error calculating {indicator} for {code}: {str(e)}") from e


# ---- 3. get_fundamentals ----


def get_fundamentals(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals from Tencent + mootdx + Eastmoney + 同花顺."""
    code = _normalize_ticker(ticker)

    try:
        lines = []

        # --- Tencent: real-time valuation ---
        try:
            tq = _tencent_quote([code])
            if code in tq:
                q = tq[code]
                lines.extend(
                    [
                        f"Name: {q['name']}",
                        f"Price: {q['price']}",
                        f"PE (TTM): {_safe_format_value(q['pe_ttm'], 'pe_ttm')}",
                        f"PE (Static): {_safe_format_value(q['pe_static'], 'pe_static')}",
                        f"PB: {_safe_format_value(q['pb'], 'pb')}",
                        f"Market Cap (100M CNY): {q['mcap_yi']}",
                        f"Float Market Cap (100M CNY): {q['float_mcap_yi']}",
                        f"Turnover Rate: {_safe_format_value(q['turnover_pct'], 'turnover_rate', '%')}",
                        f"Change: {_safe_format_value(q['change_pct'], 'change_pct', '%')}",
                        f"Limit Up: {q['limit_up']}",
                        f"Limit Down: {q['limit_down']}",
                    ]
                )
        except Exception as e:
            logger.warning("Tencent quote failed for %s: %s", code, e)

        # --- mootdx: financial snapshot (quarterly) ---
        try:
            client = _get_mootdx_client()
            fin = client.finance(symbol=code)
            if fin is not None and not (
                isinstance(fin, pd.DataFrame) and fin.empty
            ):
                row = fin.iloc[0] if isinstance(fin, pd.DataFrame) else fin
                field_map = {
                    "eps": "EPS (Quarterly)",
                    "bvps": "Book Value Per Share",
                    "roe": "ROE (%)",
                    "profit": "Net Profit",
                    "income": "Revenue",
                    "liutongguben": "Float Shares",
                    "zongguben": "Total Shares",
                }
                idx = row.index if hasattr(row, "index") else []
                for field, label in field_map.items():
                    if field in idx:
                        val = row[field]
                        if val is not None and str(val) != "nan":
                            formatted_val = _safe_format_value(val, field)
                            lines.append(f"{label}: {formatted_val}")
        except Exception as e:
            logger.warning("mootdx finance failed for %s: %s", code, e)

        # --- Eastmoney push2: basic stock info (direct HTTP) ---
        try:
            market_code = 1 if code.startswith("6") else 0
            _info_url = "https://push2.eastmoney.com/api/qt/stock/get"
            _info_params = {
                "fltt": "2",
                "invt": "2",
                "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
                "secid": f"{market_code}.{code}",
            }
            r = _em_get(_info_url, params=_info_params, timeout=10)
            d = r.json().get("data", {})
            if d:
                if d.get("f127"):
                    lines.append(f"行业: {d['f127']}")
                if d.get("f84"):
                    lines.append(f"总股本: {d['f84']}")
                if d.get("f85"):
                    lines.append(f"流通股本: {d['f85']}")
                if d.get("f116"):
                    lines.append(f"总市值: {d['f116']}")
                if d.get("f117"):
                    lines.append(f"流通市值: {d['f117']}")
                if d.get("f189"):
                    lines.append(f"上市日期: {d['f189']}")
        except Exception as e:
            logger.warning("eastmoney push2 stock info failed for %s: %s", code, e)

        # --- 同花顺 direct HTTP: consensus EPS forecast ---
        try:
            forecast_df = _ths_eps_forecast(code)
            if forecast_df is not None and not forecast_df.empty:
                lines.append("\n--- Consensus EPS Forecast (同花顺) ---")
                eps_by_year = {}
                for _, row in forecast_df.iterrows():
                    year = str(row.iloc[0]) if len(row) > 0 else ""
                    mean_eps_val = row.iloc[3] if len(row) > 3 else 0
                    count_val = row.iloc[1] if len(row) > 1 else 0
                    min_eps_val = row.iloc[2] if len(row) > 2 else "N/A"
                    max_eps_val = row.iloc[4] if len(row) > 4 else "N/A"
                    try:
                        mean_eps = float(mean_eps_val)
                    except (ValueError, TypeError):
                        mean_eps = 0
                    try:
                        count = int(count_val)
                    except (ValueError, TypeError):
                        count = 0
                    lines.append(
                        f"FY{year}: EPS={mean_eps} "
                        f"(range {min_eps_val}~{max_eps_val}, {count} analysts)"
                    )
                    if count < 3:
                        lines.append("  Warning: low coverage (<3 analysts)")
                    eps_by_year[year] = mean_eps

                # Forward PE / PEG / PE digestion
                try:
                    tq = _tencent_quote([code])
                    if code in tq:
                        price = tq[code]["price"]
                        years_sorted = sorted(eps_by_year.keys())
                        if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                            eps_cur = eps_by_year[years_sorted[0]]
                            fwd_pe = price / eps_cur
                            lines.append(
                                f"\nForward PE (FY{years_sorted[0]}): "
                                f"{fwd_pe:.1f}x (price={price}, EPS={eps_cur})"
                            )
                            if (
                                len(years_sorted) >= 2
                                and eps_by_year.get(years_sorted[1], 0) > 0
                            ):
                                eps_next = eps_by_year[years_sorted[1]]
                                cagr = eps_next / eps_cur - 1
                                if cagr > 0:
                                    peg = fwd_pe / (cagr * 100)
                                    lines.append(
                                        f"PEG: {peg:.2f} "
                                        f"(EPS CAGR={cagr * 100:.0f}%)"
                                    )
                                    if fwd_pe > 30:
                                        digest = math.log(fwd_pe / 30) / math.log(
                                            1 + cagr
                                        )
                                        lines.append(
                                            f"PE Digestion to 30x: {digest:.1f} years"
                                        )
                                    else:
                                        lines.append("PE already below 30x target")
                                else:
                                    lines.append(
                                        f"EPS declining ({cagr * 100:.0f}%), "
                                        f"PEG not applicable"
                                    )
                except Exception as e:
                    logger.warning("Forward PE calc failed for %s: %s", code, e)
        except Exception as e:
            logger.warning("Consensus EPS forecast failed for %s: %s", code, e)

        if not lines:
            return f"No fundamentals data found for A-stock '{code}'"

        header = f"# Company Fundamentals for {code} (A-stock)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error retrieving fundamentals for {code}: {str(e)}") from e


# ---- 4. get_balance_sheet ----


def _sina_stock_code(code: str) -> str:
    """Pure 6-digit code → sina format (sh688017 / sz000001 / bj832000)."""
    return f"{_get_prefix(code)}{code}"


def _get_financial_report_sina(
    code: str, report_type: str, freq: str, curr_date: str = None,
) -> pd.DataFrame:
    """Shared helper: fetch financial report via Sina direct HTTP API.

    report_type: '资产负债表' | '利润表' | '现金流量表'
    """
    _report_type_map = {
        "资产负债表": "fzb",
        "利润表": "lrb",
        "现金流量表": "llb",
    }
    source_type = _report_type_map.get(report_type, "lrb")

    prefix = "sh" if code.startswith("6") else "sz"
    paper_code = f"{prefix}{code}"
    url = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
    params = {
        "paperCode": paper_code,
        "source": source_type,
        "type": "0",
        "page": "1",
        "num": "20",
    }
    r = _requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
    d = r.json()

    result = d.get("result", {}).get("data", {})

    # ===== 新格式（2025年后的新浪API）：report_list 是日期->数据的字典 =====
    report_list = result.get("report_list", {})
    if isinstance(report_list, dict) and report_list:
        rows = []
        for date_str, report_data in sorted(report_list.items(), reverse=True):
            if not isinstance(report_data, dict):
                continue
            data_items = report_data.get("data", [])
            if not isinstance(data_items, list):
                continue
            row = {"报告日": date_str}
            for item in data_items:
                if not isinstance(item, dict):
                    continue
                title = item.get("item_title") or item.get("item_field")
                value = item.get("item_value")
                if title:
                    row[title] = value
            rows.append(row)

        if rows:
            df = pd.DataFrame(rows)

            # Filter by curr_date
            if curr_date and "报告日" in df.columns:
                df["报告日"] = pd.to_datetime(df["报告日"], errors="coerce")
                cutoff = pd.to_datetime(curr_date)
                df = df[df["报告日"] <= cutoff]

            # Filter by frequency (annual = month 12 reports only)
            if freq.lower() == "annual" and "报告日" in df.columns:
                months = pd.to_datetime(df["报告日"], errors="coerce").dt.month
                df = df[months == 12]

            return df.head(8)

    # ===== 旧格式兼容：直接的 items 数组 =====
    items = result.get(source_type, [])
    if not isinstance(items, list) or not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)

    # Filter by curr_date
    if curr_date and "报告日" in df.columns:
        df["报告日"] = pd.to_datetime(df["报告日"], errors="coerce")
        cutoff = pd.to_datetime(curr_date)
        df = df[df["报告日"] <= cutoff]

    # Filter by frequency (annual = month 12 reports only)
    if freq.lower() == "annual" and "报告日" in df.columns:
        months = pd.to_datetime(df["报告日"], errors="coerce").dt.month
        df = df[months == 12]

    return df.head(8)


def get_balance_sheet(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "资产负债表", freq, curr_date)

        if df.empty:
            return f"No balance sheet data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Balance Sheet for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        raise RuntimeError(f"Error retrieving balance sheet for {code}: {str(e)}") from e


# ---- 5. get_cashflow ----


def get_cashflow(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "现金流量表", freq, curr_date)

        if df.empty:
            return f"No cash flow data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Cash Flow for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        raise RuntimeError(f"Error retrieving cash flow for {code}: {str(e)}") from e


# ---- 6. get_income_statement ----


def get_income_statement(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "利润表", freq, curr_date)

        if df.empty:
            return f"No income statement data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Income Statement for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        raise RuntimeError(f"Error retrieving income statement for {code}: {str(e)}") from e


# ---- 7. get_news ----


def _fetch_news_eastmoney(code: str, page_size: int = 20) -> list[dict]:
    """Direct East Money search API for individual stock news."""
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_param = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    params = {
        "cb": "callback",
        "param": _json.dumps(inner_param, ensure_ascii=False),
        "_": "1",
    }
    headers = {
        "Referer": "https://so.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
    }

    resp = _em_get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    text = resp.text
    text = text[text.index("(") + 1 : text.rindex(")")]
    data = _json.loads(text)

    articles: list[dict] = []
    for item in data.get("result", {}).get("cmsArticleWebOld", []):
        articles.append({
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "time": item.get("date", ""),
            "source": item.get("mediaName", "东方财富"),
            "url": item.get("url", ""),
        })
    return articles


def _fetch_news_sina(code: str, page_size: int = 20) -> list[dict]:
    """Sina Finance stock news API (backup source)."""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = (
        f"https://vip.stock.finance.sina.com.cn/corp/view/"
        f"vCB_AllNewsStock.php?symbol={prefix}{code}&Page=1"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn/",
    }

    resp = _requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "gb2312"
    html = resp.text

    articles: list[dict] = []
    rows = _re.findall(
        r"(\d{4}-\d{2}-\d{2})\s*(?:&nbsp;)*(\d{2}:\d{2})\s*(?:&nbsp;)*"
        r"<a[^>]+href='([^']+)'[^>]*>([^<]+)</a>",
        html,
    )
    for date_str, time_str, link, title in rows[:page_size]:
        articles.append({
            "title": title.strip(),
            "content": "",
            "time": f"{date_str} {time_str}",
            "source": "新浪财经",
            "url": link,
        })
    return articles


def get_news(
    ticker: Annotated[str, "A-stock code"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via East Money direct API (Sina as fallback)."""
    code = _normalize_ticker(ticker)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    articles: list[dict] = []
    source_label = ""

    try:
        articles = _fetch_news_eastmoney(code)
        source_label = "东方财富"
    except Exception as e:
        logger.warning("East Money news fetch failed for %s: %s", code, e)

    if not articles:
        try:
            articles = _fetch_news_sina(code)
            source_label = "新浪财经"
        except Exception as e:
            logger.warning("Sina news fetch failed for %s: %s", code, e)

    if not articles:
        return f"No news found for A-stock '{code}'"

    news_str = ""
    count = 0
    for art in articles:
        pub_time = art.get("time", "")
        try:
            pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
            if pub_dt < start_dt or pub_dt > end_dt:
                continue
        except (ValueError, IndexError):
            pass

        title = art["title"]
        content = art.get("content", "")
        source = art.get("source", source_label)
        link = art.get("url", "")

        news_str += f"### {title} (source: {source})\n"
        if content:
            snippet = content[:300] + "..." if len(content) > 300 else content
            news_str += f"{snippet}\n"
        if link and link != "nan":
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        return (
            f"No news found for A-stock '{code}' "
            f"between {start_date} and {end_date}"
        )

    return (
        f"## {code} (A-stock) News, from {start_date} to {end_date}:\n\n"
        + news_str
    )


# ---- 8. get_global_news ----


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int, "Days to look back"] = 7,
    limit: Annotated[int, "Max articles"] = 10,
) -> str:
    """Get China/global financial news via direct HTTP (CLS + Eastmoney)."""
    start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(
        days=look_back_days
    )
    start_date = start_dt.strftime("%Y-%m-%d")

    all_news: list[dict] = []

    # Source 1: CLS wire (财联社快讯) — direct HTTP
    try:
        cls_url = "https://www.cls.cn/nodeapi/telegraphList"
        cls_params = {"rn": str(limit), "page": "1"}
        cls_headers = {"User-Agent": _UA, "Referer": "https://www.cls.cn/"}
        r_cls = _requests.get(cls_url, params=cls_params, headers=cls_headers, timeout=10)
        d_cls = r_cls.json()
        for item in d_cls.get("data", {}).get("roll_data", []):
            title = item.get("title", "") or item.get("brief", "")
            content = item.get("content", "") or item.get("brief", "")
            ctime = item.get("ctime", "")
            # ctime is unix timestamp
            pub_time = ""
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError, OSError):
                    pub_time = str(ctime)
            all_news.append({
                "title": title,
                "content": content,
                "time": pub_time,
                "source": "CLS Wire",
            })
    except Exception as e:
        logger.warning("CLS news fetch failed: %s", e)

    # Source 2: Eastmoney global (东财7x24资讯) — direct HTTP
    try:
        em_url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        em_params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(limit),
            "req_trace": str(uuid.uuid4()),
        }
        em_headers = {"User-Agent": _UA, "Referer": "https://kuaixun.eastmoney.com/"}
        r_em = _em_get(em_url, params=em_params, headers=em_headers, timeout=10)
        d_em = r_em.json()
        for item in d_em.get("data", {}).get("fastNewsList", []):
            title = item.get("title", "")
            summary = item.get("summary", "")[:200]
            pub_time = item.get("showTime", "")
            all_news.append({
                "title": title,
                "content": summary,
                "time": pub_time,
                "source": "Eastmoney Global",
            })
    except Exception as e:
        logger.warning("Eastmoney global news fetch failed: %s", e)

    if not all_news:
        return f"No global news found for {curr_date}"

    # Deduplicate by title
    seen: set[str] = set()
    unique: list[dict] = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)

    news_str = ""
    for n in unique[:limit]:
        news_str += f"### {n['title']} (source: {n['source']})\n"
        if n.get("content"):
            snippet = (
                n["content"][:300] + "..."
                if len(n["content"]) > 300
                else n["content"]
            )
            news_str += f"{snippet}\n"
        news_str += "\n"

    return (
        f"## China & Global Market News, from {start_date} to {curr_date}:\n\n"
        + news_str
    )


# ---- 9. get_insider_transactions ----


def get_insider_transactions(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get shareholder/insider activity via mootdx F10.

    Note: A-stock insider transaction data differs from US markets.
    Uses mootdx F10 shareholder research as the closest equivalent.
    """
    code = _normalize_ticker(ticker)

    try:
        client = _get_mootdx_client()
        text = client.F10(symbol=code, name="股东研究")

        if not text or not text.strip():
            return f"No insider/shareholder data found for A-stock '{code}'"

        header = f"# Shareholder Research for {code} (A-stock)\n"
        header += "# Note: A-stock equivalent of insider transactions\n"
        header += "# Data source: mootdx F10\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        import re

        sec4_hits = list(re.finditer(r"\r?\n【4\.股东变化】\r?\n", text))
        if sec4_hits:
            sec4_pos = sec4_hits[-1].start()
            before_sec4 = text[:sec4_pos]
            sec4_text = text[sec4_pos:]
            cut_at = 2000
            if len(sec4_text) > cut_at:
                sec4_text = (
                    sec4_text[:cut_at]
                    + "\n\n(... older shareholder history omitted, "
                    f"{len(text) - sec4_pos - cut_at} chars truncated ...)"
                )
            text = before_sec4 + sec4_text

        return header + text

    except Exception as e:
        raise RuntimeError(f"Error retrieving insider/shareholder data for {code}: {str(e)}") from e


# ---- 10. get_profit_forecast ----


def get_profit_forecast(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date (unused, for interface compat)"] = None,
) -> str:
    """Get consensus EPS forecasts with forward valuation (同花顺 direct HTTP)."""
    code = _normalize_ticker(ticker)

    try:
        df = _ths_eps_forecast(code)

        if df is None or df.empty:
            return f"No analyst coverage found for A-stock '{code}'"

        lines = [
            f"# Consensus EPS Forecast for {code} (A-stock)",
            f"# Source: 同花顺 analyst consensus (direct HTTP)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        eps_by_year = {}
        for _, row in df.iterrows():
            year = str(row.iloc[0]) if len(row) > 0 else ""
            count_val = row.iloc[1] if len(row) > 1 else 0
            mean_eps_val = row.iloc[3] if len(row) > 3 else 0
            min_eps_val = row.iloc[2] if len(row) > 2 else "N/A"
            max_eps_val = row.iloc[4] if len(row) > 4 else "N/A"
            try:
                count = int(count_val)
            except (ValueError, TypeError):
                count = 0
            try:
                mean_eps = float(mean_eps_val)
            except (ValueError, TypeError):
                mean_eps = 0
            lines.append(
                f"FY{year}: EPS={mean_eps} (range {min_eps_val}~{max_eps_val}), "
                f"analysts={count}"
            )
            if count < 3:
                lines.append("  Warning: low coverage (<3 analysts)")
            eps_by_year[year] = mean_eps

        # Forward valuation
        try:
            tq = _tencent_quote([code])
            if code in tq:
                price = tq[code]["price"]
                pe_ttm = tq[code]["pe_ttm"]
                lines.append(f"\nCurrent: price={price}, PE(TTM)={pe_ttm}")

                years_sorted = sorted(eps_by_year.keys())
                if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                    eps_cur = eps_by_year[years_sorted[0]]
                    fwd_pe = price / eps_cur
                    lines.append(
                        f"Forward PE (FY{years_sorted[0]}): {fwd_pe:.1f}x"
                    )
                    if (
                        len(years_sorted) >= 2
                        and eps_by_year.get(years_sorted[1], 0) > 0
                    ):
                        eps_next = eps_by_year[years_sorted[1]]
                        cagr = eps_next / eps_cur - 1
                        if cagr > 0:
                            peg = fwd_pe / (cagr * 100)
                            lines.append(
                                f"PEG: {peg:.2f} (CAGR={cagr * 100:.0f}%)"
                            )
                            if fwd_pe > 30:
                                digest = math.log(fwd_pe / 30) / math.log(
                                    1 + cagr
                                )
                                lines.append(
                                    f"PE Digestion to 30x: {digest:.1f} years"
                                )
                        else:
                            lines.append(
                                f"EPS declining ({cagr * 100:.0f}%), "
                                f"PEG not applicable"
                            )
        except Exception as e:
            logger.warning("Forward PE calc failed for %s: %s", code, e)

        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error retrieving profit forecast for {code}: {str(e)}") from e


# ---- 11. get_hot_stocks ----


def get_hot_stocks(
    curr_date: Annotated[str, "Date YYYY-MM-DD, empty string for today"] = "",
) -> str:
    """Get strong stocks with topic attribution from 同花顺 editorial team.

    Returns stocks that hit limit-up with human-curated reason tags
    explaining WHY they surged (e.g. '算力租赁+AI政务').
    """
    import requests

    if not curr_date or curr_date.strip() == "":
        curr_date = datetime.now().strftime("%Y-%m-%d")

    try:
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{curr_date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if data.get("errocode", 0) != 0:
            return f"同花顺 API error: {data.get('errormsg', 'unknown')}"

        rows = data.get("data") or []
        if not rows:
            return (
                f"No hot stocks data for {curr_date} "
                f"(may be non-trading day or data not yet available)"
            )

        lines = [
            f"# Hot Stocks with Topic Attribution ({curr_date})",
            f"# Source: 同花顺 editorial (human-curated reason tags)",
            f"# Total: {len(rows)} stocks",
            "",
        ]

        from collections import Counter

        all_tags: list[str] = []

        for row in rows:
            code = row.get("code", "")
            name = row.get("name", "")
            reason = row.get("reason", "")
            zhangfu = row.get("zhangfu", "")
            huanshou = row.get("huanshou", "")
            chengjiaoe = row.get("chengjiaoe", "")
            dde = row.get("ddejingliang", "")

            lines.append(
                f"{code} {name}: +{zhangfu}% "
                f"换手{huanshou}% 成交额{chengjiaoe} "
                f"大单净量{dde} | {reason}"
            )

            if reason:
                tags = [t.strip() for t in str(reason).split("+") if t.strip()]
                all_tags.extend(tags)

        if all_tags:
            cnt = Counter(all_tags)
            lines.append(f"\n## Theme Frequency (top 15)")
            for tag, n in cnt.most_common(15):
                lines.append(f"  {tag}: {n} stocks")

        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error fetching hot stocks for {curr_date}: {str(e)}") from e


# ---- 12. get_northbound_flow ----


def _northbound_cache_path() -> str:
    """Path to local CSV cache for northbound daily close snapshots."""
    from .config import get_config

    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "northbound_daily.csv")


def _save_northbound_snapshot(date_str: str, hgt: float, sgt: float) -> None:
    """Append today's northbound close to local CSV cache (dedup by date)."""
    import csv

    path = _northbound_cache_path()
    existing: dict[str, tuple[str, str]] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    existing[row[0]] = (row[1], row[2])
    existing[date_str] = (f"{hgt:.2f}", f"{sgt:.2f}")
    sorted_dates = sorted(existing.keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hgt", "sgt"])
        for d in sorted_dates:
            writer.writerow([d, existing[d][0], existing[d][1]])


def _load_northbound_history(n: int = 20) -> list[tuple[str, float, float]]:
    """Load last N days of northbound close data from local cache."""
    import csv

    path = _northbound_cache_path()
    if not os.path.exists(path):
        return []
    rows: list[tuple[str, float, float]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                try:
                    rows.append((row[0], float(row[1]), float(row[2])))
                except ValueError:
                    continue
    return rows[-n:]


def get_northbound_flow(
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily data (last 20 trading days)"
    ] = False,
) -> str:
    """Get northbound capital flow (沪深股通) from 同花顺 hsgtApi.

    Realtime: minute-level cumulative net buying for HGT(沪股通) + SGT(深股通).
    History: self-cached daily close snapshots (upstream APIs stopped updating
    northbound history since 2024-08).
    """
    import requests

    hsgt_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "Chrome/117.0.0.0 Safari/537.36"
        ),
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }

    lines = [
        f"# Northbound Capital Flow ({curr_date})",
        "# Source: 同花顺 hsgtApi (沪深股通) + local cache",
        "",
    ]

    hgt_close = 0.0
    sgt_close = 0.0
    got_realtime = False

    try:
        url_rt = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = requests.get(url_rt, headers=hsgt_headers, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if times:
            lines.append("## Realtime (cumulative net buying, 亿元)")
            n = len(times)
            start_idx = max(0, n - 10)
            for i in range(start_idx, n):
                t = times[i]
                h = hgt[i] if i < len(hgt) else "N/A"
                s = sgt[i] if i < len(sgt) else "N/A"
                lines.append(f"  {t}: HGT={h} SGT={s}")

            hgt_close = float(hgt[-1]) if hgt else 0
            sgt_close = float(sgt[-1]) if sgt else 0
            total = hgt_close + sgt_close
            lines.append(
                f"\nClose: HGT(沪股通)={hgt_close:.2f}亿 "
                f"SGT(深股通)={sgt_close:.2f}亿 "
                f"Total={total:.2f}亿"
            )
            if total > 0:
                lines.append("Signal: Net northbound INFLOW (bullish)")
            elif total < 0:
                lines.append("Signal: Net northbound OUTFLOW (bearish)")
            got_realtime = True
        else:
            lines.append("No realtime data (non-trading hours or holiday)")

        if got_realtime:
            today_str = datetime.now().strftime("%Y-%m-%d")
            _save_northbound_snapshot(today_str, hgt_close, sgt_close)

        if include_history:
            history = _load_northbound_history(20)
            if history:
                lines.append("\n## Historical Daily Close (local cache, 亿元)")
                lines.append("Date       | HGT(沪股通) | SGT(深股通) | Total")
                for date, h, s in history:
                    lines.append(f"  {date}: HGT={h:.2f} SGT={s:.2f} Total={h + s:.2f}")
                avg_total = sum(h + s for _, h, s in history) / len(history)
                lines.append(
                    f"\n{len(history)}-day avg net flow: {avg_total:.2f}亿"
                )
                if got_realtime:
                    today_total = hgt_close + sgt_close
                    diff = today_total - avg_total
                    lines.append(
                        f"Today vs avg: {'+' if diff >= 0 else ''}{diff:.2f}亿 "
                        f"({'above' if diff >= 0 else 'below'} average)"
                    )
            else:
                lines.append(
                    "\n## Historical Daily: No cached data yet. "
                    "History accumulates automatically with each call."
                )

        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error fetching northbound flow: {str(e)}") from e


# ---- 14. get_fund_flow ----


def get_fund_flow(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily fund flow (last 20 days)"
    ] = True,
) -> str:
    """Get individual stock fund flow from 东财 push2.

    Realtime: minute-level main/large/medium/small/super order net inflow.
    History: daily net inflow for 20 trading days (push2his).

    V0.2.7: replaced 百度 PAE (fundflow/fundsortlist, offline since 2026-05)
    with 东财 push2 fund flow API.
    """
    code = _normalize_ticker(ticker)
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    lines = [
        f"# Fund Flow for {code} (A-stock)",
        f"# Source: 东财 push2 (Eastmoney)",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    try:
        # Realtime minute-level fund flow
        url_rt = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params_rt = {
            "secid": secid, "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        r = _em_get(url_rt, params=params_rt, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])

        if klines:
            lines.append(
                "## Realtime Minute Flow "
                "(主力/小单/中单/大单/超大单 净流入, 元)"
            )
            for line in klines[-10:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    lines.append(
                        f"  {parts[0]}: "
                        f"主力={float(parts[1])/1e4:.0f}万 "
                        f"大单={float(parts[4])/1e4:.0f}万 "
                        f"超大单={float(parts[5])/1e4:.0f}万"
                    )

            last_parts = klines[-1].split(",")
            if len(last_parts) >= 2:
                main_net = float(last_parts[1])
                lines.append(
                    f"\nClose: 主力净流入={main_net/1e4:.0f}万元"
                )
                if main_net > 0:
                    lines.append(
                        "Signal: Net main force INFLOW (bullish)"
                    )
                elif main_net < 0:
                    lines.append(
                        "Signal: Net main force OUTFLOW (bearish)"
                    )
        else:
            lines.append(
                "No realtime fund flow (non-trading hours or holiday)"
            )

        # Historical daily fund flow (push2his)
        if include_history:
            url_hist = (
                "https://push2his.eastmoney.com"
                "/api/qt/stock/fflow/daykline/get"
            )
            params_hist = {
                "secid": secid, "lmt": 20, "klt": 101,
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
            }
            rh = _em_get(url_hist, params=params_hist, timeout=10)
            dh = rh.json()
            hist_klines = dh.get("data", {}).get("klines", [])

            if hist_klines:
                lines.append(
                    f"\n## Historical Daily Fund Flow "
                    f"(last {len(hist_klines)} trading days)"
                )
                lines.append(
                    "Date | 主力净流入(万) | 大单(万) "
                    "| 中单(万) | 小单(万) | 超大单(万)"
                )
                for line in hist_klines:
                    parts = line.split(",")
                    if len(parts) >= 6:
                        lines.append(
                            f"  {parts[0]} "
                            f"| main={float(parts[1])/1e4:.0f} "
                            f"| large={float(parts[4])/1e4:.0f} "
                            f"| mid={float(parts[3])/1e4:.0f} "
                            f"| small={float(parts[2])/1e4:.0f} "
                            f"| super={float(parts[5])/1e4:.0f}"
                        )

        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error fetching fund flow for {code}: {str(e)}") from e


# ---------------------------------------------------------------------------
# 15. Dragon Tiger Board (龙虎榜)
# ---------------------------------------------------------------------------

def get_dragon_tiger_board(
    ticker: str,
    trade_date: str,
    look_back_days: int = 30,
) -> str:
    """Get dragon-tiger board (龙虎榜) appearances and seat details.

    Args:
        ticker: 6-digit A-share code, e.g. '000858'
        trade_date: YYYY-MM-DD
        look_back_days: how many days back to search (default 30)

    Returns:
        Formatted text with LHB appearances, top buyer/seller seats,
        and institutional activity.
    """
    code = safe_ticker_component(ticker)
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - pd.Timedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    lines = [f"# 龙虎榜数据 | {code} | {trade_date} (近{look_back_days}日)"]

    # 1. 上榜记录 — eastmoney datacenter direct HTTP
    try:
        data = _eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=(
                f"(TRADE_DATE>='{start_date_str}')"
                f"(TRADE_DATE<='{trade_date}')"
                f"(SECURITY_CODE=\"{code}\")"
            ),
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        if not data:
            lines.append(f"\n近{look_back_days}日未上龙虎榜。")
        else:
            lines.append(f"\n## 上榜记录 ({len(data)} 次)")
            lines.append("日期 | 原因 | 净买入(万) | 换手率")
            for row in data:
                net_buy = round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1)
                turnover = round(float(row.get("TURNOVERRATE") or 0), 2)
                lines.append(
                    f"  {str(row.get('TRADE_DATE', ''))[:10]} "
                    f"| {row.get('EXPLANATION', '')} "
                    f"| {net_buy:.0f} "
                    f"| {turnover:.2f}%"
                )
    except Exception as e:
        lines.append(f"龙虎榜列表查询失败: {e}")

    # 2. 最近上榜的买卖席位 — eastmoney datacenter direct HTTP
    try:
        if data:
            latest_date = str(data[0].get("TRADE_DATE", ""))[:10]
            lines.append(f"\n## 最近上榜席位明细 ({latest_date})")

            # 买入席位
            buy_data = _eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="BUY",
                sort_types="-1",
            )
            if buy_data:
                lines.append("\n### 买入席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in buy_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )

            # 卖出席位
            sell_data = _eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="SELL",
                sort_types="-1",
            )
            if sell_data:
                lines.append("\n### 卖出席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in sell_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )
    except Exception:
        pass

    # 3. 机构动向 — 从买卖席位明细筛选机构专用席位 (OPERATEDEPT_CODE="0")
    try:
        inst_buy = 0.0
        inst_sell = 0.0
        for detail, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in (detail or []):
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    if side == "buy":
                        inst_buy += (row.get("BUY") or 0)
                    else:
                        inst_sell += (row.get("SELL") or 0)
        if inst_buy > 0 or inst_sell > 0:
            lines.append("\n## 机构动向")
            lines.append(
                f"  机构买入 {inst_buy/1e4:.0f} 万 "
                f"| 卖出 {inst_sell/1e4:.0f} 万 "
                f"| 净额 {(inst_buy - inst_sell)/1e4:.0f} 万"
            )
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 16. Lockup Expiry Calendar (限售解禁日历)
# ---------------------------------------------------------------------------

def get_lockup_expiry(
    ticker: str,
    trade_date: str,
    forward_days: int = 90,
) -> str:
    """Get lockup expiry schedule for a stock.

    Args:
        ticker: 6-digit A-share code
        trade_date: YYYY-MM-DD
        forward_days: how many days forward to check (default 90)

    Returns:
        Formatted text with historical unlock records and upcoming
        expiry calendar with impact metrics.
    """
    code = safe_ticker_component(ticker)
    lines = [f"# 限售解禁日历 | {code} | {trade_date}"]

    # 1. 历史解禁记录 — eastmoney datacenter direct HTTP
    try:
        history_data = _eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            page_size=15,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        if history_data:
            lines.append(f"\n## 个股解禁记录 (共 {len(history_data)} 批)")
            lines.append("解禁时间 | 类型 | 解禁数量 | 占比")
            for row in history_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| {row.get('FREE_SHARES_NUM', '')} "
                    f"| {row.get('FREE_RATIO', '')}"
                )
        else:
            lines.append("\n无历史解禁记录。")
    except Exception as e:
        lines.append(f"个股解禁查询失败: {e}")

    # 2. 未来待解禁 — eastmoney datacenter direct HTTP
    try:
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d") + pd.Timedelta(
            days=forward_days
        )
        end_str = end_dt.strftime("%Y-%m-%d")
        upcoming_data = _eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=(
                f"(SECURITY_CODE=\"{code}\")"
                f"(FREE_DATE>='{trade_date}')"
                f"(FREE_DATE<='{end_str}')"
            ),
            page_size=20,
            sort_columns="FREE_DATE",
            sort_types="1",
        )
        if upcoming_data:
            lines.append(f"\n## 未来 {forward_days} 天待解禁")
            for row in upcoming_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| 数量 {row.get('FREE_SHARES_NUM', '')} "
                    f"| 占比 {row.get('FREE_RATIO', '')}"
                )
        else:
            lines.append(f"\n未来 {forward_days} 天无待解禁。")
    except Exception as e:
        lines.append(f"解禁日历查询失败: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 17. Industry Comparison (行业横向对比)
# ---------------------------------------------------------------------------

_BAIDU_PAE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://gushitong.baidu.com/",
}


def get_concept_blocks(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """Get concept/sector/region blocks that a stock belongs to (百度股市通).

    Returns industry classification (申万), concept themes, and region.
    Each block includes current day's change percentage.
    """
    import requests

    code = _normalize_ticker(ticker)

    try:
        url = (
            "https://finance.pae.baidu.com/api/getrelatedblock"
            f'?stock=[{{"code":"{code}","market":"ab","type":"stock"}}]'
            "&finClientType=pc"
        )
        r = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=10)
        d = r.json()

        if str(d.get("ResultCode", -1)) != "0":
            return (
                f"Baidu PAE error: ResultCode={d.get('ResultCode')} "
                f"{d.get('ResultMsg', '')}"
            )

        result = d.get("Result", {})
        categories = result.get(code, [])
        if not categories:
            return f"No concept/block data for {code}"

        lines = [
            f"# Concept & Sector Blocks for {code} (A-stock)",
            f"# Source: 百度股市通 (Baidu PAE)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        concept_names: list[str] = []

        for cat in categories:
            cat_name = cat.get("name", "")
            items = cat.get("list", [])
            if not items:
                continue
            lines.append(f"## {cat_name}")
            for item in items:
                name = item.get("name", "")
                ratio = item.get("ratio", "")
                desc = item.get("describe", "")
                suffix = f" ({desc})" if desc else ""
                lines.append(f"  {name}{suffix}: {ratio}")
                if cat_name == "概念":
                    concept_names.append(name)

        if concept_names:
            lines.append(f"\nConcept tags: {' / '.join(concept_names)}")

        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"Error fetching concept blocks for {code}: {str(e)}") from e


def _extract_industry_from_blocks(blocks_text: str) -> list[str]:
    """从概念板块文本中提取行业名称列表（申万一级、二级）"""
    industries = []
    in_industry = False
    for line in blocks_text.split("\n"):
        if line.startswith("## 行业"):
            in_industry = True
            continue
        elif line.startswith("## "):
            in_industry = False
            continue
        if in_industry and line.strip():
            stripped = line.strip()
            match = _re.search(r"(.+?)\s*\(申万", stripped)
            if match:
                industries.append(match.group(1).strip())
            elif "：" in stripped:
                # 格式如 "国防军工 (申万一级): +3.86%"
                name_part = stripped.split("：")[0].strip()
                name = name_part.split("(")[0].strip()
                if name:
                    industries.append(name)
    return industries


def _get_sina_industry_list() -> dict:
    """从新浪财经获取行业列表，返回 {行业名称: {code, change_pct, count, leader}}"""
    import requests

    headers = {
        "Referer": "https://finance.sina.com.cn/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
    r = requests.get(url, headers=headers, timeout=10)

    # 提取 JSON 部分：找到第一个 { 和最后一个 }
    text = r.text
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace < 0 or last_brace <= first_brace:
        return {}

    try:
        raw = _json.loads(text[first_brace : last_brace + 1])
    except (_json.JSONDecodeError, ValueError):
        return {}
    result = {}
    for k, v in raw.items():
        parts = v.split(",")
        if len(parts) >= 6:
            name = parts[1]
            try:
                change_pct = float(parts[5]) if parts[5] else 0.0
            except (ValueError, IndexError):
                change_pct = 0.0
            result[name] = {
                "code": k,
                "name": name,
                "count": parts[2] if len(parts) > 2 else "",
                "change_pct": change_pct,
                "leader_code": parts[-4] if len(parts) > 4 else "",
                "leader_name": parts[-1] if parts else "",
            }
    return result


def _match_industry(industry_names: list[str], industry_map: dict) -> Optional[dict]:
    """在新浪行业列表中匹配申万行业名称，返回匹配的行业信息"""
    if not industry_names or not industry_map:
        return None

    # 常见的行业名称映射（申万 -> 新浪）
    name_mapping = {
        "国防军工": ["飞机制造", "船舶制造", "航天航空"],
        "电子": ["电子器件", "电子信息", "电子元件"],
        "计算机": ["电子信息", "软件开发"],
        "医药生物": ["生物制药", "医疗器械"],
        "电力设备": ["电气设备", "太阳能"],
        "汽车": ["汽车制造", "汽车配件"],
        "机械设备": ["机械行业", "仪器仪表"],
        "化工": ["化工行业", "化纤行业", "农药化肥"],
        "有色金属": ["有色金属", "稀土永磁"],
        "食品饮料": ["酿酒行业", "食品行业"],
    }

    # 1. 精确匹配
    for ind_name in industry_names:
        if ind_name in industry_map:
            return industry_map[ind_name]

    # 2. 预定义映射匹配
    for ind_name in industry_names:
        if ind_name in name_mapping:
            for sina_alias in name_mapping[ind_name]:
                if sina_alias in industry_map:
                    return industry_map[sina_alias]

    # 3. 模糊匹配（关键词包含）
    keywords = []
    for ind_name in industry_names:
        # 提取关键词，如"国防军工"提取"军工"，"军工电子Ⅱ"提取"军工"
        for kw in ["军工", "电子", "医药", "汽车", "化工", "机械", "电力", "银行", "地产", "食品", "计算机", "通信", "新能源", "光伏", "半导体", "芯片"]:
            if kw in ind_name:
                keywords.append(kw)

    best_match = None
    best_score = 0
    for sina_name, sina_info in industry_map.items():
        score = 0
        for kw in keywords:
            if kw in sina_name:
                score += 1
        if score > best_score:
            best_score = score
            best_match = sina_info

    return best_match


def _is_matched_industry(sina_name: str, industry_names: list[str]) -> bool:
    """判断新浪行业名称是否与申万行业匹配"""
    matched = _match_industry(industry_names, {sina_name: {"name": sina_name}})
    return matched is not None


def _get_sina_industry_stocks(industry_code: str, num: int = 10) -> list[dict]:
    """从新浪财经获取行业成分股列表"""
    import requests

    headers = {
        "Referer": "https://finance.sina.com.cn/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeData?page=1&num={num}&sort=changepercent&asc=0&node={industry_code}"
    )
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = _json.loads(r.text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_industry_comparison(
    ticker: str,
    trade_date: str,
    top_n: int = 15,
) -> str:
    """Get comprehensive industry/sector comparison including valuation context.

    Uses Baidu PAE for concept/industry blocks and Sina Finance for industry rankings.
    Provides peer valuation context for relative analysis.

    Args:
        ticker: 6-digit A-share code
        trade_date: YYYY-MM-DD
        top_n: number of top/bottom industries to show (default 15)

    Returns:
        Formatted report with:
        - Stock's industry and concept blocks
        - Full industry performance ranking
        - Target industry's component stocks (for valuation comparison)
        - Market style context
    """
    code = safe_ticker_component(ticker)
    lines = [f"# 行业与板块综合对比 | {code} | {trade_date}"]

    # === 第一部分：个股所属行业与概念板块 ===
    lines.append("\n## 一、所属行业与概念板块")
    blocks_text = ""
    try:
        blocks_text = get_concept_blocks(ticker)
        if "Error" not in blocks_text[:50] and "error" not in blocks_text[:50]:
            lines.append("数据来源：百度股市通")
            # 提取行业部分
            in_industry = False
            for line in blocks_text.split("\n"):
                if line.startswith("## 行业"):
                    in_industry = True
                    lines.append(line.replace("## 行业", "### 所属行业"))
                    continue
                elif line.startswith("## 概念"):
                    in_industry = False
                    lines.append("### 核心概念板块")
                    continue
                elif line.startswith("## 地域"):
                    lines.append("### 地域板块")
                    continue
                elif line.startswith("## "):
                    continue
                elif line.startswith("Concept tags"):
                    continue
                elif line.startswith("# "):
                    continue
                if in_industry and line.strip():
                    lines.append(line)
                elif not in_industry and line.strip().startswith("  ") and len(line.strip()) < 30:
                    # 概念板块只显示前10个
                    pass
        else:
            lines.append(f"板块数据获取异常: {blocks_text[:100]}")
    except Exception as e:
        lines.append(f"板块数据获取失败: {e}")

    # 提取行业名称用于后续分析
    industry_names = _extract_industry_from_blocks(blocks_text) if blocks_text else []

    # === 第二部分：全行业涨跌幅排名 ===
    lines.append("\n## 二、全行业涨跌幅排名")
    industry_map = {}
    try:
        industry_map = _get_sina_industry_list()
        if industry_map:
            industries = sorted(
                industry_map.values(), key=lambda x: x["change_pct"], reverse=True
            )
            lines.append(f"数据来源：新浪财经（共 {len(industries)} 个行业）")
            lines.append("")
            lines.append("| 排名 | 行业 | 涨跌幅 | 成分股数 | 领涨股 |")
            lines.append("|------|------|--------|----------|--------|")

            # 涨幅前 top_n
            for i, item in enumerate(industries[:top_n]):
                highlight = " ⭐" if _is_matched_industry(item["name"], industry_names) else ""
                lines.append(
                    f"| {i+1} | {item['name']}{highlight} | {item['change_pct']:.2f}% "
                    f"| {item['count']} | {item['leader_name']} |"
                )

            # 中间省略
            lines.append(f"| ... | ... (共 {len(industries)} 个行业) | ... | ... | ... |")

            # 跌幅前 top_n
            for i, item in enumerate(industries[-top_n:]):
                rank = len(industries) - top_n + i + 1
                highlight = " ⭐" if _is_matched_industry(item["name"], industry_names) else ""
                lines.append(
                    f"| {rank} | {item['name']}{highlight} | {item['change_pct']:.2f}% "
                    f"| {item['count']} | {item['leader_name']} |"
                )

            # 标记所属行业位置
            if industry_names:
                lines.append("\n> 注：⭐ 标记为目标个股所属行业")
        else:
            lines.append("行业排名数据获取为空。")
    except Exception as e:
        lines.append(f"行业排名数据获取失败: {e}")

    # === 第三部分：所属行业成分股（用于估值对比）===
    lines.append("\n## 三、所属行业成分股（估值对比参考）")
    if industry_names and industry_map:
        # 使用智能匹配找到最相关的行业
        target_industry = _match_industry(industry_names, industry_map)

        if target_industry:
            lines.append(f"对标行业：{target_industry['name']}（行业代码: {target_industry['code']}）")
            lines.append("")

            # 获取成分股列表（按涨跌幅排序，取前10和后5，加上领涨股）
            stocks = _get_sina_industry_stocks(target_industry["code"], num=20)
            if stocks:
                lines.append("| 序号 | 股票代码 | 股票名称 | 现价 | 涨跌幅 | 换手率 |")
                lines.append("|------|----------|----------|------|--------|--------|")
                for i, s in enumerate(stocks[:15]):
                    symbol = s.get("code", s.get("symbol", ""))
                    name = s.get("name", "")
                    price = s.get("trade", s.get("price", "-"))
                    change_pct = s.get("changepercent", "-")
                    turnover = s.get("turnoverratio", s.get("turnover", "-"))
                    lines.append(
                        f"| {i+1} | {symbol} | {name} | {price} | {change_pct}% | {turnover}% |"
                    )
                lines.append("")
                lines.append(
                    "> 💡 **估值建议**：请使用 `get_fundamentals` 工具获取上表中 3-5 只代表性股票（龙头股 + 同业务公司）的 PE/PB/ROE 数据，"
                    "与目标股进行横向对比，判断其相对估值水平。"
                    "建议关注：行业龙头估值、业务相近公司估值、估值分位数。"
                )
                lines.append("")
                lines.append(
                    "> ⚠️ **A股估值特点**："
                    "A股整体估值中枢高于美股，成长股/题材股PE 30-60倍为常态；"
                    "判断估值高低需结合行业景气度、市场风格、板块轮动阶段，不能仅凭绝对PE下结论。"
                )
            else:
                lines.append("行业成分股数据获取为空。")
                lines.append(
                    "> 建议：直接选择3-5只同行业知名公司，使用 `get_fundamentals` 获取其估值数据进行对比。"
                )
        else:
            lines.append(f"未在新浪行业列表中找到匹配的行业（申万行业: {', '.join(industry_names)}）")
            lines.append(
                "> 建议：手动选择3-5只同行业可比公司，使用 `get_fundamentals` 获取估值数据进行对比。"
            )
    else:
        lines.append("无法获取行业成分股数据。")
        lines.append(
            "> 建议：使用 `get_fundamentals` 工具获取3-5只同行业代表性公司的PE/PB进行对比。"
        )

    # === 第四部分：市场风格与板块环境判断指引 ===
    lines.append("\n## 四、市场风格与板块环境分析指引")
    lines.append("")
    lines.append("请结合以上数据分析：")
    lines.append("")
    lines.append("1. **板块位置**：目标行业在全市场涨幅排名中处于什么位置？处于领涨、跟涨还是落后状态？")
    lines.append("2. **板块热度**：所属概念板块中，哪些涨幅最大？是否有明确的主题炒作主线？")
    lines.append("3. **市场风格**：当前领涨行业偏向价值（金融/周期）还是成长（科技/新能源）？是否与目标股风格匹配？")
    lines.append("4. **相对估值视角**：")
    lines.append("   - 若整个板块都在拔估值，个股PE高可能是板块性行情，而非个股泡沫")
    lines.append("   - 若板块整体估值合理但个股显著偏高，需警惕个股回调风险")
    lines.append("   - A股主题炒作阶段，PE偏离行业均值是常见现象，需结合景气度判断")
    lines.append("5. **资金流向验证**：可结合资金面分析，确认板块是否有主力资金持续流入")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 融资融券数据（Margin Trading）
# ---------------------------------------------------------------------------

def get_margin_trading(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    look_back_days: Annotated[int, "Days to look back (default 30)"] = 30,
) -> str:
    """Get margin trading (融资融券) data for a stock.

    Shows financing balance (融资余额), margin buying (融资买入额),
    short selling balance (融券余额), and short selling volume.
    Key indicator for retail investor leverage sentiment.

    Args:
        ticker: 6-digit A-share code
        curr_date: YYYY-MM-DD
        look_back_days: how many days back to check

    Returns:
        Formatted text with margin trading history and trend analysis
    """
    code = _normalize_ticker(ticker)
    secucode = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"

    lines = [
        f"# 融资融券数据 | {code} | {curr_date} (近{look_back_days}日)",
        "# Source: 东方财富 datacenter (Eastmoney)",
        "",
    ]

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": "1",
            "pageSize": str(look_back_days),
            "sortColumns": "DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        }
        r = _em_get(url, params=params, timeout=10)
        d = r.json()
        data = d.get("result", {}).get("data", [])

        if not data:
            lines.append("无融资融券数据（可能是两融标的范围外的股票）")
            return "\n".join(lines)

        # 数据是倒序的（最新的在前），反转成正序
        data = list(reversed(data))

        lines.append(f"## 融资融券历史（近{len(data)}个交易日）")
        lines.append(
            "日期 | 融资余额(万) | 融资买入额(万) | 融资偿还额(万) | "
            "融券余额(万) | 融券卖出量(股)"
        )

        financing_balances = []
        margin_buying = []
        short_balances = []

        for row in data:
            date = str(row.get("DATE", ""))[:10]
            fin_bal = float(row.get("RZYE", 0) or 0) / 1e4  # 融资余额（元→万元）
            fin_buy = float(row.get("RZMRE", 0) or 0) / 1e4  # 融资买入额
            fin_repay = float(row.get("RZCHE", 0) or 0) / 1e4  # 融资偿还额
            short_bal = float(row.get("RQYE", 0) or 0) / 1e4  # 融券余额
            short_sell = float(row.get("RQMCL", 0) or 0)  # 融券卖出量

            financing_balances.append(fin_bal)
            margin_buying.append(fin_buy)
            short_balances.append(short_bal)

            lines.append(
                f"  {date} "
                f"| {fin_bal:.0f} "
                f"| {fin_buy:.0f} "
                f"| {fin_repay:.0f} "
                f"| {short_bal:.0f} "
                f"| {short_sell:.0f}"
            )

        # 趋势分析
        if len(financing_balances) >= 5:
            latest = financing_balances[-1]
            avg_5 = sum(financing_balances[-5:]) / 5
            change_pct = ((latest - avg_5) / avg_5 * 100) if avg_5 > 0 else 0

            lines.append("")
            lines.append("## 散户杠杆情绪分析")
            lines.append(f"- 最新融资余额: {latest:.0f} 万元")
            lines.append(f"- 5日平均融资余额: {avg_5:.0f} 万元")
            lines.append(f"- 融资余额变化: {'+' if change_pct >= 0 else ''}{change_pct:.2f}% (相对5日均值)")

            if change_pct > 10:
                lines.append(
                    "⚠️ 信号: 融资余额快速上升 → 散户加杠杆积极，"
                    "短期情绪亢奋，需警惕回调风险（反向指标）"
                )
            elif change_pct < -10:
                lines.append(
                    "📉 信号: 融资余额快速下降 → 杠杆资金出清，"
                    "若股价企稳可能是见底信号（反向指标）"
                )
            else:
                lines.append("📊 信号: 融资余额平稳 → 杠杆情绪中性")

            # 融资买入占比分析
            if len(margin_buying) >= 5:
                avg_buy_5 = sum(margin_buying[-5:]) / 5
                lines.append(f"- 5日平均融资买入额: {avg_buy_5:.0f} 万元")

    except Exception as e:
        lines.append(f"融资融券数据获取失败: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 户均持股/筹码集中度数据
# ---------------------------------------------------------------------------

def get_shareholder_concentration(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
) -> str:
    """Get shareholder concentration (户均持股) data.

    Shows average shares per shareholder, shareholder count changes,
    and chip concentration trend. Key metric for institutional accumulation.

    Args:
        ticker: 6-digit A-share code
        curr_date: YYYY-MM-DD

    Returns:
        Formatted text with shareholder concentration data and analysis
    """
    code = _normalize_ticker(ticker)

    lines = [
        f"# 户均持股/筹码集中度 | {code} | {curr_date}",
        "# Source: 东方财富 (Eastmoney F10)",
        "",
    ]

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_F10_EH_HOLDERNUM",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code}")',
            "pageNumber": "1",
            "pageSize": "10",
            "sortColumns": "END_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        }
        r = _em_get(url, params=params, timeout=10)
        d = r.json()
        data = d.get("result", {}).get("data", [])

        if not data:
            lines.append("暂无股东户数数据")
            return "\n".join(lines)

        lines.append(f"## 股东户数变化（近{len(data)}期）")
        lines.append("报告期 | 股东户数 | 户均持股(股) | 较上期变化(%)")

        holder_counts = []
        avg_shares_list = []

        for row in data:
            report_date = str(row.get("END_DATE", ""))[:10]
            holder_num = row.get("HOLDER_TOTAL_NUM", 0) or 0
            avg_shares = row.get("AVG_FREE_SHARES", 0) or 0
            change_pct = row.get("CHANGEWITHLAST", None)

            holder_counts.append(holder_num)
            avg_shares_list.append(avg_shares)

            change_str = (
                f"{change_pct:.2f}%"
                if change_pct is not None
                else "N/A"
            )

            lines.append(
                f"  {report_date} "
                f"| {holder_num:,} 户 "
                f"| {avg_shares:,.0f} "
                f"| {change_str}"
            )

        # 筹码集中度分析
        if len(holder_counts) >= 2:
            latest = holder_counts[0]
            previous = holder_counts[1]
            change = ((latest - previous) / previous * 100) if previous > 0 else 0

            lines.append("")
            lines.append("## 筹码集中度分析")
            lines.append(f"- 最新股东户数: {latest:,} 户")
            lines.append(f"- 较上期变化: {'+' if change >= 0 else ''}{change:.2f}%")

            if change < -5:
                lines.append(
                    "📈 信号: 股东户数显著下降 → 筹码正在集中，"
                    "可能有主力/机构在吸筹（看多信号）"
                )
            elif change > 5:
                lines.append(
                    "📉 信号: 股东户数显著增加 → 筹码正在分散，"
                    "可能主力在派发给散户（看空信号）"
                )
            else:
                lines.append("📊 信号: 股东户数变化不大 → 筹码集中度稳定")

            if len(avg_shares_list) >= 2:
                avg_latest = avg_shares_list[0]
                avg_prev = avg_shares_list[1]
                avg_change = (
                    ((avg_latest - avg_prev) / avg_prev * 100)
                    if avg_prev > 0 else 0
                )
                lines.append(f"- 户均持股变化: {'+' if avg_change >= 0 else ''}{avg_change:.2f}%")

    except Exception as e:
        lines.append(f"股东户数数据获取失败: {e}")

    return "\n".join(lines)



# ---------------------------------------------------------------------------
# 通达信风险扫描数据
# ---------------------------------------------------------------------------

def get_risk_scan(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
) -> str:
    """Get Tongdaxin risk scan data (通达信风险扫描).

    Provides a comprehensive risk assessment covering 4 categories:
    - Financial risks (财务类风险): earnings loss, goodwill, R&D capitalization, etc.
    - Market risks (市场类风险): regulatory actions, debt default, management changes, etc.
    - Trading risks (交易类风险): lockup expiry, pledge, northbound selling, etc.
    - ST/delisting risks (ST风险和退市): ST warning, delisting risk, etc.

    Args:
        ticker: 6-digit A-share code
        curr_date: YYYY-MM-DD

    Returns:
        Formatted text with risk scan results including risk items and their triggers
    """
    code = _normalize_ticker(ticker)

    lines = [
        f"# 通达信风险扫描 | {code} | {curr_date}",
        "# Source: 通达信 (Tongdaxin / 通达信风险扫描)",
        "",
    ]

    try:
        url = f"http://page1.tdx.com.cn:7615/site/pcwebcall_static/bxb/json/{code}.json"

        import gzip

        response = _requests.get(url, timeout=10)
        response.raise_for_status()

        try:
            raw = gzip.decompress(response.content).decode("utf-8", errors="replace")
        except OSError:
            raw = response.text

        raw_data = _json.loads(raw) if isinstance(raw, str) else raw

        total = raw_data.get("total", 0)
        num = raw_data.get("num", 0)
        name = raw_data.get("name", "")
        raw_categories = raw_data.get("data", [])

        score = max(0, min(100, 100 - num * 5)) if total > 0 else 0

        lines.append(f"## 风险概览")
        lines.append(f"- **股票名称**: {name}")
        lines.append(f"- **总检查项**: {total}")
        lines.append(f"- **风险项数**: 🔴 {num}")
        lines.append(f"- **风险安全分**: {score}/100（分数越高越安全）")
        lines.append("")

        if not raw_categories:
            lines.append("暂无风险数据")
            return "\n".join(lines)

        risk_items_summary = []
        for cat in raw_categories:
            cat_name = cat.get("name", "")
            rows = cat.get("rows", [])

            risk_items = []
            safe_items = []

            for row in rows:
                trig_yy = (row.get("trigyy") or "").strip()
                trig_yy = trig_yy.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
                item_name = row.get("lx", "")

                if trig_yy:
                    risk_items.append({
                        "name": item_name,
                        "reason": trig_yy.strip(),
                    })
                else:
                    safe_items.append(item_name)

            lines.append(f"## {cat_name} ({len(risk_items)}风险 / {len(safe_items)}安全)")
            lines.append("")

            if risk_items:
                lines.append("### 🔴 风险项")
                for i, item in enumerate(risk_items, 1):
                    lines.append(f"{i}. **{item['name']}**")
                    reason = item["reason"]
                    if "http" in reason:
                        import re as _re
                        reason = _re.sub(
                            r'TXT:?\s*https?://\S+',
                            '',
                            reason
                        ).strip()
                    lines.append(f"   - 原因: {reason}")
                    lines.append("")
                    risk_items_summary.append(f"{cat_name} - {item['name']}")

            if safe_items:
                lines.append("### 🟢 安全项")
                safe_display = "、".join(safe_items)
                lines.append(f"- {safe_display}")
                lines.append("")

        lines.append("## 风险项汇总")
        if risk_items_summary:
            for i, r in enumerate(risk_items_summary, 1):
                lines.append(f"{i}. {r}")
        else:
            lines.append("✅ 暂无风险项")
        lines.append("")

    except Exception as e:
        lines.append(f"风险扫描数据获取失败: {e}")
        logger.warning(f"风险扫描数据获取失败 {code}: {e}")

    return "\n".join(lines)
