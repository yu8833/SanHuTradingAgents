"""分析师「XX/100 评分」公式化硬打分 —— 把 LLM 主观评分转成可验证的量化环节。

背景：
- 7 位分析师报告的第一行是「## 📊 技术面评分：XX/100」等，该数字此前完全由 LLM
  依据工具数据主观给出，不可复现、无法校验。
- 系统已有确定性公式分：技术面 = StockTrendAnalyzer.signal_score
  （app/services/stock_analyzer/stock_analyzer.py，趋势30+乖离20+量能15+支撑10+MACD15+RSI10=100），
  经 quick_analysis_result 注入图 state；基本面可从工具返回的键值行文本解析财务指标静态计分。

本模块职责：
- compute_analyst_formula_scores(state, analyst_tool_data)：按分析师计算公式分（暂无公式的
  analyst 返回 available=False，保持 LLM 主观并显式标注）。
- extract_report_score(report, analyst_type)：正则解析报告第一行的 XX/100。
- score_deviation_tag(...)：LLM 分与公式分偏差 > 阈值且无「偏离/不采用」说明时，生成标注文案。

设计口径：公式分是「弱基线」而非无可辩驳的权威 —— LLM 可在报告中给出偏离理由，
只要如实标注，不阻断分析，仅由下游质量门控据此降级。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 7 位分析师全部落公式分（policy 恒 unavailable）：
# - market / fundamentals：权重最高两位（AccuracyGuardian 1.5 / 1.3），第一批落地；
# - news / hot_money / social / lockup：从确定性工具输出推导弱基线（第二批）；
# - policy：纯文本无确定性数值，保持 available=False（弱基线哲学）。
_MARKET = "market"
_FUNDAMENTALS = "fundamentals"
_NEWS = "news"
_HOT_MONEY = "hot_money"
_SOCIAL = "social"
_LOCKUP = "lockup"
_POLICY = "policy"

_ALL_FORMULA_ANALYSTS = (_MARKET, _FUNDAMENTALS, _NEWS, _HOT_MONEY, _SOCIAL, _LOCKUP)

_ANALYST_CN = {
    _MARKET: "技术面",
    _FUNDAMENTALS: "基本面",
    _NEWS: "消息面",
    _HOT_MONEY: "资金面",
    _SOCIAL: "情绪面",
    _LOCKUP: "解禁面",
    _POLICY: "政策面",
}

# LLM 分与公式分允许的最大偏差；超过需在报告中给出偏离说明并由质量门控降级
_DEFAULT_DEVIATION_THRESHOLD = 20


@dataclass
class FormulaScore:
    """某分析师的公式化硬得分（确定性、可复现）。"""

    analyst_type: str
    score: int
    available: bool
    source: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "analyst_type": self.analyst_type,
            "score": self.score,
            "available": self.available,
            "source": self.source,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# 数值提取工具（对 a_stock / akshare_vendor 两种键值行文本统一解析）
# ---------------------------------------------------------------------------


def _find_number(text: str, keys: list[str]) -> float | None:
    """在键值行文本中查找形如 `KEY: 数值` 的首个数字。

    兼容项（针对工具实际输出格式）：
      - 键可能被 markdown 加粗包裹：`**风险安全分**: 90`
      - 分隔符支持冒号 `:`/`：` 或等号 `=`/`＝`：`主力净流入=8500万元`
      - 数值后缀支持 `%`/`x`/`倍`/`/100` 等（只提取数字本体，忽略后缀）
    支持正负小数、千分位逗号。
    """
    for key in keys:
        # 前后可选 de markdown `**`，键后可选空白、分隔符、空白
        pat = re.compile(
            rf"\*{{0,2}}{re.escape(key)}\*{{0,2}}\s*[：:＝=]\s*"
            rf"([+-]?(?:\d[\d,]*\.?\d*|\d*\.\d+))(?:%|x|倍|/\d+)?"
        )
        m = pat.search(text or "")
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(value))))


def _flatten_tool_text(tool_data: dict) -> str:
    """把 {tool_name: [output_str, ...]} 扁平化为单个文本块（供公式分解析）。"""
    texts = []
    for outputs in (tool_data or {}).values():
        if isinstance(outputs, list):
            texts.extend(str(o) for o in outputs)
        else:
            texts.append(str(outputs))
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# 公式分计算
# ---------------------------------------------------------------------------


def _market_formula_score(state: dict) -> FormulaScore | None:
    """技术面公式分：复用快速扫描的确定性 signal_score（0-100）。"""
    qa = (state or {}).get("quick_analysis_result") or {}
    signal_score = qa.get("signal_score")
    if signal_score is None:
        return FormulaScore(_MARKET, 0, False, "unavailable")
    try:
        score = _clamp(float(signal_score))
    except (TypeError, ValueError):
        return FormulaScore(_MARKET, 0, False, "unavailable")
    return FormulaScore(
        _MARKET,
        score,
        True,
        "quick_scan_signal_score",
        notes=["技术面确定性公式：趋势30+乖离20+量能15+支撑10+MACD15+RSI10=100"],
    )


def _fundamentals_formula_score(tool_data: dict) -> FormulaScore | None:
    """基本面公式分：从 get_fundamentals/get_profit_forecast 的键值行文本静态计分。

    静态计分（弱基线，不代表完整财务模型）：
      - 基准 50；ROE：≥15 → +15 / 8-15 → +8 / 0-8 → +2 / 负 → -20
      - 净利：>0 → +10 / ≤0 → -15
      - PE(TTM)：0-30 → +10 / 30-60 → +0 / 亏损(≤0) → -5 / >60 → -5
      - PB：0-5 → +5 / >10 → -3
      - PEG：0-1 → +5 / >1 → -1
    只有至少解析到 ROE / 净利 / PE 之一才 available=True。
    """
    blob = _flatten_tool_text(tool_data)

    roe = _find_number(blob, ["ROE (%)", "ROE"])
    net_profit = _find_number(blob, ["Net Profit", "净利润"])
    pe_ttm = _find_number(blob, ["PE (TTM)", "PE(TTM)", "市盈率"])
    pb = _find_number(blob, ["PB"])
    peg = _find_number(blob, ["PEG"])

    known = [v for v in (roe, net_profit, pe_ttm) if v is not None]
    if not known:
        return FormulaScore(_FUNDAMENTALS, 0, False, "unavailable",
                            notes=["未解析到 ROE/净利/PE，公式分不可用"])

    score = 50.0
    notes: list[str] = []
    if roe is not None:
        if roe >= 15:
            score += 15
        elif roe >= 8:
            score += 8
        elif roe >= 0:
            score += 2
        else:
            score -= 20
        notes.append(f"ROE={roe:.1f}%")
    if net_profit is not None:
        if net_profit > 0:
            score += 10
        else:
            score -= 15
        notes.append("净利为正" if net_profit > 0 else "净利未盈利")
    if pe_ttm is not None:
        if 0 < pe_ttm <= 30:
            score += 10
        elif 30 < pe_ttm <= 60:
            pass
        elif pe_ttm <= 0:
            score -= 5
        else:
            score -= 5
        notes.append(f"PE(TTM)={pe_ttm:.1f}")
    if pb is not None:
        if 0 < pb <= 5:
            score += 5
        elif pb > 10:
            score -= 3
    if peg is not None:
        if 0 < peg <= 1:
            score += 5
        elif peg > 1:
            score -= 1

    return FormulaScore(
        _FUNDAMENTALS,
        _clamp(score),
        True,
        "fundamentals_static",
        notes=notes + ["弱基线静态计分，非完整财务模型"],
    )


def _news_formula_score(tool_data: dict) -> FormulaScore | None:
    """消息面公式分：从 get_risk_scan 的「风险安全分」推导。

    通达信风险扫描确定性输出：风险安全分 = 100 - 风险项数*5（越高越安全）。
    公式：50 + (safety - 50) * 0.8 —— 以监管/交易风险为锚的弱基线
    （未纳入新闻事件强度，属保守口径；LLM 可结合新闻给偏离理由）。
    """
    blob = _flatten_tool_text(tool_data)
    safety = _find_number(blob, ["风险安全分"])
    if safety is None:
        return FormulaScore(
            _NEWS, 0, False, "unavailable",
            notes=["未解析到风险安全分（get_risk_scan 无输出），公式分不可用"],
        )
    score = 50 + (safety - 50) * 0.8
    return FormulaScore(
        _NEWS,
        _clamp(score),
        True,
        "risk_scan_safety",
        notes=[f"风险安全分={safety:.0f}", "弱基线：以监管/交易风险为锚，未含新闻事件强度"],
    )


def _hot_money_formula_score(tool_data: dict) -> FormulaScore | None:
    """资金面公式分：主力净流入方向 ±15、北向 INFLOW/OUTFLOW ±10、龙虎榜 +5。

    确定性数据源：get_fund_flow（`Close: 主力净流入=...万元`）、
    get_northbound_flow（`Signal: Net northbound INFLOW/OUTFLOW`）、
    get_dragon_tiger_board（`## 上榜记录` 段）。
    至少命中一项才 available=True。
    """
    blob = _flatten_tool_text(tool_data)
    score = 50.0
    notes: list[str] = []
    hit = False

    main_net = _find_number(blob, ["主力净流入"])
    if main_net is not None:
        if main_net > 0:
            score += 15
            notes.append(f"主力净流入={main_net:.0f}万元")
        else:
            score -= 15
            notes.append(f"主力净流出={abs(main_net):.0f}万元")
        hit = True

    if "Signal: Net northbound INFLOW" in blob:
        score += 10
        notes.append("北向净流入")
        hit = True
    elif "Signal: Net northbound OUTFLOW" in blob:
        score -= 10
        notes.append("北向净流出")
        hit = True

    if "## 上榜记录" in blob:
        score += 5
        notes.append("龙虎榜有上榜记录")
        hit = True

    if not hit:
        return FormulaScore(
            _HOT_MONEY, 0, False, "unavailable",
            notes=["未解析到主力/北向/龙虎榜数据，公式分不可用"],
        )
    return FormulaScore(_HOT_MONEY, _clamp(score), True, "fund_flow_static", notes)


def _social_formula_score(tool_data: dict) -> FormulaScore | None:
    """情绪面公式分：主力净流入方向 ±12、股东户数显著变化 ±8。

    确定性数据源：get_fund_flow（主力净流入方向）、
    get_shareholder_concentration（`📈 信号: 股东户数显著下降…` / `📉 信号: …增加…`）。
    至少命中一项才 available=True。
    """
    blob = _flatten_tool_text(tool_data)
    score = 50.0
    notes: list[str] = []
    hit = False

    main_net = _find_number(blob, ["主力净流入"])
    if main_net is not None:
        if main_net > 0:
            score += 12
            notes.append("主力净流入")
        else:
            score -= 12
            notes.append("主力净流出")
        hit = True

    if "股东户数显著下降" in blob:
        score += 8
        notes.append("股东户数显著下降（筹码集中）")
        hit = True
    elif "股东户数显著增加" in blob:
        score -= 8
        notes.append("股东户数显著增加（筹码分散）")
        hit = True
    elif ("股东户数变化不大" in blob) or ("筹码集中度稳定" in blob):
        # 中性信号：已解析到股东户数数据，但方向中性，不加不减
        notes.append("股东户数变化不大（筹码集中度稳定）")
        hit = True

    if not hit:
        return FormulaScore(
            _SOCIAL, 0, False, "unavailable",
            notes=["未解析到主力资金/股东户数数据，公式分不可用"],
        )
    return FormulaScore(_SOCIAL, _clamp(score), True, "sentiment_static", notes)


def _lockup_formula_score(tool_data: dict) -> FormulaScore | None:
    """解禁面公式分：30 天内解禁 -25、90 天内 -10、无待解禁 +10。

    确定性数据源：get_lockup_expiry 的「未来待解禁」段
    （`## 未来 {N} 天待解禁` + 行 `YYYY-MM-DD | 类型 | 数量 | 占比`）。
    参考日期取输出头部 `# 限售解禁日历 | code | trade_date`；
    历史解禁记录段在「未来」段之前，天然被排除。
    """
    from datetime import datetime

    blob = _flatten_tool_text(tool_data)

    if re.search(r"未来\s+\d+\s*天无待解禁", blob):
        return FormulaScore(
            _LOCKUP, _clamp(50 + 10), True, "lockup_calendar",
            notes=["未来无待解禁"],
        )

    seg = re.search(r"##\s*未来\s+\d+\s*天待解禁", blob)
    if not seg:
        return FormulaScore(
            _LOCKUP, 0, False, "unavailable",
            notes=["未解析到待解禁数据（无输出或查询失败），公式分不可用"],
        )

    # 参考日期：`# 限售解禁日历 | code | trade_date`
    ref = None
    hm = re.search(r"#\s*限售解禁日历\s*\|\s*\S+\s*\|\s*(\d{4}-\d{2}-\d{2})", blob)
    if hm:
        try:
            ref = datetime.strptime(hm.group(1), "%Y-%m-%d").date()
        except ValueError:
            ref = None

    # 仅在未来待解禁段内解析解禁日期，计算距参考日期的天数
    future_part = blob[seg.end():]
    min_days = None
    for dm in re.finditer(r"(?m)^\s*(\d{4}-\d{2}-\d{2})\s*\|", future_part):
        try:
            d = datetime.strptime(dm.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if ref is not None:
            days = (d - ref).days
            if days < 0:
                continue  # 防御：历史行误入未来段
            min_days = days if min_days is None else min(min_days, days)
        else:
            min_days = 0  # 参考日期不可解析 → 按最保守（<=30 天）处理
            break

    if min_days is None:
        return FormulaScore(
            _LOCKUP, _clamp(50 - 10), True, "lockup_calendar",
            notes=["有待解禁段但解禁日期无法解析，保守计分"],
        )
    if min_days <= 30:
        return FormulaScore(
            _LOCKUP, _clamp(50 - 25), True, "lockup_calendar",
            notes=[f"{min_days} 天内有解禁（<=30 天）"],
        )
    return FormulaScore(
        _LOCKUP, _clamp(50 - 10), True, "lockup_calendar",
        notes=[f"{min_days} 天后有解禁（30-90 天）"],
    )


def compute_analyst_formula_scores(
    state: dict,
    analyst_tool_data: dict,
) -> dict:
    """按分析师计算公式分，返回 {analyst_type: FormulaScore}。

    analyst_tool_data: {analyst_type: {tool_name: [tool_output_str, ...]}}
        —— 由 parallel_analysts.run_single_analyst 拦截工具输出后写入 state。
    market 从 state.quick_analysis_result 取 signal_score（无需工具数据）；
    其余分析师按各自确定性工具输出计算；policy 恒 unavailable。
    """
    scores: dict = {}
    scores[_MARKET] = _market_formula_score(state)
    for analyst_type, func in (
        (_FUNDAMENTALS, _fundamentals_formula_score),
        (_NEWS, _news_formula_score),
        (_HOT_MONEY, _hot_money_formula_score),
        (_SOCIAL, _social_formula_score),
        (_LOCKUP, _lockup_formula_score),
    ):
        tool_data = (analyst_tool_data or {}).get(analyst_type) or {}
        scores[analyst_type] = func(tool_data)
    scores[_POLICY] = FormulaScore(
        _POLICY, 0, False, "unavailable",
        notes=["政策面纯文本无确定性数值，保持 LLM 主观评分"],
    )
    return scores


def get_formula_score(state: dict, analyst_type: str) -> int | None:
    """从 state._formula_scores 取某分析师的公式分（available=False 返回 None）。"""
    entries = (state or {}).get("_formula_scores") or {}
    entry = entries.get(analyst_type) or {}
    if not entry.get("available"):
        return None
    return entry.get("score")


# ---------------------------------------------------------------------------
# 报告评分解析 与 偏差标注
# ---------------------------------------------------------------------------

_SCORE_PATTERNS = {
    "market": re.compile(r"##\s*📊\s*技术面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "fundamentals": re.compile(r"##\s*📈\s*基本面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "news": re.compile(r"##\s*📰\s*消息面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "hot_money": re.compile(r"##\s*💰\s*资金面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "social": re.compile(r"##\s*💭\s*情绪面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "lockup": re.compile(r"##\s*🔓\s*解禁面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
    "policy": re.compile(r"##\s*🏛️\s*政策面评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?"),
}


def extract_report_score(report: str, analyst_type: str) -> int | None:
    """解析报告第一行的 XX/100 评分（LLM 给出）。无法解析返回 None。"""
    if not report:
        return None
    head = report[:500]
    pattern = _SCORE_PATTERNS.get(analyst_type)
    if pattern:
        m = pattern.search(head)
        if m:
            try:
                return _clamp(float(m.group(1)))
            except ValueError:
                return None
    # 通用兜底：任意「评分：XX」形态（限前 300 字符，避免误取正文数值）
    generic = re.search(r"评分\s*[：:]\s*(\d{1,3})(?:\s*/\s*100)?", head[:300])
    if generic:
        try:
            return _clamp(float(generic.group(1)))
        except ValueError:
            return None
    return None


# 报告中对公式分偏差给出过理由的提示词（命中即视为已说明，不标注）
_JUSTIFIED_MARKERS = ("偏离", "不采用", "与公式分", "公式基线", "未采用公式")


def score_deviation_tag(
    formula: int | None,
    llm_score: int | None,
    report: str = "",
    threshold: int = _DEFAULT_DEVIATION_THRESHOLD,
) -> str:
    """LLM 分与公式分偏差 > threshold 且报告未说明理由时，生成标注文案。"""
    if formula is None or llm_score is None:
        return ""
    if abs(llm_score - formula) <= threshold:
        return ""
    if any(marker in (report or "")[:2000] for marker in _JUSTIFIED_MARKERS):
        return ""
    return f"[⚠️ 公式分偏差: LLM={llm_score} vs 公式={formula}]"


# prompt 阶段（工具尚未运行）各分析师的量化口径约束文案
_BEHAVIOR_CONSTRAINTS = {
    _FUNDAMENTALS: (
        "第一行评分应与 `get_fundamentals`/财务工具返回的指标"
        "（ROE、净利润、PE/PB 等）所反映的基本面强弱保持一致"
    ),
    _NEWS: (
        "第一行评分应与 `get_risk_scan` 返回的「风险安全分」及新闻事件"
        "（利好/利空清单）所反映的消息面强弱保持一致"
    ),
    _HOT_MONEY: (
        "第一行评分应与 `get_fund_flow`/`get_northbound_flow`/龙虎榜返回的"
        "资金数据（主力净流入方向、北向流向、上榜情况）所反映的资金面强弱保持一致"
    ),
    _SOCIAL: (
        "第一行评分应与 `get_fund_flow` 主力净流入方向、"
        "`get_shareholder_concentration` 股东户数变化所反映的情绪强弱保持一致"
    ),
    _LOCKUP: (
        "第一行评分应与 `get_lockup_expiry` 返回的待解禁日历"
        "（30/90 天内解禁、无待解禁）所反映的解禁压力保持一致"
    ),
}


def _numeric_baseline_text(analyst_type: str, formula: int) -> str:
    """数值基线文案：注入确定性公式分，要求 LLM 接近或说明偏离理由。"""
    cn = _ANALYST_CN.get(analyst_type, analyst_type)
    return (
        f"\n\n📐 **公式分基线**：{cn}= {formula}/100（确定性公式，见工具返回数据）。"
        f"第一行评分必须等于或接近该基线；若偏离超过 {_DEFAULT_DEVIATION_THRESHOLD} 分，"
        f"须在同一段落明确给出偏离理由与依据的指标数值。"
    )


def formula_score_baseline_text(analyst_type: str, formula: int | None) -> str:
    """生成注入分析师 prompt 的「公式分基线/量化口径约束」文案。

    - 公式分在 prompt 阶段可得（market 的 signal_score）→ 数值基线；
    - 其余已落公式的分析师在 prompt 阶段公式未算 → 行为约束（无伪数字）；
    - policy 及无公式分分析师 → 空串。
    """
    if analyst_type in _ALL_FORMULA_ANALYSTS and formula is not None:
        return _numeric_baseline_text(analyst_type, formula)
    constraint = _BEHAVIOR_CONSTRAINTS.get(analyst_type)
    if constraint:
        return (
            f"\n\n📐 **量化口径约束**：{constraint}；若明显背离，"
            f"必须在同一段落给出具体数值依据作为偏离理由。"
        )
    return ""