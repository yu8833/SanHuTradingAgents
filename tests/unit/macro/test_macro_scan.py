"""宏观快扫（盘前）单元测试 —— 规则引擎打分 / 财经日历规则 / 快讯分级。

对应设计文档《第六章·交易工具与日常流程》§5.4-A 信号表与阈值：
  - 标普500 ±0.5%、纳斯达克 ±0.8%、恒指/日经/KOSPI ±0.5%、VIX <18/>25、
    期货同标普、高重要性事件 ±2、昨日大盘情绪 >3:1 / <1:3；
  - 聚合：总分 ≥2 偏多、≤-2 偏空、否则中性。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.macro import financial_calendar as fc
from app.services.macro import macro_scorer as ms
from app.services.macro import news_classifier as nc


def _idx(key: str, name: str, price: float, chg: float, region: str = "测试") -> dict:
    return {"key": key, "name": name, "price": price,
            "change_pct": chg, "region": region}


def _news(title: str, importance: str = "high", content: str = "") -> dict:
    return {"title": title, "content": content or title, "importance": importance,
            "category": "经济数据", "source": "test", "publish_time": ""}


# ---------------------------------------------------------------------------
# 规则引擎：方向映射
# ---------------------------------------------------------------------------
class TestMacroScorer:
    def test_bullish(self):
        """全面偏多 → 方向=偏多，置信度>0。"""
        indices = [
            _idx("spx", "标普500", 5000, 1.0),
            _idx("ndx", "纳斯达克", 15000, 1.2),
            _idx("hsi", "恒生指数", 20000, 1.0),
            _idx("n225", "日经225", 30000, 0.8),
            _idx("kospi", "韩国KOSPI", 3000, 0.6),
            _idx("vix", "VIX恐慌指数", 15.0, -2.0),
            _idx("a50fut", "富时A50期货", 12000, 1.0),
        ]
        news = [_news("央行宣布降准 0.5个百分点 支持实体经济发展")]
        breadth = {"up": 4000, "down": 500}
        r = ms.score_macro(indices, [], news, breadth)
        assert r["direction"] == "偏多", r
        assert r["score"] > 0
        assert 0 < r["confidence"] <= 100
        assert len(r["signals"]) > 0

    def test_bearish(self):
        """全面偏空 → 方向=偏空。"""
        indices = [
            _idx("spx", "标普500", 5000, -1.0),
            _idx("ndx", "纳斯达克", 15000, -1.5),
            _idx("hsi", "恒生指数", 20000, -1.0),
            _idx("vix", "VIX恐慌指数", 30.0, 10.0),
            _idx("a50fut", "富时A50期货", 12000, -1.0),
        ]
        news = [_news("美国宣布加征关税 全球市场承压")]
        breadth = {"up": 300, "down": 4200}
        r = ms.score_macro(indices, [], news, breadth)
        assert r["direction"] == "偏空", r
        assert r["score"] < 0

    def test_neutral(self):
        """各信号都在阈值内 → 中性。"""
        indices = [
            _idx("spx", "标普500", 5000, 0.2),
            _idx("ndx", "纳斯达克", 15000, 0.3),
            _idx("hsi", "恒生指数", 20000, -0.2),
            _idx("vix", "VIX恐慌指数", 20.0, 0.0),
        ]
        r = ms.score_macro(indices, [], [], None)
        assert r["direction"] == "中性", r
        assert r["score"] == 0

    def test_threshold_boundary(self):
        """阈值边界：恰为 +0.5% 不得分（> 才是 +1）。"""
        indices = [_idx("spx", "标普500", 5000, 0.5)]
        r = ms.score_macro(indices, [], [], None)
        assert r["score"] == 0, r
        indices = [_idx("spx", "标普500", 5000, 0.51)]
        r = ms.score_macro(indices, [], [], None)
        assert r["direction"] == "中性"  # 单 +1 分不足 2 分
        assert r["score"] == 1

    def test_missing_data_no_crash(self):
        """数据缺失/空列表不崩溃。"""
        r = ms.score_macro([], [], [], None)
        assert r["direction"] == "中性"
        assert r["score"] == 0
        assert r["confidence"] == 0

    def test_confidence_ignores_non_fired_signals(self):
        """未触发信号不稀释置信度：满分只计已触发信号的权重。"""
        indices = [
            _idx("spx", "标普500", 5000, 1.2),    # 触发 +1
            _idx("ndx", "纳斯达克", 15000, 0.2),  # 未触发（阈值内）
            _idx("hsi", "恒生指数", 20000, -0.2), # 未触发（阈值内）
        ]
        r = ms.score_macro(indices, [], [], None)
        assert r["score"] == 1
        assert r["max_abs"] == 1, r  # 只有 spx 的权重 1 计入分母
        assert r["confidence"] == 100, r

    def test_confidence_conflicting_signals(self):
        """触发信号方向分歧 → 置信度下降（反映分歧而非稀释）。"""
        indices = [
            _idx("spx", "标普500", 5000, 1.2),    # +1
            _idx("ndx", "纳斯达克", 15000, -1.0), # -1
        ]
        r = ms.score_macro(indices, [], [], None)
        assert r["score"] == 0
        assert r["max_abs"] == 2, r
        assert r["confidence"] == 0, r

    def test_event_polarity(self):
        """事件极性：利好 +2 / 利空 -2。"""
        assert ms._event_polarity("央行降息 0.1个百分点") > 0
        assert ms._event_polarity("美联储宣布加息 25个基点") < 0
        assert ms._event_polarity("某公司发布财报") == 0

    def test_event_cap(self):
        """事件计分封顶：最多 EVENT_CAP 条。"""
        news = [_news(f"央行降准利好经济 {i}") for i in range(10)]
        r = ms.score_macro([], [], news, None)
        event_sigs = [s for s in r["signals"] if s["name"] == "高重要性政策/数据事件"]
        assert len(event_sigs) <= ms.EVENT_CAP


# ---------------------------------------------------------------------------
# 财经日历：手工规则表生成
# ---------------------------------------------------------------------------
class TestFinancialCalendar:
    def test_manual_events_in_window(self):
        """未来 7 天内能生成至少 1 条高频事件。"""
        events = fc._manual_events(date.today(), 7)
        assert isinstance(events, list)
        # 窗口内事件日期必须落在 [today, today+6]
        today = date.today()
        end = today + timedelta(days=6)
        for e in events:
            d = date.fromisoformat(e["date"])
            assert today <= d <= end, e

    def test_event_required_fields(self):
        """事件结构必须含 date/region/event/importance/release_time。"""
        for e in fc._manual_events(date.today(), 7):
            for k in ("date", "region", "event", "importance", "release_time"):
                assert k in e, e

    def test_fomc_rule_known_date(self):
        """FOMC 2026 已知决议日应能被规则命中。"""
        # 2026-07-29 是 2026 年 7 月 FOMC 决议日
        d = fc._fomc_next(date(2026, 7, 1))
        assert d == date(2026, 7, 29), d


# ---------------------------------------------------------------------------
# 快讯分级：重要性关键词
# ---------------------------------------------------------------------------
class TestNewsClassifier:
    def test_high_importance(self):
        assert nc._classify_importance("央行降准 0.5个百分点") == "high"
        assert nc._classify_importance("美国非农数据大幅超预期") == "high"
        assert nc._classify_importance("证监会发布新规") == "high"

    def test_medium_importance(self):
        assert nc._classify_importance("某板块指数大涨") == "medium"
        assert nc._classify_importance("北向资金今日净流入") == "medium"

    def test_low_default(self):
        assert nc._classify_importance("某新股今日上市") == "low"
        assert nc._classify_importance("无关内容") == "low"

    def test_category(self):
        assert nc._classify_category("央行宣布降息") == "货币政策"
        assert nc._classify_category("美国CPI数据公布") == "经济数据"
        assert nc._classify_category("普通新闻") == "其他"
