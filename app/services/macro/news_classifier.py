"""快讯分级（宏观快扫数据层 C 提供方）—— 复用财联社 + 东财 7x24 文字流 + 重要性分级规则。

设计文档《第六章·交易工具与日常流程》§5.3-C：
  - 复用 tradingagents/dataflows/news/realtime_news.py 的财联社 + 东财 7x24 文字流；
  - 新增重要性分级规则（关键词表）：货币政策（降准/降息/LPR/MLF/美联储）、财政（国常会/专项债）、
    数据（CPI/PPI/PMI/社融/非农）、地缘（关税/制裁）、监管（证监会/IPO/解禁）→ 高/中/低；
  - 过去 12-24h 窗口 + 去重 + 截断 top N。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# 重要性关键词表：高 / 中 / 低。命中优先级从高到低。
_HIGH_KEYWORDS = (
    # 货币政策
    "降准", "降息", "LPR", "MLF", "美联储", "加息", "利率决议", "联邦基金",
    # 财政
    "国常会", "专项债", "财政政策", "特别国债", "万亿",
    # 数据
    "CPI", "PPI", "PMI", "社融", "M2", "非农", "失业率", "GDP", "进出口",
    # 地缘
    "关税", "制裁", "贸易战", "地缘",
    # 监管
    "证监会", "IPO", "解禁", "退市", "印花税",
    # 市场级
    "降准降息", "央行", "政策", "国务院", "中央经济工作会议", "政治局会议",
)

_MEDIUM_KEYWORDS = (
    "财报", "业绩", "涨停", "跌停", "回购", "增持", "减持", "重组", "并购",
    "指数", "大盘", "板块", "沪指", "深成指", "创业板", "北向资金", "主力资金",
    "通胀", "就业", "制造业", "零售", "工业增加值", "固定资产投资",
)

_LOW_KEYWORDS = (
    "新股", "中签", "分红", "送转", "解禁股", "公告", "停牌", "复牌",
)

# 主题分类关键词表（供 LLM / 前端标签）
_CATEGORY_KEYWORDS = {
    "货币政策": ("降准", "降息", "LPR", "MLF", "央行", "美联储", "加息", "利率"),
    "财政政策": ("国常会", "专项债", "特别国债", "财政", "万亿", "减税"),
    "经济数据": ("CPI", "PPI", "PMI", "社融", "M2", "非农", "GDP", "失业率", "通胀", "制造业"),
    "地缘风险": ("关税", "制裁", "贸易战", "地缘", "战争", "冲突"),
    "市场监管": ("证监会", "IPO", "解禁", "退市", "印花税", "监管", "交易所"),
    "市场行情": ("指数", "大盘", "板块", "涨停", "跌停", "北向资金", "沪指", "创业板"),
}


def _classify_importance(title: str) -> str:
    """重要性分级：高 > 中 > 低。"""
    for kw in _HIGH_KEYWORDS:
        if kw in title:
            return "high"
    for kw in _MEDIUM_KEYWORDS:
        if kw in title:
            return "medium"
    for kw in _LOW_KEYWORDS:
        if kw in title:
            return "low"
    return "low"


def _classify_category(title: str) -> str:
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in title for kw in kws):
            return cat
    return "其他"


def classify_news_item(item: dict) -> dict:
    """对单条快讯打重要性 + 主题标签。入参为统一结构 {title, content, source, publish_time}。"""
    title = str(item.get("title") or "") or str(item.get("content") or "")[:60]
    return {
        **item,
        "importance": _classify_importance(title),
        "category": _classify_category(title),
    }


def _fetch_macro_news(hours_back: int = 24, top_n: int = 40) -> list[dict]:
    """抓取市场级快讯（财联社 + 东财 7x24），分级 + 时间窗口 + 去重 + 截断。

    优先保留高重要性条目；时间窗口内不足时放宽到更多小时。返回统一结构：
    {title, content, source, publish_time, importance, category}。
    """
    try:
        from tradingagents.dataflows.news.realtime_news import RealtimeNewsAggregator
        agg = RealtimeNewsAggregator()
        items = agg.get_realtime_stock_news(symbol=None, hours_back=hours_back, max_news=60)
    except Exception as e:
        logger.warning(f"实时快讯获取失败: {e}")
        return []

    now = datetime.now()
    cutoff = now - timedelta(hours=hours_back)
    rows: list[dict] = []
    for n in items:
        pub = n.publish_time
        # 无时间戳者保留（无法判断窗口）；有时间戳者过滤出窗口内
        if pub is not None and pub < cutoff:
            continue
        rows.append({
            "title": n.title,
            "content": (n.content or "")[:200],
            "source": n.source,
            "publish_time": pub.isoformat() if pub else "",
            "url": getattr(n, "url", "") or "",
        })

    # 去重（按标题）
    seen: set[str] = set()
    unique: list[dict] = []
    for r in rows:
        key = r["title"].strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(r)

    # 分级（高优先排在前面），再按时间倒序
    for r in unique:
        r.update({"importance": _classify_importance(r["title"]),
                  "category": _classify_category(r["title"])})

    def _ts(r: dict) -> float:
        try:
            return datetime.fromisoformat(r["publish_time"]).timestamp() if r["publish_time"] else 0.0
        except ValueError:
            return 0.0

    unique.sort(key=lambda r: (
        0 if r["importance"] == "high" else 1 if r["importance"] == "medium" else 2,
        -_ts(r),
    ))
    return unique[:top_n]


async def get_macro_news(hours_back: int = 24, top_n: int = 40) -> list[dict]:
    """分级快讯（缓存 5min/1h）。"""
    return await cached(
        f"macro:news:{hours_back}:{top_n}",
        lambda: _fetch_macro_news(hours_back, top_n),
        category="news",
        valid=bool,
    )
