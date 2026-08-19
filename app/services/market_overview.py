"""市场总览数据层 —— 市场情绪 + 板块资金流（板块/大盘级公开数据，不涉个股推荐）。

省流量：全站共享一份缓存（Redis + 内存二级缓存），多个用户/多次打开只抓一次；
盘中分级TTL：大盘/板块 3分钟，实时行情 30秒，新闻 5分钟；
非交易时段自动延长TTL，减少数据源压力。数据源全免费、无 key。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services import vibe_astock as astock
from app.services import vibe_gstock as gstock
from app.services.cache_layer import cached
from app.services.data_sources.akshare_adapter import _parse_cn_amount, _parse_pct_str

BEIJING = timezone(timedelta(hours=8))


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sentiment() -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机（客观数据机械分档）。"""
    try:
        # akshare 惰性导入（同 astock 模式）：未装时降级返回空，不挡整个服务启动
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return {}
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _fund_amount(v) -> float:
    """行业资金流金额 → 数值（单位：元）。

    AKShare stock_fund_flow_industry 的金额列可能返回「X.XX亿/万」字符串，
    也可能是纯数字（该接口纯数字以「亿」为单位）。统一归一为「元」，
    便于下游 _industry_rank 再除以 1e8 转为「亿」。
    """
    if isinstance(v, (int, float)):
        return float(v) * 1e8  # 该接口纯数字以「亿」为单位
    val = _parse_cn_amount(v)
    return float(val) if val is not None else 0.0


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。不含领涨股等个股字段。

    AKShare stock_fund_flow_industry 金额列返回「X.XX亿/万」字符串或纯数字（亿），
    统一用 _fund_amount 规范化为数值（单位：元），
    _industry_rank 再除以 1e8 转为「亿」。
    """
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        # 规范化金额列（「亿/万」字符串或纯数字「亿」）为数值（单位：元）
        for col in ("净额", "流入资金", "流出资金"):
            if col in f.columns:
                f[col] = f[col].map(_fund_amount)
        # 涨跌幅为「21.43%」字符串 → 数值（%）
        for col in ("行业-涨跌幅",):
            if col in f.columns:
                f[col] = f[col].map(_parse_pct_str)
        f = f.sort_values("净额", ascending=False)
    except Exception:
        return []
    out = []
    for _, row in f.iterrows():
        # 金额列已在上面 map(_fund_amount) 归一为「元」，此处仅安全取数值，不再重复换算
        net_val = float(row.get("净额", 0) or 0)
        inflow_val = float(row.get("流入资金", 0) or 0)
        outflow_val = float(row.get("流出资金", 0) or 0)
        pct_val = _parse_pct_str(row.get("行业-涨跌幅", 0)) or 0
        out.append({
            "name": str(row["行业"]),
            "pct": round(float(pct_val), 2),
            "net": round(float(net_val), 2),
            "inflow": round(float(inflow_val), 2),
            "outflow": round(float(outflow_val), 2),
            "firms": _num(row.get("公司家数")),
        })
    return out


async def get_overview() -> dict:
    """市场情绪 + 板块资金（Redis缓存，大盘/板块级 TTL）。资金轮动由前端从 sectors 头尾取。"""
    def build():
        return {
            "sentiment": _sentiment(),
            "sectors": _sectors(),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return await cached(
        "vibe:market_overview", build,
        category="market",
        valid=lambda v: bool(v.get("sentiment") or v.get("sectors"))
    )


def _emotion() -> dict:
    """短线情绪（聚合口径，**零个股名**）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    数据源＝东财涨停板四池（push2ex）。只把池子聚合成计数与比率，
    **不输出任何个股 code/name**——守产品「零标的」红线（个股清单是甩名单，不做）。
    """
    # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）。
    today = datetime.now(BEIJING).date()
    resolved, zt = "", []
    for back in range(8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
        if zt:
            resolved = d
            break
    if not resolved:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）。
    # 产品定位调整（2026-07-05）：从「零标的」→「展示客观榜单但不推荐/不预测/不评分」。
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),      # 成交额,元（'-' 占位归一为 None，防排序对 str 取负崩溃）
            "float_cap": astock._numf(p.get("ltsz")),     # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    # 补充真实涨停/跌停数据（来自乐谷，与大盘总览一致）
    zt_real, dt_real = 0, 0
    try:
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
        zt_real = _num(d.get("真实涨停"))
        dt_real = _num(d.get("真实跌停"))
    except Exception:
        pass

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        "zt_count": zt_count,
        "dt_count": len(dt),
        "zt_real": zt_real,
        "dt_real": dt_real,
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
    }


async def get_short_term_emotion() -> dict:
    """短线情绪（Redis缓存，market级TTL）。"""
    return await cached("vibe:short_term_emotion", _emotion, category="market")


async def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（客观公开榜单，Redis缓存 market 级TTL）。"""
    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return await cached(
        "vibe:turnover_top", build,
        category="market",
        valid=lambda v: bool(v.get("stocks"))
    )


async def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，Redis缓存 news 级TTL）。空结果不缓存。"""
    return await cached("vibe:global_indices", gstock.global_indices, category="news", valid=bool)
