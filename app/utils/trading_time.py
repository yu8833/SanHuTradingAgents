"""
交易时间判断工具模块

提供统一的交易时间判断逻辑，用于判断当前是否在A股交易时间内。
所有需要判断"是否交易日/交易时间"的代码都应从本模块导入，禁止在别处重复实现。
"""

import logging
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from app.core.config import settings

logger = logging.getLogger(__name__)


def _parse_date_arg(d) -> date:
    """内部工具：将 date/datetime/字符串(YYYY-MM-DD 或 YYYYMMDD) 统一转为 date 对象。"""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        cleaned = d.replace("-", "").replace("/", "")
        if len(cleaned) == 8:
            try:
                return date(int(cleaned[0:4]), int(cleaned[4:6]), int(cleaned[6:8]))
            except (ValueError, IndexError):
                pass
    raise TypeError(f"无法将 {type(d).__name__} 值 {d!r} 解析为日期")


def is_trading_day(date) -> bool:
    """
    判断指定日期是否为交易日（排除周末和中国法定节假日）。

    使用 chinese_calendar 库判断节假日，如果未安装则退化为仅排除周末。

    Args:
        date: 日期对象（datetime / date / 字符串 YYYY-MM-DD 或 YYYYMMDD）

    Returns:
        bool: True 表示是交易日
    """
    try:
        d = _parse_date_arg(date)
    except TypeError:
        logger.warning(f"is_trading_day 入参不合法: {date!r}，退化为非交易日")
        return False

    if d.weekday() >= 5:
        return False
    try:
        import chinese_calendar

        return chinese_calendar.is_workday(d)
    except ImportError:
        logger.warning("chinese_calendar 未安装，仅按周末判断交易日（节假日未排除）")
        return True
    except Exception:
        return True


def get_latest_trade_day(now: datetime | None = None) -> datetime:
    """
    获取最近已完成的交易日。

    规则：
    - 如果今天是交易日且已过 15:00（收盘），返回今天
    - 如果今天是交易日但未到 15:00，返回上一个交易日
    - 如果今天不是交易日（周末/节假日），向前找到最近的交易日

    Args:
        now: 指定时间，默认为当前时间

    Returns:
        datetime: 最近的交易日
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)

    # 今天是交易日且已收盘
    if is_trading_day(now) and now.time() >= dtime(15, 0):
        return now

    # 往前找交易日
    cursor = now - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def count_trading_days_between(start, end) -> int:
    """
    计算两个日期之间的交易日数量（不含 start，含 end）。

    用于计算数据过期天数：stale_days = count_trading_days_between(data_date, latest_trade_day)

    Args:
        start: 起始日期（不含）—— 支持 date/datetime/字符串 YYYY-MM-DD / YYYYMMDD
        end: 结束日期（含）—— 支持 date/datetime/字符串 YYYY-MM-DD / YYYYMMDD

    Returns:
        int: 交易日数量
    """
    try:
        s = _parse_date_arg(start)
        e = _parse_date_arg(end)
    except TypeError as ex:
        logger.warning(f"count_trading_days_between 入参不合法: start={start!r}, end={end!r}: {ex}")
        return 0
    if s >= e:
        return 0
    count = 0
    cursor = s + timedelta(days=1)
    while cursor <= e:
        if is_trading_day(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count


def calc_stale_days(data_date_str: str | None) -> int:
    """
    根据数据日期字符串（YYYYMMDD 或 YYYY-MM-DD）计算过期交易日数。

    stale_days = 0  → 数据是最新交易日的
    stale_days = 1  → 数据落后 1 个交易日
    stale_days = N  → 数据落后 N 个交易日

    Args:
        data_date_str: 数据日期，支持 "20260731" 或 "2026-07-31" 格式

    Returns:
        int: 过期交易日数（0 表示最新）
    """
    if not data_date_str:
        return 0
    cleaned = data_date_str.replace("-", "")
    if len(cleaned) != 8:
        return 0
    try:
        data_date = date(
            int(cleaned[0:4]),
            int(cleaned[4:6]),
            int(cleaned[6:8]),
        )
    except (ValueError, IndexError):
        return 0

    latest = get_latest_trade_day()
    if data_date >= latest.date():
        return 0
    return count_trading_days_between(data_date, latest.date())


def is_trading_time(now: datetime | None = None) -> bool:
    """
    判断是否在A股交易时间或收盘后缓冲期

    交易时间：
    - 上午：9:30-11:30
    - 下午：13:00-15:00
    - 收盘后缓冲期：15:00-15:30（确保获取到收盘价）

    收盘后缓冲期说明：
    - 交易时间结束后继续获取30分钟
    - 假设6分钟一次，可以增加5次同步机会
    - 大大降低错过收盘价的风险

    Args:
        now: 指定时间，默认为当前时间（使用配置的时区）

    Returns:
        bool: 是否在交易时间内
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)
    
    # 交易日（排除周末和节假日）
    if not is_trading_day(now):
        return False

    t = now.time()

    # 上交所/深交所常规交易时段
    morning = dtime(9, 30)
    noon = dtime(11, 30)
    afternoon_start = dtime(13, 0)
    # 收盘后缓冲期（延长30分钟到15:30）
    buffer_end = dtime(15, 30)

    return (morning <= t <= noon) or (afternoon_start <= t <= buffer_end)


def is_strict_trading_time(now: datetime | None = None) -> bool:
    """
    判断是否在严格的A股交易时间内（不包含缓冲期）

    交易时间：
    - 上午：9:30-11:30
    - 下午：13:00-15:00

    Args:
        now: 指定时间，默认为当前时间（使用配置的时区）

    Returns:
        bool: 是否在严格交易时间内
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)

    # 交易日（排除周末和节假日）
    if not is_trading_day(now):
        return False
    
    t = now.time()
    
    # 上交所/深交所常规交易时段
    morning = dtime(9, 30)
    noon = dtime(11, 30)
    afternoon_start = dtime(13, 0)
    afternoon_end = dtime(15, 0)
    
    return (morning <= t <= noon) or (afternoon_start <= t <= afternoon_end)


def is_pre_market_time(now: datetime | None = None) -> bool:
    """
    判断是否在盘前时间（9:00-9:30）

    Args:
        now: 指定时间，默认为当前时间（使用配置的时区）

    Returns:
        bool: 是否在盘前时间
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)

    # 交易日（排除周末和节假日）
    if not is_trading_day(now):
        return False

    t = now.time()
    pre_market_start = dtime(9, 0)
    pre_market_end = dtime(9, 30)

    return pre_market_start <= t < pre_market_end


def is_after_market_time(now: datetime | None = None) -> bool:
    """
    判断是否在盘后时间（15:00-15:30）

    Args:
        now: 指定时间，默认为当前时间（使用配置的时区）

    Returns:
        bool: 是否在盘后时间
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)

    # 交易日（排除周末和节假日）
    if not is_trading_day(now):
        return False

    t = now.time()
    after_market_start = dtime(15, 0)
    after_market_end = dtime(15, 30)

    return after_market_start <= t <= after_market_end


def get_trading_status(now: datetime | None = None) -> str:
    """
    获取当前交易状态

    Args:
        now: 指定时间，默认为当前时间（使用配置的时区）

    Returns:
        str: 交易状态
            - "pre_market": 盘前
            - "morning_session": 上午交易时段
            - "noon_break": 午间休市
            - "afternoon_session": 下午交易时段
            - "after_market": 盘后缓冲期
            - "closed": 休市
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)
    
    # 非交易日（周末/节假日）
    if not is_trading_day(now):
        return "closed"
    
    t = now.time()
    
    # 定义时间点
    pre_market_start = dtime(9, 0)
    morning_start = dtime(9, 30)
    noon = dtime(11, 30)
    afternoon_start = dtime(13, 0)
    afternoon_end = dtime(15, 0)
    after_market_end = dtime(15, 30)
    
    # 判断状态
    if pre_market_start <= t < morning_start:
        return "pre_market"
    elif morning_start <= t <= noon:
        return "morning_session"
    elif noon < t < afternoon_start:
        return "noon_break"
    elif afternoon_start <= t <= afternoon_end:
        return "afternoon_session"
    elif afternoon_end < t <= after_market_end:
        return "after_market"
    else:
        return "closed"

