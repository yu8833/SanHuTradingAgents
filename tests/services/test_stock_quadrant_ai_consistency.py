"""
股票筛选「候选股维度一致性 AI 分析」 单元测试。

验证 analyze_candidate_consistency：
1. 规则路径（无 LLM 配置）：
   - 四维同向（趋势偏多+买入信号+双击+无预警）→ consistency=align（共振）
   - 四维多空对立（趋势偏多+卖出信号+双击+有预警）→ consistency=diverg（背离）且 conflicts 非空
2. LLM 路径：配置存在且返回合法 JSON → 使用 LLM 解读（engine=llm）
3. LLM 失败 → 自动降级规则（engine=rule），不抛异常
4. 帧中无该股 → found=False；操作结论字段与一致性区块结构完整

统一 monkeypatch _llm_cfg / get_stock_quadrant 避免真实网络与缓存依赖。
"""
import pytest

pytestmark = [pytest.mark.unit]

# 帧 8 元组：[pct, amt, turn, pe, mv, main, board, d5]
_STRONG_LAST = [6.0, 10.0, 8.0, 15.0, 100.0, 3.5, 1, 10.0]   # 强势共振（资金流入+上涨）
_WEAK_LAST = [-7.0, 10.0, 18.0, 12.0, 100.0, -4.0, 0, -12.0]  # 弱势杀跌（资金流出+下跌）


def _fake_quadrant(code: str, rows: list[list[float | None]]) -> dict:
    dates = [f"2026-09-{10 + i:02d}" for i in range(len(rows))]
    frames = {d: {code: row} for d, row in zip(dates, rows, strict=True)}
    return {
        "as_of": "2026-09-22 10:00",
        "dates": dates,
        "meta": {code: {"name": "测试股", "industry": "计算机"}},
        "frames": frames,
    }


def _patch(monkeypatch, code: str, rows: list[list[float | None]]):
    import app.services.stock_quadrant_analysis as sq

    async def fake():
        return _fake_quadrant(code, rows)

    monkeypatch.setattr(sq, "get_stock_quadrant", fake)
    return sq


async def test_consistency_align_bullish(monkeypatch):
    """四维同向（强势共振+B2+双击+无预警）→ 多维共振（偏多），无冲突。"""
    sq = _patch(monkeypatch, "600010",
                [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(7)] + [_STRONG_LAST])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_candidate_consistency(
        "600010", signal_type="B2", signal_label="突破买点",
        dg_quadrant="双击", aux_warnings=[])
    assert r["found"] is True
    assert r["engine"] == "rule"
    assert r["consistency"] == "align", f"应共振，实际 {r['consistency']}"
    assert "偏多" in r["consistency_label"]
    assert r["conflicts"] == [], "全部同向不应有冲突"
    dims = {d["name"]: d for d in r["dimensions"]}
    assert dims["趋势象限"]["value"] == "强势共振"
    assert dims["择时信号"]["support"] > 0
    assert dims["ΔG 象限"]["support"] > 0
    assert r["summary"], "应有操作结论"
    assert r["consistency_summary"], "应有一致性总评"


async def test_consistency_diverg(monkeypatch):
    """多空对立（强势共振+S1卖点+双击+有预警）→ 多空背离，conflicts 非空。"""
    sq = _patch(monkeypatch, "600011",
                [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(7)] + [_STRONG_LAST])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_candidate_consistency(
        "600011", signal_type="S1", signal_label="加速卖点",
        dg_quadrant="双击", aux_warnings=["放量下跌（价跌量涨），警惕主力出货"])
    assert r["found"] is True
    assert r["consistency"] == "diverg", f"应背离，实际 {r['consistency']}"
    assert "背离" in r["consistency_label"]
    assert r["conflicts"], "多空对立时必须有冲突解释"
    dims = {d["name"]: d for d in r["dimensions"]}
    assert dims["择时信号"]["support"] < 0
    assert dims["辅助预警"]["support"] < 0
    assert "趋势象限" in r["consistency_summary"]


async def test_consistency_weak_all_negative(monkeypatch):
    """全面走弱（弱势杀跌+仅S3信号）→ 共振但偏空。"""
    sq = _patch(monkeypatch, "600012",
                [[-1.0, 8.0, 5.0, 12.0, 100.0, -0.5, 0, -3.0] for _ in range(7)] + [_WEAK_LAST])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_candidate_consistency(
        "600012", signal_type="S3", signal_label="清仓卖出", dg_quadrant="双杀")
    assert r["consistency"] == "align"
    assert "偏空" in r["consistency_label"]
    assert r["score"] < 0, "弱势数据操作结论应为负分"


async def test_consistency_uses_llm(monkeypatch):
    """LLM 配置存在且返回合法 JSON → 使用 LLM 解读（engine=llm），结构归一化。"""
    sq = _patch(monkeypatch, "600013",
                [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(6)]
                + [[2.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0]])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: {"model": "deepseek-v4-flash",
                                                 "api_base": "https://api.deepseek.com",
                                                 "api_key": "fake", "temperature": 0.3})

    def _fake_chat(cfg, system, user, max_tokens=900):
        assert "四维信号" in user or "维度" in user
        return {
            "consistency": "partial", "consistency_label": "存在分歧",
            "summary": "资金与基本面多数支持，但择时提示冲高需谨慎。",
            "dimensions": [
                {"name": "趋势象限", "value": "强势共振", "view": "资金配合", "support": 0.9},
                {"name": "择时信号", "value": "突破买点", "view": "右侧进场", "support": 1.0},
                {"name": "ΔG 象限", "value": "双击", "view": "景气兑现", "support": 1.0},
            ],
            "conflicts": ["短期资金较强，但换手快速放大需防冲高回落"],
        }

    monkeypatch.setattr(sq, "_llm_chat", _fake_chat)

    r = await sq.analyze_candidate_consistency(
        "600013", signal_type="B2", signal_label="突破买点", dg_quadrant="双击")
    assert r["found"] is True
    assert r["engine"] == "llm"
    assert r["consistency"] == "partial"
    assert r["consistency_label"] == "存在分歧"
    assert r["consistency_summary"].startswith("资金与基本面")
    assert len(r["conflicts"]) == 1
    assert r["dimensions"], "LLM 给出的维度应保留"
    # 操作结论字段（趋势帧口径）仍返回
    assert r["action"], "应有操作建议"
    assert r["score"] is not None, "应有评分"
    assert r["data"]["today"]["pct"] == 2.0


async def test_consistency_llm_failure_falls_back(monkeypatch):
    """LLM 两次调用均失败 → 降级规则一致性（engine=rule），不抛异常。"""
    sq = _patch(monkeypatch, "600014",
                [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(7)] + [_STRONG_LAST])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: {"model": "m", "api_base": "b", "api_key": "k"})

    def _fail_chat(cfg, system, user, max_tokens=900):
        raise RuntimeError("network down")

    monkeypatch.setattr(sq, "_llm_chat", _fail_chat)

    r = await sq.analyze_candidate_consistency(
        "600014", signal_type="B2", signal_label="突破买点")
    assert r["found"] is True
    assert r["engine"] == "rule"
    assert r["consistency"] in ("align", "diverg", "partial", "neutral")
    assert r["consistency_summary"], "规则兜底应有总评"
    assert r["action"], "操作结论仍应有"


async def test_consistency_dg_fullname(monkeypatch):
    """ΔG 象限为「戴维斯双击」全称 → 仍按双击正向识别。"""
    sq = _patch(monkeypatch, "600015",
                [[1.0, 8.0, 5.0, 25.0, 150.0, 0.3, 0, 3.0] for _ in range(7)] + [_STRONG_LAST])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_candidate_consistency(
        "600015", signal_type="B2", signal_label="突破买点", dg_quadrant="戴维斯双击")
    dims = {d["name"]: d for d in r["dimensions"]}
    assert dims["ΔG 象限"]["value"] == "戴维斯双击"
    assert dims["ΔG 象限"]["support"] > 0, "全称双击应识别为偏多"


async def test_consistency_not_found(monkeypatch):
    """帧中无该股 → found=False 且不抛异常。"""
    sq = _patch(monkeypatch, "600000",
                [[1.0, 5.0, 5.0, 30.0, 200.0, 0.2, 0, 2.0] for _ in range(5)])
    monkeypatch.setattr(sq, "_llm_cfg", lambda: None)

    r = await sq.analyze_candidate_consistency(
        "300999", signal_type="B1", signal_label="左侧买点")
    assert r["found"] is False
    assert "message" in r