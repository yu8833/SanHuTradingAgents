"""
统一行情服务
整合多个数据源，根据场景智能选择最优数据源
- 少量股票：腾讯接口（数据全、实时性高）
- 大量股票：AKShare全市场快照（效率高）
- 使用统一同步缓存层
"""
import logging

logger = logging.getLogger(__name__)

_TENCENT_THRESHOLD = 20


def _get_cache_key(codes: list[str]) -> str:
    return f"unified_quotes:{','.join(sorted(codes))}"


def _merge_quotes(akshare_quotes: dict[str, dict], tencent_quotes: dict[str, dict]) -> dict[str, dict]:
    """合并两个数据源的行情数据，以腾讯数据为准，缺失的用AKShare补充

    🔥 统一字段口径（调用方约定）：
    - 腾讯源：amount_wan = 万元（tencent_quote 直接返回）
    - AKShare源：amount = 元（适配器按全局"amount=元"口径输出），
      合并到 amount_wan 时需要 ÷10000 转换为万元
    """
    result = {}
    all_codes = set(list(akshare_quotes.keys()) + list(tencent_quotes.keys()))
    for code in all_codes:
        tq = tencent_quotes.get(code, {})
        aq = akshare_quotes.get(code, {})
        if tq:
            result[code] = dict(tq)
        else:
            ak_amount = aq.get("amount")
            # AKShare 的 amount 是元，转成万元填充 amount_wan
            amount_wan = (ak_amount / 10000.0) if ak_amount is not None else None
            result[code] = {
                "name": aq.get("name", ""),
                "price": aq.get("close"),
                "change_pct": aq.get("pct_chg"),
                "change_amt": None,
                "amount_wan": amount_wan,
                "is_st": False,
                "pe_ttm": None,
                "pb": None,
                "mcap_yi": None,
                "float_mcap_yi": None,
                "turnover_pct": None,
            }
        result[code]["_source"] = "tencent" if tq else "akshare"
    return result


def _fetch_tencent_quotes(codes: list[str]) -> dict[str, dict]:
    """从腾讯接口获取行情"""
    try:
        from app.services import vibe_astock as astock
        return astock.tencent_quote(codes)
    except Exception as e:
        logger.error(f"腾讯行情获取失败: {e}")
        return {}


def _fetch_akshare_quotes(codes: list[str]) -> dict[str, dict]:
    """从AKShare全市场快照获取行情"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or getattr(df, "empty", True):
            logger.warning("AKShare spot 返回空数据")
            return {}

        def _safe_float(v):
            try:
                if v is None:
                    return None
                if isinstance(v, str):
                    s = v.strip().replace(",", "")
                    if s.endswith("%"):
                        s = s[:-1]
                    if s == "-" or s == "":
                        return None
                    return float(s)
                return float(v)
            except Exception:
                return None

        code_col = next((c for c in ["代码", "代码code", "symbol", "股票代码"] if c in df.columns), None)
        price_col = next((c for c in ["最新价", "现价", "最新价(元)", "price", "最新"] if c in df.columns), None)
        pct_col = next((c for c in ["涨跌幅", "涨跌幅(%)", "涨幅", "pct_chg"] if c in df.columns), None)
        amount_col = next((c for c in ["成交额", "成交额(元)", "amount", "成交额(万元)"] if c in df.columns), None)
        name_col = next((c for c in ["名称", "股票名称", "name"] if c in df.columns), None)

        if not code_col or not price_col:
            logger.error(f"AKShare spot 缺少必要列: code={code_col}, price={price_col}")
            return {}

        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            code_raw = row.get(code_col)
            if not code_raw:
                continue
            code_str = str(code_raw).strip()
            if code_str.isdigit():
                code_clean = code_str.lstrip('0') or '0'
                code = code_clean.zfill(6)
            else:
                code = code_str.zfill(6)
            close = _safe_float(row.get(price_col))
            pct = _safe_float(row.get(pct_col)) if pct_col else None
            amt = _safe_float(row.get(amount_col)) if amount_col else None
            name = str(row.get(name_col, "")) if name_col else ""
            result[code] = {"name": name, "close": close, "pct_chg": pct, "amount": amt}
        logger.info(f"AKShare spot 拉取完成: {len(result)} 条")
        return result
    except Exception as e:
        logger.error(f"获取AKShare实时快照失败: {e}")
        return {}


def get_unified_quotes(codes: list[str], prefer_source: str = "auto") -> dict[str, dict]:
    """
    获取统一行情数据

    Args:
        codes: 股票代码列表
        prefer_source: 优先数据源 (auto/tencent/akshare)

    Returns:
        股票代码 -> 行情数据 的字典
    """
    from app.services.sync_cache_layer import get_cache_sync, set_cache_sync

    codes = [c.strip() for c in codes if c and c.strip()]
    if not codes:
        return {}

    key = _get_cache_key(codes)
    cached_data = get_cache_sync(key)
    if cached_data:
        all_in_cache = all(code in cached_data for code in codes)
        if all_in_cache:
            logger.debug(f"统一行情命中缓存: {len(codes)}只股票")
            return {code: cached_data[code] for code in codes}

    if prefer_source == "auto":
        prefer_source = "tencent" if len(codes) < _TENCENT_THRESHOLD else "akshare"

    quotes = {}

    if prefer_source == "tencent":
        logger.info(f"统一行情使用腾讯接口: {len(codes)}只股票")
        tencent_quotes = _fetch_tencent_quotes(codes)
        missing_codes = [c for c in codes if c not in tencent_quotes]
        if missing_codes:
            logger.info(f"腾讯接口缺失 {len(missing_codes)} 只股票，补充AKShare")
            akshare_quotes = _fetch_akshare_quotes(missing_codes)
            quotes = _merge_quotes(akshare_quotes, tencent_quotes)
        else:
            quotes = {code: dict(q) for code, q in tencent_quotes.items()}
            for code in quotes:
                quotes[code]["_source"] = "tencent"

    elif prefer_source == "akshare":
        logger.info(f"统一行情使用AKShare接口: {len(codes)}只股票")
        akshare_quotes = _fetch_akshare_quotes(codes)
        missing_codes = [c for c in codes if c not in akshare_quotes]
        if missing_codes:
            logger.info(f"AKShare缺失 {len(missing_codes)} 只股票，补充腾讯")
            tencent_quotes = _fetch_tencent_quotes(missing_codes)
            quotes = _merge_quotes(akshare_quotes, tencent_quotes)
        else:
            quotes = _merge_quotes(akshare_quotes, {})

    if quotes:
        set_cache_sync(key, quotes, category="realtime")

    return quotes


def get_single_quote(code: str) -> dict | None:
    """获取单只股票行情"""
    quotes = get_unified_quotes([code], prefer_source="tencent")
    return quotes.get(code)


def refresh_quotes_cache(codes: list[str] | None = None) -> int:
    """强制刷新行情缓存"""
    from app.services.sync_cache_layer import set_cache_sync

    if codes is None:
        logger.info("刷新全市场行情缓存")
        akshare_quotes = _fetch_akshare_quotes([])
        if akshare_quotes:
            all_codes = list(akshare_quotes.keys())
            key = _get_cache_key(all_codes)
            set_cache_sync(key, akshare_quotes, category="realtime")
            return len(akshare_quotes)
        return 0
    else:
        logger.info(f"刷新指定股票行情缓存: {len(codes)}只")
        quotes = get_unified_quotes(codes, prefer_source="tencent")
        return len(quotes)
