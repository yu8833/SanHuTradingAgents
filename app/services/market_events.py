"""今日宏观事件 —— 抓取 / 白名单过滤 / 规则化影响打分。

设计原则（对应用户体验要求）：
- 只保留与 A 股风险偏好、流动性、盈利预期相关的少数事件，不把日历原样搬上页面；
- 影响分三档：none（噪音）/ volatility（只影响波动）/ direction（影响方向），
  只有 direction 档才允许改动仓位与信心度；
- 每条事件带「可证伪观察点」，让判断有失效条件，而不是叙事；
- 数据源不可用时返回 source_ok=False，不缓存，页面显式降级。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from app.services.cache_layer import cached
from app.services.vibe_astock import _akshare

BEIJING = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

# 影响等级阈值：|raw| < 0.5 视为噪音，< 1.2 只影响波动，超过才认为影响方向
_LEVEL_NONE = 0.5
_LEVEL_DIRECTION = 1.2

# 事件规则：pattern 命中标题后使用该配置打分。
# coef 为「预期差 → 大盘方向」的系数：正数表示超预期偏多，负数表示超预期偏空。
# scale 是该指标一次「普通幅度意外」的量纲，用于把绝对偏差标准化。
_RULES: list[dict] = [
    {
        "key": "cn_cpi", "region": "CN", "pattern": r"CPI|居民消费价格",
        "scale": 0.2, "coef": -0.7, "horizon": "仅今日",
        "sectors": ["高股息", "债", "成长"],
        "trans": ["通胀压力变化", "宽松预期变化", "利率敏感板块反向"],
        "watch": "10 年期国债收益率是否同向变动 >2bp",
    },
    {
        "key": "cn_ppi", "region": "CN", "pattern": r"PPI|工业生产者出厂价格",
        "scale": 0.3, "coef": -0.6, "horizon": "仅今日",
        "sectors": ["上游资源", "中游制造"],
        "trans": ["工业品价格变化", "中下游利润再分配", "周期板块分化"],
        "watch": "周期板块是否跟随商品价格同向",
    },
    {
        "key": "cn_pmi", "region": "CN", "pattern": r"PMI|采购经理",
        "scale": 0.5, "coef": 0.9, "horizon": "今日~T+1",
        "sectors": ["顺周期", "通用设备", "出口链"],
        "trans": ["景气度变化", "盈利预期修正", "顺周期板块反应"],
        "watch": "顺周期板块能否放量跑赢大盘",
    },
    {
        "key": "cn_srf", "region": "CN", "pattern": r"社会融资|社融",
        "scale": 3000, "coef": 0.8, "horizon": "今日~T+3",
        "sectors": ["券商", "银行", "中小盘"],
        "trans": ["宽信用程度", "实体融资需求", "流动性敏感板块"],
        "watch": "券商板块是否放量；若冲高回落视为预期已消化",
    },
    {
        "key": "cn_m2", "region": "CN", "pattern": r"M2|货币供应",
        "scale": 0.3, "coef": 0.6, "horizon": "今日~T+3",
        "sectors": ["券商", "成长"],
        "trans": ["货币宽松程度", "剩余流动性", "估值扩张空间"],
        "watch": "两市成交额能否维持 1.1 倍 5 日均",
    },
    {
        "key": "cn_gdp", "region": "CN", "pattern": r"GDP|国内生产总值",
        "scale": 0.3, "coef": 0.8, "horizon": "今日~T+3",
        "sectors": ["顺周期", "消费"],
        "trans": ["增长动能", "盈利预期", "顺周期与消费"],
        "watch": "顺周期与消费是否同步走强",
    },
    {
        "key": "lpr", "region": "CN", "pattern": r"LPR|贷款市场报价利率",
        "scale": 0.1, "coef": 0.9, "horizon": "今日~T+3",
        "sectors": ["券商", "银行", "地产链"],
        "trans": ["融资成本", "宽信用预期", "利率敏感板块"],
        "watch": "银行与地产链是否同向；若仅高开则视为利好出尽",
    },
    {
        "key": "us_nfp", "region": "US", "pattern": r"非农|失业率",
        "scale": 5, "coef": -0.6, "horizon": "今日~T+1",
        "sectors": ["成长", "出口链", "外资重仓"],
        "trans": ["美债利率预期", "外资风险偏好", "成长估值受压"],
        "watch": "美元指数与美债收益率是否同向走强",
    },
    {
        "key": "us_cpi", "region": "US", "pattern": r"CPI|消费者物价",
        "scale": 0.2, "coef": -0.7, "horizon": "今日~T+1",
        "sectors": ["成长", "外资重仓"],
        "trans": ["美联储路径", "美债利率", "成长估值"],
        "watch": "纳指期货与美元指数是否同向确认",
    },
    {
        "key": "fomc", "region": "US", "pattern": r"美联储|FOMC|利率决议|议息",
        "scale": None, "coef": None, "horizon": "今日~T+1",
        "sectors": ["成长", "出口链", "外资重仓"],
        "trans": ["政策路径不确定性", "美债利率与美元", "风险偏好"],
        "watch": "开盘 30 分钟北向与成长板块是否同向；不一致则按波动处理",
    },
    {
        "key": "tariff", "region": "ANY", "pattern": r"关税|制裁|出口管制|实体清单",
        "scale": None, "coef": None, "horizon": "今日~T+1",
        "sectors": ["出口链", "半导体", "军工"],
        "trans": ["风险偏好", "出口链盈利预期", "自主可控主题"],
        "watch": "出口链是否放量下跌；若低开高走视为已消化",
    },
]

# 明确剔除：仓单、竞拍、库存、每日高频项，以及日历里常见但与A股无关的例行条目
_BLACKLIST = re.compile(
    r"仓单|竞拍|库存|每日|货币供应M1金额|货币供应M2金额|国债竞拍|同业拆借|拆借利率"
)

_REGION_ALLOW = ("中国", "美国", "欧元区")


def _s(v) -> str:
    """把 NaN / None / '--' 统一成空串。"""
    if v is None:
        return ""
    t = str(v).strip()
    return "" if t.lower() in ("nan", "none", "--", "-") else t


def _num(v) -> float | None:
    t = _s(v).replace(",", "").replace("%", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _hhmm(v) -> str:
    """时间归一为 HH:MM。"""
    t = _s(v)
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return t[:5]


def _match_rule(title: str, region: str) -> dict | None:
    for rule in _RULES:
        if rule["region"] not in ("ANY", region):
            continue
        if re.search(rule["pattern"], title):
            return rule
    return None


def _strength(raw: float | None) -> str:
    if raw is None:
        return "中"
    a = abs(raw)
    return "轻" if a < 0.8 else ("中" if a < 1.5 else "重")


def _action(rule: dict, direction: str, z: float | None) -> str:
    key = rule["key"]
    bull = direction == "bull"
    if key in ("cn_cpi", "cn_ppi"):
        return "不追高估值成长，观察高股息防守" if z and z > 0 else "通胀压力缓和，可小幅提升风险偏好，但需量能确认"
    if key == "cn_pmi":
        return "景气改善，关注顺周期与设备" if bull else "景气走弱，降低顺周期暴露"
    if key in ("cn_srf", "cn_m2", "lpr"):
        return "流动性宽松，关注券商与中小盘" if bull else "宽信用不及预期，回避高杠杆方向"
    if key == "cn_gdp":
        return "增长稳定，维持顺周期配置" if bull else "增长偏弱，转向防御"
    if key in ("us_nfp", "us_cpi"):
        return "美债利率上行压力，不追成长" if not bull else "外压缓解，成长可小幅修复"
    if key in ("fomc", "tariff"):
        return "开盘不接力，等 10:00 后方向确认"
    return "按原计划执行，不因单一数据调仓"


def _score(rule: dict, actual: float | None, forecast: float | None) -> tuple[float | None, float | None]:
    """返回 (标准化预期差 z, 合成分数 raw)。无预期/公布值或无数值规则时 raw=None。"""
    if actual is None or forecast is None or not rule.get("scale") or rule.get("coef") is None:
        return None, None
    z = (actual - forecast) / float(rule["scale"])
    z = max(-3.0, min(3.0, z))
    return round(z, 3), round(z * float(rule["coef"]), 3)


def _build_event(row: dict, rule: dict, day: str) -> dict:
    title = _s(row.get("事件"))
    hhmm = _hhmm(row.get("时间")) or "待定"
    actual = _num(row.get("公布"))
    forecast = _num(row.get("预期"))
    prev = _num(row.get("前值"))
    z, raw = _score(rule, actual, forecast)

    if actual is None:
        status = "pending"
    else:
        now = datetime.now(BEIJING)
        status = "expired" if hhmm != "待定" and now.strftime("%H:%M") > hhmm and day < now.strftime("%Y-%m-%d") else "released"

    if raw is None:
        impact, direction = "volatility", "neutral"
    elif abs(raw) < _LEVEL_NONE:
        impact, direction = "none", "neutral"
    elif abs(raw) < _LEVEL_DIRECTION:
        impact, direction = "volatility", "bull" if raw > 0 else "bear"
    else:
        impact, direction = "direction", "bull" if raw > 0 else "bear"

    label = ""
    if actual is not None and forecast is not None:
        if abs(actual - forecast) < 1e-9:
            label = "符合"
        else:
            label = "超预期" if actual > forecast else "低于预期"

    return {
        "id": f"{day}-{hhmm}-{rule['key']}",
        "time": hhmm,
        "datetime": f"{day}T{hhmm}:00+08:00" if hhmm != "待定" else f"{day}T00:00:00+08:00",
        "title": title,
        "region": "CN" if rule["region"] in ("CN", "ANY") else rule["region"],
        "status": status,
        "forecast": forecast,
        "actual": actual,
        "prev": prev,
        "surprise_label": label,
        "direction": direction,
        "impact": impact,
        "strength": _strength(raw) if raw is not None else "中",
        "horizon": rule.get("horizon", ""),
        "action": "" if impact == "none" else _action(rule, direction, z),
        "sectors": rule.get("sectors", []),
        "transmission": rule.get("trans", []),
        "watch": rule.get("watch", ""),
        "score": raw,
    }


def _fomc_events(day: str) -> list[dict]:
    """手工日程补充：百度日历常把 FOMC 决议标到次日凌晨，这里按官方决议日补一条。"""
    try:
        from app.services.macro.financial_calendar import _FOMC_2026_DECISION_DATES

        d = date.fromisoformat(day)
        if d not in _FOMC_2026_DECISION_DATES:
            return []
        now = datetime.now(BEIJING).strftime("%H:%M")
        return [{
            "id": f"{day}-02:00-fomc-manual",
            "time": "02:00",
            "datetime": f"{day}T02:00:00+08:00",
            "title": "美联储 FOMC 利率决议（手工日程）",
            "region": "US",
            "status": "released" if now >= "02:00" else "pending",
            "forecast": None, "actual": None, "prev": None, "surprise_label": "",
            "direction": "neutral", "impact": "volatility", "strength": "中",
            "horizon": "今日~T+1",
            "action": "开盘不接力，等 10:00 后方向确认",
            "sectors": ["成长", "出口链", "外资重仓"],
            "transmission": ["政策路径不确定性", "美债利率与美元", "风险偏好"],
            "watch": "开盘 30 分钟北向与成长板块是否同向；不一致则按波动处理",
            "score": None,
        }]
    except Exception:
        return []


def _fetch_calendar(day: str) -> list[dict]:
    ak = _akshare()
    df = ak.news_economic_baidu(date=day.replace("-", ""))
    return df.to_dict("records")


def _process(rows: list[dict], day: str) -> list[dict]:
    events: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        title = _s(row.get("事件"))
        region = _s(row.get("地区"))
        if not title or not any(region.startswith(r) for r in _REGION_ALLOW):
            continue
        if _BLACKLIST.search(title):
            continue
        rule = _match_rule(title, "CN" if region.startswith("中国") else ("US" if region.startswith("美国") else "EU"))
        if not rule:
            continue
        ev = _build_event(row, rule, day)
        sig = f"{ev['time']}-{ev['title']}"
        if sig in seen:
            continue
        seen.add(sig)
        events.append(ev)

    for ev in _fomc_events(day):
        if not any("FOMC" in e["title"].upper() for e in events):
            events.append(ev)

    events.sort(key=lambda e: (e["time"] == "待定", e["time"]))
    return events[:8]


async def _build_events() -> dict:
    day = datetime.now(BEIJING).strftime("%Y-%m-%d")
    rows: list[dict] = []
    ok = False
    try:
        rows = await asyncio.wait_for(asyncio.to_thread(_fetch_calendar, day), timeout=20)
        ok = True
    except Exception as e:
        logger.warning("经济日历抓取失败/超时，事件降级为空: %s", e)

    events = _process(rows, day) if rows else _fomc_events(day)
    return {
        "date": day,
        "updated": datetime.now(BEIJING).replace(microsecond=0).isoformat(),
        "events": events,
        "source_ok": ok,
        "source": "akshare_baidu + 手工日程",
    }


async def get_market_events() -> dict:
    """今日事件（Redis 缓存 30 分钟）。抓取失败不写缓存，避免把「源不可用」固化半小时。"""
    return await cached(
        "vibe:market_events", _build_events,
        category="market", ttl=1800,
        valid=lambda v: bool(v.get("source_ok")),
    )
