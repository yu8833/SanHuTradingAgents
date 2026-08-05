"""概念分析数据层 —— 借鉴 tickflow-stock-panel 的「概念分析 → 概念轮动」思路。

在原有市场看板基础上，新增概念板块聚合：
  概念实时行情（涨跌幅 / 领涨股 / 资金流 / 换手率）、
  概念领涨/领跌榜、
  概念轮动 RPS 矩阵（多窗口累计涨幅）。

数据来源（全部为公开板块级数据，不涉及个股推荐）：
  - 同花顺概念板块实时行情页 q.10jqka.com.cn/gn/（内嵌 gnSection JSON，含 294 个概念）
  - 同花顺概念指数历史 stock_board_concept_index_ths（用于多窗口涨幅）
  - market_quotes 集合（领涨股名称解析）

全部为「大盘/板块级公开数据」，不涉及个股推荐。Redis 分级 TTL 缓存，全站共享一份。
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone

from app.core.database import get_mongo_db_sync
from app.services.cache_layer import cached

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# 同花顺概念板块行情页
_THS_GN_URL = "http://q.10jqka.com.cn/gn/"
_THS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
)
# 领涨股数量上限（并发解析名称，控制成本）
_MAX_LEAD = 40


def _num(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ths_v_cookie() -> str:
    """生成同花顺 v 验证 cookie（复用 akshare 的 ths.js）。"""
    try:
        import py_mini_racer
        from akshare.stock_feature.stock_board_concept_ths import _get_file_content_ths

        js = py_mini_racer.MiniRacer()
        js.eval(_get_file_content_ths("ths.js"))
        return js.call("v")
    except Exception as e:
        logger.warning(f"生成同花顺 v cookie 失败: {e}")
        return ""


def _fetch_concept_board() -> list[dict]:
    """抓取同花顺概念板块实时行情页，解析内嵌 gnSection JSON。

    返回 [{code, name, pct_chg, lead_code, money_flow, turnover}]，
    失败时返回空列表。
    """
    import html as htmllib
    import json

    import requests

    v_code = _ths_v_cookie()
    headers = {
        "User-Agent": _THS_UA,
        "Referer": "http://q.10jqka.com.cn/gn/",
        "Cookie": f"v={v_code}" if v_code else "",
    }
    try:
        resp = requests.get(_THS_GN_URL, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"抓取同花顺概念板块失败: {e}")
        return []

    m = re.search(r"id=\"gnSection\" value='(.*?)'>", resp.text)
    if not m:
        logger.warning("概念板块页面未找到 gnSection 数据")
        return []

    try:
        raw = json.loads(htmllib.unescape(m.group(1)))
    except Exception as e:
        logger.warning(f"解析 gnSection 失败: {e}")
        return []

    out = []
    for item in raw.values():
        if not isinstance(item, dict):
            continue
        name = str(item.get("platename", "")).strip()
        if not name:
            continue
        out.append({
            "code": str(item.get("platecode", "")),
            "name": name,
            "pct_chg": _num(item.get("199112")),
            "lead_code": str(item.get("cid", "")).strip(),
            "money_flow": _num(item.get("zjjlr")),
            "turnover": _num(item.get("zfl")),
        })
    return out


def _load_code_name_map() -> dict[str, str]:
    """从 market_quotes 集合构建 code -> name 映射（用于领涨股名称解析）。"""
    try:
        db = get_mongo_db_sync()
        coll = db["market_quotes"]
        m = {}
        for doc in coll.find(
            {"code": {"$exists": True}, "name": {"$exists": True}},
            {"code": 1, "name": 1, "_id": 0},
        ):
            code = str(doc.get("code") or "").strip()
            name = str(doc.get("name") or "").strip()
            if code and name:
                m[code] = name
        return m
    except Exception:
        return {}


def _market_prefix(code: str) -> str:
    """根据代码推断市场前缀（SH/SZ/BJ），用于补齐名称为空时的展示。"""
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("8", "4")):
        return "BJ"
    return "SZ"


def _resolve_lead_names(concepts: list[dict]) -> list[dict]:
    """为概念补充领涨股名称（优先 market_quotes，缺失时用统一行情兜底）。"""
    if not concepts:
        return concepts
    code_map = _load_code_name_map()
    # 仅对有限数量的领涨股做网络解析，避免大并发
    need = [c["lead_code"] for c in concepts if c["lead_code"] and c["lead_code"] not in code_map]
    if need:
        try:
            from app.services.unified_quotes import get_unified_quotes

            quotes = get_unified_quotes(need[:_MAX_LEAD])
            for code, q in quotes.items():
                code_map[code] = q.get("name") or code_map.get(code, "")
        except Exception as e:
            logger.warning(f"领涨股名称解析失败: {e}")

    for c in concepts:
        lc = c["lead_code"]
        if lc:
            c["lead_name"] = code_map.get(lc) or f"{lc}({_market_prefix(lc)})"
        else:
            c["lead_name"] = ""
    return concepts


def _build() -> dict:
    """同步构建概念分析数据。"""
    concepts = _resolve_lead_names(_fetch_concept_board())

    # 按涨跌幅排序，剔除无效
    valid = [c for c in concepts if c["pct_chg"] is not None]
    valid.sort(key=lambda c: c["pct_chg"], reverse=True)

    gainers = valid[:10]
    losers = valid[-10:][::-1] if len(valid) >= 10 else valid[::-1]

    # 资金流榜（资金净流入前10）
    money_rank = sorted(valid, key=lambda c: c["money_flow"], reverse=True)[:10]

    avg_pct = sum(c["pct_chg"] for c in valid) / len(valid) if valid else 0
    up_count = sum(1 for c in valid if c["pct_chg"] > 0)
    down_count = sum(1 for c in valid if c["pct_chg"] < 0)

    return {
        "total": len(concepts),
        "as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "breadth": {
            "up": up_count,
            "down": down_count,
            "avg_pct": round(avg_pct, 2),
        },
        "concepts": concepts,
        "gainers": gainers,
        "losers": losers,
        "money_leaders": money_rank,
    }


async def get_concept_analysis() -> dict:
    """概念分析：实时行情 + 领涨/领跌榜 + 资金流榜（Redis 缓存，market 级 TTL）。"""
    return await cached(
        "vibe:concept_analysis", _build,
        category="market",
        valid=lambda v: bool(v.get("concepts")),
    )


# ---------------------------------------------------------------------------
# 概念轮动 RPS 矩阵（多窗口累计涨幅）
# ---------------------------------------------------------------------------

# 多窗口累计涨幅（交易日）
_PCT_WINDOWS = [5, 10, 20, 60]


def _concept_index_returns(name: str) -> dict[str, float] | None:
    """获取单概念的多窗口累计涨幅（基于同花顺概念指数历史收盘价）。

    返回 {window: 累计涨幅百分数}，失败返回 None。仅取最近 ~90 个自然日。
    """
    import akshare as ak

    try:
        end = datetime.now(BEIJING).strftime("%Y%m%d")
        start = (datetime.now(BEIJING) - timedelta(days=120)).strftime("%Y%m%d")
        df = ak.stock_board_concept_index_ths(symbol=name, start_date=start, end_date=end)
        if df is None or df.empty:
            return None
        closes = df["收盘价"].astype(float).tolist()
        if len(closes) < 2:
            return None
        out = {}
        for w in _PCT_WINDOWS:
            if len(closes) > w:
                base = closes[-1 - w]
                out[w] = round((closes[-1] / base - 1) * 100, 2) if base else 0.0
            else:
                out[w] = None
        return out
    except Exception as e:
        logger.warning(f"获取概念 {name} 指数历史失败: {e}")
        return None


def _build_rotation(top_n: int = 40) -> dict:
    """构建概念轮动 RPS 矩阵：取当日涨幅前 top_n 的概念，计算多窗口累计涨幅。

    说明：多窗口累计涨幅需逐个拉取概念指数历史，成本较高，故仅对「当日热门概念」
    子集计算。结果按类别缓存。
    """
    concepts = _fetch_concept_board()
    valid = [c for c in concepts if c["pct_chg"] is not None]
    valid.sort(key=lambda c: c["pct_chg"], reverse=True)
    hot = valid[:top_n]

    rows = []
    for c in hot:
        rets = _concept_index_returns(c["name"])
        if rets is None:
            continue
        rows.append({
            "code": c["code"],
            "name": c["name"],
            "pct_chg": c["pct_chg"],
            "returns": rets,
        })

    return {
        "windows": _PCT_WINDOWS,
        "as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "rows": rows,
    }


async def get_concept_rotation(top_n: int = 40) -> dict:
    """概念轮动 RPS 矩阵（Redis 缓存，financial 级 TTL，命中热概念子集）。"""
    return await cached(
        f"vibe:concept_rotation:{top_n}",
        lambda: _build_rotation(top_n),
        category="financial",
        valid=lambda v: bool(v.get("rows")),
    )