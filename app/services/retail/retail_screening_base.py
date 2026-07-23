"""
散户策略选股共享基础服务

提供4个散户策略共用的基础设施：
- 数据获取（stock_basic_info / stock_daily_quotes / stock_screening_view）
- 回测引擎（通用回测框架，避免幸存者偏差/未来函数/流动性/交易成本4个陷阱）
- 通用工具函数
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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

    async def _get_stock_list(self, force_refresh: bool = False) -> List[dict]:
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
        self, codes: Optional[List[str]] = None
    ) -> Dict[str, dict]:
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

    async def _get_daily_quotes(
        self,
        code: str,
        end_date: Optional[str] = None,
        days: int = 250,
    ) -> List[dict]:
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
            end_date = datetime.now().strftime("%Y-%m-%d")

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
        codes: List[str],
        end_date: str,
        days: int = 60,
        concurrency: int = 100,
    ) -> Dict[str, List[dict]]:
        """批量获取多只股票的日线数据"""
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_one(code: str) -> Tuple[str, List[dict]]:
            async with semaphore:
                try:
                    quotes = await self._get_daily_quotes(code, end_date, days)
                    return code, quotes
                except Exception as e:
                    logger.debug(f"获取 {code} 日线失败: {e}")
                    return code, []

        tasks = [fetch_one(c) for c in codes]
        results = await asyncio.gather(*tasks)
        return {code: quotes for code, quotes in results}

    # ---- 通用工具 ----

    def _calc_ma(self, closes: np.ndarray, period: int) -> Optional[float]:
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

    # ---- 通用回测引擎 ----

    async def run_backtest(
        self,
        strategy_name: str,
        scan_func,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
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
        min_score = params.get("min_score", 0)

        if not start_date or not end_date:
            # 默认回测最近1年
            end_dt = datetime.now()
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

        for i, date_str in enumerate(trade_dates):
            # 1. 检查持仓是否触发卖出
            new_holdings = []
            for h in holdings:
                quotes = await self._get_daily_quotes(h["code"], date_str, 5)
                if not quotes:
                    new_holdings.append(h)
                    continue

                current_price = quotes[-1]["close"]
                holding_day_count = 0
                try:
                    holding_day_count = (
                        datetime.strptime(date_str, "%Y-%m-%d")
                        - datetime.strptime(h["buy_date"], "%Y-%m-%d")
                    ).days
                except Exception:
                    pass

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
                try:
                    scan_results = await scan_func(date_str)
                except Exception as e:
                    logger.warning(f"回测扫描 {date_str} 失败: {e}")
                    scan_results = []

                # 过滤评分、排序、取top_n
                candidates = [
                    s for s in scan_results if s.get("score", 0) >= min_score
                ]
                candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
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
