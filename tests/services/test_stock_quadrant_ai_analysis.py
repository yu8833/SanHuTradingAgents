"""
个股趋势「单股 AI 操作结论」 单元测试。

验证 analyze_stock_operation：
1. 规则路径（无 LLM 配置）：强势数据→正向建议；弱势数据→负向建议；未在帧中→found=False；
2. LLM 路径：配置存在且返回合法 JSON → 使用 LLM 结论（engine=llm）；
3. LLM 失败 → 自动降级规则（engine=rule），不抛异常。

统一 monkeypatch _llm_cfg 避免真实网络调用。
"""
import pytest

pytestmark = [pytest.mark.unit]


def _fake_quadrant(code: str, rows: list[list[float | None]]) -> dict:
    """构造合成 quadrant 缓存：dates 升序、每日帧只含目标股、meta 含名称。"""
    dates = [f"2026-09-{10 + i:02d}" for i in range(len(rows))]
    frames = {d: {code: row} for d, row in zip(dates, rows)}
    return {
        "as_of": "2026-09-22 10:00",
        "dates": dates,
        "meta": {code: {"name": "测试股", "industry": "测试行业"}},
        "frames": frames,
    }


def _patch_quadrant(monkeypatch, code, rows):
    import app.services.stock_quadrant_analysis as sq

    async def fake():
        return _fake_quadrant(code, rows)

    monkeypatch.setattr(sq, "get_stock_quadrant", fake)
    return sq


async def test_ai_analysis_strong(monkeypatch):
    """高涨幅+资金流入+低估值+连板 → 正向操作建议且评分>0。"""
    sq = _patch_quadrant(monkeypatch, "600000",
                         [[2.0, 10.0, 6.0, 15.0, 100.0, 1.0, 0, 5.0] for _ in range(7)]
                         + [[6.0, 10.0, 8.0, 15.0, 100.0, 3.5, 1, 10.0]])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_stock_operation("600000")
    assert r["found"] is True
    assert r["engine"] == "rule"
    assert r["name"] == "测试股"
    assert r["score"] > 0, f"强势数据应得正分，实际 {r['score']}"
    assert r["action"] in ("strong_buy", "buy")
    assert r["action_label"]
    assert r["reasons"], "应有判断要点"
    assert r["data"]["today"]["pct"] == 6.0
    assert len(r["data"]["recent_trend"]) == 8


async def test_ai_analysis_weak(monkeypatch):
    """大跌+资金流出 → 负向操作建议且评分<0，含风险提示。"""
    sq = _patch_quadrant(monkeypatch, "600001",
                         [[-1.0, 10.0, 5.0, 12.0, 100.0, -0.5, 0, -3.0] for _ in range(7)]
                         + [[-7.0, 10.0, 18.0, 12.0, 100.0, -4.0, 0, -12.0]])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_stock_operation("600001")
    assert r["found"] is True
    assert r["score"] < 0, f"弱势数据应得负分，实际 {r['score']}"
    assert r["action"] in ("reduce", "avoid")
    assert r["risks"], "应有风险提示"


async def test_ai_analysis_not_found(monkeypatch):
    """帧中无该股 → found=False 且不抛异常。"""
    sq = _patch_quadrant(monkeypatch, "600000",
                         [[1.0, 5.0, 5.0, 30.0, 200.0, 0.2, 0, 2.0] for _ in range(5)])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_stock_operation("300999")
    assert r["found"] is False
    assert "message" in r


async def test_ai_analysis_uses_llm(monkeypatch):
    """LLM 配置存在且返回合法结论 → 使用 LLM 结果（engine=llm）。"""
    sq = _patch_quadrant(monkeypatch, "600002",
                         [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(6)]
                         + [[2.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0]])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: {"model": "deepseek-v4-flash",
                                                 "api_base": "https://api.deepseek.com",
                                                 "api_key": "fake", "temperature": 0.3})

    def _fake_chat(cfg, system, user, max_tokens=900):
        assert "个股趋势" in system
        assert "600002" in user
        return {"action": "buy", "action_label": "逢低关注", "score": 48,
                "summary": "LLM 测试结论。", "reasons": ["理由A"], "risks": []}

    monkeypatch.setattr(sq, "_llm_chat", _fake_chat)

    r = await sq.analyze_stock_operation("600002")
    assert r["found"] is True
    assert r["engine"] == "llm"
    assert r["action"] == "buy"
    assert r["score"] == 48
    assert r["summary"] == "LLM 测试结论。"
    assert r["reasons"] == ["理由A"]


async def test_ai_analysis_llm_failure_falls_back(monkeypatch):
    """LLM 两次调用均失败 → 自动降级规则（engine=rule），不抛异常。"""
    sq = _patch_quadrant(monkeypatch, "600003",
                         [[2.0, 10.0, 6.0, 15.0, 100.0, 1.0, 0, 5.0] for _ in range(7)]
                         + [[6.0, 10.0, 8.0, 15.0, 100.0, 3.5, 1, 10.0]])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: {"model": "m", "api_base": "b", "api_key": "k"})

    def _fail_chat(cfg, system, user, max_tokens=900):
        raise RuntimeError("network down")

    monkeypatch.setattr(sq, "_llm_chat", _fail_chat)

    r = await sq.analyze_stock_operation("600003")
    assert r["found"] is True
    assert r["engine"] == "rule"
    assert r["score"] > 0 and r["action"] in ("strong_buy", "buy")
    assert r["summary"], "规则兜底应有结论"