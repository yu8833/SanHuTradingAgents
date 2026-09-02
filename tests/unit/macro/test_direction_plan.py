"""方向基准（5.2）+ 计划编排（5.3/5.4）单元测试。

对应设计文档 `docs/design/war-room-direction-plan.md`：
  - 5.2 当日方向基准：状态四态（偏多/偏空/中性{观望}/数据不足）+ 低置信度锁定观望 + 锁定时间戳；
  - 5.3 计划生成流水线：每段产出「扫描到多少 / 规则 / 保留多少 / 过滤多少 / 原因」的审计痕迹；
  - 5.4 来源标签：候选计划带 source{type, ref, label}，且不自动落库（自动生成≠自动下单）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.macro import macro_service as ms
from app.services import plan_generation_service as pgs


# ---------------------------------------------------------------------------
# 5.2 当日方向基准（basis）
# ---------------------------------------------------------------------------
class TestDirectionBasis:
    def _basis(self, direction=None, confidence=0, score=0):
        rule = {"direction": direction, "confidence": confidence,
                "score": score, "signals": []}
        return ms._build_basis(rule, datetime.now(timezone.utc))

    def test_bull_high_conf(self):
        b = self._basis("偏多", 72, 4)
        assert b["status"] == "偏多"
        assert b["low_confidence"] is False
        assert b["confidence_threshold"] == ms.CONFIDENCE_THRESHOLD

    def test_bear_high_conf(self):
        b = self._basis("偏空", 66, -5)
        assert b["status"] == "偏空"
        assert b["low_confidence"] is False

    def test_bull_low_conf_forced_watch(self):
        """偏多但置信度低于阈值 → 强摘为「中性(观望)」，标记低置信。"""
        b = self._basis("偏多", ms.CONFIDENCE_THRESHOLD - 1, 4)
        assert b["status"] == "中性(观望)"
        assert b["low_confidence"] is True

    def test_missing_direction_data_insufficient(self):
        b = self._basis(None, 0, 0)
        assert b["status"] == "数据不足"

    def test_has_locked_at(self):
        b = self._basis("偏多", 70, 3)
        assert b["locked_at"] is not None

    def test_direction_status_matrix(self):
        # 直接测四态判定函数（权威口径）
        assert ms._direction_status("偏多", 80) == "偏多"
        assert ms._direction_status("偏空", 80) == "偏空"
        assert ms._direction_status("中性", 80) == "中性(观望)"
        assert ms._direction_status("偏多", 10) == "中性(观望)"  # 低置信
        assert ms._direction_status(None, 0) == "数据不足"


# ---------------------------------------------------------------------------
# 5.3 计划生成流水线：审计痕迹 + 方向标签
# ---------------------------------------------------------------------------
class TestPlanGenerationAudit:
    def test_audit_record_shape(self):
        """每段审计痕迹含 step/scanned/rule/kept/dropped/reasons。"""
        a = pgs._audit("行业", scanned=28, rule="主题命中 + 偏空剔除高风险行业",
                       kept=6, dropped=22, reasons=["2 个高风险行业被剔除"])
        assert a["step"] == "行业"
        assert a["scanned"] == 28
        assert a["kept"] == 6
        assert a["dropped"] == 22
        assert a["reasons"] and isinstance(a["reasons"], list)

    def test_direction_tag_uses_basis(self):
        """方向标注优先取宏观基准四态（低置信 → 观望）。"""
        assert pgs._direction_tag("偏空", {"status": "中性(观望)"}) == "中性(观望)"
        assert pgs._direction_tag("偏空", {"status": "偏空"}) == "偏空"
        assert pgs._direction_tag("偏空", None) == "偏空"