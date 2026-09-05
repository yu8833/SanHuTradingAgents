"""Prompt 输入压缩工具 —— 把全文重述改为「评分 + 关键参数」摘要投喂。

背景：组合经理/风控辩论等深层节点会把 7 份分析师报告 + 决策全文逐字重述进 prompt，
输入上下文巨大，DeepSeek V4 thinking 模式下每次调用要几十分钟（长输入 → 长推理）。
本模块做**确定性压缩**（非 LLM 摘要，零额外成本、可控）：
- 保留头部（评分标题/评级/导读）
- 保留关键行（评分/评级/置信度/止损/仓位/目标/风险/结论等）
- 保留尾部（风险提示/结论常在文末）
- 其余正文截断并标记，绝不改变原文字面

默认保留量按调用方传参控制；文本短于阈值时原样返回（零开销）。
"""

from __future__ import annotations

# 关键行命中词：评分/评级/参数/风险/结论等决策依据行
_KEY_LINE_MARKERS = (
    "评分", "评级", "置信度", "止损", "仓位", "最大可接受亏损",
    "目标", "风险", "结论", "建议", "支撑", "阻力", "要点",
    "催化剂", "概率", "卖出", "买入", "减持", "增持", "持有",
    "偏离", "拐点", "背离", "放量", "缩量", "金叉", "死叉",
)

# 尾部行数上限（结论/风险提示通常在文末）
_TAIL_LINES = 12


def _mark_compressed(original_len: int) -> str:
    return f"\n\n[…] 原文 {original_len} 字符已压缩，仅保留评分与关键依据行。"


def compact_markdown(text: str | None, keep: int = 700) -> str:
    """确定性压缩 Markdown 文本到约 `keep` 字符（评分+关键行+尾部，可读性保序）。

    - 头部（评分/导读）：分配 keep 的 55%（按行累积，超预算即止）
    - 关键行（评分/评级/止损/仓位/风险等）：分配 keep 的 30%
    - 尾部（结论/风险提示）：分配 keep 的 15%
    text 为空或长度 ≤ keep 时原样返回。
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= keep:
        return text

    lines = text.splitlines()
    head_budget = int(keep * 0.55)
    tail_budget = int(keep * 0.15)

    # 头部：按字符预算累积
    head_lines: list[str] = []
    head_len = 0
    for ln in lines:
        if head_len + len(ln) > head_budget:
            break
        head_lines.append(ln)
        head_len += len(ln) + 1
    if not head_lines:  # 首行就超预算（极长行）时保底取首行截断
        head_lines = [lines[0][:head_budget]]

    # 关键行：头部之后按关键词过滤，保序去重 + 字符预算
    seen = set(head_lines)
    keys: list[str] = []
    budget = int(keep * 0.30)
    used = 0
    for ln in lines[len(head_lines):]:
        s = ln.strip()
        if not s or s in seen:
            continue
        if any(m in s for m in _KEY_LINE_MARKERS):
            keys.append(s)
            seen.add(s)
            used += len(s)
            if used >= budget:
                break

    # 尾部：按字符预算累积（去重）
    tail_lines: list[str] = []
    tail_len = 0
    for ln in reversed(lines[-_TAIL_LINES:]):
        s = ln.strip()
        if not s or s in seen or any(s == o for o in tail_lines):
            continue
        if tail_len + len(s) > tail_budget:
            break
        tail_lines.append(s)
        tail_len += len(s) + 1
    tail_lines.reverse()

    parts: list[str] = ["\n".join(head_lines)]
    if keys:
        parts.append("\n\n".join(keys))
    if tail_lines:
        parts.append("\n".join(tail_lines))
    parts.append(_mark_compressed(len(text)))
    return "\n\n".join(p for p in parts if p)