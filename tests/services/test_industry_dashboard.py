"""
大盘看板 · 行业板块扩展 单元测试。

覆盖:
1. 行业多周期资金流(_build_period_flows):阶段涨跌幅字符串解析、金额归一 元、按净额降序、四周期齐全;
2. 热力图 sectors 新字段(_sectors):行业指数/领涨股/领涨股涨跌幅/当前价 正确透传,原字段不变;
3. 行业 AI 分析(analyze_industry)规则路径:强数据→正分、弱数据→负分、未命中→found=False;
4. LLM 路径与失败降级。

统一 monkeypatch _llm_cfg 避免真实网络/LLM 调用。
"""
import pandas as pd
import pytest

pytestmark = [pytest.mark.unit]

_FAKE_CFG = {"model": "deepseek-v4-flash", "api_base": "https://api.deepseek.com",
             "api_key": "fake", "temperature": 0.3}


def _immediate_df() -> pd.DataFrame:
    """即时档 DataFrame(90 行业mock 2 行)。"""
    return pd.DataFrame([
        {"序号": 1, "行业": "银行", "行业指数": 4342.38, "行业-涨跌幅": "0.30%",
         "流入资金": "95.11亿", "流出资金": "79.05亿", "净额": "16.06亿",
         "公司家数": 84, "领涨股": "招商银行", "领涨股-涨跌幅": "4.20%", "当前价": 35.54},
        {"序号": 2, "行业": "证券", "行业指数": 4100.0, "行业-涨跌幅": "-1.20%",
         "流入资金": "40.0亿", "流出资金": "50.0亿", "净额": "-10.0亿",
         "公司家数": 50, "领涨股": "东方财富", "领涨股-涨跌幅": "-3.00%", "当前价": 12.3},
    ])


def _period_df(sym: str) -> pd.DataFrame:
    """周期档 DataFrame(任意 sym 返回相同两行,用于断言解析/归一)。"""
    return pd.DataFrame([
        {"序号": 1, "行业": "银行", "公司家数": 84, "行业指数": 4342.38,
         "阶段涨跌幅": "4.98%", "流入资金": "30.0亿", "流出资金": "20.0亿", "净额": "10.0亿"},
        {"序号": 2, "行业": "证券", "公司家数": 50, "行业指数": 4100.0,
         "阶段涨跌幅": "-2.00%", "流入资金": "6.0亿", "流出资金": "8.0亿", "净额": "-2.0亿"},
    ])


def _patch_akshare(monkeypatch):
    import app.services.vibe_astock as astock

    class _FakeAk:
        @staticmethod
        def stock_fund_flow_industry(symbol="即时"):
            return _immediate_df() if symbol == "即时" else _period_df(symbol)

        @staticmethod
        def stock_board_industry_name_ths():
            return pd.DataFrame([{"name": "银行", "code": "881155"},
                                 {"name": "证券", "code": "881122"}])

    monkeypatch.setattr(astock, "_akshare", lambda: _FakeAk())
    return _FakeAk


def test_sectors_new_fields(monkeypatch):
    """即时档 sectors 透传 行业指数/领涨股/领涨股涨跌幅/当前价,原字段不受影响。"""
    import app.services.market_overview as mo

    _patch_akshare(monkeypatch)
    sectors = mo._sectors()
    by_name = {s["name"]: s for s in sectors}
    bank = by_name["银行"]
    assert bank["pct"] == 0.3
    assert bank["firms"] == 84
    assert bank["ths_code"] == "881155"
    assert bank["index"] == pytest.approx(4342.38)
    assert bank["lead"] == "招商银行"
    assert bank["lead_pct"] == pytest.approx(4.2)
    assert bank["lead_price"] == pytest.approx(35.54)
    assert bank["net"] == pytest.approx(16.06e8, rel=1e-6)
    # 净流出行业负净额不受影响
    assert by_name["证券"]["net"] == pytest.approx(-10.0e8, rel=1e-6)
    assert by_name["证券"]["lead_pct"] == pytest.approx(-3.0)


def test_build_period_flows(monkeypatch):
    """多周期:阶段涨跌幅字符串→数值、金额归一为元、按净额降序、四周期齐全。"""
    import app.services.industry_dashboard as ind

    _patch_akshare(monkeypatch)
    periods = ind._build_period_flows()
    assert set(periods.keys()) == {"3", "5", "10", "20"}
    rows = periods["5"]
    assert [r["name"] for r in rows] == ["银行", "证券"]  # 净额降序
    bank, sec = rows[0], rows[1]
    assert bank["pct"] == pytest.approx(4.98)
    assert bank["net"] == pytest.approx(10.0e8, rel=1e-6)
    assert bank["inflow"] == pytest.approx(30.0e8, rel=1e-6)
    assert bank["outflow"] == pytest.approx(20.0e8, rel=1e-6)
    assert bank["firms"] == 84
    assert sec["pct"] == pytest.approx(-2.0)
    assert sec["net"] == pytest.approx(-2.0e8, rel=1e-6)


async def _patch_industry_ctx(monkeypatch, *, strong: bool, cfg=None):
    """patch analyze_industry 依赖的 get_overview/get_industry_period_flows/_llm_cfg。"""
    import app.services.industry_dashboard as ind

    if strong:
        sectors = [{"name": "银行", "pct": 2.5, "net": 16.0e8, "inflow": 90.0e8,
                    "outflow": 74.0e8, "firms": 84, "ths_code": "881155",
                    "index": 4342.4, "lead": "招商银行", "lead_pct": 4.2, "lead_price": 35.5}]
        period = {k: [{"name": "银行", "pct": p, "net": 5.0e8,
                       "inflow": 20.0e8, "outflow": 15.0e8, "firms": 84}]
                  for k, p in [("3", 1.0), ("5", 2.0), ("10", 3.0), ("20", 4.0)]}
    else:
        sectors = [{"name": "银行", "pct": -4.0, "net": -12.0e8, "inflow": 40.0e8,
                    "outflow": 52.0e8, "firms": 84, "ths_code": "881155",
                    "index": 4342.4, "lead": "招商银行", "lead_pct": -2.0, "lead_price": 35.5}]
        period = {k: [{"name": "银行", "pct": p, "net": -3.0e8, "inflow": 10.0e8,
                       "outflow": 13.0e8, "firms": 84}]
                  for k, p in [("3", -1.0), ("5", -2.0), ("10", -3.0), ("20", -4.0)]}

    async def fake_overview():
        return {"sectors": sectors, "updated": "2026-09-26 10:00"}

    async def fake_periods():
        return {"as_of": "2026-09-26 10:00", "periods": period}

    monkeypatch.setattr(ind, "get_overview", fake_overview)
    monkeypatch.setattr(ind, "get_industry_period_flows", fake_periods)
    monkeypatch.setattr(ind, "_llm_cfg", (lambda: None) if cfg is None else (lambda: cfg))
    return ind


async def test_analyze_industry_strong_rule(monkeypatch):
    """强数据(涨+净流入+多周期全正)→ 正分,engine=rule,data 结构完整。"""
    ind = await _patch_industry_ctx(monkeypatch, strong=True)
    r = await ind.analyze_industry("银行")
    assert r["found"] is True
    assert r["name"] == "银行"
    assert r["engine"] == "rule"
    assert r["score"] > 0
    assert r["action"] in ("strong_buy", "buy")
    assert r["reasons"]
    assert r["data"]["today"]["lead"] == "招商银行"
    assert r["data"]["today"]["index"] == pytest.approx(4342.4)
    assert r["data"]["period_flows"]["5"]["pct"] == pytest.approx(2.0)
    assert r["data"]["period_flows"]["5"]["net_yi"] == pytest.approx(5.0)


async def test_analyze_industry_weak_rule(monkeypatch):
    """弱数据(跌+净流出+多周期全负)→ 负分,含风险提示。"""
    ind = await _patch_industry_ctx(monkeypatch, strong=False)
    r = await ind.analyze_industry("银行")
    assert r["found"] is True
    assert r["score"] < 0
    assert r["action"] in ("reduce", "avoid")
    assert r["risks"]


async def test_analyze_industry_not_found(monkeypatch):
    """名称未命中 → found=False + message。"""
    ind = await _patch_industry_ctx(monkeypatch, strong=True)
    r = await ind.analyze_industry("不存在的行业")
    assert r["found"] is False
    assert "message" in r


async def test_analyze_industry_uses_llm(monkeypatch):
    """LLM 配置存在且返回合法结论 → 使用 LLM 结果(engine=llm)。"""
    ind = await _patch_industry_ctx(monkeypatch, strong=True, cfg=_FAKE_CFG)

    def _fake_chat(cfg, system, user, max_tokens=900):
        assert "行业" in system
        assert "银行" in user
        return {"action": "buy", "action_label": "逢低关注", "score": 48,
                "summary": "行业 LLM 测试结论。", "reasons": ["资金共振"], "risks": []}

    monkeypatch.setattr(ind, "_llm_chat", _fake_chat)
    r = await ind.analyze_industry("银行")
    assert r["found"] is True
    assert r["engine"] == "llm"
    assert r["action"] == "buy"
    assert r["score"] == 48
    assert r["summary"] == "行业 LLM 测试结论。"
    assert r["reasons"] == ["资金共振"]


async def test_analyze_industry_llm_failure_falls_back(monkeypatch):
    """LLM 两次调用均失败 → 自动降级规则(engine=rule),不抛异常。"""
    ind = await _patch_industry_ctx(monkeypatch, strong=True, cfg=_FAKE_CFG)

    def _fail_chat(cfg, system, user, max_tokens=900):
        raise RuntimeError("network down")

    monkeypatch.setattr(ind, "_llm_chat", _fail_chat)
    r = await ind.analyze_industry("银行")
    assert r["found"] is True
    assert r["engine"] == "rule"
    assert r["score"] > 0 and r["action"] in ("strong_buy", "buy")
    assert r["summary"], "规则兜底应有结论"