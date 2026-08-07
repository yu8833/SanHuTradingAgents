"""Tushare 数据源提供者（桥接到 TushareAdapter）"""
import logging
from typing import Optional, Dict, Any, List
import asyncio

logger = logging.getLogger(__name__)


class TushareProvider:
    """Tushare 数据源提供者

    桥接到 app.services.data_sources.tushare_adapter.TushareAdapter
    提供同步和异步兼容的接口
    """

    def __init__(self, *args, **kwargs):
        self.token = kwargs.get("token") or ""
        self._adapter = None
        self._connected = False
        # Token 来源标记：'database' / 'env' / None（由 config_bridge 设置）
        self.token_source = None
        logger.info("[TushareProvider] 初始化中...")

    def _get_adapter(self):
        """获取 TushareAdapter 实例（懒加载）"""
        if self._adapter is None:
            try:
                from app.services.data_sources.tushare_adapter import TushareAdapter
                self._adapter = TushareAdapter()
                logger.info("[TushareProvider] TushareAdapter 加载成功")
            except Exception as e:
                logger.error(f"[TushareProvider] 加载 TushareAdapter 失败: {e}")
                self._adapter = None
        return self._adapter

    def is_available(self) -> bool:
        """检查 Tushare 是否可用"""
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return False
            return adapter.is_available()
        except Exception as e:
            logger.debug(f"[TushareProvider] is_available 检查失败: {e}")
            return False

    async def connect(self) -> bool:
        """连接 Tushare"""
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return False
            self._connected = adapter.is_available()
            return self._connected
        except Exception as e:
            logger.error(f"[TushareProvider] 连接失败: {e}")
            return False

    async def get_stock_list(self, market: str = "CN") -> List[Dict[str, Any]]:
        """获取股票列表

        Args:
            market: 市场，默认 CN

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
                    "market": market,
                    "exchange": exchange,
                    "currency": "CNY",
                    "ts_code": ts_code
                }

                result.append({
                    "code": code,
                    "symbol": code,
                    "name": name,
                    "market_info": market_info,
                    "data_source": "tushare",
                    "area": row.get("area", ""),
                    "industry": row.get("industry", ""),
                    "list_date": row.get("list_date", ""),
                    "ts_code": ts_code
                })

            logger.info(f"[TushareProvider] 获取到 {len(result)} 只股票")
            return result

        except Exception as e:
            logger.error(f"[TushareProvider] 获取股票列表失败: {e}")
            return []

    async def get_realtime_quotes_batch(self) -> Dict[str, Dict[str, Any]]:
        """批量获取全市场实时行情

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
                    "trade_date": None,
                    "data_source": "tushare",
                    "updated_at": None
                }
                from datetime import datetime
                quote_data["updated_at"] = datetime.utcnow()
                result[code] = quote_data

            logger.info(f"[TushareProvider] 获取到 {len(result)} 只股票的实时行情")
            return result

        except Exception as e:
            logger.error(f"[TushareProvider] 批量获取实时行情失败: {e}")
            return {}

    async def get_stock_quotes(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单只股票的实时行情

        Args:
            symbol: 股票代码

        Returns:
            行情数据字典
        """
        try:
            all_quotes = await self.get_realtime_quotes_batch()
            symbol6 = str(symbol).zfill(6)
            return all_quotes.get(symbol6)
        except Exception as e:
            logger.error(f"[TushareProvider] 获取 {symbol} 实时行情失败: {e}")
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
            df["pre_close"] = None
            df["change"] = None
            df["pct_chg"] = None

            return df

        except Exception as e:
            logger.error(f"[TushareProvider] 获取 {symbol} 历史数据失败: {e}")
            return None

    async def get_financial_data(self, symbol: str, limit: int = 20) -> Optional[Dict[str, Any]]:
        """获取财务数据

        Args:
            symbol: 股票代码
            limit: 获取期数

        Returns:
            财务数据字典
        """
        try:
            from tradingagents.dataflows.a_stock import get_fundamentals
            result = await asyncio.to_thread(get_fundamentals, symbol)
            return result if result else None
        except Exception as e:
            logger.error(f"[TushareProvider] 获取 {symbol} 财务数据失败: {e}")
            return None

    async def get_dividend_data(self, symbol: str) -> List[Dict[str, Any]]:
        """获取个股分红送配数据（Tushare pro.dividend）。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            list[dict]，每项含 ts_code/ann_date/end_date/ex_date/cash_div/cash_div_tax 等字段
        """
        try:
            adapter = self._get_adapter()
            if adapter is None:
                return []

            # 归一化 ts_code
            if "." not in symbol:
                if symbol.startswith(("6", "9")):
                    ts_code = f"{symbol}.SH"
                elif symbol.startswith(("8", "4")):
                    ts_code = f"{symbol}.BJ"
                else:
                    ts_code = f"{symbol}.SZ"
            else:
                ts_code = symbol

            df = await asyncio.to_thread(adapter.get_dividend_data, ts_code)
            if df is None or df.empty:
                return []
            return df.to_dict("records")
        except Exception as e:
            logger.error(f"[TushareProvider] 获取 {symbol} 分红数据失败: {e}")
            return []

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
            logger.error(f"[TushareProvider] 获取 {symbol} 新闻失败: {e}")
            return []

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单只股票的基础信息"""
        try:
            from tradingagents.dataflows.a_stock import resolve_ticker
            result = await asyncio.to_thread(resolve_ticker, symbol)
            return result if result else None
        except Exception as e:
            logger.error(f"[TushareProvider] 获取 {symbol} 基础信息失败: {e}")
            return None

    def get_stock_basic(self, *args, **kwargs):
        """兼容旧接口"""
        return []

    def get_daily(self, *args, **kwargs):
        """兼容旧接口"""
        return []

    def get_financial(self, *args, **kwargs):
        """兼容旧接口"""
        return {}

    def get_company_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取公司信息（兼容旧接口）"""
        try:
            from tradingagents.dataflows.a_stock import resolve_ticker
            return resolve_ticker(code)
        except Exception:
            return None


_default_tushare = None


def get_tushare_provider(*args, **kwargs):
    """获取 TushareProvider 单例"""
    global _default_tushare
    if _default_tushare is None:
        _default_tushare = TushareProvider(*args, **kwargs)
    return _default_tushare
