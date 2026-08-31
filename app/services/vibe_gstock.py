"""美股 / 港股数据层 —— 移植自 global-stock-data（美港股全栈工具包）。

只并入「域内(东财)」的合规子集：全球指数 + 美港股行情 + 关键财务指标。
用途＝A 股「看隔夜外围脸色」+ 个股页支持美港股代码。

工程要点：
- 东财调用全部复用 `astock.em_get`（直连优先、避开用户 Clash 代理挂国内站）+
  `astock.eastmoney_datacenter`（datacenter 三表/指标已封装）。
- push2 stock/get 直连偶发掉连 → **push2 优先、失败降级 push2delay**（延时行情，研究场景足够），
  latch 到可用主机整进程复用（同成交额榜的做法）。
- Yahoo / SEC 等国外源不并入（需科学上网、且非必要）。

合规：只做客观数据整理，不预置标的、不推荐、不预测。
"""

from __future__ import annotations

import re
import urllib.request

from app.services import vibe_astock as astock

_UA_H = {"User-Agent": astock.UA}
_GS_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")
_gs_host = [0]  # 当前可用主机下标；首次 push2 掉连后 latch 到 push2delay

# 全球指数（东财 push2 secid）—— A 股看隔夜外围脸色的核心几个，均已实测。
# 宏观快扫（盘前）外围扩展：新增日经225 / KOSPI（亚太当日情绪，push2delay 实测可用）。
_INDICES = (
    {"key": "dji", "name": "道琼斯", "secid": "100.DJIA", "region": "美股"},
    {"key": "spx", "name": "标普500", "secid": "100.SPX", "region": "美股"},
    {"key": "ndx", "name": "纳斯达克", "secid": "100.NDX", "region": "美股"},
    {"key": "hsi", "name": "恒生指数", "secid": "100.HSI", "region": "港股"},
    {"key": "hstech", "name": "恒生科技", "secid": "124.HSTECH", "region": "港股"},
    {"key": "n225", "name": "日经225", "secid": "100.N225", "region": "亚太"},
    {"key": "kospi", "name": "韩国KOSPI", "secid": "100.KS11", "region": "亚太"},
)

# 富时中国 A50 期货：AKShare 东财全球期货行情中的「当月连续」/ 最近月合约。
# 东财 CME 期货 secid（ES/NQ/YM/CN00）容器实测不可达 → 按设计文档降级路径走 AKShare。
_FUTURES_TARGETS = (
    {"prefix": "ES00Y", "key": "spxfut", "name": "标普500期货", "region": "美股"},
    {"prefix": "NQ00Y", "key": "ndxfut", "name": "纳斯达克期货", "region": "美股"},
    {"prefix": "YM00Y", "key": "djifut", "name": "道指期货", "region": "美股"},
    {"prefix": "CN", "key": "a50fut", "name": "富时A50期货", "region": "新加坡"},
)

# 期货合约月份字母 → 数字（F=1月 ... Z=12月，跳过 I 避免与数字混淆）
_FUT_MONTH = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7,
              "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}

_SINA_UA_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}

# 搜索返回的 MktNum → (secucode 后缀, 市场名)
_MKT = {105: (".O", "NASDAQ"), 106: (".N", "NYSE"), 107: (".O", "US"), 116: (".HK", "HK")}

_QUOTE_FIELDS = "f43,f44,f45,f46,f48,f57,f58,f59,f60,f116,f170"


def _push2_stock_get(secid: str, fields: str) -> dict | None:
    """东财 push2 stock/get：push2 优先、失败降级 push2delay；latch 可用主机。空数据返回 None。"""
    params = {"secid": secid, "fields": fields}
    for i in range(_gs_host[0], len(_GS_HOSTS)):
        try:
            r = astock.em_get(f"https://{_GS_HOSTS[i]}/api/qt/stock/get",
                              params=params, headers=_UA_H, timeout=10)
            d = r.json().get("data")
        except Exception:
            continue
        if d:
            _gs_host[0] = i
            return d
    return None


def _price(d: dict, key: str):
    """f43 等价格字段：除以 10^f59 还原。'-' / None → None。"""
    v = d.get(key)
    if not isinstance(v, (int, float)):
        return None
    dec = d.get("f59") or 2
    return round(v / (10 ** dec), dec)


def _quote_from(d: dict) -> dict:
    chg = d.get("f170")
    return {
        "code": d.get("f57"), "name": d.get("f58"),
        "price": _price(d, "f43"), "open": _price(d, "f46"),
        "high": _price(d, "f44"), "low": _price(d, "f45"),
        "prev_close": _price(d, "f60"),
        "amount": d.get("f48") if isinstance(d.get("f48"), (int, float)) else None,
        "mcap": d.get("f116") if isinstance(d.get("f116"), (int, float)) and d.get("f116") else None,
        "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
    }


def global_indices() -> list[dict]:
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技 / 日经225 / KOSPI）。源无的档跳过。"""
    out = []
    for idx in _INDICES:
        d = _push2_stock_get(idx["secid"], "f43,f57,f58,f59,f60,f170")
        if not d:
            continue
        chg = d.get("f170")
        out.append({
            "key": idx["key"], "name": idx["name"], "region": idx["region"],
            "price": _price(d, "f43"),
            "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
        })
    return out


def vix_quote() -> dict | None:
    """VIX 恐慌指数（Sina b_VIX，东财无 VIX 指数 secid 容器实测不可达）。

    返回沿用现有结构 {key, name, price, change_pct, region}；失败返回 None。
    """
    try:
        req = urllib.request.Request(
            "https://hq.sinajs.cn/list=b_VIX", headers=_SINA_UA_H
        )
        text = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
        m = re.search(r'"([^"]*)"', text)
        if not m:
            return None
        parts = m.group(1).split(",")
        # var hq_str_b_VIX="VIX恐慌指数,15.17,0.75,5.20,,,2026-08-31,23:15:46,15.24,14.42,15.48,14.89,0";
        if len(parts) < 12:
            return None
        price = float(parts[1])
        prev_close = float(parts[9]) if parts[9] else 0.0
        change_pct = round((price / prev_close - 1) * 100, 2) if prev_close else None
        if price <= 0:
            return None
        return {"key": "vix", "name": "VIX恐慌指数", "region": "美股",
                "price": price, "change_pct": change_pct}
    except Exception:
        return None


def _front_month_code(codes: list[str], prefix: str, cur_key: int) -> str | None:
    """从期货合约代码中选最近月（>= 当前月）的主力合约代码。

    合约代码形如 `CN26U`（CN + 年份两位 + 月份字母）。返回最近未来月合约；
    无未来月合约时退而取最近的一个（避免次月合约尚未上市）。
    """
    best, best_key = None, None
    for code in codes:
        if not code.startswith(prefix):
            continue
        m = re.match(r"(\d{2})([A-Z])", code[len(prefix):])
        if not m:
            continue
        mon = _FUT_MONTH.get(m.group(2))
        if not mon:
            continue
        key = (2000 + int(m.group(1))) * 12 + mon
        if best_key is None or abs(key - cur_key) < abs(best_key - cur_key):
            best_key, best = key, code
    return best


def index_futures() -> list[dict]:
    """美股股指期货（标普/纳指/道指）+ 富时A50期货（AKShare 东财全球期货行情）。

    东财 CME 期货 secid 容器实测不可达，按设计文档降级路径走 AKShare：
    `futures_global_spot_em()` 返回全市场 600+ 期货合约，这里只按目标代码过滤。
    ES/NQ/YM 用「当月连续」合约（ES00Y 等）；A50 无连续合约，取最近月主力。
    返回沿用现有结构 {key, name, price, change_pct, region}；失败返回 []。
    """
    try:
        import akshare as ak
        df = ak.futures_global_spot_em()
        if df is None or df.empty:
            return []
        codes = df["代码"].astype(str).tolist()
        today = __import__("datetime").date.today()
        cur_key = today.year * 12 + today.month
        out = []
        for t in _FUTURES_TARGETS:
            if t["prefix"].endswith("00Y"):
                # 当月连续合约：精确匹配代码
                row = df[df["代码"].astype(str) == t["prefix"]]
            else:
                # A50：最近月主力合约
                code = _front_month_code(codes, t["prefix"], cur_key)
                row = df[df["代码"].astype(str) == code] if code else df.iloc[0:0]
            if row.empty:
                continue
            r = row.iloc[0]
            try:
                price = float(r.get("最新价"))
                change_pct = float(r.get("涨跌幅"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            out.append({
                "key": t["key"], "name": t["name"], "region": t["region"],
                "price": price, "change_pct": change_pct,
            })
        return out
    except Exception:
        return []


def macro_indices() -> list[dict]:
    """宏观快扫外围指数全集：现有 7 指数 + VIX + 股指期货 + A50 期货。

    每个指数沿用统一结构 {key, name, price, change_pct, region}。
    VIX/期货任一来源失败仅跳过该档，不阻塞整体。
    """
    out = global_indices()
    vix = vix_quote()
    if vix:
        out.append(vix)
    out.extend(index_futures())
    return out


def _search(q: str) -> dict | None:
    """东财搜索一次：市场过滤 + **精确代码匹配优先**，退而取第一条。

    只按 MktNum 过滤挑不出正股——东财搜 AAPL 会混入 AAPL22(票据)/AAPB(2倍做多ETF)，
    搜 BABA 混入 05593(窝轮)，且 SecurityType 分不开(正股与 ETF 同为 Type7、正股港股与窝轮同为 Type6)。
    正股的 Code 恰好等于查询词，故精确匹配 Code==q 最稳；无精确匹配(名称查询)才退回第一条。
    """
    url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {"input": q, "type": 14,
              "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": 10}
    try:
        r = astock.em_get(url, params=params, headers=_UA_H, timeout=10)
        rows = (r.json().get("QuotationCodeTable") or {}).get("Data") or []
    except Exception:
        return None
    matches = []
    for s in rows:
        try:
            mkt = int(s.get("MktNum"))
        except (TypeError, ValueError):
            continue
        if mkt in _MKT:
            matches.append((mkt, s))
    if not matches:
        return None
    mkt, s = next(((m, x) for m, x in matches if str(x.get("Code", "")).upper() == q), matches[0])
    suffix, market = _MKT[mkt]
    code = s.get("Code", "")
    return {"code": code, "name": s.get("Name", ""), "secid_prefix": mkt,
            "secucode": f"{code}{suffix}", "market": market}


def resolve_symbol(query: str) -> dict | None:
    """代码/名称 → {code, name, secid_prefix, secucode, market}。只认美股/港股。
    数字型港股短代码（如 `700`）补零到 5 位再试一次（东财按 `00700` 收）。"""
    q = query.strip().upper()
    if not q:
        return None
    hit = _search(q)
    if hit is None and q.isdigit() and len(q) < 5:
        hit = _search(q.zfill(5))
    return hit


def _key_metrics(secucode: str) -> dict | None:
    """东财 GMAININDICATOR 最新一期关键财务指标（美股/港股中文字段）。"""
    market = "HK" if secucode.endswith(".HK") else "US"
    rows = astock.eastmoney_datacenter(
        f"RPT_{market}F10_FN_GMAININDICATOR",
        filter_str=f'(SECUCODE="{secucode}")',
        page_size=1, sort_columns="REPORT_DATE", sort_types="-1")
    if not rows:
        return None
    m = rows[0]
    return {
        "report_date": str(m.get("REPORT_DATE") or "")[:10],
        "revenue": m.get("OPERATE_INCOME"),
        "revenue_yoy": m.get("OPERATE_INCOME_YOY"),
        "net_profit": m.get("PARENT_HOLDER_NETPROFIT") or m.get("HOLDER_PROFIT"),
        "eps": m.get("BASIC_EPS"),
        "roe": m.get("ROE_AVG"),
        "gross_margin": m.get("GROSS_PROFIT_RATIO"),
        "net_margin": m.get("NET_PROFIT_RATIO"),
        "debt_ratio": m.get("DEBT_ASSET_RATIO"),
    }


def us_hk_stock(query: str) -> dict:
    """个股聚合（美/港）：解析代码 → 行情 + 关键财务指标。查不到返回 {}。"""
    info = resolve_symbol(query)
    if not info:
        return {}
    d = _push2_stock_get(f"{info['secid_prefix']}.{info['code']}", _QUOTE_FIELDS)
    quote = _quote_from(d or {})  # 行情临时取不到也返回完整 null 形状，契合 GlobalQuote 类型
    return {
        "code": info["code"],
        "name": info["name"] or quote.get("name") or info["code"],
        "market": info["market"],
        "quote": quote,
        "metrics": _key_metrics(info["secucode"]),
    }
