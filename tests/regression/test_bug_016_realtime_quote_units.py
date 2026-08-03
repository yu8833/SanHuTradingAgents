"""
防回归测试：bug-016 AKShare stock_zh_a_minute 单只股票实时查询的单位与聚合错误

问题根因（修复前）：
    1. akshare_adapter.get_realtime_quote_single() 对 stock_zh_a_minute 的 volume 误做 ×100
       实测：stock_zh_a_minute 的 volume 本身就是"股"（当日分钟求和 ≈ 日线 volume）
       而 stock_zh_a_spot_em 的 volume 才是"手"需要 ×100
       两个接口单位不同，原代码用同一套 ×100 逻辑，导致 minute 路径 volume 放大 100 倍

    2. 原代码 last_row = df.iloc[-1] 只取最后一行（单分钟值）
       stock_zh_a_minute 返回当日分钟数据，最后一行只是一分钟的成交
       导致 volume/amount 量级骤降（amount 从千万级降到万级）

    3. 返回字典不含 trade_date 字段
       stocks.py 缓存更新用 `if q.get(key) is not None` 守卫
       源数据 trade_date=None 时跳过不覆盖
       导致 MongoDB market_quotes.trade_date 卡在上一交易日（如 07-31）

修复后契约：
    get_realtime_quote_single() 返回值：
        volume = 当日累计（股），不做 ×100
        amount = 当日累计（元）
        open  = 当日第一行
        high  = 当日 max
        low   = 当日 min
        close = 当日最后一行
        trade_date = 当日交易日 YYYYMMDD（从 day 列提取）
"""
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

_PROJECT_ROOT = "/app"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _make_minute_df(rows: list[dict]) -> pd.DataFrame:
    """构造 stock_zh_a_minute 风格的 DataFrame"""
    return pd.DataFrame(rows)


def _make_minute_df_str(rows: list[dict]) -> pd.DataFrame:
    """构造 stock_zh_a_minute 风格的 DataFrame（所有列为 object/字符串类型）

    模拟 AKShare 真实返回：列 dtype 全是 object，数值以字符串形式存储。
    这是 bug-016 的关键触发条件——sum() 对字符串列做拼接而非数值求和。
    """
    df = pd.DataFrame(rows)
    # 强制转为字符串类型（模拟 AKShare 的真实行为）
    for col in df.columns:
        if col != "day":
            df[col] = df[col].astype(str)
    return df


# 模拟当日分钟数据（2026-08-03 盘中）
_MINUTE_ROWS_TODAY = [
    {"day": "2026-08-03 09:30:00", "open": 14.60, "high": 14.62, "low": 14.58, "close": 14.61, "volume": 50000, "amount": 730500},
    {"day": "2026-08-03 09:31:00", "open": 14.61, "high": 14.65, "low": 14.60, "close": 14.64, "volume": 30000, "amount": 439200},
    {"day": "2026-08-03 14:10:00", "open": 14.62, "high": 14.66, "low": 14.62, "close": 14.63, "volume": 4000, "amount": 58494},
    {"day": "2026-08-03 14:11:00", "open": 14.63, "high": 14.65, "low": 14.63, "close": 14.65, "volume": 12000, "amount": 175862},
]

# 模拟历史日分钟数据（2026-07-31，用于验证只聚合当日）
_MINUTE_ROWS_HISTORY = [
    {"day": "2026-07-31 09:30:00", "open": 14.49, "high": 14.55, "low": 14.48, "close": 14.52, "volume": 80000, "amount": 1161600},
    {"day": "2026-07-31 15:00:00", "open": 14.66, "high": 14.98, "low": 14.65, "close": 14.67, "volume": 60000, "amount": 880200},
]


def _expected_today_volume():
    """当日 volume 求和（股）"""
    return sum(r["volume"] for r in _MINUTE_ROWS_TODAY)  # 50000+30000+4000+12000 = 96000


def _expected_today_amount():
    """当日 amount 求和（元）"""
    return sum(r["amount"] for r in _MINUTE_ROWS_TODAY)  # 730500+439200+58494+175862 = 1404056


@pytest.fixture
def adapter():
    """构造一个跳过 is_available 检查的 AKShareAdapter"""
    from app.services.data_sources.akshare_adapter import AKShareAdapter
    a = AKShareAdapter()
    a.is_available = MagicMock(return_value=True)
    return a


def _patch_minute(df, adapter, monkeypatch):
    """patch AKShare 的 stock_zh_a_minute 和 ThreadPoolExecutor"""
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_minute", lambda **kw: df)


def test_bug_016_volume_not_multiplied_by_100(adapter, monkeypatch):
    """volume 不应被 ×100（stock_zh_a_minute 的 volume 本身是股）"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result is not None, "应返回数据"
    expected_vol = _expected_today_volume()  # 96000
    assert result["volume"] == pytest.approx(expected_vol, rel=1e-6), (
        f"volume 应为当日累计 {expected_vol} 股，实际 {result['volume']}（不应 ×100）"
    )
    # 关键：不应是 96000 × 100 = 9600000
    assert result["volume"] < expected_vol * 10, "volume 被放大了，疑似 ×100 bug"


def test_bug_016_amount_is_daily_sum(adapter, monkeypatch):
    """amount 应为当日累计（元）"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_amt = _expected_today_amount()  # 1404056
    assert result["amount"] == pytest.approx(expected_amt, rel=1e-6), (
        f"amount 应为当日累计 {expected_amt} 元，实际 {result['amount']}"
    )


def test_bug_016_volume_amount_ratio_matches_price(adapter, monkeypatch):
    """volume 和 amount 应自洽：amount/volume ≈ 价格"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    if result["volume"] and result["volume"] > 0:
        ratio = result["amount"] / result["volume"]
        # 均价应在当日 [low, high] 区间内
        assert result["low"] <= ratio <= result["high"], (
            f"amount/volume={ratio} 不在 [{result['low']}, {result['high']}] 区间，单位失配"
        )


def test_bug_016_close_is_last_row(adapter, monkeypatch):
    """close 应为当日最后一行"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result["close"] == pytest.approx(14.65, rel=1e-6), (
        f"close 应为最后一行 14.65，实际 {result['close']}"
    )


def test_bug_016_open_is_first_row(adapter, monkeypatch):
    """open 应为当日第一行"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result["open"] == pytest.approx(14.60, rel=1e-6), (
        f"open 应为第一行 14.60，实际 {result['open']}"
    )


def test_bug_016_high_is_daily_max(adapter, monkeypatch):
    """high 应为当日最高"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_high = max(r["high"] for r in _MINUTE_ROWS_TODAY)  # 14.66
    assert result["high"] == pytest.approx(expected_high, rel=1e-6), (
        f"high 应为当日最高 {expected_high}，实际 {result['high']}"
    )


def test_bug_016_low_is_daily_min(adapter, monkeypatch):
    """low 应为当日最低"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_low = min(r["low"] for r in _MINUTE_ROWS_TODAY)  # 14.58
    assert result["low"] == pytest.approx(expected_low, rel=1e-6), (
        f"low 应为当日最低 {expected_low}，实际 {result['low']}"
    )


def test_bug_016_trade_date_returned(adapter, monkeypatch):
    """返回值应包含 trade_date（YYYYMMDD），修复缓存 trade_date 不更新的问题"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result.get("trade_date") == "20260803", (
        f"trade_date 应为 '20260803'，实际 {result.get('trade_date')}"
    )


def test_bug_016_only_aggregates_today_not_history(adapter, monkeypatch):
    """多日数据时，只聚合最后一行所属交易日，不混入历史数据"""
    rows = _MINUTE_ROWS_HISTORY + _MINUTE_ROWS_TODAY  # 历史在前，今日在后
    df = _make_minute_df(rows)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    # 只应是今日的聚合，不包含 07-31 的数据
    expected_vol = _expected_today_volume()  # 96000，不含历史 140000
    assert result["volume"] == pytest.approx(expected_vol, rel=1e-6), (
        f"volume 应只聚合今日 {expected_vol}，实际 {result['volume']}（疑似混入历史数据）"
    )
    expected_amt = _expected_today_amount()  # 1404056，不含历史
    assert result["amount"] == pytest.approx(expected_amt, rel=1e-6), (
        f"amount 应只聚合今日 {expected_amt}，实际 {result['amount']}（疑似混入历史数据）"
    )
    assert result["trade_date"] == "20260803"


def test_bug_016_high_low_not_single_minute(adapter, monkeypatch):
    """high/low 应是当日 max/min，不是最后一分钟的值"""
    df = _make_minute_df(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    last_row_high = _MINUTE_ROWS_TODAY[-1]["high"]  # 14.65
    last_row_low = _MINUTE_ROWS_TODAY[-1]["low"]  # 14.63
    assert result["high"] > last_row_high, (
        f"high={result['high']} 应大于最后一行 high={last_row_high}（应是当日 max 而非单分钟）"
    )
    assert result["low"] < last_row_low, (
        f"low={result['low']} 应小于最后一行 low={last_row_low}（应是当日 min 而非单分钟）"
    )


def test_bug_016_symbol_prefix_routing(adapter, monkeypatch):
    """验证 sh/sz 前缀路由（600/688 开头走 sh，其余走 sz）"""
    captured = {}

    import akshare as ak

    def _fake_minute(symbol=None, **kw):
        captured["symbol"] = symbol
        return _make_minute_df(_MINUTE_ROWS_TODAY)

    monkeypatch.setattr(ak, "stock_zh_a_minute", _fake_minute)

    # 300902 -> sz
    adapter.get_realtime_quote_single("300902", timeout=10)
    assert captured["symbol"] == "sz300902", f"300902 应走 sz，实际 {captured['symbol']}"

    # 688669 -> sh
    adapter.get_realtime_quote_single("688669", timeout=10)
    assert captured["symbol"] == "sh688669", f"688669 应走 sh，实际 {captured['symbol']}"

    # 600000 -> sh
    adapter.get_realtime_quote_single("600000", timeout=10)
    assert captured["symbol"] == "sh600000", f"600000 应走 sh，实际 {captured['symbol']}"


def test_bug_016_empty_df_returns_none(adapter, monkeypatch):
    """空 DataFrame 应返回 None"""
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_minute", lambda **kw: pd.DataFrame())

    result = adapter.get_realtime_quote_single("300902", timeout=10)
    assert result is None


# ========================================================================
# 关键场景：AKShare 返回的列 dtype 为 object（字符串），必须用 pd.to_numeric 转换
# 这是 bug-016 在生产环境触发的真实根因
# ========================================================================

def test_bug_016_string_dtype_volume_not_concatenated(adapter, monkeypatch):
    """字符串类型列的 volume 应为数值求和，不是字符串拼接"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_vol = _expected_today_volume()  # 96000
    assert result["volume"] == pytest.approx(expected_vol, rel=1e-6), (
        f"字符串列 volume 应为数值求和 {expected_vol}，实际 {result['volume']}（疑似字符串拼接）"
    )
    # 关键：不应是 "5000030000400012000" 这样的超长字符串转成的 inf
    assert result["volume"] < expected_vol * 10, "volume 疑似字符串拼接后溢出"


def test_bug_016_string_dtype_amount_not_concatenated(adapter, monkeypatch):
    """字符串类型列的 amount 应为数值求和，不是字符串拼接"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_amt = _expected_today_amount()  # 1404056
    assert result["amount"] == pytest.approx(expected_amt, rel=1e-6), (
        f"字符串列 amount 应为数值求和 {expected_amt}，实际 {result['amount']}（疑似字符串拼接）"
    )


def test_bug_016_string_dtype_high_low_correct(adapter, monkeypatch):
    """字符串类型列的 high/low 应为数值 max/min"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    expected_high = max(r["high"] for r in _MINUTE_ROWS_TODAY)  # 14.66
    expected_low = min(r["low"] for r in _MINUTE_ROWS_TODAY)  # 14.58
    assert result["high"] == pytest.approx(expected_high, rel=1e-6), (
        f"字符串列 high 应为数值 max {expected_high}，实际 {result['high']}"
    )
    assert result["low"] == pytest.approx(expected_low, rel=1e-6), (
        f"字符串列 low 应为数值 min {expected_low}，实际 {result['low']}"
    )


def test_bug_016_string_dtype_close_open_correct(adapter, monkeypatch):
    """字符串类型列的 close/open 应正确转换"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result["close"] == pytest.approx(14.65, rel=1e-6), (
        f"close 应为 14.65，实际 {result['close']}"
    )
    assert result["open"] == pytest.approx(14.60, rel=1e-6), (
        f"open 应为 14.60，实际 {result['open']}"
    )


def test_bug_016_string_dtype_volume_amount_ratio(adapter, monkeypatch):
    """字符串类型列时 volume/amount 应自洽：amount/volume ≈ 价格"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    if result["volume"] and result["volume"] > 0:
        ratio = result["amount"] / result["volume"]
        assert result["low"] <= ratio <= result["high"], (
            f"amount/volume={ratio} 不在 [{result['low']}, {result['high']}] 区间，单位失配"
        )


def test_bug_016_string_dtype_trade_date(adapter, monkeypatch):
    """字符串类型列时 trade_date 仍应正确提取"""
    df = _make_minute_df_str(_MINUTE_ROWS_TODAY)
    _patch_minute(df, adapter, monkeypatch)

    result = adapter.get_realtime_quote_single("300902", timeout=10)

    assert result["trade_date"] == "20260803"
