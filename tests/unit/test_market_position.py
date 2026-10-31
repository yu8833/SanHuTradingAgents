"""大盘位置（market_position）纯计算单元测试。"""
from datetime import datetime, timedelta

from app.services.market_position import (
    _divergence,
    _forward_returns,
    _forward_stats,
    _heat_of,
    _rank_series,
    _zone_of,
    compute_position_payload,
)

KEYS = [
    "valuation_pe", "valuation_pb", "drawdown", "ma250_dev", "amplitude",
    "volatility", "amount", "up_pct", "low_price",
]
LONG_KEYS = {"drawdown", "ma250_dev", "amplitude", "volatility", "amount", "up_pct", "low_price"}


def _rows(n: int = 800) -> list[dict]:
    """构造趋势向上、宽度扩张、低价股占比下降的合成历史。"""
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
            "amp_pct": round(2.0 + i / 1000, 2),
            "low_pct": round(20 - i / 100, 2),
            "avg_pe": None,
            "avg_pb": None,
        })
    return out


def test_empty_rows_not_ready():
    payload = compute_position_payload([])
    assert payload["ready"] is False
    assert payload["position"] == []
    assert payload["forward"] is None
    assert payload["analogs"] is None
    assert payload["guidance"]["top"]["active"] is False
    assert payload["guidance"]["bottom"]["active"] is False


def test_position_metrics_and_zone():
    payload = compute_position_payload(_rows())
    assert payload["ready"] is True

    by_key = {p["key"]: p for p in payload["position"]}
    assert list(by_key) == KEYS

    # PE / PB 样本缺失 → 不给分位、样本数 0，且不参与合成
    for k in ("valuation_pe", "valuation_pb"):
        assert by_key[k]["percentile"] is None
        assert by_key[k]["samples"] == 0
        assert by_key[k]["group"] == "估值"

    # 上涨家数单调上升 → 当前值高于此前全部样本，分位 100
    assert by_key["up_pct"]["percentile"] == 100
    assert by_key["up_pct"]["samples"] == 799
    assert by_key["up_pct"]["group"] == "参与度"

    # 低价股占比越高越冷：热度方向必须反向
    assert by_key["low_price"]["higher_is_hot"] is False
    assert by_key["drawdown"]["higher_is_hot"] is False

    comp = payload["composite"]
    assert set(comp["components"]) == LONG_KEYS
    assert comp["percentile"] is not None and comp["percentile"] >= 75
    assert comp["zone"] == "overheated"
    assert comp["label"] == "高位区"
    assert "逃顶" in comp["advice"]


def test_composite_series_and_thresholds():
    payload = compute_position_payload(_rows())
    comp = payload["composite"]
    series = comp["series"]
    # 800 行样本 → 等距抽稀到上限 180 个点
    assert len(series) == 180
    assert series[-1]["pct"] == comp["percentile"]
    dates = [p["date"] for p in series]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    assert all(0 <= p["pct"] <= 100 for p in series)
    assert comp["thresholds"] == {"top": 80, "bottom": 20}

    empty = compute_position_payload([])
    assert empty["composite"]["series"] == []
    assert empty["composite"]["thresholds"] == {"top": 80, "bottom": 20}


def test_guidance_blocks():
    payload = compute_position_payload(_rows())
    g = payload["guidance"]
    assert g["top"]["active"] is True and g["bottom"]["active"] is False
    assert "逃顶" in g["top"]["title"]
    assert "判断底部" in g["bottom"]["title"]
    assert "历史" in g["top"]["stats"] and "%" in g["top"]["stats"]
    assert g["current"]["percentile"] == payload["composite"]["percentile"]


def test_analogs_cases():
    payload = compute_position_payload(_rows())
    logs = payload["analogs"]
    assert logs is not None
    assert logs["day"] == 20
    assert 1 <= logs["n"] <= 6
    assert len(logs["cases"]) == logs["n"]
    assert logs["median_return"] is not None
    assert logs["win_rate"] is not None
    for c in logs["cases"]:
        assert c["date"] and c["forward_return"] is not None
        assert 0 <= c["similarity"] <= 100
    assert "不代表未来" in logs["note"]


def test_zone_mapping():
    assert _zone_of(85)["zone"] == "overheated"
    assert _zone_of(65)["zone"] == "warm"
    assert _zone_of(50)["zone"] == "neutral"
    assert _zone_of(25)["zone"] == "cool"
    assert _zone_of(5)["zone"] == "oversold"
    assert _zone_of(None)["zone"] == "unknown"
    assert "逃顶" in _zone_of(85)["advice"]
    assert "判断底部" in _zone_of(5)["advice"]


def test_heat_semantics():
    assert _heat_of(90, True) == 90
    assert _heat_of(90, False) == 10
    assert _heat_of(None, True) is None


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
    # 指标周期波动，保证分位覆盖 5 档
    start = datetime(2023, 1, 2)
    rows = []
    for i in range(800):
        rows.append({
            "date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
            "up_pct": (i * 7) % 100,
            "amount": (i * 11) % 1000,
            "amp_pct": (i * 13) % 60,
            "low_pct": (i * 17) % 50,
            "avg_pct": 0.6 if i % 2 == 0 else -0.5,
        })
    series = _rank_series([r["up_pct"] for r in rows])
    fwd = _forward_stats(rows, series, _forward_returns(rows))
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
    # 逃顶 / 判断底部的历史证据：最热 / 最冷各 20%
    assert "hot" in fwd["zones"] and "cold" in fwd["zones"]
    assert fwd["zones"]["hot"]["n"] >= 0
    assert fwd["zones"]["cold"]["n"] >= 0


def test_forward_hidden_when_history_too_short():
    rows = _rows(200)
    series = _rank_series([r["up_pct"] for r in rows])
    assert _forward_stats(rows, series, _forward_returns(rows)) is None


def test_divergence_rules():
    percentiles = {
        "valuation_pe": 80,
        "up_pct": 20,
        "amount": 70,
        "drawdown": 30,
        "volatility": 50,
    }
    out = _divergence(percentiles, 75)
    titles = {d["title"] for d in out}
    assert "估值与宽度背离" in titles
    assert "放量下跌" in titles
    assert len(out) <= 3

    calm = {k: 50 for k in percentiles}
    assert _divergence(calm, 50) == []

    deep = {**calm, "drawdown": 90, "volatility": 90}
    assert _divergence(deep, 50)[0]["title"] == "深回撤 + 高波动"
