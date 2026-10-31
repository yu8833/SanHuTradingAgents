"""大盘位置（market_position）纯计算单元测试。"""
from datetime import datetime, timedelta

from app.services.market_position import (
    _divergence,
    _forward_stats,
    _rank_series,
    _zone_of,
    compute_position_payload,
)


def _rows(n: int = 800) -> list[dict]:
    start = datetime(2023, 1, 2)
    out = []
    for i in range(n):
        out.append({
            "date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
            "n": 5000,
            "up": 1000 + i,
            "down": 3000 - i,
            "up_pct": round((1000 + i) / 5000 * 100, 2),
            "zt": 20 + i // 10,
            "amount": round(800 + i, 2),
            # 交替涨跌，保证未来 20 日收益有正有负
            "avg_pct": 0.6 if i % 2 == 0 else -0.5,
            "avg_pe": None,
        })
    return out


def test_empty_rows_not_ready():
    payload = compute_position_payload([])
    assert payload["ready"] is False
    assert payload["position"] == []
    assert payload["forward"] is None


def test_position_metrics_and_zone():
    payload = compute_position_payload(_rows())
    assert payload["ready"] is True
    keys = [p["key"] for p in payload["position"]]
    assert keys == ["valuation", "sentiment", "breadth", "funds"]

    breadth = payload["position"][2]
    assert breadth["percentile"] is not None and breadth["percentile"] >= 95
    assert breadth["samples"] == 799

    valuation = payload["position"][0]
    assert valuation["percentile"] is None
    assert valuation["samples"] == 0

    # 宽度/情绪/资金都在历史高位 → 合成高位区
    assert payload["composite"]["percentile"] >= 90
    assert payload["composite"]["zone"] == "overheated"
    assert payload["composite"]["label"] == "高位区"


def test_zone_mapping():
    assert _zone_of(85)["zone"] == "overheated"
    assert _zone_of(65)["zone"] == "warm"
    assert _zone_of(50)["zone"] == "neutral"
    assert _zone_of(25)["zone"] == "cool"
    assert _zone_of(5)["zone"] == "oversold"
    assert _zone_of(None)["zone"] == "unknown"


def test_rank_series_has_no_future_lookahead():
    vals = [1, 2, 3, 4, 5, 6]
    ranks = _rank_series(vals)
    # 前 60 个样本不足时不给分位
    assert all(r is None for r in ranks[:60])
    assert ranks[5] is None

    vals = list(range(70))
    ranks = _rank_series(vals)
    assert ranks[-1] == 100  # 最大值高于此前全部样本，分位 100


def test_forward_bins():
    # 三个指标周期波动，保证合成分位覆盖 5 档
    start = datetime(2023, 1, 2)
    rows = []
    for i in range(800):
        rows.append({
            "date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
            "up_pct": (i * 7) % 100,
            "zt": (i * 5) % 100,
            "amount": (i * 11) % 1000,
            "avg_pct": 0.6 if i % 2 == 0 else -0.5,
        })
    series = _rank_series([r["up_pct"] for r in rows])
    fwd = _forward_stats(rows, series)
    assert fwd is not None
    assert fwd["day"] == 20
    assert len(fwd["bins"]) == 5
    assert sum(b["n"] for b in fwd["bins"]) == fwd["samples"]
    assert fwd["samples"] > 600
    assert fwd["current_bin"] in {"b0", "b1", "b2", "b3", "b4"}
    assert sum(1 for b in fwd["bins"] if b["n"] > 0) >= 3
    for b in fwd["bins"]:
        if b["n"] > 0:
            assert b["median_return"] is not None
            assert b["win_rate"] is not None


def test_forward_hidden_when_history_too_short():
    rows = _rows(200)[:200]
    series = _rank_series([r["up_pct"] for r in rows])
    assert _forward_stats(rows, series) is None


def test_divergence_rules():
    position = {
        "valuation": {"percentile": 80},
        "breadth": {"percentile": 20},
        "funds": {"percentile": 70},
        "sentiment": {"percentile": 90},
    }
    out = _divergence(position, composite=75)
    titles = {d["title"] for d in out}
    assert "估值与宽度背离" in titles
    assert "放量下跌" in titles
    assert len(out) <= 3

    calm = {
        "valuation": {"percentile": 50},
        "breadth": {"percentile": 50},
        "funds": {"percentile": 50},
        "sentiment": {"percentile": 50},
    }
    assert _divergence(calm, composite=50) == []
