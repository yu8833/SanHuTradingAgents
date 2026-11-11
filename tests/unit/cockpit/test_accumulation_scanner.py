"""积累区扫描器（_select_candidates 纯函数）单元测试。

覆盖：入池五条件的边界、ST/次新剔除、触发价口径、横盘天数与距离计算。
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.services.cockpit.accumulation_scanner import ACCUM_DEFAULTS, _select_candidates

P = ACCUM_DEFAULTS
ROWS = 100  # ≥ min_panel_rows(80)


def _panel(symbol: str = "000001", rows: int = ROWS, **overrides) -> pd.DataFrame:
    """构造默认满足全部入池条件的单票面板，可按列覆盖制造违规。"""
    start = datetime(2025, 1, 1)
    data = {
        "symbol": [symbol] * rows,
        "date": [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(rows)],
        "close": [10.0] * rows,
        "high": [11.0] * rows,
        "low": [9.5] * rows,
        "amount": [2e8] * rows,
        # 振幅：前段 4.0、近 15 日 2.0 → 收敛比 2/3.5 ≈ 0.571 ≤ 0.6
        "amplitude": [4.0] * (rows - P["converge_days"]) + [2.0] * P["converge_days"],
        # 波动率：历史 0.5、当前 0.2 → 250 日分位 0 < 0.30
        "annual_vol_20d": [0.5] * (rows - 1) + [0.2],
        "ma5": [10.0] * rows,
    }
    for k, v in overrides.items():
        data[k] = v
    return pd.DataFrame(data)


INFO = {"000001": {"name": "平安银行", "industry": "银行"}}


def test_happy_path_candidate_fields():
    cands = _select_candidates(_panel(), INFO)
    assert len(cands) == 1
    c = cands[0]
    assert c["code"] == "000001"
    assert c["name"] == "平安银行"
    assert c["industry"] == "银行"
    # 横盘天数：恒定收盘 → 最近一次"创新低"就是当日 → 0，下限取 n_short=20
    assert c["sideways_days"] == 20
    assert c["volatility_pctile"] == 0.0
    assert c["converge_ratio"] == pytest.approx(2.0 / 3.5, abs=1e-4)
    assert c["avg_amount_20d"] == 2e8
    assert c["avg_amount_5d"] == 2e8
    # 触发价：20/60 日高点相等 → 取 high_20d 口径
    assert c["trigger_price"] == 11.0
    assert c["trigger_basis"] == "high_20d"
    assert c["range_low"] == 9.5
    assert c["close"] == 10.0
    assert c["ma5"] == 10.0
    assert c["distance_to_trigger"] == pytest.approx(10.0 / 11.0 - 1, abs=1e-4)


def test_min_panel_rows_boundary():
    """面板行数 < 80 剔除次新；恰好 80 行放行。"""
    assert _select_candidates(_panel(rows=79), INFO) == []
    assert len(_select_candidates(_panel(rows=80), INFO)) == 1


@pytest.mark.parametrize("name", ["ST平安", "*ST平安", "退市平安"])
def test_st_and_delisted_filtered(name):
    assert _select_candidates(_panel(), {"000001": {"name": name, "industry": "银行"}}) == []


def test_condition1_new_low_rejected():
    """近 20 日收盘跌破前 40 日旧低（容差外）→ 拒绝。"""
    close = [10.0] * ROWS
    close[90] = 10.0 * (P["no_new_low_tolerance"] - 0.02)  # 容差外下探
    assert _select_candidates(_panel(close=close), INFO) == []


def test_condition1_tolerance_boundary():
    """容差边界：min20 == 旧低*0.995 恰好放行，再低一分钱拒绝。"""
    close = [10.0] * ROWS
    close[90] = 10.0 * P["no_new_low_tolerance"]  # 恰好等于阈值
    assert len(_select_candidates(_panel(close=close), INFO)) == 1
    close[90] = 10.0 * P["no_new_low_tolerance"] - 0.01
    assert _select_candidates(_panel(close=close), INFO) == []


def test_condition2_high_vol_percentile_rejected():
    """当前波动率处于历史最高位（分位≈1）→ 拒绝。"""
    vol = [0.2] * (ROWS - 1) + [0.5]
    assert _select_candidates(_panel(annual_vol_20d=vol), INFO) == []


def test_condition2_insufficient_vol_samples_skipped():
    """波动率有效样本 < 60 → 跳过（无法计算分位）。"""
    vol = [None] * (ROWS - 50) + [0.5] * 49 + [0.2]
    assert _select_candidates(_panel(annual_vol_20d=vol), INFO) == []


def test_condition3_no_converge_rejected():
    """振幅无收敛（比率 1.0 > 0.6）→ 拒绝。"""
    assert _select_candidates(_panel(amplitude=[4.0] * ROWS), INFO) == []


def test_condition4_illiquid_rejected():
    """20 日日均成交额 < 1 亿 → 拒绝。"""
    assert _select_candidates(_panel(amount=[5e7] * ROWS), INFO) == []


def test_trigger_basis_prefers_tighter_60d():
    """前段（60 日窗口前 40 日）高点更紧 → trigger_basis=high_60d。"""
    high = [11.0] * ROWS
    high[ROWS - 5] = 11.5  # 近 20 日拉高至 11.5，前段高点仍 11.0 → 取更紧的 11.0
    cands = _select_candidates(_panel(high=high), INFO)
    assert len(cands) == 1
    assert cands[0]["trigger_price"] == 11.0
    assert cands[0]["trigger_basis"] == "high_60d"


def test_sideways_days_counts_from_last_new_low():
    """横盘天数 = 距最近一次收盘创 60 日新低的交易日数（下限 20）。"""
    # 最近一次新低出现在 25 个交易日前（index 74），旧低即该低点
    close = [10.0] * ROWS
    close[ROWS - 26] = 8.96  # 窗口最低；min20=10.0 ≥ 8.96*0.995 → 条件一通过
    cands = _select_candidates(_panel(close=close), INFO)
    assert len(cands) == 1
    assert cands[0]["sideways_days"] == 25


def test_sideways_days_floor_is_short_window():
    """近期才创新低（10 日前）→ 横盘天数按下限取 20。"""
    close = [10.0] * ROWS
    close[60] = 9.0  # 前段旧低
    close[ROWS - 10] = 8.96  # 10 日前创新低，8.96 ≥ 9.0*0.995 → 条件一通过
    cands = _select_candidates(_panel(close=close), INFO)
    assert len(cands) == 1
    assert cands[0]["sideways_days"] == 20
