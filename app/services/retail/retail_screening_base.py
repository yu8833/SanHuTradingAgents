"""
散户策略选股共享基础服务

提供4个散户策略共用的基础设施：
- 数据获取（stock_basic_info / stock_daily_quotes / stock_screening_view）
- 回测引擎（通用回测框架，避免幸存者偏差/未来函数/流动性/交易成本4个陷阱）
- 通用工具函数
"""

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from app.utils.timezone import now_tz

import numpy as np

logger = logging.getLogger(__name__)

# A股涨跌停幅度
LIMIT_UP_PCT_MAIN = 9.8  # 主板
LIMIT_UP_PCT_KCB = 19.5  # 科创板
LIMIT_UP_PCT_CYB = 19.5  # 创业板
LIMIT_DOWN_PCT_MAIN = -9.8
LIMIT_DOWN_PCT_KCB = -19.5
LIMIT_DOWN_PCT_CYB = -19.5

# 交易成本
COMMISSION_RATE = 0.00025  # 佣金万2.5
STAMP_TAX_RATE = 0.001  # 印花税千1（卖出）
SLIPPAGE_RATE = 0.002  # 滑点0.2%


class RetailScreeningBase:
    """散户策略选股共享基础"""

    def __init__(self):
        self._db = None
        self._stock_list_cache = None
        self._stock_list_cache_time = 0

    async def _get_db(self):
        """获取MongoDB连接"""
        if self._db is None:
            from app.core.database import get_mongo_db
            self._db = get_mongo_db()
        return self._db

    async def _get_stock_list(self, force_refresh: bool = False) -> list[dict]:
        """获取A股股票列表（带缓存，5分钟过期）"""
        now = time.time()
        if (
            not force_refresh
            and self._stock_list_cache
            and now - self._stock_list_cache_time < 300
        ):
            return self._stock_list_cache

        db = await self._get_db()
        cursor = db["stock_basic_info"].find(
            {},
            {
                "code": 1,
                "name": 1,
                "industry": 1,
                "market": 1,
                "list_date": 1,
                "_id": 0,
            },
        )
        stocks = await cursor.to_list(length=None)
        self._stock_list_cache = stocks
        self._stock_list_cache_time = now
        return stocks

    async def _get_screening_view_batch(
        self, codes: list[str] | None = None
    ) -> dict[str, dict]:
        """
        从 stock_screening_view 获取最新行情+估值数据
        返回 {code: {pe, pb, total_mv, circ_mv, turnover_rate, close, pct_chg, ...}}
        """
        db = await self._get_db()
        query = {}
        if codes:
            query["code"] = {"$in": codes}
        cursor = db["stock_screening_view"].find(
            query,
            {
                "code": 1,
                "name": 1,
                "industry": 1,
                "market": 1,
                "pe": 1,
                "pb": 1,
                "total_mv": 1,
                "circ_mv": 1,
                "turnover_rate": 1,
                "close": 1,
                "pct_chg": 1,
                "volume": 1,
                "amount": 1,
                "trade_date": 1,
                "_id": 0,
            },
        )
        docs = await cursor.to_list(length=None)
        return {d["code"]: d for d in docs if d.get("code")}

    async def _get_screening_view_for_date(
        self, date_str: str, codes: list[str] | None = None
    ) -> dict[str, dict]:
        """
        从 stock_daily_quotes 获取指定日期的历史行情数据，模拟当时的筛选视图
        用于回测，避免未来函数

        Args:
            date_str: 查询日期 YYYY-MM-DD
            codes: 股票代码列表，None 表示全部

        Returns:
            {code: {pe, pb, total_mv, close, pct_chg, ...}}
        """
        db = await self._get_db()

        # 1. 获取指定日期的历史行情
        query = {
            "trade_date": date_str,
            "period": "daily",
        }
        if codes:
            query["code"] = {"$in": codes}

        cursor = db["stock_daily_quotes"].find(
            query,
            {
                "code": 1,
                "close": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "pct_chg": 1,
                "volume": 1,
                "amount": 1,
                "pe": 1,
                "pb": 1,
                "total_mv": 1,
                "circ_mv": 1,
                "turnover_rate": 1,
                "trade_date": 1,
                "data_source": 1,  # 用于多数据源优先级去重
                "_id": 0,
            },
        )
        quotes_docs = await cursor.to_list(length=None)

        # 1.5 按 data_source 优先级去重（tushare > sina > baostock > akshare）
        # 同一只股票同一天可能存在多个数据源的记录，只保留优先级最高的一份
        source_priority = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}
        deduped_quotes: dict[str, dict] = {}
        for qd in quotes_docs:
            code = qd.get("code")
            if not code:
                continue
            existing = deduped_quotes.get(code)
            if existing is None:
                deduped_quotes[code] = qd
                continue
            # 比较数据源优先级
            cur_src = qd.get("data_source", "")
            existing_src = existing.get("data_source", "")
            if source_priority.get(cur_src, 0) > source_priority.get(existing_src, 0):
                deduped_quotes[code] = qd

        # 2. 获取股票基础信息（含静态字段：name, industry, market）
        basic_query = {}
        if codes:
            basic_query["code"] = {"$in": codes}
        basic_cursor = db["stock_basic_info"].find(
            basic_query,
            {
                "code": 1,
                "name": 1,
                "industry": 1,
                "market": 1,
                "pe": 1,
                "pb": 1,
                "total_mv": 1,
                "circ_mv": 1,
                "_id": 0,
            },
        )
        basic_docs = await basic_cursor.to_list(length=None)
        basic_map = {d["code"]: d for d in basic_docs if d.get("code")}

        # 3. 合并：行情为主，基础信息补全 name/industry/market/pe/pb/total_mv
        result = {}
        for qd in deduped_quotes.values():
            code = qd.get("code")
            basic = basic_map.get(code, {})
            item = {
                "code": code,
                "name": basic.get("name", ""),
                "industry": basic.get("industry", ""),
                "market": basic.get("market", "主板"),
                "close": qd.get("close"),
                "open": qd.get("open"),
                "high": qd.get("high"),
                "low": qd.get("low"),
                "pct_chg": qd.get("pct_chg"),
                "volume": qd.get("volume"),
                "amount": qd.get("amount"),
                "trade_date": qd.get("trade_date"),
                # 优先取行情中的估值，其次取基础信息中的估值
                "pe": qd.get("pe") or basic.get("pe"),
                "pb": qd.get("pb") or basic.get("pb"),
                "total_mv": qd.get("total_mv") or basic.get("total_mv"),
                "circ_mv": qd.get("circ_mv") or basic.get("circ_mv"),
                "turnover_rate": qd.get("turnover_rate"),
            }
            result[code] = item

        return result

    async def _get_daily_quotes(
        self,
        code: str,
        end_date: str | None = None,
        days: int = 250,
    ) -> list[dict]:
        """
        获取个股日线数据（按日期倒序，最近days天）

        Args:
            code: 股票代码
            end_date: 截止日期 YYYY-MM-DD，默认今天
            days: 获取天数

        Returns:
            按日期正序排列的日线列表
        """
        db = await self._get_db()
        if end_date is None:
            end_date = now_tz().strftime("%Y-%m-%d")

        cursor = db["stock_daily_quotes"].find(
            {
                "code": code,
                "trade_date": {"$lte": end_date},
                "period": "daily",
            },
            {
                "trade_date": 1,
                "open": 1,
                "close": 1,
                "high": 1,
                "low": 1,
                "volume": 1,
                "amount": 1,
                "pct_chg": 1,
                "pre_close": 1,
                "data_source": 1,
                "_id": 0,
            },
        ).sort("trade_date", -1).limit(days)

        docs = await cursor.to_list(length=None)

        # 按data_source优先级去重（tushare > sina > baostock > akshare）
        source_priority = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}
        seen_dates = {}
        for d in docs:
            dt = d.get("trade_date")
            src = d.get("data_source", "")
            if dt not in seen_dates or source_priority.get(
                src, 0
            ) > source_priority.get(seen_dates[dt].get("data_source", ""), 0):
                seen_dates[dt] = d

        result = sorted(seen_dates.values(), key=lambda x: x["trade_date"])
        return result

    async def _batch_get_quotes(
        self,
        codes: list[str],
        end_date: str,
        days: int = 60,
        concurrency: int = 100,
        batch_size: int = 500,
    ) -> dict[str, list[dict]]:
        """
        批量获取多只股票的日线数据（分片并发 $in 查询）

        性能优化：
        1. 将大量 codes 按 batch_size 分片，并发执行多个子查询，
           避免单次超大 $in 查询导致 MongoDB 游标阻塞和内存压力。
        2. 每片内部利用 $in 批量查询，消除 N 次单股查询。

        Args:
            codes: 股票代码列表
            end_date: 截止日期 YYYY-MM-DD
            days: 每只股票获取的最近天数
            concurrency: 并发分片数上限
            batch_size: 每片包含的股票数量
        """
        if not codes:
            return {}

        # 计算日期下界：交易日 days 天约需 days*2 个自然日（含周末），加 30 天缓冲
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except Exception:
            end_dt = now_tz()
        start_lower = (end_dt - timedelta(days=days * 2 + 30)).strftime("%Y-%m-%d")

        # 分片
        chunks = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
        semaphore = asyncio.Semaphore(max(1, concurrency))
        source_priority = {"tushare": 4, "sina": 3, "baostock": 2, "akshare": 1}

        async def _query_chunk(chunk: list[str]) -> dict[str, list[dict]]:
            async with semaphore:
                db = await self._get_db()
                cursor = db["stock_daily_quotes"].find(
                    {
                        "code": {"$in": chunk},
                        "trade_date": {"$lte": end_date, "$gte": start_lower},
                        "period": "daily",
                    },
                    {
                        "trade_date": 1,
                        "code": 1,
                        "open": 1,
                        "close": 1,
                        "high": 1,
                        "low": 1,
                        "volume": 1,
                        "amount": 1,
                        "pct_chg": 1,
                        "pre_close": 1,
                        "data_source": 1,
                        "_id": 0,
                    },
                ).sort("trade_date", -1)

                docs = await cursor.to_list(length=None)

                by_code: dict[str, dict[str, dict]] = {}
                for d in docs:
                    code = d.get("code")
                    if not code:
                        continue
                    bucket = by_code.setdefault(code, {})
                    dt = d.get("trade_date")
                    src = d.get("data_source", "")
                    if dt not in bucket or source_priority.get(
                        src, 0
                    ) > source_priority.get(bucket[dt].get("data_source", ""), 0):
                        bucket[dt] = d

                result: dict[str, list[dict]] = {}
                for code, bucket in by_code.items():
                    sorted_quotes = sorted(
                        bucket.values(), key=lambda x: x["trade_date"], reverse=True
                    )[:days]
                    result[code] = sorted(sorted_quotes, key=lambda x: x["trade_date"])
                return result

        chunk_results = await asyncio.gather(*[_query_chunk(c) for c in chunks])
        merged: dict[str, list[dict]] = {}
        for r in chunk_results:
            merged.update(r)
        return merged

    # ---- 通用工具 ----

    def _calc_ma(self, closes: np.ndarray, period: int) -> float | None:
        """计算均线"""
        if len(closes) < period:
            return None
        return float(np.mean(closes[-period:]))

    def _is_limit_up(self, pct_chg: float, market: str = "主板") -> bool:
        """判断是否涨停"""
        threshold = LIMIT_UP_PCT_KCB if "科创" in market else (
            LIMIT_UP_PCT_CYB if "创业" in market else LIMIT_UP_PCT_MAIN
        )
        return pct_chg >= threshold

    def _is_limit_down(self, pct_chg: float, market: str = "主板") -> bool:
        """判断是否跌停"""
        threshold = LIMIT_DOWN_PCT_KCB if "科创" in market else (
            LIMIT_DOWN_PCT_CYB if "创业" in market else LIMIT_DOWN_PCT_MAIN
        )
        return pct_chg <= threshold

    def _calc_trade_cost(self, amount: float, is_buy: bool) -> float:
        """计算交易成本"""
        commission = max(amount * COMMISSION_RATE, 5.0)  # 佣金最低5元
        stamp_tax = 0.0 if is_buy else amount * STAMP_TAX_RATE
        slippage = amount * SLIPPAGE_RATE
        return commission + stamp_tax + slippage

    # ---- 风险扫描前置过滤 ----

    async def _apply_risk_filter(
        self,
        items: list[dict],
        screening_data: dict[str, dict] | None = None,
    ) -> list[dict]:
        """
        对扫描结果做风险过滤

        策略：
        1. 高风险股票（ST/质押>50%/商誉>50%/财务造假）直接排除
        2. 中低风险股票保留，但在结果中附加 risk_info 字段

        Args:
            items: 扫描结果列表，每项需含 code 字段
            screening_data: 行情数据（可选，用于获取股票名称）

        Returns:
            过滤后的列表（高风险已排除，其余附加 risk_info）
        """
        if not items:
            return items

        try:
            from app.services.retail.risk_scanner import get_risk_scanner

            scanner = get_risk_scanner()

            # 并行扫描：每只股票的风险扫描含多次 akshare 网络请求（I/O 密集），
            # 用 asyncio.gather + 信号量并发执行，替代串行 for 循环阻塞。
            # 信号量控制并发上限，避免数据源限流。
            semaphore = asyncio.Semaphore(10)

            async def scan_one(item: dict) -> tuple[dict, dict | None]:
                code = item.get("code", "")
                if not code:
                    return item, None
                name = item.get("name", "")
                if not name and screening_data:
                    name = screening_data.get(code, {}).get("name", "")
                async with semaphore:
                    try:
                        risk = await scanner.scan_stock_risks_async(code, name)
                        return item, risk
                    except Exception as e:
                        logger.warning(f"风险扫描异常 {code}: {e}")
                        return item, None

            results = await asyncio.gather(*[scan_one(it) for it in items])

            filtered = []
            for item, risk in results:
                if risk is None:
                    # 单只扫描失败：标记 risk_scan_failed 但保留（与整体失败策略一致，避免静默放行未扫描股）
                    item["risk_info"] = {
                        "risk_level": "unknown",
                        "risk_count": 0,
                        "has_high_risk": False,
                        "has_any_risk": False,
                        "risks": [],
                        "risk_scan_failed": True,
                        "message": "该股票风险扫描异常，请谨慎对待",
                    }
                    filtered.append(item)
                    continue

                # 高风险直接排除
                if risk["has_high_risk"]:
                    logger.info(
                        f"⚠️ 风险过滤: 排除 {item.get('code', '')} {item.get('name', '')} - "
                        f"{'; '.join(r['risk_name'] for r in risk['risks'])}"
                    )
                    continue

                # 保留，附加风险信息
                item["risk_info"] = risk
                filtered.append(item)

            excluded = len(items) - len(filtered)
            if excluded > 0:
                logger.info(f"风险过滤: 排除 {excluded} 只高风险股票，剩余 {len(filtered)} 只")

            return filtered

        except Exception as e:
            # 风险扫描失败时，绝不能静默放行未过滤的原始列表（违背"高风险股票必须排除"的约束）
            # 为每个 item 标记 risk_scan_failed，前端据此提示用户"风险未扫描"
            logger.error(f"风险过滤整体失败，标记所有候选为 risk_scan_failed: {e}", exc_info=True)
            for item in items:
                item["risk_info"] = {
                    "risk_level": "unknown",
                    "risk_count": 0,
                    "has_high_risk": False,
                    "has_any_risk": False,
                    "risks": [],
                    "risk_scan_failed": True,
                    "message": "风险扫描服务异常，未完成风险检查，请谨慎对待",
                }
            return items

    # ---- 通用回测引擎 ----

    async def run_backtest(
        self,
        strategy_name: str,
        scan_func,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        通用回测引擎

        Args:
            strategy_name: 策略名称
            scan_func: 异步扫描函数，签名为 scan_func(date_str) -> List[dict]
                       每个 item 需含 code, close, score 字段
            params: 回测参数

        Returns:
            回测结果
        """
        start_time = time.time()
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        hold_days = params.get("hold_days", 20)
        top_n = params.get("top_n", 10)
        initial_capital = params.get("initial_capital", 1000000)
        max_position_pct = params.get("max_position_pct", 0.1)

        if not start_date or not end_date:
            # 默认回测最近1年
            end_dt = now_tz()
            start_dt = end_dt - timedelta(days=365)
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date = end_dt.strftime("%Y-%m-%d")

        # 生成交易日列表（简化：按自然日遍历，跳过周末）
        trade_dates = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        while current <= end_dt:
            if current.weekday() < 5:  # 周一到周五
                trade_dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        if not trade_dates:
            return {"error": "回测日期范围内无交易日"}

        # 回测状态
        capital = initial_capital
        holdings = []  # [{code, buy_price, buy_date, shares, amount, score}]
        all_trades = []
        daily_results = []

        # 按周扫描选股（不是每天扫，减少计算量）
        scan_interval = 5  # 每5个交易日扫描一次
        scan_dates = trade_dates[::scan_interval]

        # ========== 预计算市场环境（每天的上涨股票比例）==========
        logger.info("📊 预计算市场环境数据...")
        market_rise_ratio: dict[str, float] = {}
        for dt in trade_dates:
            try:
                screening_data = await self._get_screening_view_for_date(dt)
                if screening_data:
                    total = len(screening_data)
                    rising = sum(1 for d in screening_data.values() if d.get("pct_chg", 0) > 0)
                    market_rise_ratio[dt] = rising / total if total > 0 else 0.5
                else:
                    market_rise_ratio[dt] = 0.5
            except Exception as e:
                logger.warning(f"计算 {dt} 市场环境失败: {e}")
                market_rise_ratio[dt] = 0.5
        logger.info("✅ 市场环境预计算完成")

        for _i, date_str in enumerate(trade_dates):
            # 1. 检查持仓是否触发卖出
            # 性能优化：单次批量查询所有持仓当日行情，替代逐持仓 N 次查询
            new_holdings = []
            holding_codes = [h["code"] for h in holdings]
            if holding_codes:
                quotes_map = await self._batch_get_quotes(holding_codes, date_str, days=5)
            else:
                quotes_map = {}
            for h in holdings:
                quotes = quotes_map.get(h["code"], [])
                if not quotes:
                    new_holdings.append(h)
                    continue

                current_price = quotes[-1]["close"]
                holding_day_count = 0
                with contextlib.suppress(Exception):
                    holding_day_count = (
                        datetime.strptime(date_str, "%Y-%m-%d")
                        - datetime.strptime(h["buy_date"], "%Y-%m-%d")
                    ).days

                # 卖出条件：到期 或 止损10% 或 止盈30%
                pnl_pct = (current_price - h["buy_price"]) / h["buy_price"]
                should_sell = False
                sell_reason = ""

                if holding_day_count >= hold_days:
                    should_sell = True
                    sell_reason = "到期卖出"
                elif pnl_pct <= -0.10:
                    should_sell = True
                    sell_reason = "止损卖出"
                elif pnl_pct >= 0.30:
                    should_sell = True
                    sell_reason = "止盈卖出"

                if should_sell:
                    sell_amount = current_price * h["shares"]
                    cost = self._calc_trade_cost(sell_amount, is_buy=False)
                    capital += sell_amount - cost
                    all_trades.append({
                        "code": h["code"],
                        "buy_price": h["buy_price"],
                        "sell_price": current_price,
                        "buy_date": h["buy_date"],
                        "sell_date": date_str,
                        "shares": h["shares"],
                        "return_pct": pnl_pct,
                        "sell_reason": sell_reason,
                        "score": h.get("score", 0),
                    })
                else:
                    h["current_price"] = current_price
                    new_holdings.append(h)

            holdings = new_holdings

            # 2. 在扫描日选股买入
            if date_str in scan_dates and capital > initial_capital * 0.1:
                # ========== 市场环境过滤 ==========
                rise_ratio = market_rise_ratio.get(date_str, 0.5)
                
                # 极端熊市（上涨比例<20%）不交易
                if rise_ratio < 0.2:
                    logger.debug(f"📉 {date_str} 市场环境恶劣（上涨比例 {rise_ratio:.1%}），跳过买入")
                    pass  # 不买入，但继续处理卖出
                
                else:
                    try:
                        scan_results = await scan_func(date_str)
                    except Exception as e:
                        logger.warning(f"回测扫描 {date_str} 失败: {e}")
                        scan_results = []

                    # 排序、取top_n（保留评分用于排序，不再用min_score过滤）
                    candidates = sorted(scan_results, key=lambda x: x.get("score", 0), reverse=True)
                    
                    # 弱势环境减半
                    if rise_ratio < 0.4:
                        candidates = candidates[:max(1, int(len(candidates) * 0.5))]
                    
                    candidates = candidates[:top_n]

                    # 买入（每只不超过 max_position_pct 比例）
                    for c in candidates:
                        if len(holdings) >= 30:
                            break
                        code = c.get("code")
                        price = c.get("close") or c.get("price")
                        if not code or not price or price <= 0:
                            continue
                        # 已持有则跳过
                        if any(h["code"] == code for h in holdings):
                            continue

                        max_amount = capital * max_position_pct
                        shares = int(max_amount / price / 100) * 100
                        if shares <= 0:
                            continue

                        buy_amount = shares * price
                        cost = self._calc_trade_cost(buy_amount, is_buy=True)
                        if buy_amount + cost > capital:
                            continue

                        capital -= buy_amount + cost
                        holdings.append({
                            "code": code,
                            "buy_price": price,
                            "buy_date": date_str,
                            "shares": shares,
                            "amount": buy_amount,
                            "score": c.get("score", 0),
                        })

            # 3. 记录每日净值
            holding_value = sum(
                h.get("current_price", h["buy_price"]) * h["shares"]
                for h in holdings
            )
            total_value = capital + holding_value
            daily_results.append({
                "date": date_str,
                "total_value": round(total_value, 2),
                "cash": round(capital, 2),
                "holding_value": round(holding_value, 2),
                "positions": len(holdings),
            })

        # 强制平仓剩余持仓
        for h in holdings:
            current_price = h.get("current_price", h["buy_price"])
            pnl_pct = (current_price - h["buy_price"]) / h["buy_price"]
            sell_amount = current_price * h["shares"]
            cost = self._calc_trade_cost(sell_amount, is_buy=False)
            capital += sell_amount - cost
            all_trades.append({
                "code": h["code"],
                "buy_price": h["buy_price"],
                "sell_price": current_price,
                "buy_date": h["buy_date"],
                "sell_date": trade_dates[-1] if trade_dates else end_date,
                "shares": h["shares"],
                "return_pct": pnl_pct,
                "sell_reason": "回测期末",
                "score": h.get("score", 0),
            })

        # 4. 统计
        final_capital = capital
        total_return = (final_capital - initial_capital) / initial_capital
        total_trades = len(all_trades)
        winning = [t for t in all_trades if t["return_pct"] > 0]
        losing = [t for t in all_trades if t["return_pct"] <= 0]
        win_rate = len(winning) / total_trades if total_trades > 0 else 0
        avg_win = (
            np.mean([t["return_pct"] for t in winning]) if winning else 0
        )
        avg_loss = (
            np.mean([t["return_pct"] for t in losing]) if losing else 0
        )
        profit_loss_ratio = (
            abs(avg_win / avg_loss) if avg_loss != 0 else 0
        )
        avg_return = (
            np.mean([t["return_pct"] for t in all_trades])
            if all_trades
            else 0
        )

        # 最大回撤
        values = [d["total_value"] for d in daily_results]
        max_drawdown = 0
        peak = values[0] if values else initial_capital
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_drawdown:
                max_drawdown = dd

        # 夏普比率（简化：日收益/日波动 * sqrt(252)）
        if len(values) > 1:
            daily_returns = [
                (values[i] - values[i - 1]) / values[i - 1]
                for i in range(1, len(values))
                if values[i - 1] > 0
            ]
            if daily_returns:
                std = np.std(daily_returns)
                sharpe = (
                    (np.mean(daily_returns) / std * np.sqrt(252))
                    if std > 0
                    else 0
                )
            else:
                sharpe = 0
        else:
            sharpe = 0

        # 年化收益
        backtest_days = len(trade_dates)
        annualized_return = (
            ((final_capital / initial_capital) ** (252 / max(backtest_days, 1)) - 1)
            if backtest_days > 0 and initial_capital > 0
            else 0
        )

        # 最大连续亏损
        max_consecutive_losses = 0
        current_streak = 0
        for t in all_trades:
            if t["return_pct"] <= 0:
                current_streak += 1
                max_consecutive_losses = max(
                    max_consecutive_losses, current_streak
                )
            else:
                current_streak = 0

        # 卖出原因统计
        sell_reason_stats = {}
        for t in all_trades:
            reason = t["sell_reason"]
            if reason not in sell_reason_stats:
                sell_reason_stats[reason] = {"count": 0, "win_rate": 0, "avg_return": 0}
            sell_reason_stats[reason]["count"] += 1
        for reason, stats in sell_reason_stats.items():
            reason_trades = [t for t in all_trades if t["sell_reason"] == reason]
            stats["win_rate"] = (
                len([t for t in reason_trades if t["return_pct"] > 0])
                / len(reason_trades)
                if reason_trades
                else 0
            )
            stats["avg_return"] = (
                float(np.mean([t["return_pct"] for t in reason_trades]))
                if reason_trades
                else 0
            )

        # 排序交易记录
        sorted_trades = sorted(all_trades, key=lambda x: x["return_pct"])
        worst_trades = [
            {k: v for k, v in t.items() if k != "score"} for t in sorted_trades[:20]
        ]
        top_trades = [
            {k: v for k, v in t.items() if k != "score"}
            for t in sorted_trades[-20:][::-1]
        ]

        total_fees = sum(
            self._calc_trade_cost(t["buy_price"] * t["shares"], True)
            + self._calc_trade_cost(t["sell_price"] * t["shares"], False)
            for t in all_trades
        )

        took_ms = int((time.time() - start_time) * 1000)

        return {
            "strategy": strategy_name,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 4),
            "avg_return": round(float(avg_return), 4),
            "avg_win": round(float(avg_win), 4),
            "avg_loss": round(float(avg_loss), 4),
            "profit_loss_ratio": round(float(profit_loss_ratio), 4),
            "max_drawdown": round(float(max_drawdown), 4),
            "sharpe_ratio": round(float(sharpe), 4),
            "calmar_ratio": round(
                float(annualized_return / max_drawdown)
                if max_drawdown > 0
                else 0,
                4,
            ),
            "annualized_return": round(float(annualized_return), 4),
            "max_consecutive_losses": max_consecutive_losses,
            "total_fees_est": round(float(total_fees), 2),
            "total_return": round(float(total_return), 4),
            "final_capital": round(float(final_capital), 2),
            "initial_capital": initial_capital,
            "backtest_days": backtest_days,
            "sell_reason_stats": sell_reason_stats,
            "daily_results": daily_results[-50:],
            "top_trades": top_trades,
            "worst_trades": worst_trades,
            "params": params,
            "took_ms": took_ms,
        }
