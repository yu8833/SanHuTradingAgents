"""
Bug-022 防回归测试：长时全市场回测的技术指标阶段需上报增量进度

根因：`compute_all` 内部（compute_indicators/compute_signals）不报增量进度，
      全市场回测时进度条在 2% 处停留十余分钟，用户误以为卡死。

修复：`compute_all`/`compute_indicators`/`compute_signals` 增加可选 `progress_cb`，
      按分批上报进度（[0,1] 内单调递增），`_load_panel` 将其映射到整体进度。
"""
import pandas as pd
import pytest

from app.strategy_system.indicators import compute_all

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _build_panel(n_symbols: int = 10, n_days: int = 40) -> pd.DataFrame:
    # 400 行 > _INDICATOR_CHUNK_SYMBOLS(300)，确保走分批计算路径以触发进度上报
    rows = []
    for s in range(n_symbols):
        sym = f"{s:06d}"
        for d in range(n_days):
            rows.append({
                "symbol": sym,
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=d),
                "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0 + d * 0.01,
                "volume": 1000,
            })
    return pd.DataFrame(rows)


def test_compute_all_reports_monotonic_progress():
    """compute_all 应按分批上报单调递增的 [0,1] 进度。"""
    panel = _build_panel()
    seen: list[float] = []
    compute_all(panel, progress_cb=lambda p, msg: seen.append(float(p)))
    assert seen, "分批计算应上报至少一次进度"
    assert seen == sorted(seen), "进度应单调递增"
    assert seen[-1] == pytest.approx(1.0), "指标+信号阶段结束进度应到 1.0"


def test_compute_all_without_progress_cb_backward_compatible():
    """不传 progress_cb 时行为不变（screener 等既有调用不受影响）。"""
    panel = _build_panel()
    out = compute_all(panel)
    assert "ma5" in out.columns
    assert "signal_ma5_breakout" in out.columns
    assert len(out) == len(panel)