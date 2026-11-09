"""
Bug-027 防回归测试：超跌反弹回测/筛选口径硬化。

覆盖：
1. 回测评分按「当日横截面」归一化（全局 min/max 会让未来价格影响历史评分）；
2. 评分支持负权重（跌幅因子：跌得越多分越高），且缺失值不因反转而误得满分；
3. 股票池清洗：ST/退市/次新/低流动性剔除；
4. 价格异常清洗：非新股单日 |涨跌|>21% 的行被剔除；
5. 成交口径仅允许 open_t+1（close_t 未来函数在 API 层被拒绝）。
"""
import pandas as pd
import pytest
from pydantic import ValidationError

from app.strategy_system.backtest import _score_series
from app.strategy_system.data_adapter import _sanitize_price_rows
from app.strategy_system.screener import apply_universe_filter

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def test_score_series_uses_daily_cross_section():
    """评分归一化必须按当日横截面，未来日的高值不得影响历史日评分。"""
    df = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06"],
        "symbol": ["A", "B", "A", "B"],
        "x": [1.0, 2.0, 100.0, 3.0],
    })
    scores = _score_series(df, {"x": 1.0})
    # 01-05 横截面：A=1(最低)→0，B=2(最高)→100；与 01-06 的 100 无关
    assert scores.iloc[0] == pytest.approx(0.0)
    assert scores.iloc[1] == pytest.approx(100.0)
    # 01-06 横截面：A=100(最高)→100，B=3→0
    assert scores.iloc[2] == pytest.approx(100.0)
    assert scores.iloc[3] == pytest.approx(0.0)


def test_score_series_negative_weight_and_missing():
    """负权重 = 越低越好；缺失值不因 1-norm 反转而拿到满分。"""
    df = pd.DataFrame({
        "date": ["2026-01-05"] * 3,
        "symbol": ["A", "B", "C"],
        "x": [1.0, 5.0, None],
    })
    scores = _score_series(df, {"x": -1.0})
    assert scores.iloc[0] == pytest.approx(100.0)  # 1 最低 → 分最高
    assert scores.iloc[1] == pytest.approx(0.0)    # 5 最高 → 分最低
    assert scores.iloc[2] == pytest.approx(0.0)    # 缺失 → 0，而非 100


def test_universe_filter_excludes_st_new_and_illiquid():
    """ST/退市/次新/低流动性必须被剔除，正常股票保留。"""
    dates = pd.bdate_range("2026-01-05", periods=70).strftime("%Y-%m-%d").tolist()
    rows = []
    for d in dates:
        rows.extend([
            # 正常股票：长期上市、成交额充足
            {"symbol": "000001", "date": d, "amount": 1e8},
            # ST 股票
            {"symbol": "000002", "date": d, "amount": 1e8},
            # 次新股：只有最近 10 个交易日
            {"symbol": "000003", "date": dates[-10], "amount": 1e8},
            # 低流动性
            {"symbol": "000004", "date": d, "amount": 1e6},
        ])
    panel = pd.DataFrame(rows)
    # 次新股只保留最近若干行
    panel = panel[~((panel["symbol"] == "000003") & (~panel["date"].isin(dates[-10:])))]
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)

    meta = {
        "000001": {"name": "平安银行", "list_date": "1991-04-03", "status": "L", "is_active": True},
        "000002": {"name": "ST海投", "list_date": "1994-01-01", "status": "L", "is_active": True},
        "000003": {"name": "新股科技", "list_date": dates[-10], "status": "L", "is_active": True},
        "000004": {"name": "冷门股", "list_date": "2000-01-01", "status": "L", "is_active": True},
    }
    mask = apply_universe_filter(panel, meta)
    last = panel["date"] == dates[-1]
    allowed = set(panel.loc[mask & last, "symbol"])
    assert allowed == {"000001"}


def test_sanitize_price_rows_drops_abnormal_move():
    """非新股单日 |涨跌|>21% 的脏行必须剔除；上市初期（前 10 行）不剔除。"""
    rows = []
    for i in range(15):
        rows.append({
            "symbol": "000001",
            "date": f"2026-02-{i + 1:02d}",
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1000, "amount": 1e8, "pct_chg": 0.0,
        })
    rows[12]["pct_chg"] = 0.35  # 第 13 行异常（非新股）
    panel = pd.DataFrame(rows)
    cleaned = _sanitize_price_rows(panel)
    assert len(cleaned) == len(panel) - 1
    assert 0.35 not in set(cleaned["pct_chg"])


def test_close_t_is_rejected_by_api_model():
    """close_t 会引入未来函数，API 必须拒绝。"""
    from app.routers.strategy import BacktestRequest

    with pytest.raises(ValidationError):
        BacktestRequest(strategy_id="oversold_bounce", start="2026-01-01",
                        end="2026-03-01", entry_fill="close_t")
    req = BacktestRequest(strategy_id="oversold_bounce", start="2026-01-01",
                          end="2026-03-01", entry_fill="open_t+1")
    assert req.entry_fill == "open_t+1"
