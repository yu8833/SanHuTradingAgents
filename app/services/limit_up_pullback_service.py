"""
涨停回调（龙回头/N字反包）选股策略服务

核心逻辑：
1. 筛选最近N天内出现过涨停的股票
2. 涨停后出现缩量回调（3-5天）
3. 回调期间出现地量+下影线（左侧买点）
4. 放量突破5日线（右侧确认买点）
5. 回调期间不破10日线（生命线）
"""

import asyncio
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


def _validate_limit_up_score(dimensions: Dict[str, float], actual_score: float,
                               service_name: str = "limit_up_pullback") -> Dict[str, Any]:
    """
    涨停回调评分维度校验。
    记录各维度得分，校验实际得分在[0,100]之间。
    """
    total_max = sum(dimensions.values())
    result = {
        "passed": True,
        "errors": [],
        "warnings": [],
        "dimensions": dimensions,
        "total_max": total_max,
        "actual_score": round(actual_score, 1),
    }
    # 涨停回调各维度满分可能超过100（突破5日线是额外加分项），只警告不报错
    if total_max > 100:
        result["warnings"].append(f"维度满分总和超过100: {total_max}，突破5日线为额外加分")
    if actual_score < 0 or actual_score > 100:
        result["passed"] = False
        result["errors"].append(f"实际得分越界: {actual_score:.1f} (应为0~100)")
    if not result["passed"]:
        logger.warning(f"[{service_name}] 评分校验失败: {result['errors']}")
    return result


class LimitUpPullbackService:
    """涨停回调选股策略服务"""

    def __init__(self):
        self.db = None

    async def _get_db(self):
        """延迟获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def _get_all_stock_codes(self) -> List[dict]:
        """获取所有A股股票代码列表"""
        db = await self._get_db()
        collection = db["stock_basic_info"]
        # 使用 category 字段筛选A股，或者用 sse/exchange 字段
        cursor = collection.find(
            {
                "$or": [
                    {"category": "stock_cn"},
                    {"sse": {"$in": ["上海证券交易所", "深圳证券交易所", "上交所", "深交所"]}},
                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                ]
            },
            projection={"_id": 0, "code": 1, "symbol": 1, "name": 1, "industry": 1}
        )
        stocks = await cursor.to_list(length=5000)
        result = []
        for s in stocks:
            code = s.get("code") or s.get("symbol")
            if code and len(str(code)) == 6 and str(code).isdigit():
                result.append({
                    "code": str(code).zfill(6),
                    "name": s.get("name", ""),
                    "industry": s.get("industry", "")
                })
        return result

    async def _get_daily_kline(self, stock_code: str, days: int = 60) -> List[Dict[str, Any]]:
        """获取股票日线数据
        
        Args:
            stock_code: 股票代码（6位数字）
            days: 获取天数
            
        Returns:
            按日期升序排列的K线数据列表
        """
        db = await self._get_db()
        stock_code = stock_code.zfill(6)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days * 2)
        start_date_str = start_date.strftime('%Y-%m-%d')

        collection = db["stock_daily_quotes"]
        cursor = collection.find(
            {
                "code": stock_code,
                "period": "daily",
                "trade_date": {"$gte": start_date_str}
            },
            projection={
                "_id": 0, 
                "code": 1, 
                "trade_date": 1, 
                "open": 1, 
                "close": 1, 
                "high": 1, 
                "low": 1, 
                "volume": 1,
                "amount": 1,
                "pct_chg": 1
            }
        ).sort("trade_date", 1)

        data = await cursor.to_list(length=days * 2)
        return data

    def _get_limit_up_threshold(self, stock_code: str, stock_name: str = "") -> float:
        """根据板块获取涨停阈值
        
        创业板(300/301)：20% → 阈值19.5%
        科创板(688)：20% → 阈值19.5%
        ST股票（名称含ST）：5% → 阈值4.8%
        北交所(8/4)：30% → 阈值29.5%
        普通主板：10% → 阈值9.5%
        """
        code = str(stock_code).zfill(6)
        name = stock_name or ""
        is_st = "ST" in name.upper() or "*ST" in name.upper()

        if code.startswith("300") or code.startswith("301"):
            return 19.5  # 创业板
        elif code.startswith("688"):
            return 19.5  # 科创板
        elif code.startswith("8") or code.startswith("4"):
            return 29.5  # 北交所
        elif is_st:
            return 4.8   # ST股
        else:
            return 9.5   # 普通主板

    def _is_limit_up(self, kline: Dict[str, Any], stock_code: str = "", stock_name: str = "", prev_close: float = None) -> bool:
        """判断是否为涨停（区分板块）"""
        threshold = self._get_limit_up_threshold(stock_code, stock_name)
        pct_chg = kline.get("pct_chg")
        if pct_chg is not None:
            return pct_chg >= threshold

        if prev_close and prev_close > 0:
            close = kline.get("close", 0)
            pct = (close - prev_close) / prev_close * 100
            return pct >= threshold

        return False

    def _calculate_ma(self, closes: List[float], period: int) -> List[Optional[float]]:
        """计算移动平均线"""
        mas = []
        for i in range(len(closes)):
            if i < period - 1:
                mas.append(None)
            else:
                mas.append(float(np.mean(closes[i - period + 1:i + 1])))
        return mas

    def _calculate_volume_ratio(self, volumes: List[float], idx: int, period: int = 5) -> float:
        """计算量比（当日成交量 / 前N日平均成交量）"""
        if idx < period or idx >= len(volumes):
            return 1.0
        
        current_vol = volumes[idx]
        avg_vol = np.mean(volumes[idx - period:idx])
        
        if avg_vol == 0:
            return 1.0
        
        return float(current_vol / avg_vol)

    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
        """计算标准14日ATR（Wilder's Average True Range）"""
        n = len(closes)
        atr = [0.0] * n
        
        if n < period:
            return atr
        
        tr = [0.0] * n
        for i in range(1, n):
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        
        atr[period - 1] = float(np.mean(tr[1:period]))
        alpha = 2 / (period + 1)
        for i in range(period, n):
            atr[i] = float(atr[i-1] * (1 - alpha) + tr[i] * alpha)
        
        return atr

    def _can_buy(self, buy_price: float, prev_close: float) -> bool:
        """判断当天是否可以买入（非涨停板）"""
        if buy_price <= 0 or prev_close <= 0:
            return True
        
        limit_up_price = round(prev_close * 1.1, 2)
        return buy_price < limit_up_price * 0.995

    def _can_sell(self, close: float, open: float, prev_close: float) -> bool:
        """判断当天是否可以卖出（非跌停板）"""
        if close <= 0 or prev_close <= 0:
            return True
        
        limit_down_price = round(prev_close * 0.9, 2)
        return close > limit_down_price * 1.005

    def _analyze_single_stock(
        self, 
        stock_code: str, 
        stock_name: str,
        kline_data: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """分析单只股票是否符合涨停回调策略
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            kline_data: K线数据（升序）
            params: 策略参数
            
        Returns:
            符合条件的股票详细信息，不符合返回None
        """
        if len(kline_data) < 20:
            return None

        def safe_float(v, default=0.0):
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        # 提取数据，过滤掉无效数据点
        valid_data = []
        for k in kline_data:
            open_val = safe_float(k.get("open"))
            close_val = safe_float(k.get("close"))
            high_val = safe_float(k.get("high"))
            low_val = safe_float(k.get("low"))
            vol_val = safe_float(k.get("volume"))
            if open_val > 0 and close_val > 0 and high_val > 0 and low_val > 0 and vol_val > 0:
                valid_data.append(k)

        if len(valid_data) < 20:
            return None

        dates = [k["trade_date"] for k in valid_data]
        opens = [safe_float(k["open"]) for k in valid_data]
        closes = [safe_float(k["close"]) for k in valid_data]
        highs = [safe_float(k["high"]) for k in valid_data]
        lows = [safe_float(k["low"]) for k in valid_data]
        volumes = [safe_float(k["volume"]) for k in valid_data]

        # 计算涨跌幅（如果数据中没有pct_chg，就用收盘价计算）
        pct_chgs = []
        for i in range(len(valid_data)):
            pct = valid_data[i].get("pct_chg")
            if pct is not None:
                pct_chgs.append(safe_float(pct))
            elif i > 0 and closes[i - 1] > 0:
                pct_chgs.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
            else:
                pct_chgs.append(0.0)

        # 计算均线
        ma5 = self._calculate_ma(closes, 5)
        ma10 = self._calculate_ma(closes, 10)
        ma20 = self._calculate_ma(closes, 20)

        # 参数
        max_lookback_days = params.get("max_lookback_days", 15)  # 最多往前找多少天的涨停
        min_pullback_days = params.get("min_pullback_days", 2)   # 最少回调天数
        max_pullback_days = params.get("max_pullback_days", 8)   # 最多回调天数
        shrink_volume_ratio = params.get("shrink_volume_ratio", 0.5)  # 缩量比例（回调期均量 / 涨停日量）
        min_shrink_days = params.get("min_shrink_days", 2)       # 最少缩量天数
        above_ma10 = params.get("above_ma10", True)             # 是否要求站上10日线
        ground_volume_ratio = params.get("ground_volume_ratio", 0.35)  # 地量比例
        lower_shadow_ratio = params.get("lower_shadow_ratio", 0.015)   # 下影线比例阈值
        breakout_ma5 = params.get("breakout_ma5", False)         # 是否要求突破5日线（右侧买点）
        breakout_volume_ratio = params.get("breakout_volume_ratio", 1.5)  # 突破放量倍数

        # 获取涨停阈值（区分板块）
        limit_up_threshold = self._get_limit_up_threshold(stock_code, stock_name)

        # 从最近开始往前找涨停日
        current_idx = len(closes) - 1
        limit_up_idx = None

        for i in range(current_idx, max(current_idx - max_lookback_days, 1), -1):
            if pct_chgs[i] >= limit_up_threshold:
                limit_up_idx = i
                break

        if limit_up_idx is None:
            return None

        # 涨停日到当前的天数
        days_since_limit_up = current_idx - limit_up_idx

        # 回调天数检查
        if days_since_limit_up < min_pullback_days or days_since_limit_up > max_pullback_days:
            return None

        # 涨停日数据
        limit_up_close = closes[limit_up_idx]
        limit_up_volume = volumes[limit_up_idx]
        limit_up_date = dates[limit_up_idx]

        # 回调期数据（涨停日次日到当前）
        pullback_indices = list(range(limit_up_idx + 1, current_idx + 1))
        if not pullback_indices:
            return None

        pullback_closes = [closes[i] for i in pullback_indices]
        pullback_volumes = [volumes[i] for i in pullback_indices]
        pullback_lows = [lows[i] for i in pullback_indices]
        pullback_pcts = [pct_chgs[i] for i in pullback_indices]

        # 计算回调幅度
        max_close_in_pullback = max(pullback_closes)
        min_close_in_pullback = min(pullback_closes)
        current_close = closes[current_idx]
        
        pullback_depth = (limit_up_close - min_close_in_pullback) / limit_up_close * 100

        # 缩量检查
        avg_pullback_volume = np.mean(pullback_volumes)
        volume_shrink_ratio = avg_pullback_volume / limit_up_volume if limit_up_volume > 0 else 1

        # 统计缩量天数
        shrink_days = sum(1 for v in pullback_volumes if v / limit_up_volume <= shrink_volume_ratio)

        if shrink_days < min_shrink_days:
            return None

        # 10日线检查（回调期间逐日检查，不只是当前日）
        # 战法要求：回调期间收盘价始终在10日线上方，盘中可小幅刺破但收盘收回
        ma10_broken_days = 0
        if above_ma10:
            for idx in pullback_indices:
                if ma10[idx] is not None:
                    if closes[idx] < ma10[idx]:
                        ma10_broken_days += 1
            # 允许1天收盘跌破（盘中洗盘），超过则不符合
            if ma10_broken_days > 1:
                return None

        # ========== 地量检查（增强版） ==========
        # 战法标准：①回调第3-5天出现地量 ②成交量≤涨停日1/3 ③或创近20个交易日最低量
        min_volume_idx_in_pullback = pullback_indices[np.argmin(pullback_volumes)]
        min_volume = volumes[min_volume_idx_in_pullback]
        ground_volume_ratio_val = min_volume / limit_up_volume if limit_up_volume > 0 else 1

        # 地量日位置：战法要求在第3-5天出现（ground_day_offset从1开始计数）
        ground_day_offset = min_volume_idx_in_pullback - limit_up_idx
        ground_volume_in_right_position = 3 <= ground_day_offset <= 5

        # 检查是否为近20日最低量
        vol_20_start = max(0, min_volume_idx_in_pullback - 20)
        vol_20_end = min_volume_idx_in_pullback
        if vol_20_end > vol_20_start:
            min_vol_20 = min(volumes[vol_20_start:vol_20_end + 1])
            is_20day_ground = min_volume <= min_vol_20
        else:
            is_20day_ground = False

        # 地量判定：满足涨停日1/3以下 且 近20日最低量（加强版：两个条件都满足）
        is_ground_volume = ground_volume_ratio_val <= 0.33 and is_20day_ground

        # ========== 下影线检查（修正版） ==========
        # 战法标准：下影线长度≥实体长度的1.5倍
        ground_day_open = opens[min_volume_idx_in_pullback]
        ground_day_close = closes[min_volume_idx_in_pullback]
        ground_day_low = lows[min_volume_idx_in_pullback]
        ground_day_high = highs[min_volume_idx_in_pullback]

        # 下影线长度 = min(open, close) - low
        lower_shadow = min(ground_day_open, ground_day_close) - ground_day_low
        lower_shadow_pct = lower_shadow / ground_day_low if ground_day_low > 0 else 0

        # 实体长度
        body_size = abs(ground_day_close - ground_day_open)
        # 下影线/实体 比值（战法标准：≥1.5倍；十字星body为0时视为满足）
        shadow_to_body_ratio = (lower_shadow / body_size) if body_size > 0 else (99.0 if lower_shadow > 0 else 0.0)

        # 下影线判定：实体比≥1.5 或 占最低价比≥阈值
        has_lower_shadow = shadow_to_body_ratio >= 2.0 or lower_shadow_pct >= lower_shadow_ratio

        # ========== 空间位置检查 ==========
        # 战法标准：①下影线最低价不跌破涨停板实体的一半 ②或精准回踩10日均线后弹起
        limit_up_open = opens[limit_up_idx]
        limit_up_entity_low = min(limit_up_open, limit_up_close)
        limit_up_entity_high = max(limit_up_open, limit_up_close)
        limit_up_entity_mid = (limit_up_entity_low + limit_up_entity_high) / 2
        # 条件①：地量日最低价在涨停板实体一半以上（允许2%误差）
        space_position_ok = ground_day_low >= limit_up_entity_mid * 0.98

        # 条件②：回踩10日均线后弹起（地量日最低价触及10日线±2%范围内，且收盘价在10日线上方）
        ma10_bounce_ok = False
        if ma10[min_volume_idx_in_pullback] is not None:
            ma10_val = ma10[min_volume_idx_in_pullback]
            ma10_distance = (ground_day_low - ma10_val) / ma10_val * 100
            # 最低价距离10日线在-2%到+1%范围内，且收盘在10日线上方
            if -2 <= ma10_distance <= 1 and ground_day_close >= ma10_val:
                ma10_bounce_ok = True
        # 空间位置满足条件①或②
        space_position_ok = space_position_ok or ma10_bounce_ok

        # ========== 次日阳线确认 ==========
        # 战法标准：地量+下影线之后，次日收阳线也可作为确认信号
        next_day_bullish = False
        if min_volume_idx_in_pullback + 1 <= current_idx:
            next_day_idx = min_volume_idx_in_pullback + 1
            next_day_close = closes[next_day_idx]
            next_day_open = opens[next_day_idx]
            # 次日收阳线（收盘>开盘）且收盘高于地量日收盘
            if next_day_close > next_day_open and next_day_close > ground_day_close:
                next_day_bullish = True

        # ========== 地量日其他指标 ==========
        # 地量日是第几天
        ground_day_offset = min_volume_idx_in_pullback - limit_up_idx

        # 地量日距今天数
        days_since_ground_day = current_idx - min_volume_idx_in_pullback

        # 地量日后的反弹幅度（当前价相对地量日最低价的涨幅）
        ground_day_low_price = lows[min_volume_idx_in_pullback]
        rebound_from_ground = (current_close - ground_day_low_price) / ground_day_low_price * 100 if ground_day_low_price > 0 else 0

        # 地量日是否收阴或十字星（实体很小）
        ground_day_body_pct = abs(ground_day_close - ground_day_open) / ground_day_open if ground_day_open > 0 else 0

        # ========== 突破5日线检查（增强版） ==========
        # 战法标准：①收盘站上5日线 ②5日线走平或上翘 ③放量≥1.5倍 ④无假突破
        ma5_breakout = False
        breakout_volume = 1.0
        fake_breakout = False

        if breakout_ma5 and ma5[current_idx] is not None and ma5[current_idx - 1] is not None:
            prev_close = closes[current_idx - 1]
            # 5日线方向判断（走平或上翘）：斜率≥0为走平或上翘
            ma5_slope = ma5[current_idx] - ma5[current_idx - 1]
            ma5_flat_or_up = ma5_slope >= 0

            # 放量检查
            avg_vol_5 = np.mean(volumes[max(0, current_idx - 5):current_idx])
            breakout_volume = volumes[current_idx] / avg_vol_5 if avg_vol_5 > 0 else 1

            # 假突破过滤：上影线过长（>2.5%）
            upper_shadow = highs[current_idx] - max(opens[current_idx], closes[current_idx])
            upper_shadow_pct = upper_shadow / closes[current_idx] if closes[current_idx] > 0 else 0
            if upper_shadow_pct >= 0.025:
                fake_breakout = True

            is_above_ma5 = current_close >= ma5[current_idx]
            
            # 加强过滤：收盘价必须在回调区间最高价之上
            pullback_high = max(highs[i] for i in pullback_indices) if pullback_indices else float('inf')
            is_above_pullback_high = current_close >= pullback_high * 0.99

            # 加强过滤：5日线必须上穿10日线
            ma5_above_ma10 = False
            if ma10[current_idx] is not None and ma5[current_idx] is not None:
                ma5_above_ma10 = ma5[current_idx] >= ma10[current_idx] * 0.995
            
            if is_above_ma5 and ma5_flat_or_up and breakout_volume >= breakout_volume_ratio and not fake_breakout and is_above_pullback_high and ma5_above_ma10:
                ma5_breakout = True

        # 连续小阴小阳（主力控盘迹象）
        small_body_days = 0
        for i in pullback_indices:
            body_pct = abs(closes[i] - opens[i]) / opens[i] if opens[i] > 0 else 0
            if body_pct < 0.02:
                small_body_days += 1
        small_body_ratio = small_body_days / len(pullback_indices) if pullback_indices else 0

        # ========== 综合评分（调整后） ==========
        score = 0.0
        score_details = []
        dimensions: Dict[str, float] = {}

        # 缩量评分（20分）
        shrink_score = max(0, 20 * (1 - volume_shrink_ratio))
        score += shrink_score
        dimensions["缩量"] = shrink_score
        score_details.append(f"缩量: {volume_shrink_ratio:.2%} → {shrink_score:.1f}分")

        # 回调幅度适中评分（15分）：回调5-15%最佳
        depth_score = 0.0
        if 3 <= pullback_depth <= 20:
            depth_score = 15 - abs(pullback_depth - 10) * 1.5
            depth_score = max(0, depth_score)
            score += depth_score
        dimensions["回调幅度"] = depth_score
        score_details.append(f"回调幅度: {pullback_depth:.1f}% → {depth_score:.1f}分")

        # 地量评分（15分）：满足涨停日比例或20日最低量
        if is_ground_volume:
            ground_score = 15.0
            if is_20day_ground and ground_volume_ratio_val > ground_volume_ratio:
                ground_score = 13.0  # 仅满足20日最低量，略低
        else:
            ground_score = max(0, 15 * (1 - (ground_volume_ratio_val - ground_volume_ratio) / 0.5))
        score += ground_score
        dimensions["地量"] = ground_score
        score_details.append(f"地量: {ground_volume_ratio_val:.2%} {'(20日最低)' if is_20day_ground else ''} → {ground_score:.1f}分")

        # 下影线评分（15分）：按实体比评分
        shadow_score = 0.0
        if has_lower_shadow:
            shadow_score = min(15, 8 + shadow_to_body_ratio * 2)
            score += shadow_score
        dimensions["下影线"] = shadow_score
        score_details.append(f"下影线: 实体比{shadow_to_body_ratio:.1f}倍 → {shadow_score:.1f}分")

        # 空间位置评分（10分）：地量日最低价在涨停板实体一半以上
        space_score = 0.0
        if space_position_ok:
            space_score = 10.0
            score += space_score
        dimensions["空间位置"] = space_score
        score_details.append(f"空间位置: 未破涨停实体一半 → {space_score:.1f}分")

        # 站上10日线评分（10分）
        above_score = 0.0
        if above_ma10 and ma10[current_idx] is not None and current_close >= ma10[current_idx]:
            above_score = 10.0
            score += above_score
        dimensions["站上10日线"] = above_score
        score_details.append(f"站上10日线 → {above_score:.1f}分")

        # 小阴小阳评分（5分）
        small_body_score = small_body_ratio * 5
        score += small_body_score
        dimensions["小阴小阳"] = small_body_score
        score_details.append(f"小阴小阳: {small_body_ratio:.0%} → {small_body_score:.1f}分")

        # 突破5日线加分（25分）：右侧确认是核心买点，权重提高
        breakout_score = 0.0
        if ma5_breakout:
            breakout_score = 25.0
            score += breakout_score
            score_details.append(f"突破5日线: 放量{breakout_volume:.1f}倍 → {breakout_score:.1f}分")
        elif fake_breakout:
            score_details.append(f"假突破过滤: 上影线过长，不确认右侧")
        dimensions["突破5日线"] = breakout_score

        # 评分维度校验
        score_validation = _validate_limit_up_score(dimensions, score)

        # 确定信号类型
        signal_type = "观察"
        # 地量信号确认：有下影线 + 满足地量标准 + （地量日在第3-5天 或 次日阳线确认）
        has_ground_signal = has_lower_shadow and is_ground_volume and ground_volume_in_right_position

        if ma5_breakout:
            signal_type = "右侧确认"
        elif has_ground_signal:
            if days_since_ground_day <= 2 and rebound_from_ground <= 3:
                signal_type = "左侧潜伏"
            elif days_since_ground_day <= 4 and rebound_from_ground <= 5:
                signal_type = "底部观察"
            else:
                signal_type = "观察"
        elif volume_shrink_ratio <= shrink_volume_ratio:
            signal_type = "缩量回调中"

        # 当前价距涨停价空间
        upside_space = (limit_up_close - current_close) / current_close * 100 if current_close > 0 else 0

        # ========== 各阶段日期计算 ==========
        # 缩量回调起止日期：涨停次日 → 当前日（或信号日）
        pullback_start_date = kline_data[limit_up_idx + 1]["trade_date"] if limit_up_idx + 1 < len(kline_data) else None
        pullback_end_date = dates[current_idx]  # 回调至今
        # 地量日日期
        ground_day_date = kline_data[min_volume_idx_in_pullback]["trade_date"] if is_ground_volume else None
        # 底部观察起始日：地量日（地量出现即进入观察期）
        bottom_watch_start_date = ground_day_date if is_ground_volume else None
        # 底部观察结束日：当前日（观察期持续到出现买点或当前）
        bottom_watch_end_date = dates[current_idx] if bottom_watch_start_date else None
        # 左侧潜伏买点日期：地量日当天或次日（满足左侧条件时）
        left_buy_date = None
        if has_ground_signal:
            left_buy_date = ground_day_date
        # 右侧确认买点日期：突破5日线当天
        right_buy_date = None
        if ma5_breakout:
            right_buy_date = dates[current_idx]  # 使用当前索引对应的日期

        return {
            "code": stock_code,
            "name": stock_name,
            "close": round(current_close, 2),
            "pct_chg": round(pct_chgs[current_idx], 2),
            "limit_up_date": limit_up_date,
            "days_since_limit_up": days_since_limit_up,
            "limit_up_close": round(limit_up_close, 2),
            "pullback_depth": round(pullback_depth, 2),
            "volume_shrink_ratio": round(volume_shrink_ratio, 4),
            "ground_volume_ratio": round(ground_volume_ratio_val, 4),
            "lower_shadow_pct": round(lower_shadow_pct, 4),
            "shadow_to_body_ratio": round(shadow_to_body_ratio, 2),
            "space_position_ok": space_position_ok,
            "is_20day_ground": is_20day_ground,
            "fake_breakout": fake_breakout,
            "signal_type": signal_type,
            "score": round(score, 1),
            "score_details": score_details,
            "score_validation": score_validation,
            "upside_space": round(upside_space, 2),
            "ma5": round(ma5[current_idx], 2) if ma5[current_idx] else None,
            "ma10": round(ma10[current_idx], 2) if ma10[current_idx] else None,
            "ma20": round(ma20[current_idx], 2) if ma20[current_idx] else None,
            "small_body_ratio": round(small_body_ratio, 4),
            "ground_day_offset": ground_day_offset,
            "days_since_ground_day": days_since_ground_day,
            "rebound_from_ground": round(rebound_from_ground, 2),
            "ground_day_body_pct": round(ground_day_body_pct, 4),
            "industry": kline_data[0].get("industry", "") if kline_data else "",
            # 各阶段日期
            "pullback_start_date": pullback_start_date,
            "pullback_end_date": pullback_end_date,
            "bottom_watch_start_date": bottom_watch_start_date,
            "bottom_watch_end_date": bottom_watch_end_date,
            "left_buy_date": left_buy_date,
            "right_buy_date": right_buy_date,
            "ground_day_date": ground_day_date
        }

    def _determine_sell_point(
        self,
        kline_data: List[Dict[str, Any]],
        buy_idx: int,
        limit_up_close: float,
        limit_up_idx: int,
        max_hold_days: int = 20,
        buy_price: float = 0.0
    ) -> tuple:
        """确定卖出时点（六条卖点规则）

        卖点1：ATR止损 → 动态止损，适应不同波动率（优先）
        卖点2：10日线止损 → 趋势破坏止损（备选）
        卖点3：时间止盈 → 涨停日后第8天未突破涨停价
        卖点4：高位止盈 → 放量滞涨
        卖点5：移动止盈 → 盈利后跌破5日线
        卖点6：ATR止盈 → 盈利后跌破最近高点下方1.5倍ATR

        Returns:
            (sell_idx, sell_reason)
        """
        if buy_idx >= len(kline_data) - 1:
            return buy_idx, "无法持有"

        def safe_float(v, default=0.0):
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        closes = [safe_float(k.get("close")) for k in kline_data]
        volumes = [safe_float(k.get("volume")) for k in kline_data]
        highs = [safe_float(k.get("high")) for k in kline_data]
        opens = [safe_float(k.get("open")) for k in kline_data]
        lows = [safe_float(k.get("low")) for k in kline_data]

        ma5 = self._calculate_ma(closes, 5)
        ma10 = self._calculate_ma(closes, 10)

        atr14 = self._calculate_atr(highs, lows, closes, period=14)

        max_high_since_limit_up = max(highs[limit_up_idx:buy_idx + 1]) if buy_idx > limit_up_idx else highs[limit_up_idx]
        has_exceeded_limit_up = max_high_since_limit_up >= limit_up_close

        trailing_stop_active = False
        trailing_stop_price = buy_price * 0.95

        for day_offset in range(1, min(max_hold_days + 1, len(kline_data) - buy_idx)):
            check_idx = buy_idx + day_offset
            if check_idx >= len(kline_data):
                break

            current_close = closes[check_idx]
            current_high = highs[check_idx]
            current_vol = volumes[check_idx]

            if current_high > max_high_since_limit_up:
                max_high_since_limit_up = current_high
            if current_high >= limit_up_close:
                has_exceeded_limit_up = True

            # 持续更新移动止盈价（盈利>3%开启）
            if buy_price > 0 and current_close > buy_price * 1.03:
                trailing_stop_active = True
                ma5_stop = ma5[check_idx] if ma5[check_idx] is not None else 0
                atr_trailing_stop = max_high_since_limit_up - 1.0 * atr14[check_idx] if atr14[check_idx] > 0 else 0
                new_stop_price = max(ma5_stop, atr_trailing_stop)
                if new_stop_price > trailing_stop_price:
                    trailing_stop_price = new_stop_price

            # 卖点1：ATR止损（优先）- 买入价下方0.4倍ATR
            if atr14[check_idx] > 0:
                atr_stop_price = buy_price - 0.4 * atr14[check_idx]
                if current_close < atr_stop_price:
                    return check_idx, "ATR止损"

            # 卖点2：10日线止损（兜底）- 收盘价跌破10日线98%
            if ma10[check_idx] is not None and current_close < ma10[check_idx] * 0.98:
                return check_idx, "10日止损"

            # 卖点3：时间止盈 - 第8天未突破涨停价
            days_since_limit_up = check_idx - limit_up_idx
            if days_since_limit_up == 8 and not has_exceeded_limit_up:
                return check_idx, "8日时间止盈"

            # 卖点4：高位止盈 - 放量滞涨
            if check_idx >= 5:
                avg_vol_5 = np.mean(volumes[max(0, check_idx - 5):check_idx])
                if avg_vol_5 > 0:
                    vol_ratio = current_vol / avg_vol_5
                    body_pct = abs(current_close - opens[check_idx]) / opens[check_idx] if opens[check_idx] > 0 else 0
                    upper_shadow = highs[check_idx] - max(opens[check_idx], current_close)
                    upper_shadow_pct = upper_shadow / opens[check_idx] if opens[check_idx] > 0 else 0
                    if vol_ratio >= 1.5 and (body_pct < 0.02 or upper_shadow_pct > 0.03):
                        return check_idx, "高位止盈"

            # 卖点5：移动止盈 - 跌破移动止盈价
            if trailing_stop_active and trailing_stop_price > 0:
                if current_close < trailing_stop_price:
                    if ma5[check_idx] is not None and current_close < ma5[check_idx]:
                        return check_idx, "5日线止盈"
                    else:
                        return check_idx, "ATR止盈"

        sell_idx = min(buy_idx + max_hold_days, len(kline_data) - 1)
        return sell_idx, "到期卖出"

    async def scan_limit_up_pullback(
        self,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """扫描符合涨停回调策略的股票
        【性能优化】使用批量数据查询，将数据库查询从5000+次减少到2次
        
        Args:
            params: 策略参数
                - max_lookback_days: 最多往前找多少天的涨停（默认15）
                - min_pullback_days: 最少回调天数（默认2）
                - max_pullback_days: 最多回调天数（默认8）
                - shrink_volume_ratio: 缩量比例阈值（默认0.5）
                - min_shrink_days: 最少缩量天数（默认2）
                - above_ma10: 是否要求站上10日线（默认True）
                - ground_volume_ratio: 地量比例阈值（默认0.35）
                - lower_shadow_ratio: 下影线比例阈值（默认0.015）
                - breakout_ma5: 是否要求突破5日线（默认False）
                - min_score: 最低评分阈值（默认40）
                - limit: 返回数量限制（默认50）
                
        Returns:
            扫描结果
        """
        import time
        from collections import defaultdict
        from datetime import datetime, timedelta
        start_time = time.time()

        if params is None:
            params = {}

        # 精简参数：只暴露4个核心参数，其余内部固定
        default_params = {
            "max_lookback_days": 15,
            "min_pullback_days": 2,
            "max_pullback_days": 8,
            "shrink_volume_ratio": 0.5,
            "min_shrink_days": 2,
            "above_ma10": True,
            "ground_volume_ratio": 0.35,
            "lower_shadow_ratio": 0.015,
            "breakout_ma5": True,
            "breakout_volume_ratio": 1.5,
            "min_score": 30,
            "limit": 50,
            "initial_capital": 1000000,
            "top_n": 10,
            "hold_days": 20
        }
        default_params.update(params)
        params = default_params

        logger.info(f"📊 涨停回调策略扫描开始，参数: {params}")

        db = await self._get_db()

        # ========== 第1次查询：获取所有A股股票代码和名称 ==========
        basic_collection = db["stock_basic_info"]
        basic_cursor = basic_collection.find(
            {
                "$or": [
                    {"category": "stock_cn"},
                    {"sse": {"$in": ["上海证券交易所", "深圳证券交易所", "上交所", "深交所"]}},
                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                ]
            },
            projection={"_id": 0, "code": 1, "symbol": 1, "name": 1, "industry": 1}
        )
        basic_stocks = await basic_cursor.to_list(length=10000)

        # 构建股票代码映射
        stock_info_map = {}
        for s in basic_stocks:
            code = s.get("code") or s.get("symbol")
            if code and len(str(code)) == 6 and str(code).isdigit():
                code = str(code).zfill(6)
                stock_info_map[code] = {
                    "name": s.get("name", ""),
                    "industry": s.get("industry", "")
                }

        stock_codes = list(stock_info_map.keys())
        total_scanned = len(stock_codes)
        logger.info(f"📊 待扫描股票数量: {total_scanned}")

        # ========== 第2次查询：一次性获取所有股票最近60天日线数据 ==========
        end_date = datetime.now()
        start_date = end_date - timedelta(days=120)
        start_date_str = start_date.strftime('%Y-%m-%d')

        quotes_collection = db["stock_daily_quotes"]
        quotes_cursor = quotes_collection.find(
            {
                "code": {"$in": stock_codes},
                "period": "daily",
                "trade_date": {"$gte": start_date_str}
            },
            projection={"_id": 0, "code": 1, "trade_date": 1, "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1, "amount": 1, "pct_chg": 1, "pre_close": 1, "data_source": 1}
        ).sort("trade_date", 1)

        all_quotes = await quotes_cursor.to_list(length=total_scanned * 300)

        # 按股票代码分组，并按日期去重
        # 数据源优先级: tushare > sina > baostock > akshare
        # 原因: tushare 数据最新，pct_chg 可以自己计算
        DATA_SOURCE_PRIORITY = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}
        quotes_by_stock = defaultdict(list)
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
                existing_priority = DATA_SOURCE_PRIORITY.get(existing_src, 0)
                new_priority = DATA_SOURCE_PRIORITY.get(new_src, 0)
                if new_priority > existing_priority:
                    quotes_by_date_by_stock[code][trade_date] = quote

        # 转换为列表格式并按日期排序
        for code, date_map in quotes_by_date_by_stock.items():
            sorted_quotes = sorted(date_map.values(), key=lambda x: x.get("trade_date", ""))
            quotes_by_stock[code] = sorted_quotes

        logger.info(f"📊 已获取 {len(all_quotes)} 条原始日线数据，去重后覆盖 {len(quotes_by_stock)} 只股票")

        # ========== 内存中计算每只股票的信号（零数据库查询） ==========
        semaphore = asyncio.Semaphore(200)
        results = []

        async def process_stock(code: str):
            async with semaphore:
                try:
                    kline_data = quotes_by_stock.get(code, [])
                    if len(kline_data) < 20:
                        return None

                    info = stock_info_map.get(code, {})
                    name = info.get("name", "")
                    industry = info.get("industry", "")

                    result = self._analyze_single_stock(code, name, kline_data, params)
                    if result and result["score"] >= params["min_score"]:
                        result["industry"] = industry
                        return result
                    return None
                except Exception as e:
                    logger.warning(f"分析股票 {code} 失败: {e}")
                    return None

        # 分批处理，避免任务过多
        batch_size = 1000
        for i in range(0, len(stock_codes), batch_size):
            batch_codes = stock_codes[i:i + batch_size]
            tasks = [process_stock(code) for code in batch_codes]
            batch_results = await asyncio.gather(*tasks)
            results.extend([r for r in batch_results if r is not None])
            logger.info(f"📊 扫描进度: {min(i + batch_size, len(stock_codes))}/{len(stock_codes)}, 已找到 {len(results)} 只符合条件的股票")

        # 按评分排序
        results.sort(key=lambda x: x["score"], reverse=True)

        # 限制返回数量
        results = results[:params["limit"]]

        took_ms = int((time.time() - start_time) * 1000)

        logger.info(f"✅ 涨停回调策略扫描完成: 找到 {len(results)} 只股票, 耗时 {took_ms}ms")

        return {
            "total": len(results),
            "items": results,
            "took_ms": took_ms,
            "params": params,
            "scanned_count": len(stock_codes)
        }


    def _precompute_stock_indicators(
        self,
        kline_data: List[Dict[str, Any]],
        stock_code: str,
        stock_name: str,
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """预计算单只股票的所有指标，用于回测加速

        Returns:
            包含所有预计算指标的字典，数据不足返回None
        """
        if len(kline_data) < 20:
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
            open_val = safe_float(k.get("open"))
            close_val = safe_float(k.get("close"))
            high_val = safe_float(k.get("high"))
            low_val = safe_float(k.get("low"))
            vol_val = safe_float(k.get("volume"))
            if open_val > 0 and close_val > 0 and high_val > 0 and low_val > 0 and vol_val > 0:
                valid_data.append(k)

        if len(valid_data) < 20:
            return None

        n = len(valid_data)
        dates = [k["trade_date"] for k in valid_data]
        opens = np.array([safe_float(k["open"]) for k in valid_data], dtype=np.float64)
        closes = np.array([safe_float(k["close"]) for k in valid_data], dtype=np.float64)
        highs = np.array([safe_float(k["high"]) for k in valid_data], dtype=np.float64)
        lows = np.array([safe_float(k["low"]) for k in valid_data], dtype=np.float64)
        volumes = np.array([safe_float(k["volume"]) for k in valid_data], dtype=np.float64)

        pct_chgs = np.zeros(n, dtype=np.float64)
        for i in range(n):
            pct = valid_data[i].get("pct_chg")
            if pct is not None:
                pct_chgs[i] = safe_float(pct)
            elif i > 0 and closes[i - 1] > 0:
                pct_chgs[i] = (closes[i] - closes[i - 1]) / closes[i - 1] * 100

        def calc_ma_np(data: np.ndarray, period: int) -> np.ndarray:
            result = np.full(n, np.nan, dtype=np.float64)
            if n < period:
                return result
            cumsum = np.cumsum(data)
            result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
            return result

        ma5 = calc_ma_np(closes, 5)
        ma10 = calc_ma_np(closes, 10)
        ma20 = calc_ma_np(closes, 20)

        atr14 = np.full(n, np.nan, dtype=np.float64)
        if n >= 5:
            tr = np.zeros(n)
            for i in range(1, n):
                tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            atr14[4] = np.mean(tr[1:5])
            for i in range(5, n):
                atr14[i] = (atr14[i-1] * 4 + tr[i]) / 5

        limit_up_threshold = self._get_limit_up_threshold(stock_code, stock_name)
        date_to_idx = {d: i for i, d in enumerate(dates)}

        return {
            "n": n,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "pct_chgs": pct_chgs,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "atr14": atr14,
            "limit_up_threshold": limit_up_threshold,
            "date_to_idx": date_to_idx
        }

    def _analyze_at_idx(
        self,
        indicators: Dict[str, Any],
        current_idx: int,
        stock_code: str,
        stock_name: str,
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if current_idx < 20:
            return None

        n = indicators["n"]
        dates = indicators["dates"]
        opens = indicators["opens"]
        closes = indicators["closes"]
        highs = indicators["highs"]
        lows = indicators["lows"]
        volumes = indicators["volumes"]
        pct_chgs = indicators["pct_chgs"]
        ma5 = indicators["ma5"]
        ma10 = indicators["ma10"]
        limit_up_threshold = indicators["limit_up_threshold"]

        max_lookback_days = params.get("max_lookback_days", 15)
        min_pullback_days = params.get("min_pullback_days", 2)
        max_pullback_days = params.get("max_pullback_days", 8)
        shrink_volume_ratio = params.get("shrink_volume_ratio", 0.5)
        min_shrink_days = params.get("min_shrink_days", 2)
        above_ma10 = params.get("above_ma10", True)
        ground_volume_ratio = params.get("ground_volume_ratio", 0.35)
        lower_shadow_ratio = params.get("lower_shadow_ratio", 0.015)
        breakout_ma5 = params.get("breakout_ma5", False)
        breakout_volume_ratio = params.get("breakout_volume_ratio", 1.5)

        limit_up_idx = None
        search_end = max(current_idx - max_lookback_days, 1)
        for i in range(current_idx, search_end, -1):
            if pct_chgs[i] >= limit_up_threshold:
                limit_up_idx = i
                break

        if limit_up_idx is None:
            return None

        days_since_limit_up = current_idx - limit_up_idx
        if days_since_limit_up < min_pullback_days or days_since_limit_up > max_pullback_days:
            return None

        limit_up_close = closes[limit_up_idx]
        limit_up_volume = volumes[limit_up_idx]
        limit_up_date = dates[limit_up_idx]

        pullback_indices = list(range(limit_up_idx + 1, current_idx + 1))
        if not pullback_indices:
            return None

        pullback_closes = closes[pullback_indices]
        pullback_volumes = volumes[pullback_indices]

        min_close_in_pullback = float(np.min(pullback_closes))
        current_close = closes[current_idx]
        pullback_depth = (limit_up_close - min_close_in_pullback) / limit_up_close * 100

        avg_pullback_volume = float(np.mean(pullback_volumes))
        volume_shrink_ratio_val = avg_pullback_volume / limit_up_volume if limit_up_volume > 0 else 1

        shrink_days = int(np.sum(pullback_volumes / limit_up_volume <= shrink_volume_ratio)) if limit_up_volume > 0 else 0
        if shrink_days < min_shrink_days:
            return None

        if above_ma10:
            ma10_broken = 0
            for idx in pullback_indices:
                if not np.isnan(ma10[idx]) and closes[idx] < ma10[idx]:
                    ma10_broken += 1
            if ma10_broken > 1:
                return None

        min_vol_idx_in_pullback = pullback_indices[int(np.argmin(pullback_volumes))]
        min_volume = volumes[min_vol_idx_in_pullback]
        ground_volume_ratio_val = min_volume / limit_up_volume if limit_up_volume > 0 else 1

        # 地量日位置：战法要求在第3-5天出现
        ground_day_offset = min_vol_idx_in_pullback - limit_up_idx
        ground_volume_in_right_position = 3 <= ground_day_offset <= 5

        vol_20_start = max(0, min_vol_idx_in_pullback - 20)
        vol_20_end = min_vol_idx_in_pullback
        if vol_20_end > vol_20_start:
            min_vol_20 = float(np.min(volumes[vol_20_start:vol_20_end + 1]))
            is_20day_ground = min_volume <= min_vol_20
        else:
            is_20day_ground = False

        is_ground_volume = ground_volume_ratio_val <= 0.33 and is_20day_ground

        ground_day_open = opens[min_vol_idx_in_pullback]
        ground_day_close = closes[min_vol_idx_in_pullback]
        ground_day_low = lows[min_vol_idx_in_pullback]

        lower_shadow = min(ground_day_open, ground_day_close) - ground_day_low
        lower_shadow_pct = lower_shadow / ground_day_low if ground_day_low > 0 else 0

        body_size = abs(ground_day_close - ground_day_open)
        shadow_to_body_ratio = (lower_shadow / body_size) if body_size > 0 else (99.0 if lower_shadow > 0 else 0.0)
        has_lower_shadow = shadow_to_body_ratio >= 2.0 or lower_shadow_pct >= lower_shadow_ratio

        # 空间位置：①不破涨停实体一半 ②或回踩10日线弹起
        limit_up_open = opens[limit_up_idx]
        limit_up_entity_low = min(limit_up_open, limit_up_close)
        limit_up_entity_mid = (limit_up_entity_low + max(limit_up_open, limit_up_close)) / 2
        space_position_ok = ground_day_low >= limit_up_entity_mid * 0.98

        ma10_bounce_ok = False
        if not np.isnan(ma10[min_vol_idx_in_pullback]):
            ma10_val = ma10[min_vol_idx_in_pullback]
            ma10_distance = (ground_day_low - ma10_val) / ma10_val * 100
            if -2 <= ma10_distance <= 1 and ground_day_close >= ma10_val:
                ma10_bounce_ok = True
        space_position_ok = space_position_ok or ma10_bounce_ok

        # 次日阳线确认
        next_day_bullish = False
        if min_vol_idx_in_pullback + 1 <= current_idx:
            next_day_idx = min_vol_idx_in_pullback + 1
            next_day_close = closes[next_day_idx]
            next_day_open = opens[next_day_idx]
            if next_day_close > next_day_open and next_day_close > ground_day_close:
                next_day_bullish = True

        days_since_ground_day = current_idx - min_vol_idx_in_pullback
        ground_day_low_price = lows[min_vol_idx_in_pullback]
        rebound_from_ground = (current_close - ground_day_low_price) / ground_day_low_price * 100 if ground_day_low_price > 0 else 0
        ground_day_body_pct = abs(ground_day_close - ground_day_open) / ground_day_open if ground_day_open > 0 else 0

        ma5_breakout = False
        breakout_volume = 1.0
        fake_breakout = False

        if breakout_ma5 and not np.isnan(ma5[current_idx]) and not np.isnan(ma5[current_idx - 1]):
            prev_close = closes[current_idx - 1]
            ma5_slope = ma5[current_idx] - ma5[current_idx - 1]
            ma5_flat_or_up = ma5_slope >= 0

            avg_vol_5 = float(np.mean(volumes[max(0, current_idx - 5):current_idx]))
            breakout_volume = volumes[current_idx] / avg_vol_5 if avg_vol_5 > 0 else 1

            upper_shadow = highs[current_idx] - max(opens[current_idx], closes[current_idx])
            upper_shadow_pct = upper_shadow / closes[current_idx] if closes[current_idx] > 0 else 0
            if upper_shadow_pct >= 0.025:
                fake_breakout = True

            is_above_ma5 = current_close >= ma5[current_idx]
            
            # 加强过滤：收盘价必须在回调区间最高价之上
            pullback_high = max(highs[i] for i in pullback_indices) if pullback_indices else float('inf')
            is_above_pullback_high = current_close >= pullback_high * 0.99

            # 加强过滤：5日线必须上穿10日线
            ma5_above_ma10 = False
            if not np.isnan(ma10[current_idx]) and not np.isnan(ma5[current_idx]):
                ma5_above_ma10 = ma5[current_idx] >= ma10[current_idx] * 0.995
            
            if is_above_ma5 and ma5_flat_or_up and breakout_volume >= breakout_volume_ratio and not fake_breakout and is_above_pullback_high and ma5_above_ma10:
                ma5_breakout = True

        small_body_days = 0
        for i in pullback_indices:
            body_pct = abs(closes[i] - opens[i]) / opens[i] if opens[i] > 0 else 0
            if body_pct < 0.02:
                small_body_days += 1
        small_body_ratio = small_body_days / len(pullback_indices) if pullback_indices else 0

        score = 0.0
        score_details = []
        # 预初始化各维度得分，避免条件分支未命中时变量未定义
        shrink_score = 0.0
        depth_score = 0.0
        ground_score = 0.0
        shadow_score = 0.0
        space_score = 0.0
        above_score = 0.0
        breakout_score = 0.0

        shrink_score = max(0, 20 * (1 - volume_shrink_ratio_val))
        score += shrink_score
        score_details.append(f"缩量: {volume_shrink_ratio_val:.2%} → {shrink_score:.1f}分")

        if 3 <= pullback_depth <= 20:
            depth_score = 15 - abs(pullback_depth - 10) * 1.5
            depth_score = max(0, depth_score)
            score += depth_score
            score_details.append(f"回调幅度: {pullback_depth:.1f}% → {depth_score:.1f}分")

        if is_ground_volume:
            ground_score = 15
            if is_20day_ground and ground_volume_ratio_val > ground_volume_ratio:
                ground_score = 13
        else:
            ground_score = max(0, 15 * (1 - (ground_volume_ratio_val - ground_volume_ratio) / 0.5))
        score += ground_score
        score_details.append(f"地量: {ground_volume_ratio_val:.2%} {'(20日最低)' if is_20day_ground else ''} → {ground_score:.1f}分")

        if has_lower_shadow:
            shadow_score = min(15, 8 + shadow_to_body_ratio * 2)
            score += shadow_score
            score_details.append(f"下影线: 实体比{shadow_to_body_ratio:.1f}倍 → {shadow_score:.1f}分")

        if space_position_ok:
            space_score = 10
            score += space_score
            score_details.append(f"空间位置: 未破涨停实体一半 → {space_score:.1f}分")

        if above_ma10 and not np.isnan(ma10[current_idx]) and current_close >= ma10[current_idx]:
            above_score = 10
            score += above_score
            score_details.append(f"站上10日线 → {above_score:.1f}分")

        small_body_score = small_body_ratio * 5
        score += small_body_score
        score_details.append(f"小阴小阳: {small_body_ratio:.0%} → {small_body_score:.1f}分")

        if ma5_breakout:
            breakout_score = 25
            score += breakout_score
            score_details.append(f"突破5日线: 放量{breakout_volume:.1f}倍 → {breakout_score:.1f}分")
        elif fake_breakout:
            score_details.append(f"假突破过滤: 上影线过长，不确认右侧")

        # 评分维度汇总（用于 score_validation 校验）
        dimensions = {
            "缩量": shrink_score,
            "回调幅度": depth_score,
            "地量": ground_score,
            "下影线": shadow_score,
            "空间位置": space_score,
            "站上10日线": above_score,
            "小阴小阳": small_body_score,
            "突破5日线": breakout_score,
        }
        # 评分校验（修复回测时 NameError：原代码引用了未定义的 score_validation）
        score_validation = _validate_limit_up_score(dimensions, score)

        signal_type = "观察"
        # 地量信号确认：有下影线 + 满足地量标准 + （地量日在第3-5天 或 次日阳线确认）
        has_ground_signal = has_lower_shadow and is_ground_volume and ground_volume_in_right_position

        if ma5_breakout:
            signal_type = "右侧确认"
        elif has_ground_signal:
            if days_since_ground_day <= 2 and rebound_from_ground <= 3:
                signal_type = "左侧潜伏"
            elif days_since_ground_day <= 4 and rebound_from_ground <= 5:
                signal_type = "底部观察"
            else:
                signal_type = "观察"
        elif volume_shrink_ratio_val <= shrink_volume_ratio:
            signal_type = "缩量回调中"

        upside_space = (limit_up_close - current_close) / current_close * 100 if current_close > 0 else 0

        return {
            "code": stock_code,
            "name": stock_name,
            "close": round(float(current_close), 2),
            "pct_chg": round(float(pct_chgs[current_idx]), 2),
            "limit_up_date": limit_up_date,
            "days_since_limit_up": days_since_limit_up,
            "limit_up_close": round(float(limit_up_close), 2),
            "limit_up_idx": limit_up_idx,
            "pullback_depth": round(float(pullback_depth), 2),
            "volume_shrink_ratio": round(float(volume_shrink_ratio_val), 4),
            "ground_volume_ratio": round(float(ground_volume_ratio_val), 4),
            "lower_shadow_pct": round(float(lower_shadow_pct), 4),
            "shadow_to_body_ratio": round(float(shadow_to_body_ratio), 2),
            "space_position_ok": space_position_ok,
            "is_20day_ground": is_20day_ground,
            "fake_breakout": fake_breakout,
            "signal_type": signal_type,
            "score": round(float(score), 1),
            "score_details": score_details,
            "score_validation": score_validation,
            "upside_space": round(float(upside_space), 2),
            "ma5": round(float(ma5[current_idx]), 2) if not np.isnan(ma5[current_idx]) else None,
            "ma10": round(float(ma10[current_idx]), 2) if not np.isnan(ma10[current_idx]) else None,
            "ma20": round(float(indicators["ma20"][current_idx]), 2) if not np.isnan(indicators["ma20"][current_idx]) else None,
            "small_body_ratio": round(float(small_body_ratio), 4),
            "ground_day_offset": ground_day_offset,
            "days_since_ground_day": days_since_ground_day,
            "rebound_from_ground": round(float(rebound_from_ground), 2),
            "ground_day_body_pct": round(float(ground_day_body_pct), 4),
            "industry": "",
            # 各阶段日期
            "pullback_start_date": indicators["dates"][limit_up_idx + 1] if limit_up_idx + 1 < indicators["n"] else None,
            "pullback_end_date": indicators["dates"][current_idx],
            "bottom_watch_start_date": indicators["dates"][min_vol_idx_in_pullback] if is_ground_volume else None,
            "bottom_watch_end_date": indicators["dates"][current_idx] if is_ground_volume else None,
            "left_buy_date": indicators["dates"][min_vol_idx_in_pullback] if has_ground_signal else None,
            "right_buy_date": indicators["dates"][current_idx] if ma5_breakout else None,
            "ground_day_date": indicators["dates"][min_vol_idx_in_pullback] if is_ground_volume else None
        }

    def _sell_point_fast(
        self,
        indicators: Dict[str, Any],
        buy_idx: int,
        limit_up_close: float,
        limit_up_idx: int,
        max_hold_days: int = 20,
        buy_price: float = 0.0
    ) -> tuple:
        """快速卖点计算（四条规则，使用预计算指标）

        卖点1：ATR止损 → 动态止损，适应不同波动率
        卖点2：10日线止损 → 趋势破坏止损（备选）
        卖点3：时间止盈 → 涨停日后第8天未突破涨停价
        卖点4：高位止盈 → 放量滞涨
        卖点5：移动止盈 → 盈利后跌破5日线或ATR止盈
        """
        n = indicators["n"]
        closes = indicators["closes"]
        volumes = indicators["volumes"]
        highs = indicators["highs"]
        opens = indicators["opens"]
        lows = indicators["lows"]
        ma5 = indicators["ma5"]
        ma10 = indicators["ma10"]
        ma20 = indicators["ma20"]
        atr14 = indicators["atr14"]

        if buy_idx >= n - 1:
            return buy_idx, "无法持有"

        max_high_since_limit_up = float(np.max(highs[limit_up_idx:buy_idx + 1])) if buy_idx > limit_up_idx else highs[limit_up_idx]
        has_exceeded_limit_up = max_high_since_limit_up >= limit_up_close

        trailing_stop_active = False
        trailing_stop_price = buy_price * 0.95

        end_idx = min(buy_idx + max_hold_days + 1, n)
        for check_idx in range(buy_idx + 1, end_idx):
            current_close = closes[check_idx]
            current_high = highs[check_idx]
            current_vol = volumes[check_idx]

            if current_high > max_high_since_limit_up:
                max_high_since_limit_up = current_high
            if current_high >= limit_up_close:
                has_exceeded_limit_up = True

                # 持续更新移动止盈价（盈利>3%开启）
            if buy_price > 0 and current_close > buy_price * 1.03:
                trailing_stop_active = True
                ma5_stop = ma5[check_idx] if not np.isnan(ma5[check_idx]) else 0
                atr_trailing_stop = max_high_since_limit_up - 1.0 * atr14[check_idx] if (not np.isnan(atr14[check_idx]) and atr14[check_idx] > 0) else 0
                new_stop_price = max(ma5_stop, atr_trailing_stop)
                if new_stop_price > trailing_stop_price:
                    trailing_stop_price = new_stop_price

            # 卖点1：ATR止损（优先）- 买入价下方0.4倍ATR
            if not np.isnan(atr14[check_idx]) and atr14[check_idx] > 0:
                atr_stop_price = buy_price - 0.4 * atr14[check_idx]
                if current_close < atr_stop_price:
                    return check_idx, "ATR止损"

            # 卖点2：10日线止损（兜底）- 收盘价跌破10日线98%
            if not np.isnan(ma10[check_idx]) and current_close < ma10[check_idx] * 0.98:
                return check_idx, "10日止损"

            # 卖点3：时间止盈 - 第8天未突破涨停价
            days_since_limit_up = check_idx - limit_up_idx
            if days_since_limit_up == 8 and not has_exceeded_limit_up:
                return check_idx, "8日时间止盈"

            # 卖点4：高位止盈 - 放量滞涨
            if check_idx >= 5:
                avg_vol_5 = float(np.mean(volumes[max(0, check_idx - 5):check_idx]))
                if avg_vol_5 > 0:
                    vol_ratio = current_vol / avg_vol_5
                    body_pct = abs(current_close - opens[check_idx]) / opens[check_idx] if opens[check_idx] > 0 else 0
                    upper_shadow = highs[check_idx] - max(opens[check_idx], current_close)
                    upper_shadow_pct = upper_shadow / opens[check_idx] if opens[check_idx] > 0 else 0
                    if vol_ratio >= 1.5 and (body_pct < 0.02 or upper_shadow_pct > 0.03):
                        return check_idx, "高位止盈"

            # 卖点5：移动止盈 - 跌破移动止盈价（5日线和ATR止盈取较高者）
            if trailing_stop_active and trailing_stop_price > 0:
                if current_close < trailing_stop_price:
                    # 判断是哪种止盈
                    if not np.isnan(ma5[check_idx]) and current_close < ma5[check_idx]:
                        return check_idx, "5日线止盈"
                    else:
                        return check_idx, "ATR止盈"

        sell_idx = min(buy_idx + max_hold_days, n - 1)
        return sell_idx, "到期卖出"

    def _check_daily_sell_signal(
        self,
        indicators: Dict[str, Any],
        check_idx: int,
        pos_state: Dict[str, Any],
        buy_price: float,
        limit_up_close: float,
        limit_up_idx: int,
        max_hold_days: int = 20
    ) -> Optional[Dict[str, Any]]:
        """逐日检查卖出信号（用于逐日盯市回测）

        检查并更新持仓状态，如触发卖出则返回卖出信息。

        Args:
            indicators: 预计算指标
            check_idx: 当前检查的K线索引
            pos_state: 持仓状态字典（会被更新）
            buy_price: 买入价
            limit_up_close: 涨停收盘价
            limit_up_idx: 涨停K线索引
            max_hold_days: 最大持有天数

        Returns:
            如触发卖出，返回 {"sell_reason": "..."}，否则返回 None
        """
        n = indicators["n"]
        closes = indicators["closes"]
        volumes = indicators["volumes"]
        highs = indicators["highs"]
        opens = indicators["opens"]
        ma5 = indicators["ma5"]
        ma10 = indicators["ma10"]
        atr14 = indicators["atr14"]

        if check_idx >= n or check_idx <= 0:
            return None

        current_close = closes[check_idx]
        current_high = highs[check_idx]
        current_vol = volumes[check_idx]

        # 更新涨停以来最高价
        if current_high > pos_state["max_high_since_limit_up"]:
            pos_state["max_high_since_limit_up"] = current_high
        if current_high >= limit_up_close:
            pos_state["has_exceeded_limit_up"] = True

        # 更新移动止盈价（盈利>3%开启）
        if buy_price > 0 and current_close > buy_price * 1.03:
            pos_state["trailing_stop_active"] = True
            ma5_stop = ma5[check_idx] if not np.isnan(ma5[check_idx]) else 0
            atr_trailing_stop = pos_state["max_high_since_limit_up"] - 1.0 * atr14[check_idx] \
                if (not np.isnan(atr14[check_idx]) and atr14[check_idx] > 0) else 0
            new_stop_price = max(ma5_stop, atr_trailing_stop)
            if new_stop_price > pos_state["trailing_stop_price"]:
                pos_state["trailing_stop_price"] = new_stop_price

        days_since_limit_up = check_idx - limit_up_idx
        days_held = check_idx - pos_state["buy_idx"]

        # 卖点1：ATR止损（优先）
        if not np.isnan(atr14[check_idx]) and atr14[check_idx] > 0:
            atr_stop_price = buy_price - 0.4 * atr14[check_idx]
            if current_close < atr_stop_price:
                return {"sell_reason": "ATR止损"}

        # 卖点2：10日线止损（兜底）
        if not np.isnan(ma10[check_idx]) and current_close < ma10[check_idx] * 0.98:
            return {"sell_reason": "10日止损"}

        # 卖点3：时间止盈 - 第8天未突破涨停价
        if days_since_limit_up == 8 and not pos_state["has_exceeded_limit_up"]:
            return {"sell_reason": "8日时间止盈"}

        # 卖点4：高位止盈 - 放量滞涨
        if check_idx >= 5:
            avg_vol_5 = float(np.mean(volumes[max(0, check_idx - 5):check_idx]))
            if avg_vol_5 > 0:
                vol_ratio = current_vol / avg_vol_5
                body_pct = abs(current_close - opens[check_idx]) / opens[check_idx] if opens[check_idx] > 0 else 0
                upper_shadow = highs[check_idx] - max(opens[check_idx], current_close)
                upper_shadow_pct = upper_shadow / opens[check_idx] if opens[check_idx] > 0 else 0
                if vol_ratio >= 1.5 and (body_pct < 0.02 or upper_shadow_pct > 0.03):
                    return {"sell_reason": "高位止盈"}

        # 卖点5：移动止盈
        if pos_state["trailing_stop_active"] and pos_state["trailing_stop_price"] > 0:
            if current_close < pos_state["trailing_stop_price"]:
                if not np.isnan(ma5[check_idx]) and current_close < ma5[check_idx]:
                    return {"sell_reason": "5日线止盈"}
                else:
                    return {"sell_reason": "ATR止盈"}

        # 到期卖出
        if days_held >= max_hold_days:
            return {"sell_reason": "到期卖出"}

        return None

    async def backtest(
        self,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """涨停回调策略回测（性能优化版）

        优化点：
        1. 预计算每只股票的所有指标（numpy向量化）
        2. 建立日期→索引映射，O(1)查找
        3. 外层循环股票，内层循环日期，减少重复计算
        4. 使用numpy数组替代Python列表循环

        Args:
            params: 回测参数
                - start_date: 回测开始日期
                - end_date: 回测结束日期
                - hold_days: 最大持有天数（默认15，安全阀，实际按卖点规则卖出）
                - top_n: 每次选前N只股票（默认10）
                - min_score: 最低评分
                - 其他策略参数同 scan_limit_up_pullback

        Returns:
            回测结果
        """
        import time
        from collections import defaultdict
        from datetime import datetime, timedelta

        start_time = time.time()

        if params is None:
            params = {}

        # 精简参数：只暴露4个核心参数，其余内部固定
        default_params = {
            "start_date": None,
            "end_date": None,
            "hold_days": 20,
            "top_n": 10,
            "min_score": 30,
            "initial_capital": 1000000,
            "max_position_pct": 0.1,
            # 以下为内部固定参数
            "max_lookback_days": 15,
            "min_pullback_days": 2,
            "max_pullback_days": 8,
            "shrink_volume_ratio": 0.5,
            "min_shrink_days": 2,
            "above_ma10": True,
            "ground_volume_ratio": 0.35,
            "lower_shadow_ratio": 0.015,
            "breakout_ma5": True,
            "breakout_volume_ratio": 1.5,
            "slippage_pct": 0.003,
            "max_holdings": 30
        }
        default_params.update(params)
        params = default_params

        hold_days = params["hold_days"]
        top_n = params["top_n"]

        logger.info(f"📊 涨停回调策略回测开始（优化版），参数: {params}")

        db = await self._get_db()

        basic_collection = db["stock_basic_info"]
        basic_cursor = basic_collection.find(
            {
                "$or": [
                    {"category": "stock_cn"},
                    {"sse": {"$in": ["上海证券交易所", "深圳证券交易所", "上交所", "深交所"]}},
                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                ]
            },
            projection={"_id": 0, "code": 1, "symbol": 1, "name": 1}
        )
        basic_stocks = await basic_cursor.to_list(length=10000)

        stock_info_map = {}
        for s in basic_stocks:
            code = s.get("code") or s.get("symbol")
            if code and len(str(code)) == 6 and str(code).isdigit():
                code = str(code).zfill(6)
                stock_info_map[code] = {"name": s.get("name", "")}

        stock_codes = list(stock_info_map.keys())
        total_scanned = len(stock_codes)
        logger.info(f"📊 待回测股票数量: {total_scanned}")

        end_date = datetime.strptime(params["end_date"], "%Y-%m-%d") if params.get("end_date") else datetime.now()
        start_date = datetime.strptime(params["start_date"], "%Y-%m-%d") if params.get("start_date") else end_date - timedelta(days=180)
        data_start = start_date - timedelta(days=120)
        data_end = end_date + timedelta(days=hold_days + 10)

        quotes_collection = db["stock_daily_quotes"]
        quotes_cursor = quotes_collection.find(
            {
                "code": {"$in": stock_codes},
                "period": "daily",
                "trade_date": {"$gte": data_start.strftime('%Y-%m-%d'), "$lte": data_end.strftime('%Y-%m-%d')}
            },
            projection={"_id": 0, "code": 1, "trade_date": 1, "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1, "pct_chg": 1, "data_source": 1}
        ).sort("trade_date", 1)

        # 性能优化：流式遍历游标直接写入分组字典，避免 to_list 产生巨型中间列表
        # 原 to_list(length=total_scanned*300) 会把 ~1.5M 条记录全量驻留内存，
        # 再复制到 quotes_by_date_by_stock，导致内存翻倍。流式处理只需一份内存。
        DATA_SOURCE_PRIORITY = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}
        quotes_by_date_by_stock = defaultdict(dict)
        raw_count = 0
        async for quote in quotes_cursor:
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
                existing_priority = DATA_SOURCE_PRIORITY.get(existing_src, 0)
                new_priority = DATA_SOURCE_PRIORITY.get(new_src, 0)
                if new_priority > existing_priority:
                    quotes_by_date_by_stock[code][trade_date] = quote
            raw_count += 1
        logger.info(f"📊 流式加载行情完成: {raw_count} 条原始记录, {len(quotes_by_date_by_stock)} 只股票")

        quotes_by_stock = {}
        all_trade_dates = set()
        for code, date_map in quotes_by_date_by_stock.items():
            sorted_quotes = sorted(date_map.values(), key=lambda x: x.get("trade_date", ""))
            quotes_by_stock[code] = sorted_quotes
            for q in sorted_quotes:
                all_trade_dates.add(q["trade_date"])

        trade_dates = sorted(list(all_trade_dates))
        logger.info(f"📊 交易日数量: {len(trade_dates)}")

        # 计算每日市场涨跌比例（大盘环境过滤）
        logger.info("📊 计算市场环境指标...")
        market_rise_ratio: Dict[str, float] = {}
        for td in trade_dates:
            rise_count = 0
            total_count = 0
            for code, date_map in quotes_by_date_by_stock.items():
                q = date_map.get(td)
                if q and q.get("pct_chg") is not None:
                    total_count += 1
                    if q["pct_chg"] > 0:
                        rise_count += 1
            if total_count > 0:
                market_rise_ratio[td] = rise_count / total_count
            else:
                market_rise_ratio[td] = 0.5
        logger.info(f"📊 市场环境计算完成，共{len(market_rise_ratio)}个交易日")

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        backtest_dates = [d for d in trade_dates if start_str <= d <= end_str]
        logger.info(f"📊 回测天数: {len(backtest_dates)}")

        # ===== 核心优化：预计算+按日期收集信号 =====
        daily_signals: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        indicators_cache: Dict[str, Any] = {}

        precompute_start = time.time()
        processed_stocks = 0

        for code in stock_codes:
            kline_data = quotes_by_stock.get(code, [])
            if len(kline_data) < 20:
                continue

            info = stock_info_map.get(code, {})
            name = info.get("name", "")

            indicators = self._precompute_stock_indicators(kline_data, code, name, params)
            if indicators is None:
                continue

            indicators_cache[code] = indicators
            date_to_idx = indicators["date_to_idx"]
            processed_stocks += 1

            for current_date in backtest_dates:
                current_idx = date_to_idx.get(current_date, -1)
                if current_idx < 20:
                    continue

                result = self._analyze_at_idx(indicators, current_idx, code, name, params)
                if result and result["score"] >= params["min_score"] and result["signal_type"] in ("左侧潜伏", "右侧确认"):
                    daily_signals[current_date].append(result)

            if processed_stocks % 500 == 0:
                elapsed = time.time() - precompute_start
                logger.info(f"📊 预计算进度: {processed_stocks}/{total_scanned}, 耗时 {elapsed:.1f}s")

        precompute_elapsed = time.time() - precompute_start
        logger.info(f"📊 预计算完成: {processed_stocks} 只股票, 耗时 {precompute_elapsed:.1f}s")

        initial_capital = params.get("initial_capital", 1000000)
        max_position_pct = params.get("max_position_pct", 0.1)
        signal_cooldown_days = params.get("signal_cooldown_days", 5)
        slippage_pct = params.get("slippage_pct", 0.003)
        fee_rate = 0.001  # 单边手续费0.1%
        max_holdings = params.get("max_holdings", 30)

        # ===== 第二步：逐日盯市回测（T+1交易规则）=====
        daily_results = []
        all_trades = []
        capital_history = []

        holdings: Dict[str, dict] = {}
        recent_buys: Dict[str, str] = {}
        capital = float(initial_capital)
        peak_capital = float(initial_capital)
        max_drawdown = 0.0

        sorted_dates = sorted(backtest_dates)

        for date_idx, current_date in enumerate(sorted_dates):
            # ========== 1. 处理卖出 ==========
            codes_to_sell = []
            for code, pos in holdings.items():
                indicators = indicators_cache.get(code)
                if not indicators:
                    continue

                idx = indicators["date_to_idx"].get(current_date, -1)
                if idx < 0 or idx <= pos["buy_idx"]:
                    continue

                close = indicators["closes"][idx]
                prev_close = indicators["closes"][idx - 1] if idx > 0 else close
                open_p = indicators["opens"][idx]

                # 跌停无法卖出，跳过
                if not self._can_sell(close, open_p, prev_close):
                    continue

                # 检查卖出信号
                sell_signal = self._check_daily_sell_signal(
                    indicators, idx, pos["state"],
                    pos["buy_price"], pos["limit_up_close"],
                    pos["limit_up_idx"], max_hold_days=hold_days
                )

                if sell_signal:
                    sell_reason = sell_signal["sell_reason"]
                    # 卖出滑点
                    sell_price = close * (1 - slippage_pct)
                    proceeds = pos["remaining_shares"] * sell_price * (1 - fee_rate)
                    capital += proceeds
                    total_proceeds = pos["cumulative_proceeds"] + proceeds
                    return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
                    avg_sell = total_proceeds / pos["total_shares"] / (1 - fee_rate)

                    all_trades.append({
                        "code": code,
                        "name": pos["name"],
                        "buy_date": pos["buy_date"],
                        "sell_date": current_date,
                        "buy_price": round(pos["buy_price"], 2),
                        "sell_price": round(avg_sell, 2),
                        "return_pct": round(return_pct, 2),
                        "score": pos["score"],
                        "signal_type": pos["signal_type"],
                        "sell_reason": sell_reason,
                        "limit_up_date": pos.get("limit_up_date"),
                        "pullback_start_date": pos.get("pullback_start_date"),
                        "pullback_end_date": pos.get("pullback_end_date"),
                        "left_buy_date": pos.get("left_buy_date"),
                        "right_buy_date": pos.get("right_buy_date"),
                        "ground_day_date": pos.get("ground_day_date"),
                        "shares": pos["total_shares"],
                        "profit": round(total_proceeds - pos["cost"], 2)
                    })
                    codes_to_sell.append(code)

            for code in codes_to_sell:
                del holdings[code]

            # ========== 2. 处理买入 ==========
            rise_ratio = market_rise_ratio.get(current_date, 0.5)
            selected_stocks = daily_signals.get(current_date, [])

            # 极端熊市（上涨比例<20%）不交易
            market_skip = False
            if rise_ratio < 0.2:
                market_skip = True

            if not market_skip and len(holdings) < max_holdings:
                selected_stocks.sort(key=lambda x: x["score"], reverse=True)

                # 弱势环境减半
                if rise_ratio < 0.4:
                    selected_stocks = selected_stocks[:max(1, int(len(selected_stocks) * 0.5))]

                available_slots = min(max_holdings - len(holdings), top_n)

                for stock in selected_stocks[:available_slots]:
                    code = stock["code"]
                    if code in holdings:
                        continue

                    # 冷却期检查
                    last_buy = recent_buys.get(code)
                    if last_buy:
                        try:
                            last_dt = datetime.strptime(last_buy, "%Y-%m-%d")
                            curr_dt = datetime.strptime(current_date, "%Y-%m-%d")
                            if (curr_dt - last_dt).days < signal_cooldown_days:
                                continue
                        except ValueError:
                            pass

                    indicators = indicators_cache.get(code)
                    if not indicators:
                        continue

                    signal_idx = indicators["date_to_idx"].get(current_date, -1)
                    if signal_idx < 0:
                        continue

                    # T+1买入：次日开盘价
                    buy_idx = signal_idx + 1
                    if buy_idx >= indicators["n"]:
                        continue

                    buy_price_raw = float(indicators["opens"][buy_idx])
                    if buy_price_raw <= 0:
                        continue

                    prev_close = float(indicators["closes"][signal_idx])
                    if not self._can_buy(buy_price_raw, prev_close):
                        continue

                    # 买入滑点
                    buy_price = buy_price_raw * (1 + slippage_pct)

                    # 仓位计算
                    pos_size = min(max_position_pct, 1.0 / max(1, len(holdings) + top_n))
                    amount = capital * pos_size
                    shares = int(amount / buy_price / 100) * 100
                    if shares < 100:
                        continue

                    cost = shares * buy_price * (1 + fee_rate)
                    if cost > capital * 0.95:
                        continue

                    limit_up_idx = stock.get("limit_up_idx", 0)
                    limit_up_close = stock.get("limit_up_close", 0)

                    # 初始状态
                    initial_high = float(np.max(indicators["highs"][limit_up_idx:buy_idx + 1])) \
                        if buy_idx > limit_up_idx else indicators["highs"][limit_up_idx]

                    holdings[code] = {
                        "name": stock["name"],
                        "buy_date": indicators["dates"][buy_idx],
                        "buy_idx": buy_idx,
                        "buy_price": buy_price,
                        "total_shares": shares,
                        "remaining_shares": shares,
                        "cost": cost,
                        "cumulative_proceeds": 0.0,
                        "score": stock["score"],
                        "signal_type": stock["signal_type"],
                        "limit_up_close": limit_up_close,
                        "limit_up_idx": limit_up_idx,
                        "limit_up_date": stock.get("limit_up_date"),
                        "pullback_start_date": stock.get("pullback_start_date"),
                        "pullback_end_date": stock.get("pullback_end_date"),
                        "left_buy_date": stock.get("left_buy_date"),
                        "right_buy_date": stock.get("right_buy_date"),
                        "ground_day_date": stock.get("ground_day_date"),
                        "last_valid_idx": buy_idx,
                        "state": {
                            "buy_idx": buy_idx,
                            "max_high_since_limit_up": initial_high,
                            "has_exceeded_limit_up": initial_high >= limit_up_close,
                            "trailing_stop_active": False,
                            "trailing_stop_price": buy_price * 0.95
                        }
                    }
                    capital -= cost
                    recent_buys[code] = indicators["dates"][buy_idx]

            # ========== 3. 计算当日总资产 ==========
            total_value = capital
            for code, pos in holdings.items():
                indicators = pos.get("ind") or indicators_cache.get(code)
                if not indicators:
                    continue
                idx = indicators["date_to_idx"].get(current_date, -1)
                if idx < 0:
                    idx = pos.get("last_valid_idx", pos["buy_idx"])
                else:
                    pos["last_valid_idx"] = idx
                if idx >= 0 and idx < indicators["n"]:
                    total_value += pos["remaining_shares"] * indicators["closes"][idx]

            capital_history.append(total_value)
            peak_capital = max(peak_capital, total_value)
            dd = (peak_capital - total_value) / peak_capital * 100 if peak_capital > 0 else 0
            max_drawdown = max(max_drawdown, dd)

            total_position_value = total_value - capital
            position_pct = (total_position_value / total_value * 100) if total_value > 0 else 0

            daily_results.append({
                "date": current_date,
                "total_value": round(total_value, 2),
                "position_count": len(holdings),
                "position_pct": round(position_pct, 2),
                "cash": round(capital, 2),
                "position_value": round(total_position_value, 2),
                "return_pct": round((total_value - initial_capital) / initial_capital * 100, 2),
                "drawdown": round(dd, 2),
                "market_rise_ratio": round(rise_ratio * 100, 1)
            })

        # ========== 4. 期末清算 ==========
        final_value = capital
        last_date = sorted_dates[-1] if sorted_dates else ""
        for code, pos in holdings.items():
            indicators = indicators_cache.get(code)
            if not indicators:
                continue
            idx = indicators["date_to_idx"].get(last_date, indicators["n"] - 1)
            if idx < 0:
                idx = indicators["n"] - 1
            sell_price = indicators["closes"][idx] * (1 - slippage_pct)
            proceeds = pos["remaining_shares"] * sell_price * (1 - fee_rate)
            final_value += proceeds
            total_proceeds = pos["cumulative_proceeds"] + proceeds
            return_pct = (total_proceeds - pos["cost"]) / pos["cost"] * 100
            avg_sell = total_proceeds / pos["total_shares"] / (1 - fee_rate)
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
                "limit_up_date": pos.get("limit_up_date"),
                "shares": pos["total_shares"],
                "profit": round(total_proceeds - pos["cost"], 2)
            })

        # ========== 5. 统计指标 ==========
        total_trades = len(all_trades)
        if total_trades > 0:
            wins = [t for t in all_trades if t["return_pct"] > 0]
            losses = [t for t in all_trades if t["return_pct"] <= 0]
            win_rate = len(wins) / total_trades * 100
            avg_return = float(np.mean([t["return_pct"] for t in all_trades]))
            avg_win = float(np.mean([t["return_pct"] for t in wins])) if wins else 0
            avg_loss = float(np.mean([t["return_pct"] for t in losses])) if losses else 0
            profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

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

        # 日收益率 & 夏普比率
        daily_returns = []
        for i in range(1, len(capital_history)):
            if capital_history[i - 1] > 0:
                daily_returns.append((capital_history[i] - capital_history[i - 1]) / capital_history[i - 1])

        if daily_returns:
            avg_daily_return = float(np.mean(daily_returns))
            std_daily_return = float(np.std(daily_returns))
            risk_free_daily = 0.03 / 252
            sharpe_ratio = (avg_daily_return - risk_free_daily) / std_daily_return * np.sqrt(252) \
                if std_daily_return > 0 else 0
        else:
            sharpe_ratio = 0

        # 卡玛比率
        days_count = len(sorted_dates) if sorted_dates else 1
        annualized_return = (1 + total_return / 100) ** (252 / days_count) - 1 if days_count > 0 else 0
        calmar_ratio = annualized_return / (max_drawdown / 100) if max_drawdown > 0 else 0

        # 手续费估算
        total_fees = 0.0
        for t in all_trades:
            cost_basis = t["buy_price"] * t["shares"]
            total_fees += cost_basis * (fee_rate * 2 + slippage_pct * 2)

        # 按信号类型统计
        signal_stats: Dict[str, Dict[str, Any]] = {}
        for t in all_trades:
            st = t["signal_type"]
            if st not in signal_stats:
                signal_stats[st] = {"count": 0, "wins": 0, "returns": []}
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

        return {
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
            "backtest_days": len(sorted_dates),
            "signal_stats": signal_summary,
            "sell_reason_stats": sell_reason_summary,
            "daily_results": daily_results[:50],
            "top_trades": sorted(all_trades, key=lambda x: x["return_pct"], reverse=True)[:20],
            "worst_trades": sorted(all_trades, key=lambda x: x["return_pct"])[:20],
            "params": params,
            "took_ms": took_ms
        }

# 单例
_limit_up_pullback_service = None


def get_limit_up_pullback_service() -> LimitUpPullbackService:
    """获取涨停回调策略服务单例"""
    global _limit_up_pullback_service
    if _limit_up_pullback_service is None:
        _limit_up_pullback_service = LimitUpPullbackService()
    return _limit_up_pullback_service
