"""大盘画像（market portrait）命名与判定的唯一来源。

此前系统内各处（散户环境检测、大屏看板、通知、AI 提示词）各自用
「牛市 / 熊市 / 震荡市 / 偏强 / 偏弱」等不同措辞描述同一件事，
用户在不同页面看到的口径不一致。本模块把 8 个画像名称与判定规则收敛到一处：

    牛市普涨 / 牛市强趋势 / 震荡蓄势 / 震荡分化 /
    熊市阴跌 / 熊市恐慌 / 熊市反弹 / 高波动市

所有需要「当前大盘是什么状态」的地方都应调用 derive_portrait()，
不要在各自模块里另写映射表。
"""

from __future__ import annotations

# 8 个画像（顺序 = 一轮行情自然流转，前端轮盘按此顺序展示）
PORTRAIT_NAMES: tuple[str, ...] = (
    "牛市普涨",
    "牛市强趋势",
    "震荡蓄势",
    "震荡分化",
    "熊市阴跌",
    "熊市恐慌",
    "熊市反弹",
    "高波动市",
)

# 画像 → 一句话操作建议（唯一文案源）
PORTRAIT_ADVICE: dict[str, str] = {
    "牛市普涨": "全面上涨 → 趋势 / 突破类为主，仓位可放到 7~8 成，回避连板高位股",
    "牛市强趋势": "主线趋势延续 → 只做强势主线回踩，别追高开和放量假突破",
    "震荡蓄势": "区间下沿低吸、上沿减仓，破位即走，仓位 3~5 成",
    "震荡分化": "结构性行情 → 精选个股、宁缺毋滥，不做指数级别的方向押注",
    "熊市阴跌": "防御为主 → 低估值高股息 + 债底保护，仓位 ≤3 成",
    "熊市恐慌": "恐慌错杀 → 只用小仓做 1~3 日反弹，跌破前低立即止损，不接下跌中继",
    "熊市反弹": "中期仍空、短期转强 → 只做超跌反弹，小仓快进快出；反弹不放量 / 破反弹低点即走",
    "高波动市": "情绪脉冲 → 快进快出，严格止损，不逆势承接",
}


def derive_portrait(
    mid_trend: str,
    volatility: str,
    breadth: str,
    sentiment: str | None,
    short_trend: str | None = None,
) -> str:
    """四维 / 双尺度 → 画像（唯一判定实现）。

    Args:
        mid_trend: 中期趋势 bull / bear / range / unknown（沪深300 vs 年线 MA250）
        volatility: high / normal / low / unknown
        breadth: broad（普涨） / neutral / narrow（分化）
        sentiment: euphoric / neutral / panic / None（未知）
        short_trend: 短期趋势 bull / sideways / bear；缺省时按宽度推断
            （宽度普涨 → 短期偏强，宽度分化 → 短期偏弱，其余中性）。
            散户环境检测只提供宽度、没有独立短期宽度序列，故允许缺省。

    「熊市反弹」：中期在年线下方（熊），但短期已转强（反弹）——
    既不能算「熊市阴跌」（短期并不弱），也不能算「牛市强趋势」（中期仍空）。
    """
    mid = mid_trend
    if short_trend not in ("bull", "sideways", "bear"):
        short_trend = "bull" if breadth == "broad" else "bear" if breadth == "narrow" else "sideways"
    if mid == "unknown":
        # 指数日线缺失时用短期宽度代理中期趋势，调用方应在数据质量中标注降级
        mid = short_trend if short_trend in ("bull", "bear") else "range"

    if mid == "bull":
        # 中期多头 + 短期普涨才算「普涨」；只有中期强趋势则是「强趋势」
        return "牛市普涨" if breadth == "broad" and short_trend == "bull" else "牛市强趋势"

    if mid == "bear":
        if sentiment == "panic" and volatility == "high":
            return "熊市恐慌"
        # 情绪数据缺失时的价格行为代理：中期熊 + 短期继续弱 + 高波动 = 单边急跌
        if volatility == "high" and short_trend == "bear":
            return "熊市恐慌"
        if short_trend == "bull":
            return "熊市反弹"
        return "熊市阴跌"

    if volatility == "high":
        return "高波动市"
    if volatility == "low" or breadth == "broad":
        return "震荡蓄势"
    return "震荡分化"
