"""
三买三卖交易策略服务（融合 GMMA Pro + ΔG 景气框架）

基于 Wind 三买三卖系统，融合 GMMA Pro 慢组压缩度 S1 预警和 ATR×3 安全网机制，
配合 ΔG 景气框架作为基本面过滤器。

三类买点：
- B1 左侧买点: BIAS(60) ∈ [-30%, -20%]
- B2 突破买点: 放量 + 中阳 + 站上 MA55 & MA60
- B3 回踩买点: 回调至 MA60 附近(±5%) + 放量中阳支撑

三类卖点：
- S1 加速卖点: BIAS ≥ 阈值（30%/65%/100%）或 GMMA 慢组压缩 > 30%
- S2 跌破卖点: 连续2日跌破 MA5 & MA8 & MA13
- S3 清仓卖点: 跌破 MA55 & MA60 且 MA60 拐头向下

安全网: 单日跌幅 > ATR(14) × 3 → 强制减至 50%
"""

import asyncio
import logging
import numpy as np
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple

from app.core.database import get_mongo_db
from app.utils.technical_indicators import (
    calc_ma_np, calc_ema_np, calc_macd_np, calc_bias_np,
    calc_atr_np, calc_volume_ratio_np, calc_ma_slope_np,
    calc_ma_convergence_np, is_zhongyang_np,
    calc_slow_group_compression_np, classify_stock_type,
    get_s1_threshold, calc_market_trend,
    calc_fast_slow_separation_np, calc_strong_bull_duration_np
)

logger = logging.getLogger(__name__)


def _validate_score_dimensions(dimensions: Dict[str, int], actual_score: int,
                                  bonus: int = 0, service_name: str = "") -> Dict[str, Any]:
    """
    评分维度加总校验。
    确保各维度满分之和为100，实际得分在[0,100]之间。
    """
    total_max = sum(dimensions.values())
    result = {
        "passed": True,
        "errors": [],
        "warnings": [],
        "dimensions": dimensions,
        "total_max": total_max,
        "actual_score": actual_score,
        "bonus": bonus,
    }
    if total_max != 100:
        result["passed"] = False
        result["errors"].append(f"维度满分总和不等于100: {total_max}")
    if actual_score < 0 or actual_score > 100:
        result["passed"] = False
        result["errors"].append(f"实际得分越界: {actual_score} (应为0~100)")
    if bonus != 0 and abs(bonus) > 30:
        result["warnings"].append(f"加分项异常: {bonus} (正常范围±30)")
    if not result["passed"]:
        logger.warning(f"[{service_name}] 评分校验失败: {result['errors']}")
    return result


def _to_native(value: Any) -> Any:
    """将 numpy 标量类型转换为 Python 原生类型"""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    return value


class ThreeBuysThreeSellsService:
    """三买三卖交易策略服务"""

    def __init__(self):
        self.db = None
        self._dg_service = None

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def _get_dg_service(self):
        if self._dg_service is None:
            from app.services.dg_prosperity_service import get_dg_prosperity_service
            self._dg_service = get_dg_prosperity_service()
        return self._dg_service

    async def _get_all_stock_codes(self) -> List[dict]:
        """获取所有 A 股股票代码列表"""
        db = await self._get_db()
        collection = db["stock_basic_info"]
        cursor = collection.find(
            {
                "$or": [
                    {"category": "stock_cn"},
                    {"sse": {"$in": ["上海证券交易所", "深圳证券交易所", "上交所", "深交所"]}},
                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                ]
            },
            projection={"_id": 0, "code": 1, "symbol": 1, "name": 1, "industry": 1, "total_mv": 1}
        )
        stocks = await cursor.to_list(length=6000)
        result = []
        for s in stocks:
            code = s.get("code") or s.get("symbol")
            if code and len(str(code)) == 6 and str(code).isdigit():
                code = str(code).zfill(6)
                market_cap = s.get("total_mv") or 0
                if isinstance(market_cap, (int, float)):
                    market_cap_yi = market_cap / 10000
                else:
                    try:
                        market_cap_yi = float(market_cap) / 10000 if market_cap else 0
                    except (ValueError, TypeError):
                        market_cap_yi = 0
                result.append({
                    "code": code,
                    "name": s.get("name", ""),
                    "industry": s.get("industry", ""),
                    "market_cap": market_cap_yi
                })
        return result

    async def _batch_get_quotes(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """批量获取多只股票日线数据，按数据源优先级去重"""
        db = await self._get_db()
        collection = db["stock_daily_quotes"]

        DATA_SOURCE_PRIORITY = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}

        cursor = collection.find(
            {
                "code": {"$in": stock_codes},
                "period": "daily",
                "trade_date": {"$gte": start_date, "$lte": end_date}
            },
            projection={
                "_id": 0, "code": 1, "trade_date": 1,
                "open": 1, "close": 1, "high": 1, "low": 1,
                "volume": 1, "amount": 1, "pct_chg": 1, "data_source": 1
            }
        ).sort("trade_date", 1)

        all_quotes = await cursor.to_list(length=len(stock_codes) * 400)

        quotes_by_date_by_stock = defaultdict(dict)
        for quote in all_quotes:
            code = quote.get("code", "")
            if not code or len(code) != 6 or not code.isdigit():
                continue
            trade_date = quote.get("trade_date", "")
            if not trade_date:
                continue
            existing = quotes_by_date_by_stock[code].get(trade_date)
            if existing is None:
                quotes_by_date_by_stock[code][trade_date] = quote
            else:
                existing_src = existing.get("data_source", "")
                new_src = quote.get("data_source", "")
                if DATA_SOURCE_PRIORITY.get(new_src, 0) > DATA_SOURCE_PRIORITY.get(existing_src, 0):
                    quotes_by_date_by_stock[code][trade_date] = quote

        result = {}
        for code, date_map in quotes_by_date_by_stock.items():
            sorted_quotes = sorted(date_map.values(), key=lambda x: x.get("trade_date", ""))
            result[code] = sorted_quotes
        return result

    def _precompute_indicators(
        self,
        kline_data: List[Dict[str, Any]],
        stock_code: str,
        stock_name: str,
        industry: str = "",
        market_cap: float = 0
    ) -> Optional[Dict[str, Any]]:
        """预计算单只股票所有技术指标（numpy 向量化）

        Returns:
            包含所有指标数组的字典，数据不足返回 None
        """
        if len(kline_data) < 70:
            return None

        def safe_float(v, default=0.0):
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        valid_data = []
        for k in kline_data:
            o = safe_float(k.get("open"))
            c = safe_float(k.get("close"))
            h = safe_float(k.get("high"))
            l = safe_float(k.get("low"))
            v = safe_float(k.get("volume"))
            if o > 0 and c > 0 and h > 0 and l > 0 and v > 0:
                valid_data.append(k)

        if len(valid_data) < 70:
            return None

        n = len(valid_data)
        dates = [k["trade_date"] for k in valid_data]
        opens = np.array([safe_float(k["open"]) for k in valid_data], dtype=np.float64)
        closes = np.array([safe_float(k["close"]) for k in valid_data], dtype=np.float64)
        highs = np.array([safe_float(k["high"]) for k in valid_data], dtype=np.float64)
        lows = np.array([safe_float(k["low"]) for k in valid_data], dtype=np.float64)
        volumes = np.array([safe_float(k["volume"]) for k in valid_data], dtype=np.float64)

        pct_chgs = np.zeros(n, dtype=np.float64)
        for i in range(1, n):
            pct = valid_data[i].get("pct_chg")
            if pct is not None:
                pct_chgs[i] = safe_float(pct)
            elif closes[i - 1] > 0:
                pct_chgs[i] = (closes[i] - closes[i - 1]) / closes[i - 1] * 100

        ma5 = calc_ma_np(closes, 5)
        ma8 = calc_ma_np(closes, 8)
        ma13 = calc_ma_np(closes, 13)
        ma20 = calc_ma_np(closes, 20)
        ma55 = calc_ma_np(closes, 55)
        ma60 = calc_ma_np(closes, 60)
        ma65 = calc_ma_np(closes, 65)

        ema30 = calc_ema_np(closes, 30)

        bias60 = calc_bias_np(closes, ma60)

        dif, dea, macd_hist = calc_macd_np(closes, 12, 26, 9)

        atr14 = calc_atr_np(highs, lows, closes, 14)

        volume_ratio = calc_volume_ratio_np(volumes, 20)

        ma60_slope = calc_ma_slope_np(ma60, 5)

        short_convergence = calc_ma_convergence_np([ma5, ma8, ma13])
        mid_convergence = calc_ma_convergence_np([ma55, ma60, ma65])

        zhongyang = is_zhongyang_np(closes, opens, 0.05)

        slow_compression = calc_slow_group_compression_np(ema30, ma60, 60)

        fast_slow_separation = calc_fast_slow_separation_np(ma13, ma55)

        strong_bull_duration = calc_strong_bull_duration_np(
            ma5, ma8, ma13, ma55, ma60, ma65
        )

        stock_type = classify_stock_type(market_cap, industry, stock_name)
        s1_threshold = get_s1_threshold(stock_type)

        date_to_idx = {d: i for i, d in enumerate(dates)}

        # 向量化预计算：所有日期的GMMA强多状态、个股趋势、过热指标
        # GMMA强多: 快组多头(ma5>ma8>ma13) + 慢组多头(ma55>ma60>ma65) + 快组在慢组之上(ma13>ma55)
        gmma_strong_bull_arr = (
            (ma5[65:] > ma8[65:]) & (ma8[65:] > ma13[65:]) &
            (ma55[65:] > ma60[65:]) & (ma60[65:] > ma65[65:]) &
            (ma13[65:] > ma55[65:])
        )
        gmma_strong_bull = np.zeros(n, dtype=bool)
        gmma_strong_bull[65:] = gmma_strong_bull_arr

        # 个股趋势: up/down/neutral 预计算
        above_ma60 = closes > ma60
        ma20_above_ma60 = ma20 > ma60
        slope_up = ma60_slope > 0
        stock_trend_arr = np.full(n, "neutral", dtype=object)
        stock_trend_arr[60:] = np.where(
            (above_ma60[60:] & ma20_above_ma60[60:] & slope_up[60:]), "up",
            np.where(
                (~above_ma60[60:] & ~ma20_above_ma60[60:] & ~slope_up[60:]), "down", "neutral"
            )
        )

        return {
            "n": n,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "pct_chgs": pct_chgs,
            "ma5": ma5, "ma8": ma8, "ma13": ma13,
            "ma20": ma20,
            "ma55": ma55, "ma60": ma60, "ma65": ma65,
            "ema30": ema30,
            "bias60": bias60,
            "dif": dif, "dea": dea, "macd_hist": macd_hist,
            "atr14": atr14,
            "volume_ratio": volume_ratio,
            "ma60_slope": ma60_slope,
            "short_convergence": short_convergence,
            "mid_convergence": mid_convergence,
            "zhongyang": zhongyang,
            "slow_compression": slow_compression,
            "fast_slow_separation": fast_slow_separation,
            "strong_bull_duration": strong_bull_duration,
            "stock_type": stock_type,
            "s1_threshold": s1_threshold,
            "market_cap": market_cap,
            "industry": industry,
            "date_to_idx": date_to_idx,
            "gmma_strong_bull": gmma_strong_bull,
            "stock_trend": stock_trend_arr,
        }

    # ===== 信号检测方法 =====

    def _check_b1(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """B1 左侧买点: BIAS(60) ∈ [-30%, -20%]

        enable_strict_b1=True时增加确认条件:
        - 三天不新低: 近3天最低价 > 前10天最低价
        - 下降市均线粘合向上
        """
        if idx < 63:
            return None
        bias = ind["bias60"][idx]
        bias_min = params.get("bias_b1_min", -35.0)
        bias_max = params.get("bias_b1_max", -15.0)
        if bias < bias_min or bias > bias_max:
            return None

        enable_strict_b1 = params.get("enable_strict_b1", False)
        market_trend = params.get("_market_trend", "neutral")

        if enable_strict_b1:
            # 三天不新低确认: 近3天最低价 > 前10天最低价
            if idx < 13:
                return None
            recent_lows = ind["lows"][idx - 2:idx + 1]
            earlier_lows = ind["lows"][idx - 12:idx - 2]
            if len(recent_lows) < 3 or len(earlier_lows) < 10:
                return None
            min_recent = float(np.min(recent_lows))
            min_earlier = float(np.min(earlier_lows))
            if min_recent <= min_earlier:
                return None

            # 大盘下降趋势中，B1需要更强确认：短期均线粘合向上
            if market_trend == "down":
                # 短期均线粘合: 间距 < 2%
                sc = ind["short_convergence"][idx]
                if sc > 2.0:
                    return None
                ma5_slope = ind["ma5"][idx] - ind["ma5"][idx - 2]
                ma8_slope = ind["ma8"][idx] - ind["ma8"][idx - 2]
                if ma5_slope <= 0 or ma8_slope <= 0:
                    return None

        return {
            "type": "B1",
            "type_label": "左侧买点",
            "trigger_price": ind["closes"][idx],
            "bias60": round(float(bias), 2),
            "stop_loss_bias": -35.0,
            "position_pct": 0.33
        }

    def _check_b2(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """B2 突破买点: 放量 + 中阳 + 站上 MA55 & MA60 至少 2 条"""
        if idx < 60:
            return None
        vol_ratio = ind["volume_ratio"][idx]
        vol_threshold = params.get("breakout_volume_ratio", 1.5)
        zhongyang_threshold = params.get("zhongyang_threshold", 0.05)

        if vol_ratio < vol_threshold:
            return None

        zhongyang_arr = is_zhongyang_np(
            ind["closes"], ind["opens"], zhongyang_threshold
        )
        if not zhongyang_arr[idx]:
            return None

        close = ind["closes"][idx]
        ma55 = ind["ma55"][idx]
        ma60 = ind["ma60"][idx]
        ma65 = ind["ma65"][idx]

        above_count = sum([close > ma55, close > ma60, close > ma65])
        if above_count < 2:
            return None

        # 前一天不在中期均线上方（刚突破）—— 放宽为前一天不超过1条在上方
        if idx < 1:
            return None
        prev_close = ind["closes"][idx - 1]
        prev_above = sum([
            prev_close > ind["ma55"][idx - 1],
            prev_close > ind["ma60"][idx - 1],
            prev_close > ind["ma65"][idx - 1]
        ])
        if prev_above >= 3:
            return None

        return {
            "type": "B2",
            "type_label": "突破买点",
            "trigger_price": close,
            "volume_ratio": round(float(vol_ratio), 2),
            "ma55": round(float(ma55), 2),
            "ma60": round(float(ma60), 2),
            "position_pct": 0.67
        }

    def _check_b3(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """B3 回踩买点: 30日内BIAS曾>15%、MA13>MA55、当前BIAS∈±5% + 放量中阳支撑"""
        if idx < 60:
            return None
        bias = ind["bias60"][idx]
        pullback_range = params.get("pullback_bias_range", 5.0)

        if abs(bias) > pullback_range:
            return None

        # 前提1: 30日内曾有较大正乖离（放宽到10%）
        lookback = min(30, idx)
        max_bias_30 = float(np.max(ind["bias60"][idx - lookback:idx]))
        if max_bias_30 < 10.0:
            return None

        # 前提2: MA13 仍在 MA55 上方（中期趋势未坏）
        if ind["ma13"][idx] <= ind["ma55"][idx]:
            return None

        # 放量中阳确认
        vol_ratio = ind["volume_ratio"][idx]
        vol_threshold = params.get("breakout_volume_ratio", 1.5)
        zhongyang_threshold = params.get("zhongyang_threshold", 0.05)

        if vol_ratio < vol_threshold * 0.8:
            return None

        zhongyang_arr = is_zhongyang_np(
            ind["closes"], ind["opens"], zhongyang_threshold * 0.8
        )
        if not zhongyang_arr[idx]:
            return None

        return {
            "type": "B3",
            "type_label": "回踩买点",
            "trigger_price": ind["closes"][idx],
            "bias60": round(float(bias), 2),
            "max_bias_30": round(max_bias_30, 2),
            "position_pct": 1.0
        }

    def _check_gmma_b2(
        self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """GMMA版B2加仓信号: 强多5-25根+首次回踩快组下沿+收阳站回+放量+20日内涨幅>15%

        GMMA Pro实战手册定义的B2是加仓信号，捕捉健康上涨中的第一次像样回调。
        只在强多前期（5-25根）才作为建仓信号，后期回调风险高。
        """
        if idx < 30:
            return None

        # 强多状态且持续5-25根（早期-中期，成熟后期不建仓）
        duration = int(ind["strong_bull_duration"][idx])
        min_duration = params.get("gmma_b2_min_duration", 5)
        max_duration = params.get("gmma_b2_max_duration", 25)
        if duration < min_duration or duration > max_duration:
            return None

        # 前置条件: 20日内曾有明显上涨（BIAS > 15%）
        lookback_rise = min(20, idx)
        max_bias_20 = float(np.max(ind["bias60"][idx - lookback_rise:idx + 1]))
        if max_bias_20 < 12.0:
            return None

        # 最近3-5根K线最低价触及或跌破MA13（回调确认）
        lookback = min(5, idx)
        recent_lows = ind["lows"][idx - lookback + 1:idx + 1]
        recent_ma13 = ind["ma13"][idx - lookback + 1:idx + 1]
        touched = np.any(recent_lows <= recent_ma13 * 1.01)
        if not touched:
            return None

        # 当根K线收阳 + 收盘价站回MA13之上
        close = ind["closes"][idx]
        open_p = ind["opens"][idx]
        ma13 = ind["ma13"][idx]
        if close <= open_p or close <= ma13:
            return None

        # 放量确认（流动性自适应）
        vol_ratio = ind["volume_ratio"][idx]
        market_cap = ind.get("market_cap", 0)
        vol_threshold = self._get_volume_threshold(market_cap, params)
        if vol_ratio < vol_threshold:
            return None

        # 快慢分离度不宜过高（<12%，避免在过热区回调）
        separation = float(ind["fast_slow_separation"][idx])
        if separation > 12.0:
            return None

        return {
            "type": "B2G",
            "type_label": "GMMA加仓",
            "trigger_price": close,
            "volume_ratio": round(float(vol_ratio), 2),
            "ma13": round(float(ma13), 2),
            "strong_bull_duration": duration,
            "max_bias_20": round(max_bias_20, 2),
            "position_pct": 0.8
        }

    def _get_volume_threshold(self, market_cap: float, params: Dict[str, Any]) -> float:
        """流动性自适应放量阈值: 大盘股1.3x，小盘股2.0x

        大盘股流动性好，1.3倍放量已足够确认；
        小盘股流动性差，需要2.0倍以上才是真突破。
        """
        base = params.get("breakout_volume_ratio", 1.5)
        enable_adaptive = params.get("enable_adaptive_volume", True)
        if not enable_adaptive:
            return base
        if market_cap >= 1000:  # 1000亿以上大盘股
            return base * 0.87  # ≈1.3
        elif market_cap <= 100:  # 100亿以下小盘股
            return base * 1.33  # ≈2.0
        else:
            # 线性插值
            ratio = (market_cap - 100) / 900
            return base * (1.33 - ratio * 0.46)

    def _check_bottom_pickup(self, ind: Dict[str, Any], idx: int) -> bool:
        """抄底信号: 3天不新低 + 短期均线粘合向上"""
        if idx < 20:
            return False
        # 三天不新低: 近3天最低价 > 前10天最低价
        recent_lows = ind["lows"][max(0, idx - 2):idx + 1]
        earlier_lows = ind["lows"][max(0, idx - 13):max(0, idx - 2)]
        if len(recent_lows) < 3 or len(earlier_lows) < 5:
            return False
        if float(np.min(recent_lows)) <= float(np.min(earlier_lows)):
            return False

        # 短期均线粘合: 间距 < 2%
        sc = ind["short_convergence"][idx]
        if sc > 2.0:
            return False

        # MA5 和 MA8 都在上升
        if idx < 8:
            return False
        ma5_rising = bool(ind["ma5"][idx] > ind["ma5"][idx - 3] and ind["ma5"][idx] > ind["ma5"][idx - 1])
        ma8_rising = bool(ind["ma8"][idx] > ind["ma8"][idx - 3] and ind["ma8"][idx] > ind["ma8"][idx - 1])
        if not (ma5_rising and ma8_rising):
            return False

        return True

    def _check_macd_divergence(self, ind: Dict[str, Any], idx: int, window: int = 20) -> str:
        """MACD 背离检测: 'top' 顶背离 / 'bottom' 底背离 / '' 无"""
        if idx < window + 5:
            return ""

        closes = ind["closes"]
        dif = ind["dif"]
        start = max(0, idx - window)
        window_closes = closes[start:idx + 1]
        window_dif = dif[start:idx + 1]

        if len(window_closes) < 10:
            return ""

        price_new_high = float(np.max(window_closes[-5:])) > float(np.max(window_closes[:-5]))
        price_new_low = float(np.min(window_closes[-5:])) < float(np.min(window_closes[:-5]))
        dif_new_high = float(np.max(window_dif[-5:])) > float(np.max(window_dif[:-5]))
        dif_new_low = float(np.min(window_dif[-5:])) < float(np.min(window_dif[:-5]))

        if price_new_high and not dif_new_high:
            return "top"
        if price_new_low and not dif_new_low:
            return "bottom"
        return ""

    def _check_volume_price_divergence(self, ind: Dict[str, Any], idx: int, window: int = 5) -> bool:
        """量价背离: 价涨量跌 + 在 MA60 上方"""
        if idx < window + 20:
            return False
        if ind["closes"][idx] <= ind["ma60"][idx]:
            return False
        price_rising = bool(ind["closes"][idx] > ind["closes"][idx - window])
        avg_vol_recent = float(np.mean(ind["volumes"][idx - 4:idx + 1]))
        avg_vol_earlier = float(np.mean(ind["volumes"][idx - window - 4:idx - window + 1])) if idx > window + 4 else avg_vol_recent
        volume_falling = avg_vol_recent < avg_vol_earlier * 0.9
        return bool(price_rising and volume_falling)

    def _check_s1(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """S1 减仓预警: BIAS 超过阈值 或 GMMA 慢组压缩 > 30%"""
        if idx < 60:
            return None
        bias = ind["bias60"][idx]
        s1_threshold = ind.get("s1_threshold", 30.0)

        reasons = []
        if bias >= s1_threshold:
            reasons.append(f"BIAS60={bias:.1f}% 超过阈值{s1_threshold}%")

        if params.get("enable_slow_group_s1", True):
            compression = ind["slow_compression"][idx]
            # S1需强多持续>10根K线（GMMA Pro要求）
            min_s1_duration = params.get("gmma_s1_min_duration", 10)
            duration = int(ind["strong_bull_duration"][idx])
            if compression > 0.3 and ind["bias60"][idx] > 10 and duration >= min_s1_duration:
                reasons.append(f"GMMA慢组压缩度={compression*100:.0f}% 超过30%")

        if reasons:
            return {
                "type": "S1",
                "type_label": "减仓预警",
                "trigger_price": ind["closes"][idx],
                "bias60": round(float(bias), 2),
                "reasons": reasons,
                "sell_pct": 0.33
            }
        return None

    def _check_s2(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """S2 主减仓: 连续N日跌破 MA5 & MA8 & MA13（全部）"""
        break_days = params.get("s2_break_days", 2)
        if idx < break_days + 13:
            return None

        for i in range(idx - break_days + 1, idx + 1):
            close = ind["closes"][i]
            if close >= ind["ma5"][i] or close >= ind["ma8"][i] or close >= ind["ma13"][i]:
                return None

        return {
            "type": "S2",
            "type_label": "主减仓",
            "trigger_price": ind["closes"][idx],
            "sell_pct": 0.67
        }

    def _check_s3(self, ind: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
        """S3 清仓: 跌破 MA55 & MA60 且 MA60 拐头向下"""
        if idx < 65:
            return None
        close = ind["closes"][idx]
        ma55 = ind["ma55"][idx]
        ma60 = ind["ma60"][idx]
        ma60_slope = ind["ma60_slope"][idx]

        if close < ma55 and close < ma60 and ma60_slope < 0:
            return {
                "type": "S3",
                "type_label": "清仓卖出",
                "trigger_price": close,
                "ma60_slope": round(float(ma60_slope), 2),
                "sell_pct": 1.0
            }
        return None

    def _check_safety_net(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """安全网: 单日跌幅 > ATR(14) × 3"""
        if idx < 14:
            return None
        if not params.get("enable_safety_net", True):
            return None

        atr = ind["atr14"][idx]
        prev_close = ind["closes"][idx - 1] if idx > 0 else ind["closes"][idx]
        pct_drop = ind["pct_chgs"][idx]

        if prev_close > 0:
            atr_pct = atr / prev_close * 100
        else:
            atr_pct = 5.0

        if pct_drop < -atr_pct * 3:
            return {
                "type": "SafetyNet",
                "type_label": "安全网触发",
                "trigger_price": ind["closes"][idx],
                "daily_drop": round(float(pct_drop), 2),
                "atr_pct": round(float(atr_pct), 2),
                "sell_pct": 0.5
            }
        return None

    def _check_gmma_strong_bull(self, ind: Dict[str, Any], idx: int) -> bool:
        """判断GMMA强多状态: 快组多头 + 慢组多头 + 快组在慢组之上

        强多状态是GMMA Pro系统中最核心的状态过滤:
        - 快组多头排列(MA5>MA8>MA13): 散户共识向上
        - 慢组多头排列(MA55>MA60>MA65): 机构共识向上
        - 快组在慢组之上(MA13>MA55): 短期力量战胜中长期阻力
        """
        if idx < 65:
            return False
        fast_bull = bool(ind["ma5"][idx] > ind["ma8"][idx] > ind["ma13"][idx])
        slow_bull = bool(ind["ma55"][idx] > ind["ma60"][idx] > ind["ma65"][idx])
        fast_above_slow = bool(ind["ma13"][idx] > ind["ma55"][idx])
        return fast_bull and slow_bull and fast_above_slow

    def _check_trailing_stop(
        self,
        ind: Dict[str, Any],
        idx: int,
        highest_price: float,
        buy_price: float,
        atr_multiplier: float = 2.5,
        min_profit_pct: float = 8.0
    ) -> Optional[Dict[str, Any]]:
        """ATR移动止损: 盈利达到min_profit_pct后才启动，止损价 = 最高价 - ATR(14) × multiplier

        移动止损是趋势策略锁定利润的核心机制:
        - 盈利不足min_profit_pct时不启动（用初始止损）
        - 止损价随最高价上移，不会回退
        - ATR×2.5 既能跟住上涨又能过滤正常波动
        """
        if idx < 14:
            return None
        atr = ind["atr14"][idx]
        if atr <= 0:
            return None
        close = ind["closes"][idx]
        # 盈利未达标，不启动移动止损
        if buy_price <= 0 or (close - buy_price) / buy_price * 100 < min_profit_pct:
            return None
        stop_price = highest_price - atr * atr_multiplier
        # 止损价至少不低于成本价
        stop_price = max(stop_price, buy_price * 1.01)
        if close < stop_price:
            return {
                "type": "TrailingStop",
                "type_label": "移动止损",
                "trigger_price": close,
                "stop_price": round(float(stop_price), 2),
                "highest_price": round(float(highest_price), 2),
                "atr": round(float(atr), 2),
                "sell_pct": 1.0
            }
        return None

    def _check_overheat(self, ind: Dict[str, Any], idx: int, params: Dict[str, Any]) -> bool:
        """过热检查: 快慢分离度>15% 或 BIAS过高 → 禁止新建仓

        GMMA Pro速查卡: 分离度>15%警惕均值回归
        Wind教材: 震荡市频繁交易是大忌
        """
        if not params.get("enable_overheat_filter", True):
            return False
        separation = float(ind["fast_slow_separation"][idx])
        overheat_sep = params.get("overheat_separation_pct", 15.0)
        bias = float(ind["bias60"][idx])
        overheat_bias = params.get("overheat_bias_pct", 40.0)
        return separation > overheat_sep or bias > overheat_bias

    def _get_position_multiplier(
        self,
        market_trend: str,
        stock_trend: str,
        params: Dict[str, Any]
    ) -> float:
        """大盘×个股四象限仓位矩阵

        大盘↑个股↑: 1.0 满仓做多
        大盘↑个股↓: 0.3 快进快出
        大盘↓个股↑: 0.5 谨慎持有
        大盘↓个股↓: 0.0 空仓观望

        当 multiplier <= 0 时，不允许新建仓。
        """
        if not params.get("enable_market_matrix", True):
            return 1.0
        matrix = {
            ("up", "up"): 1.0,
            ("up", "down"): 0.3,
            ("neutral", "up"): 0.7,
            ("neutral", "neutral"): 0.5,
            ("neutral", "down"): 0.2,
            ("down", "up"): 0.5,
            ("down", "down"): 0.0,
        }
        return matrix.get((market_trend, stock_trend), 0.5)

    def _get_b1_position_multiplier(
        self,
        market_trend: str,
        stock_trend: str,
        params: Dict[str, Any]
    ) -> float:
        """B1左侧买点的仓位系数（根据大盘趋势调节）

        B1是逆向抄底，大盘下降时用小仓位试探，大盘上升时可以加大:
        - 大盘上升: 0.8（可以重仓抄底）
        - 大盘震荡: 0.5（中等仓位）
        - 大盘下降: 0.3（小仓位试探）
        """
        if not params.get("enable_market_matrix", True):
            return 1.0
        if market_trend == "up":
            return 0.8
        elif market_trend == "neutral":
            return 0.5
        else:  # down
            return 0.3

    def _judge_stock_trend(self, ind: Dict[str, Any], idx: int) -> str:
        """判断个股趋势: up=上升, down=下降, neutral=震荡"""
        if idx < 60:
            return "neutral"
        # 股价在MA60上方 + MA20>MA60 + MA60斜率向上 = 上升
        above_ma60 = ind["closes"][idx] > ind["ma60"][idx]
        ma20_above_ma60 = ind["ma20"][idx] > ind["ma60"][idx]
        slope_up = ind["ma60_slope"][idx] > 0
        if above_ma60 and ma20_above_ma60 and slope_up:
            return "up"
        # 股价在MA60下方 + MA20<MA60 + MA60斜率向下 = 下降
        if not above_ma60 and not ma20_above_ma60 and not slope_up:
            return "down"
        return "neutral"

    # ===== 信号评分 =====

    def _calc_signal_score(
        self,
        ind: Dict[str, Any],
        idx: int,
        signal_type: str,
        market_trend: str,
        dg_info: Optional[dict]
    ) -> Tuple[int, List[str], Dict[str, Any]]:
        """信号强度评分（100 分制）

        维度: 成交量 / K线涨幅 / 均线形态 / 大盘配合 / MACD
        + ΔG 加分项
        """
        score = 0
        details = []
        dimensions: Dict[str, int] = {}

        # 成交量（20分）
        vr = ind["volume_ratio"][idx]
        if vr >= 2.0:
            score += 20
            dimensions["成交量"] = 20
            details.append(f"成交量强(量比{vr:.1f})")
        elif vr >= 1.5:
            score += 10
            dimensions["成交量"] = 10
            details.append(f"成交量达标(量比{vr:.1f})")
        else:
            dimensions["成交量"] = 0
            details.append(f"成交量不足(量比{vr:.1f})")

        # K线涨幅（20分）
        body_pct = (ind["closes"][idx] - ind["opens"][idx]) / ind["opens"][idx] * 100 if ind["opens"][idx] > 0 else 0
        if body_pct >= 7:
            score += 20
            dimensions["K线涨幅"] = 20
            details.append(f"大阳线(实体{body_pct:.1f}%)")
        elif body_pct >= 5:
            score += 10
            dimensions["K线涨幅"] = 10
            details.append(f"中阳线(实体{body_pct:.1f}%)")
        else:
            dimensions["K线涨幅"] = 0
            details.append(f"涨幅不足(实体{body_pct:.1f}%)")

        # 均线形态（20分）
        if signal_type == "B1":
            sc = ind["short_convergence"][idx]
            if sc < 2.0:
                score += 20
                dimensions["均线形态"] = 20
                details.append("短期均线粘合")
            else:
                score += 10
                dimensions["均线形态"] = 10
                details.append("均线未完全粘合")
        else:
            # 多头排列检查
            ma5 = ind["ma5"][idx]
            ma13 = ind["ma13"][idx]
            ma60 = ind["ma60"][idx]
            if ma5 > ma13 > ma60:
                score += 20
                dimensions["均线形态"] = 20
                details.append("均线多头排列")
            elif ma5 > ma60:
                score += 10
                dimensions["均线形态"] = 10
                details.append("短期均线在中期均线上方")
            else:
                dimensions["均线形态"] = 0
                details.append("均线形态偏弱")

        # 大盘配合（20分）
        if market_trend == "up":
            score += 20
            dimensions["大盘配合"] = 20
            details.append("大盘上升趋势")
        elif market_trend == "neutral":
            score += 10
            dimensions["大盘配合"] = 10
            details.append("大盘震荡")
        else:
            dimensions["大盘配合"] = 0
            details.append("大盘下降趋势")

        # MACD（20分）
        dif = ind["dif"][idx]
        dea = ind["dea"][idx]
        hist = ind["macd_hist"][idx]
        if hist > 0 and dif > dea:
            if hist > 0 and idx > 0 and ind["macd_hist"][idx - 1] <= 0:
                score += 20
                dimensions["MACD"] = 20
                details.append("MACD金叉/柱转正")
            elif dif > dea:
                score += 10
                dimensions["MACD"] = 10
                details.append("MACD DIF>DEA")
        else:
            dimensions["MACD"] = 0
            details.append("MACD偏弱")

        # ΔG 加分
        bonus = 0
        if dg_info and dg_info.get("available"):
            q = dg_info.get("quadrant", "")
            if q == "double_click":
                bonus = 10
                score = min(100, score + bonus)
                details.append(f"ΔG 戴维斯双击")
            elif q == "reversal":
                details.append(f"ΔG 困境反转")
            elif q == "peaking":
                bonus = -10
                score = max(0, score + bonus)
                details.append(f"ΔG 景气见顶(减分)")
            elif q == "double_kill":
                bonus = -30
                score = max(0, score + bonus)
                details.append(f"ΔG 戴维斯双杀(大减分)")

        final_score = min(100, score)

        # 评分维度校验
        validation = _validate_score_dimensions(
            dimensions, final_score, bonus=bonus, service_name="three_buys_three_sells"
        )

        return final_score, details, validation

    # ===== 扫描 =====

    async def scan_three_buys_three_sells(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """三买三卖策略扫描"""
        import time
        start_time = time.time()

        logger.info(f"📊 三买三卖策略扫描开始，参数: {params}")

        stock_list = await self._get_all_stock_codes()
        total_scanned = len(stock_list)
        logger.info(f"📊 待扫描股票数量: {total_scanned}")

        if total_scanned == 0:
            return {"total": 0, "items": [], "took_ms": 0, "scanned_count": 0, "params": params}

        end_date = datetime.now()
        start_date = end_date - timedelta(days=150)
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        codes = [s["code"] for s in stock_list]
        stock_info = {s["code"]: s for s in stock_list}

        quotes_by_stock = await self._batch_get_quotes(codes, start_str, end_str)

        # ΔG 批量查询
        dg_data = {}
        if params.get("enable_dg_filter", True):
            try:
                dg_svc = await self._get_dg_service()
                dg_data = await dg_svc.get_quadrant_batch(codes)
            except Exception as e:
                logger.warning(f"📊 ΔG 查询失败: {e}")

        # 大盘趋势（用上证指数代码 000001）
        market_trend = "neutral"
        idx_quotes = quotes_by_stock.get("000001", [])
        if len(idx_quotes) > 60:
            idx_ind = self._precompute_indicators(idx_quotes, "000001", "上证指数", "", 0)
            if idx_ind:
                last = idx_ind["n"] - 1
                market_trend = calc_market_trend(
                    idx_ind["closes"], idx_ind["ma60"], idx_ind["ma20"]
                )

        results = []
        semaphore = asyncio.Semaphore(200)

        async def analyze_one(code: str):
            async with semaphore:
                info = stock_info.get(code, {})
                name = info.get("name", "")
                industry = info.get("industry", "")
                market_cap = info.get("market_cap", 0)

                kline = quotes_by_stock.get(code, [])
                if len(kline) < 70:
                    return None

                ind = self._precompute_indicators(kline, code, name, industry, market_cap)
                if ind is None:
                    return None

                last_idx = ind["n"] - 1
                if last_idx < 60:
                    return None

                # 检测所有信号
                signals = []
                # GMMA强多状态过滤：B2/B3/B2G需要强多状态确认，B1是左侧抄底不需要
                enable_gmma = params.get("enable_gmma_filter", True)
                gmma_strong_bull = bool(ind["gmma_strong_bull"][last_idx])

                # 过热过滤：过热状态下不新建仓
                overheated = self._check_overheat(ind, last_idx, params)

                # 个股趋势 + 大盘仓位矩阵
                stock_trend = str(ind["stock_trend"][last_idx])

                # B2/B3是突破信号，不打仓位折扣；B1按大盘趋势调节
                b1_multiplier = self._get_b1_position_multiplier(market_trend, stock_trend, params)

                # 将大盘趋势写入params供B1检查
                local_params = dict(params)
                local_params["_market_trend"] = market_trend

                b1 = self._check_b1(ind, last_idx, local_params)
                if b1:
                    b1["position_pct"] = round(b1["position_pct"] * b1_multiplier, 4)
                    signals.append(b1)
                # B2/B3/B2G 在启用GMMA过滤时需要强多状态，且不能过热
                if not enable_gmma or gmma_strong_bull:
                    if not overheated:
                        b2 = self._check_b2(ind, last_idx, local_params)
                        if b2:
                            signals.append(b2)
                        b3 = self._check_b3(ind, last_idx, local_params)
                        if b3:
                            signals.append(b3)
                        # GMMA版B2（加仓信号）
                        b2g = self._check_gmma_b2(ind, last_idx, local_params)
                        if b2g:
                            signals.append(b2g)

                s1 = self._check_s1(ind, last_idx, params)
                if s1:
                    signals.append(s1)
                s2 = self._check_s2(ind, last_idx, params)
                if s2:
                    signals.append(s2)
                s3 = self._check_s3(ind, last_idx)
                if s3:
                    signals.append(s3)
                safetynet = self._check_safety_net(ind, last_idx, params)
                if safetynet:
                    signals.append(safetynet)

                bottom = self._check_bottom_pickup(ind, last_idx)
                macd_div = self._check_macd_divergence(ind, last_idx)
                vp_div = self._check_volume_price_divergence(ind, last_idx)

                # 至少有一个买卖信号才返回
                if not signals and not bottom and not macd_div and not vp_div:
                    return None

                dg_info = dg_data.get(code)

                # 计算主要买入信号评分
                primary_signal = None
                score = 0
                score_details = []
                for sig in signals:
                    if sig["type"] in ("B1", "B2", "B3", "B2G"):
                        score, score_details, _ = self._calc_signal_score(
                            ind, last_idx, sig["type"], market_trend, dg_info
                        )
                        primary_signal = sig
                        break

                if primary_signal is None and signals:
                    primary_signal = signals[0]

                if params.get("min_score", 5) > 0 and score < params.get("min_score", 5):
                    if primary_signal and primary_signal["type"] in ("B1", "B2", "B3", "B2G"):
                        return None

                close = ind["closes"][last_idx]
                bias60 = ind["bias60"][last_idx]
                ma60_val = ind["ma60"][last_idx]
                ma60_slope = ind["ma60_slope"][last_idx]

                ma60_dir = "上升" if ma60_slope > 0.5 else ("下降" if ma60_slope < -0.5 else "走平")

                s1_threshold = ind.get("s1_threshold", 30.0)
                stop_price = ma60_val * 0.95

                item = {
                    "code": code,
                    "name": name,
                    "industry": industry,
                    "market_cap": round(market_cap, 1),
                    "close": round(float(close), 2),
                    "pct_chg": round(float(ind["pct_chgs"][last_idx]), 2),
                    "bias60": round(float(bias60), 2),
                    "ma60": round(float(ma60_val), 2),
                    "ma60_direction": ma60_dir,
                    "ma60_slope": round(float(ma60_slope), 2),
                    "stock_type": ind.get("stock_type", "normal"),
                    "stock_type_label": {"normal": "普通股", "tech_leader": "科技龙头", "leader": "龙头股", "st": "ST股票"}.get(ind.get("stock_type", "normal"), "普通股"),
                    "signals": signals,
                    "primary_signal_type": primary_signal["type"] if primary_signal else "",
                    "primary_signal_label": primary_signal["type_label"] if primary_signal else "",
                    "bottom_pickup": bottom,
                    "macd_divergence": macd_div,
                    "volume_price_divergence": vp_div,
                    "score": score,
                    "score_details": score_details,
                    "s1_threshold": s1_threshold,
                    "stop_price": round(float(stop_price), 2),
                    "volume_ratio": round(float(ind["volume_ratio"][last_idx]), 2),
                    "atr14": round(float(ind["atr14"][last_idx]), 2),
                    "dif": round(float(ind["dif"][last_idx]), 4),
                    "dea": round(float(ind["dea"][last_idx]), 4),
                    "macd_hist": round(float(ind["macd_hist"][last_idx]), 4),
                    "dg_quadrant": dg_info.get("quadrant_label", "数据不足") if dg_info else "数据不足",
                    "dg_available": dg_info.get("available", False) if dg_info else False,
                    "dg_g": dg_info.get("g") if dg_info else None,
                    "dg_dg": dg_info.get("dg") if dg_info else None,
                    "market_trend": market_trend,
                    "trigger_date": ind["dates"][last_idx]
                }
                return item

        tasks = [analyze_one(code) for code in codes]
        batch_size = 500
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch)
            for r in batch_results:
                if r is not None:
                    results.append(r)
            logger.info(f"📊 扫描进度: {min(i + batch_size, len(tasks))}/{len(tasks)}, 已找到 {len(results)} 只")

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        limit = params.get("limit", 50)
        results = results[:limit]

        results = [_to_native(r) for r in results]

        took_ms = int((time.time() - start_time) * 1000)

        return {
            "total": len(results),
            "items": results,
            "took_ms": took_ms,
            "scanned_count": total_scanned,
            "params": params,
            "market_trend": market_trend
        }

    # ===== 卖点判断（回测用） =====

    def _determine_sell_point(
        self,
        ind: Dict[str, Any],
        buy_idx: int,
        buy_price: float,
        max_hold_days: int,
        params: Dict[str, Any]
    ) -> Tuple[int, float, str]:
        """确定卖点（从买入日后开始找第一个卖出信号）

        Returns:
            (sell_idx, sell_price, sell_reason)
        """
        n = ind["n"]
        end_idx = min(buy_idx + max_hold_days, n - 1)

        # 跟踪状态
        position_pct = 1.0  # 初始满仓
        highest_price = buy_price

        for i in range(buy_idx + 1, end_idx + 1):
            close = ind["closes"][i]
            highest_price = max(highest_price, close)

            # 优先级: S3 > 安全网 > S2 > S1
            s3 = self._check_s3(ind, i)
            if s3 and position_pct > 0:
                return i, close, "S3清仓"

            sn = self._check_safety_net(ind, i, params)
            if sn and position_pct > 0.5:
                return i, close, "安全网触发"

            s2 = self._check_s2(ind, i, params)
            if s2 and position_pct > 0.34:
                return i, close, "S2主减仓"

            s1 = self._check_s1(ind, i, params)
            if s1 and position_pct > 0.67:
                # 部分止盈不立即全部卖出，回测简化为：S1 后继续持有等 S2/S3
                # 但为了回测准确性，我们继续跟踪
                pass

            # 额外：买入价下方 1.5 倍 ATR 止损（硬止损）
            atr = ind["atr14"][i]
            stop_price = buy_price - atr * 1.5
            if close < stop_price:
                return i, close, "ATR止损"

        # 到期卖出
        return end_idx, ind["closes"][end_idx], "到期卖出"

    # ===== 回测 =====

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """三买三卖策略回测"""
        import time
        start_time = time.time()

        if params is None:
            params = {}

        # 精简参数：只暴露5个核心参数，其余内部固定
        default_params = {
            "start_date": None,
            "end_date": None,
            "hold_days": 60,
            "top_n": 10,
            "initial_capital": 1000000,
            "min_score": 5,
            "max_position_pct": 0.15,
            # 以下为内部固定参数，不再暴露给用户
            "bias_b1_min": -35.0,
            "bias_b1_max": -15.0,
            "breakout_volume_ratio": 1.5,
            "zhongyang_threshold": 0.05,
            "pullback_bias_range": 5.0,
            "s1_threshold_normal": 30.0,
            "s2_break_days": 2,
            "enable_dg_filter": True,
            "enable_safety_net": False,  # 安全网与ATR止损重复，关闭
            "enable_slow_group_s1": True,
            "enable_gmma_filter": True,
            "enable_overheat_filter": True,
            "enable_market_matrix": False,  # 四象限矩阵过于复杂，关闭
            "enable_adaptive_volume": True,
            "enable_strict_b1": False,  # B1确认条件过于严格，关闭
            "gmma_s1_min_duration": 10,
            "gmma_b2_min_duration": 5,
            "gmma_b2_max_duration": 25,
            "overheat_separation_pct": 15.0,
            "overheat_bias_pct": 40.0,
            "slippage_pct": 0.003,
            "enable_b2b3_stop_loss": True,
            "b2b3_stop_loss_pct": -10.0,
            "trailing_stop_min_profit": 8.0,
            "trailing_stop_atr_mult": 2.5,
            "max_holdings": 30
        }
        default_params.update(params)
        params = default_params

        hold_days = params["hold_days"]
        top_n = params["top_n"]
        initial_capital = params["initial_capital"]
        max_pos_pct = params["max_position_pct"]

        logger.info(f"📊 三买三卖策略回测开始，参数: {params}")

        db = await self._get_db()

        stock_list = await self._get_all_stock_codes()
        total_scanned = len(stock_list)
        stock_info_map = {s["code"]: s for s in stock_list}
        stock_codes = list(stock_info_map.keys())
        logger.info(f"📊 待回测股票数量: {total_scanned}")

        end_date = datetime.strptime(params["end_date"], "%Y-%m-%d") if params.get("end_date") else datetime.now()
        start_date = datetime.strptime(params["start_date"], "%Y-%m-%d") if params.get("start_date") else end_date - timedelta(days=180)
        data_start = start_date - timedelta(days=150)
        data_end = end_date + timedelta(days=hold_days + 10)

        quotes_by_stock = await self._batch_get_quotes(
            stock_codes,
            data_start.strftime('%Y-%m-%d'),
            data_end.strftime('%Y-%m-%d')
        )

        all_trade_dates = set()
        for code, klines in quotes_by_stock.items():
            for k in klines:
                all_trade_dates.add(k["trade_date"])
        trade_dates = sorted(list(all_trade_dates))

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        backtest_dates = [d for d in trade_dates if start_str <= d <= end_str]
        logger.info(f"📊 回测交易日数量: {len(backtest_dates)}")

        # 计算大盘环境
        logger.info("📊 计算市场环境指标...")
        market_rise_ratio: Dict[str, float] = {}
        market_trend_map: Dict[str, str] = {}

        idx_klines = quotes_by_stock.get("000001", [])
        idx_ind = None
        if idx_klines:
            idx_ind = self._precompute_indicators(idx_klines, "000001", "上证指数", "", 0)

        for td in backtest_dates:
            rise_count = 0
            total_count = 0
            for code in stock_codes:
                kline_list = quotes_by_stock.get(code, [])
                for k in kline_list:
                    if k["trade_date"] == td and k.get("pct_chg") is not None:
                        total_count += 1
                        if k["pct_chg"] > 0:
                            rise_count += 1
                        break
            if total_count > 0:
                market_rise_ratio[td] = rise_count / total_count
            else:
                market_rise_ratio[td] = 0.5

            if idx_ind:
                idx_i = idx_ind["date_to_idx"].get(td, -1)
                if idx_i >= 60:
                    trend = calc_market_trend(
                        idx_ind["closes"][:idx_i + 1] if idx_i + 1 <= idx_ind["n"] else idx_ind["closes"],
                        idx_ind["ma60"][:idx_i + 1] if idx_i + 1 <= idx_ind["n"] else idx_ind["ma60"],
                        idx_ind["ma20"][:idx_i + 1] if idx_i + 1 <= idx_ind["n"] else idx_ind["ma20"]
                    )
                    market_trend_map[td] = trend
                else:
                    market_trend_map[td] = "neutral"
            else:
                market_trend_map[td] = "neutral"

        logger.info(f"📊 市场环境计算完成")

        # 预计算所有股票指标
        logger.info("📊 预计算指标...")
        indicators_cache: Dict[str, Any] = {}
        processed = 0
        for code in stock_codes:
            kline = quotes_by_stock.get(code, [])
            if len(kline) < 70:
                continue
            info = stock_info_map.get(code, {})
            ind = self._precompute_indicators(
                kline, code, info.get("name", ""),
                info.get("industry", ""), info.get("market_cap", 0)
            )
            if ind:
                indicators_cache[code] = ind
                processed += 1
        logger.info(f"📊 预计算完成: {processed} 只股票")

        # ΔG 数据
        dg_data = {}
        if params.get("enable_dg_filter", True):
            try:
                dg_svc = await self._get_dg_service()
                dg_data = await dg_svc.get_quadrant_batch(stock_codes)
            except Exception as e:
                logger.warning(f"📊 ΔG 查询失败: {e}")

        # 收集每日信号
        logger.info("📊 收集每日信号...")
        daily_signals: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for code, ind in indicators_cache.items():
            date_to_idx = ind["date_to_idx"]
            info = stock_info_map.get(code, {})
            dg_info = dg_data.get(code)

            for td in backtest_dates:
                idx = date_to_idx.get(td, -1)
                if idx < 60:
                    continue

                # GMMA强多状态过滤（使用预计算数组）
                enable_gmma = params.get("enable_gmma_filter", True)
                gmma_strong_bull = bool(ind["gmma_strong_bull"][idx])

                # 过热过滤
                overheated = self._check_overheat(ind, idx, params)

                # 个股趋势 + 大盘仓位矩阵（使用预计算数组）
                stock_trend = str(ind["stock_trend"][idx])
                market_trend = market_trend_map.get(td, "neutral")

                # B2/B3是突破信号，本身就是强趋势确认，下降市中数量自然减少，不打仓位折扣
                # B1是左侧抄底，根据大盘趋势调节仓位
                b1_multiplier = self._get_b1_position_multiplier(market_trend, stock_trend, params)
                b2_multiplier = 1.0  # 趋势突破信号不打折扣
                b3_multiplier = 1.0
                b2g_multiplier = 1.0

                # 将大盘趋势写入params供B1检查使用
                local_params = dict(params)
                local_params["_market_trend"] = market_trend

                check_fns_m = [
                    (lambda: self._check_b1(ind, idx, local_params), "B1")
                ]

                b2g_included = False
                if not enable_gmma or gmma_strong_bull:
                    if not overheated:
                        check_fns_m.append((lambda: self._check_b2(ind, idx, local_params), "B2"))
                        check_fns_m.append((lambda: self._check_b3(ind, idx, local_params), "B3"))
                        check_fns_m.append((lambda: self._check_gmma_b2(ind, idx, local_params), "B2G"))
                        b2g_included = True

                for check_fn, sig_type_hint in check_fns_m:
                    sig = check_fn()
                    if sig:
                        sig_type = sig["type"]
                        score, details, score_validation = self._calc_signal_score(
                            ind, idx, sig_type, market_trend, dg_info
                        )
                        if score >= params["min_score"]:
                            # 按信号类型应用仓位系数
                            if sig_type == "B1":
                                adj_pos_pct = sig.get("position_pct", 0.33) * b1_multiplier
                            elif sig_type == "B2":
                                adj_pos_pct = sig.get("position_pct", 0.67) * b2_multiplier
                            elif sig_type == "B3":
                                adj_pos_pct = sig.get("position_pct", 1.0) * b3_multiplier
                            else:  # B2G
                                adj_pos_pct = sig.get("position_pct", 0.8) * b2g_multiplier
                            daily_signals[td].append({
                                "code": code,
                                "name": info.get("name", ""),
                                "signal_type": sig_type,
                                "signal_label": sig["type_label"],
                                "price": ind["closes"][idx],
                                "score": score,
                                "score_details": details,
                                "score_validation": score_validation,
                                "position_pct": adj_pos_pct,
                                "idx": idx,
                                "ind": ind
                            })
                        break

        # 模拟交易
        logger.info("📊 模拟交易...")
        capital = initial_capital
        positions: Dict[str, Dict[str, Any]] = {}
        all_trades: List[Dict[str, Any]] = []
        daily_results: List[Dict[str, Any]] = []
        capital_history: List[float] = []
        peak_capital = initial_capital
        max_drawdown = 0.0

        for di, td in enumerate(backtest_dates):
            # 先处理卖出 - 逐日检查卖出信号（支持S1分批止盈 + ATR移动止损）
            codes_to_sell = []
            for code, pos in positions.items():
                ind = pos["ind"]
                buy_idx = pos["buy_idx"]
                idx = ind["date_to_idx"].get(td, -1)
                if idx < 0 or idx <= buy_idx:
                    continue

                close = ind["closes"][idx]
                high = ind["highs"][idx] if idx >= 0 and idx < ind["n"] else close
                pos["highest_price"] = max(pos["highest_price"], high)

                # 优先级1: S3 清仓（无条件全部卖出）
                s3 = self._check_s3(ind, idx)
                if s3:
                    proceeds = pos["remaining_shares"] * close * 0.999
                    capital += proceeds
                    total_proceeds = pos["cumulative_proceeds"] + proceeds
                    return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                    avg_sell = total_proceeds / pos["total_shares"] / 0.999
                    all_trades.append({
                        "code": code, "name": pos["name"],
                        "buy_date": pos["buy_date"], "sell_date": td,
                        "buy_price": round(pos["buy_price"], 2),
                        "sell_price": round(avg_sell, 2),
                        "return_pct": round(return_pct, 2),
                        "score": pos["score"], "signal_type": pos["signal_type"],
                        "sell_reason": "S3清仓", "shares": pos["total_shares"],
                        "profit": round(total_proceeds - pos["cost"], 2)
                    })
                    codes_to_sell.append(code)
                    continue

                # 优先级2: 安全网 - 减仓至50%
                sn = self._check_safety_net(ind, idx, params)
                if sn and pos["remaining_pct"] > 0.5:
                    sell_ratio = (pos["remaining_pct"] - 0.5) / pos["remaining_pct"]
                    sell_shares = int(pos["remaining_shares"] * sell_ratio / 100) * 100
                    if sell_shares >= 100:
                        proceeds = sell_shares * close * 0.999
                        capital += proceeds
                        pos["remaining_shares"] -= sell_shares
                        pos["cumulative_proceeds"] += proceeds
                        pos["remaining_pct"] = 0.5
                    continue

                # 优先级2.5: B1初始止损（BIAS继续扩大到-35%以下止损）
                if pos.get("signal_type") == "B1":
                    bias = ind["bias60"][idx]
                    if bias < -35.0:
                        proceeds = pos["remaining_shares"] * close * 0.999
                        capital += proceeds
                        total_proceeds = pos["cumulative_proceeds"] + proceeds
                        return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                        avg_sell = total_proceeds / pos["total_shares"] / 0.999
                        all_trades.append({
                            "code": code, "name": pos["name"],
                            "buy_date": pos["buy_date"], "sell_date": td,
                            "buy_price": round(pos["buy_price"], 2),
                            "sell_price": round(avg_sell, 2),
                            "return_pct": round(return_pct, 2),
                            "score": pos["score"], "signal_type": pos["signal_type"],
                            "sell_reason": "B1止损", "shares": pos["total_shares"],
                            "profit": round(total_proceeds - pos["cost"], 2)
                        })
                        codes_to_sell.append(code)
                        continue

                # 优先级2.6: B2/B3初始止损（亏损超过阈值强制止损）
                if params.get("enable_b2b3_stop_loss", True) and pos.get("signal_type") in ("B2", "B3", "B2G"):
                    cost_basis = pos["buy_price"]
                    if cost_basis > 0 and (close - cost_basis) / cost_basis * 100 <= params.get("b2b3_stop_loss_pct", -10.0):
                        proceeds = pos["remaining_shares"] * close * 0.999
                        capital += proceeds
                        total_proceeds = pos["cumulative_proceeds"] + proceeds
                        return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                        avg_sell = total_proceeds / pos["total_shares"] / 0.999
                        all_trades.append({
                            "code": code, "name": pos["name"],
                            "buy_date": pos["buy_date"], "sell_date": td,
                            "buy_price": round(pos["buy_price"], 2),
                            "sell_price": round(avg_sell, 2),
                            "return_pct": round(return_pct, 2),
                            "score": pos["score"], "signal_type": pos["signal_type"],
                            "sell_reason": "初始止损", "shares": pos["total_shares"],
                            "profit": round(total_proceeds - pos["cost"], 2)
                        })
                        codes_to_sell.append(code)
                        continue

                # 优先级3: ATR移动止损（盈利8%以上才启动，锁定利润）
                ts = self._check_trailing_stop(ind, idx, pos["highest_price"], pos["buy_price"])
                if ts:
                    proceeds = pos["remaining_shares"] * close * 0.999
                    capital += proceeds
                    total_proceeds = pos["cumulative_proceeds"] + proceeds
                    return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                    avg_sell = total_proceeds / pos["total_shares"] / 0.999
                    all_trades.append({
                        "code": code, "name": pos["name"],
                        "buy_date": pos["buy_date"], "sell_date": td,
                        "buy_price": round(pos["buy_price"], 2),
                        "sell_price": round(avg_sell, 2),
                        "return_pct": round(return_pct, 2),
                        "score": pos["score"], "signal_type": pos["signal_type"],
                        "sell_reason": "移动止损", "shares": pos["total_shares"],
                        "profit": round(total_proceeds - pos["cost"], 2)
                    })
                    codes_to_sell.append(code)
                    continue

                # 优先级4: S2 主减仓 - 减至1/3
                s2 = self._check_s2(ind, idx, params)
                if s2 and pos["remaining_pct"] > 0.34:
                    sell_ratio = (pos["remaining_pct"] - 0.33) / pos["remaining_pct"]
                    sell_shares = int(pos["remaining_shares"] * sell_ratio / 100) * 100
                    if sell_shares >= 100:
                        proceeds = sell_shares * close * 0.999
                        capital += proceeds
                        pos["remaining_shares"] -= sell_shares
                        pos["cumulative_proceeds"] += proceeds
                        pos["remaining_pct"] = 0.33
                    continue

                # 优先级5: S1 减仓预警 - 卖出1/3（仅触发一次，锁定利润）
                s1 = self._check_s1(ind, idx, params)
                if s1 and not pos.get("s1_triggered", False) and pos["remaining_pct"] > 0.67:
                    sell_shares = int(pos["remaining_shares"] / 3 / 100) * 100
                    if sell_shares >= 100:
                        proceeds = sell_shares * close * 0.999
                        capital += proceeds
                        pos["remaining_shares"] -= sell_shares
                        pos["cumulative_proceeds"] += proceeds
                        pos["remaining_pct"] = 0.67
                        pos["s1_triggered"] = True
                    continue

                # 优先级6: 到期卖出
                if idx - buy_idx >= hold_days:
                    proceeds = pos["remaining_shares"] * close * 0.999
                    capital += proceeds
                    total_proceeds = pos["cumulative_proceeds"] + proceeds
                    return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                    avg_sell = total_proceeds / pos["total_shares"] / 0.999
                    all_trades.append({
                        "code": code, "name": pos["name"],
                        "buy_date": pos["buy_date"], "sell_date": td,
                        "buy_price": round(pos["buy_price"], 2),
                        "sell_price": round(avg_sell, 2),
                        "return_pct": round(return_pct, 2),
                        "score": pos["score"], "signal_type": pos["signal_type"],
                        "sell_reason": "到期卖出", "shares": pos["total_shares"],
                        "profit": round(total_proceeds - pos["cost"], 2)
                    })
                    codes_to_sell.append(code)
                    continue

            for code in codes_to_sell:
                del positions[code]

            # 再处理买入（T+1：今天出现的信号，明天开盘价买入）
            signals = daily_signals.get(td, [])
            signals.sort(key=lambda x: x["score"], reverse=True)

            # 先处理加仓信号（B2G，已有持仓的股票加仓）
            for sig in signals:
                code = sig["code"]
                if code not in positions:
                    continue
                if sig["signal_type"] != "B2G":
                    continue
                pos = positions[code]
                # 已有持仓且当前仓位<80%才加仓
                if pos["remaining_pct"] >= 0.95:
                    continue
                ind = sig["ind"]
                cur_idx = sig["idx"]
                next_idx = cur_idx + 1
                if next_idx >= ind["n"]:
                    continue
                buy_price = ind["opens"][next_idx]
                if buy_price <= 0:
                    continue
                # 买入滑点
                slippage = params.get("slippage_pct", 0.003)
                buy_price = buy_price * (1 + slippage)
                # 加仓量：把仓位加到满仓（从当前加到100%）
                target_pct = 1.0
                add_pct = target_pct - pos["remaining_pct"]
                if add_pct <= 0.05:
                    continue
                # 计算当前持仓价值
                current_value = pos["remaining_shares"] * buy_price
                total_target_value = current_value / pos["remaining_pct"] * target_pct
                add_amount = total_target_value - current_value
                add_amount = min(add_amount, capital * 0.95)
                add_shares = int(add_amount / buy_price / 100) * 100
                if add_shares < 100:
                    continue
                add_cost = add_shares * buy_price * 1.001
                if add_cost > capital * 0.95:
                    continue
                # 更新持仓
                pos["total_shares"] += add_shares
                pos["remaining_shares"] += add_shares
                pos["cost"] += add_cost
                pos["remaining_pct"] = 1.0
                capital -= add_cost

            # 再处理新建仓信号（B1/B2/B3，top_n 只新股）
            new_signals = [s for s in signals if s["code"] not in positions and s["signal_type"] in ("B1", "B2", "B3")]
            max_holdings = params.get("max_holdings", 30)
            available_slots = max(0, max_holdings - len(positions))
            new_signals = new_signals[:min(top_n, available_slots)]

            for sig in new_signals:
                code = sig["code"]
                if code in positions:
                    continue

                ind = sig["ind"]
                cur_idx = sig["idx"]
                next_idx = cur_idx + 1
                if next_idx >= ind["n"]:
                    continue

                buy_price = ind["opens"][next_idx]
                if buy_price <= 0:
                    continue
                # 买入滑点
                slippage = params.get("slippage_pct", 0.003)
                buy_price = buy_price * (1 + slippage)

                pos_size = min(max_pos_pct, 1.0 / max(1, len(positions) + top_n))
                # 乘以信号的仓位系数（大盘四象限矩阵调节）
                sig_pos_pct = sig.get("position_pct", 1.0)
                pos_size = pos_size * sig_pos_pct
                amount = capital * pos_size
                shares = int(amount / buy_price / 100) * 100
                if shares < 100:
                    continue

                cost = shares * buy_price * 1.001  # 买入手续费
                if cost > capital * 0.95:
                    continue

                positions[code] = {
                    "buy_price": buy_price,
                    "buy_date": ind["dates"][next_idx] if next_idx < ind["n"] else td,
                    "buy_idx": next_idx,
                    "total_shares": shares,
                    "remaining_shares": shares,
                    "cost": cost,
                    "cumulative_proceeds": 0.0,
                    "highest_price": buy_price,
                    "remaining_pct": 1.0,
                    "s1_triggered": False,
                    "score": sig["score"],
                    "signal_type": sig["signal_type"],
                    "name": sig["name"],
                    "ind": ind
                }
                capital -= cost

            # 计算当日总资产
            total_value = capital
            for code, pos in positions.items():
                ind = pos["ind"]
                idx = ind["date_to_idx"].get(td, -1)
                if idx < 0:
                    # 停牌：使用上次有效价格索引
                    idx = pos.get("last_valid_idx", pos["buy_idx"])
                else:
                    # 更新上次有效索引
                    pos["last_valid_idx"] = idx
                if idx >= 0 and idx < ind["n"]:
                    total_value += pos["remaining_shares"] * ind["closes"][idx]

            capital_history.append(total_value)
            peak_capital = max(peak_capital, total_value)
            dd = (peak_capital - total_value) / peak_capital * 100 if peak_capital > 0 else 0
            max_drawdown = max(max_drawdown, dd)

            # 计算当日总持仓市值
            total_position_value = total_value - capital
            position_pct = (total_position_value / total_value * 100) if total_value > 0 else 0

            daily_results.append({
                "date": td,
                "total_value": round(total_value, 2),
                "position_count": len(positions),
                "position_pct": round(position_pct, 2),
                "cash": round(capital, 2),
                "position_value": round(total_position_value, 2),
                "return_pct": round((total_value - initial_capital) / initial_capital * 100, 2),
                "drawdown": round(dd, 2)
            })

        # 清算剩余持仓
        final_value = capital
        last_date = backtest_dates[-1] if backtest_dates else ""
        for code, pos in positions.items():
            ind = pos["ind"]
            idx = ind["date_to_idx"].get(last_date, ind["n"] - 1)
            sell_price = ind["closes"][idx]
            proceeds = pos["remaining_shares"] * sell_price * 0.999
            final_value += proceeds
            total_proceeds = pos["cumulative_proceeds"] + proceeds
            return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
            avg_sell = total_proceeds / pos["total_shares"] / 0.999
            all_trades.append({
                "code": code,
                "name": pos["name"],
                "buy_date": pos["buy_date"],
                "sell_date": last_date,
                "buy_price": round(pos["buy_price"], 2),
                "sell_price": round(avg_sell, 2),
                "return_pct": round(return_pct, 2),
                "score": pos["score"],
                "signal_type": pos["signal_type"],
                "sell_reason": "回测期末",
                "shares": pos["total_shares"],
                "profit": round(total_proceeds - pos["cost"], 2)
            })

        # 统计
        total_trades = len(all_trades)
        if total_trades > 0:
            wins = [t for t in all_trades if t["return_pct"] > 0]
            losses = [t for t in all_trades if t["return_pct"] <= 0]
            win_rate = len(wins) / total_trades * 100
            avg_return = float(np.mean([t["return_pct"] for t in all_trades]))
            avg_win = float(np.mean([t["return_pct"] for t in wins])) if wins else 0
            avg_loss = float(np.mean([t["return_pct"] for t in losses])) if losses else 0
            profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            # 最大连续亏损
            max_consecutive_losses = 0
            current_streak = 0
            for t in all_trades:
                if t["return_pct"] <= 0:
                    current_streak += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_streak)
                else:
                    current_streak = 0
        else:
            win_rate = 0
            avg_return = 0
            avg_win = 0
            avg_loss = 0
            profit_loss_ratio = 0
            max_consecutive_losses = 0

        total_return = (final_value - initial_capital) / initial_capital * 100

        # 计算日收益率用于夏普比率
        daily_returns = []
        for i in range(1, len(capital_history)):
            if capital_history[i - 1] > 0:
                daily_returns.append((capital_history[i] - capital_history[i - 1]) / capital_history[i - 1])

        if daily_returns:
            avg_daily_return = float(np.mean(daily_returns))
            std_daily_return = float(np.std(daily_returns))
            # 年化夏普比率（假设252个交易日，无风险利率3%）
            risk_free_daily = 0.03 / 252
            sharpe_ratio = (avg_daily_return - risk_free_daily) / std_daily_return * np.sqrt(252) if std_daily_return > 0 else 0
        else:
            sharpe_ratio = 0

        # 卡玛比率 = 年化收益 / 最大回撤
        days_count = len(backtest_dates) if backtest_dates else 1
        annualized_return = (1 + total_return / 100) ** (252 / days_count) - 1 if days_count > 0 else 0
        calmar_ratio = annualized_return / (max_drawdown / 100) if max_drawdown > 0 else 0

        # 总手续费估算
        total_fees = 0.0
        for t in all_trades:
            # 买入手续费 0.1% + 卖出 0.1% + 买卖滑点
            cost = t["profit"] / (t["return_pct"] / 100) if t["return_pct"] != 0 else t["buy_price"] * t["shares"]
            total_fees += cost * 0.002  # 粗略估算买卖双边手续费

        # 按信号类型统计
        signal_stats: Dict[str, Dict[str, Any]] = {}
        for t in all_trades:
            st = t["signal_type"]
            if st not in signal_stats:
                signal_stats[st] = {"count": 0, "wins": 0, "total_return": 0.0, "returns": []}
            signal_stats[st]["count"] += 1
            if t["return_pct"] > 0:
                signal_stats[st]["wins"] += 1
            signal_stats[st]["returns"].append(t["return_pct"])

        signal_summary = {}
        for st, s in signal_stats.items():
            signal_summary[st] = {
                "count": s["count"],
                "win_rate": round(s["wins"] / s["count"] * 100, 2) if s["count"] > 0 else 0,
                "avg_return": round(float(np.mean(s["returns"])), 2) if s["returns"] else 0
            }

        # 按卖出原因统计
        sell_stats: Dict[str, Dict[str, Any]] = {}
        for t in all_trades:
            sr = t["sell_reason"]
            if sr not in sell_stats:
                sell_stats[sr] = {"count": 0, "wins": 0, "returns": []}
            sell_stats[sr]["count"] += 1
            if t["return_pct"] > 0:
                sell_stats[sr]["wins"] += 1
            sell_stats[sr]["returns"].append(t["return_pct"])

        sell_reason_summary = {}
        for sr, s in sell_stats.items():
            sell_reason_summary[sr] = {
                "count": s["count"],
                "win_rate": round(s["wins"] / s["count"] * 100, 2) if s["count"] > 0 else 0,
                "avg_return": round(float(np.mean(s["returns"])), 2) if s["returns"] else 0
            }

        took_ms = int((time.time() - start_time) * 1000)

        logger.info(f"✅ 回测完成: {total_trades} 笔交易, 胜率 {win_rate:.1f}%, 平均收益 {avg_return:.2f}%, 耗时 {took_ms}ms")

        result = {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "avg_return": round(avg_return, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "annualized_return": round(annualized_return * 100, 2),
            "max_consecutive_losses": max_consecutive_losses,
            "total_fees_est": round(total_fees, 2),
            "total_return": round(total_return, 2),
            "final_capital": round(final_value, 2),
            "initial_capital": initial_capital,
            "backtest_days": len(backtest_dates),
            "signal_stats": signal_summary,
            "sell_reason_stats": sell_reason_summary,
            "daily_results": daily_results[:50],
            "top_trades": sorted(all_trades, key=lambda x: x["return_pct"], reverse=True)[:20],
            "worst_trades": sorted(all_trades, key=lambda x: x["return_pct"])[:20],
            "params": params,
            "took_ms": took_ms
        }

        return _to_native(result)


_tbts_service = None


def get_three_buys_three_sells_service() -> ThreeBuysThreeSellsService:
    """获取三买三卖策略服务单例"""
    global _tbts_service
    if _tbts_service is None:
        _tbts_service = ThreeBuysThreeSellsService()
    return _tbts_service
