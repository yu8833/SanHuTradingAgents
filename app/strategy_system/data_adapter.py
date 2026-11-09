"""数据适配层 — 从 MongoDB stock_daily_quotes 读取日线行情并转为 pandas 面板。

移植自 tickflow-stock-panel 的 KlineRepository，但数据源改为本项目 MongoDB。
统一输出列: symbol, date, open, high, low, close, volume, amount, pct_chg。
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd

from app.core.data_source_priority import source_rank

logger = logging.getLogger(__name__)

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
    adjust: str = "none",
    notes: list[str] | None = None,
) -> pd.DataFrame:
    """从 stock_daily_quotes 加载日线行情并转为 pandas 面板。

    - 按 (symbol, date) 去重，多数据源时优先保留 DATA_SOURCE_PRIORITY 靠前者。
    - 返回列: symbol, date, open, high, low, close, volume, amount, pct_chg。
    - 若某 symbol 无数据，返回空 DataFrame（不抛错）。

    Args:
        adjust: 复权方式，'none'=不复权 / 'hfq'=用 pct_chg 链重建后复权价格。
            hfq 消除除权除息造成的价格断层（避免误触发 MA/突破类信号）：
            pct_chg 缺失（停牌/首日）处按当日零涨跌处理（即回退 raw）。
        notes: 可选，用于接收复权/清洗过程中的标注信息。
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
    # symbol_sources 记录每只 symbol 出现过的数据源集合（用于口径标注）。
    best: dict[tuple, tuple[int, int]] = {}
    rows: list[dict] = []
    symbol_sources: dict[str, set[str]] = {}
    cursor = collection.find(query, projection)
    for doc in cursor:
        code = doc.get("code") or doc.get("symbol")
        code = str(code) if code else ""
        trade_date = doc.get("trade_date", "")
        if not code or not trade_date:
            continue
        key = (code, trade_date)
        src = doc.get("data_source", "")
        symbol_sources.setdefault(code, set()).add(src or "")
        src_rank = source_rank(src)
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

    # === 复权治理（B3）：hfq 链重建 ===
    # 先复权再清洗：除权除息造成的 raw close 断层属于「应被复权修正」的正常事件，
    # 若先按 raw 跳变剔除会把除权日整行删掉，破坏链式连续性。
    if adjust == "hfq":
        df = _apply_hfq_adjust(df, symbol_sources, notes=notes)

    # 价格异常清洗：剔除非新股单日 |涨跌|>21% 或相邻收盘跳变>50% 的脏行，
    # 避免数据源错误/异常行情被当作真实收益（如单笔 +205% 的离群交易）。
    df = _sanitize_price_rows(df, notes=notes)
    return df


def _sanitize_price_rows(
    df: pd.DataFrame,
    notes: list[str] | None = None,
    max_abs_pct: float = 0.21,
    max_jump: float = 0.5,
) -> pd.DataFrame:
    """剔除价格异常行（非新股）。

    - 单日 |涨跌幅| > 21%（A 股主板/创业板/科创板涨跌停上限为 20%）；
    - 相邻交易日收盘价跳变 > 50%（未复权除权断层或数据错误）。

    「新股」定义为每只股票面板内的前 NEW_ROWS 个交易日（上市初期无涨跌停约束且
    常有大幅波动），不参与清洗，避免误删真实的首日行情。
    """
    if df.empty:
        return df
    new_rows = 10
    seq = df.groupby("symbol", sort=False).cumcount()
    is_new = seq < new_rows
    pct_bad = pd.to_numeric(df["pct_chg"], errors="coerce").abs() > max_abs_pct
    prev_close = df.groupby("symbol", sort=False)["close"].shift(1)
    ratio = (df["close"] / prev_close.where(prev_close > 0)).astype("float64")
    jump_bad = (ratio > (1 + max_jump)) | (ratio < (1 - max_jump))
    drop = (~is_new) & (pct_bad | jump_bad)
    n_drop = int(drop.sum())
    if n_drop:
        logger.warning(f"⚠️ 价格异常清洗：剔除 {n_drop} 行（|涨跌|>21% 或收盘跳变>50%）")
        if notes is not None:
            notes.append(f"价格异常清洗剔除 {n_drop} 行（非新股单日|涨跌|>21% 或跳变>50%）")
        df = df.loc[~drop].reset_index(drop=True)
    return df


def _apply_hfq_adjust(
    df: pd.DataFrame,
    symbol_sources: dict[str, set[str]],
    notes: list[str] | None = None,
) -> pd.DataFrame:
    """按 symbol 用 pct_chg（小数口径）链式重建后复权价格。

    hfq_close = close.ffill() * (1 + pct_chg).cumprod()（首行锚定 raw close），
    scale = hfq_close / raw_close 应用到 open/high/low；volume/amount 保持原值。

    边界：
    - pct_chg 缺失（停牌/首日）按当日零涨跌处理（即回退 raw，价格平走）；
    - 各数据源均存不复权的原始 OHLC，pct_chg 已统一为小数口径，因此混源
      不会造成价格等级漂移；链式复权对所有 symbol 一视同仁，消除除权断层。
    """
    if df.empty:
        return df

    parts: list[pd.DataFrame] = []
    adjusted_count = 0
    for symbol, g in df.groupby("symbol", sort=False):
        g = g.copy()
        close_f = g["close"].ffill()
        # 缺失涨跌幅按 0 处理（价格平走 = 回退 raw）；首行 pct_chg 通常为 NaN
        growth = (1.0 + g["pct_chg"].astype("float32").fillna(0.0)).astype(
            "float32", copy=False
        )
        # 后复权链：hfq[t] = c0 × Π_{i=1..t}(1+r[i])，首行锚定 raw close。
        # 除以 growth[0] 去掉首日自身涨跌的贡献（首日为 NaN→0 时等价于不除）。
        # 保证 hfq[t]/hfq[t-1] = (1+pct_chg[t])，与涨跌幅口径一致，收益率不畸变。
        g0 = growth.iloc[0]
        hfq_close = close_f.iloc[0] * growth.cumprod() / g0
        # 除 0 保护：raw close 为 0/NaN 时 scale 置 NaN，该行不缩放
        scale = hfq_close / close_f.mask(close_f == 0)
        g["close"] = hfq_close
        for col in ("open", "high", "low"):
            g[col] = g[col] * scale
        parts.append(g)
        adjusted_count += 1

    logger.info(f"✅ hfq 复权完成：{adjusted_count} 只")
    return pd.concat(parts, ignore_index=True) if parts else df


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


def _safe_float(v) -> float:
    """将可能为 None / str / 非数值 的字段转为 float，非法则返回 0。"""
    try:
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def normalize_realtime_snapshot(realtime_quote: dict) -> dict | None:
    """把 market_quotes 的单只实时快照归一化为标准行，供各分析模块合并。

    返回字段（均为统一口径）:
      - date: 行情对应交易日的 YYYY-MM-DD 字符串（兼容 20251028 / 2025-10-28）
      - open / high / low / close / volume / amount: 浮点数
      - pre_close: 昨收价（缺失为 0）
      - pct_chg: 当日涨跌幅，小数口径（0.0057 = +0.57%）

    仅当快照存在且交易日有效时返回 dict，否则返回 None。
    本函数只做归一化，不写库，不影响每日同步。
    """
    if not realtime_quote:
        return None
    rt_raw = str(realtime_quote.get("trade_date") or "")
    if not rt_raw:
        return None
    rt_date = rt_raw
    if len(rt_raw) == 8 and rt_raw.isdigit():
        rt_date = f"{rt_raw[:4]}-{rt_raw[4:6]}-{rt_raw[6:8]}"

    close = _safe_float(realtime_quote.get("close"))
    if close <= 0:
        return None

    pre_close = _safe_float(realtime_quote.get("pre_close"))
    if pre_close <= 0:
        pre_close = _safe_float(realtime_quote.get("prev_close"))

    # 涨跌幅优先由昨收计算（小数口径）；昨收缺失时用存档涨跌幅折算为小数
    pct = None
    if pre_close > 0:
        pct = close / pre_close - 1.0
    else:
        raw_pct = realtime_quote.get("pct_chg")
        if raw_pct is not None:
            try:
                pct = float(raw_pct)
                if abs(pct) > 1.5:  # 百分数（如 5.32）折为小数
                    pct = pct / 100.0
            except (TypeError, ValueError):
                pct = None

    return {
        "date": rt_date,
        "open": _safe_float(realtime_quote.get("open")),
        "high": _safe_float(realtime_quote.get("high")),
        "low": _safe_float(realtime_quote.get("low")),
        "close": close,
        "volume": _safe_float(realtime_quote.get("volume")),
        "amount": _safe_float(realtime_quote.get("amount")),
        "pre_close": pre_close,
        "pct_chg": pct,
    }


def merge_realtime_into_panel(
    df: pd.DataFrame,
    realtime_quote: dict,
    symbol: str,
) -> pd.DataFrame:
    """把当日实时快照合并进历史日线 DataFrame（追加或覆盖当日行）。

    输出列与 load_daily_panel 一致：date 为 YYYY-MM-DD 字符串，pct_chg 为小数口径。
    纯内存拼接（只读 market_quotes 快照），不写 stock_daily_quotes，不影响每日同步。
    """
    row = normalize_realtime_snapshot(realtime_quote)
    if row is None or df is None or df.empty:
        return df

    date_str = row["date"]
    has = (df["date"].astype(str) == date_str).any()
    if has:
        # 覆盖已有当日行（可能为历史落库的盘中数据，用最新实时快照覆盖）
        new_df = df.copy()
        mask = new_df["date"].astype(str) == date_str
        new_df.loc[mask, ["open", "high", "low", "close", "volume", "amount", "pct_chg"]] = [
            row["open"], row["high"], row["low"], row["close"],
            row["volume"], row["amount"], row["pct_chg"],
        ]
        return new_df
    # 追加当日实时行
    new_row = {
        "symbol": symbol,
        "date": date_str,
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
        "amount": row["amount"],
        "pct_chg": row["pct_chg"],
    }
    new_df = pd.concat([df.copy(), pd.DataFrame([new_row])], ignore_index=True)
    new_df = new_df.sort_values("date").reset_index(drop=True)
    return new_df