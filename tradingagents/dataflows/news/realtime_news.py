"""实时新闻聚合: 从东方财富/新浪(个股)与财联社/东方财富快讯(市场)实时抓取。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from tradingagents.dataflows.a_stock import (
    _em_get,
    _fetch_news_eastmoney,
    _fetch_news_sina,
    _normalize_ticker,
)

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


@dataclass
class NewsItem:
    """实时新闻条目"""
    title: str
    content: str
    url: str
    source: str
    publish_time: datetime | None


def _parse_time(time_val) -> datetime | None:
    """解析发布时间，支持多种格式"""
    if not time_val:
        return None
    text = str(time_val).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fetch_market_news(limit: int = 50) -> list[NewsItem]:
    """抓取财联社 + 东方财富 7x24 快讯（市场级实时新闻）"""
    items: list[NewsItem] = []

    try:
        cls_url = "https://www.cls.cn/nodeapi/telegraphList"
        cls_params = {"rn": str(limit), "page": "1"}
        r_cls = requests.get(
            cls_url, params=cls_params, headers={"User-Agent": _UA, "Referer": "https://www.cls.cn/"}, timeout=10
        )
        for item in r_cls.json().get("data", {}).get("roll_data", []):
            title = item.get("title", "") or item.get("brief", "")
            content = item.get("content", "") or item.get("brief", "")
            pub_time = None
            ctime = item.get("ctime", "")
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime))
                except (ValueError, TypeError, OSError):
                    pub_time = None
            items.append(NewsItem(
                title=title, content=content,
                url=f"https://www.cls.cn/detail/{item.get('id', '')}" if item.get("id") else "",
                source="财联社", publish_time=pub_time
            ))
    except Exception as e:
        logger.warning("财联社实时新闻获取失败: %s", e)

    try:
        em_url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        em_params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(limit),
            "req_trace": str(uuid.uuid4()),
        }
        r_em = _em_get(em_url, params=em_params, headers={"User-Agent": _UA, "Referer": "https://kuaixun.eastmoney.com/"}, timeout=10)
        for item in r_em.json().get("data", {}).get("fastNewsList", []):
            code = str(item.get("code", "") or "")
            items.append(NewsItem(
                title=item.get("title", ""),
                content=str(item.get("summary", "") or "")[:300],
                url=str(item.get("infoUrl", "") or "") or (
                    f"http://wap.eastmoney.com/3g/news/article,8,365,1,{code}.shtml" if code else ""
                ),
                source="东财快讯",
                publish_time=_parse_time(item.get("showTime")),
            ))
    except Exception as e:
        logger.warning("东财快讯获取失败: %s", e)

    return items


def _to_news_items(articles: list[dict], fallback_source: str) -> list[NewsItem]:
    """将东财/新浪返回的 dict 列表转换为 NewsItem"""
    items: list[NewsItem] = []
    for art in articles:
        items.append(NewsItem(
            title=art.get("title", ""),
            content=art.get("content", ""),
            url=art.get("url", ""),
            source=art.get("source", fallback_source),
            publish_time=_parse_time(art.get("time")),
        ))
    return items


class RealtimeNewsAggregator:
    """实时新闻聚合器：个股新闻（东财+新浪）与市场新闻（财联社+东财快讯）"""

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)

    def get_news(self, *args, **kwargs):
        """兼容旧占位接口，返回空列表"""
        return []

    def get_realtime_stock_news(
        self,
        symbol: str | None,
        hours_back: int = 6,
        max_news: int = 20,
    ) -> list[NewsItem]:
        """获取实时(股票/市场)新闻

        Args:
            symbol: 个股代码；为 None 时抓取市场级新闻（财联社 + 东财快讯）
            hours_back: 回溯小时数
            max_news: 最大条数
        """
        items: list[NewsItem] = []
        try:
            if not symbol:
                items = _fetch_market_news(limit=max_news)
            else:
                try:
                    articles = _fetch_news_eastmoney(_normalize_ticker(symbol), page_size=max_news)
                    items = _to_news_items(articles, "东方财富")
                except Exception as e:
                    self.logger.warning("东财个股新闻获取失败 %s: %s", symbol, e)
                    items = []
                if not items:
                    try:
                        articles = _fetch_news_sina(symbol, page_size=max_news)
                        items = _to_news_items(articles, "新浪财经")
                    except Exception as e:
                        self.logger.warning("新浪个股新闻获取失败 %s: %s", symbol, e)
        except Exception as e:
            self.logger.error("获取实时新闻失败: %s", e)
            return []

        # 按回溯时间过滤
        if hours_back:
            cutoff = datetime.now() - timedelta(hours=hours_back)
            filtered = [n for n in items if n.publish_time is None or n.publish_time >= cutoff]
            items = filtered

        # 去重 + 按时间倒序 + 截断
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for n in items:
            key = n.url if n.url else n.title
            if key not in seen:
                seen.add(key)
                unique.append(n)
        unique.sort(key=lambda x: x.publish_time or datetime.min, reverse=True)
        return unique[:max_news]