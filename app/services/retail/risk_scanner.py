"""
散户风险扫描器

系统核心价值：帮散户"不亏大钱"。在选股策略筛出候选后，做前置风险过滤，
排除地雷股。

5类风险扫描：
1. 财务造假风险：应收账款异常、存货异常、现金流背离
2. 商誉减值风险：商誉/净资产占比过高
3. 质押爆仓风险：大股东质押比例过高
4. 退市风险：ST、连续亏损
5. 解禁减持风险：近期限售解禁规模大

数据源：
- akshare stock_gpzy_pledge_ratio_em（全市场质押比例，批量）
- akshare stock_financial_abstract_ths（财务摘要，单股）
- akshare stock_financial_debt_ths（资产负债表，单股，含商誉/应收/存货）
- akshare stock_zh_a_st_em（ST股列表，批量，不稳定时降级）

缓存策略：质押/ST数据1天，财务数据1天。
"""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services import vibe_astock as astock
from app.services.cache_layer import cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 风险等级
# ---------------------------------------------------------------------------
RISK_LEVEL_HIGH = "high"       # 高风险，必须排除
RISK_LEVEL_MEDIUM = "medium"   # 中风险，警告
RISK_LEVEL_LOW = "low"        # 低风险，提示

# ---------------------------------------------------------------------------
# 阈值参数
# ---------------------------------------------------------------------------
# 质押风险阈值（质押比例 > 50% 为高风险）
PLEDGE_RATIO_HIGH = 50.0
PLEDGE_RATIO_MEDIUM = 30.0

# 商誉风险阈值（商誉/净资产 > 50% 为高风险）
GOODWILL_RATIO_HIGH = 0.50
GOODWILL_RATIO_MEDIUM = 0.30

# 应收账款风险（应收账款/总资产 > 25% 或 周转天数 > 180天）
RECEIVABLE_RATIO_HIGH = 0.25
RECEIVABLE_DAYS_HIGH = 180

# 存货风险（存货/总资产 > 40%）
INVENTORY_RATIO_HIGH = 0.40

# 现金流背离（净利润 > 0 但经营现金流 < 0，且 |经营现金流| > |净利润| * 0.5）
CASHFLOW_DIVERGENCE_RATIO = 0.5

# 连续亏损年数（>= 2 年为高风险）
CONSECUTIVE_LOSS_YEARS = 2


def _safe_float(v, default=0.0) -> float:
    """安全转换为 float，处理百分比字符串"""
    try:
        if v is None or (isinstance(v, str) and v.strip() in ("", "-", "False")):
            return default
        if isinstance(v, str):
            v = v.replace("%", "").replace(",", "").replace("亿", "").strip()
        val = float(v)
        if pd.isna(val):
            return default
        return val
    except (ValueError, TypeError):
        return default


def _parse_amount(v) -> float:
    """解析带单位的金额（亿/万），返回原始数值"""
    try:
        if v is None or (isinstance(v, str) and v.strip() in ("", "-", "False")):
            return 0.0
        s = str(v).strip()
        if s.endswith("亿"):
            return float(s.replace("亿", "")) * 1e8
        if s.endswith("万"):
            return float(s.replace("万", "")) * 1e4
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


class RiskScanner:
    """散户风险扫描器"""

    def __init__(self):
        self._pledge_cache: Optional[pd.DataFrame] = None
        self._pledge_cache_time: float = 0
        self._st_codes_cache: Optional[set] = None
        self._st_cache_time: float = 0

    # ------------------------------------------------------------------
    # 批量数据获取（带缓存）
    # ------------------------------------------------------------------

    def _get_pledge_data(self) -> pd.DataFrame:
        """获取全市场质押比例数据（缓存1天）"""
        now = time.time()
        if (
            self._pledge_cache is not None
            and not self._pledge_cache.empty
            and now - self._pledge_cache_time < 86400
        ):
            return self._pledge_cache

        try:
            ak = astock._akshare()
            # 用最近的季末日期
            today = date.today()
            quarter_ends = [
                f"{today.year}1231" if today.month >= 12 else f"{today.year - 1}1231",
                f"{today.year}0930" if today.month >= 9 else f"{today.year - 1}0930",
                f"{today.year}0630" if today.month >= 6 else f"{today.year - 1}0630",
            ]
            for d in quarter_ends:
                try:
                    df = ak.stock_gpzy_pledge_ratio_em(date=d)
                    if df is not None and not df.empty:
                        self._pledge_cache = df
                        self._pledge_cache_time = now
                        logger.info(f"获取质押数据成功: {len(df)} 条 (date={d})")
                        return df
                except Exception:
                    continue

            logger.warning("质押数据获取失败，所有季度日期均无数据")
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"获取质押数据失败: {e}")
            return pd.DataFrame()

    def _get_st_codes(self) -> set:
        """获取ST股代码集合（缓存1天，失败时降级）"""
        now = time.time()
        if (
            self._st_codes_cache is not None
            and now - self._st_cache_time < 86400
        ):
            return self._st_codes_cache

        st_codes = set()
        try:
            ak = astock._akshare()
            df = ak.stock_zh_a_st_em()
            if df is not None and not df.empty:
                code_col = "代码" if "代码" in df.columns else df.columns[1]
                st_codes = set(str(c).zfill(6) for c in df[code_col].tolist())
                logger.info(f"获取ST股列表成功: {len(st_codes)} 只")
        except Exception as e:
            logger.warning(f"获取ST股列表失败（将降级为名称过滤）: {e}")

        self._st_codes_cache = st_codes
        self._st_cache_time = now
        return st_codes

    def _get_financial_abstract(self, code: str) -> dict:
        """获取财务摘要（单股，含周转率/资产负债率等）"""
        try:
            data = astock.financials(code)
            return data if data else {}
        except Exception as e:
            logger.debug(f"获取{code}财务摘要失败: {e}")
            return {}

    def _get_balance_sheet(self, code: str) -> dict:
        """获取资产负债表数据（单股，含商誉/应收/存货）"""
        try:
            ak = astock._akshare()
            df = ak.stock_financial_debt_ths(symbol=code, indicator="按报告期")
            if df is None or df.empty:
                return {}
            row = df.iloc[0].to_dict()  # 最新一期

            def _g(keys: List[str]) -> Optional[str]:
                for k in keys:
                    if k in row and row[k] not in (None, "", "False"):
                        return row[k]
                return None

            result = {
                "period": row.get("报告期"),
                # 净资产
                "equity": _g(["*归属于母公司所有者权益合计", "归属于母公司所有者权益合计",
                              "*所有者权益（或股东权益）合计"]),
                # 应收账款
                "receivables": _g(["应收账款", "应收票据及应收账款"]),
                # 存货
                "inventory": _g(["存货"]),
                # 商誉（动态列，不一定存在）
                "goodwill": _g(["商誉"]),
                # 总资产
                "total_assets": _g(["*资产合计", "资产合计"]),
            }
            return result
        except Exception as e:
            logger.debug(f"获取{code}资产负债表失败: {e}")
            return {}

    # ------------------------------------------------------------------
    # 5类风险扫描
    # ------------------------------------------------------------------

    def _scan_fraud_risk(self, code: str, abstract: dict, balance: dict) -> Optional[dict]:
        """
        财务造假风险识别

        三个信号：
        1. 应收账款/总资产 > 25%（收入虚增嫌疑）
        2. 存货/总资产 > 40%（存货积压或虚增）
        3. 现金流背离：净利润>0 但经营现金流<0
        """
        signals = []

        # 信号1：应收账款占比过高
        total_assets_str = balance.get("total_assets")
        receivables_str = balance.get("receivables")
        if total_assets_str and receivables_str:
            total_assets = _parse_amount(total_assets_str)
            receivables = _parse_amount(receivables_str)
            if total_assets > 0:
                recv_ratio = receivables / total_assets
                if recv_ratio >= RECEIVABLE_RATIO_HIGH:
                    signals.append({
                        "type": "high_receivables",
                        "message": f"应收账款占总资产 {recv_ratio*100:.1f}%（阈值{RECEIVABLE_RATIO_HIGH*100:.0f}%），存在收入虚增嫌疑",
                    })

        # 信号2：存货占比过高
        inventory_str = balance.get("inventory")
        if total_assets_str and inventory_str:
            total_assets = _parse_amount(total_assets_str)
            inventory = _parse_amount(inventory_str)
            if total_assets > 0:
                inv_ratio = inventory / total_assets
                if inv_ratio >= INVENTORY_RATIO_HIGH:
                    signals.append({
                        "type": "high_inventory",
                        "message": f"存货占总资产 {inv_ratio*100:.1f}%（阈值{INVENTORY_RATIO_HIGH*100:.0f}%），存货积压或虚增",
                    })

        # 信号3：现金流背离（净利润>0 但 经营现金流<0）
        net_profit = abstract.get("net_profit")
        op_cf_ps = abstract.get("op_cf_ps")  # 每股经营现金流
        if net_profit and op_cf_ps is not None:
            np_val = _safe_float(net_profit)
            cf_val = _safe_float(op_cf_ps)
            if np_val > 0 and cf_val < 0:
                signals.append({
                    "type": "cashflow_divergence",
                    "message": f"净利润为正({np_val})但经营现金流为负({cf_val})，利润质量存疑",
                })

        # 信号4：应收账款周转天数过长
        recv_days = abstract.get("应收账款周转天数")
        if recv_days:
            days = _safe_float(recv_days)
            if days > RECEIVABLE_DAYS_HIGH:
                signals.append({
                    "type": "slow_receivables",
                    "message": f"应收账款周转天数 {days:.0f} 天（阈值{RECEIVABLE_DAYS_HIGH}天），回款能力差",
                })

        if not signals:
            return None

        level = RISK_LEVEL_HIGH if len(signals) >= 2 else RISK_LEVEL_MEDIUM
        return {
            "risk_type": "fraud",
            "risk_name": "财务造假风险",
            "level": level,
            "signals": signals,
            "message": "；".join(s["message"] for s in signals),
        }

    def _scan_goodwill_risk(self, code: str, balance: dict) -> Optional[dict]:
        """
        商誉减值风险

        商誉/净资产 > 50% 为高风险（一旦减值将大幅冲击利润）
        商誉/净资产 > 30% 为中风险
        """
        goodwill_str = balance.get("goodwill")
        equity_str = balance.get("equity")

        if not goodwill_str or not equity_str:
            return None

        goodwill = _parse_amount(goodwill_str)
        equity = _parse_amount(equity_str)

        if equity <= 0 or goodwill <= 0:
            return None

        gw_ratio = goodwill / equity

        if gw_ratio >= GOODWILL_RATIO_HIGH:
            level = RISK_LEVEL_HIGH
        elif gw_ratio >= GOODWILL_RATIO_MEDIUM:
            level = RISK_LEVEL_MEDIUM
        else:
            return None

        return {
            "risk_type": "goodwill",
            "risk_name": "商誉减值风险",
            "level": level,
            "signals": [{
                "type": "high_goodwill",
                "message": f"商誉 {goodwill/1e8:.1f}亿 / 净资产 {equity/1e8:.1f}亿 = {gw_ratio*100:.1f}%（阈值{GOODWILL_RATIO_HIGH*100:.0f}%）",
                "goodwill_ratio": round(gw_ratio, 4),
            }],
            "message": f"商誉占净资产 {gw_ratio*100:.1f}%，减值将大幅冲击利润",
        }

    def _scan_pledge_risk(self, code: str) -> Optional[dict]:
        """
        大股东质押爆仓风险

        质押比例 > 50% 为高风险（股价下跌易触发平仓）
        质押比例 > 30% 为中风险
        """
        df = self._get_pledge_data()
        if df.empty:
            return None

        # 股票代码统一为6位
        code_clean = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

        try:
            row = df[df["股票代码"].astype(str).str.zfill(6) == code_clean]
            if row.empty:
                return None

            pledge_ratio = _safe_float(row.iloc[0].get("质押比例", 0))
            if pledge_ratio <= 0:
                return None

            if pledge_ratio >= PLEDGE_RATIO_HIGH:
                level = RISK_LEVEL_HIGH
            elif pledge_ratio >= PLEDGE_RATIO_MEDIUM:
                level = RISK_LEVEL_MEDIUM
            else:
                return None

            return {
                "risk_type": "pledge",
                "risk_name": "质押爆仓风险",
                "level": level,
                "signals": [{
                    "type": "high_pledge",
                    "message": f"质押比例 {pledge_ratio:.1f}%（阈值{PLEDGE_RATIO_HIGH:.0f}%），股价下跌易触发平仓",
                    "pledge_ratio": pledge_ratio,
                }],
                "message": f"大股东质押比例 {pledge_ratio:.1f}%，爆仓风险高",
            }
        except Exception as e:
            logger.debug(f"扫描{code}质押风险失败: {e}")
            return None

    def _scan_delisting_risk(self, code: str, stock_name: str = "") -> Optional[dict]:
        """
        退市风险

        1. ST股（名称含 ST/*ST）
        2. 连续亏损（最近2年净利润为负）
        """
        signals = []

        # 信号1：ST股（优先用ST列表，降级用名称）
        st_codes = self._get_st_codes()
        code_clean = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

        is_st = code_clean in st_codes if st_codes else False
        # 降级：用名称判断
        if not is_st and stock_name:
            is_st = "ST" in stock_name or "*ST" in stock_name

        if is_st:
            signals.append({
                "type": "st_stock",
                "message": f"{'*ST' if '*' in (stock_name or '') else 'ST'}股，存在退市风险",
            })

        # 信号2：连续亏损（需要财务数据）
        try:
            abstract = self._get_financial_abstract(code)
            if abstract:
                net_profit = _safe_float(abstract.get("net_profit"))
                np_yoy = _safe_float(abstract.get("net_profit_yoy"))
                # 如果净利润为负，且同比也为负（持续亏损）
                if net_profit < 0 and np_yoy < 0:
                    signals.append({
                        "type": "consecutive_loss",
                        "message": f"净利润 {net_profit} 且同比下降 {np_yoy}%，持续亏损",
                    })
        except Exception:
            pass

        if not signals:
            return None

        # ST或连续亏损都是高风险
        return {
            "risk_type": "delisting",
            "risk_name": "退市风险",
            "level": RISK_LEVEL_HIGH,
            "signals": signals,
            "message": "；".join(s["message"] for s in signals),
        }

    def _scan_lockup_risk(self, code: str) -> Optional[dict]:
        """
        解禁减持风险

        注：akshare 个股解禁接口不稳定，降级为板块解禁规模判断。
        当近期全市场解禁规模较大时，对所有股票发出中等风险提示。
        """
        try:
            ak = astock._akshare()
            # 获取近期解禁数据（按板块汇总）
            df = ak.stock_restricted_release_summary_em(symbol="全部")
            if df is None or df.empty:
                return None

            # 最近30天内的解禁数据
            today = date.today()
            df["解禁时间"] = pd.to_datetime(df["解禁时间"]).dt.date
            recent = df[(df["解禁时间"] >= today) & (df["解禁时间"] <= today + timedelta(days=90))]

            if recent.empty:
                return None

            total_value = recent["实际解禁市值"].sum()
            # 如果未来90天解禁市值 > 5000亿，市场整体解禁压力较大
            if total_value > 5e11:
                return {
                    "risk_type": "lockup",
                    "risk_name": "解禁减持风险",
                    "level": RISK_LEVEL_LOW,
                    "signals": [{
                        "type": "market_lockup_pressure",
                        "message": f"未来90天全市场解禁市值 {total_value/1e8:.0f}亿，市场整体解禁压力较大",
                    }],
                    "message": "市场处于解禁高峰期，注意个股解禁减持风险",
                }
        except Exception as e:
            logger.debug(f"扫描{code}解禁风险失败: {e}")

        return None

    # ------------------------------------------------------------------
    # 统一扫描入口
    # ------------------------------------------------------------------

    def scan_stock_risks(self, code: str, stock_name: str = "") -> dict:
        """
        扫描单只股票的所有风险（同步入口）

        Returns:
            {
                "code": "600519",
                "name": "贵州茅台",
                "risk_count": 0,
                "has_high_risk": False,
                "has_any_risk": False,
                "risk_level": "safe",
                "risks": [...],
            }
        """
        risks = []

        # 获取财务数据（用于多个风险扫描）
        abstract = self._get_financial_abstract(code)
        balance = self._get_balance_sheet(code)

        # 1. 退市风险（含ST + 连续亏损）
        delisting = self._scan_delisting_risk(code, stock_name)
        if delisting:
            risks.append(delisting)

        # 2. 质押爆仓风险
        pledge = self._scan_pledge_risk(code)
        if pledge:
            risks.append(pledge)

        # 3. 商誉减值风险
        goodwill = self._scan_goodwill_risk(code, balance)
        if goodwill:
            risks.append(goodwill)

        # 4. 财务造假风险
        fraud = self._scan_fraud_risk(code, abstract, balance)
        if fraud:
            risks.append(fraud)

        # 5. 解禁减持风险（市场级别）
        lockup = self._scan_lockup_risk(code)
        if lockup:
            risks.append(lockup)

        has_high = any(r["level"] == RISK_LEVEL_HIGH for r in risks)
        risk_level = "high" if has_high else ("medium" if risks else "safe")

        return {
            "code": code,
            "name": stock_name,
            "risk_count": len(risks),
            "has_high_risk": has_high,
            "has_any_risk": len(risks) > 0,
            "risk_level": risk_level,
            "risks": risks,
        }

    async def scan_stock_risks_async(self, code: str, stock_name: str = "") -> dict:
        """异步入口"""
        return await asyncio.to_thread(self.scan_stock_risks, code, stock_name)

    def filter_risky_stocks(
        self, stocks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, dict]]:
        """
        批量过滤高风险股票

        Args:
            stocks: [{"code": "600519", "name": "贵州茅台", ...}, ...]

        Returns:
            (safe_stocks, risk_details)
            safe_stocks: 无高风险的股票列表
            risk_details: {code: risk_scan_result} 所有股票的风险详情
        """
        safe_stocks = []
        risk_details = {}

        for stock in stocks:
            code = stock.get("code", "")
            name = stock.get("name", "")
            if not code:
                continue

            risk = self.scan_stock_risks(code, name)
            risk_details[code] = risk

            if not risk["has_high_risk"]:
                safe_stocks.append(stock)

        return safe_stocks, risk_details

    async def filter_risky_stocks_async(
        self, stocks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, dict]]:
        """异步批量过滤"""
        return await asyncio.to_thread(self.filter_risky_stocks, stocks)


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_scanner: Optional[RiskScanner] = None


def get_risk_scanner() -> RiskScanner:
    global _scanner
    if _scanner is None:
        _scanner = RiskScanner()
    return _scanner
