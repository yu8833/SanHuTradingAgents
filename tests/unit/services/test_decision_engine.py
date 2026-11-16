"""今日待办规则层单测：方向过滤、环境闸门、仓位与组合约束、过期信号、T+1。"""

from __future__ import annotations

import pytest

from app.services.decision import decide
from app.services.decision.models import Candidate, Direction, Holding, Snapshot


def test_normalize_industries_keeps_only_ths_names():
    from app.services.market_synthesis import normalize_industries

    out = normalize_industries(["半导体", "半导体 ", "科技", "其他", "", None, "消费电子"])
    assert out == ["半导体", "消费电子"]


def _snapshot(**kwargs) -> Snapshot:
    defaults = dict(
        as_of="2026-11-16T10:00:00+08:00",
        trade_date="2026-11-16",
        is_intraday=True,
        quote_as_of=None,
        gate="green",
        gate_label="进攻",
        gate_degraded=False,
        gate_position_hint="7-8 成",
        direction=Direction(
            status="ok",
            attack=("半导体", "消费电子"),
            avoid=("房地产开发",),
            as_of="2026-11-16",
            direction="偏多",
        ),
        cash=1_000_000.0,
        equity=1_000_000.0,
    )
    defaults.update(kwargs)
    return Snapshot(**defaults)


def _candidate(**kwargs) -> Candidate:
    defaults = dict(
        code="600001",
        name="测试股",
        industry="半导体",
        price=10.0,
        price_source="live",
        trigger_price=9.8,
        source="b2",
        score=85,
        bias60=3.0,
        structure_stop=9.2,
        trigger_date="2026-11-16",
        status="triggered",
    )
    defaults.update(kwargs)
    return Candidate(**defaults)


def test_attack_industry_passes_and_avoid_industry_filtered():
    snap = _snapshot(
        candidates=(
            _candidate(code="600001", industry="半导体"),
            _candidate(code="600002", industry="房地产开发", price=8.0),
            _candidate(code="600003", industry="银行", price=9.0),
        )
    )
    result = decide(snap)
    assert [x["code"] for x in result["buy"]["items"]] == ["600001"]
    assert result["buy"]["filtered"] == {"avoid": 1, "not_attack": 1}


def test_direction_unavailable_does_not_silently_filter():
    snap = _snapshot(
        direction=Direction(status="unavailable", note="旧缓存缺少方向字段"),
        candidates=(_candidate(industry="银行"),),
    )
    result = decide(snap)
    assert result["direction"]["usable"] is False
    assert result["buy"]["items"][0]["blocked"] is False
    assert any("方向过滤未生效" in r["text"] for r in result["buy"]["items"][0]["reasons"])


@pytest.mark.parametrize("gate", ["red"])
def test_red_gate_blocks_new_positions(gate):
    snap = _snapshot(gate=gate, candidates=(_candidate(),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert item["suggest_qty"] == 0
    assert "红灯" in item["block_reason"]


def test_degraded_gate_blocks_new_positions():
    snap = _snapshot(gate_degraded=True, candidates=(_candidate(),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert "降级" in item["block_reason"]


def test_yellow_gate_halves_risk_and_limits_positions():
    snap = _snapshot(gate="yellow", candidates=(_candidate(),))
    green = decide(_snapshot(candidates=(_candidate(),)))["buy"]["items"][0]
    yellow = decide(snap)["buy"]["items"][0]
    assert yellow["suggest_qty"] == green["suggest_qty"] // 2 or yellow["suggest_qty"] < green["suggest_qty"]
    assert yellow["risk_amount"] <= green["risk_amount"]

    holdings = tuple(
        Holding(code=f"00000{i}", name=f"持仓{i}", industry="银行", source="paper", state="normal")
        for i in range(3)
    )
    blocked = decide(_snapshot(gate="yellow", holdings=holdings, candidates=(_candidate(),)))
    assert blocked["buy"]["items"][0]["blocked"] is True
    assert "上限 3 只" in blocked["buy"]["items"][0]["block_reason"]


def test_single_position_cap_15pct():
    snap = _snapshot(
        candidates=(_candidate(score=100, price=10.0, structure_stop=9.9, bias60=0),),
    )
    item = decide(snap)["buy"]["items"][0]
    assert item["position_pct"] <= 0.15 + 1e-9


def test_invalid_stop_is_rejected():
    snap = _snapshot(candidates=(_candidate(structure_stop=10.5),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert "止损价" in item["block_reason"]


def test_missing_price_blocks_without_fake_order_params():
    snap = _snapshot(candidates=(_candidate(price=None, price_source="none"),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert item["suggest_qty"] == 0
    assert item["stop_loss_price"] is None
    assert "取不到现价" in item["block_reason"]


def test_zero_equity_blocks():
    snap = _snapshot(equity=0.0, cash=0.0, candidates=(_candidate(),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert "总资产" in item["block_reason"]


def test_industry_cap_30pct():
    holdings = (
        Holding(
            code="000001", name="已有", industry="半导体", source="paper", state="normal",
            quantity=28_000, market_value=280_000,
        ),
    )
    snap = _snapshot(holdings=holdings, candidates=(_candidate(score=100),))
    item = decide(snap)["buy"]["items"][0]
    room = 1_000_000 * 0.30 - 280_000
    assert item["suggest_amount"] <= room


def test_portfolio_risk_cap_3pct():
    candidates = tuple(
        _candidate(code=f"60{i:04d}", name=f"股{i}", price=10.0, structure_stop=9.6, score=90, bias60=0)
        for i in range(6)
    )
    result = decide(_snapshot(candidates=candidates))
    total_risk = sum(x["risk_amount"] for x in result["buy"]["items"])
    assert total_risk <= 1_000_000 * 0.03 + 1e-6
    assert any(x["blocked"] for x in result["buy"]["items"])


def test_stale_trigger_goes_to_watch_not_buy():
    snap = _snapshot(
        candidates=(_candidate(status="watching", stale=True, price=9.0, trigger_price=9.5),)
    )
    result = decide(snap)
    assert result["buy"]["count"] == 0
    assert result["watch"]["items"][0]["stale"] is True
    assert "过期" in result["watch"]["items"][0]["summary"]


def test_missing_mainlines_does_not_claim_not_mainline():
    snap = _snapshot(mainlines={}, candidates=(_candidate(),))
    reasons = decide(snap)["buy"]["items"][0]["reasons"]
    texts = [r["text"] for r in reasons]
    assert any("主线数据缺失" in t for t in texts)
    assert not any("不在资金持续净流入主线内" in t for t in texts)


def test_held_code_cannot_be_bought_again():
    holdings = (
        Holding(code="600001", name="测试股", industry="半导体", source="paper", state="normal", quantity=100),
    )
    snap = _snapshot(holdings=holdings, candidates=(_candidate(held=True),))
    item = decide(snap)["buy"]["items"][0]
    assert item["blocked"] is True
    assert "已持有" in item["block_reason"]


def test_sell_exit_wins_and_t1_downgrades_to_warn():
    holdings = (
        Holding(code="600001", name="A", industry="半导体", source="paper", state="exit", sell_pct=1.0),
        Holding(
            code="600002", name="B", industry="银行", source="paper", state="exit",
            sell_pct=1.0, t1_locked=True,
        ),
        Holding(code="600003", name="C", industry="银行", source="paper", state="normal"),
    )
    sell = decide(_snapshot(holdings=holdings))["sell"]
    assert sell["exit_count"] == 1
    assert sell["warn_count"] == 1
    assert sell["hold_count"] == 1
    assert sell["items"][0]["code"] == "600001"
    assert sell["items"][1]["state"] == "warn"
    assert "T+1" in sell["items"][1]["advice"]


def test_sorting_is_deterministic():
    snap = _snapshot(
        candidates=(
            _candidate(code="600002", score=90, bias60=5, trigger_price=9.9),
            _candidate(code="600001", score=90, bias60=5, trigger_price=9.9),
            _candidate(code="600003", score=95, bias60=2, trigger_price=9.9),
        )
    )
    codes = [x["code"] for x in decide(snap)["buy"]["items"]]
    assert codes == ["600003", "600001", "600002"]
    assert decide(snap)["meta"]["snapshot_hash"] == decide(snap)["meta"]["snapshot_hash"]
