"""快讯分级（宏观快扫数据层 C 提供方）—— 复用财联社 + 东财 7x24 文字流 + 重要性分级规则。

设计文档《第六章·交易工具与日常流程》§5.3-C：
  - 复用 tradingagents/dataflows/news/realtime_news.py 的财联社 + 东财 7x24 文字流；
  - 新增重要性分级规则（关键词表）：货币政策（降准/降息/LPR/MLF/美联储）、财政（国常会/专项债）、
    数据（CPI/PPI/PMI/社融/非农）、地缘（关税/制裁）、监管（证监会/IPO/解禁）→ 高/中/低；
  - 过去 12-24h 窗口 + 去重 + 截断 top N。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# 个股新闻判定：标题含 6 位股票代码（如 "山东矿机(002526) 涨停"）
_STOCK_CODE_RE = re.compile(r"\b\d{6}\b")

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
# 全局宏观豁免词（用于区分"个股新闻"与"宏观级快讯"——仅当标题命中这些真正
# 的全局词时才不作为个股新闻压制；"证监会/政策/国务院"等机构词常伴随个股公告，
# 不纳入豁免，避免"金富科技…证监会批复"这类个股新闻被豁免）
_GLOBAL_KEYWORDS = (
    "降准", "降息", "LPR", "MLF", "央行", "美联储", "加息", "利率决议",
    "非农", "失业率", "CPI", "PPI", "PMI", "社融", "GDP",
    "关税", "制裁", "贸易战", "国常会", "政治局", "中央经济工作会议", "印花税",
)
# 个股动作关键词（标题命中即倾向个股新闻，除非同时命中全局宏观词）
_STOCK_ACTION_KW = re.compile(
    r"涨停|跌停|连板|中签|回购|增持|减持|定增|配股|可转债|批复|中标|签订|签署|"
    r"业绩预告|预增|预减|扭亏|获准|停牌|复牌|\d+板"
)


def _is_stock_news(title: str) -> bool:
    """个股新闻识别：含 6 位股票代码，或命中个股动作词（涨停/增持/批复…）且不含全局宏观词。"""
    if _STOCK_CODE_RE.search(title):
        return True
    if _STOCK_ACTION_KW.search(title) and not any(k in title for k in _GLOBAL_KEYWORDS):
        return True
    return False

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
    """抓取多源市场级快讯（财联社 + 东财 7x24 文字流 + 资讯雷达 108 个公开 RSS），
    分级 + 时间窗口 + 去重 + 截断。

    数据源：
      1) RealtimeNewsAggregator（tradingagents core：财联社 + 东财 7x24 文字流）；
      2) newsradar（app/services/newsradar：12 赛道 108 个公开 RSS 源，与"资讯雷达"页同源）；
    个股新闻压制：标题含 6 位股票代码、且未命中全局高重要性关键词（降准/加息/关税等）的
    个股公告/异动类新闻最高降为 low，避免"XX 涨停"被误标为高/中混入"重要快讯"。

    返回统一结构：{title, content, source, publish_time, importance, category}。
    """
    rows: list[dict] = []

    # 数据源 1：财联社 + 东财 7x24 文字流
    try:
        from tradingagents.dataflows.news.realtime_news import RealtimeNewsAggregator
        agg = RealtimeNewsAggregator()
        items = agg.get_realtime_stock_news(symbol=None, hours_back=hours_back, max_news=60)
        for n in items:
            pub = n.publish_time
            # 无时间戳者保留（无法判断窗口）；有时间戳者过滤出窗口内
            if pub is not None and pub < datetime.now() - timedelta(hours=hours_back):
                continue
            rows.append({
                "title": n.title,
                "content": (n.content or "")[:200],
                "source": n.source,
                "publish_time": pub.isoformat() if pub else "",
                "url": getattr(n, "url", "") or "",
            })
    except Exception as e:
        logger.warning(f"实时快讯（财联社/东财）获取失败: {e}")

    # 数据源 2：资讯雷达（108 个公开 RSS 源，与资讯雷达页同源）。
    # 同步抓取（与财联社源一致，频率低：宏观快照 8:15/手动刷新时执行一次）。
    radar_data = None
    try:
        from app.services.newsradar import fetch_radar
        radar_data = fetch_radar()
    except Exception as e:
        logger.warning(f"资讯雷达源不可用: {e}")

    if radar_data:
        cnt = 0
        for ind in radar_data.get("industries") or []:
            for it in ind.get("items") or []:
                title = str(it.get("title") or "").strip()
                if not title:
                    continue
                ts = it.get("ts") or 0
                rows.append({
                    "title": title,
                    "content": str(it.get("summary") or "")[:200],
                    "source": f"资讯雷达·{it.get('source') or ind.get('name') or 'RSS'}",
                    "publish_time": datetime.fromtimestamp(int(ts)).isoformat() if ts else "",
                    "url": it.get("url") or "",
                })
                cnt += 1
        if cnt:
            logger.info(f"资讯雷达并入 {cnt} 条快讯（多源）")

    unique: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        key = r["title"].strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(r)

    # 分级（高优先排在前面），再按时间倒序；个股新闻压制
    for r in unique:
        r.update({"importance": _classify_importance(r["title"]),
                  "category": _classify_category(r["title"])})
        if _is_stock_news(r["title"]):
            r["importance"] = "low"   # 个股异动/公告类：不构成"重要"级
            r["category"] = "个股"

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
    """分级快讯（缓存 5min/1h）。v2：多源合并（财联社/东财 + 资讯雷达）+ 个股压制。"""
    return await cached(
        f"macro:news:v3:{hours_back}:{top_n}",
        lambda: _fetch_macro_news(hours_back, top_n),
        category="news",
        valid=bool,
    )
