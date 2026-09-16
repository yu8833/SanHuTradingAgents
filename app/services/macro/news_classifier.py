"""快讯分级（宏观快扫数据层 C 提供方）—— 复用财联社 + 东财 7x24 文字流 + 重要性分级规则。

设计文档《第六章·交易工具与日常流程》§5.3-C：
  - 复用 tradingagents/dataflows/news/realtime_news.py 的财联社 + 东财 7x24 文字流；
  - 新增重要性分级规则（关键词表）：货币政策（降准/降息/LPR/MLF/美联储）、财政（国常会/专项债）、
    数据（CPI/PPI/PMI/社融/非农）、地缘（关税/制裁）、监管（证监会/IPO/解禁）→ 高/中/低；
  - 过去 12-24h 窗口 + 去重 + 截断 top N。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# 个股新闻判定：标题含 6 位股票代码（如 "山东矿机(002526) 涨停"）
_STOCK_CODE_RE = re.compile(r"\b\d{6}\b")

# 重要性关键词表：高 / 中 / 低。命中优先级从高到低。
_HIGH_KEYWORDS = (
    # 货币政策
    "降准", "降息", "LPR", "MLF", "美联储", "加息", "利率决议", "联邦基金",
    # 财政
    "国常会", "专项债", "财政政策", "特别国债", "万亿",
    # 数据
    "CPI", "PPI", "PMI", "社融", "M2", "非农", "失业率", "GDP", "进出口",
    # 地缘
    "关税", "制裁", "贸易战", "地缘",
    # 监管
    "证监会", "IPO", "解禁", "退市", "印花税",
    # 市场级
    "降准降息", "央行", "政策", "国务院", "中央经济工作会议", "政治局会议",
)
# 全局宏观豁免词（用于区分"个股新闻"与"宏观级快讯"——仅当标题命中这些真正
# 的全局词时才不作为个股新闻压制；"证监会/政策/国务院"等机构词常伴随个股公告，
# 不纳入豁免，避免"金富科技…证监会批复"这类个股新闻被豁免）
_GLOBAL_KEYWORDS = (
    "降准", "降息", "LPR", "MLF", "央行", "美联储", "加息", "利率决议",
    "非农", "失业率", "CPI", "PPI", "PMI", "社融", "GDP",
    "关税", "制裁", "贸易战", "国常会", "政治局", "中央经济工作会议", "印花税",
)
# 个股动作关键词（标题命中即倾向个股新闻，除非同时命中全局宏观词）
_STOCK_ACTION_KW = re.compile(
    r"涨停|跌停|连板|中签|回购|增持|减持|定增|配股|可转债|批复|中标|签订|签署|"
    r"业绩预告|预增|预减|扭亏|获准|停牌|复牌|\d+板"
)


def _is_stock_news(title: str) -> bool:
    """个股新闻识别：含 6 位股票代码，或命中个股动作词（涨停/增持/批复…）且不含全局宏观词。"""
    if _STOCK_CODE_RE.search(title):
        return True
    if _STOCK_ACTION_KW.search(title) and not any(k in title for k in _GLOBAL_KEYWORDS):
        return True
    return False


# v5 事件指纹去重：不同来源对同一事件的报道措辞不同，title 精确去重失效。
# 指纹 = 大写英文专名（OpenAI/AAPL…）+ 数字金额（1.2万亿/92.4%…）+ 明确动作词。
# 两标题指纹交集 >=2 → 视为同一事件，保留先出现的。
_ACT_KW = ("融资", "收购", "并购", "降准", "降息", "加息", "IPO", "解禁", "回购",
           "增持", "减持", "制裁", "关税", "上市", "破产", "违约", "裁员", "下调")


def _event_fingerprint(title: str) -> frozenset:
    tokens: set[str] = set()
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9.]{2,}\b", title):
        tokens.add(m.group(0))
    for m in re.finditer(r"\d+(?:\.\d+)?(?:万亿|亿|万|%|点|基点|美元|元)?", title):
        tokens.add("NUM:" + m.group(0)[:14])
    for w in _ACT_KW:
        if w in title:
            tokens.add("ACT:" + w)
    return frozenset(tokens)


def _is_fp_duplicate(fp: frozenset, seen_fps: list[frozenset]) -> bool:
    for sf in seen_fps:
        if len(fp & sf) >= 2:
            return True
    return False

_MEDIUM_KEYWORDS = (
    "财报", "业绩", "涨停", "跌停", "回购", "增持", "减持", "重组", "并购",
    "指数", "大盘", "板块", "沪指", "深成指", "创业板", "北向资金", "主力资金",
    "通胀", "就业", "制造业", "零售", "工业增加值", "固定资产投资",
)

_LOW_KEYWORDS = (
    "新股", "中签", "分红", "送转", "解禁股", "公告", "停牌", "复牌",
)

# 主题分类关键词表（供 LLM / 前端标签）
_CATEGORY_KEYWORDS = {
    "货币政策": ("降准", "降息", "LPR", "MLF", "央行", "美联储", "加息", "利率"),
    "财政政策": ("国常会", "专项债", "特别国债", "财政", "减税"),
    "经济数据": ("CPI", "PPI", "PMI", "社融", "M2", "非农", "GDP", "失业率", "通胀", "制造业"),
    "地缘风险": ("关税", "制裁", "贸易战", "地缘", "战争", "冲突"),
    "市场监管": ("证监会", "IPO", "解禁", "退市", "印花税", "监管", "交易所"),
    "市场行情": ("指数", "大盘", "板块", "涨停", "跌停", "北向资金", "沪指", "创业板"),
}

# ── 影响度打分：利多/利空方向词表（确定性公式，不做 LLM 主观打分）──
_BULL_WORDS = (
    "利好", "提振", "上涨", "上调", "增长", "超预期", "回升", "扩张", "回暖",
    "宽松", "降准", "降息", "回购", "增持", "创新高", "突破", "改善", "走强",
    "录得增长", "大幅增长", "盈利预增", "签约", "中标", "获批", "豁免", "达成",
    # v5 补充：融资/并购/订单/提价/扩产等高频利多事件
    "融资", "IPO", "上市", "估值", "收购", "并购", "重组", "订单", "涨价", "提价",
    "扩产", "预增", "扭亏", "攀升", "升温", "上调评级", "首予",
    "大涨", "飙涨", "暴涨", "放量", "涨停潮", "抢筹", "大幅流入",
)
_BEAR_WORDS = (
    "利空", "下跌", "下挫", "衰退", "萎缩", "不及预期", "违约", "暴跌",
    "大跌", "制裁", "加征", "解禁", "减持", "亏损", "收缩", "走弱", "承压",
    "贬值", "收紧", "破产", "裁员", "腰斩", "拖累", "回落", "缩减",
    # "下调评级"单独保留（"下调"易与"下调利率/下调基准"等宽松语境混淆，从方向词表中剔除）
    "下调评级",
    # v5 补充：加息/缩表/新低/军费/防务/下修等高频利空事件
    "加息", "缩表", "新低", "降薪", "军费", "防务", "下修", "延期", "爆仓",
    "撤资", "债务危机", "股价腰斩", "退市", "暴雷", "资金链断裂",
)
# 强影响词（放大量级）。注意："创新高/新低"这类**无主语的词**不能作全局强词——
# 长标题句尾小商品"创新高"会把整条利空新闻带偏（标普新低被误判 +80 的教训），
# 因此从强词表移除，降为普通词，靠分句判定归属。
_BULL_STRONG = ("降准", "降息", "宽松", "超预期", "重磅", "重大利好")
_BEAR_STRONG = ("违约", "暴跌", "衰退", "危机", "制裁", "加征", "破产", "腰斩",
                "重大利空", "崩盘", "加息", "缩表", "新低")
# 英文方向词（标题为英文新闻时，lower 后匹配）
_BULL_WORDS_EN = ("bullish", "beat expectations", "raise", "upgrade", "outperform",
                  "buyback", "dividend", "record high", "growth", "surge", "rally",
                  "strong demand", "beat")
_BEAR_WORDS_EN = ("bearish", "miss expectations", "cut", "downgrade", "layoff",
                  "tariff", "sanction", "debt", "bankruptcy", "record low", "plunge",
                  "selloff", "slump", "recession", "default")
_BEAR_STRONG_EN = ("bankruptcy", "record low", "plunge", "selloff", "default", "recession")
# 语义降级词：弱证据（传闻/拟议/否认）——方向可保留但强度减半，避免把传闻当事实打分
_HEDGE_WORDS = ("否认", "辟谣", "澄清", "传闻", "考虑", "据悉", "拟", "据称")

# 类别 → 相关 A 股板块（供前端 chips 展示）
_CATEGORY_SECTORS = {
    "货币政策": ["银行", "券商", "地产", "保险"],
    "财政政策": ["基建", "建材", "工程机械", "水泥"],
    "经济数据": ["周期股", "消费", "上游资源", "汇率"],
    "地缘风险": ["军工", "黄金", "石油石化", "稀土"],
    "市场监管": ["券商", "次新股", "壳资源"],
    "市场行情": ["宽基指数", "券商", "市场情绪"],
    "个股": [],
    "其他": [],
}
# v5 细粒度板块：标题命中具体行业/题材词 → 用具体板块替换泛化模板（如"旅游板块"→旅游酒店，
# 而不是宽基指数/券商）。中文词 `in` 匹配；英文缩写词用 \b 词边界避免 OpenAI→AI 误匹配。
_SECTOR_KEYWORDS = (
    ("旅游", "旅游酒店"), ("白酒", "白酒"), ("医药", "医药生物"), ("创新药", "创新药"),
    ("半导体", "半导体"), ("芯片", "半导体"), ("光刻", "半导体设备"), ("军工", "国防军工"),
    ("黄金", "黄金"), ("券商", "券商"), ("银行", "银行"), ("保险", "保险"), ("地产", "房地产"),
    ("新能源", "新能源"), ("光伏", "光伏"), ("锂电", "锂电池"), ("储能", "储能"),
    ("汽车", "汽车"), ("智能驾驶", "智能驾驶"), ("机器人", "机器人"), ("人工智能", "AI算力"),
    ("算力", "AI算力"), ("数据中心", "算力租赁"), ("猪肉", "养殖业"), ("农业", "农业"),
    ("有色", "有色金属"), ("煤炭", "煤炭"), ("石油", "石油石化"), ("化工", "化工"),
    ("基建", "基建"), ("水泥", "建材"), ("钢铁", "钢铁"), ("消费电子", "消费电子"),
    ("光模块", "光模块"), ("液冷", "液冷"), ("卫星", "卫星互联网"), ("低空", "低空经济"),
    ("信创", "信创"), ("跨境电商", "跨境电商"), ("传媒", "传媒"), ("游戏", "游戏"),
    ("教育", "教育"), ("免税", "免税"), ("航空", "航空"), ("物流", "物流"),
    ("固态电池", "固态电池"), ("氢能", "氢能源"), ("核能", "核电"), ("风电", "风电"),
)
_SECTOR_KEYWORDS_RE = (
    (re.compile(r"\bAI\b"), "AI算力"),
    (re.compile(r"\bPCB\b"), "PCB"),
    (re.compile(r"\bCPO\b"), "CPO"),
)
# 类别 → 解读模板
_CATEGORY_ANALYSIS = {
    "货币政策": "流动性信号，直接作用于资金面与风险偏好",
    "财政政策": "财政发力信号，利好基建产业链与总需求",
    "经济数据": "基本面数据，影响经济预期与周期板块表现",
    "地缘风险": "外部风险扰动，避险资产与军工资源受益",
    "市场监管": "监管动向，影响对应行业短期情绪",
    "市场行情": "市场情绪面信号，参考作用大于方向指引",
    "个股": "个股层面事件，对指数影响有限",
    "其他": "与市场关联度待观察",
}

_IMPACT_BASE = {"high": 50, "medium": 30, "low": 12}


def _split_clauses(title: str) -> list[str]:
    """按标点切成短句，逐句判定方向——避免长标题被句尾小词的强词带偏整条（如"标普新低+柴油创新高"）。"""
    parts = re.split(r"[，,。；;：:！!？?|、/\s]+", title)
    return [p.strip() for p in parts if p.strip()]


def _clause_hits(clause: str, lower: str) -> tuple[int, int, int]:
    """单句词命中：(bull_hits, bear_hits, strong_net)。

    strong_net = 该句强利多 +30/条 − 强利空 +30/条（正=偏多，负=偏空）。
    """
    bull = sum(1 for w in _BULL_WORDS if w in clause)
    bear = sum(1 for w in _BEAR_WORDS if w in clause)
    bull += sum(1 for w in _BULL_WORDS_EN if w in lower)
    bear += sum(1 for w in _BEAR_WORDS_EN if w in lower)
    s = 0
    for w in _BULL_STRONG:
        if w in clause:
            s += 30
    for w in _BEAR_STRONG:
        if w in clause:
            s -= 30
    for w in _BEAR_STRONG_EN:
        if w in lower:
            s -= 30
    return bull, bear, s


def _clause_direction(clause: str, lower: str) -> str | None:
    """单句方向：普通词多数定向；平手时该句强词定向；否则 None。"""
    bull, bear, s = _clause_hits(clause, lower)
    if bull > bear:
        return "bull"
    if bear > bull:
        return "bear"
    if s > 0:
        return "bull"
    if s < 0:
        return "bear"
    return None


def score_news_item(item: dict) -> dict:
    """对单条快讯做影响度打分 + 规则解读（确定性公式）。

    输出（并入原 item）：
      impact_score : -100 ~ +100（利多为正、利空为负、中性为 0）
      direction    : bull / bear / neutral
      impact_level : 强 / 中 / 弱
      analysis     : 一句话解读（方向判定 + 类别模板）
      related_sectors: 相关 A 股板块列表

    打分逻辑（v5）：
      - 长标题（>25 字）按标点切句，逐句判定方向后多数投票；
        "创新高/新低"等无主语词不再作全局强词，避免句尾小词带偏整条；
      - 短标题（<=25 字）整条统一判定，强词可定方向；
      - 传闻/拟议类弱证据词（否认/传闻/考虑/据悉…）方向保留、强度减半；
      - 英文标题按小写英文词表打分。
    """
    title = str(item.get("title") or "")
    lower = title.lower()
    hedged = any(w in title for w in _HEDGE_WORDS)
    is_short = len(title) <= 25
    clauses = _split_clauses(title)

    if is_short:
        bull_total, bear_total, strong_net = _clause_hits(title, lower)
        if bull_total > bear_total or (strong_net > 0 and bull_total >= bear_total):
            direction = "bull"
        elif bear_total > bull_total or (strong_net < 0 and bear_total >= bull_total):
            direction = "bear"
        else:
            direction = "neutral"
    else:
        bull_clauses = sum(1 for c in clauses if _clause_direction(c, lower) == "bull")
        bear_clauses = sum(1 for c in clauses if _clause_direction(c, lower) == "bear")
        _bt, _be, strong_net = _clause_hits(title, lower)
        if bull_clauses > bear_clauses:
            direction = "bull"
        elif bear_clauses > bull_clauses:
            direction = "bear"
        elif strong_net > 0:
            direction = "bull"
        elif strong_net < 0:
            direction = "bear"
        else:
            direction = "neutral"

    base = _IMPACT_BASE.get(str(item.get("importance") or "low"), 12)
    if direction == "neutral":
        score = 0
    else:
        # 强度 = 全标题强词净贡献（短标题全额；长标题已由分句投票定向，强度仍可叠加）
        strength = abs(strong_net)
        if hedged:
            strength = int(strength / 2)  # 传闻/拟议：强度减半，方向保留
        score = base + strength if direction == "bull" else -(base + strength)
    score = max(-100, min(100, score))

    category = str(item.get("category") or "其他")
    # v5 板块：标题命中具体行业/题材词 → 以具体板块为主（替换"宽基指数/市场情绪"泛化模板）
    specific = [tag for kw, tag in _SECTOR_KEYWORDS if kw in title]
    specific += [tag for rx, tag in _SECTOR_KEYWORDS_RE if rx.search(title)]
    base_sectors = list(_CATEGORY_SECTORS.get(category, []))
    if specific:
        kept = [s for s in base_sectors if s in title or s in specific]
        sectors = list(dict.fromkeys([*kept, *specific]))[:4]
    else:
        sectors = base_sectors
    cat_analysis = _CATEGORY_ANALYSIS.get(category, "与市场关联度待观察")

    if direction == "bull":
        analysis = f"偏利好：{cat_analysis}"
        if sectors:
            analysis += f"，相关板块 {', '.join(sectors)} 可能受益"
    elif direction == "bear":
        analysis = f"偏利空：{cat_analysis}"
        if sectors:
            analysis += f"，注意 {', '.join(sectors)} 承压风险"
    else:
        analysis = f"中性：{cat_analysis}，暂不据此调整仓位"

    # v5 影响等级语义：中性方向显示"中性"，避免与前端"重大/重要"标签产生"重大+弱影响"的矛盾观感
    if direction == "neutral":
        level = "中性"
    else:
        level = "强" if abs(score) >= 60 else ("中" if abs(score) >= 30 else "弱")
    return {
        **item,
        "impact_score": score,
        "direction": direction,
        "impact_level": level,
        "analysis": analysis,
        "related_sectors": sectors,
    }


def _classify_importance(title: str) -> str:
    """重要性分级：高 > 中 > 低。"""
    for kw in _HIGH_KEYWORDS:
        if kw in title:
            return "high"
    for kw in _MEDIUM_KEYWORDS:
        if kw in title:
            return "medium"
    for kw in _LOW_KEYWORDS:
        if kw in title:
            return "low"
    return "low"


def _classify_category(title: str) -> str:
    # v5 前置规则：先于关键词表，修正高频误配
    # 1) 成交额/成交量语境 → 市场行情（"成交额1.62万亿"不应因"万亿"归财政政策）
    if "成交额" in title or "成交量" in title or "成交" in title:
        return "市场行情"
    # 2) 融资/估值/并购 → 企业/科技事件，不套财政模板（OpenAI 融资 ≠ 财政政策）；
    #    IPO 不在此列（"证监会IPO"属市场监管，走关键词表）
    if any(k in title for k in ("融资", "估值", "收购", "并购", "融资规模")):
        return "其他"
    # 3) 军事/防务/军费 → 地缘风险
    if any(k in title for k in ("防务", "军费", "军事", "国防", "扩军")):
        return "地缘风险"
    # 关键词表优先（含降准/降息/央行等货币政策词，避免被"万亿"兜底抢归市场行情）
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in title for kw in kws):
            return cat
    # 4) "万亿"兜底：关键词表未命中时，仅财政语境词才归财政政策，否则市场行情
    if "万亿" in title:
        if any(k in title for k in ("国常会", "专项债", "特别国债", "财政", "减税", "投资", "基建")):
            return "财政政策"
        return "市场行情"
    return "其他"


def classify_news_item(item: dict) -> dict:
    """对单条快讯打重要性 + 主题标签。入参为统一结构 {title, content, source, publish_time}。"""
    title = str(item.get("title") or "") or str(item.get("content") or "")[:60]
    return {
        **item,
        "importance": _classify_importance(title),
        "category": _classify_category(title),
    }


def _fetch_macro_news(hours_back: int = 24, top_n: int = 40) -> list[dict]:
    """抓取多源市场级快讯（财联社 + 东财 7x24 文字流 + 资讯雷达 108 个公开 RSS），
    分级 + 时间窗口 + 去重 + 截断。

    数据源：
      1) RealtimeNewsAggregator（tradingagents core：财联社 + 东财 7x24 文字流）；
      2) newsradar（app/services/newsradar：12 赛道 108 个公开 RSS 源，与"资讯雷达"页同源）；
    个股新闻压制：标题含 6 位股票代码、且未命中全局高重要性关键词（降准/加息/关税等）的
    个股公告/异动类新闻最高降为 low，避免"XX 涨停"被误标为高/中混入"重要快讯"。

    返回统一结构：{title, content, source, publish_time, importance, category}。
    """
    rows: list[dict] = []

    # 数据源 1：财联社 + 东财 7x24 文字流
    try:
        from tradingagents.dataflows.news.realtime_news import RealtimeNewsAggregator
        agg = RealtimeNewsAggregator()
        items = agg.get_realtime_stock_news(symbol=None, hours_back=hours_back, max_news=60)
        for n in items:
            pub = n.publish_time
            # 无时间戳者保留（无法判断窗口）；有时间戳者过滤出窗口内
            if pub is not None and pub < datetime.now() - timedelta(hours=hours_back):
                continue
            rows.append({
                "title": n.title,
                "content": (n.content or "")[:200],
                "source": n.source,
                "publish_time": pub.isoformat() if pub else "",
                "url": getattr(n, "url", "") or "",
            })
    except Exception as e:
        logger.warning(f"实时快讯（财联社/东财）获取失败: {e}")

    # 数据源 2：资讯雷达（108 个公开 RSS 源，与资讯雷达页同源）。
    # 同步抓取（与财联社源一致，频率低：宏观快照 8:15/手动刷新时执行一次）。
    radar_data = None
    try:
        from app.services.newsradar import fetch_radar
        radar_data = fetch_radar()
    except Exception as e:
        logger.warning(f"资讯雷达源不可用: {e}")

    if radar_data:
        cnt = 0
        for ind in radar_data.get("industries") or []:
            for it in ind.get("items") or []:
                title = str(it.get("title") or "").strip()
                if not title:
                    continue
                ts = it.get("ts") or 0
                rows.append({
                    "title": title,
                    "content": str(it.get("summary") or "")[:200],
                    "source": f"资讯雷达·{it.get('source') or ind.get('name') or 'RSS'}",
                    "publish_time": datetime.fromtimestamp(int(ts)).isoformat() if ts else "",
                    "url": it.get("url") or "",
                })
                cnt += 1
        if cnt:
            logger.info(f"资讯雷达并入 {cnt} 条快讯（多源）")

    unique: list[dict] = []
    seen: set[str] = set()
    seen_fps: list[frozenset] = []
    for r in rows:
        key = r["title"].strip()
        if not key or key in seen:
            continue
        fp = _event_fingerprint(key)
        if len(fp) >= 2 and _is_fp_duplicate(fp, seen_fps):
            continue  # 同事件多来源（如 OpenAI 融资被多家媒体以不同措辞报道）
        seen.add(key)
        seen_fps.append(fp)
        unique.append(r)

    # 分级（高优先排在前面），再按时间倒序；个股新闻压制；最后统一影响度打分
    for r in unique:
        r.update({"importance": _classify_importance(r["title"]),
                  "category": _classify_category(r["title"])})
        if _is_stock_news(r["title"]):
            r["importance"] = "low"   # 个股异动/公告类：不构成"重要"级
            r["category"] = "个股"
    unique = [score_news_item(r) for r in unique]

    def _ts(r: dict) -> float:
        try:
            return datetime.fromisoformat(r["publish_time"]).timestamp() if r["publish_time"] else 0.0
        except ValueError:
            return 0.0

    unique.sort(key=lambda r: (
        0 if r["importance"] == "high" else 1 if r["importance"] == "medium" else 2,
        -_ts(r),
    ))
    return unique[:top_n]


async def get_macro_news(hours_back: int = 24, top_n: int = 40) -> list[dict]:
    """分级快讯（缓存 5min/1h）。v2：多源合并（财联社/东财 + 资讯雷达）+ 个股压制。
    v4：逐条影响度打分（impact_score / direction / analysis / related_sectors）。
    v5：分句判定方向（修"句尾小词创新高带偏整条"）+ 词表补全（加息/融资/英文/新低等）
        + 分类前置规则（成交额/融资/防务/万亿语境）+ 传闻降级。"""
    return await cached(
        f"macro:news:v5:{hours_back}:{top_n}",
        lambda: _fetch_macro_news(hours_back, top_n),
        category="news",
        valid=bool,
    )
