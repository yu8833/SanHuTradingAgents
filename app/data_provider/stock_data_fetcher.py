# -*- coding: utf-8 -*-
"""
===================================
简化版数据获取模块
===================================

复用 TradingAgents-CN 现有的数据获取逻辑，
为 StockTrendAnalyzer 提供 K 线数据。

数据来源：
1. mootdx (优先) - 实时 K 线数据
2. Sina Finance HTTP API (备选) - 兜底数据源
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class StockDataFetcher:
    """
    股票数据获取器
    
    封装 K 线数据获取逻辑，为速览分析提供数据
    """
    
    def __init__(self):
        """初始化数据获取器"""
        self._mootdx_client = None
    
    def _get_mootdx_client(self):
        """获取 mootdx 客户端（延迟初始化）"""
        if self._mootdx_client is None:
            try:
                from mootdx import Server
                self._mootdx_client = Server()
            except ImportError:
                logger.warning("mootdx 未安装，将使用 Sina API 获取数据")
                return None
            except Exception as e:
                logger.warning(f"mootdx 连接失败: {e}，将使用 Sina API 获取数据")
                return None
        return self._mootdx_client
    
    def _sina_kline_fallback(self, code: str, period: str = "daily", limit: int = 800) -> pd.DataFrame:
        """
        从 Sina Finance API 获取 K 线数据（mootdx 备选方案）
        
        Args:
            code: 股票代码（6位数字）
            period: K 线周期，支持 "daily" / "weekly" / "monthly"
            limit: 获取数据条数
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        import json as json_lib
        import requests
        
        # 确定市场前缀
        prefix = "sh" if code.startswith("6") else "sz"
        
        # Sina API 参数
        scale_map = {"daily": 240, "weekly": 240, "monthly": 240}
        scale = scale_map.get(period, 240)
        
        url = (
            "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData"
        )
        params = {
            "symbol": f"{prefix}{code}",
            "scale": str(scale),
            "ma": "no",
            "datalen": str(limit),
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = json_lib.loads(response.text)
            
            if not data:
                return pd.DataFrame()
            
            rows = []
            for item in data:
                rows.append({
                    "date": item["day"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": int(item["volume"]),
                })
            
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
            
        except Exception as e:
            logger.error(f"Sina API 获取 {code} K 线数据失败: {e}")
            return pd.DataFrame()
    
    def get_kline(
        self,
        code: str,
        period: str = "daily",
        limit: int = 100,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        获取股票 K 线数据
        
        数据源优先级（与参考项目 daily_stock_analysis 对齐）：
        1. DataSourceManager (akshare / tushare / baostock) - 优先使用项目统一数据源
        2. mootdx - 通达信
        3. Sina Finance API - 兜底
        
        Args:
            code: 股票代码（支持 6 位纯数字或带市场前缀如 sh600000）
            period: K 线周期，支持 "daily" / "weekly" / "monthly"
            limit: 获取数据条数（默认 100 条）
            end_date: 截止日期，格式 YYYY-MM-DD
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        # 标准化股票代码
        code = self._normalize_code(code)
        
        # 1. 优先使用 DataSourceManager（akshare / tushare / baostock）
        try:
            from app.services.data_sources.manager import DataSourceManager
            ds_manager = DataSourceManager()
            
            period_map = {"daily": "day", "weekly": "week", "monthly": "month"}
            ds_period = period_map.get(period, "day")
            
            items, source = ds_manager.get_kline_with_fallback(
                code=code, period=ds_period, limit=limit
            )
            
            if items and source:
                logger.info(f"使用 DataSourceManager({source}) 获取 {code} K 线数据成功，共 {len(items)} 条")
                df = self._items_to_dataframe(items)
                if df is not None and not df.empty:
                    # 过滤截止日期
                    if end_date:
                        df = df[df["date"] <= pd.to_datetime(end_date)]
                    return df
        except Exception as e:
            logger.warning(f"DataSourceManager 获取 {code} K 线数据失败: {e}，尝试备选数据源")
        
        # 2. 尝试使用 mootdx 获取数据
        client = self._get_mootdx_client()
        if client is not None:
            try:
                df = self._get_mootdx_kline(client, code, period, limit)
                if df is not None and not df.empty:
                    logger.info(f"使用 mootdx 获取 {code} K 线数据成功，共 {len(df)} 条")
                    return df
            except Exception as e:
                logger.warning(f"mootdx 获取 {code} K 线数据失败: {e}")
        
        # 3. 使用 Sina API 兜底
        logger.info(f"使用 Sina API 获取 {code} K 线数据")
        df = self._sina_kline_fallback(code, period, limit)
        
        # 过滤截止日期
        if end_date and not df.empty:
            df = df[df["date"] <= pd.to_datetime(end_date)]
        
        return df
    
    def _items_to_dataframe(self, items: list) -> Optional[pd.DataFrame]:
        """将 DataSourceManager 返回的 items 转换为标准 DataFrame"""
        if not items:
            return None
        
        rows = []
        for item in items:
            rows.append({
                "date": item.get("time", ""),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(float(item.get("volume", 0))),
            })
        
        df = pd.DataFrame(rows)
        if df.empty:
            return None
        
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    
    def _get_mootdx_kline(
        self,
        client,
        code: str,
        period: str = "daily",
        limit: int = 100,
    ) -> Optional[pd.DataFrame]:
        """
        使用 mootdx 获取 K 线数据
        
        Args:
            client: mootdx Server 客户端
            code: 股票代码
            period: K 线周期
            limit: 数据条数
            
        Returns:
            DataFrame or None
        """
        # mootdx 的 period 参数映射
        frequency_map = {
            "daily": 9,    # 日线
            "weekly": 5,   # 周线
            "monthly": 6,  # 月线
        }
        frequency = frequency_map.get(period, 9)
        
        # 判断市场
        if code.startswith("6"):
            market = 1  # 上交所
        else:
            market = 0  # 深交所
        
        try:
            # 调用 mootdx
            df = client.df(code=code, market=market, frequency=frequency, adjust="")
            
            if df is None or df.empty:
                return None
            
            # 标准化列名
            df = df.copy()
            
            # 尝试匹配不同的列名格式
            column_mapping = {}
            for col in df.columns:
                col_lower = col.lower()
                if "open" in col_lower and "p" not in col_lower:
                    column_mapping[col] = "open"
                elif "high" in col_lower:
                    column_mapping[col] = "high"
                elif "low" in col_lower:
                    column_mapping[col] = "low"
                elif "close" in col_lower:
                    column_mapping[col] = "close"
                elif "volume" in col_lower or "vol" in col_lower:
                    column_mapping[col] = "volume"
                elif "date" in col_lower or "time" in col_lower:
                    column_mapping[col] = "date"
            
            df = df.rename(columns=column_mapping)
            
            # 确保必要的列存在
            required_cols = ["date", "open", "high", "low", "close", "volume"]
            if not all(col in df.columns for col in required_cols):
                # 尝试另一种格式
                df = self._parse_alternative_format(df)
            
            # 确保 date 列是 datetime 类型
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            
            # 只保留需要的列
            existing_cols = [col for col in required_cols if col in df.columns]
            df = df[existing_cols].copy()
            
            # 排序并限制条数
            df = df.sort_values("date").tail(limit).reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.warning(f"mootdx 解析 {code} 数据失败: {e}")
            return None
    
    def _parse_alternative_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """尝试解析替代格式的 DataFrame"""
        # 常见的列名格式
        alt_mappings = [
            # 格式1: date, open, high, low, close, volume, amount
            {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"},
            # 格式2: 时间, 开盘, 最高, 最低, 收盘, 成交量
            {"时间": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"},
            # 格式3: datetime, open, high, low, close, volume
            {"datetime": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"},
        ]
        
        for mapping in alt_mappings:
            rename_dict = {}
            for old_col, new_col in mapping.items():
                if old_col in df.columns:
                    rename_dict[old_col] = new_col
            
            if rename_dict:
                df_renamed = df.rename(columns=rename_dict)
                # 检查是否所有必需列都存在
                required = ["date", "open", "high", "low", "close", "volume"]
                if all(col in df_renamed.columns for col in required):
                    return df_renamed
        
        return df
    
    def _normalize_code(self, code: str) -> str:
        """
        标准化股票代码
        
        Args:
            code: 股票代码，支持多种格式
            
        Returns:
            6 位纯数字代码
        """
        # 去除空格
        code = code.strip()
        
        # 去除常见前缀后缀
        for prefix in ["sh", "sz", "SH", "SZ", "sh", "sz"]:
            if code.startswith(prefix):
                code = code[len(prefix):]
        
        for suffix in [".SH", ".SZ", ".sh", ".sz"]:
            if code.endswith(suffix):
                code = code[:-len(suffix)]
        
        # 只保留数字部分
        code = "".join(c for c in code if c.isdigit())
        
        # 取前6位
        return code[:6]
    
    def get_realtime_quote(self, code: str) -> Optional[dict]:
        """
        获取实时行情数据
        
        Args:
            code: 股票代码
            
        Returns:
            dict with keys: code, name, price, change, change_pct, volume, amount, high, low, open, etc.
        """
        import requests
        
        code = self._normalize_code(code)
        
        # 确定市场前缀
        prefix = "sh" if code.startswith("6") else "sz"
        
        # Sina 实时行情 API
        url = f"http://hq.sinajs.cn/list={prefix}{code}"
        headers = {
            "Referer": "http://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = "gbk"
            text = response.text
            
            # 解析返回数据
            # 格式: var hq_str_sh600000="名称,今开,昨收,当前价,最高,最低,竞买价,竞卖价,成交量,成交额,日期,时间,..."
            match = self._parse_sina_quote(text)
            if match:
                return match
                
        except Exception as e:
            logger.error(f"获取 {code} 实时行情失败: {e}")
        
        return None
    
    def _parse_sina_quote(self, text: str) -> Optional[dict]:
        """解析新浪实时行情返回的文本"""
        import re
        
        # 匹配格式: var hq_str_xxx="..."
        pattern = r'hq_str_\w+="([^"]+)"'
        match = re.search(pattern, text)
        
        if not match:
            return None
        
        data_str = match.group(1)
        fields = data_str.split(",")
        
        if len(fields) < 32:
            return None
        
        try:
            name = fields[0]
            open_price = float(fields[1]) if fields[1] else 0
            prev_close = float(fields[2]) if fields[2] else 0
            price = float(fields[3]) if fields[3] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0
            volume = int(float(fields[8])) if fields[8] else 0  # 成交量（手）
            amount = float(fields[9]) if fields[9] else 0  # 成交额（元）
            date = fields[30] if len(fields) > 30 else ""
            time = fields[31] if len(fields) > 31 else ""
            
            # 计算涨跌
            change = price - prev_close if prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            return {
                "name": name,
                "open": open_price,
                "prev_close": prev_close,
                "price": price,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": amount,
                "change": change,
                "change_pct": change_pct,
                "date": date,
                "time": time,
            }
            
        except (ValueError, IndexError) as e:
            logger.error(f"解析实时行情失败: {e}")
            return None


# 单例模式
_fetcher: Optional[StockDataFetcher] = None


def get_stock_data_fetcher() -> StockDataFetcher:
    """获取股票数据获取器单例"""
    global _fetcher
    if _fetcher is None:
        _fetcher = StockDataFetcher()
    return _fetcher


def get_kline(code: str, period: str = "daily", limit: int = 100) -> pd.DataFrame:
    """
    便捷函数：获取 K 线数据
    
    Args:
        code: 股票代码
        period: K 线周期
        limit: 数据条数
        
    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    return get_stock_data_fetcher().get_kline(code, period, limit)


def get_realtime_quote(code: str) -> Optional[dict]:
    """
    便捷函数：获取实时行情
    
    Args:
        code: 股票代码
        
    Returns:
        dict with realtime quote data
    """
    return get_stock_data_fetcher().get_realtime_quote(code)
