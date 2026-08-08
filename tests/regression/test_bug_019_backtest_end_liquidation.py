"""
Bug-019 防回归测试：回测期末强制平仓价错误使用买入价

根因：`_simulate_portfolio` 的期末强制平仓逻辑中，`px = pos["entry_price"]`，
      直接把建仓买入价当作平仓成交价，导致买入价 == 卖出价、期末盈亏恒为 0，
      total_return 完全失真（无法反映持仓在回测末期的真实价格变动）。

修复：期末强制平仓改为取"最后交易日的收盘价"并扣除卖出滑点，
      与盘中卖出 `_price_for(..., "sell", ...)` 口径一致。

本测试：构造一个仅在首日买入、且无任何卖出信号、一直持有到期末的 panel，
        验证期末平仓的 exit_reason=="end"、exit_price 应为最后交易日收盘价、
        且不等于买入价（股票价格在区间内有变动时）。
"""
import pandas as pd
import pytest

from app.strategy_system.backtest import _simulate_portfolio, StrategyBtConfig

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _build_panel() -> pd.DataFrame:
    """构造一只股票 3 个交易日，价格从 10 → 12 → 14 的 panel。"""
    rows = [
        {"symbol": "000001", "date": "2026-01-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0,
         "volume": 1000, "amount": 10000, "pct_chg": 0.0, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-06", "open": 10.2, "high": 12.5, "low": 10.1, "close": 12.0,
         "volume": 1000, "amount": 12000, "pct_chg": 0.2, "name": "测试股"},
        {"symbol": "000001", "date": "2026-01-07", "open": 12.2, "high": 14.5, "low": 12.0, "close": 14.0,
         "volume": 1000, "amount": 14000, "pct_chg": 0.1667, "name": "测试股"},
    ]
    return pd.DataFrame(rows)


def _make_entry_mask(df: pd.DataFrame) -> pd.Series:
    """只在首日产生买入信号的 mask。"""
    return pd.Series(df["date"] == "2026-01-05", index=df.index)


def test_end_liquidation_uses_last_close_not_entry_price():
    """期末强制平仓价应使用最后交易日收盘价，而非买入价。"""
    df = _build_panel()
    entry = _make_entry_mask(df)
    exit_mask = pd.Series(False, index=df.index)  # 无卖出信号 → 一直持有到期末
    scores = pd.Series(100.0, index=df.index)
    config = StrategyBtConfig(
        strategy_id="low_pe_high_div_leader",
        start="2026-01-05",
        end="2026-01-07",
        entry_fill="open_t+1",
        exit_fill="open_t+1",
        slippage_bps=5.0,
        max_positions=10,
        initial_capital=1_000_000.0,
        as_dict={
            "start": "2026-01-05",
            "end": "2026-01-07",
        },
    )

    sim = _simulate_portfolio(df, entry, exit_mask, scores, config, "2026-01-05", "2026-01-07", db=None)

    assert sim is not None
    # 期末持仓应产生一笔 end 平仓交易
    end_trades = [t for t in sim["trades"] if t["exit_reason"] == "end"]
    assert len(end_trades) == 1, f"应恰好一笔期末平仓，实际 {len(end_trades)}"

    t = end_trades[0]
    # 卖出日期应为最后交易日
    assert t["exit_date"] == "2026-01-07", f"期末平仓应在最后交易日，实际 {t['exit_date']}"
    # 卖出价应为最后交易日收盘价(14.0)扣减卖出滑点(0.05% = 0.0005)，而非买入价(10.0)
    assert t["exit_price"] == pytest.approx(14.0 * (1 - 0.0005), rel=1e-4), \
        f"期末平仓价应为最后收盘价扣滑点，实际 {t['exit_price']}（bug-019 复发：误用买入价）"
    # 关键断言：卖出价 ≠ 买入价
    assert t["exit_price"] != t["entry_price"], \
        f"期末平仓价 == 买入价 ({t['entry_price']})，bug-019 复发"