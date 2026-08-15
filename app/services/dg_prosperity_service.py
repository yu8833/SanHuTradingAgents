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
import math
import time
from datetime import datetime

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


def _finite(v):
    """返回有限数值（过滤 NaN/±inf），非有限或 None 返回 False。"""
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _delta(curr, prev):
    """计算两个有限数值之差（百分点）。任一非有限或缺失返回 None。"""
    if not _finite(curr) or not _finite(prev):
        return None
    return float(curr) - float(prev)


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
        self._cache_ts: dict[str, float] = {}
        # 行业 ΔG 基于季度财务数据，短期内不变；10 分钟 TTL 足以避免候选池/行业筛选重复计算
        self._cache_ttl = 600

    def _sector_dg_cache_get(self, industry: str) -> dict | None:
        ts = self._cache_ts.get(industry)
        if ts is None:
            return None
        if time.monotonic() - ts > self._cache_ttl:
            self._cache.pop(industry, None)
            self._cache_ts.pop(industry, None)
            return None
        return self._cache.get(industry)

    def _sector_dg_cache_set(self, industry: str, value: dict) -> None:
        # 行业数有限（~190 细类），超过阈值时清掉最旧一半防止无限增长
        if len(self._cache) >= 500 and industry not in self._cache:
            for k in list(self._cache)[: len(self._cache) // 2]:
                self._cache.pop(k, None)
                self._cache_ts.pop(k, None)
        self._cache[industry] = value
        self._cache_ts[industry] = time.monotonic()

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

        # 使用聚合管道按 code 分组取最新季度（避免 to_list length 限制导致数据遗漏）
        try:
            pipeline = [
                {"$match": {"code": {"$in": codes_str}}},
                {"$sort": {"report_period": -1}},
                {"$group": {
                    "_id": "$code",
                    "g": {"$first": "$g"},
                    "dg": {"$first": "$dg"},
                    "report_period": {"$first": "$report_period"}
                }}
            ]
            cursor = collection.aggregate(pipeline)
            docs = await cursor.to_list(length=len(codes_str))
        except Exception as e:
            logger.warning(f"[DgProsperity] 查缓存失败: {e}")
            return {c: self._empty_quadrant() for c in codes_str}

        latest: dict[str, dict] = {}
        for doc in docs:
            code = doc.get("_id", "")
            if code:
                latest[code] = doc

        result = {}
        for code in codes_str:
            if code in latest:
                doc = latest[code]
                g = doc.get("g")
                dg = doc.get("dg")
                or_yoy = doc.get("or_yoy")
                d_or_yoy = doc.get("d_or_yoy")
                roe = doc.get("roe")
                d_roe = doc.get("d_roe")
                # 过滤非有限值：NaN/±inf 无法 JSON 序列化，且会污染聚合/象限判定
                if not _finite(g):
                    g = None
                if not _finite(dg):
                    dg = None
                if not _finite(or_yoy):
                    or_yoy = None
                if not _finite(d_or_yoy):
                    d_or_yoy = None
                if not _finite(roe):
                    roe = None
                if not _finite(d_roe):
                    d_roe = None
                q = classify_quadrant(g, dg)
                result[code] = {
                    "quadrant": q,
                    "quadrant_label": QUADRANT_LABELS.get(q, "未知"),
                    "quadrant_color": QUADRANT_COLORS.get(q, "info"),
                    "g": g,
                    "dg": dg,
                    "or_yoy": or_yoy,
                    "d_or_yoy": d_or_yoy,
                    "roe": roe,
                    "d_roe": d_roe,
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
            "or_yoy": None,
            "d_or_yoy": None,
            "roe": None,
            "d_roe": None,
            "report_period": "",
            "available": False
        }

    async def refresh_quarterly(self, codes: list[str] | None = None) -> dict:
        """季度刷新 ΔG 数据（从 Tushare fina_indicator 拉取）

        Tushare 标准权限下 fina_indicator 接口必须传 ts_code，因此按股票代码
        并发查询（限制并发数避免触发频率限制），每只股票拉取最近 8 个季度。

        Args:
            codes: 股票代码列表，None 表示全 A 股

        Returns:
            {updated_count, failed_count, total_count, quarters}
        """
        import asyncio
        from datetime import timedelta

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

        # 计算最近 8 个季度的 period 列表（如 2026Q2, 2026Q1, 2025Q4, ...）
        today = datetime.now()
        quarters = []
        q_date = today
        for _i in range(8):
            # 回退到最近的季末月
            while q_date.month not in (3, 6, 9, 12):
                q_date = q_date.replace(day=1) - timedelta(days=1)
            period = f"{q_date.year}Q{(q_date.month // 3)}"
            if period not in quarters:
                quarters.append(period)
            # 继续回退到上一个季度
            q_date = q_date.replace(day=1) - timedelta(days=1)

        # Tushare period 格式：20240930 等
        end_dates = {"Q1": "0331", "Q2": "0630", "Q3": "0930", "Q4": "1231"}
        tushare_periods = []
        for period in quarters:
            q_label = period[-2:]
            y = period[:4]
            tushare_periods.append(f"{y}{end_dates.get(q_label, '1231')}")

        updated = 0
        failed = 0

        # 代码 → ts_code 映射（需要交易所后缀）
        # 沪市: 6开头 → .SH, 深市: 0/3开头 → .SZ, 北交所: 8/4开头 → .BJ
        def code_to_ts_code(code: str) -> str:
            c = str(code).zfill(6)
            if c.startswith(('60', '68', '90', '11', '13')):
                return f"{c}.SH"
            elif c.startswith(('8', '4', '92')):
                return f"{c}.BJ"
            else:
                return f"{c}.SZ"

        # 并发拉取（限制并发数，避免 Tushare 频率限制）
        semaphore = asyncio.Semaphore(10)

        async def fetch_one(code: str):
            nonlocal updated, failed
            async with semaphore:
                ts_code = code_to_ts_code(code)
                try:
                    # 拉取该股票最近8个季度的财务指标
                    df = pro.fina_indicator(
                        ts_code=ts_code,
                        fields='ts_code,end_date,q_profit_yoy,or_yoy,roe'
                    )
                    if df is None or len(df) == 0:
                        return

                    for _, row in df.iterrows():
                        end_date_str = str(row.get("end_date", ""))
                        g = row.get("q_profit_yoy")
                        if g is None or not end_date_str:
                            continue

                        # 将 end_date(20240930) 转为 period(2024Q3)
                        y = end_date_str[:4]
                        md = end_date_str[4:]
                        q_map = {"0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Q4"}
                        period = f"{y}{q_map.get(md, 'Q4')}"

                        set_fields = {
                            "code": code,
                            "report_period": period,
                            "ts_code": ts_code,
                            "updated_at": datetime.now().isoformat()
                        }
                        # 仅写入有限数值，避免 NaN/±inf 污染 Δ 计算
                        if _finite(g):
                            set_fields["g"] = float(g)
                        or_yoy = row.get("or_yoy")
                        if _finite(or_yoy):
                            set_fields["or_yoy"] = float(or_yoy)
                        roe = row.get("roe")
                        if _finite(roe):
                            set_fields["roe"] = float(roe)

                        await collection.update_one(
                            {"code": code, "report_period": period},
                            {"$set": set_fields},
                            upsert=True
                        )
                        updated += 1
                except Exception as e:
                    failed += 1
                    if failed <= 5:
                        logger.warning(f"[DgProsperity] 拉取 {ts_code} 失败: {e}")

        # 分批处理，避免内存问题
        batch_size = 200
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            await asyncio.gather(*[fetch_one(c) for c in batch], return_exceptions=True)
            logger.info(f"[DgProsperity] 进度: {min(i + batch_size, len(codes))}/{len(codes)}, updated={updated}, failed={failed}")

        # 第二遍：计算 ΔG（环比差值）
        await self._compute_dg_for_all()

        return {
            "updated_count": updated,
            "failed_count": failed,
            "total_count": len(codes),
            "quarters": quarters
        }

    async def _compute_dg_for_all(self):
        """计算所有股票的 ΔG、Δ收入增速、ΔROE（当季 - 上季）"""
        db = await self._get_db()
        collection = db["dg_prosperity"]

        # 获取所有唯一 code
        try:
            codes = await collection.distinct("code")
        except Exception:
            return

        for code in codes:
            try:
                # 按报告期降序取最近 12 个季度，确保覆盖新拉取的数据
                cursor = collection.find({"code": code}).sort("report_period", -1)
                docs = await cursor.to_list(length=12)
            except Exception:
                continue

            if len(docs) < 2:
                continue

            # 按报告期升序排列后计算环比 Δ（百分点）
            docs_sorted = sorted(docs, key=lambda d: d.get("report_period", ""))
            for i in range(1, len(docs_sorted)):
                prev, curr = docs_sorted[i - 1], docs_sorted[i]
                set_fields = {}
                dg = _delta(curr.get("g"), prev.get("g"))
                if dg is not None:
                    set_fields["dg"] = dg
                d_or_yoy = _delta(curr.get("or_yoy"), prev.get("or_yoy"))
                if d_or_yoy is not None:
                    set_fields["d_or_yoy"] = d_or_yoy
                d_roe = _delta(curr.get("roe"), prev.get("roe"))
                if d_roe is not None:
                    set_fields["d_roe"] = d_roe
                if set_fields:
                    with contextlib.suppress(Exception):
                        await collection.update_one(
                            {"_id": curr["_id"]},
                            {"$set": set_fields}
                        )

    async def get_sector_dg(self, industry: str) -> dict:
        """获取行业级 ΔG 景气（宏观层面判断，对齐教材四层链路）。

        以本地 `stock_basic_info.industry` 反查该行业成分股，再批量取每只股票
        `dg_prosperity` 的最新一期 G/ΔG/象限，聚合出行业级景气：
        - 成分股数 / 有数据数
        - 平均 G / 平均 ΔG
        - 四象限分布
        - 主导象限（按数量，平局按 双击>反转>见顶>双杀 优先级）

        Args:
            industry: 行业名（本地 stock_basic_info.industry 口径）

        Returns:
            {industry, quadrant, quadrant_label, quadrant_color, avg_g, avg_dg,
             member_count, data_count, distribution, report_period, available}
        """
        from collections import Counter

        # TTL 缓存：行业 ΔG 基于季度财务数据，聚合结果在刷新前不变，直接复用
        cached = self._sector_dg_cache_get(industry)
        if cached is not None:
            return cached

        db = await self._get_db()
        # 1. 该行业全部成分股代码
        cursor = db["stock_basic_info"].find(
            {"industry": industry},
            {"_id": 0, "code": 1},
        )
        codes = [str(s.get("code") or "") for s in await cursor.to_list(length=6000)]
        codes = [c for c in codes if c]
        member_count = len(codes)
        if not codes:
            result = {**self._empty_quadrant(), "industry": industry, "member_count": 0,
                      "data_count": 0, "distribution": {}}
            self._sector_dg_cache_set(industry, result)
            return result

        # 2. 批量取每只股票最新一期象限（过滤非有限 g，避免 NaN/±inf 污染聚合）
        batch = await self.get_quadrant_batch(codes)
        valid = [d for d in batch.values()
                 if d.get("available") and _finite(d.get("g"))]
        data_count = len(valid)
        if not valid:
            result = {**self._empty_quadrant(), "industry": industry, "member_count": member_count,
                      "data_count": 0, "distribution": {}}
            self._sector_dg_cache_set(industry, result)
            return result

        # 3. 聚合：平均 G / 平均 ΔG（均过滤非有限值）
        gs = [float(d["g"]) for d in valid if _finite(d.get("g"))]
        dg_list = [float(d["dg"]) for d in valid if _finite(d.get("dg"))]
        avg_g = round(sum(gs) / len(gs), 2) if gs else None
        avg_dg = round(sum(dg_list) / len(dg_list), 2) if dg_list else None

        # 4. 四象限分布 + 主导象限（平局按优先级）
        dist = Counter(d.get("quadrant") for d in valid)
        priority = ["double_click", "reversal", "peaking", "double_kill"]
        dominant = max(priority, key=lambda q: dist.get(q, 0))
        if dist.get(dominant, 0) == 0:
            dominant = "unknown"

        # 5. 最新报告期（取成分股中最新的）
        periods = [str(d.get("report_period") or "") for d in valid if d.get("report_period")]
        report_period = max(periods) if periods else ""

        result = {
            "industry": industry,
            "quadrant": dominant,
            "quadrant_label": QUADRANT_LABELS.get(dominant, "数据不足"),
            "quadrant_color": QUADRANT_COLORS.get(dominant, "info"),
            "avg_g": avg_g,
            "avg_dg": avg_dg,
            "member_count": member_count,
            "data_count": data_count,
            "distribution": {q: dist.get(q, 0) for q in QUADRANT_LABELS},
            "report_period": report_period,
            "available": True,
        }
        self._sector_dg_cache_set(industry, result)
        return result


_dg_service_instance: DgProsperityService | None = None


def get_dg_prosperity_service() -> DgProsperityService:
    """获取单例"""
    global _dg_service_instance
    if _dg_service_instance is None:
        _dg_service_instance = DgProsperityService()
    return _dg_service_instance
