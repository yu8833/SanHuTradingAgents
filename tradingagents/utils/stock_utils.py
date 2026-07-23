"""股票工具兼容层"""
from typing import Dict, Any


class StockUtils:
    """股票工具类 - 兼容层"""

    @staticmethod
    def get_market_info(symbol: str) -> Dict[str, Any]:
        """根据股票代码判断市场类型

        Args:
            symbol: 股票代码 (例如 '600000', '000001', '301356')

        Returns:
            Dict: 包含 market, exchange, currency 等字段
        """
        if not symbol:
            return {"market": "unknown", "exchange": "unknown", "currency": "CNY"}

        s = str(symbol).strip().upper()
        # 移除前缀后缀
        for suffix in (".SH", ".SZ", ".BJ"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        for prefix in ("SH", "SZ", "BJ"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break

        code = s.strip()
        if not code.isdigit():
            return {"market": "unknown", "exchange": "unknown", "currency": "CNY"}

        if code.startswith(("60", "68", "90")):
            return {"market": "china_a", "exchange": "SSE", "currency": "CNY", "name": ""}
        elif code.startswith(("00", "30", "20")):
            return {"market": "china_a", "exchange": "SZSE", "currency": "CNY", "name": ""}
        elif code.startswith(("8", "43", "92")):
            return {"market": "china_a", "exchange": "BSE", "currency": "CNY", "name": ""}
        elif code.startswith("4") or code.startswith("8"):
            return {"market": "china_b", "exchange": "BSE", "currency": "CNY", "name": ""}
        elif len(code) == 5:
            return {"market": "hk", "exchange": "HKEX", "currency": "HKD", "name": ""}
        else:
            return {"market": "us", "exchange": "NASDAQ/NYSE", "currency": "USD", "name": ""}

    @staticmethod
    def get_market_type(symbol: str) -> str:
        """简化的市场类型判断"""
        info = StockUtils.get_market_info(symbol)
        return info.get("market", "unknown")

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """标准化股票代码"""
        s = str(symbol).strip().upper()
        for suffix in (".SH", ".SZ", ".BJ"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        for prefix in ("SH", "SZ", "BJ"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        return s.strip()
