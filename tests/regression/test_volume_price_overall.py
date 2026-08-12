"""
量价分析「综合判断」增强 防回归测试。

增强背景：综合判断此前仅简单汇总五步信号，未将「位置」与「量价关系」交叉综合，
无法呈现高位放量、低位放量、上涨中继放量、下跌中继放量等典型情景。

修复：_build_overall 依据第五步的 60 日高低点定位 高位/中位/低位，
依据第三步量能活跃度归一化为 放量/缩量/量能平稳，并与趋势交叉归纳出情景。

本测试验证：
1. 高位放量 / 低位放量 / 上涨中继放量 / 下跌中继放量 情景正确生成；
2. overall 返回 position / volume_state / scenario / scenario_meaning 字段；
3. 五步每条均带 meaning 字段（前端鼠标停留展示）。
"""
import pytest
from datetime import datetime

import pandas as pd

from app.services import volume_price_analysis as vpa

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _steps(step5_levels, trend="多头排列", level="显著放量", close=10.0,
           meaning="含义"):
    """构造五步分析 dict，供 _build_overall 消费。

    顺序：位置判断、趋势判断、量能活跃度、量价象限、关键位量能分析。
    第一步不显式给 position，走 _build_overall 的 key-level 兜底推算，以便场景测试控制。
    """
    return [
        {"step": 1, "title": "位置判断", "meaning": meaning},
        {"step": 2, "title": "趋势判断", "trend": trend, "meaning": meaning},
        {"step": 3, "title": "量能活跃度", "level": level, "meaning": meaning},
        {"step": 4, "title": "量价象限", "dominant": "价涨量增", "meaning": meaning},
        {"step": 5, "title": "关键位量能分析", "levels": step5_levels, "meaning": meaning},
    ]


def _real_steps():
    """用真实五步函数跑一份合成行情，返回真实 steps（含 meaning）。"""
    import numpy as np
    n = 90
    dates = pd.date_range(end=datetime.now(), periods=n, freq="B")
    base = np.linspace(8.0, 10.0, n)  # 温和上行
    close = base + np.random.RandomState(0).normal(0, 0.1, n)
    df = pd.DataFrame({
        "date": dates,
        "open": close - 0.05,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": 1_000_000 + np.random.RandomState(1).normal(0, 50_000, n),
        "change_pct": np.random.RandomState(2).normal(0.5, 1.0, n),
        "vol_ratio_5d": np.random.RandomState(3).uniform(1.0, 2.5, n),
        "vol_ma5": [1_100_000] * n,
        "vol_ma10": [1_000_000] * n,
        "ma5": close,
        "ma20": base,
        "ma60": base - 0.2,
        "high_60d": [10.2] * n,
        "low_60d": [7.8] * n,
        "obv": np.cumsum(np.random.RandomState(4).normal(0, 1000, n)),
        "obv_ma5": [0] * n,
    })
    latest = df.iloc[-1]
    return [
        vpa._step1_position(df, latest),
        vpa._step2_trend(df, latest),
        vpa._step3_volume(df, latest),
        vpa._step4_quadrant(df),
        vpa._step5_key_level_volume(df, latest),
    ]


def _levels(high, low):
    return [
        {"name": "60日高点", "value": high, "nearby": False},
        {"name": "60日低点", "value": low, "nearby": False},
    ]


def _test_overall_scenario(step5_levels, trend, level, close, expected_scenario):
    overall = vpa._build_overall(_steps(step5_levels, trend, level, close), close)
    assert overall["scenario"] == expected_scenario, (
        f"期望情景 {expected_scenario}，实际 {overall['scenario']}\n"
        f"position={overall.get('position')} volume_state={overall.get('volume_state')}"
    )
    assert overall["scenario_meaning"], "情景含义不能为空"
    assert overall["position"] in ("高位", "中位", "低位")
    assert overall["volume_state"] in ("放量", "缩量", "量能平稳")


def test_high_position_volume_surge():
    # 收盘接近 60 日高点（ratio>=0.7）且放量
    high, low = 10.0, 6.0
    close = 9.8  # (9.8-6)/4 = 0.95 -> 高位
    _test_overall_scenario(_levels(high, low), "震荡", "显著放量", close, "高位放量")


def test_low_position_volume_surge():
    high, low = 10.0, 6.0
    close = 6.6  # (6.6-6)/4 = 0.15 -> 低位
    _test_overall_scenario(_levels(high, low), "震荡", "显著放量", close, "低位放量")


def test_uptrend_continuation_surge():
    # 多头排列 + 放量 -> 上涨中继放量（优先于位置场景）
    high, low = 10.0, 6.0
    close = 9.0
    _test_overall_scenario(_levels(high, low), "多头排列", "温和放量", close, "上涨中继放量")


def test_downtrend_continuation_surge():
    # 空头排列 + 放量 -> 下跌中继放量
    high, low = 10.0, 6.0
    close = 7.0
    _test_overall_scenario(_levels(high, low), "空头排列", "显著放量", close, "下跌中继放量")


def test_overall_returns_enriched_fields():
    overall = vpa._build_overall(_steps(_levels(10.0, 6.0), "震荡", "显著放量", 9.8), 9.8)
    for key in ("bias", "signals", "summary", "position", "volume_state", "scenario",
                "scenario_meaning", "bias_basis",
                "current_state", "signal_note"):
        assert key in overall, f"overall 缺少字段 {key}"
    assert overall["current_state"], "当前量价状态为空"
    assert overall["current_state"] in overall["summary"], "summary 应包含当前状态片段"
    # 量价分析不再输出方向预判与操作建议（交由三买三卖系统单独给出）
    assert "direction" not in overall, "量价分析不应再输出 direction"
    assert "action" not in overall, "量价分析不应再输出 action"


def test_summary_is_coherent_narrative():
    """综合判断应重塑为连贯叙述：当前状态 → 情景信号解读，不再输出方向预判/操作建议。"""
    overall = vpa._build_overall(
        _steps(_levels(10.0, 6.0), "震荡", "显著放量", 9.8),
        9.8,
    )
    assert "direction" not in overall
    assert "action" not in overall
    # 偏空场景的叙述不得出现「平稳/无明显信号」这类与之矛盾的措辞
    bear = vpa._build_overall(
        _steps(_levels(10.0, 6.0), "空头排列", "显著放量", 7.0),
        7.0,
    )
    assert bear["bias"] == "偏空"
    assert "平稳" not in bear["summary"], f"偏空但叙述出现量价平稳: {bear['summary']}"


def test_low_volume_shrink_scenario_gives_stabling_signals():
    """低位缩量应给出具体可落地的企稳信号与下一步关注点。"""
    note = vpa._scenario_signal_note("低位缩量")
    assert note, "低位缩量企稳信号说明为空"
    for kw in ("企稳信号", "放量阳线", "创新低", "OBV"):
        assert kw in note, f"企稳信号说明缺少关键词 {kw}: {note}"


def test_every_step_has_meaning():
    """真实五步函数每一步都应返回 meaning，供前端鼠标停留展示。"""
    for step in _real_steps():
        assert step.get("meaning"), f"step{step['step']}({step['title']}) 缺少 meaning"


def test_step2_has_quadrant_meanings():
    """量价象限步骤（五步法中的第4步）应为四个量价象限各提供含义，供前端鼠标停留展示。"""
    quad_step = [s for s in _real_steps() if s.get("quadrant_meanings")]
    assert quad_step, "五步法中应存在携带 quadrant_meanings 的量价象限步骤"
    meanings = quad_step[0]["quadrant_meanings"]
    assert set(meanings.keys()) == {"价涨量增", "价涨量缩", "价跌量增", "价跌量缩"}
    for k, v in meanings.items():
        assert v, f"象限 {k} 缺少含义"


def test_compute_position_boundaries():
    def pos(levels, close):
        # _compute_position 期望传入 step5 dict（含 levels 键）
        return vpa._compute_position({"levels": levels}, close)

    assert pos(_levels(10.0, 6.0), 9.8) == "高位"
    assert pos(_levels(10.0, 6.0), 6.6) == "低位"
    assert pos(_levels(10.0, 6.0), 8.0) == "中位"
    # 无关键位数据时降级为中位
    assert pos([], 8.0) == "中位"


def test_compute_volume_state():
    assert vpa._compute_volume_state({"level": "显著放量"}) == "放量"
    assert vpa._compute_volume_state({"level": "温和放量"}) == "放量"
    assert vpa._compute_volume_state({"level": "缩量"}) == "缩量"
    assert vpa._compute_volume_state({"level": "量能平稳"}) == "量能平稳"