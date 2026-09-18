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

聚合：总分 ≥2 偏多、≤-2 偏空、否则中性；
置信度 = |总分|/满分，其中满分 = 已触发信号的权重绝对值之和（衡量触发信号间的方向一致度；
未触发（score=0）的信号不计入分母，避免大量中性信号结构性稀释置信度，使低置信度反映"信号平淡/分歧"而非"信号太少"）。
输出：{direction, score, confidence, signals[]}，每条带依据 —— 可解释、可回测。

本模块为纯函数（无 IO），便于单测与回测。
"""

from __future__ import annotations

import math
from typing import Any

# ---- 阈值（可配置；设计文档建议默认值先行，后续按回测调参）----
SPX_HIGH, SPX_LOW = 0.5, -0.5
NDX_HIGH, NDX_LOW = 0.8, -0.8
REGION_HIGH, REGION_LOW = 0.5, -0.5
VIX_RISK_ON, VIX_RISK_OFF = 18.0, 25.0
BREADTH_BULL, BREADTH_BEAR = 3.0, 1 / 3  # 涨跌家数比 >3:1 / <1:3
DIRECTION_BULL, DIRECTION_BEAR = 2, -2
EVENT_WEIGHT = 2     # 高重要性政策/数据事件权重
EVENT_CAP = 10       # 事件计分上限条数。高于前端"重要事件"默认展示数（5），
                     # 保证所有 |影响度|≥50 的强影响事件都能计入总分，事件卡不出现"未计入 —"
                     # 已按 |impact_score| 过滤且每条权重 ±2，条数上限只作兜底防极端堆积。
INDEX_WEIGHT = 1

# B 档：事件"概率×幅度"分级用的弱证据词（与 news_classifier._HEDGE_WORDS 语义对齐）。
# 命中任一 → 事件为"预期/传闻"类（未落地），影响概率打折；
# 未命中 → 视为"已落地事实/正式表态"，影响概率较高。
_EVENT_HEDGE_WORDS = ("否认", "辟谣", "澄清", "传闻", "考虑", "据悉", "拟", "据称", "或将", "或考虑")

# 事件类型 → 影响概率（确定性公式，不引入 LLM 主观）：
#   fact(已落地/正式) 0.8 — 正式数据/政策/声明，方向大概率兑现
#   expectation(预期/传闻) 0.5 — 尚未落地，兑现概率对半
# 叠加 |impact| 调节：影响度>80 权重上调 0.05，<60 下调 0.10，边界截断在 [0.3, 0.9]。
_EVENT_PROB_FACT = 0.80
_EVENT_PROB_EXPECT = 0.50
_EVENT_PROB_MIN, _EVENT_PROB_MAX = 0.30, 0.90

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


def _sanitize_indices(indices: list[dict]) -> list[dict]:
    """清洗外围指数：非有限数值（NaN/Infinity）置 None。

    数据源偶发 NaN（停牌/源异常）会让评分引擎输出 NaN 信号并污染快照，
    进而导致 JSON 序列化 500；这里统一转为 None，由下游 `is not None`
    检查自然跳过该信号。
    """
    out = []
    for it in indices:
        it = dict(it)
        for k in ("price", "change_pct"):
            v = it.get(k)
            if isinstance(v, float) and not math.isfinite(v):
                it[k] = None
        out.append(it)
    return out


def _score_change(v: float, high: float, low: float, name: str, detail: str) -> dict:
    """按涨跌幅阈值打分：>high → +1，<low → -1，否则 0。

    detail 写明"当前值 + 触发规则 + 判定 + 对方向的贡献"，让悬浮可读清如何影响方向。
    """
    if v > high:
        score = INDEX_WEIGHT
        judge = f">{high:+.1f}% 处偏多 → 利多，贡献 {INDEX_WEIGHT:+d}"
    elif v < low:
        score = -INDEX_WEIGHT
        judge = f"<{low:+.1f}% 处偏空 → 利空，贡献 {score:+d}"
    else:
        score = 0
        judge = f"介于 {low:+.1f}%~{high:+.1f}% 波动 → 中性，贡献 0"
    return {"name": name, "value": v, "score": score,
            "detail": f"{detail} {v:+.2f}%；{judge}", "weight": INDEX_WEIGHT}


def _event_polarity(title: str) -> int:
    """按关键词判定单条快讯极性：+1 利好 / -1 利空 / 0 中性。"""
    bull = sum(1 for w in _BULL_WORDS if w in title)
    bear = sum(1 for w in _BEAR_WORDS if w in title)
    return 1 if bull > bear else -1 if bear > bull else 0


# ── 事件主题去重：同一主题（主体/动作一致）只计入最强一条，避免"美联储加息"4条×-3 重复加权带崩方向 ──
_TOPIC_ENTITIES = (
    "美联储", "日本央行", "欧洲央行", "中国人民银行", "央行", "证监会", "交易所",
    "国务院", "国常会", "特朗普", "OpenAI", "苹果", "华为", "英伟达", "财政部", "发改委",
)
_TOPIC_ACTIONS = (
    "加息", "降息", "降准", "LPR", "MLF", "融资", "IPO", "收购", "并购",
    "制裁", "关税", "解禁", "回购", "增持", "减持", "违约", "破产", "裁员",
    "重组", "万亿", "特别国债", "涨停", "退市",
)


def _event_topic(title: str) -> str | None:
    """事件主题键：**动作词优先**（加息/降准/IPO…，同动作话题统一去重，避免"鸽派加息"与"美联储加息"
    被拆成两个主题）；标题无动作词时才用主体（美联储/证监会…）。无命中返回 None。"""
    for act in _TOPIC_ACTIONS:
        if act in title:
            return "动作:" + act
    for ent in _TOPIC_ENTITIES:
        if ent in title:
            return "主体:" + ent
    return None


def _event_probability(polarity: int, impact: float, title: str) -> tuple[str, float]:
    """事件类型判定 + 影响概率（确定性公式）。

    - 命中弱证据词（拟/考虑/传闻/据悉/或将…）→ 'expectation' 预期类，方向存疑、概率打折；
    - 否则 → 'fact' 已落地/正式表态类，方向可信度较高。
    - 概率 = 基值 + |影响度| 微调，边界截断在 [0.3, 0.9]。
    """
    hedged = any(w in title for w in _EVENT_HEDGE_WORDS)
    base = _EVENT_PROB_EXPECT if hedged else _EVENT_PROB_FACT
    adj = 0.05 if impact >= 80 else (-0.10 if impact < 60 else 0.0)
    prob = max(_EVENT_PROB_MIN, min(_EVENT_PROB_MAX, base + adj))
    return ("expectation" if hedged else "fact"), round(prob, 2)


def _score_events(news: list[dict]) -> tuple[list[dict], int]:
    """高重要性政策/数据事件：利多 +2（影响度≥80 为 +3）/ 利空对称，最多计 EVENT_CAP 条。

    news 入参为分级快讯（含 importance/category + v5 impact_score/direction）。
    只计入 |impact_score| ≥ 50 的强影响事件；**同主题事件（如多条"美联储加息"）
    按主题去重，只取影响度最强的一条**，避免同事件重复加权扭曲大盘方向；
    无打分字段（历史缓存/直接构造入参）时回退本地词表 _event_polarity。
    """
    # 1) 收集候选（high importance + 强影响）
    cands: list[dict] = []
    for item in news:
        if item.get("importance") != "high":
            continue
        title = item.get("title") or ""
        v5 = item.get("impact_score")
        if v5 is not None:
            v5 = float(v5)
            if abs(v5) < 50:   # 弱影响事件不计入大盘，也不进"重要事件"列表
                continue
            polarity = 1 if v5 > 0 else -1
            contrib = 2 + (1 if abs(v5) >= 80 else 0)   # |影响度|≥80 重大 ±3 / 50~79 ±2
            impact = abs(v5)
        else:
            polarity = _event_polarity(title)
            if polarity == 0:
                continue
            contrib = EVENT_WEIGHT
            impact = 50.0
            v5 = None
        cands.append({
            "item": item, "title": title, "polarity": polarity, "contrib": contrib,
            "impact": impact, "v5": v5, "topic": _event_topic(title),
        })

    # 2) 同主题去重：保留影响度最强一条；无主题词的各自保留
    keep: list[dict] = []
    best: dict[str, dict] = {}
    for c in cands:
        tp = c["topic"]
        if tp is None:
            keep.append(c)
            continue
        ex = best.get(tp)
        if ex is None or c["impact"] > ex["impact"]:
            best[tp] = c
    selected = keep + list(best.values())

    # 3) 按影响度降序取前 EVENT_CAP 条
    selected.sort(key=lambda c: c["impact"], reverse=True)
    selected = selected[:EVENT_CAP]

    # 4) 生成信号
    signals: list[dict] = []
    total = 0
    for c in selected:
        score = c["polarity"] * c["contrib"]
        total += score
        # B 档：事件"概率×幅度"分级（事实/预期 + 影响概率 + 解读/板块透传）
        event_type, prob = _event_probability(c["polarity"], c["impact"], c["title"] or "")
        item = c["item"]
        signals.append({
            "name": "高重要性政策/数据事件",
            "value": c["title"][:40],
            "score": score,
            "detail": f"{'利好' if c['polarity'] > 0 else '利空'}（贡献 {score:+d}"
                      f"{' · 影响度 ' + ('+' if c['polarity'] > 0 else '') + str(int(c['impact'])) if c['v5'] is not None else ''}）：{c['title'][:40]}",
            "weight": c["contrib"],
            "title": c["title"],
            "url": c["item"].get("url") or "",
            "impact_score": c["v5"],
            "event_type": event_type,          # fact=已落地 / expectation=预期/传闻
            "probability": prob,               # 影响兑现概率（确定性公式）
            "analysis": item.get("analysis") or "",
            "related_sectors": item.get("related_sectors") or [],
        })
    return signals, total


def score_macro(indices: list[dict], calendar: list[dict],
                news: list[dict], breadth: dict | None = None,
                a_share: dict | None = None) -> dict:
    """宏观方向评分。

    Args:
        indices: 外围指数列表 [{key, name, price, change_pct, region}]
        calendar: 财经日历 [{date, region, event, importance, forecast, previous, release_time}]
        news: 分级快讯 [{title, content, importance, category, ...}]
        breadth: 昨日大盘情绪 {up, down}（涨跌家数），可为 None
        a_share: A股自身技术面 {close, ma20, ma60, amount, amount_avg5}，可为 None
    """
    indices = _sanitize_indices(indices or [])
    signals: list[dict] = []
    total = 0
    max_abs = 0  # 已触发信号的满分绝对值之和（用于置信度）

    def _add(sig: dict, contrib: int):
        nonlocal total, max_abs
        signals.append(sig)
        total += contrib
        if contrib != 0:
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
            judge = f"低于 {VIX_RISK_ON:.0f} 风险偏好 → 利多"
        elif v > VIX_RISK_OFF:
            score = -INDEX_WEIGHT
            judge = f"高于 {VIX_RISK_OFF:.0f} 恐慌 → 利空"
        else:
            score = 0
            judge = f"介于 {VIX_RISK_ON:.0f}~{VIX_RISK_OFF:.0f} 波动 → 中性"
        _add({"name": "VIX恐慌指数", "value": v, "score": score,
              "detail": f"VIX={v:.1f}（{judge}，贡献 {score:+d}）",
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
            judge = f"涨跌比 {ratio:.1f}:1 超 3:1 普涨 → 利多"
        elif ratio < BREADTH_BEAR:
            score = -INDEX_WEIGHT
            judge = f"涨跌比 {ratio:.2f}:1 破 1:3 普跌 → 利空"
        else:
            score = 0
            judge = "涨跌比接近均衡 → 中性"
        _add({"name": "昨日大盘情绪", "value": f"{up}:{down}", "score": score,
              "detail": f"涨跌家数 {up}/{down}（{judge}，贡献 {score:+d}）",
              "weight": INDEX_WEIGHT}, score)

    # 8. A股自身技术面（业界主导信号，外围只作辅助）：上证指数 vs 均线 + 量能
    #    a_share = {close, ma20, ma60, amount, amount_avg5}，任一缺失则跳过对应信号
    if a_share:
        ax = a_share.get
        close = ax("close")
        ma20 = ax("ma20")
        ma60 = ax("ma60")
        if close is not None and ma20:
            if close >= ma20:
                _add({"name": "上证指数·20日线", "value": close, "score": INDEX_WEIGHT,
                      "detail": f"上证 {close} 站上 20 日线 {ma20:.0f} → 短期偏多，贡献 +{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, INDEX_WEIGHT)
            else:
                _add({"name": "上证指数·20日线", "value": close, "score": -INDEX_WEIGHT,
                      "detail": f"上证 {close} 跌破 20 日线 {ma20:.0f} → 短期偏空，贡献 -{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, -INDEX_WEIGHT)
        if ma20 and ma60:
            if ma20 >= ma60:
                _add({"name": "上证指数·中期趋势", "value": f"MA20 {ma20:.0f}",
                      "score": INDEX_WEIGHT,
                      "detail": f"MA20 {ma20:.0f} ≥ MA60 {ma60:.0f} 多头排列 → 中期偏多，贡献 +{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, INDEX_WEIGHT)
            else:
                _add({"name": "上证指数·中期趋势", "value": f"MA20 {ma20:.0f}",
                      "score": -INDEX_WEIGHT,
                      "detail": f"MA20 {ma20:.0f} < MA60 {ma60:.0f} 空头排列 → 中期偏空，贡献 -{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, -INDEX_WEIGHT)
        amount = ax("amount")
        amount_avg5 = ax("amount_avg5")
        if amount and amount_avg5:
            if amount >= amount_avg5 * 1.05:
                _add({"name": "两市量能", "value": round(amount, 0), "score": INDEX_WEIGHT,
                      "detail": f"成交额 {amount/1e8:.0f}亿 ≥ 5日均量 {amount_avg5/1e8:.0f}亿×1.05 放量 → 量在价先，贡献 +{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, INDEX_WEIGHT)
            elif amount <= amount_avg5 * 0.95:
                _add({"name": "两市量能", "value": round(amount, 0), "score": -INDEX_WEIGHT,
                      "detail": f"成交额 {amount/1e8:.0f}亿 ≤ 5日均量 {amount_avg5/1e8:.0f}亿×0.95 缩量 → 观望，贡献 -{INDEX_WEIGHT}",
                      "weight": INDEX_WEIGHT}, -INDEX_WEIGHT)

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
