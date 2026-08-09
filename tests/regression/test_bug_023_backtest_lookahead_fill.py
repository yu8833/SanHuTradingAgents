"""
Bug-023 防回归测试：回测 open_t+1 成交存在未来函数（当盘信号当日开盘成交）

根因：`_simulate_portfolio` 用 `_price_for(row, "buy"/"sell", "open_t+1")` 取
      当前行的 open，即"当日开盘"。但策略信号（RSI、MA 金叉/死叉等）都依赖
      当日 close 计算。于是出现：
        - 买入：用当日收盘信号在当日开盘成交（开盘时无法预知收盘）→ 买入价过低，
          系统性高估反转策略收益（超跌反弹年化虚高至 700%+ 即由此而来）。
        - 卖出：用当日收盘信号在当日开盘卖出 → 卖出价过高，同样高估收益。
        - 止损/止盈：用当日 low/high 判定触发，却用当日开盘价成交 → 已知当日
          最低/最高价后再用更早的开盘价结算，对止损/止盈都系统性有利。

修复：
  - open_t+1 语义改为"T 日收盘信号 → T+1 日开盘执行"，把信号按每只股票时间
    序列后移一个交易日（_shift_signal_to_execute）。
  - 止损/止盈改为在触发价（stop/tp 价）成交并扣滑点，不再用当日开盘价。

本测试：构造"当日收盘大涨/大跌产生信号"的 panel，验证 open_t+1 下买卖都落在
      下一个交易日的开盘价，而非信号当日开盘价。
"""
import pandas as pd
import pytest

from app.strategy_system.backtest import _simulate_portfolio, StrategyBtConfig

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _config(**kw) -> StrategyBtConfig:
    base = dict(
        strategy_id="oversold_bounce",
        start="2026-01-05",
        end="2026-01-07",
        entry_fill="open_t+1",
        exit_fill="open_t+1",
        slippage_bps=5.0,
        max_positions=10,
        initial_capital=1_000_000.0,
        as_dict={"start": "2026-01-05", "end": "2026-01-07"},
    )
    base.update(kw)
    return StrategyBtConfig(**base)


def _panel(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _run(panel, entry_dates, exit_dates=(), **cfg_kw):
    entry = pd.Series(panel["date"].isin(entry_dates), index=panel.index)
    exit_mask = pd.Series(panel["date"].isin(exit_dates), index=panel.index)
    scores = pd.Series(100.0, index=panel.index)
    config = _config(**cfg_kw)
    return _simulate_portfolio(
        panel, entry, exit_mask, scores, config,
        "2026-01-05", "2026-01-07", db=None,
    )


def test_buy_executes_at_next_open_not_signal_day_open():
    """买入信号在 T 日收盘产生，open_t+1 应在 T+1 日开盘成交。"""
    # 01-06 收盘大涨（12 vs 开盘 10.2），若用当日开盘成交会白赚 12/10.2 的日内涨幅。
    panel = _panel([
        {"symbol": "000001", "date": "2026-01-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0,
         "volume": 1000, "amount": 10000, "pct_chg": 0.0, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-06", "open": 10.2, "high": 12.5, "low": 10.1, "close": 12.0,
         "volume": 1000, "amount": 12000, "pct_chg": 0.2, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-07", "open": 13.0, "high": 13.5, "low": 12.8, "close": 13.0,
         "volume": 1000, "amount": 13000, "pct_chg": 0.083, "name": "测试股"},
    ])
    sim = _run(panel, entry_dates=["2026-01-06"])  # 信号在 01-06 收盘产生
    assert sim is not None

    # 买入信号 01-06 → 01-07 开盘建仓，随后期末（01-07）平仓，故仅一笔 end 交易
    assert len(sim["trades"]) == 1, f"应恰好一笔交易，实际 {len(sim['trades'])}"
    t = sim["trades"][0]
    # 关键断言：买入日应为 01-07（信号次日开盘），而非信号当日 01-06
    assert t["entry_date"] == "2026-01-07", \
        f"open_t+1 买入应在信号次日开盘（01-07），实际 {t['entry_date']}（未来函数：当日开盘成交）"
    # 买入价应为 01-07 开盘价(13.0) 加滑点，而非 01-06 开盘价(10.2)
    assert t["entry_price"] == pytest.approx(13.0 * (1 + 0.0005), rel=1e-4), \
        f"买入价应为 01-07 开盘价加滑点，实际 {t['entry_price']}（未来函数：买在信号日开盘）"


def test_sell_executes_at_next_open_not_signal_day_open():
    """卖出信号在 T 日收盘产生，open_t+1 应在 T+1 日开盘成交。"""
    # 01-06 收盘下跌（13 vs 开盘 14），若在当日开盘卖出可躲过当日跌幅 → 高估收益。
    panel = _panel([
        {"symbol": "000001", "date": "2026-01-05", "open": 14.0, "high": 14.5, "low": 13.8, "close": 14.0,
         "volume": 1000, "amount": 14000, "pct_chg": 0.0, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-06", "open": 14.0, "high": 14.2, "low": 12.9, "close": 13.0,
         "volume": 1000, "amount": 13500, "pct_chg": -0.071, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-07", "open": 12.5, "high": 12.8, "low": 12.2, "close": 12.5,
         "volume": 1000, "amount": 12500, "pct_chg": -0.038, "name": "测试股"},
    ])
    # 买入信号 01-05 → 01-06 开盘买入；卖出信号 01-06 → 应在 01-07 开盘卖出
    sim = _run(panel, entry_dates=["2026-01-05"], exit_dates=["2026-01-06"])
    assert sim is not None

    exits = [t for t in sim["trades"] if t["exit_reason"] == "exit_signal"]
    assert len(exits) == 1, f"应恰好一笔信号卖出，实际 {len(exits)}"
    t = exits[0]
    assert t["entry_date"] == "2026-01-06", f"买入应在 01-06 开盘，实际 {t['entry_date']}"
    # 关键断言：卖出日应为 01-07（信号次日开盘），而非信号当日 01-06
    assert t["exit_date"] == "2026-01-07", \
        f"open_t+1 卖出应在信号次日开盘（01-07），实际 {t['exit_date']}（未来函数：当日开盘卖出）"
    assert t["exit_price"] == pytest.approx(12.5 * (1 - 0.0005), rel=1e-4), \
        f"卖出价应为 01-07 开盘价扣滑点，实际 {t['exit_price']}"


def test_stop_loss_fills_at_stop_price_not_day_open():
    """止损盘中触发（当日 low 击穿），应在止损价成交，而非当日开盘价。"""
    stop_pct = 0.1
    # 买入信号 01-05 → 在 01-06 开盘成交（open_t+1），成交价 = 01-06 开盘 10.2 加滑点。
    # 01-06 盘中下探 8.8，但当日买入尚未建仓（买入在卖出判定之后），故不触发；
    # 01-07 盘中 low 8.7 击穿止损线（基于实际成交价计算），应在止损价成交。
    # 若按当日开盘价 9.0 卖出，会躲过 8.7 的跌幅，系统性高估收益（未来函数）。
    panel = _panel([
        {"symbol": "000001", "date": "2026-01-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0,
         "volume": 1000, "amount": 10000, "pct_chg": 0.0, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-06", "open": 10.2, "high": 10.3, "low": 8.8, "close": 9.2,
         "volume": 1000, "amount": 9500, "pct_chg": -0.08, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-07", "open": 9.0, "high": 9.1, "low": 8.7, "close": 8.8,
         "volume": 1000, "amount": 9000, "pct_chg": -0.043, "name": "测试股"},
    ])
    sim = _run(panel, entry_dates=["2026-01-05"], stop_loss_pct=stop_pct)
    assert sim is not None

    stops = [t for t in sim["trades"] if t["exit_reason"] == "stop_loss"]
    assert len(stops) == 1, f"应恰好一笔止损，实际 {len(stops)}"
    t = stops[0]
    # 买入价：01-06 开盘 10.2 加滑点（信号 01-05 → 次日开盘成交）
    actual_entry = 10.2 * (1 + 0.0005)
    assert t["entry_price"] == pytest.approx(actual_entry, rel=1e-4)
    # 止损成交价 = 基于实际成交价的止损线 扣滑点，而非当日开盘价
    stop_line = actual_entry * (1 - stop_pct)
    expected = stop_line * (1 - 0.0005)
    assert t["exit_price"] == pytest.approx(expected, rel=1e-4), \
        f"止损应在止损价成交（{expected:.4f}），实际 {t['exit_price']}（未来函数：用当日开盘价高估）"