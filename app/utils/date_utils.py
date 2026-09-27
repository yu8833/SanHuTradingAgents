"""统一日期工具 —— 日期解析/格式化的唯一事实来源。

收敛系统内多套手工互转（stock_quadrant._dash/_compact、tushare_sync._norm_date/_compact_date、
board_quadrant._dash、trade_calendar._norm、trading_time._parse_date_arg），统一语义：

- normalize_date：接收 date/datetime/YYYY-MM-DD/YYYYMMDD/含 / 与 . 分隔，返回 YYYY-MM-DD；
  非法/空返回 None（不抛错、不截断）；
- compact_date：YYYY-MM-DD → YYYYMMDD；
- parse_date：解析为 date 对象（非法 None）；
- today_str：北京时区今日 YYYY-MM-DD。

各调用点保留自身特殊约定（抛 TypeError / 空串 / 截断）时，在本模块之上自行包装。
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.utils.timezone import now_tz

_YYYYMMDD_RE = re.compile(r"^\d{8}$")


def normalize_date(d) -> str | None:
    """任意常见日期表示 → 'YYYY-MM-DD'；非法/空返回 None。

    接受：date / datetime / 'YYYY-MM-DD' / 'YYYYMMDD' / 'YYYY/MM/DD' / 'YYYY.MM.DD'。
    语义统一：非法输入不抛错、不截断。
    """
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    if not s:
        return None
    collapsed = re.sub(r"[^\d]", "", s)
    if _YYYYMMDD_RE.match(collapsed):
        s = f"{collapsed[:4]}-{collapsed[4:6]}-{collapsed[6:8]}"
    try:
        return date.fromisoformat(s).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def compact_date(d) -> str | None:
    """任意常见日期表示 → 'YYYYMMDD'；非法/空返回 None。"""
    norm = normalize_date(d)
    return norm.replace("-", "") if norm else None


def parse_date(d) -> date | None:
    """任意常见日期表示 → date 对象；非法/空返回 None。"""
    norm = normalize_date(d)
    if not norm:
        return None
    try:
        return date.fromisoformat(norm)
    except (ValueError, TypeError):
        return None


def today_str() -> str:
    """北京时区今日 'YYYY-MM-DD'。"""
    return now_tz().strftime("%Y-%m-%d")