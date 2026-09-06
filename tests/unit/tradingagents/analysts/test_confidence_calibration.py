"""置信度统计校准单测：命中率统计 / Wilson 区间 / Brier / 校准曲线 / 注入文案 / 缓存失效。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/analysts/test_confidence_calibration.py
"""

from __future__ import annotations

import sys
from unittest import mock

from tradingagents.agents.utils.confidence_calibration import (
    _is_hit,
    calibration_injection_text,
    compute_calibration_curve,
    compute_rating_stats,
    get_rating_stats,
    invalidate_calibration_cache,
    load_entries,
)

# 避免 tests/unit/tradingagents 目录缺失导致收集失败
sys.path.insert(0, "tests/unit")


def _entry(rating: str, raw: str, alpha: str = None, ticker: str = "000001", date: str = "2026-08-01") -> dict:
    e = {
        "date": date,
        "ticker": ticker,
        "rating": rating,
        "pending": False,
        "raw": raw,
        "alpha": alpha,
        "holding": "5d",
        "decision": "DECISION",
        "reflection": "REFLECTION",
    }
    # 模拟 load_entries 的数值化处理
    e["raw_f"] = _parse_like_load(raw)
    e["alpha_f"] = _parse_like_load(alpha) if alpha else None
    return e


def _parse_like_load(s: str):
    if not s or s.lower() in ("n/a", "nan"):
        return None
    return float(s.rstrip("%")) / 100.0


# ---------------------------------------------------------------------------
# compute_rating_stats
# ---------------------------------------------------------------------------


def test_rating_stats_buckets_and_hit_rates():
    entries = [
        _entry("Buy", "+5.2%", "+3.0%"),
        _entry("Buy", "+1.1%", "-0.5%"),
        _entry("Buy", "-2.0%", "-3.0%"),  # 未命中（raw<0）
        _entry("Overweight", "+0.8%", "+1.0%"),
        _entry("Underweight", "-4.0%", "-2.0%"),
        _entry("Sell", "+1.5%", "+2.0%"),  # 未命中（卖出但 raw>0）
        _entry("Hold", "+0.2%", "+0.1%"),  # 不参与命中率
    ]
    stats = compute_rating_stats(entries)

    buy = stats["per_rating"]["Buy"]
    assert buy["n"] == 3
    assert buy["abs_hit_rate"] == round(2 / 3, 4)  # 2/3 命中
    assert buy["brier"] == round(1 - 2 / 3, 4)

    overall = stats["overall"]
    assert overall["n"] == 6  # 方向性样本（不含 Hold）
    assert overall["abs_hit_rate"] == round(4 / 6, 4)  # Buy2 + Overweight1 + Underweight1
    # Wilson 95% 区间对称包围点估计
    assert overall["wilson_ci_lo"] <= overall["abs_hit_rate"] <= overall["wilson_ci_hi"]


def test_rating_stats_hold_only_reports_mean():
    entries = [_entry("Hold", "+1.0%"), _entry("Hold", "-1.0%")]
    stats = compute_rating_stats(entries)
    hold = stats["per_rating"]["Hold"]
    assert hold["abs_hit_rate"] is None
    assert hold["avg_raw"] == 0.0
    # 无方向性样本 → overall n=0
    assert stats["overall"]["n"] == 0


def test_rating_stats_empty():
    stats = compute_rating_stats([])
    assert stats["overall"]["n"] == 0
    assert stats["per_rating"]["Buy"]["abs_hit_rate"] is None


def test_is_hit_direction_logic():
    assert _is_hit(_entry("Buy", "+1%"), "Buy") is True
    assert _is_hit(_entry("Buy", "-1%"), "Buy") is False
    assert _is_hit(_entry("Sell", "-1%"), "Sell") is True
    assert _is_hit(_entry("Sell", "+1%"), "Sell") is False
    assert _is_hit(_entry("Hold", "+1%"), "Hold") is None
    assert _is_hit(_entry("Sell", "+1%"), "overall") is False
    assert _is_hit(_entry("Buy", "+1%"), "overall") is True


# ---------------------------------------------------------------------------
# compute_calibration_curve
# ---------------------------------------------------------------------------


def test_calibration_curve_buckets():
    entries = [
        _entry("Buy", "+5%", date="2026-08-01"),
        _entry("Buy", "-3%", date="2026-08-02"),  # 未命中
        _entry("Sell", "-2%", date="2026-08-03"),
        _entry("Hold", "+1%", date="2026-08-04"),
    ]
    conf_map = {
        ("000001", "2026-08-01"): 0.85,
        ("000001", "2026-08-02"): 0.85,
        ("000001", "2026-08-03"): 0.72,
        ("000001", "2026-08-04"): 0.88,
    }
    curve = compute_calibration_curve(entries, conf_map)
    by_bucket = {c["bucket"]: c for c in curve}

    assert by_bucket[">=0.8"]["n"] == 3  # 0.85/0.85/0.88
    assert by_bucket[">=0.8"]["claimed"] == round((0.85 + 0.85 + 0.88) / 3, 4)
    # 方向性样本：0.85命中(Buy+5%)、0.85未命中(Buy-3%)、0.88是Hold不参与 → 1/2
    assert by_bucket[">=0.8"]["empirical"] == 0.5
    assert by_bucket["0.7-0.8"]["n"] == 1  # 0.72
    assert by_bucket["<0.5"]["n"] == 0


def test_calibration_curve_no_confidence_match():
    curve = compute_calibration_curve(
        [_entry("Buy", "+5%", date="2026-08-01")], {}
    )
    assert all(c["n"] == 0 for c in curve)


# ---------------------------------------------------------------------------
# calibration_injection_text
# ---------------------------------------------------------------------------


def test_injection_text_empty_when_small_sample():
    entries = [_entry("Buy", "+5%")] * 5  # N=5 < 10
    stats = compute_rating_stats(entries)
    assert calibration_injection_text(stats) == ""


def test_injection_text_with_sufficient_sample():
    entries = [_entry("Buy", "+5%", "+3%") for _ in range(8)]
    entries += [_entry("Buy", "-2%", "-1%") for _ in range(4)]  # N=12
    stats = compute_rating_stats(entries)
    text = calibration_injection_text(stats)
    assert "历史命中率统计" in text
    assert "买入评级命中率" in text
    assert "方向性样本合计命中率" in text
    assert "67%" in text  # 8/12 命中


def test_injection_text_skips_low_sample_buckets():
    entries = [_entry("Buy", "+5%") for _ in range(12)] + [_entry("Sell", "-1%")]
    stats = compute_rating_stats(entries)
    text = calibration_injection_text(stats)
    assert "买入评级命中率" in text
    assert "卖出评级命中率" not in text  # N=1 < 10 不注入


# ---------------------------------------------------------------------------
# load_entries / 缓存
# ---------------------------------------------------------------------------


@mock.patch("tradingagents.agents.utils.confidence_calibration.get_config")
@mock.patch("tradingagents.agents.utils.memory.TradingMemoryLog")
def test_load_entries_parses_resolved_only(mock_log_cls, mock_get_config):
    pending = {
        "date": "2026-08-01", "ticker": "000001", "rating": "Buy",
        "pending": True, "raw": None, "alpha": None, "holding": None,
    }
    resolved = {
        "date": "2026-08-01", "ticker": "000001", "rating": "Buy",
        "pending": False, "raw": "+5.2%", "alpha": "+3.0%", "holding": "5d",
    }
    mock_log_cls.return_value.load_entries.return_value = [pending, resolved]
    entries = load_entries()
    assert len(entries) == 1
    assert entries[0]["raw_f"] == 0.052
    assert entries[0]["alpha_f"] == 0.03


def test_rating_stats_cache_and_invalidation():
    invalidate_calibration_cache()
    with mock.patch(
        "tradingagents.agents.utils.confidence_calibration.load_entries",
        return_value=[_entry("Buy", "+5%")] * 12,
    ):
        stats1 = get_rating_stats()
        assert stats1["overall"]["n"] == 12
        # mtime 未变 → 命中缓存（load_entries 不会被再次调用）
        with mock.patch(
            "tradingagents.agents.utils.confidence_calibration.load_entries",
            return_value=[_entry("Buy", "+5%")] * 3,
        ):
            stats2 = get_rating_stats()
            assert stats2["overall"]["n"] == 12  # 仍为缓存值
            # 失效后重算必须在 load_entries mock 生效范围内调用，否则走真实数据
            invalidate_calibration_cache()
            stats3 = get_rating_stats()
            assert stats3["overall"]["n"] == 3  # 失效后重算
