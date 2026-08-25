"""AKShare 数据源提供者（桥接到 AKShareAdapter）"""
import logging
from typing import Optional, Dict, Any, List
import asyncio

logger = logging.getLogger(__name__)


class AkshareProvider:
    """AKShare 数据源提供者

    桥接到 app.services.data_sources.akshare_adapter.AKShareAdapter
    提供同步和异步兼容的接口
    """

    def __init__(self, *args, **kwargs):
        self._adapter = None
        self._connected = False
        logger.info("[AkshareProvider] 初始化中...")

    def _get_adapter(self):
        """获取 AKShareAdapter 实例（懒加载）"""
        if self._adapter is None:
            try:
                from app.services.data_sources.akshare_adapter import AKShareAdapter
                self._adapter = AKShareAdapter()
                logger.info("[AkshareProvider] AKShareAdapter 加载成功")
            except Exception as e:
                logger.error(f"[AkshareProvider] 加载 AKShareAdapter 失败: {e}")
                self._adapter = None
        return self._adapter

    async def test_connection(self) -> bool:
        """测试 AKShare 连接"""
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return False
            self._connected = adapter.is_available()
            return self._connected
        except Exception as e:
            logger.error(f"[AkshareProvider] 测试连接失败: {e}")
            return False

    def is_available(self) -> bool:
        """检查 AKShare 是否可用（同步接口）"""
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return False
            return adapter.is_available()
        except Exception as e:
            logger.debug(f"[AkshareProvider] is_available 检查失败: {e}")
            return False

    async def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表

        Returns:
            股票信息列表，每个元素包含 code, name 等字段
        """
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return []

            df = await asyncio.to_thread(adapter.get_stock_list)
            if df is None or df.empty:
                return []

            result = []
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code", ""))
                symbol = str(row.get("symbol", "")).zfill(6)
                name = str(row.get("name", ""))

                if "." in ts_code:
                    code = ts_code.split(".")[0].zfill(6)
                else:
                    code = symbol

                exchange = ""
                if ts_code.endswith(".SH"):
                    exchange = "SSE"
                elif ts_code.endswith(".SZ"):
                    exchange = "SZSE"
                elif ts_code.endswith(".BJ"):
                    exchange = "BSE"

                market_info = {
                    "market": "CN",
                    "exchange": exchange,
                    "currency": "CNY",
                    "ts_code": ts_code
                }

                result.append({
                    "code": code,
                    "symbol": code,
                    "name": name,
                    "market_info": market_info,
                    "data_source": "akshare",
                    "area": row.get("area", ""),
                    "industry": row.get("industry", ""),
                    "list_date": row.get("list_date", ""),
                    "ts_code": ts_code
                })

            logger.info(f"[AkshareProvider] 获取到 {len(result)} 只股票")
            return result

        except Exception as e:
            logger.error(f"[AkshareProvider] 获取股票列表失败: {e}")
            return []

    async def get_stock_basic_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只股票的基础信息

        Args:
            code: 股票代码

        Returns:
            基础信息字典
        """
        try:
            from tradingagents.dataflows.a_stock import resolve_ticker
            result = await asyncio.to_thread(resolve_ticker, code)
            if result:
                if isinstance(result, dict):
                    result["data_source"] = "akshare"
                    result["source"] = "akshare"
                return result
            return None
        except Exception as e:
            logger.error(f"[AkshareProvider] 获取 {code} 基础信息失败: {e}")
            return None

    async def get_batch_stock_quotes(self, symbols: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """批量获取股票实时行情

        Args:
            symbols: 股票代码列表，为 None 则获取全市场

        Returns:
            Dict[code, quote_data] 格式的行情数据
        """
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return {}

            quotes = await asyncio.to_thread(adapter.get_realtime_quotes)
            if not quotes:
                return {}

            result = {}
            for code, q in quotes.items():
                quote_data = {
                    "code": code,
                    "symbol": code,
                    "close": q.get("close"),
                    "price": q.get("close"),
                    "open": q.get("open"),
                    "high": q.get("high"),
                    "low": q.get("low"),
                    "pre_close": q.get("pre_close"),
                    "volume": q.get("volume"),
                    "amount": q.get("amount"),
                    "pct_chg": q.get("pct_chg"),
                    "change_percent": q.get("pct_chg"),
                    "trade_date": q.get("trade_date"),
                    "data_source": "akshare",
                    "updated_at": None
                }
                from datetime import datetime
                quote_data["updated_at"] = datetime.now()
                result[code] = quote_data

            if symbols:
                filtered = {}
                for sym in symbols:
                    sym6 = str(sym).zfill(6)
                    if sym6 in result:
                        filtered[sym6] = result[sym6]
                logger.info(f"[AkshareProvider] 批量获取行情: 全市场 {len(result)} 只，过滤后 {len(filtered)} 只")
                return filtered

            logger.info(f"[AkshareProvider] 获取到 {len(result)} 只股票的实时行情")
            return result

        except Exception as e:
            logger.error(f"[AkshareProvider] 批量获取实时行情失败: {e}")
            return {}

    async def get_stock_quotes(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单只股票的实时行情（🔥 使用快速查询接口）

        Args:
            symbol: 股票代码

        Returns:
            行情数据字典
        """
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return None

            # 🔥 使用单只股票快速查询（约 1 秒），而不是全市场获取（约 25 秒）
            symbol6 = str(symbol).zfill(6)
            quotes = await asyncio.to_thread(adapter.get_realtime_quote_single, symbol6, 5)
            
            if quotes:
                # 添加 symbol 和 code 字段
                quotes["symbol"] = symbol6
                quotes["code"] = symbol6
                return quotes
            
            # 如果快速查询失败，回退到全市场获取（作为兜底）
            logger.warning(f"[AkshareProvider] 单只股票快速查询失败，回退到全市场获取")
            all_quotes = await self.get_batch_stock_quotes()
            return all_quotes.get(symbol6)
        except Exception as e:
            logger.error(f"[AkshareProvider] 获取 {symbol} 实时行情失败: {e}")
            return None

    async def get_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ):
        """获取历史K线数据

        Args:
            symbol: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期 daily/weekly/monthly

        Returns:
            pandas DataFrame
        """
        try:
            import pandas as pd
            adapter = self._get_adapter()
            if adapter is None:
                return None

            period_map = {
                "daily": "day",
                "weekly": "week",
                "monthly": "month"
            }
            adapter_period = period_map.get(period, "day")

            start_date_clean = start_date.replace("-", "")
            end_date_clean = end_date.replace("-", "")

            import datetime
            start_dt = datetime.datetime.strptime(start_date_clean, "%Y%m%d")
            end_dt = datetime.datetime.strptime(end_date_clean, "%Y%m%d")
            days_diff = (end_dt - start_dt).days + 1

            kline_data = await asyncio.to_thread(
                adapter.get_kline,
                symbol,
                period=adapter_period,
                limit=max(days_diff, 100)
            )

            if not kline_data:
                return None

            df = pd.DataFrame(kline_data)

            if "time" in df.columns:
                df["trade_date"] = df["time"].apply(
                    lambda x: x[:10].replace("-", "") if len(x) >= 10 else x
                )

            for col in ["open", "high", "low", "close", "volume", "amount"]:
                if col not in df.columns:
                    df[col] = None

            df["ts_code"] = ""
            # 🔥 修复（F4）：AKShare 日线本包含昨收/涨跌幅，但 adapter.get_kline 未透出，
            #    这里按相邻日线用前一交易日 close 回算 pre_close/change/pct_chg，
            #    避免 stock_daily_quotes 写入 null 涨跌字段，保证被 AKShare 兜底补数的
            #    股票日线（K线/涨跌幅）展示准确。
            df = df.sort_values("trade_date").reset_index(drop=True)
            _closes = df["close"].tolist()
            pre_closes: list = []
            changes: list = []
            pcts: list = []
            prev_c = None
            for c in _closes:
                try:
                    c = None if c is None else float(c)
                except (TypeError, ValueError):
                    c = None
                if c is None:
                    pre_closes.append(None)
                    changes.append(None)
                    pcts.append(None)
                elif prev_c not in (None, 0):
                    pre_closes.append(prev_c)
                    changes.append(round(c - prev_c, 2))
                    pcts.append(round((c / prev_c - 1.0) * 100.0, 2))
                else:
                    pre_closes.append(None)
                    changes.append(None)
                    pcts.append(None)
                prev_c = c
            df["pre_close"] = pre_closes
            df["change"] = changes
            df["pct_chg"] = pcts

            return df

        except Exception as e:
            logger.error(f"[AkshareProvider] 获取 {symbol} 历史数据失败: {e}")
            return None

    async def get_financial_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取财务数据

        Args:
            symbol: 股票代码

        Returns:
            财务数据字典
        """
        try:
            from tradingagents.dataflows.a_stock import get_fundamentals
            result = await asyncio.to_thread(get_fundamentals, symbol)
            return result if result else None
        except Exception as e:
            logger.error(f"[AkshareProvider] 获取 {symbol} 财务数据失败: {e}")
            return None

    async def get_stock_news(
        self,
        symbol: str,
        limit: int = 50,
        hours_back: int = 24
    ) -> List[Dict[str, Any]]:
        """获取股票新闻

        Args:
            symbol: 股票代码
            limit: 最大新闻数量
            hours_back: 回溯小时数

        Returns:
            新闻列表
        """
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return []

            days = max(1, hours_back // 24)
            news = await asyncio.to_thread(
                adapter.get_news,
                symbol,
                days=days,
                limit=limit
            )

            return news if news else []

        except Exception as e:
            logger.error(f"[AkshareProvider] 获取 {symbol} 新闻失败: {e}")
            return []

    def get_stock_basic(self, *args, **kwargs):
        """兼容旧接口"""
        return []

    def get_daily(self, *args, **kwargs):
        """兼容旧接口"""
        return []

    def get_financial(self, *args, **kwargs):
        """兼容旧接口"""
        return {}

    def get_news(self, *args, **kwargs):
        """兼容旧接口"""
        return []


_default_akshare = None


def get_akshare_provider(*args, **kwargs):
    """获取 AkshareProvider 单例"""
    global _default_akshare
    if _default_akshare is None:
        _default_akshare = AkshareProvider(*args, **kwargs)
    return _default_akshare
