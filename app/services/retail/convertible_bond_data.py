"""
可转债数据采集服务

数据源：akshare bond_zh_cov（东方财富-可转债一览表）
提供全市场已上市可转债的转债现价、正股价、转股价、转股价值、转股溢价率、
发行规模、上市时间、信用评级等数据。

用于策略D（转债下修博弈）的数据接入。

注：bond_zh_cov 不含纯债价值/回售触发价/强赎触发价/剩余年限等字段，
    下修博弈筛选改用「正股/转股价偏离度 + 转债价格 + 转股溢价率 + 双低」
    作为下修动力与债底保护的替代指标。
"""

import logging
from datetime import date
from typing import List, Optional, Dict, Any

import pandas as pd

from app.services import vibe_astock as astock
from app.services.cache_layer import cached

logger = logging.getLogger(__name__)


def _safe_akshare():
    """惰性获取 akshare"""
    try:
        return astock._akshare()
    except Exception as e:
        logger.warning(f"akshare 不可用: {e}")
        return None


def _safe_float(v, default=0.0) -> float:
    """安全转换为 float"""
    try:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return default
        val = float(v)
        if pd.isna(val):
            return default
        return val
    except (ValueError, TypeError):
        return default


def _estimate_years_to_maturity(list_date, term_years: int = 6) -> Optional[float]:
    """
    估算剩余年限

    bond_zh_cov 不返回到期日，但可转债发行期限通常为 6 年，
    根据上市时间估算剩余年限（仅供评分参考，非精确值）。

    Args:
        list_date: 上市日期（datetime.date 或 str）
        term_years: 可转债期限（默认6年）

    Returns:
        剩余年限（年），无法估算时返回 None
    """
    try:
        if list_date is None or (isinstance(list_date, float) and pd.isna(list_date)):
            return None
        if isinstance(list_date, str):
            ld = pd.to_datetime(list_date).date()
        elif hasattr(list_date, "year"):
            ld = list_date
        else:
            return None
        today = date.today()
        days_elapsed = (today - ld).days
        if days_elapsed < 0:
            return float(term_years)
        years_elapsed = days_elapsed / 365.0
        years_left = term_years - years_elapsed
        return max(years_left, 0.0)
    except Exception:
        return None


def _fetch_all_convertible_bonds() -> List[Dict[str, Any]]:
    """
    获取全市场已上市可转债数据

    通过 akshare bond_zh_cov() 获取东方财富可转债一览表，过滤已上市转债。

    返回字段：
        bond_code: 转债代码
        bond_name: 转债名称
        bond_price: 转债现价
        stock_code: 正股代码
        stock_name: 正股名称
        stock_price: 正股价
        conversion_price: 转股价
        conversion_value: 转股价值
        conversion_premium: 转股溢价率（小数，如 0.416 表示 41.6%）
        issue_size: 发行规模（亿元）
        list_date: 上市日期（YYYY-MM-DD 字符串）
        rating: 信用评级
        years_to_maturity: 估算剩余年限（年）
    """
    ak = _safe_akshare()
    if ak is None:
        return []

    try:
        df = ak.bond_zh_cov()
        if df is None or len(df) == 0:
            return []

        items: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            try:
                list_date = row.get("上市时间")
                # 仅保留已上市转债（上市时间非空）
                if list_date is None or (isinstance(list_date, float) and pd.isna(list_date)):
                    continue

                bond_price = _safe_float(row.get("债现价", 0))
                conversion_price = _safe_float(row.get("转股价", 0))
                stock_price = _safe_float(row.get("正股价", 0))

                # 过滤无效数据
                if bond_price <= 0 or conversion_price <= 0 or stock_price <= 0:
                    continue

                conversion_premium_pct = _safe_float(row.get("转股溢价率", 0))
                years_left = _estimate_years_to_maturity(list_date)

                item = {
                    "bond_code": str(row.get("债券代码", "")),
                    "bond_name": str(row.get("债券简称", "")),
                    "bond_price": bond_price,
                    "stock_code": str(row.get("正股代码", "")),
                    "stock_name": str(row.get("正股简称", "")),
                    "stock_price": stock_price,
                    "conversion_price": conversion_price,
                    "conversion_value": _safe_float(row.get("转股价值", 0)),
                    # akshare 返回的转股溢价率单位是 %（如 41.60 表示 41.6%），统一转为小数
                    "conversion_premium": conversion_premium_pct / 100.0,
                    "issue_size": _safe_float(row.get("发行规模", 0)),
                    "list_date": str(list_date) if list_date is not None else "",
                    "rating": str(row.get("信用评级", "") or ""),
                    "years_to_maturity": years_left if years_left is not None else 0.0,
                    "data_source": "bond_zh_cov",
                }
                items.append(item)
            except Exception as e:
                logger.warning(f"解析转债行数据失败: {e}")
                continue

        logger.info(f"获取已上市可转债数据成功: {len(items)} 只")
        return items

    except Exception as e:
        logger.error(f"获取可转债数据失败: {e}")
        return []


async def get_all_convertible_bonds() -> List[Dict[str, Any]]:
    """
    异步入口：获取全市场可转债数据（带缓存）

    缓存策略：交易时段3分钟，非交易时段30分钟（category=market）。
    """
    return await cached(
        "retail:convertible_bonds",
        _fetch_all_convertible_bonds,
        category="market",
        valid=lambda v: isinstance(v, list) and len(v) > 0,
    )


def get_all_convertible_bonds_sync() -> List[Dict[str, Any]]:
    """同步入口：直接获取（无缓存）"""
    return _fetch_all_convertible_bonds()


def _rating_score(rating: str) -> int:
    """信用评级评分（越高分越高）"""
    r = (rating or "").upper().strip()
    # 处理类似 "AA+sti" / "AAA" / "A+" 等格式
    if r.startswith("AAA"):
        return 15
    if r.startswith("AA+"):
        return 13
    if r.startswith("AA"):
        return 11
    if r.startswith("A+"):
        return 9
    if r.startswith("A"):
        return 7
    if r.startswith("BBB"):
        return 5
    if r.startswith("BB"):
        return 3
    if r.startswith("B"):
        return 2
    if r.startswith("C"):
        return 1
    return 6  # 无评级给中等分


def filter_down_revision_candidates(
    bonds: List[Dict[str, Any]],
    max_bond_price: float = 110,
    max_stock_vs_conversion: float = 0.7,
    min_issue_size: float = 1.0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    筛选下修博弈候选转债

    下修博弈策略核心逻辑：
    1. 正股深跌（正股/转股价 ≤ max_stock_vs_conversion）→ 公司有下修动力避免回售
    2. 转债价格合理（≤ max_bond_price）→ 有债底保护，下行风险有限
    3. 发行规模 ≥ min_issue_size → 流动性保障
    4. 已上市且数据完整

    评分维度（100分制）：
    - 下修动力（40分）：正股/转股价偏离度，越低动力越强
    - 转债价格（25分）：价格越低，债底保护越好
    - 转股溢价率（20分）：溢价率越高，下修后弹性越大
    - 信用评级（15分）：评级越高，下修能力越强（融资能力）

    Args:
        bonds: 全市场可转债列表
        max_bond_price: 转债价格上限
        max_stock_vs_conversion: 正股/转股价最大比值（低于此值有下修动力）
        min_issue_size: 最小发行规模（亿元）
        limit: 返回条数上限

    Returns:
        筛选后的候选列表，每项附加计算字段
    """
    candidates: List[Dict[str, Any]] = []
    for b in bonds:
        bond_price = b.get("bond_price", 0)
        stock_price = b.get("stock_price", 0)
        conversion_price = b.get("conversion_price", 0)
        issue_size = b.get("issue_size", 0)
        years_to_maturity = b.get("years_to_maturity", 0)

        # 基本过滤
        if bond_price <= 0 or bond_price > max_bond_price:
            continue
        if conversion_price <= 0 or stock_price <= 0:
            continue
        if issue_size < min_issue_size:
            continue

        # 计算正股/转股价偏离度（核心指标）
        stock_vs_conversion = stock_price / conversion_price
        if stock_vs_conversion > max_stock_vs_conversion:
            continue

        conversion_premium = b.get("conversion_premium", 0)
        # 双低值 = 转债价格 + 转股溢价率*100（衡量转债便宜程度）
        double_low = bond_price + conversion_premium * 100

        # 判断是否在回售期（剩余年限 < 2 年且 > 0，估算值）
        in_put_period = 0 < years_to_maturity <= 2

        # 判断下修动力等级
        # high: 正股深跌（偏离度<0.5）+ 接近回售期
        # medium: 正股深跌（偏离度<0.6）或 正股中度下跌+回售期
        # low: 正股中度下跌
        if stock_vs_conversion < 0.5:
            motivation = "high" if in_put_period else "medium"
        elif stock_vs_conversion < 0.6:
            motivation = "medium"
        else:
            motivation = "low"

        # 评分（100分制）
        score = 0
        score_details: Dict[str, str] = {}

        # 1. 下修动力评分（40分）—— 正股/转股价偏离度越低，动力越强
        if stock_vs_conversion < 0.4:
            power_score = 40
        elif stock_vs_conversion < 0.5:
            power_score = 32
        elif stock_vs_conversion < 0.6:
            power_score = 24
        else:
            power_score = 16
        # 在回售期内额外加 5 分（封顶40）
        if in_put_period:
            power_score = min(power_score + 5, 40)
        score += power_score
        score_details["下修动力"] = f"{motivation} (偏离度{stock_vs_conversion:.2f}, {power_score}/40)"

        # 2. 转债价格评分（25分）—— 价格越低，债底保护越好
        if bond_price <= 90:
            price_score = 25
        elif bond_price <= 100:
            price_score = 20
        elif bond_price <= 105:
            price_score = 15
        else:
            price_score = 10
        score += price_score
        score_details["转债价格"] = f"{bond_price:.2f} ({price_score}/25)"

        # 3. 转股溢价率评分（20分）—— 溢价率越高，下修后弹性越大
        if conversion_premium >= 0.8:
            premium_score = 20
        elif conversion_premium >= 0.6:
            premium_score = 16
        elif conversion_premium >= 0.4:
            premium_score = 12
        elif conversion_premium >= 0.2:
            premium_score = 8
        else:
            premium_score = 4
        score += premium_score
        score_details["转股溢价率"] = f"{conversion_premium*100:.1f}% ({premium_score}/20)"

        # 4. 信用评级评分（15分）—— 评级越高，下修能力越强
        rating_score = _rating_score(b.get("rating", ""))
        score += rating_score
        score_details["信用评级"] = f"{b.get('rating', '-')} ({rating_score}/15)"

        candidates.append({
            **b,
            "stock_vs_conversion": round(stock_vs_conversion, 4),
            "double_low": round(double_low, 2),
            "in_put_period": in_put_period,
            "down_revision_motivation": motivation,
            "score": score,
            "score_details": score_details,
            "signal_type": "下修博弈",
        })

    # 按评分降序排序（保留评分用于排序，不再用min_score过滤）
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]
