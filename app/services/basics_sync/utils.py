"""
与 Tushare 相关的阻塞式工具函数：
- fetch_stock_basic_df：获取股票列表（确保 Tushare 已连接）
- find_latest_trade_date：探测最近可用交易日（YYYYMMDD）
- fetch_daily_basic_mv_map：根据交易日获取日度基础指标映射（市值/估值/交易）
"""
from __future__ import annotations
from app.utils.timezone import now_tz

from datetime import datetime, timedelta

import os


def get_pro():
    """获取 Tushare pro API 实例（token 来自环境变量或 provider）"""
    import tushare as ts

    try:
        from tradingagents.dataflows.providers.china.tushare import get_tushare_provider
        token = getattr(get_tushare_provider(), "token", None) or ""
    except Exception:
        token = ""
    if not token:
        token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        return None
    ts.set_token(token)
    return ts.pro_api()


def fetch_stock_basic_df():
    """
    从 Tushare 获取股票基础列表（DataFrame格式），要求已正确配置并连接。
    依赖环境变量：TUSHARE_ENABLED=true 且 .env 中提供 TUSHARE_TOKEN。

    注意：这是一个同步函数，会等待 Tushare 连接完成。
    """
    import logging

    from app.core.config import settings

    logger = logging.getLogger(__name__)

    # 检查 Tushare 是否启用
    if not settings.TUSHARE_ENABLED:
        logger.error("❌ Tushare 数据源已禁用 (TUSHARE_ENABLED=false)")
        logger.error("💡 请在 .env 文件中设置 TUSHARE_ENABLED=true 或使用多数据源同步服务")
        raise RuntimeError(
            "Tushare is disabled (TUSHARE_ENABLED=false). "
            "Set TUSHARE_ENABLED=true in .env or use MultiSourceBasicsSyncService."
        )

    # 检查连接状态和API可用性
    pro = get_pro()
    if pro is None:
        logger.error("❌ Tushare 连接失败（未获取到 TUSHARE_TOKEN）")
        logger.error("💡 请检查：")
        logger.error("   1. .env 文件中配置了有效的 TUSHARE_TOKEN")
        logger.error("   2. Tushare Token 未过期且有足够的积分")
        logger.error("   3. 网络连接正常")
        raise RuntimeError(
            "Tushare not connected. Check TUSHARE_TOKEN in .env and ensure it's valid."
        )

    logger.info("✅ Tushare 已连接，开始获取股票列表...")

    # 直接调用 Tushare API 获取 DataFrame
    try:
        df = pro.stock_basic(
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market,exchange,list_date,is_hs'
        )

        # 🔧 增强错误诊断
        if df is None:
            logger.error("❌ Tushare API 返回 None")
            logger.error("💡 可能原因：")
            logger.error("   1. Tushare Token 无效或过期")
            logger.error("   2. API 积分不足")
            logger.error("   3. 网络连接问题")
            raise RuntimeError("Tushare API returned None. Check token validity and API credits.")

        if hasattr(df, 'empty') and df.empty:
            logger.error("❌ Tushare API 返回空 DataFrame")
            logger.error("💡 可能原因：")
            logger.error("   1. list_status='L' 参数可能不正确")
            logger.error("   2. Tushare 数据源暂时不可用")
            logger.error("   3. API 调用限制（请检查积分和调用频率）")
            raise RuntimeError("Tushare API returned empty DataFrame. Check API parameters and data availability.")

        logger.info(f"✅ 成功获取 {len(df)} 条股票数据")
        return df

    except Exception as e:
        logger.error(f"❌ 调用 Tushare API 失败: {e}")
        raise RuntimeError(f"Failed to fetch stock basic DataFrame: {e}")


def find_latest_trade_date() -> str:
    """
    探测最近可用的交易日（YYYYMMDD）。
    - 从今天起回溯最多 5 天；
    - 如都不可用，回退为昨天日期。
    """
    api = get_pro()
    if api is None:
        raise RuntimeError("Tushare API unavailable")

    today = now_tz()
    for delta in range(0, 6):
        d = (today - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            db = api.daily_basic(trade_date=d, fields="ts_code,total_mv")
            if db is not None and not db.empty:
                return d
        except Exception:
            continue
    return (today - timedelta(days=1)).strftime("%Y%m%d")


def fetch_daily_basic_mv_map(trade_date: str) -> dict[str, dict[str, float]]:
    """
    根据交易日获取日度基础指标映射。
    覆盖字段：total_mv/circ_mv/pe/pb/ps/turnover_rate/volume_ratio/pe_ttm/pb_mrq/ps_ttm
    """
    api = get_pro()
    if api is None:
        raise RuntimeError("Tushare API unavailable")

    # 🔥 新增：添加 ps、ps_ttm、total_share、float_share 字段
    fields = "ts_code,total_mv,circ_mv,pe,pb,ps,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps_ttm,total_share,float_share"
    db = api.daily_basic(trade_date=trade_date, fields=fields)

    data_map: dict[str, dict[str, float]] = {}
    if db is not None and not db.empty:
        for _, row in db.iterrows():  # type: ignore
            ts_code = row.get("ts_code")
            if ts_code is not None:
                try:
                    metrics = {}
                    # 🔥 新增：添加 ps、ps_ttm、total_share、float_share 到字段列表
                    for field in [
                        "total_mv",
                        "circ_mv",
                        "pe",
                        "pb",
                        "ps",
                        "turnover_rate",
                        "volume_ratio",
                        "pe_ttm",
                        "pb_mrq",
                        "ps_ttm",
                        "total_share",
                        "float_share",
                    ]:
                        value = row.get(field)
                        if value is not None and str(value).lower() not in ["nan", "none", ""]:
                            metrics[field] = float(value)
                    if metrics:
                        data_map[str(ts_code)] = metrics
                except Exception:
                    pass
    return data_map




def fetch_latest_roe_map() -> dict[str, dict[str, float]]:
    """
    获取最近一个可用财报期的 ROE 映射（ts_code -> {"roe": float}）。
    优先按最近季度的 end_date 逆序探测，找到第一期非空数据。
    """
    from datetime import datetime

    api = get_pro()
    if api is None:
        raise RuntimeError("Tushare API unavailable")

    # 生成最近若干个财政季度的期末日期，格式 YYYYMMDD
    def quarter_ends(now: datetime):
        y = now.year
        q_dates = [
            f"{y}0331",
            f"{y}0630",
            f"{y}0930",
            f"{y}1231",
        ]
        # 包含上一年，增加成功概率
        py = y - 1
        q_dates_prev = [
            f"{py}1231",
            f"{py}0930",
            f"{py}0630",
            f"{py}0331",
        ]
        # 近6期即可
        return q_dates_prev + q_dates

    candidates = quarter_ends(now_tz())
    data_map: dict[str, dict[str, float]] = {}

    for end_date in candidates:
        try:
            df = api.fina_indicator(end_date=end_date, fields="ts_code,end_date,roe")
            if df is not None and not df.empty:
                for _, row in df.iterrows():  # type: ignore
                    ts_code = row.get("ts_code")
                    val = row.get("roe")
                    if ts_code is None or val is None:
                        continue
                    try:
                        v = float(val)
                    except Exception:
                        continue
                    data_map[str(ts_code)] = {"roe": v}
                if data_map:
                    break  # 找到最近一期即可
        except Exception:
            continue

    return data_map
