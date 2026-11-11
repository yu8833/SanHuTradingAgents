"""环境闸门（gate_service）单元测试。

覆盖：情绪周期阶段推导（移植自 Emotion.vue 的规则）、
8 画像 × 7 阶段闸门矩阵、数据缺失降级。
"""
import pytest

from app.services.cockpit.gate_service import derive_emotion_phase, derive_gate
from app.strategy_system.market_portrait import PORTRAIT_ADVICE, PORTRAIT_NAMES

PHASES = ("冰点期", "退潮期", "分歧期", "修复期", "启动期", "发酵期", "高潮期")
STRONG = ("牛市普涨", "牛市强趋势")
WEAK = ("熊市阴跌", "熊市恐慌")
GREEN_PHASES = ("发酵期", "高潮期", "启动期", "修复期")


class TestDeriveEmotionPhase:
    def test_missing_today(self):
        r = derive_emotion_phase(None, None)
        assert r["label"] is None

    def test_ice_point(self):
        r = derive_emotion_phase({"zt": 20, "dt": 25, "zb": 0}, None)
        assert r["label"] == "冰点期"

    def test_ebb_by_break_rate(self):
        r = derive_emotion_phase({"zt": 50, "dt": 0, "zb": 0, "break_rate": 0.35}, {"zt": 100})
        assert r["label"] == "退潮期"

    def test_ebb_by_limit_down(self):
        r = derive_emotion_phase({"zt": 50, "dt": 12, "zb": 0, "break_rate": 0.1}, {"zt": 100})
        assert r["label"] == "退潮期"

    def test_divergence_derives_break_rate_from_zb(self):
        # 未传 break_rate 时由 zb/(zt+zb) 推导：50/100=0.5 ≥ 0.35
        r = derive_emotion_phase({"zt": 50, "zb": 50, "dt": 0}, None)
        assert r["label"] == "分歧期"

    def test_divergence_by_prev_shrink(self):
        r = derive_emotion_phase({"zt": 40, "zb": 0, "dt": 0, "break_rate": 0.1}, {"zt": 60})
        assert r["label"] == "分歧期"

    def test_climax_by_zt(self):
        r = derive_emotion_phase({"zt": 120, "zb": 10, "dt": 0}, None)
        assert r["label"] == "高潮期"

    def test_climax_by_boards(self):
        r = derive_emotion_phase({"zt": 50, "zb": 10, "dt": 0, "max_boards": 6}, None)
        assert r["label"] == "高潮期"

    def test_fermentation(self):
        # seal_rate = 70/80 = 0.875 ≥ 0.65
        r = derive_emotion_phase({"zt": 70, "zb": 10, "dt": 0}, None)
        assert r["label"] == "发酵期"

    def test_repair(self):
        r = derive_emotion_phase({"zt": 45, "zb": 0, "dt": 0}, {"zt": 40})
        assert r["label"] == "修复期"

    def test_startup(self):
        r = derive_emotion_phase({"zt": 35, "zb": 0, "dt": 0}, {"zt": 35})
        assert r["label"] == "启动期"

    def test_explicit_break_rate_respected_over_zb(self):
        # zb 推导仅 0.09，但显式 break_rate=0.4 优先 → 分歧期
        r = derive_emotion_phase({"zt": 50, "zb": 5, "dt": 0, "break_rate": 0.4}, None)
        assert r["label"] == "分歧期"


class TestDeriveGate:
    @pytest.mark.parametrize("portrait", PORTRAIT_NAMES)
    @pytest.mark.parametrize("phase", PHASES)
    def test_full_matrix(self, portrait, phase):
        r = derive_gate(portrait, phase)
        if portrait in WEAK or phase == "冰点期":
            assert r["gate"] == "red", (portrait, phase)
            assert r["position_hint"] == "0~2 成（观察仓）"
        elif portrait in STRONG and phase in GREEN_PHASES:
            assert r["gate"] == "green", (portrait, phase)
            assert r["position_hint"] == PORTRAIT_ADVICE[portrait]
        else:
            assert r["gate"] == "yellow", (portrait, phase)
        assert r["gate"] in ("green", "yellow", "red")
        assert r["label"] and r["hint"] and r["position_hint"]
        assert r["degraded"] is False

    def test_ebb_hint(self):
        r = derive_gate("震荡蓄势", "退潮期")
        assert r["gate"] == "yellow"
        assert "临近触发" in r["hint"]

    def test_high_volatility_hint(self):
        r = derive_gate("高波动市", "启动期")
        assert r["gate"] == "yellow"
        assert "高波动市" in r["hint"]

    def test_missing_portrait_degrades_to_yellow(self):
        r = derive_gate(None, "发酵期")
        assert r["gate"] == "yellow"
        assert r["degraded"] is True
        assert "画像数据缺失" in r["degrade_note"]

    def test_missing_phase_degrades_but_keeps_portrait_rule(self):
        r = derive_gate("熊市阴跌", None)
        assert r["gate"] == "red"
        assert r["degraded"] is True
        assert "情绪数据缺失" in r["degrade_note"]

    def test_missing_phase_strong_portrait_stays_yellow(self):
        r = derive_gate("牛市强趋势", None)
        assert r["gate"] == "yellow"
        assert r["degraded"] is True
