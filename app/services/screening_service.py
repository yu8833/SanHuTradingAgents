from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from app.services.screening.eval_utils import (
    collect_fields_from_conditions as _collect_fields_from_conditions_util,
    evaluate_conditions as _evaluate_conditions_util,
    evaluate_fund_conditions as _evaluate_fund_conditions_util,
    safe_float as _safe_float_util,
)

# --- DSL 约束 ---
ALLOWED_FIELDS = {
    "open", "high", "low", "close", "vol", "amount",
    "pct_chg",
    "ma5", "ma10", "ma20", "ma60",
    "ema12", "ema26",
    "dif", "dea", "macd_hist",
    "rsi14",
    "boll_mid", "boll_upper", "boll_lower",
    "atr14",
    "kdj_k", "kdj_d", "kdj_j",
    "pe", "pb", "pe_ttm", "pb_mrq", "roe", "market_cap",
    "total_mv", "circ_mv",
    "turnover_rate", "volume_ratio",
    "market", "board", "industry", "area",
    "macd_golden_fork", "kdj_golden_fork",
    "macd_golden_fork_n", "kdj_golden_fork_n",
    "ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross",
    "ma_bullish", "ma_bearish",
    "boll_break_upper", "boll_break_lower",
    "ma5_ma10_golden", "ma10_ma20_golden",
}

BASE_FIELDS = {"open", "high", "low", "close", "vol", "amount", "pct_chg"}
TECH_FIELDS = {
    "ma5", "ma10", "ma20", "ma60",
    "ema12", "ema26",
    "dif", "dea", "macd_hist",
    "rsi14",
    "boll_mid", "boll_upper", "boll_lower",
    "atr14",
    "kdj_k", "kdj_d", "kdj_j",
    "macd_golden_fork", "kdj_golden_fork",
    "macd_golden_fork_n", "kdj_golden_fork_n",
    "ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross",
    "ma_bullish", "ma_bearish",
    "boll_break_upper", "boll_break_lower",
    "ma5_ma10_golden", "ma10_ma20_golden",
}
FUND_FIELDS = {"pe", "pb", "pe_ttm", "pb_mrq", "roe", "market_cap", "total_mv", "circ_mv",
               "turnover_rate", "volume_ratio", "market", "board", "industry", "area"}

ALLOWED_OPS = {">", "<", ">=", "<=", "==", "!=", "eq", "ne",
                "between", "in", "not_in", "contains", "cross_up", "cross_down"}


@dataclass
class ScreeningParams:
    market: str = "CN"
    date: Optional[str] = None
    adj: str = "qfq"
    limit: int = 50
    offset: int = 0
    order_by: Optional[List[Dict[str, str]]] = None


import logging
logger = logging.getLogger("agents")


# ==========================
# Redis 缓存
# ==========================
_redis_client: Any = None
_redis_lock = threading.Lock()


def _get_sync_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            from app.core.sync_redis import get_sync_redis
            _redis_client = get_sync_redis()
        except Exception as e:
            logger.warning(f"⚠️ Redis模块导入失败: {e}")
            _redis_client = None
    return _redis_client


class KlineCache:
    PREFIX = "kline"

    def __init__(self, ttl_trading: int = 300, ttl_holiday: int = 3600):
        self.ttl_trading = ttl_trading
        self.ttl_holiday = ttl_holiday

    def _key(self, code: str, period: str, limit: int, adj: str) -> str:
        adj_s = f"_{adj}" if adj else ""
        return f"{self.PREFIX}:{code}:{period}:{limit}{adj_s}"

    def _ttl(self) -> int:
        now = datetime.now()
        if now.weekday() >= 5:
            return self.ttl_holiday
        hm = now.hour * 100 + now.minute
        if 930 <= hm <= 1500:
            return self.ttl_trading
        return self.ttl_holiday

    def get(self, code: str, period: str, limit: int, adj: str) -> Optional[List[Dict]]:
        client = _get_sync_redis()
        if client is None:
            return None
        try:
            data = client.get(self._key(code, period, limit, adj))
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    def set(self, code: str, period: str, limit: int, adj: str, data: List[Dict]):
        client = _get_sync_redis()
        if client is None:
            return
        try:
            client.setex(self._key(code, period, limit, adj), self._ttl(), json.dumps(data, ensure_ascii=False))
        except Exception:
            pass


# ==========================
# 技术指标计算（纯pandas）
# ==========================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """使用纯 pandas 计算技术指标"""
    if df is None or df.empty or len(df) < 30:
        return df

    dfc = df.copy()
    close = dfc['close']

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dfc['dif'] = ema12 - ema26
    dfc['dea'] = dfc['dif'].ewm(span=9, adjust=False).mean()
    dfc['macd_hist'] = (dfc['dif'] - dfc['dea']) * 2

    # KDJ (9, 3, 3)
    low_min = dfc['low'].rolling(window=9).min()
    high_max = dfc['high'].rolling(window=9).max()
    rsv = (close - low_min) / (high_max - low_min + 1e-10) * 100
    rsv = rsv.fillna(50)
    dfc['kdj_k'] = rsv.ewm(alpha=1/3, adjust=False).mean()
    dfc['kdj_d'] = dfc['kdj_k'].ewm(alpha=1/3, adjust=False).mean()
    dfc['kdj_j'] = 3 * dfc['kdj_k'] - 2 * dfc['kdj_d']

    # 均线
    dfc['ma5'] = close.rolling(5).mean()
    dfc['ma10'] = close.rolling(10).mean()
    dfc['ma20'] = close.rolling(20).mean()
    dfc['ma60'] = close.rolling(60).mean() if len(dfc) >= 60 else close.rolling(len(dfc)).mean()

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    dfc['rsi14'] = 100 - (100 / (1 + rs))

    # 布林带 (20, 2)
    boll_mid = close.rolling(20).mean()
    boll_std = close.rolling(20).std()
    dfc['boll_mid'] = boll_mid
    dfc['boll_upper'] = boll_mid + 2 * boll_std
    dfc['boll_lower'] = boll_mid - 2 * boll_std

    # ATR (14)
    high_low = dfc['high'] - dfc['low']
    high_close = (dfc['high'] - dfc['close'].shift(1)).abs()
    low_close = (dfc['low'] - dfc['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    dfc['atr14'] = tr.rolling(14).mean()

    # 均线多头/空头排列
    ma5 = dfc['ma5']
    ma10 = dfc['ma10']
    ma20 = dfc['ma20']
    ma60 = dfc['ma60']
    dfc['ma_bullish'] = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)
    dfc['ma_bearish'] = (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)

    return dfc


# ==========================
# 主筛选服务（优化版）
# ==========================
class ScreeningService:
    def __init__(self):
        self._data_source_manager = None
        self._kline_cache = KlineCache()
        self._max_workers = 8  # 并发数（避免API限流）
        self._batch_size = 20   # 每批大小

    def _get_data_source_manager(self):
        if self._data_source_manager is None:
            try:
                from app.services.data_sources.manager import DataSourceManager
                self._data_source_manager = DataSourceManager()
                logger.info("✅ 数据源管理器初始化成功")
            except Exception as e:
                logger.error(f"❌ 数据源管理器初始化失败: {e}")
        return self._data_source_manager

    def _get_kline(self, code: str, limit: int = 220, adj: str = "qfq") -> Optional[List[Dict]]:
        """获取K线数据（Redis缓存优先 → 网络）"""
        # 1. 尝试Redis缓存
        cached = self._kline_cache.get(code, "day", limit, adj)
        if cached:
            return cached

        # 2. 从网络获取
        manager = self._get_data_source_manager()
        if manager is None:
            return None

        kline_data, _ = manager.get_kline_with_fallback(code, "day", limit, adj)
        if kline_data:
            # 写入缓存（异步，不阻塞）
            threading.Thread(
                target=self._kline_cache.set,
                args=(code, "day", limit, adj, kline_data),
                daemon=True
            ).start()
        return kline_data

    def _get_turnover_rates_batch(self, codes: List[str]) -> Dict[str, float]:
        """批量获取股票的换手率（从数据库）"""
        result = {}
        try:
            from app.core.database import get_mongo_db_sync
            db = get_mongo_db_sync()
            if db is None:
                return result
            # stock_screening_view 中每只股票只有一条最新记录，字段是 trade_date
            docs = list(db.stock_screening_view.find(
                {"code": {"$in": codes}},
                {"code": 1, "turnover_rate": 1, "_id": 0}
            ))
            for doc in docs:
                if doc.get("turnover_rate") is not None:
                    result[doc["code"]] = float(doc["turnover_rate"])
        except Exception:
            pass
        return result

    def _process_one(self, code: str, conditions: Dict, need_tech: bool, params: ScreeningParams, turnover_map: Dict[str, float]) -> Optional[Dict]:
        """处理单只股票"""
        try:
            kline_data = self._get_kline(code, 220, params.adj)
            if not kline_data or len(kline_data) == 0:
                return None

            df = pd.DataFrame(kline_data)
            if df.empty:
                return None

            # 列名标准化
            col_map = {c: c.lower() for c in df.columns if c.lower() != c}
            if col_map:
                df = df.rename(columns=col_map)

            if "close" in df.columns:
                df["pct_chg"] = df["close"].pct_change() * 100.0

            if need_tech and len(df) >= 30:
                df = compute_indicators(df)

            # 补充数据库字段（turnover_rate）
            db_turnover = turnover_map.get(code)
            if db_turnover is not None:
                df["turnover_rate"] = db_turnover

            last = df.iloc[-1]

            # 评估条件
            passes = _evaluate_conditions_util(df, conditions, ALLOWED_FIELDS, ALLOWED_OPS)
            if not passes:
                return None

            # 构建结果
            item = {"code": code}
            item.update({
                "close": _safe_float_util(last.get("close")),
                "pct_chg": _safe_float_util(last.get("pct_chg")),
                "amount": _safe_float_util(last.get("amount")),
                "turnover_rate": _safe_float_util(last.get("turnover_rate")),
                "ma20": _safe_float_util(last.get("ma20")) if need_tech else None,
                "rsi14": _safe_float_util(last.get("rsi14")) if need_tech else None,
                "kdj_k": _safe_float_util(last.get("kdj_k")) if need_tech else None,
                "kdj_d": _safe_float_util(last.get("kdj_d")) if need_tech else None,
                "kdj_j": _safe_float_util(last.get("kdj_j")) if need_tech else None,
                "dif": _safe_float_util(last.get("dif")) if need_tech else None,
                "dea": _safe_float_util(last.get("dea")) if need_tech else None,
                "macd_hist": _safe_float_util(last.get("macd_hist")) if need_tech else None,
                "boll_upper": _safe_float_util(last.get("boll_upper")) if need_tech else None,
                "boll_mid": _safe_float_util(last.get("boll_mid")) if need_tech else None,
                "boll_lower": _safe_float_util(last.get("boll_lower")) if need_tech else None,
                "atr14": _safe_float_util(last.get("atr14")) if need_tech else None,
                "ma_bullish": bool(last.get("ma_bullish")) if need_tech else None,
                "ma_bearish": bool(last.get("ma_bearish")) if need_tech else None,
            })
            return item
        except Exception as e:
            return None

    def _get_universe(self) -> List[str]:
        """获取A股代码集合"""
        try:
            from app.core.database import get_mongo_db_sync, settings as _db_settings
            db = get_mongo_db_sync()
            collection = db.stock_basic_info
            query = {
                "$or": [
                    {"market_info.market": "CN"},
                    {"category": "stock_cn"},
                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                ]
            }
            codes: List[str] = []
            try:
                docs = list(collection.find(query, {"code": 1, "_id": 0}))
                codes = [doc.get("code") for doc in docs if doc.get("code")]
            except (TypeError, AttributeError):
                try:
                    from pymongo import MongoClient
                    sync_client = MongoClient(_db_settings.MONGO_URI, serverSelectionTimeoutMS=5000)
                    sync_db = sync_client[_db_settings.MONGO_DB]
                    docs = list(sync_db.stock_basic_info.find(query, {"code": 1, "_id": 0}))
                    codes = [doc.get("code") for doc in docs if doc.get("code")]
                    sync_client.close()
                except Exception as inner_e:
                    logger.error(f"❌ 同步直连MongoDB获取股票列表失败: {inner_e}")
            if codes:
                logger.info(f"📊 从 MongoDB 获取到 {len(codes)} 只A股股票")
                return codes
            return ["000001", "000002", "000858", "600519", "600036", "601318", "300750"]
        except Exception as e:
            logger.error(f"❌ 从 MongoDB 获取股票列表失败: {e}")
            return ["000001", "000002", "000858", "600519", "600036", "601318", "300750"]

    # --- 公共入口 ---
    def run(self, conditions: Dict[str, Any], params: ScreeningParams) -> Dict[str, Any]:
        symbols = self._get_universe()
        if not symbols:
            return {"total": 0, "items": []}

        # 解析条件
        needed_fields = _collect_fields_from_conditions_util(conditions, ALLOWED_FIELDS)
        order_fields = {o.get("field") for o in (params.order_by or []) if o.get("field")}
        all_needed = set(needed_fields) | set(order_fields)
        need_tech = any(f in TECH_FIELDS for f in all_needed)
        # 扩展扫描范围
        MAX_SCAN = 500 if need_tech else 2000
        symbols = symbols[:MAX_SCAN]

        logger.info(f"📊 筛选开始，扫描 {len(symbols)} 只，技术指标={need_tech}，并发={self._max_workers}")

        # 批量获取换手率（从数据库）
        turnover_map: Dict[str, float] = {}
        if "turnover_rate" in all_needed:
            turnover_map = self._get_turnover_rates_batch(symbols)
            logger.info(f"📊 批量获取换手率: {len(turnover_map)} 只股票有数据")

        # 预热数据源管理器（主线程初始化，避免子线程冲突）
        self._get_data_source_manager()

        results: List[Dict[str, Any]] = []
        t0 = time.time()

        # 并行处理（使用线程池，复用连接）
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(self._process_one, code, conditions, need_tech, params, turnover_map): code
                for code in symbols
            }
            done = 0
            for future in as_completed(futures):
                done += 1
                try:
                    result = future.result(timeout=60)
                    if result:
                        results.append(result)
                    if done % 50 == 0:
                        elapsed = time.time() - t0
                        logger.info(f"📊 进度: {done}/{len(symbols)} ({elapsed:.1f}s), 当前 {len(results)} 只通过")
                except Exception:
                    pass

        elapsed = time.time() - t0
        total = len(results)
        logger.info(f"📊 筛选完成: {total} 只通过，耗时 {elapsed:.1f}s")

        # 排序
        if params.order_by:
            for order in reversed(params.order_by):
                f = order.get("field")
                d = (order.get("direction") or "desc").lower()
                if f in ALLOWED_FIELDS:
                    results.sort(key=lambda x: (x.get(f) is None, x.get(f)), reverse=(d == "desc"))

        # 分页
        start = params.offset or 0
        end = start + (params.limit or 50)
        page_items = results[start:end]

        return {"total": total, "items": page_items}
