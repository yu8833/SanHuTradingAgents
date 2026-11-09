"""
市场数据采集服务

为 MarketRegimeDetector 和 ExitRuleEngine 提供自动数据采集能力，
消除手动传参。所有数据采集都走缓存层 + 降级机制。

数据源：
- 指数价格/MA250/波动率分位：akshare stock_zh_index_daily
- 市场宽度（涨跌家数占比）：market_overview._sentiment()
- 融资余额变化：akshare stock_margin_sse + stock_margin_szse
- 全市场换手率：akshare stock_zh_a_spot_em 聚合
"""

import logging
from datetime import datetime, timedelta
from app.utils.timezone import now_tz

import numpy as np

from app.services import vibe_astock as astock
from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# 沪深300指数代码
HS300_INDEX_CODE = "sh000300"
# 用于波动率计算的交易日窗口
VOLATILITY_WINDOW = 20
# 用于融资余额变化计算的天数
MARGIN_CHANGE_DAYS = 5
# 用于换手率MA计算的天数
TURNOVER_MA_DAYS = 20


def _safe_akshare():
    """惰性获取 akshare（与 vibe_astock._akshare 一致的降级策略）"""
    try:
        return astock._akshare()
    except Exception as e:
        logger.warning(f"akshare 不可用: {e}")
        return None


def _fetch_index_daily(symbol: str) -> object | None:
    """获取指数日线数据（pandas DataFrame）"""
    ak = _safe_akshare()
    if ak is None:
        return None
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is not None and len(df) > 0:
            return df
    except Exception as e:
        logger.warning(f"获取指数日线失败 {symbol}: {e}")
    return None


def _calc_volatility_percentile(closes: list, window: int = VOLATILITY_WINDOW) -> float:
    """
    计算近20日波动率在历史中的分位

    原理：对每个交易日，计算过去 window 天的日收益率标准差，
    得到一条波动率时间序列，然后看最近一天的波动率在历史中处于什么分位。
    """
    if len(closes) < window + 10:
        return 0.5  # 数据不足，返回中性

    closes_arr = np.array(closes, dtype=float)
    returns = np.diff(np.log(closes_arr))  # 对数收益率

    # 滚动计算 window 日波动率
    vols = []
    for i in range(window, len(returns) + 1):
        vol = float(np.std(returns[i - window:i]))
        vols.append(vol)

    if len(vols) < 10:
        return 0.5

    current_vol = vols[-1]
    # 计算分位（0-1）
    percentile = float(np.mean(np.array(vols) <= current_vol))
    return round(max(0.0, min(1.0, percentile)), 4)


def _fetch_margin_balance_change() -> float | None:
    """
    获取全市场融资余额近5日变化百分比

    数据源：akshare stock_margin_sse（上交所）+ stock_margin_szse（深交所）
    注意：两个接口参数不同，sse 支持 start_date/end_date，szse 不支持（返回全部历史）

    失败 / 数据不足返回 None（不再用 0.0 冒充「无变化」，避免情绪维度被静默判为中性）。
    """
    ak = _safe_akshare()
    if ak is None:
        return None

    # 主数据源：沪深合计的历史序列。stock_margin_szse 已退化为只回 1 行（不再可靠），
    # account_info 单接口直接给全市场融资余额（单位亿元，算变化率无需换算），更稳。
    try:
        df_all = ak.stock_margin_account_info()
        if df_all is not None and len(df_all) > MARGIN_CHANGE_DAYS + 1:
            df_all = df_all.copy()
            df_all["日期"] = df_all["日期"].astype(str)
            df_all = df_all.sort_values("日期")
            vals = [float(v) for v in df_all["融资余额"].tail(MARGIN_CHANGE_DAYS + 1).tolist()]
            if len(vals) >= MARGIN_CHANGE_DAYS + 1 and vals[0] != 0:
                return round(float((vals[-1] - vals[0]) / vals[0]), 4)
    except Exception as e:
        logger.warning(f"获取全市场融资余额(account_info)失败: {e}")

    # 回退：两所合并（保留原逻辑，防止主路径接口再变动）
    try:
        sse_map = {}  # {date_str: balance}
        szse_map = {}

        # 上交所融资余额（支持日期过滤）
        try:
            df_sse = ak.stock_margin_sse(
                start_date=(now_tz() - timedelta(days=30)).strftime("%Y%m%d"),
                end_date=now_tz().strftime("%Y%m%d"),
            )
            if df_sse is not None and len(df_sse) > 0:
                # 日期列名可能是"日期"或第一列
                date_col = "日期" if "日期" in df_sse.columns else df_sse.columns[0]
                bal_col = "融资余额" if "融资余额" in df_sse.columns else df_sse.columns[1]
                for _, row in df_sse.iterrows():
                    d = str(row[date_col]).replace("-", "").strip()
                    sse_map[d] = float(row[bal_col])
        except Exception as e:
            logger.warning(f"获取上交所融资余额失败: {e}")

        # 深交所融资余额（不支持日期参数，返回全部历史，取尾部）
        try:
            df_szse = ak.stock_margin_szse()
            if df_szse is not None and len(df_szse) > 0:
                date_col = "日期" if "日期" in df_szse.columns else df_szse.columns[0]
                bal_col = "融资余额" if "融资余额" in df_szse.columns else df_szse.columns[1]
                for _, row in df_szse.iterrows():
                    d = str(row[date_col]).replace("-", "").strip()
                    szse_map[d] = float(row[bal_col])
        except Exception as e:
            logger.warning(f"获取深交所融资余额失败: {e}")

        # 按日期对齐合并（修复：原代码按数组下标对齐导致不同日期被相加）
        all_dates = sorted(set(sse_map.keys()) & set(szse_map.keys()))
        if len(all_dates) < MARGIN_CHANGE_DAYS + 1:
            return None

        # 取最近 MARGIN_CHANGE_DAYS+1 个共同交易日
        recent_dates = all_dates[-(MARGIN_CHANGE_DAYS + 1):]
        total_recent = [sse_map[d] + szse_map[d] for d in recent_dates]

        if len(total_recent) < MARGIN_CHANGE_DAYS + 1:
            return None

        current = total_recent[-1]
        before = total_recent[0]
        if before == 0:
            return None

        change_pct = (current - before) / before
        return round(float(change_pct), 4)

    except Exception as e:
        logger.warning(f"获取融资余额变化失败: {e}")
        return None


def _fetch_market_turnover() -> tuple:
    """
    获取全市场平均换手率及其20日均值

    数据源：akshare stock_zh_a_spot_em（全市场快照，含换手率列）
    返回：(当前换手率, 20日均值)

    20 日均值需要历史序列才能算，当前未接入 → 返回 (当前值, None)；
    失败返回 (None, None)。不再用「当前值当均值」制造恒为 0 的偏离度
    （那会让「狂热」永远无法触发，却看起来像正常判断）。
    """
    ak = _safe_akshare()
    if ak is None:
        return None, None

    try:
        # 当前全市场换手率
        df = ak.stock_zh_a_spot_em()
        if df is None or len(df) == 0:
            return None, None

        # 换手率列名可能是"换手率"
        turnover_col = None
        for col_name in ["换手率", "turnover_rate"]:
            if col_name in df.columns:
                turnover_col = col_name
                break

        if turnover_col is None:
            return None, None

        # 过滤掉停牌（换手率为0或NaN）的股票
        turnovers = df[turnover_col].astype(float)
        turnovers = turnovers[(turnovers > 0) & turnovers.notna()]
        if len(turnovers) == 0:
            return None, None

        current_turnover = float(turnovers.mean())
        return round(current_turnover, 4), None

    except Exception as e:
        logger.warning(f"获取全市场换手率失败: {e}")
        return None, None


def _fetch_breadth_ratio() -> float | None:
    """获取市场宽度（上涨家数占比）；失败返回 None（不冒充 0.5 中性）。"""
    try:
        from app.services.market_overview import _sentiment
        sentiment = _sentiment()
        if not sentiment:
            return None

        up = sentiment.get("up", 0)
        down = sentiment.get("down", 0)
        flat = sentiment.get("flat", 0)
        total = up + down + flat
        if total == 0:
            return None
        return round(up / total, 4)
    except Exception as e:
        logger.warning(f"获取市场宽度失败: {e}")
        return None


def _fetch_index_price() -> float:
    """获取沪深300当前价"""
    try:
        indices = astock.index_quote()
        for idx in indices:
            name = idx.get("name", "")
            if "沪深300" in name or "300" in name:
                price = float(idx.get("price", 0))
                if price > 0:
                    return price
    except Exception as e:
        logger.warning(f"获取沪深300指数失败: {e}")
    return 0.0


def _build_daily_state() -> dict:
    """
    日级别分量：指数 MA250 + 波动率分位 + 融资余额变化 + 全市场换手率。

    盘中基本不变（收盘后才更新），单独 6h 缓存，避免 60s 的实时刷新每次都重拉
    指数日线与两所融资余额历史（省流且稳定）。

    换手率快照（stock_zh_a_spot_em 全市场分页，实测约 2 分钟）也放在日级：
    它是日频指标，且其 20 日均值尚未接入历史序列、不参与情绪判定，
    放进 60s 的实时分量会阻塞页面刷新。
    """
    # 指数MA250 + 波动率分位（共用一次日线拉取）
    index_ma250 = 3800.0
    volatility_percentile = 0.5
    index_ok = False

    df = _fetch_index_daily(HS300_INDEX_CODE)
    if df is not None and len(df) > 0:
        closes = df["close"].astype(float).tolist()
        if len(closes) >= 250:
            index_ma250 = float(np.mean(closes[-250:]))
        elif len(closes) >= 20:
            index_ma250 = float(np.mean(closes))
        volatility_percentile = _calc_volatility_percentile(closes)
        index_ok = True

    # 融资余额变化（T+1 日频数据）；失败为 None，由上层标注降级
    margin_change = _fetch_margin_balance_change()

    # 全市场换手率（日频快照；20 日均值暂未接入）
    turnover_ratio, turnover_ma20 = _fetch_market_turnover()

    return {
        "index_ma250": round(index_ma250, 2),
        "volatility_percentile": volatility_percentile,
        "margin_balance_change_pct": margin_change,
        "turnover_ratio": turnover_ratio,
        "turnover_ma20": turnover_ma20,
        "_ok": {
            "index": index_ok,
            "margin": margin_change is not None,
            "turnover": turnover_ratio is not None,
        },
    }


def _build_live_state() -> dict:
    """
    实时分量：指数点位 + 市场宽度。

    盘中随行情变化，随 market 分类 TTL（交易时段 60s）刷新。
    """
    # 1. 指数当前价
    index_price = _fetch_index_price()

    # 2. 市场宽度（失败时回落 0.5 供旧检测器使用，但用 _ok 标记缺失）
    breadth_raw = _fetch_breadth_ratio()

    return {
        "index_price": round(index_price, 2) if index_price > 0 else 3800.0,
        "breadth_ratio": breadth_raw if breadth_raw is not None else 0.5,
        "_ok": {
            "index_price": index_price > 0,
            "breadth": breadth_raw is not None,
        },
    }


# 检测器 detect() 的入参白名单：采集结果里还会带 _ok 采集状态，不能直接 ** 展开
REGIME_INPUT_KEYS = (
    "index_price",
    "index_ma250",
    "volatility_percentile",
    "breadth_ratio",
    "margin_balance_change_pct",
    "turnover_ratio",
    "turnover_ma20",
)


def _build_regime_data() -> dict:
    """构建完整的市场环境检测数据（同步入口 / 单次全量构建）。"""
    return {**_build_daily_state(), **_build_live_state()}


async def collect_market_regime_data_with_sources() -> dict:
    """
    异步入口（带采集状态）：返回 7 个检测入参 + sources 数据源可用性。

    - 日级别分量（MA250/波动率分位/融资余额/换手率）：6h 缓存 + SWR，盘中不必重算；
    - 实时分量（指数点位/宽度）：交易时段 60s、非交易 30min（category=market）。

    sources 用于上层标注 data_quality=degraded，避免 akshare 失败被静默当成正常值。
    """
    daily = await cached(
        "retail:regime_daily_v2",
        _build_daily_state,
        category="default",
        ttl=21600,
        valid=lambda v: bool(v and v.get("index_ma250", 0) > 0),
        # 日级分量含全市场换手率快照（约 2 分钟），过期时先返回旧值再后台重建，
        # 避免「常用策略」页 60s 轮询被一次 2 分钟的重建阻塞。
        swr=True,
        stale_ttl=7 * 86400,
    )
    live = await cached(
        "retail:regime_live_v2",
        _build_live_state,
        category="market",
        valid=lambda v: bool(v and v.get("index_price", 0) > 0),
    )
    merged = {**daily, **live}
    ok = {**(daily.get("_ok") or {}), **(live.get("_ok") or {})}
    return {
        **{k: merged.get(k) for k in REGIME_INPUT_KEYS},
        "sources": {
            "index": bool(ok.get("index")),
            "index_price": bool(ok.get("index_price")),
            "breadth": bool(ok.get("breadth")),
            "margin": bool(ok.get("margin")),
            "turnover": bool(ok.get("turnover")),
        },
    }


async def collect_market_regime_data() -> dict:
    """
    异步入口：采集市场环境检测数据（分级缓存）。

    只返回检测器需要的 7 个入参，保证 `detect(**data)` 可安全调用；
    需要采集状态时用 collect_market_regime_data_with_sources。
    """
    data = await collect_market_regime_data_with_sources()
    return {k: data.get(k) for k in REGIME_INPUT_KEYS}


def collect_market_regime_data_sync() -> dict:
    """
    同步入口：直接采集（无缓存），供定时任务等同步上下文使用
    """
    data = _build_regime_data()
    return {k: data.get(k) for k in REGIME_INPUT_KEYS}
