"""
AKShare data source adapter
"""
import logging
from datetime import datetime, timedelta
from typing import Any
from app.utils.timezone import now_tz

import pandas as pd

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)


def _news_time_key(time_str: str) -> str:
    """将新闻时间字符串规范化为可排序的 key（YYYY-MM-DD HH:MM:SS）。

    兼容多种格式：'2026-08-05 16:55:00'、'2026-08-05'、'2026/08/05' 等；
    无法解析的置为最早时间，保证排到最后。
    """
    s = (time_str or "").strip().replace("/", "-")
    s = s.replace("T", " ").replace("Z", "")
    # 补全到标准长度，缺秒补 :00
    if len(s) == 10:  # YYYY-MM-DD
        s = s + " 00:00:00"
    elif len(s) == 16:  # YYYY-MM-DD HH:MM
        s = s + ":00"
    return s or "0000-00-00 00:00:00"


def _parse_cn_amount(v) -> float | None:
    """解析「X.XX亿/万」金额字符串为数值（单位：元）。'--'/NaN/空 → None。"""
    try:
        s = str(v).strip()
        if not s or s in ("--", "-", "None", "nan", "NaN"):
            return None
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        return float(s)
    except (TypeError, ValueError):
        return None


def _parse_pct_str(v) -> float | None:
    """解析「21.43%」百分比字符串为数值（%）。'--'/NaN/空 → None。"""
    try:
        s = str(v).strip().replace("%", "")
        if not s or s in ("--", "-", "None", "nan", "NaN"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


class AKShareAdapter(DataSourceAdapter):
    """AKShare数据源适配器"""

    def __init__(self):
        super().__init__()  # 调用父类初始化

    @property
    def name(self) -> str:
        return "akshare"

    def _get_default_priority(self) -> int:
        return 2  # 数字越大优先级越高

    def is_available(self) -> bool:
        """检查AKShare是否可用（仅检查 import，快速返回，不阻塞）"""
        try:
            import akshare as ak  # noqa: F401  # 仅用于可用性探测
            return True
        except ImportError:
            return False

    async def test_connection(self) -> bool:
        """
        真正的网络连通性测试（异步，不阻塞事件循环）

        使用 stock_zh_a_spot_em 获取一只股票的实时行情作为轻量级测试，
        通过 ThreadPoolExecutor 添加超时保护，避免网络问题导致长时间阻塞。
        成功结果缓存5分钟，失败时不缓存（允许立即重试）。
        """
        import time as _time
        # 成功时缓存5分钟，失败时不缓存
        now = _time.time()
        if getattr(self, '_cached_available', None) is True and (now - getattr(self, '_available_cache_ts', 0.0)) < 300:
            return True
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak

            def _fetch():
                # 轻量级测试：尝试获取一只股票的实时行情
                return ak.stock_zh_a_spot_em()

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    df = future.result(timeout=15)
                except FuturesTimeoutError:
                    logger.warning("AKShare test_connection 超时（15秒）")
                    result = False
                    df = None
                else:
                    result = df is not None and len(df) > 0
        except Exception as e:
            logger.debug(f"AKShare test_connection 失败: {e}")
            result = False

        self._cached_available = result
        self._available_cache_ts = now
        return result

    def get_stock_list(self) -> pd.DataFrame | None:
        """获取股票列表（使用 AKShare 的 stock_info_a_code_name 接口获取真实股票名称）"""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            logger.info("AKShare: Fetching stock list with real names from stock_info_a_code_name()...")

            # 使用 AKShare 的 stock_info_a_code_name 接口获取股票代码和名称
            df = ak.stock_info_a_code_name()

            if df is None or df.empty:
                logger.warning("AKShare: stock_info_a_code_name() returned empty data")
                return None

            # 标准化列名（AKShare 返回的列名可能是中文）
            # 通常返回的列：code（代码）、name（名称）
            df = df.rename(columns={
                'code': 'symbol',
                '代码': 'symbol',
                'name': 'name',
                '名称': 'name'
            })

            # 确保有必需的列
            if 'symbol' not in df.columns or 'name' not in df.columns:
                logger.error(f"AKShare: Unexpected column names: {df.columns.tolist()}")
                return None

            # 生成 ts_code 和其他字段
            def generate_ts_code(code: str) -> str:
                """根据股票代码生成 ts_code"""
                if not code:
                    return ""
                code = str(code).zfill(6)
                if code.startswith(('60', '68', '90')):
                    return f"{code}.SH"
                elif code.startswith(('00', '30', '20')):
                    return f"{code}.SZ"
                elif code.startswith(('8', '4')):
                    return f"{code}.BJ"
                else:
                    return f"{code}.SZ"  # 默认深圳

            def get_market(code: str) -> str:
                """根据股票代码判断市场"""
                if not code:
                    return ""
                code = str(code).zfill(6)
                if code.startswith('000'):
                    return '主板'
                elif code.startswith('002'):
                    return '中小板'
                elif code.startswith('300'):
                    return '创业板'
                elif code.startswith('60'):
                    return '主板'
                elif code.startswith('688'):
                    return '科创板'
                elif code.startswith('8'):
                    return '北交所'
                elif code.startswith('4'):
                    return '新三板'
                else:
                    return '未知'

            # 添加 ts_code 和 market 字段
            df['ts_code'] = df['symbol'].apply(generate_ts_code)
            df['market'] = df['symbol'].apply(get_market)
            df['area'] = ''
            df['industry'] = ''
            df['list_date'] = ''

            logger.info(f"AKShare: Successfully fetched {len(df)} stocks with real names")
            return df

        except Exception as e:
            logger.error(f"AKShare: Failed to fetch stock list: {e}")
            return None

    def get_daily_basic(self, trade_date: str) -> pd.DataFrame | None:
        """获取每日基础财务数据（快速版）"""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            logger.info(f"AKShare: Attempting to get basic financial data for {trade_date}")

            stock_df = self.get_stock_list()
            if stock_df is None or stock_df.empty:
                logger.warning("AKShare: No stock list available")
                return None

            max_stocks = 10
            stock_list = stock_df.head(max_stocks)

            basic_data = []
            processed_count = 0
            import time
            start_time = time.time()
            timeout_seconds = 30

            for _, stock in stock_list.iterrows():
                if time.time() - start_time > timeout_seconds:
                    logger.warning(f"AKShare: Timeout reached, processed {processed_count} stocks")
                    break
                try:
                    symbol = stock.get('symbol', '')
                    name = stock.get('name', '')
                    ts_code = stock.get('ts_code', '')
                    if not symbol:
                        continue
                    info_data = ak.stock_individual_info_em(symbol=symbol)
                    if info_data is not None and not info_data.empty:
                        info_dict = {}
                        for _, row in info_data.iterrows():
                            item = row.get('item', '')
                            value = row.get('value', '')
                            info_dict[item] = value
                        latest_price = self._safe_float(info_dict.get('最新', 0))
                        # 🔥 AKShare 的"总市值"单位是万元，需要转换为亿元（与 Tushare 一致）
                        total_mv_wan = self._safe_float(info_dict.get('总市值', 0))  # 万元
                        total_mv_yi = total_mv_wan / 10000 if total_mv_wan else None  # 转换为亿元
                        basic_data.append({
                            'ts_code': ts_code,
                            'trade_date': trade_date,
                            'name': name,
                            'close': latest_price,
                            'total_mv': total_mv_yi,  # 亿元（与 Tushare 一致）
                            'turnover_rate': None,
                            'pe': None,
                            'pb': None,
                        })
                        processed_count += 1
                        if processed_count % 5 == 0:
                            logger.debug(f"AKShare: Processed {processed_count} stocks in {time.time() - start_time:.1f}s")
                except Exception as e:
                    logger.debug(f"AKShare: Failed to get data for {symbol}: {e}")
                    continue

            if basic_data:
                df = pd.DataFrame(basic_data)
                logger.info(f"AKShare: Successfully fetched basic data for {trade_date}, {len(df)} records")
                return df
            else:
                logger.warning("AKShare: No basic data collected")
                return None
        except Exception as e:
            logger.error(f"AKShare: Failed to fetch basic data for {trade_date}: {e}")
            return None

    def _safe_float(self, value) -> float | None:
        try:
            if value is None or value == '' or value == 'None':
                return None
            return float(value)
        except (ValueError, TypeError):
            return None


    def get_realtime_quotes(self, source: str = "sina", timeout: int = 30):
        """
        获取全市场实时快照，返回以6位代码为键的字典

        Args:
            source: 数据源选择，"sina"（新浪财经）或 "eastmoney"（东方财富）
                    如果指定数据源失败，会自动尝试另一个
                    默认使用 sina，因为它更稳定
            timeout: 超时时间（秒），默认 30 秒

        Returns:
            Dict[str, Dict]: {code: {close, pct_chg, amount, ...}}
        """
        if not self.is_available():
            return None

        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak  # type: ignore

            # 定义数据源优先级列表
            sources = [source]
            if source == "eastmoney":
                sources.append("sina")
            else:
                sources.append("eastmoney")
            # 去重保持顺序
            seen = set()
            sources = [s for s in sources if not (s in seen or seen.add(s))]

            last_error = None

            for src in sources:
                try:
                    logger.info(f"尝试 AKShare {src} 数据源获取实时行情（超时: {timeout}秒）")

                    def _fetch_data(_src=src):
                        """在子线程中获取数据"""
                        if _src == "sina":
                            df = ak.stock_zh_a_spot()  # 新浪财经接口
                            logger.info("使用 AKShare 新浪财经接口获取实时行情")
                        else:  # 默认使用东方财富
                            df = ak.stock_zh_a_spot_em()  # 东方财富接口
                            logger.info("使用 AKShare 东方财富接口获取实时行情")
                        return df

                    # 使用 ThreadPoolExecutor 添加超时保护
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_fetch_data)
                        try:
                            df = future.result(timeout=timeout)
                        except FuturesTimeoutError:
                            logger.warning(f"AKShare {src} 数据获取超时（{timeout}秒）")
                            last_error = TimeoutError(f"AKShare {src} timeout after {timeout} seconds")
                            continue

                    if df is None or getattr(df, "empty", True):
                        logger.warning(f"AKShare {src} 返回空数据")
                        last_error = Exception("empty data")
                        continue

                    # 列名兼容（两个接口的列名可能不同）
                    code_col = next((c for c in ["代码", "code", "symbol", "股票代码"] if c in df.columns), None)
                    price_col = next((c for c in ["最新价", "现价", "最新价(元)", "price", "最新", "trade"] if c in df.columns), None)
                    pct_col = next((c for c in ["涨跌幅", "涨跌幅(%)", "涨幅", "pct_chg", "changepercent"] if c in df.columns), None)
                    amount_col = next((c for c in ["成交额", "成交额(元)", "amount", "成交额(万元)", "amount(万元)"] if c in df.columns), None)
                    open_col = next((c for c in ["今开", "开盘", "open", "今开(元)"] if c in df.columns), None)
                    high_col = next((c for c in ["最高", "high"] if c in df.columns), None)
                    low_col = next((c for c in ["最低", "low"] if c in df.columns), None)
                    pre_close_col = next((c for c in ["昨收", "昨收(元)", "pre_close", "昨收价", "settlement"] if c in df.columns), None)
                    volume_col = next((c for c in ["成交量", "成交量(手)", "volume", "成交量(股)", "vol"] if c in df.columns), None)
                    name_col = next((c for c in ["名称", "name", "股票名称"] if c in df.columns), None)
                    turnover_col = next((c for c in ["换手率", "turnover_rate", "turnover"] if c in df.columns), None)
                    vol_ratio_col = next((c for c in ["量比", "vol_ratio"] if c in df.columns), None)

                    if not code_col or not price_col:
                        logger.error(f"AKShare {src} 缺少必要列: code={code_col}, price={price_col}, columns={list(df.columns)}")
                        last_error = Exception("missing columns")
                        continue

                    result: dict[str, dict[str, float | None]] = {}
                    for _, row in df.iterrows():  # type: ignore
                        code_raw = row.get(code_col)
                        if not code_raw:
                            continue
                        # 标准化股票代码：处理交易所前缀（如 sz000001, sh600036）
                        code_str = str(code_raw).strip()

                        # 如果代码长度超过6位，去掉前面的交易所前缀（如 sz, sh）
                        if len(code_str) > 6:
                            # 去掉前面的非数字字符（通常是2个字符的交易所代码）
                            code_str = ''.join(filter(str.isdigit, code_str))

                        # 如果是纯数字，移除前导0后补齐到6位
                        if code_str.isdigit():
                            code_clean = code_str.lstrip('0') or '0'  # 移除前导0，如果全是0则保留一个0
                            code = code_clean.zfill(6)  # 补齐到6位
                        else:
                            # 如果不是纯数字，尝试提取数字部分
                            code_digits = ''.join(filter(str.isdigit, code_str))
                            if code_digits:
                                code = code_digits.zfill(6)
                            else:
                                # 无法提取有效代码，跳过
                                continue

                        close = self._safe_float(row.get(price_col))
                        pct = self._safe_float(row.get(pct_col)) if pct_col else None
                        amt = self._safe_float(row.get(amount_col)) if amount_col else None
                        op = self._safe_float(row.get(open_col)) if open_col else None
                        hi = self._safe_float(row.get(high_col)) if high_col else None
                        lo = self._safe_float(row.get(low_col)) if low_col else None
                        pre = self._safe_float(row.get(pre_close_col)) if pre_close_col else None
                        vol = self._safe_float(row.get(volume_col)) if volume_col else None
                        
                        # 🔥 单位转换（区分数据源）：
                        # 全局统一口径：amount=元，volume=股
                        # - 东方财富 (eastmoney)：成交量单位为手 → 股（×100）；成交额已经是元，无需转换
                        # - 新浪财经 (sina)：成交量单位已经是股（无需转换）；成交额已经是元，无需转换
                        if src == "eastmoney" and vol is not None:
                            vol = vol * 100  # 手 → 股
                        # sina 的成交量单位已经是股，无需转换
                        # amount 已经是元，两个数据源均无需转换

                        result[code] = {
                            "close": close,
                            "pct_chg": pct,
                            "amount": amt,
                            "volume": vol,
                            "open": op,
                            "high": hi,
                            "low": lo,
                            "pre_close": pre,
                            "name": str(row.get(name_col)).strip() if name_col and row.get(name_col) is not None else None,
                            "turnover_rate": self._safe_float(row.get(turnover_col)) if turnover_col else None,
                            "vol_ratio": self._safe_float(row.get(vol_ratio_col)) if vol_ratio_col else None,
                        }

                    logger.info(f"✅ AKShare {src} 获取到 {len(result)} 只股票的实时行情")
                    return result

                except Exception as e:
                    logger.warning(f"AKShare {src} 获取失败: {e}")
                    last_error = e
                    continue

            # 所有数据源都失败了
            logger.error(f"所有 AKShare 数据源都失败了: {sources}, 最后错误: {last_error}")
            return None

        except Exception as e:
            logger.error(f"获取AKShare实时快照失败: {e}")
            return None

    def get_realtime_quote_single(self, code: str, timeout: int = 5) -> dict[str, Any] | None:
        """
        🔥 单只股票快速查询（使用 stock_zh_a_minute 接口，约 1 秒）
        
        Args:
            code: 股票代码（6位数字）
            timeout: 超时时间（秒），默认 5 秒
            
        Returns:
            Dict: {close, pct_chg, amount, volume, open, high, low, pre_close}
        """
        if not self.is_available():
            return None
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak
            
            code6 = str(code).zfill(6)
            logger.info(f"🔥 AKShare 单只股票快速查询: {code6}（超时: {timeout}秒）")
            
            def _fetch_minute_data():
                """获取分时数据"""
                # 根据股票代码判断交易所前缀
                symbol_with_prefix = f"sh{code6}" if code6.startswith(('60', '68')) else f"sz{code6}"
                
                df = ak.stock_zh_a_minute(symbol=symbol_with_prefix, period="1", adjust="")
                return df
            
            # 使用 ThreadPoolExecutor 添加超时保护
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch_minute_data)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    logger.warning(f"AKShare 单只股票查询超时（{timeout}秒）")
                    return None
            
            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare 单只股票查询返回空数据")
                return None

            # 🔥 确定列名（兼容中英文）
            day_col = "day" if "day" in df.columns else ("时间" if "时间" in df.columns else None)
            close_col = "close" if "close" in df.columns else ("收盘" if "收盘" in df.columns else None)
            open_col = "open" if "open" in df.columns else ("开盘" if "开盘" in df.columns else None)
            high_col = "high" if "high" in df.columns else ("最高" if "最高" in df.columns else None)
            low_col = "low" if "low" in df.columns else ("最低" if "最低" in df.columns else None)
            volume_col = "volume" if "volume" in df.columns else ("成交量" if "成交量" in df.columns else None)
            amount_col = "amount" if "amount" in df.columns else ("成交额" if "成交额" in df.columns else None)

            if not all([close_col, open_col, high_col, low_col, volume_col, amount_col]):
                logger.error(f"AKShare minute 数据列名异常: {df.columns.tolist()}")
                return None

            # 🔥 stock_zh_a_minute 返回多日分钟数据，需取最后一行所属交易日做当日聚合
            # 修复 bug-016: 原代码只取 iloc[-1] 单分钟值，导致 volume/amount 量级错误
            last_row = df.iloc[-1]
            trade_date_str = None
            df_today = df  # 兜底：无法识别日期列时用全量
            if day_col:
                last_day_val = str(last_row[day_col])
                date_part = last_day_val[:10]  # "2026-08-03"
                if len(date_part) >= 8:
                    trade_date_str = date_part.replace("-", "")  # "20260803"
                    df_today = df[df[day_col].astype(str).str.startswith(date_part)]
                    if df_today.empty:
                        df_today = df  # 过滤异常时兜底

            has_today = not getattr(df_today, "empty", True)

            # 🔥 当日聚合：close=最后一行，open=第一行，high=max，low=min，volume/amount=求和
            # 注意：stock_zh_a_minute 返回的列 dtype 是 object（字符串），必须先 pd.to_numeric 转换
            # 否则 sum()/max()/min() 会做字符串拼接而非数值运算
            if has_today:
                close = self._safe_float(df_today.iloc[-1][close_col])
                open_price = self._safe_float(df_today.iloc[0][open_col])
                high = self._safe_float(pd.to_numeric(df_today[high_col], errors="coerce").max())
                low = self._safe_float(pd.to_numeric(df_today[low_col], errors="coerce").min())
                volume = self._safe_float(pd.to_numeric(df_today[volume_col], errors="coerce").sum())
                amount = self._safe_float(pd.to_numeric(df_today[amount_col], errors="coerce").sum())
            else:
                close = self._safe_float(last_row.get(close_col))
                open_price = None
                high = None
                low = None
                volume = None
                amount = None

            # 🔥 全局统一口径：amount=元，volume=股
            # stock_zh_a_minute 的 volume 本身就是"股"（实测：当日分钟求和 ≈ 日线 volume）
            # 与 stock_zh_a_spot_em 不同（spot 的 volume 是"手"需要 ×100）
            # 修复 bug-016: 删除错误的 volume × 100

            # 🔥 返回数据，包含 trade_date（修复缓存 trade_date 卡在上一交易日的问题）
            # 涨跌幅和昨收价仍由调用方从缓存计算
            result = {
                "close": close,
                "pct_chg": None,  # 🔥 暂时设为 None，由调用方从缓存或历史数据计算
                "amount": amount,
                "volume": volume,
                "open": open_price,
                "high": high,
                "low": low,
                "pre_close": None,  # 🔥 暂时设为 None，由调用方从缓存获取
                "trade_date": trade_date_str,  # 🔥 新增：当日交易日 YYYYMMDD
            }

            logger.info(
                f"✅ AKShare 单只股票查询成功: {code6} close={close}, "
                f"trade_date={trade_date_str}, volume={volume}, amount={amount}"
            )
            return result
            
        except Exception as e:
            logger.error(f"AKShare 单只股票查询失败: {e}")
            return None

    def get_etf_spot_fund_flow(self, timeout: int = 45) -> pd.DataFrame | None:
        """获取全市场 ETF 资金流快照（东财 fund_etf_spot_em）。

        ETF Radar 核心数据源：单次全量返回全部 ETF，含主力净流入、超大单/大单/中单/小单
        净流入、量比、换手率、最新份额、流通/总市值等字段（约 1500+ 只，实测 ~19s）。
        使用 ThreadPoolExecutor 添加超时保护，避免网络问题长时间阻塞事件循环。

        Returns:
            原始 DataFrame（含中文列名），失败返回 None。
        """
        if not self.is_available():
            return None
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak

            def _fetch():
                return ak.fund_etf_spot_em()

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    logger.warning(f"AKShare ETF 资金流获取超时（{timeout}秒）")
                    return None

            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare ETF 资金流返回空数据")
                return None
            logger.info(f"✅ AKShare ETF 资金流获取成功: {len(df)} 只")
            return df
        except Exception as e:
            logger.error(f"AKShare ETF 资金流获取失败: {e}")
            return None

    def get_industry_fund_flow(self, symbol: str = "即时", timeout: int = 15) -> pd.DataFrame | None:
        """获取行业资金流（同花顺 stock_fund_flow_industry）。

        ETF Radar 行业维度交叉校验：返回约 90 个行业的流入/流出/净额/涨跌幅/领涨股
        （实测 symbol='即时' 约 0.8s）。东财 stock_sector_fund_flow_rank 连接被拒，
        不可用，故统一走同花顺。

        Args:
            symbol: '即时'（盘中实时）| '3日排行' | '5日排行' | '10日排行' | '20日排行'
        """
        if not self.is_available():
            return None
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak

            def _fetch():
                return ak.stock_fund_flow_industry(symbol=symbol)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    logger.warning(f"AKShare 行业资金流获取超时（{timeout}秒）")
                    return None

            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare 行业资金流返回空数据")
                return None
            logger.info(f"✅ AKShare 行业资金流获取成功: {len(df)} 个行业")
            return df
        except Exception as e:
            logger.error(f"AKShare 行业资金流获取失败: {e}")
            return None

    def get_individual_fund_flow(self, symbol: str = "即时", timeout: int = 25) -> pd.DataFrame | None:
        """获取全市场个股资金流（同花顺 stock_fund_flow_individual）。

        Stock Radar 个股「资金流」维度：一次返回全市场 5000+ 只股票的净额/流入/流出/换手率/成交额
        （实测 symbol='即时' 返回 5205 只）。东财 stock_individual_fund_flow_rank 连接被拒，
        不可用，故统一走同花顺。

        净额/流入/流出/成交额原始为「X.XX亿/万」字符串，本方法已规范化为数值（单位：元）。

        Args:
            symbol: '即时'（盘中实时）| '3日排行' | '5日排行' | '10日排行' | '20日排行'
        """
        if not self.is_available():
            return None
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            import akshare as ak

            def _fetch():
                return ak.stock_fund_flow_individual(symbol=symbol)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    logger.warning(f"AKShare 个股资金流获取超时（{timeout}秒）")
                    return None

            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare 个股资金流返回空数据")
                return None

            # 规范化「亿/万」字符串金额为数值（单位：元）
            for col in ("净额", "流入资金", "流出资金", "成交额"):
                if col in df.columns:
                    df[col] = df[col].map(_parse_cn_amount)
            # 换手率/涨跌幅为「21.43%」字符串 → 数值（%）
            for col in ("换手率", "涨跌幅"):
                if col in df.columns:
                    df[col] = df[col].map(_parse_pct_str)

            logger.info(f"✅ AKShare 个股资金流获取成功: {len(df)} 只")
            return df
        except Exception as e:
            logger.error(f"AKShare 个股资金流获取失败: {e}")
            return None

    def get_kline(self, code: str, period: str = "day", limit: int = 120, adj: str | None = None):
        """AKShare K-line as fallback. Try daily/week/month via stock_zh_a_hist; minutes via stock_zh_a_minute."""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            code6 = str(code).zfill(6)
            items = []
            if period in ("day", "week", "month"):
                period_map = {"day": "daily", "week": "weekly", "month": "monthly"}
                adjust_map = {None: "", "qfq": "qfq", "hfq": "hfq"}
                df = ak.stock_zh_a_hist(symbol=code6, period=period_map[period], adjust=adjust_map.get(adj, ""))
                if df is None or getattr(df, 'empty', True):
                    return None
                df = df.tail(limit)
                for _, row in df.iterrows():
                    items.append({
                        "time": str(row.get('日期') or row.get('date') or ''),
                        "open": self._safe_float(row.get('开盘') or row.get('open')),
                        "high": self._safe_float(row.get('最高') or row.get('high')),
                        "low": self._safe_float(row.get('最低') or row.get('low')),
                        "close": self._safe_float(row.get('收盘') or row.get('close')),
                        # 🔥 全局统一口径：volume=股（手×100），amount=元（AKShare 已经是元，无需转换）
                        "volume": (lambda v: v * 100 if v is not None else None)(self._safe_float(row.get('成交量') or row.get('volume'))),
                        "amount": self._safe_float(row.get('成交额') or row.get('amount')),
                    })
                return items
            else:
                # minutes
                per_map = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}
                if period not in per_map:
                    return None
                df = ak.stock_zh_a_minute(symbol=code6, period=per_map[period], adjust=adj if adj in ("qfq", "hfq") else "")
                if df is None or getattr(df, 'empty', True):
                    return None
                df = df.tail(limit)
                for _, row in df.iterrows():
                    items.append({
                        "time": str(row.get('时间') or row.get('day') or ''),
                        "open": self._safe_float(row.get('开盘') or row.get('open')),
                        "high": self._safe_float(row.get('最高') or row.get('high')),
                        "low": self._safe_float(row.get('最低') or row.get('low')),
                        "close": self._safe_float(row.get('收盘') or row.get('close')),
                        # 🔥 全局统一口径：volume=股（手×100），amount=元（AKShare 已经是元，无需转换）
                        "volume": (lambda v: v * 100 if v is not None else None)(self._safe_float(row.get('成交量') or row.get('volume'))),
                        "amount": self._safe_float(row.get('成交额') or row.get('amount')),
                    })
                return items
        except Exception as e:
            logger.error(f"AKShare get_kline failed: {e}")
            return None

    def get_news(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True):
        """AKShare-based news/announcements fallback"""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            code6 = str(code).zfill(6)
            items = []
            # news
            try:
                dfn = ak.stock_news_em(symbol=code6)
                if dfn is not None and not dfn.empty:
                    for _, row in dfn.head(limit).iterrows():
                        items.append({
                            # AkShare 将字段标准化为中文列名：新闻标题 / 文章来源 / 发布时间 / 新闻链接
                            "title": str(row.get('新闻标题') or row.get('标题') or row.get('title') or ''),
                            "source": str(row.get('文章来源') or row.get('来源') or row.get('source') or 'akshare'),
                            "time": str(row.get('发布时间') or row.get('time') or ''),
                            "url": str(row.get('新闻链接') or row.get('url') or ''),
                            "type": "news",
                        })
            except Exception:
                pass
            # announcements
            try:
                if include_announcements:
                    dfa = ak.stock_announcement_em(symbol=code6)
                    if dfa is not None and not dfa.empty:
                        for _, row in dfa.head(max(0, limit - len(items))).iterrows():
                            items.append({
                                "title": str(row.get('公告标题') or row.get('title') or ''),
                                "source": "akshare",
                                "time": str(row.get('公告时间') or row.get('time') or ''),
                                "url": str(row.get('公告链接') or row.get('url') or ''),
                                "type": "announcement",
                            })
            except Exception:
                pass
            # 🔥 按时间倒序排序后再截断：AKShare 返回顺序不代表时间顺序
            # （000001 等代码在东财同时是上证指数，大盘新闻会排在行业新闻前面），
            # 若不排序，行业新闻等有效内容易被顶出 limit 截断窗口。
            items.sort(key=lambda x: _news_time_key(x.get("time", "")), reverse=True)
            return items[:limit] if items else None
        except Exception as e:
            logger.error(f"AKShare get_news failed: {e}")
            return None

    def find_latest_trade_date(self) -> str | None:
        yesterday = (now_tz() - timedelta(days=1)).strftime("%Y%m%d")
        logger.info(f"AKShare: Using yesterday as trade date: {yesterday}")
        return yesterday

