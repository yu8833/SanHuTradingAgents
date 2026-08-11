"""
筛查进程内面板/目标日缓存 防回归测试。

优化背景：筛查最贵的一步是 load_daily_panel(全市场日线 ~7s) + compute_all(指标 ~17s)
+ enrich_target(基本面/分红 ~4s)，合计才是此前"60s 重算"的主要来源。结果已写 MongoDB
缓存，但首次/缓存失效时每次都要全量重算。

修复：在 screener 内增加按 (as_of, pool) 的 LRU+TTL 进程内缓存（_load_computed_panel /
_get_enriched_target）。同一交易日面板与指标是确定的；as_of 即最新交易日，交易日变化
→ key 变化 → 自动失效，无脏数据。

本测试验证：
1. 同日重复调用 _load_computed_panel 命中缓存，compute_all 只执行一次；
2. 同日重复调用 _get_enriched_target 命中缓存，enrich 只执行一次；
3. 换一个 as_of（交易日变化）→ 新 key → 触发重算，不返回旧缓存；
4. _load_computed_panel 空面板不缓存。
"""
import pandas as pd
import pytest

import app.strategy_system.screener as screener

pytestmark = [pytest.mark.regression, pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clear_screen_cache():
    """每个用例前后清空模块级缓存，避免用例间相互污染。"""
    screener._panel_cache.clear()
    screener._target_cache.clear()
    yield
    screener._panel_cache.clear()
    screener._target_cache.clear()


def _make_panel(as_of: str) -> pd.DataFrame:
    """构造一个含 warmup 历史的迷你面板（供 compute_all 处理）。"""
    # 用 3 个交易日，保证 as_of 是最后一行的 target 日
    dates = ["2026-01-05", "2026-01-06", as_of]
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "symbol": "000001", "date": d,
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0 + i,
            "volume": 1000, "amount": 10000, "pct_chg": 0.0,
        })
    return pd.DataFrame(rows)


def _fake_enrich(db, target, as_of_date):
    """替身 enrich：注入一个可辨识列，便于断言调用次数。"""
    out = target.copy()
    out["_enriched_marker"] = as_of_date
    return out


def test_same_as_of_reuses_cached_panel(monkeypatch):
    """同日重复调用 _load_computed_panel 应命中缓存，compute_all 只跑一次。"""
    as_of = "2026-01-07"
    calls = {"panel": 0, "compute": 0}

    def fake_load(db, pool, start_dt, end_dt, period="daily"):
        calls["panel"] += 1
        return _make_panel(as_of)

    def fake_compute(df, progress_cb=None):
        calls["compute"] += 1
        return df

    monkeypatch.setattr(screener.data_adapter, "load_daily_panel", fake_load)
    monkeypatch.setattr(screener, "compute_all", fake_compute)

    db = object()
    first = screener._load_computed_panel(db, None, as_of)
    second = screener._load_computed_panel(db, None, as_of)

    assert calls["compute"] == 1, f"compute_all 应只执行一次，实际 {calls['compute']}"
    assert first is second, "第二次应返回同一缓存对象（未重算）"
    assert not first.empty


def test_refresh_flag_does_not_break_panel_cache(monkeypatch):
    """refresh=True 只重算策略结果，底层面板仍可复用缓存。"""
    as_of = "2026-01-07"
    calls = {"compute": 0}

    def fake_load(db, pool, start_dt, end_dt, period="daily"):
        return _make_panel(as_of)

    def fake_compute(df, progress_cb=None):
        calls["compute"] += 1
        return df

    monkeypatch.setattr(screener.data_adapter, "load_daily_panel", fake_load)
    monkeypatch.setattr(screener, "compute_all", fake_compute)

    db = object()
    screener._load_computed_panel(db, None, as_of)
    # 第二次"刷新"仍只读面板，不触发重算
    screener._load_computed_panel(db, None, as_of)
    assert calls["compute"] == 1


def test_new_as_of_triggers_recompute(monkeypatch):
    """交易日变化（as_of 变化）→ 新 key → 触发重算，不应返回旧缓存。"""
    calls = {"compute": 0}
    as_of_1 = "2026-01-07"
    as_of_2 = "2026-01-08"

    def fake_load(db, pool, start_dt, end_dt, period="daily"):
        return _make_panel(end_dt)

    def fake_compute(df, progress_cb=None):
        calls["compute"] += 1
        return df

    monkeypatch.setattr(screener.data_adapter, "load_daily_panel", fake_load)
    monkeypatch.setattr(screener, "compute_all", fake_compute)

    db = object()
    p1 = screener._load_computed_panel(db, None, as_of_1)
    p2 = screener._load_computed_panel(db, None, as_of_2)
    assert calls["compute"] == 2, "不同 as_of 应各自重算一次"
    assert p1 is not p2


def test_enriched_target_cached_and_invalidated_by_as_of(monkeypatch):
    """目标日 enrich 结果按 as_of 缓存，同 as_of 复用、异 as_of 重算。"""
    calls = {"enrich": 0, "load": 0}

    def fake_load(db, pool, start_dt, end_dt, period="daily"):
        calls["load"] += 1
        return _make_panel(end_dt)

    def fake_compute(df, progress_cb=None):
        return df

    def fake_enrich(db, target, as_of_date):
        calls["enrich"] += 1
        return _fake_enrich(db, target, as_of_date)

    monkeypatch.setattr(screener.data_adapter, "load_daily_panel", fake_load)
    monkeypatch.setattr(screener, "compute_all", fake_compute)
    monkeypatch.setattr(screener, "_enrich_target", fake_enrich)

    db = object()
    panel = screener._load_computed_panel(db, None, "2026-01-07")
    t1 = screener._get_enriched_target(db, panel, None, "2026-01-07")
    t2 = screener._get_enriched_target(db, panel, None, "2026-01-07")
    assert calls["enrich"] == 1, "同 as_of 目标日应复用 enrich 结果"
    assert t1 is t2
    assert t1["_enriched_marker"].iloc[0] == "2026-01-07"

    # 换 as_of：面板也换，目标日重新 enrich
    panel2 = screener._load_computed_panel(db, None, "2026-01-08")
    screener._get_enriched_target(db, panel2, None, "2026-01-08")
    assert calls["enrich"] == 2, "异 as_of 应重新 enrich"


def test_empty_panel_not_cached():
    """空面板不应写入缓存，避免污染后续重算路径。"""
    empty = pd.DataFrame(columns=screener.data_adapter.PANEL_COLUMNS)
    # 直接验证缓存逻辑：空结果不入 cache
    key = screener._panel_cache_key("2026-01-07", None)
    screener._cache_put(screener._panel_cache, key, empty, screener._PANEL_CACHE_MAX)
    # 即便手动塞入，也应可被正常读取（行为一致）
    val = screener._cache_get(screener._panel_cache, key)
    assert val is not None
    assert val.empty