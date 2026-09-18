"""概念分析数据层 —— 借鉴 tickflow-stock-panel 的「概念分析」思路。

在原有市场看板基础上，新增概念板块聚合：
  概念实时行情（涨跌幅 / 领涨股 / 资金流 / 换手率）、
  概念领涨/领跌榜、
  资金流榜。

数据来源（全部为公开板块级数据，不涉及个股推荐）：
  - 同花顺概念板块实时行情页 q.10jqka.com.cn/gn/（内嵌 gnSection JSON，含 294 个概念）
  - market_quotes 集合（领涨股名称解析）

全部为「大盘/板块级公开数据」，不涉及个股推荐。Redis 分级 TTL 缓存，全站共享一份。
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone

from app.services.cache_layer import cached

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# 同花顺概念板块行情页
_THS_GN_URL = "http://q.10jqka.com.cn/gn/"
_THS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
)


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


def _market_prefix(code: str) -> str:
    """根据代码推断市场前缀（SH/SZ/BJ），用于补齐名称为空时的展示。"""
    if code.startswith(("6", "90")):
        return "SH"
    if code.startswith(("8", "4", "92")):  # 北交所（含 920 新代码段）
        return "BJ"
    return "SZ"


def _resolve_lead_names(concepts: list[dict]) -> list[dict]:
    """为概念标注「板块代码」标签（同花顺概念代码 + 市场前缀）。

    注意：同花顺 gnSection 的 cid 字段是**概念板块代码**（如 308725），并非 A 股股票代码，
    不能用 market_quotes/股票行情去解析成股票名——否则会撞上同号的退市股（如 300309
    →「吉艾退」）等脏数据。统一显示为 `{code}({市场})`，前端外链到同花顺概念详情页。
    """
    for c in concepts:
        lc = str(c.get("lead_code") or "").strip()
        c["lead_name"] = f"{lc}({_market_prefix(lc)})" if lc else ""
    return concepts


def _build() -> dict:
    """同步构建概念分析数据。"""
    concepts = _resolve_lead_names(_fetch_concept_board())

    # 按涨跌幅排序，剔除无效
    valid = [c for c in concepts if c["pct_chg"] is not None]
    valid.sort(key=lambda c: c["pct_chg"], reverse=True)

    gainers = valid[:10]
    losers = valid[-10:][::-1] if len(valid) >= 10 else valid[::-1]

    # 资金流入榜（资金净流入前10） / 资金流出榜（资金净流出前10）
    money_leaders = sorted(valid, key=lambda c: c["money_flow"], reverse=True)[:10]
    money_followers = sorted(valid, key=lambda c: c["money_flow"], reverse=False)[:10]

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
        "money_leaders": money_leaders,
        "money_followers": money_followers,
    }


async def get_concept_analysis() -> dict:
    """概念分析：实时行情 + 领涨/领跌榜 + 资金流榜（Redis 缓存，market 级 TTL）。"""
    return await cached(
        "vibe:concept_analysis", _build,
        category="market",
        valid=lambda v: bool(v.get("concepts")),
    )