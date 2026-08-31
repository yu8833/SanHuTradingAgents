"""规则引擎 macro_scorer —— 宏观快扫方向判断（硬锚点，可控、可回测、可解释）。

设计文档《第六章·交易工具与日常流程》§5.4-A 信号表：

| 信号 | 打分规则 |
|---|---|
| 标普500 | >+0.5% → +1；<-0.5% → -1 |
| 纳斯达克 | >+0.8% → +1；<-0.8% → -1 |
| 恒指 / 日经 / KOSPI | >+0.5% → +1；<-0.5% → -1 |
| VIX | <18 → +1；>25 → -1 |
| 富时A50期货 / 美股期货 | 同标普规则 |
| 高重要性政策/数据事件 | 利好 +2 / 利空 -2 |
| 昨日大盘情绪 | 涨跌家数 >3:1 → +1；<1:3 → -1 |

聚合：总分 ≥2 偏多、≤-2 偏空、否则中性；置信度 = |总分|/满分。
输出：{direction, score, confidence, signals[]}，每条带依据 —— 可解释、可回测。

本模块为纯函数（无 IO），便于单测与回测。
"""

from __future__ import annotations

from typing import Any

# ---- 阈值（可配置；设计文档建议默认值先行，后续按回测调参）----
SPX_HIGH, SPX_LOW = 0.5, -0.5
NDX_HIGH, NDX_LOW = 0.8, -0.8
REGION_HIGH, REGION_LOW = 0.5, -0.5
VIX_RISK_ON, VIX_RISK_OFF = 18.0, 25.0
BREADTH_BULL, BREADTH_BEAR = 3.0, 1 / 3  # 涨跌家数比 >3:1 / <1:3
DIRECTION_BULL, DIRECTION_BEAR = 2, -2
EVENT_WEIGHT = 2     # 高重要性政策/数据事件权重
EVENT_CAP = 2        # 事件计分上限条数（防事件类信号过度加权）
INDEX_WEIGHT = 1

# 事件极性关键词（利好/利空）；命中多者取数量差符号
_BULL_WORDS = (
    "上涨", "利好", "增长", "超预期", "降准", "降息", "宽松", "支持",
    "提振", "回升", "上调", "改善", "突破", "扩表", "增持",
)
_BEAR_WORDS = (
    "下跌", "利空", "下滑", "低于预期", "加息", "收紧", "制裁", "关税",
    "缩减", "下调", "恶化", "风险", "减持", "爆雷", "退市",
)


def _find_index(indices: list[dict], key: str) -> dict | None:
    return next((i for i in indices if i.get("key") == key), None)


def _score_change(v: float, high: float, low: float, name: str, detail: str) -> dict:
    """按涨跌幅阈值打分：>high → +1，<low → -1，否则 0。"""
    if v > high:
        score = INDEX_WEIGHT
    elif v < low:
        score = -INDEX_WEIGHT
    else:
        score = 0
    return {"name": name, "value": v, "score": score,
            "detail": f"{detail} {v:+.2f}%", "weight": INDEX_WEIGHT}


def _event_polarity(title: str) -> int:
    """按关键词判定单条快讯极性：+1 利好 / -1 利空 / 0 中性。"""
    bull = sum(1 for w in _BULL_WORDS if w in title)
    bear = sum(1 for w in _BEAR_WORDS if w in title)
    return 1 if bull > bear else -1 if bear > bull else 0


def _score_events(news: list[dict]) -> tuple[list[dict], int]:
    """高重要性政策/数据事件：利好 +2 / 利空 -2，最多计 EVENT_CAP 条。

    news 入参为分级快讯（含 importance/category）。只取 high 且带明确极性的。
    """
    signals: list[dict] = []
    total = 0
    counted = 0
    for item in news:
        if counted >= EVENT_CAP:
            break
        if item.get("importance") != "high":
            continue
        title = item.get("title") or ""
        polarity = _event_polarity(title)
        if polarity == 0:
            continue
        score = polarity * EVENT_WEIGHT
        total += score
        counted += 1
        signals.append({
            "name": "高重要性政策/数据事件",
            "value": title[:40],
            "score": score,
            "detail": f"{'利好' if polarity > 0 else '利空'}：{title[:50]}",
            "weight": EVENT_WEIGHT,
        })
    return signals, total


def score_macro(indices: list[dict], calendar: list[dict],
                news: list[dict], breadth: dict | None = None) -> dict:
    """宏观方向评分。

    Args:
        indices: 外围指数列表 [{key, name, price, change_pct, region}]
        calendar: 财经日历 [{date, region, event, importance, forecast, previous, release_time}]
        news: 分级快讯 [{title, content, importance, category, ...}]
        breadth: 昨日大盘情绪 {up, down}（涨跌家数），可为 None
    """
    signals: list[dict] = []
    total = 0
    max_abs = 0  # 可用信号的满分绝对值之和（用于置信度）

    def _add(sig: dict, contrib: int):
        nonlocal total, max_abs
        signals.append(sig)
        total += contrib
        max_abs += abs(sig["weight"])

    # 1. 标普500
    spx = _find_index(indices, "spx")
    if spx and spx.get("change_pct") is not None:
        _add(_score_change(spx["change_pct"], SPX_HIGH, SPX_LOW, "标普500",
                           "隔夜标普500涨跌幅"), spx["change_pct"] > SPX_HIGH and 1 or (spx["change_pct"] < SPX_LOW and -1 or 0))

    # 2. 纳斯达克（阈值 ±0.8%）
    ndx = _find_index(indices, "ndx")
    if ndx and ndx.get("change_pct") is not None:
        _add(_score_change(ndx["change_pct"], NDX_HIGH, NDX_LOW, "纳斯达克",
                           "隔夜纳斯达克涨跌幅"), ndx["change_pct"] > NDX_HIGH and 1 or (ndx["change_pct"] < NDX_LOW and -1 or 0))

    # 3. 恒指 / 日经 / KOSPI（阈值 ±0.5%）
    for key, name in (("hsi", "恒生指数"), ("n225", "日经225"), ("kospi", "韩国KOSPI")):
        idx = _find_index(indices, key)
        if idx and idx.get("change_pct") is not None:
            sig = _score_change(idx["change_pct"], REGION_HIGH, REGION_LOW, name,
                                f"{name}涨跌幅")
            _add(sig, sig["score"])

    # 4. VIX（<18 → +1；>25 → -1）
    vix = _find_index(indices, "vix")
    if vix and vix.get("price") is not None:
        v = vix["price"]
        if v < VIX_RISK_ON:
            score = INDEX_WEIGHT
        elif v > VIX_RISK_OFF:
            score = -INDEX_WEIGHT
        else:
            score = 0
        _add({"name": "VIX恐慌指数", "value": v, "score": score,
              "detail": f"VIX={v:.1f}（<{VIX_RISK_ON:.0f} 风险偏好 / >{VIX_RISK_OFF:.0f} 恐慌）",
              "weight": INDEX_WEIGHT}, score)

    # 5. 富时A50期货 / 美股期货（同标普 ±0.5%）
    for key, name in (("a50fut", "富时A50期货"), ("spxfut", "标普500期货"),
                      ("ndxfut", "纳斯达克期货"), ("djifut", "道指期货")):
        idx = _find_index(indices, key)
        if idx and idx.get("change_pct") is not None:
            sig = _score_change(idx["change_pct"], REGION_HIGH, REGION_LOW, name,
                                f"{name}涨跌幅")
            _add(sig, sig["score"])

    # 6. 高重要性政策/数据事件（利好 +2 / 利空 -2，封顶 EVENT_CAP 条）
    ev_signals, ev_total = _score_events(news)
    signals.extend(ev_signals)
    total += ev_total
    max_abs += EVENT_WEIGHT * min(len(ev_signals), EVENT_CAP)

    # 7. 昨日大盘情绪（涨跌家数 >3:1 → +1；<1:3 → -1）
    if breadth and breadth.get("up") is not None and breadth.get("down") is not None:
        up, down = breadth["up"], breadth["down"]
        ratio = up / down if down else (BREADTH_BULL if up else 0)
        if ratio > BREADTH_BULL:
            score = INDEX_WEIGHT
        elif ratio < BREADTH_BEAR:
            score = -INDEX_WEIGHT
        else:
            score = 0
        _add({"name": "昨日大盘情绪", "value": f"{up}:{down}", "score": score,
              "detail": f"涨跌家数 {up}/{down}（>3:1 偏多 / <1:3 偏空）",
              "weight": INDEX_WEIGHT}, score)

    # 聚合
    if total >= DIRECTION_BULL:
        direction = "偏多"
    elif total <= DIRECTION_BEAR:
        direction = "偏空"
    else:
        direction = "中性"
    confidence = round(abs(total) / max_abs * 100) if max_abs else 0

    return {
        "direction": direction,
        "score": total,
        "confidence": confidence,
        "signals": signals,
        "max_abs": max_abs,
    }
