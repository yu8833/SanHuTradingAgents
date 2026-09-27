"""
统一日期工具 防回归测试。

覆盖:
1. date_utils.normalize_date / compact_date / parse_date:date/datetime/YYYYMMDD/YYYY-MM-DD/含 / 与 . 分隔、
   非法/None/边界值(如 20260230);
2. 五处旧工具函数"行为等价"委托(各保留自身约定):
   - stock_quadrant_analysis._dash/_compact/_today
   - board_quadrant_analysis._dash
   - tushare_sync_service._norm_date(非法→空串)/_compact_date(/ 容错+截断回退)
   - trade_calendar_service._norm
   - trading_time._parse_date_arg(非法→抛 TypeError)
"""
from datetime import date, datetime

import pytest

pytestmark = [pytest.mark.unit]


# ── date_utils 统一工具 ──
def test_normalize_date_variants():
    from app.utils.date_utils import normalize_date

    assert normalize_date(date(2026, 9, 24)) == "2026-09-24"
    assert normalize_date(datetime(2026, 9, 24, 15, 30)) == "2026-09-24"
    assert normalize_date("20260924") == "2026-09-24"
    assert normalize_date("2026-09-24") == "2026-09-24"
    assert normalize_date("2026/09/24") == "2026-09-24"
    assert normalize_date("2026.09.24") == "2026-09-24"


def test_normalize_date_invalid_returns_none():
    from app.utils.date_utils import normalize_date

    assert normalize_date(None) is None
    assert normalize_date("") is None
    assert normalize_date("abc") is None
    assert normalize_date("2026-02-30") is None  # 非法日历日
    assert normalize_date("2026093") is None     # 7 位


def test_compact_date():
    from app.utils.date_utils import compact_date

    assert compact_date("2026-09-24") == "20260924"
    assert compact_date(date(2026, 9, 24)) == "20260924"
    assert compact_date("2026/09/24") == "20260924"
    assert compact_date("bad") is None


def test_parse_date():
    from app.utils.date_utils import parse_date

    assert parse_date("20260924") == date(2026, 9, 24)
    assert parse_date("2026-09-24") == date(2026, 9, 24)
    assert parse_date(None) is None
    assert parse_date("2026-13-01") is None


# ── 五处旧工具"行为等价"委托 ──
def test_stock_quadrant_dash_compact_today(monkeypatch):
    import app.services.stock_quadrant_analysis as sq

    assert sq._dash("20260924") == "2026-09-24"
    assert sq._dash("2026-09-24") == "2026-09-24"
    assert sq._dash("bad") == "bad"          # 非法回退截断(原约定)
    assert sq._compact("2026-09-24") == "20260924"
    assert sq._compact("20260924") == "20260924"
    # _today 委托北京时区今日(与原来 datetime.now(BEIJING) 一致)
    assert sq._today() == datetime.now().strftime("%Y-%m-%d")


def test_board_quadrant_dash():
    import app.services.board_quadrant_analysis as bq

    assert bq._dash("20260924") == "2026-09-24"
    assert bq._dash("2026-09-24") == "2026-09-24"


def test_tushare_norm_and_compact_date():
    import app.worker.tushare_sync_service as ts

    assert ts._norm_date("20260924") == "2026-09-24"
    assert ts._norm_date("2026-09-24") == "2026-09-24"
    assert ts._norm_date(None) == ""          # 保留空串约定
    assert ts._norm_date("bad") == ""          # 非法→空串(委托统一语义)
    assert ts._compact_date("2026-09-24") == "20260924"
    assert ts._compact_date("2026/09/24") == "20260924"   # / 容错
    assert ts._compact_date("20260924") == "20260924"
    assert ts._compact_date("bad") == "bad"    # 截断回退


def test_trade_calendar_norm():
    import app.services.trade_calendar_service as tcs

    assert tcs._norm("20260924") == "2026-09-24"
    assert tcs._norm("2026-09-24") == "2026-09-24"
    assert tcs._norm(date(2026, 9, 24)) == "2026-09-24"
    assert tcs._norm(datetime(2026, 9, 24, 10, 0)) == "2026-09-24"
    assert tcs._norm("2026/09/24") == "2026-09-24"
    assert tcs._norm(None) == "None"           # 原 str→截断约定


def test_trading_time_parse_date_arg():
    import app.utils.trading_time as tt

    assert tt._parse_date_arg("20260924") == date(2026, 9, 24)
    assert tt._parse_date_arg("2026-09-24") == date(2026, 9, 24)
    assert tt._parse_date_arg(date(2026, 9, 24)) == date(2026, 9, 24)
    with pytest.raises(TypeError):
        tt._parse_date_arg("bad")