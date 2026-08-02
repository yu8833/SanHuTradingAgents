"""
AI 输入层数据完整性校验拦截层

三级检查策略（与项目数据契约一脉相承：宁可标记不可用，不让 AI 基于脏数据推理）：

L1 时效性：日线数据过期判断（基于返回文本末行 Date + calc_stale_days）
    - 过期 → 触发即时补数（DataIntegrityService）→ 补完重取
    - 补数失败 → 直接阻断（抛 DataStaleError），给出明确说明
    - 仅对 get_stock_data（日线 OHLCV）适用，因为只有这一类有补数机制

L2 完整性：无数据哨兵字符串识别
    - 识别 "No data found" / "无数据" / "数据不可用" 等
    - 标记 MISSING，附在结果字符串后（不阻断）

L3 异常值：从文本中提取关键数值，复用 data_validator 校验
    - 超范围值标记 ABNORMAL，附在结果字符串后（不阻断）

阻断条件（严格遵循用户要求）：
    仅当 method == "get_stock_data" 且日线过期且补数失败时阻断
    其他数据类型只标记不阻断
"""
import asyncio
import logging
import re
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ========================================================================
# 异常定义
# ========================================================================

class DataStaleError(Exception):
    """数据过期且补数失败，应阻断分析"""

    def __init__(self, symbol: str, stale_days: int, detail: str = ""):
        self.symbol = symbol
        self.stale_days = stale_days
        msg = (
            f"数据过期阻断：股票 {symbol} 日线数据落后 {stale_days} 个交易日，"
            f"自动补数失败。{detail}"
            f"请检查数据同步定时任务是否正常运行，或手动触发补数。"
            f"本次分析已中止，避免基于过期数据得出错误结论。"
        )
        super().__init__(msg)


# ========================================================================
# 哨兵字符串识别
# ========================================================================

_NO_DATA_PATTERNS = [
    re.compile(r"No data found", re.IGNORECASE),
    re.compile(r"无数据", re.IGNORECASE),
    re.compile(r"数据不可用", re.IGNORECASE),
    re.compile(r"No fundamentals data found", re.IGNORECASE),
    re.compile(r"No news found", re.IGNORECASE),
    re.compile(r"未找到.*数据", re.IGNORECASE),
]


def _is_empty_result(result: str) -> bool:
    """识别无数据哨兵字符串"""
    if not result or not result.strip():
        return True
    for pat in _NO_DATA_PATTERNS:
        if pat.search(result):
            return True
    return False


# ========================================================================
# 日线过期检测
# ========================================================================

# 从 CSV/文本末行提取日期的正则
# 匹配 YYYY-MM-DD 格式
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# CSV 末行日期提取（Date,Open,High,Low,Close,Volume 格式）
_CSV_LAST_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}),[\d.\-]+,[\d.\-]+,[\d.\-]+,[\d.\-]+,[\d.\-]+\s*$",
    re.MULTILINE,
)


def _extract_last_date_from_stock_data(result: str) -> Optional[str]:
    """从 get_stock_data 返回的 CSV 文本中提取末行日期（YYYY-MM-DD）。

    get_stock_data 返回格式：
        # Stock data for {code} ...
        # Total records: N
        # Data source: xxx
        # Data retrieved on: YYYY-MM-DD HH:MM:SS
        Date,Open,High,Low,Close,Volume
        2026-07-25,...
        2026-07-28,...
        2026-07-29,...

    末行 Date 即为数据源覆盖到的最后交易日。
    """
    if not result:
        return None

    # 优先用 CSV 行格式匹配（最后一行数据行）
    matches = _CSV_LAST_DATE_RE.findall(result)
    if matches:
        return matches[-1]

    # Fallback:提取文本中所有 YYYY-MM-DD，取最后一个（排除 header 的 retrieved on）
    # 先移除 header 中的 "Data retrieved on" 行
    lines = result.split("\n")
    body_lines = [
        line for line in lines
        if not line.startswith("#") and "Data retrieved on" not in line
    ]
    body = "\n".join(body_lines)
    dates = _DATE_RE.findall(body)
    if dates:
        return dates[-1]

    return None


def _calc_stale_days_safe(date_str: str) -> int:
    """安全计算过期天数，失败返回 0（不阻断）"""
    try:
        # 延迟导入，避免循环依赖
        from app.utils.trading_time import calc_stale_days
        return calc_stale_days(date_str)
    except Exception as e:
        logger.debug(f"计算过期天数失败 {date_str}: {e}")
        return 0


# ========================================================================
# 异步补数触发（在新线程中运行，避免事件循环冲突）
# ========================================================================

def _run_async_in_thread(coro_factory):
    """在新线程中运行异步函数，避免与现有事件循环冲突。

    Args:
        coro_factory: 返回协程的无参可调用对象
    Returns:
        协程的返回值
    """
    result_box = [None]
    error_box = [None]

    def runner():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_box[0] = loop.run_until_complete(coro_factory())
            finally:
                loop.close()
        except Exception as e:
            error_box[0] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=120)  # 补数最多等 120 秒

    if t.is_alive():
        # 超时
        logger.error("⏰ 即时补数超时（120s），视为补数失败")
        return None
    if error_box[0] is not None:
        logger.error(f"即时补数异常: {error_box[0]}")
        return None
    return result_box[0]


def _trigger_remediation(symbol: str, trade_date: str) -> bool:
    """触发即时补数（针对单只股票的单日缺失）

    Returns:
        True 表示补数成功（或数据已存在），False 表示补数失败
    """
    try:
        from app.services.data_integrity_service import DataIntegrityService

        def coro_factory():
            service = DataIntegrityService()
            return service.check_historical_completeness(
                trade_date=trade_date,
                auto_remediate=True,
                remediate_source="akshare",
                remediate_batch_size=50,
                remediate_lookback_days=5,
            )

        result = _run_async_in_thread(coro_factory)
        if result is None:
            return False

        # 检查补数后该股票是否有数据了
        missing_codes = result.get("missing_codes", []) if isinstance(result, dict) else []
        if symbol in missing_codes:
            logger.warning(f"补数后 {symbol} 仍在缺失列表中")
            return False

        remediated = result.get("remediated_count", 0) if isinstance(result, dict) else 0
        logger.info(f"✅ 即时补数完成: {symbol} {trade_date}, remediated={remediated}")
        return True

    except Exception as e:
        logger.error(f"触发即时补数异常: {e}")
        return False


# ========================================================================
# 主校验入口
# ========================================================================

# 日线过期阈值：超过此天数视为过期
# stale_days=0 表示数据是最新交易日；>0 表示落后 N 个交易日
STALE_DAYS_THRESHOLD = 0


def check_integrity(result: str, method: str, args: tuple) -> str:
    """对 route_to_vendor 返回的数据进行完整性校验。

    Args:
        result: vendor 返回的字符串结果
        method: 数据方法名（如 "get_stock_data"）
        args: 传给 vendor 的原始参数（用于提取 symbol 等）

    Returns:
        校验后的结果字符串（可能附加质量标记）

    Raises:
        DataStaleError: 当日线数据过期且补数失败时
    """
    if not isinstance(result, str):
        return result

    # 提取 symbol（大部分工具第一个参数是股票代码）
    symbol = str(args[0]) if args else "unknown"

    # ----------------------------------------------------------------
    # L2 完整性：无数据哨兵识别（只标记不阻断）
    # ----------------------------------------------------------------
    if _is_empty_result(result):
        marker = f"\n\n⚠️ [数据完整性] 股票 {symbol} 的 {method} 数据缺失（无数据返回）。AI 分析时请注意该维度数据不可用，不要基于推测编造数据。"
        logger.warning(f"[IntegrityGuard] {method} 数据缺失: {symbol}")
        return result + marker

    # ----------------------------------------------------------------
    # L1 时效性：仅对 get_stock_data 做日线过期检查+补数+阻断
    # ----------------------------------------------------------------
    if method == "get_stock_data":
        last_date = _extract_last_date_from_stock_data(result)
        if last_date:
            stale_days = _calc_stale_days_safe(last_date)
            if stale_days > STALE_DAYS_THRESHOLD:
                logger.warning(
                    f"⚠️ [IntegrityGuard] {symbol} 日线数据过期: 末行日期={last_date}, stale_days={stale_days}, 触发即时补数"
                )

                # 触发即时补数
                remediated = _trigger_remediation(symbol, last_date)

                if remediated:
                    # 补数成功，重新获取数据
                    try:
                        from tradingagents.dataflows.interface import _get_vendor_method, _build_fallback_chain
                        chain = _build_fallback_chain(method)
                        for vendor in chain:
                            func = _get_vendor_method(vendor, method)
                            if func is None:
                                continue
                            try:
                                new_result = func(*args)
                                if new_result and not _is_empty_result(new_result):
                                    # 重新检查过期
                                    new_last_date = _extract_last_date_from_stock_data(new_result)
                                    if new_last_date:
                                        new_stale = _calc_stale_days_safe(new_last_date)
                                        if new_stale <= STALE_DAYS_THRESHOLD:
                                            logger.info(f"✅ [IntegrityGuard] {symbol} 补数后数据已更新: {new_last_date}")
                                            return new_result
                                        else:
                                            # 补数后仍过期，阻断
                                            raise DataStaleError(
                                                symbol, new_stale,
                                                detail=f"补数后末行日期仍为 {new_last_date}。"
                                            )
                                    else:
                                        # 无法提取日期，放行（不阻断）
                                        return new_result + f"\n\n⚠️ [数据时效性] 补数后无法确认数据日期，请谨慎使用。"
                            except DataStaleError:
                                raise
                            except Exception as e:
                                logger.warning(f"[IntegrityGuard] 重新获取数据失败 ({vendor}): {e}")
                                continue
                    except DataStaleError:
                        raise

                    # 所有 vendor 都没拿到新数据，但补数本身成功了——放行但标记
                    return result + f"\n\n⚠️ [数据时效性] 股票 {symbol} 日线数据落后 {stale_days} 个交易日（末行日期 {last_date}），已触发补数但重新获取数据失败。请谨慎使用。"

                else:
                    # 补数失败 → 阻断（用户明确要求）
                    raise DataStaleError(symbol, stale_days, detail=f"末行日期 {last_date}，补数未成功。")

    # ----------------------------------------------------------------
    # L3 异常值：从文本提取关键数值校验（只标记不阻断）
    # ----------------------------------------------------------------
    # 对 get_fundamentals 做关键指标异常值检测
    if method == "get_fundamentals":
        abnormal_flags = _check_fundamentals_abnormal(result, symbol)
        if abnormal_flags:
            marker = f"\n\n⚠️ [数据异常值] 股票 {symbol} 以下指标数值异常已标记: {'; '.join(abnormal_flags)}。AI 分析时请注意这些数据可能不准确，不要基于异常值得出结论。"
            return result + marker

    return result


def _check_fundamentals_abnormal(result: str, symbol: str) -> list[str]:
    """从 get_fundamentals 返回文本中提取关键指标，校验异常值。

    get_fundamentals 返回格式（a_stock）：
        PE (TTM): 23.5
        PB: 3.2
        ...

    复用 data_validator 的约束范围。
    """
    flags = []
    try:
        from tradingagents.dataflows.data_validator import validate_value

        # label → field_name 映射
        label_map = {
            "PE (TTM)": "pe_ttm",
            "PE": "pe",
            "PB": "pb",
            "PB (MRQ)": "pb_mrq",
            "PS (TTM)": "ps_ttm",
            "PS": "ps",
            "PEG": "peg",
            "ROE": "roe",
            "ROA": "roa",
            "毛利率": "gross_margin",
            "净利率": "net_margin",
            "换手率": "turnover_rate",
            "量比": "volume_ratio",
            "振幅": "amplitude",
            "涨跌幅": "change_percent",
            "资产负债率": "debt_to_assets",
        }

        for line in result.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("==="):
                continue
            for label, field_name in label_map.items():
                if label in line:
                    # 提取行中的数值
                    nums = re.findall(r"-?\d+\.?\d*", line.split(label)[-1])
                    if nums:
                        try:
                            val = float(nums[0])
                            cleaned, warning = validate_value(val, field_name)
                            if warning and cleaned is None:
                                flags.append(f"{label}={val}({warning})")
                        except (ValueError, IndexError):
                            pass
                    break
    except ImportError:
        logger.debug("data_validator 不可用，跳过异常值校验")
    except Exception as e:
        logger.debug(f"异常值校验异常: {e}")

    return flags


# ========================================================================
# 质量标记格式化（供 agent_utils 注入 Prompt）
# ========================================================================

def format_quality_notice(method: str, result: str) -> str:
    """将已附加的质量标记格式化为 AI 可读的提示。

    此函数保留给上层调用方使用（如 agent_utils 在工具返回前注入）。
    当前 check_integrity 已直接把标记附加到结果字符串末尾，
    所以此函数仅做透传，便于未来扩展。
    """
    return result
