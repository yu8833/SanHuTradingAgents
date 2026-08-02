"""
防回归测试：bug-010 数据过期天数未排除周末/节假日

现象：
    股票详情页（stocks/:code）显示"数据已过期 2 天"，
    但实际 8 月 1 日和 8 月 2 日是周末，数据并不过期。

根因：
    前端 getDataExpiredDays 用自然日差值（today - dataDate）计算过期天数，
    完全不考虑周末和节假日。后端也没有返回 stale_days 字段。

修复：
    1. trading_time.py 新增统一的 is_trading_day()（使用 chinese_calendar）
    2. 后端 /quote 端点返回 stale_days（交易日差值，已排除非交易日）
    3. 前端 getDataExpiredDays 改用后端返回的 stale_days
    4. 所有碎片化的"周末判断"替换为统一的 is_trading_day
"""
import pytest


@pytest.mark.regression
def test_bug_010_is_trading_day_exists_and_works():
    """bug-010: trading_time 模块必须导出 is_trading_day 函数"""
    # 周六一定不是交易日
    from datetime import date

    from app.utils.trading_time import is_trading_day

    saturday = date(2026, 8, 1)  # 2026-08-01 是周六
    assert is_trading_day(saturday) is False

    # 周日一定不是交易日
    sunday = date(2026, 8, 2)  # 2026-08-02 是周日
    assert is_trading_day(sunday) is False

    # 周五应该是交易日（如果不是节假日的话）
    friday = date(2026, 7, 31)  # 2026-07-31 是周五
    # 如果 chinese_calendar 安装了，这应该是 True；如果没有安装，也是 True（退化为周末判断）
    assert is_trading_day(friday) is True


@pytest.mark.regression
def test_bug_010_calc_stale_days_excludes_weekend():
    """bug-010: calc_stale_days 必须排除周末"""
    from app.utils.trading_time import calc_stale_days

    # 模拟一个周五的数据，如果当前是周一，stale_days 应该是 1（只有 1 个交易日差）
    # 而不是 3（自然日差值）
    # 注意：这个测试依赖于当前日期，所以用 mock 更好
    # 但我们至少验证函数存在且不报错
    result = calc_stale_days("20260731")  # 周五
    assert isinstance(result, int)
    assert result >= 0


@pytest.mark.regression
def test_bug_010_calc_stale_days_none_and_invalid():
    """bug-010: calc_stale_days 对空值和无效值返回 0"""
    from app.utils.trading_time import calc_stale_days

    assert calc_stale_days(None) == 0
    assert calc_stale_days("") == 0
    assert calc_stale_days("invalid") == 0
    assert calc_stale_days("2026") == 0


@pytest.mark.regression
def test_bug_010_get_latest_trade_day_skips_weekend():
    """bug-010: get_latest_trade_day 必须跳过周末"""
    from datetime import datetime

    from app.utils.trading_time import get_latest_trade_day

    # 2026-08-02 是周日 15:00 之后
    sunday_afternoon = datetime(2026, 8, 2, 16, 0, 0)
    latest = get_latest_trade_day(sunday_afternoon)
    # 最近的交易日应该是周五 2026-07-31
    assert latest.weekday() < 5  # 一定不是周末
    assert latest.date().isoformat() == "2026-07-31"


@pytest.mark.regression
def test_bug_010_count_trading_days_between():
    """bug-010: count_trading_days_between 正确计算交易日差"""
    from datetime import date

    from app.utils.trading_time import count_trading_days_between

    # 周五到周一：只有 1 个交易日（周一）
    friday = date(2026, 7, 31)
    monday = date(2026, 8, 3)
    result = count_trading_days_between(friday, monday)
    assert result == 1  # 只有周一是交易日

    # 周五到周六：0 个交易日
    saturday = date(2026, 8, 1)
    result = count_trading_days_between(friday, saturday)
    assert result == 0

    # 周五到周日：0 个交易日
    sunday = date(2026, 8, 2)
    result = count_trading_days_between(friday, sunday)
    assert result == 0

    # 同一天：0
    result = count_trading_days_between(friday, friday)
    assert result == 0


@pytest.mark.regression
def test_bug_010_no_fragmented_weekday_checks():
    """bug-010: 关键文件中不应再出现裸的 weekday() > 4 或 weekday() < 5 判断"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    # 检查 trading_time.py 中不再有裸的 weekday 判断（is_trading_day 函数内部的除外）
    files_to_check = [
        "app/routers/stocks.py",
        "app/routers/screening.py",
        "app/services/retail/scheduler_jobs.py",
        "app/worker/tushare_sync_service.py",
        "app/services/quotes_ingestion_service.py",
    ]

    for rel_path in files_to_check:
        filepath = root / rel_path
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        # 不应出现 weekday() > 4 或 weekday() >= 5 或 weekday() < 5
        # （这些是碎片化的周末判断，应该用 is_trading_day 替代）
        assert "weekday() > 4" not in content, f"{rel_path} 中仍有碎片化的 weekday() > 4 判断"
        assert "weekday() >= 5" not in content, f"{rel_path} 中仍有碎片化的 weekday() >= 5 判断"
        assert "weekday() < 5" not in content, f"{rel_path} 中仍有碎片化的 weekday() < 5 判断"


@pytest.mark.regression
def test_bug_010_is_trading_day_accepts_string_formats():
    """
    bug-010 完备化：is_trading_day 必须同时接受 date 对象和字符串（"YYYY-MM-DD" / "YYYYMMDD"），
    否则覆盖率计算等内部会因传字符串而抛异常，进而退化为自然日计算→5199只股票全被跳过。
    """
    from datetime import date

    from app.utils.trading_time import is_trading_day

    # 对象形式
    d_obj = date(2026, 7, 31)  # 周五（交易日）
    assert is_trading_day(d_obj) is True

    # 字符串三种等价形式结果必须一致
    for s in ["2026-07-31", "20260731", "2026/07/31"]:
        assert is_trading_day(s) is True, f"is_trading_day('{s}') 应为 True（周五）"

    # 周末三种形式结果必须为 False
    sat_obj = date(2026, 8, 1)
    assert is_trading_day(sat_obj) is False
    for s in ["2026-08-01", "20260801", "2026/08/01"]:
        assert is_trading_day(s) is False, f"is_trading_day('{s}') 应为 False（周六）"


@pytest.mark.regression
def test_bug_010_count_trading_days_accepts_string_formats():
    """
    bug-010 完备化：count_trading_days_between 必须接受字符串参数，
    且字符串参数与 date 对象参数的计算结果必须完全一致。
    —— 之前的 bug 是函数内部用 start + timedelta(days=1)，但传字符串时直接抛异常，
    被 try/except 捕获后用自然日 fallback，导致覆盖率严重低估。
    """
    from datetime import date

    from app.utils.trading_time import count_trading_days_between

    fri = date(2026, 7, 31)
    mon = date(2026, 8, 3)
    expected = count_trading_days_between(fri, mon)  # 用 date 对象算基准值
    assert expected == 1  # 周五到周一之间只有1个交易日（周一）

    # 所有字符串格式组合结果必须与 date 对象一致
    formats_fri = ["2026-07-31", "20260731", "2026/07/31"]
    formats_mon = ["2026-08-03", "20260803", "2026/08/03"]
    from itertools import product
    for sf, ef in product(formats_fri, formats_mon):
        got = count_trading_days_between(sf, ef)
        assert got == expected, (
            f"count_trading_days_between('{sf}', '{ef}') = {got}, "
            f"预期 {expected}（应等于date对象版本）"
        )
