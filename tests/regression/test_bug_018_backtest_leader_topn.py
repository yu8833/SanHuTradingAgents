"""
Bug-018 防回归测试：低估值高股息策略在回测（多日面板）中无买入信号

根因：`_low_pe_high_dividend_leader` 的行业龙头选择用 `grp.head(top_n)` 取"行"而非"只股票"。
      筛选侧每个 symbol 只有 1 行，head(top_n) 恰好取到 top_n 只股票；
      回测侧 panel 每个 symbol 有多个交易日行，市值/行业为每股快照逐日广播，
      排序后 head(top_n) 会取到市值最高同一只股票的多行，导致真正的行业龙头多数被漏选，
      且被选中的少数行散落在 warmup 区间 → 正式区间 0 信号，前端提示"在指定区间内未产生买入信号"。

修复：按 symbol 去重后再按行业取市值 TopN 只股票，再把这些股票的全部分日期行标记为候选。

本测试：构造一个多日面板（每只股票 2 个交易日行），验证 top_n=3 时应选中 3 只不同股票
        的全部日期行，且按 PE/PB 过滤掉的股票不被选中。
"""
import pandas as pd
import pytest

from app.strategy_system.strategies import _low_pe_high_dividend_leader

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _build_panel() -> pd.DataFrame:
    """构造多日面板。市值/行业/估值/股息为每股快照（逐日广播），与回测 `_enrich_panel_fundamentals` 一致。"""
    dates = ["2026-01-05", "2026-01-06"]
    rows = []
    for d in dates:
        # 行业 X：A/B/C 通过基础过滤且市值 Top3，D 市值第4（不应选中），E 估值过高（PE/PB 过滤淘汰）
        for sym, mv, pe, pb, dy, yrs in [
            ("000001", 100.0, 10.0, 1.0, 0.05, 5),
            ("000651", 90.0, 10.0, 1.0, 0.05, 5),
            ("002142", 80.0, 10.0, 1.0, 0.05, 5),
            ("000568", 70.0, 10.0, 1.0, 0.05, 5),   # 市值第4，top_n=3 不应选中
            ("000333", 1000.0, 100.0, 5.0, 0.05, 5),  # PE/PB 过高，被基础过滤淘汰
        ]:
            rows.append({
                "symbol": sym,
                "date": d,
                "close": 10.0,
                "pe_ttm": pe,
                "pb": pb,
                "total_mv": mv,
                "div_yield": dy,
                "div_paying_years": yrs,
                "industry": "X",
            })
    return pd.DataFrame(rows)


def test_leader_selects_topn_distinct_symbols_across_dates():
    """top_n=3 时应选中 3 只不同股票的全部分日期行，而非同一只股票的多行。"""
    df = _build_panel()
    leader = _low_pe_high_dividend_leader(df, {"top_n": 3})

    # 选中股票集合
    selected_syms = set(df.loc[leader, "symbol"])
    assert selected_syms == {"000001", "000651", "002142"}, \
        f"行业龙头 Top3 选择错误，实际选中 {selected_syms}（bug-018 复发：head(top_n) 误取同一股票多行）"

    # 每只被选中的股票，其全部日期行都应为 True（回测需覆盖整个区间的买入信号）
    for sym in selected_syms:
        sym_rows_leader = leader[df["symbol"] == sym]
        assert sym_rows_leader.all(), f"{sym} 并非所有交易日都被标记为候选（bug-018 复发）"

    # 市值第4的股票与估值过高的股票不应被选中
    for sym in ["000568", "000333"]:
        assert not leader[df["symbol"] == sym].any(), f"{sym} 不应被选为行业龙头（bug-018 复发）"


def test_leader_single_date_unchanged():
    """单日面板（筛选侧每只股票仅 1 行）行为保持与修复前一致，仍正确选出 Top3。"""
    df = _build_panel()
    single = df[df["date"] == "2026-01-05"].copy()
    leader = _low_pe_high_dividend_leader(single, {"top_n": 3})
    selected_syms = set(single.loc[leader, "symbol"])
    assert selected_syms == {"000001", "000651", "002142"}