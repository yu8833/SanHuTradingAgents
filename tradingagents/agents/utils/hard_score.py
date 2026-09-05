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

# market 与 fundamentals 是 AccuracyGuardian 中权重最高的两位（1.5 / 1.3），
# 因此第一批落公式分；其余分析师暂 available=False，架构预留扩展。
_MARKET = "market"
_FUNDAMENTALS = "fundamentals"

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

    支持正负小数、百分比后缀（% 会被去掉）、千分位逗号。
    """
    for key in keys:
        pat = re.compile(
            rf"{re.escape(key)}\s*[：:]\s*([+-]?(?:\d[\d,]*\.?\d*|\d*\.\d+))(?:%|x|倍)?"
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
    texts = []
    for outputs in (tool_data or {}).values():
        if isinstance(outputs, list):
            texts.extend(str(o) for o in outputs)
        else:
            texts.append(str(outputs))
    blob = "\n".join(texts)

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


def compute_analyst_formula_scores(
    state: dict,
    analyst_tool_data: dict,
) -> dict:
    """按分析师计算公式分，返回 {analyst_type: FormulaScore}。

    analyst_tool_data: {analyst_type: {tool_name: [tool_output_str, ...]}}
        —— 由 parallel_analysts.run_single_analyst 拦截工具输出后写入 state。
    """
    scores: dict = {}
    scores[_MARKET] = _market_formula_score(state)
    fundamentals_tool_data = (analyst_tool_data or {}).get(_FUNDAMENTALS) or {}
    scores[_FUNDAMENTALS] = _fundamentals_formula_score(fundamentals_tool_data)
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


def formula_score_baseline_text(analyst_type: str, formula: int | None) -> str:
    """生成注入分析师 prompt 的「公式分基线」文案。

    - market：公式分在 prompt 阶段即可得（signal_score），注入数值基线；
    - fundamentals：数值需工具数据运行后才可计算，注入行为约束（无伪数字）；
    - 其余分析师：无公式分，返回空串。
    """
    if analyst_type == _MARKET and formula is not None:
        return (
            f"\n\n📐 **公式分基线**：技术面= {formula}/100（确定性公式，见快速扫描 signal_score）。"
            f"第一行评分必须等于或接近该基线；若偏离超过 {_DEFAULT_DEVIATION_THRESHOLD} 分，"
            f"须在同一段落明确给出偏离理由与依据的指标数值。"
        )
    if analyst_type == _FUNDAMENTALS:
        return (
            "\n\n📐 **量化口径约束**：第一行评分应与 `get_fundamentals`/财务工具返回的指标"
            "（ROE、净利润、PE/PB 等）所反映的基本面强弱保持一致；若明显背离，"
            "必须在同一段落给出具体数值依据作为偏离理由。"
        )
    return ""