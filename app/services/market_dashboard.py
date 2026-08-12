"""市场看板数据层 —— 借鉴 tickflow-stock-panel 的 Dashboard 聚合。

在原有「市场情绪 + 板块资金流」基础上，新增全市场时刻聚合：
  情绪评分 + 6 维雷达（指数/赚钱/量能/投机/抗跌/主线）、
  KPI 指标行（涨/平/跌、强势/弱势、涨停/跌停+封板率、最高连板、成交额、换手/量比）、
  涨跌分布 8 档直方图 + 广度条、四大榜单（涨幅/跌幅/成交额/换手）、
  行业热度领涨/领跌。

数据来源：
  - market_quotes 集合（全市场实时快照，含 pct_chg/amount/turnover_rate/name/industry）
  - 复用 market_overview 的情绪/板块/短线情绪（akshare 免费源）
  - 大盘指数（vibe_astock.index_quote）

全部为「大盘/板块级公开数据」，不涉及个股推荐。Redis 分级 TTL 缓存，全站共享一份。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.core.database import get_mongo_db_sync
from app.services import vibe_astock as astock
from app.services.cache_layer import cached
from app.services.market_overview import _emotion, _sectors, _sentiment

BEIJING = timezone(timedelta(hours=8))


def _num(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _score(value: float, low: float, high: float) -> int:
    """将 value 线性映射到 0-100 分（越接近 high 越高）。"""
    if high <= low:
        return 50
    return max(0, min(100, round((value - low) / (high - low) * 100)))


def _load_name_fallback() -> dict[str, str]:
    """从 stock_basic_info 构建 code -> 中文名称 映射，用于 market_quotes 缺 name 时兜底。"""
    try:
        db = get_mongo_db_sync()
        m = {}
        for doc in db["stock_basic_info"].find(
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


def _load_market_rows() -> list[dict]:
    """读取全市场实时快照，返回带有效涨跌幅的行（仅保留 pct_chg 有效者）。"""
    try:
        db = get_mongo_db_sync()
        coll = db["market_quotes"]
        name_map = _load_name_fallback()
        rows = []
        for doc in coll.find({
            "code": {"$exists": True},
            "pct_chg": {"$ne": None},
        }, {
            "code": 1, "symbol": 1, "name": 1,
            "close": 1, "pct_chg": 1, "amount": 1,
            "turnover_rate": 1, "industry": 1,
            "_id": 0,
        }):
            pct = _num(doc.get("pct_chg"))
            if math.isnan(pct):
                continue
            code = str(doc.get("code") or doc.get("symbol") or "")
            rows.append({
                "code": code,
                "name": doc.get("name") or name_map.get(code) or code,
                "close": _num(doc.get("close")),
                "pct_chg": pct,
                "amount": _num(doc.get("amount")),
                # 保留 None 以区分「换手率缺失」与「真实为 0」，供量能兜底逻辑判断
                "turnover_rate": doc.get("turnover_rate"),
                "industry": doc.get("industry") or "",
            })
        return rows
    except Exception:
        return []


def _pct_band_rows(values: list[float]) -> list[dict]:
    bands = [
        ("<-5%", None, -5.0),
        ("-5~-3%", -5.0, -3.0),
        ("-3~-1%", -3.0, -1.0),
        ("-1~0%", -1.0, 0.0),
        ("0~1%", 0.0, 1.0),
        ("1~3%", 1.0, 3.0),
        ("3~5%", 3.0, 5.0),
        (">5%", 5.0, None),
    ]
    total = len(values) or 1
    out = []
    for label, low, high in bands:
        count = 0
        for v in values:
            if low is None and v < high or high is None and v >= low or low is not None and high is not None and low <= v < high:
                count += 1
        out.append({"label": label, "count": count, "pct": round(count / total * 100, 1)})
    return out


def _top_rows(rows: list[dict], key: str, descending: bool, limit: int = 8) -> list[dict]:
    filtered = [r for r in rows if r.get(key) is not None]
    filtered.sort(key=lambda r: r.get(key) or 0, reverse=descending)
    return [
        {
            "code": r["code"],
            "name": r["name"],
            "close": r["close"],
            "pct_chg": r["pct_chg"],
            "amount": r["amount"],
            "turnover_rate": r["turnover_rate"],
        }
        for r in filtered[:limit]
    ]


def _industry_rank(rows: list[dict]) -> dict:
    """行业热度：按行业资金流 pct 领涨/领跌（复用 _sectors 的即时资金流）。"""
    sectors = _sectors()
    if not sectors:
        return {"leading": [], "lagging": []}
    items = [
        {
            "name": s.get("name", ""),
            "pct": round(_num(s.get("pct")), 2),
            "count": int(_num(s.get("firms"))),
            "net": round(_num(s.get("net")) / 1e8, 2),  # 元 -> 亿
        }
        for s in sectors
        if s.get("name")
    ]
    leading = sorted(items, key=lambda x: x["pct"], reverse=True)[:5]
    lagging = sorted(items, key=lambda x: x["pct"])[:5]
    return {"leading": leading, "lagging": lagging}


def _build() -> dict:
    """同步构建看板数据（market_quotes + 情绪/板块/短线情绪 + 指数）。"""
    rows = _load_market_rows()
    indices = astock.index_quote()
    sentiment = _sentiment()
    emotion = _emotion()

    total = len(rows)
    up = sum(1 for r in rows if r["pct_chg"] > 0)
    down = sum(1 for r in rows if r["pct_chg"] < 0)
    flat = max(0, total - up - down)
    up_pct = up / total * 100 if total else 0
    down_pct = down / total * 100 if total else 0

    pct_values = [r["pct_chg"] for r in rows]
    avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0
    median_pct = sorted(pct_values)[len(pct_values) // 2] if pct_values else 0
    strong_up = sum(1 for v in pct_values if v >= 3.0)
    strong_down = sum(1 for v in pct_values if v <= -3.0)

    amounts = [r["amount"] for r in rows]
    total_amount = sum(amounts)
    avg_amount = total_amount / total if total else 0

    turnovers = [r["turnover_rate"] for r in rows if r["turnover_rate"] is not None]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
    high_turnover = sum(1 for v in turnovers if v >= 5.0)
    high_turnover_pct = high_turnover / total * 100 if total else 0
    # 量能兜底：换手率缺失（如历史回填来源）时，用成交额占比近似资金活跃度，
    # 避免情绪雷达「量能」维度恒为 0。
    high_amount_pct = (sum(1 for r in rows if r["amount"] >= 1e8) / total * 100) if total else 0

    # 涨停/跌停/封板率/最高连板/梯队（短线情绪，失败时降级为空）
    zt_count = int(_num(sentiment.get("zt_real"))) if sentiment else 0
    dt_count = int(_num(sentiment.get("dt_real"))) if sentiment else 0
    seal_rate = emotion.get("seal_rate") if emotion else None
    max_boards = int(_num(emotion.get("max_boards"))) if emotion else 0
    ladder = emotion.get("ladder") or []
    tier2_count = sum(int(t.get("count", 0)) for t in ladder if int(_num(t.get("boards"))) >= 2)

    # 6 维雷达
    index_changes = [float(i.get("change_pct") or 0) for i in indices if i.get("change_pct") is not None]
    avg_index_pct = sum(index_changes) / len(index_changes) if index_changes else 0

    strong_diff_pct = (strong_up - strong_down) / total * 100 if total else 0
    strong_down_pct = strong_down / total * 100 if total else 0

    # 主线 = 行业热度领涨（平均涨幅 + 覆盖度）
    ind_rank = _industry_rank(rows)
    mainline_items = ind_rank["leading"]
    mainline_avg = max([float(i.get("pct") or 0) for i in mainline_items], default=0)
    mainline_score = round(_score(mainline_avg, -0.5, 3.0)) if mainline_items else 50

    radar = [
        {"key": "index", "label": "指数", "value": _score(avg_index_pct, -2.5, 2.5)},
        {"key": "profit", "label": "赚钱", "value": round(
            _score(up_pct, 20, 80) * 0.45
            + _score(avg_pct, -2.0, 2.0) * 0.25
            + _score(median_pct, -2.0, 2.0) * 0.20
            + _score(strong_diff_pct, -8, 8) * 0.10
        )},
        {"key": "money", "label": "量能", "value": round(
            _score(avg_turnover, 0.6, 4.0) * 0.6
            + _score(high_turnover_pct, 2, 15) * 0.4
            if turnovers else
            _score(high_amount_pct, 2, 15)
        )},
        {"key": "speculation", "label": "投机", "value": round(
            _score(zt_count, 5, 90) * 0.25
            + _score(float(seal_rate or 0) * 100, 30, 85) * 0.35
            + _score(max_boards, 1, 8) * 0.25
            + _score(tier2_count, 0, 30) * 0.15
        )},
        {"key": "resilience", "label": "抗跌", "value": 100 - round(
            _score(down_pct, 20, 80) * 0.55
            + _score(strong_down_pct, 1, 12) * 0.45
        )},
        {"key": "mainline", "label": "主线", "value": mainline_score},
    ]
    emotion_score = round(sum(r["value"] for r in radar) / len(radar)) if radar else 50
    if emotion_score >= 70:
        emotion_label = "强势"
    elif emotion_score >= 55:
        emotion_label = "偏暖"
    elif emotion_score >= 45:
        emotion_label = "震荡"
    elif emotion_score >= 30:
        emotion_label = "偏冷"
    else:
        emotion_label = "冰点"

    return {
        "as_of": sentiment.get("date") or "",
        "indices": indices,
        "breadth": {
            "total": total, "up": up, "down": down, "flat": flat,
            "up_pct": round(up_pct, 1), "down_pct": round(down_pct, 1),
            "avg_pct": round(avg_pct, 2), "median_pct": round(median_pct, 2),
            "strong_up": strong_up, "strong_down": strong_down,
        },
        "amount": {"total": round(total_amount, 2), "avg": round(avg_amount, 2)},
        "distribution": _pct_band_rows(pct_values),
        "limit": {
            "limit_up": zt_count, "limit_down": dt_count,
            "seal_rate": seal_rate, "max_boards": max_boards,
            "tiers": ladder,
        },
        "activity": {
            "avg_turnover": round(avg_turnover, 2),
            "high_turnover": high_turnover,
            "high_turnover_pct": round(high_turnover_pct, 1),
        },
        "radar": radar,
        "emotion": {"score": emotion_score, "label": emotion_label},
        "top_gainers": _top_rows(rows, "pct_chg", True),
        "top_losers": _top_rows(rows, "pct_chg", False),
        "turnover_leaders": _top_rows(rows, "amount", True),
        "active_leaders": _top_rows(rows, "turnover_rate", True),
        "industry_rank": ind_rank,
        "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
    }


async def get_dashboard() -> dict:
    """市场看板（Redis 缓存，market 级 TTL）。"""
    return await cached(
        "vibe:market_dashboard", _build,
        category="market",
        valid=lambda v: bool(v.get("breadth", {}).get("total")) or bool(v.get("indices")),
    )