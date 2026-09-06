"""7 策略落地（管道 A/B/C）+ 对话路线 + 预算护栏 的单元测试。"""
import numpy as np
import pandas as pd
import pytest


# ── 管道A：底部放量 / 一阳夹三阴 filter 注册与逻辑 ──
class TestPipelineAStrategies:
    def test_bottom_volume_registered(self):
        """底部放量已进注册表且带显式列依赖/画像。"""
        import app.strategy_system.strategies as st  # noqa: F401 触发注册
        from app.strategy_system.registry import registry

        s = registry.get("bottom_volume")
        assert s is not None
        assert "vol_ratio_5d" in s.required_columns
        assert "熊市恐慌" in s.market_regimes
        assert len(registry.all()) == 23  # 23 策略池

    def test_one_yang_three_yin_registered(self):
        import app.strategy_system.strategies as st  # noqa: F401
        from app.strategy_system.registry import registry

        s = registry.get("one_yang_three_yin")
        assert s is not None
        assert s.market_regimes == ["牛市强趋势", "震荡蓄势"]

    def test_bottom_volume_fires_on_bottom_surge(self):
        """持续下跌后放量大阳（长下影）→ 触发。"""
        from app.strategy_system.strategies import _bottom_volume

        n = 26
        closes = np.concatenate([np.linspace(20, 10.4, 24), [11.2, 11.9]])
        opens = closes * 0.99
        highs = np.maximum(opens, closes) * 1.02
        lows = np.minimum(opens, closes) * 0.9  # 长下影
        volumes = np.array([30000] * 24 + [120000, 90000])
        df = pd.DataFrame({"close": closes, "open": opens, "high": highs, "low": lows, "volume": volumes})
        df["momentum_20d"] = df["close"].pct_change(20).fillna(0.0)
        prev_ma5 = df["volume"].shift(1).rolling(5).mean()
        df["vol_ratio_5d"] = (df["volume"] / prev_ma5).fillna(1.0)

        out = _bottom_volume(df, {})
        # 放量日（量比≥3）触发放量反转
        assert bool(out.iloc[24])
        # 后续量能回落则不再触发（信号只在放量日）
        assert not bool(out.iloc[25])

    def test_one_yang_three_yin_fires_on_5day_pattern(self):
        """1 大阳 + 3 小K（不破开盘）+ 第5日突破 → 触发。"""
        from app.strategy_system.strategies import _one_yang_three_yin

        rows = []
        # day1 大阳（实体>2%），day2-4 小K（低点不破 day1 开盘 100、收在实体区间 100~104），day5 突破大阳收盘
        pattern = [
            (100, 105, 99.5, 104, 100000),   # day1 大阳
            (103, 103.8, 101, 101.5, 60000),  # day2 小K(阴)
            (101.5, 102.5, 100.5, 101, 65000),  # day3 小K
            (101, 102, 100.6, 101.8, 62000),   # day4 小K
            (101.8, 106, 101.5, 105.2, 90000),  # day5 阳线突破 day1 收盘 104
        ]
        for i, (o, h, l, c, v) in enumerate(pattern):
            rows.append({"symbol": "X", "open": o, "high": h, "low": l, "close": c, "volume": v,
                         "ma5": 103 if i < 4 else 104, "ma10": 102, "ma20": 101})
        df = pd.DataFrame(rows)
        out = _one_yang_three_yin(df, {})
        assert bool(out.iloc[-1])


# ── 管道B：情绪/事件/预期 辅助信号 ──
class TestPipelineBAuxiliarySignals:
    def _ind(self, n=60):
        closes = np.linspace(20, 10, n)
        closes[-3:] = [10.2, 10.5, 11.0]
        opens = closes * 0.995
        highs = closes * 1.01
        lows = closes * 0.98
        volumes = np.full(n, 30000.0)
        volumes[-1] = 100000.0
        vol_ratio = volumes / 30000.0
        return {
            "n": n, "opens": opens, "closes": closes, "highs": highs, "lows": lows,
            "volumes": volumes, "pct_chgs": np.zeros(n),
            "ma5": closes, "ma8": closes, "ma13": closes, "ma20": closes * 0.99,
            "ma55": closes, "ma60": closes, "ma65": closes,
            "dif": np.zeros(n), "dea": np.zeros(n), "macd_hist": np.zeros(n),
            "volume_ratio": vol_ratio, "short_convergence": np.ones(n),
            "stock_trend": np.full(n, "down", dtype=object),
            "bias60": np.zeros(n), "atr14": np.ones(n), "ma60_slope": np.zeros(n),
        }

    def test_three_new_signals_included(self):
        from app.services.candidate_pool.auxiliary_signal_layer import compute_auxiliary

        out = compute_auxiliary(self._ind(), market_trend="down")
        for key in ("emotion_cycle", "event_driven", "expectation_repricing"):
            assert key in out["details"]
        assert 0 <= out["score"] <= 100

    def test_emotion_overheat_warns(self):
        from app.services.candidate_pool.auxiliary_signal_layer import compute_auxiliary

        ind = self._ind()
        ind["volume_ratio"][-1] = 6.0  # 天量脉冲 → 情绪过热
        out = compute_auxiliary(ind)
        sig = out["details"]["emotion_cycle"]
        assert sig["level"] == "warn"
        assert any("情绪过热" in w for w in out["warnings"])

    def test_event_breakout_confirms(self):
        from app.services.candidate_pool.auxiliary_signal_layer import compute_auxiliary

        ind = self._ind()
        # 放量阳线站上 MA20 → 事件确认突破
        # 注意：ind 里 ma20 基于构造时 closes 快照（其 [n-1]≈11.0*0.99），
        # 故收盘价需抬升到 ma20 之上（>10.89）避免被"跌破 MA20"分支拦截。
        ind["opens"][-1] = 10.0
        ind["closes"][-1] = 11.3
        ind["highs"][-1] = 11.4
        ind["lows"][-1] = 9.95
        ind["volume_ratio"][-1] = 2.0
        out = compute_auxiliary(ind)
        sig = out["details"]["event_driven"]
        assert sig["label"] == "事件确认突破"


# ── 管道C：对话模板与路由 ──
class TestPipelineCDialogue:
    def test_templates_cover_7(self):
        from app.strategy_system.strategy_templates import STRATEGY_TEMPLATES

        assert set(STRATEGY_TEMPLATES) == {
            "chan_theory", "wave_theory", "event_driven", "expectation_repricing",
            "emotion_cycle", "one_yang_three_yin", "bottom_volume",
        }
        for t in STRATEGY_TEMPLATES.values():
            assert t["tools"] and t["steps"] and t.get("constraint")

    def test_route_strategy_keywords(self):
        from app.services.chat_agent_service import _route_strategy

        assert _route_strategy("用缠论看 600519") == "chan_theory"
        assert _route_strategy("底部放量分析 000858") == "bottom_volume"
        assert _route_strategy("情绪周期角度分析") == "emotion_cycle"
        assert _route_strategy("小盘价值") == "small_cap_value"
        assert _route_strategy("随便聊聊") is None

    def test_build_strategy_prompt_fallback(self):
        from app.services.chat_agent_service import _build_strategy_prompt

        assert "缠论" in _build_strategy_prompt("chan_theory")
        assert "MA金叉" in _build_strategy_prompt("ma_golden_cross")  # 存量策略回退 registry


# ── 预算护栏（纯函数段，不写库） ──
class TestBudgetGuardRail:
    def test_limits_defaults(self):
        from app.services.chat_session_service import _budget_limits

        mr, mt, mc = _budget_limits()
        assert mr > 0 and mt > 0 and mc > 0

    def test_charge_budget_round_not_double_counted(self):
        """门禁(计入轮次) + 记账(不重复计轮) 的结构断言：文档化契约。"""
        import inspect

        from app.services.chat_session_service import charge_budget
        sig = inspect.signature(charge_budget)
        params = list(sig.parameters)
        assert "count_round" in params  # 记账时不重复计轮次