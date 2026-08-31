"""财经日历 provider —— 东财 datacenter 首选，AKShare 宏观接口兜底，手工高频事件日历再兜底。

设计文档《第六章·交易工具与日常流程》§5.3-B：
  - 首选：东财 datacenter 经济日历接口，拉取未来 7 天：中国（CPI/PPI/PMI/社融/M2/LPR/MLF）、
    美国（非农/CPI/PPI/利率决议/初请失业金）；
  - 兜底：AKShare 宏观接口；再兜底：手工维护的"高频事件日历"表（降准降息日/议息日/数据发布日/重要会议日）；
  - 输出：`{date, region, event, importance, forecast, 发布时点}`，Redis 1 天 TTL。

容器实测（2026-08-31）：东财 datacenter 三类经济日历报表均返回"报表配置不存在"；
AKShare 的 `macro_info_ws` 周历数据停在 2024-05 为陈旧数据。故以「手工高频事件日历」规则表
为可靠底座（确定性、可维护），并叠加 AKShare 宏观序列做「预期/前值」增量增强。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# 日历前瞻天数
_CALENDAR_DAYS = 7

# FOMC 2026 议息会议（决议公布日 = 会议第 2 天，北京时间通常次日凌晨）。
# 手工维护：每年年初按美联储官方日程更新一次（2026-08-31 据 fomccalendars.htm 核实）。
_FOMC_2026_DECISION_DATES = (
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
)


def _next_month_day(d: date, day: int) -> date:
    """d 所在月及之后、每月 day 日的最近一次（>= d）。"""
    candidate = d.replace(day=day)
    if candidate < d:
        y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
        candidate = date(y, m, day)
    return candidate


def _next_business_day(d: date) -> date:
    """如 d 落在周末，顺延到下一个工作日（不处理法定节假日，够用即可）。"""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _next_nth_weekday(d: date, weekday: int, nth: int) -> date:
    """自 d 起（含 d 所在月）第 nth 个 weekday（0=周一 ... 6=周日）的最近一次。"""
    def _nth_in_month(y: int, m: int) -> date:
        first = date(y, m, 1)
        offset = (weekday - first.weekday()) % 7
        day = 1 + offset + (nth - 1) * 7
        if day > 28:  # 简化：超过当月天数则视为当月不存在该次
            day = 1 + offset + (nth - 1) * 7 - 7
        return date(y, m, day)

    candidate = _nth_in_month(d.year, d.month)
    if candidate < d:
        y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
        candidate = _nth_in_month(y, m)
    return candidate


def _next_weekly(d: date, weekday: int) -> date:
    """自 d 起最近一次 weekday（0=周一 ... 6=周日），>= d。"""
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset)


def _fomc_next(d: date) -> date | None:
    for dt in _FOMC_2026_DECISION_DATES:
        if dt >= d:
            return dt
    return None


# ---------------------------------------------------------------------------
# 手工高频事件日历规则表（可维护）。rule(d) -> 最近一次发生日期（>= d）或 None。
# 每个事件附带：发布时点（北京时间）、AKShare 序列名（用于预期/前值增强）。
# ---------------------------------------------------------------------------
def _lpr_rule(d: date) -> date:
    return _next_business_day(_next_month_day(d, 20))


def _china_pmi_rule(d: date) -> date:
    # 官方制造业 PMI 于月末最后一天公布
    end = date(d.year, d.month + 1, 1) if d.month < 12 else date(d.year + 1, 1, 1)
    return end - timedelta(days=1)


def _cpi_ppi_rule(d: date) -> date:
    # 中国 CPI/PPI 于每月 9 日前后公布上月数据
    return _next_month_day(d, 9)


def _srz_m2_rule(d: date) -> date:
    # 社融/M2 通常中旬（10-15 日）公布，取 15 日作为参考发布日
    return _next_month_day(d, 15)


def _mlf_rule(d: date) -> date:
    # 每月 15 日 MLF 操作（遇周末顺延）
    return _next_business_day(_next_month_day(d, 15))


def _non_farm_rule(d: date) -> date:
    # 美国非农：每月第一个周五
    return _next_nth_weekday(d, 4, 1)


def _us_cpi_rule(d: date) -> date:
    # 美国 CPI：每月中旬（约 13 日）
    return _next_month_day(d, 13)


def _us_ppi_rule(d: date) -> date:
    # 美国 PPI：每月约 15 日
    return _next_month_day(d, 15)


def _jobless_rule(d: date) -> date:
    # 美国初请失业金：每周四（美东）
    return _next_weekly(d, 3)


def _ism_rule(d: date) -> date:
    # 美国 ISM 制造业 PMI：每月第一个工作日
    return _next_business_day(_next_nth_weekday(d, 0, 1))


# 规则表：event / region / importance / rule / release_time / akshare
_HIGH_FREQ_EVENTS = (
    # ---- 中国 ----
    {"event": "中国 LPR 报价", "region": "中国", "importance": "high",
     "rule": _lpr_rule, "release_time": "09:15", "akshare": "macro_china_lpr"},
    {"event": "中国官方制造业 PMI", "region": "中国", "importance": "high",
     "rule": _china_pmi_rule, "release_time": "09:30", "akshare": "macro_china_pmi_yearly"},
    {"event": "中国 CPI/PPI（上月）", "region": "中国", "importance": "high",
     "rule": _cpi_ppi_rule, "release_time": "09:30", "akshare": "macro_china_cpi_yearly"},
    {"event": "中国社融/M2 数据", "region": "中国", "importance": "medium",
     "rule": _srz_m2_rule, "release_time": "中旬", "akshare": None},
    {"event": "中国 MLF 操作", "region": "中国", "importance": "medium",
     "rule": _mlf_rule, "release_time": "10:00", "akshare": None},
    # ---- 美国 ----
    {"event": "美国非农就业", "region": "美国", "importance": "high",
     "rule": _non_farm_rule, "release_time": "20:30", "akshare": "macro_usa_non_farm"},
    {"event": "美国 CPI", "region": "美国", "importance": "high",
     "rule": _us_cpi_rule, "release_time": "20:30", "akshare": "macro_usa_cpi_yoy"},
    {"event": "美国 PPI", "region": "美国", "importance": "medium",
     "rule": _us_ppi_rule, "release_time": "20:30", "akshare": "macro_usa_ppi"},
    {"event": "美国初请失业金", "region": "美国", "importance": "medium",
     "rule": _jobless_rule, "release_time": "20:30", "akshare": None},
    {"event": "美国 ISM 制造业 PMI", "region": "美国", "importance": "medium",
     "rule": _ism_rule, "release_time": "22:00", "akshare": "macro_usa_ism_pmi"},
    {"event": "美联储 FOMC 利率决议", "region": "美国", "importance": "high",
     "rule": _fomc_next, "release_time": "次日02:00", "akshare": None},
)


def _eastmoney_calendar() -> list[dict]:
    """东财 datacenter 经济日历（首选）。容器实测报表不可用 → 返回 []，由调用方降级。"""
    try:
        rows = astock_eastmoney_calendar()
        return rows or []
    except Exception as e:
        logger.warning(f"东财财经日历不可用（降级 AKShare/手工日历）: {e}")
        return []


def astock_eastmoney_calendar() -> list[dict]:
    """东财 datacenter 经济日历（报表名已实测不存在，保留入口便于后续切换报表名）。"""
    from app.services import vibe_astock as astock
    out: list[dict] = []
    for report in ("RPT_ECONOMIC_VALUE_BASE", "RPT_ECONOMIC_CALENDAR", "RPT_CALENDAR_EVENT"):
        rows = astock.eastmoney_datacenter(report, page_size=50, sort_columns="REPORT_DATE")
        if rows:
            out = []
            for r in rows:
                out.append({
                    "date": str(r.get("REPORT_DATE") or r.get("DATE") or "")[:10],
                    "region": str(r.get("REGION") or r.get("COUNTRY") or ""),
                    "event": str(r.get("TITLE") or r.get("EVENT_NAME") or ""),
                    "importance": str(r.get("IMPORTANCE") or "").lower(),
                    "forecast": r.get("PRED_VALUE") or r.get("FORECAST"),
                    "release_time": str(r.get("RELEASE_TIME") or r.get("PUBLISH_TIME") or ""),
                })
            break
    return out


# ---------------------------------------------------------------------------
# AKShare 宏观序列增强：为日历事件附加 {previous, forecast}（预期/前值）。
# ---------------------------------------------------------------------------
def _akshare_recent_value(fn_name: str) -> dict | None:
    """取 AKShare 宏观序列最近一期的 {previous, forecast, actual}；失败返回 None。"""
    try:
        import akshare as ak
        fn = getattr(ak, fn_name, None)
        if fn is None:
            return None
        df = fn()
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        col_map = {c: i for i, c in enumerate(df.columns)}
        def _get(*names):
            for n in names:
                if n in col_map:
                    v = last.iloc[col_map[n]]
                    if v is not None and str(v) not in ("", "nan", "None"):
                        return v
            return None
        return {
            "actual": _get("今值", "实际", "value", "今值"),
            "forecast": _get("预测值", "预期", "forecast", "预测值"),
            "previous": _get("前值", "previous", "前值"),
        }
    except Exception:
        return None


def _akshare_values() -> dict[str, dict]:
    """按事件 akshare 名聚合最近一期预期/前值；一次性抓取，失败项忽略。"""
    values: dict[str, dict] = {}
    seen: set[str] = set()
    for ev in _HIGH_FREQ_EVENTS:
        fn = ev.get("akshare")
        if not fn or fn in seen:
            continue
        seen.add(fn)
        v = _akshare_recent_value(fn)
        if v:
            values[ev["event"]] = v
    return values


def _manual_events(today: date, days: int) -> list[dict]:
    """从规则表生成 [today, today+days-1] 窗口内的高频事件日历。"""
    end = today + timedelta(days=days - 1)
    out: list[dict] = []
    for ev in _HIGH_FREQ_EVENTS:
        try:
            dt = ev["rule"](today)
        except Exception:
            continue
        if dt is None or not (today <= dt <= end):
            continue
        out.append({
            "date": dt.isoformat(),
            "region": ev["region"],
            "event": ev["event"],
            "importance": ev["importance"],
            "forecast": None,
            "previous": None,
            "release_time": ev["release_time"],
        })
    out.sort(key=lambda x: (x["date"], x["event"]))
    return out


def _build_calendar(days: int = _CALENDAR_DAYS) -> list[dict]:
    """日历构建：东财首选，失败走 AKShare 增强 + 手工高频事件日历。"""
    rows = _eastmoney_calendar()
    if rows:
        return rows

    today = date.today()
    events = _manual_events(today, days)
    if not events:
        return events

    # AKShare 增强：为命中事件附加 {previous, forecast}
    values = _akshare_values()
    for ev in events:
        v = values.get(ev["event"])
        if v:
            ev["forecast"] = v.get("forecast")
            ev["previous"] = v.get("previous")
    return events


async def get_financial_calendar(days: int = _CALENDAR_DAYS) -> list[dict]:
    """财经日历（未来 7 天），Redis 1 天 TTL 缓存。"""
    return await cached(
        f"macro:calendar:{days}",
        lambda: _build_calendar(days),
        category="financial",
        valid=bool,
    )
