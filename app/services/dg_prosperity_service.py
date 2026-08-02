"""
ΔG 景气服务

基于 Tushare fina_indicator 接口的季度景气度分析：
- G = q_profit_yoy（单季净利润同比增速）
- ΔG = 当季 G - 上季 G（环比变化）
- 四象限：戴维斯双击(G>0,ΔG>0)、景气见顶(G>0,ΔG<0)、戴维斯双杀(G<0,ΔG<0)、困境反转(G<0,ΔG>0)

数据缓存到 MongoDB `dg_prosperity` 集合，按季度更新。
如果 Tushare 不可用或数据缺失，返回 None，不影响策略运行。
"""

import contextlib
import logging
from datetime import datetime

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)

QUADRANT_LABELS = {
    "double_click": "戴维斯双击",
    "peaking": "景气见顶",
    "double_kill": "戴维斯双杀",
    "reversal": "困境反转",
    "unknown": "数据不足"
}

QUADRANT_COLORS = {
    "double_click": "success",
    "peaking": "warning",
    "double_kill": "danger",
    "reversal": "info",
    "unknown": "info"
}


def classify_quadrant(g: float | None, dg: float | None) -> str:
    """根据 G 和 ΔG 判定景气象限

    Args:
        g: 单季净利润同比增速(%)，如 25.3
        dg: 环比变化(百分点)，如 -10.2

    Returns:
        象限 key: double_click / peaking / double_kill / reversal / unknown
    """
    if g is None or dg is None:
        return "unknown"
    if g > 0 and dg > 0:
        return "double_click"
    elif g > 0 and dg < 0:
        return "peaking"
    elif g < 0 and dg < 0:
        return "double_kill"
    elif g < 0 and dg > 0:
        return "reversal"
    return "unknown"


class DgProsperityService:
    """ΔG 景气分析服务"""

    def __init__(self):
        self.db = None
        self._tushare_pro = None
        self._cache: dict[str, dict] = {}

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _get_tushare_pro(self):
        """获取 Tushare pro 接口"""
        if self._tushare_pro is not None:
            return self._tushare_pro
        try:
            import os

            import tushare as ts
            token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")
            if not token:
                return None
            ts.set_token(token)
            self._tushare_pro = ts.pro_api()
            return self._tushare_pro
        except Exception as e:
            logger.warning(f"[DgProsperity] Tushare 初始化失败: {e}")
            return None

    async def get_quadrant_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量获取多只股票的 ΔG 象限数据

        Args:
            codes: 股票代码列表（6 位）

        Returns:
            {code: {quadrant, g, dg, report_period, sector}} 字典
        """
        db = await self._get_db()
        collection = db["dg_prosperity"]

        codes_str = [str(c).zfill(6) for c in codes]

        # 批量查 MongoDB 缓存
        try:
            cursor = collection.find({"code": {"$in": codes_str}})
            docs = await cursor.to_list(length=len(codes_str) * 4)
        except Exception as e:
            logger.warning(f"[DgProsperity] 查缓存失败: {e}")
            return {c: self._empty_quadrant() for c in codes_str}

        # 按 code 取最新季度
        latest: dict[str, dict] = {}
        for doc in docs:
            code = doc.get("code", "")
            period = doc.get("report_period", "")
            if code not in latest or period > latest[code].get("report_period", ""):
                latest[code] = doc

        result = {}
        for code in codes_str:
            if code in latest:
                doc = latest[code]
                g = doc.get("g")
                dg = doc.get("dg")
                q = classify_quadrant(g, dg)
                result[code] = {
                    "quadrant": q,
                    "quadrant_label": QUADRANT_LABELS.get(q, "未知"),
                    "quadrant_color": QUADRANT_COLORS.get(q, "info"),
                    "g": g,
                    "dg": dg,
                    "report_period": doc.get("report_period", ""),
                    "available": True
                }
            else:
                result[code] = self._empty_quadrant()

        return result

    def _empty_quadrant(self) -> dict:
        return {
            "quadrant": "unknown",
            "quadrant_label": "数据不足",
            "quadrant_color": "info",
            "g": None,
            "dg": None,
            "report_period": "",
            "available": False
        }

    async def refresh_quarterly(self, codes: list[str] | None = None) -> dict:
        """季度刷新 ΔG 数据（从 Tushare fina_indicator 拉取）

        Args:
            codes: 股票代码列表，None 表示全 A 股

        Returns:
            {updated_count, failed_count, total_count}
        """
        pro = self._get_tushare_pro()
        if pro is None:
            return {"updated_count": 0, "failed_count": 0, "total_count": 0, "error": "Tushare 不可用"}

        db = await self._get_db()
        collection = db["dg_prosperity"]

        # 获取股票列表
        if codes is None:
            stock_coll = db["stock_basic_info"]
            cursor = stock_coll.find(
                {
                    "$or": [
                        {"category": "stock_cn"},
                        {"sse": {"$in": ["上海证券交易所", "深圳证券交易所", "上交所", "深交所"]}}
                    ]
                },
                projection={"_id": 0, "code": 1}
            )
            stock_docs = await cursor.to_list(length=6000)
            codes = [s.get("code", "") for s in stock_docs if s.get("code")]

        if not codes:
            return {"updated_count": 0, "failed_count": 0, "total_count": 0, "error": "无股票代码"}

        # 最近 8 个季度（2 年）
        today = datetime.now()
        quarters = []
        for _i in range(8):
            q_date = today
            while q_date.month not in (3, 6, 9, 12):
                q_date = q_date.replace(day=1)
                from datetime import timedelta
                q_date = q_date - timedelta(days=1)
            if q_date.month == 12:
                period = f"{q_date.year}Q4"
            elif q_date.month == 9:
                period = f"{q_date.year}Q3"
            elif q_date.month == 6:
                period = f"{q_date.year}Q2"
            else:
                period = f"{q_date.year}Q1"
            if period not in quarters:
                quarters.append(period)
            q_date = q_date.replace(day=1)
            from datetime import timedelta
            q_date = q_date - timedelta(days=1)

        updated = 0
        failed = 0

        # 按季度批量拉取（Tushare fina_indicator 按 code 或 period 批量）
        try:
            for period in quarters:
                period.replace("Q", "")
                # 构造 Tushare 的 period 格式：20240930 等
                end_dates = {
                    "Q1": "0331",
                    "Q2": "0630",
                    "Q3": "0930",
                    "Q4": "1231"
                }
                q_label = period[-2:]
                y = period[:4]
                end_date = f"{y}{end_dates.get(q_label, '1231')}"

                try:
                    df = pro.fina_indicator(period=end_date, fields='ts_code,end_date,q_profit_yoy')
                    if df is None or len(df) == 0:
                        continue

                    for _, row in df.iterrows():
                        ts_code = row.get("ts_code", "")
                        code = ts_code.split(".")[0] if "." in ts_code else ts_code
                        if len(code) != 6:
                            continue
                        g = row.get("q_profit_yoy")
                        if g is None:
                            continue

                        # 计算 ΔG 需要上一个季度的数据，先存进去
                        await collection.update_one(
                            {"code": code, "report_period": period},
                            {"$set": {"code": code, "report_period": period, "g": float(g), "updated_at": datetime.now().isoformat()}},
                            upsert=True
                        )
                        updated += 1
                except Exception as e:
                    logger.warning(f"[DgProsperity] 拉取 {period} 失败: {e}")
                    failed += 1

            # 第二遍：计算 ΔG（环比差值）
            await self._compute_dg_for_all()

        except Exception as e:
            logger.error(f"[DgProsperity] 季度刷新失败: {e}", exc_info=True)

        return {
            "updated_count": updated,
            "failed_count": failed,
            "total_count": len(codes),
            "quarters": quarters
        }

    async def _compute_dg_for_all(self):
        """计算所有股票的 ΔG（当季 G - 上季 G）"""
        db = await self._get_db()
        collection = db["dg_prosperity"]

        # 获取所有唯一 code
        try:
            codes = await collection.distinct("code")
        except Exception:
            return

        for code in codes:
            try:
                cursor = collection.find({"code": code}).sort("report_period", 1)
                docs = await cursor.to_list(length=20)
            except Exception:
                continue

            if len(docs) < 2:
                continue

            docs_sorted = sorted(docs, key=lambda d: d.get("report_period", ""))
            for i in range(1, len(docs_sorted)):
                prev_g = docs_sorted[i - 1].get("g")
                curr_g = docs_sorted[i].get("g")
                if prev_g is not None and curr_g is not None:
                    dg = curr_g - prev_g
                    with contextlib.suppress(Exception):
                        await collection.update_one(
                            {"_id": docs_sorted[i]["_id"]},
                            {"$set": {"dg": float(dg)}}
                        )

    async def get_sector_dg(self, industry: str) -> dict:
        """获取行业平均 ΔG（宏观层面判断）"""
        # 简化实现：返回空
        return self._empty_quadrant()


_dg_service_instance: DgProsperityService | None = None


def get_dg_prosperity_service() -> DgProsperityService:
    """获取单例"""
    global _dg_service_instance
    if _dg_service_instance is None:
        _dg_service_instance = DgProsperityService()
    return _dg_service_instance
