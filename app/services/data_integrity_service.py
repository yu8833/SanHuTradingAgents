"""
数据完整性检查与自动补数服务

核心功能：
1. 检查 stock_daily_quotes 中最新交易日的数据完整性
2. 识别缺失股票并用备用数据源自动补数
3. 记录完整性检查结果到 MongoDB
4. 提供API查询接口

调用时机：
- Tushare/AKShare 历史同步完成后自动触发
- 每天19:00定时执行兜底检查
- 手动通过API触发
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from app.utils.timezone import now_tz
from app.utils.trading_time import get_latest_trade_day

from app.core.config import settings
from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


class DataIntegrityService:
    """数据完整性检查与自动补数服务"""

    def __init__(self):
        self.db = None
        self.check_collection = "data_integrity_checks"
        self._repair_inflight = False

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def check_historical_completeness(
        self,
        trade_date: str | None = None,
        auto_remediate: bool = True,
        remediate_source: str | None = None,
        remediate_batch_size: int = 50,
        remediate_lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        检查指定交易日的历史数据完整性，可选自动补数

        Args:
            trade_date: 交易日期 (YYYY-MM-DD)，None则自动检测最新交易日
            auto_remediate: 是否自动补数
            remediate_source: 补数数据源 ("akshare" / "tushare" / "baostock")，
                              None 时使用配置 DATA_INTEGRITY_REMEDIATE_SOURCE（默认 tushare，最准；失败自动降级 akshare）
            remediate_batch_size: 补数批次大小
            remediate_lookback_days: 补数回看天数（默认30天，可配置）

        Returns:
            检查结果字典
        """
        db = await self._get_db()
        result = {
            "check_time": now_tz().isoformat(),
            "trade_date": None,
            "expected_count": 0,
            "actual_count": 0,
            "missing_count": 0,
            "missing_codes": [],
            "low_quality_count": 0,
            "low_quality_codes": [],
            "remediated_count": 0,
            "remediation_errors": [],
            "source_coverage": {},
            "status": "unknown",
        }

        try:
            # 1. 确定交易日期
            if not trade_date:
                db_latest = await self._get_latest_trade_date(db)
                if not db_latest:
                    logger.warning("⚠️ stock_daily_quotes 为空，跳过完整性检查")
                    result["status"] = "no_trade_date"
                    return result

                try:
                    expected_latest = get_latest_trade_day().strftime("%Y-%m-%d")
                except Exception:
                    logger.warning("⚠️ 交易日历获取失败，回退到DB最新日期")
                    expected_latest = db_latest

                if db_latest < expected_latest:
                    logger.warning(
                        f"📅 数据缺口：DB最新日期={db_latest}, 预期最新交易日={expected_latest}, "
                        f"将补数覆盖中间所有日期"
                    )

                trade_date = expected_latest

            result["trade_date"] = trade_date

            # 补数源未指定时，使用配置（默认 tushare，付费源最准；失败自动降级 akshare）
            if not remediate_source:
                remediate_source = settings.DATA_INTEGRITY_REMEDIATE_SOURCE

            logger.info(f"🔍 开始检查 {trade_date} 的历史数据完整性...")

            # 2. 获取应同步的股票列表（与同步服务一致的过滤逻辑）
            expected_codes = await self._get_expected_stock_codes(db, trade_date)
            result["expected_count"] = len(expected_codes)

            if not expected_codes:
                logger.warning("⚠️ stock_basic_info 中没有找到A股股票")
                result["status"] = "no_expected_stocks"
                return result

            # 3. 查询实际有数据的股票
            actual_cursor = db.stock_daily_quotes.distinct(
                "code",
                {"trade_date": trade_date, "period": "daily"}
            )
            actual_codes = set(await actual_cursor)
            result["actual_count"] = len(actual_codes)

            # 统计各数据源的覆盖情况（用于诊断；actual_codes 不区分 source，
            # 因为补数的目标就是“有数据”即可，下游查询按优先级去重）
            source_stats = {}
            for src in ["tushare", "akshare", "baostock"]:
                src_count = len(await db.stock_daily_quotes.distinct(
                    "code",
                    {"trade_date": trade_date, "period": "daily", "data_source": src}
                ))
                source_stats[src] = src_count
            result["source_coverage"] = source_stats

            # 4. 计算缺失（值级校验：已存在但 pct_chg/pre_close 全为 null 的看作低质量，一并纳入补数）
            expected_set = set(expected_codes)
            missing_codes = list(expected_set - actual_codes)
            result["missing_count"] = len(missing_codes)
            result["missing_codes"] = missing_codes[:200]  # 最多记录200个

            low_quality_codes = await self._find_low_quality_codes(db, trade_date, expected_set)
            result["low_quality_count"] = len(low_quality_codes)
            result["low_quality_codes"] = low_quality_codes[:200]

            # 统一纳入补数的股票集合（缺失 + 低质量）
            remediate_codes = sorted(set(missing_codes) | set(low_quality_codes))
            needs_fix_count = len(remediate_codes)

            completeness = (len(actual_codes) / len(expected_codes)) * 100 if expected_codes else 0
            logger.info(
                f"📊 完整性检查结果: {trade_date} - "
                f"期望 {len(expected_codes)} 只, 实际 {len(actual_codes)} 只, "
                f"缺失 {len(missing_codes)} 只, 低质量(涨跌字段缺失) {len(low_quality_codes)} 只, "
                f"需补数 {needs_fix_count} 只, 完整度 {completeness:.1f}%"
            )

            # 5. 自动补数
            if auto_remediate and remediate_codes:
                remediation_result = await self._remediate_missing(
                    remediate_codes,
                    trade_date,
                    remediate_source,
                    remediate_batch_size,
                    lookback_days=remediate_lookback_days,
                )
                result["remediated_count"] = remediation_result["success_count"]
                result["remediation_errors"] = remediation_result["errors"][:50]
            elif remediate_codes:
                logger.info(f"ℹ️ 自动补数未启用，{len(remediate_codes)} 只股票数据缺失或低质量")

            # 6. 确定状态
            if needs_fix_count == 0:
                result["status"] = "complete"
            elif result["remediated_count"] > 0:
                remaining = needs_fix_count - result["remediated_count"]
                result["status"] = "remediated" if remaining <= 0 else "partial"
            else:
                result["status"] = "incomplete"

            # 7. 持久化检查结果
            await self._save_check_result(db, result)

            # 8. 记录数据指标：计算「补数后仍无法自愈」的孤立记录数（P1-2）
            result["needs_fix_count"] = needs_fix_count
            orphan_count = max(0, needs_fix_count - result["remediated_count"])
            result["orphan_count"] = orphan_count
            await self._save_data_metrics(db, result, orphan_count)

            return result

        except Exception as e:
            logger.error(f"❌ 完整性检查失败: {e}", exc_info=True)
            result["status"] = "error"
            result["error"] = str(e)
            await self._save_check_result(db, result)
            return result

    async def _get_latest_trade_date(self, db) -> str | None:
        """获取最新交易日（从 stock_daily_quotes 中查找最新的交易日期）

        空库或异常时返回 None，不回退到今天，避免周末/节假日触发全量误报。
        """
        try:
            pipeline = [
                {"$match": {"period": "daily"}},
                {"$group": {"_id": "$trade_date"}},
                {"$sort": {"_id": -1}},
                {"$limit": 1},
            ]
            cursor = db.stock_daily_quotes.aggregate(pipeline)
            docs = await cursor.to_list(length=1)
            if docs:
                return docs[0]["_id"]
        except Exception as e:
            logger.warning(f"获取最新交易日失败: {e}")
            return None

        # 空库时返回 None，让调用方跳过检查
        logger.warning("⚠️ stock_daily_quotes 为空，无法确定最新交易日")
        return None

    async def _get_expected_stock_codes(self, db, trade_date: str | None = None) -> list[str]:
        """获取应同步的A股股票代码列表（与同步服务一致），按 code 去重

        在市口径以 Tushare 上市状态为准（is_active 由 multi_source_basics_sync_service 每日回填）：
        is_active=False 的退市/代码停用记录剔除；缺失 is_active 视为在市（兼容新上市未回填）。

        注意：不能用「近 N 日有成交」作为主判据——长期停牌的在市股票同样没有成交，
        会被误判为退市（如 *ST康佳A、信达证券等）。仅当全库尚未回填 is_active 时，
        才回退到「近45日有成交 且 名称含退/退市」的兜底口径。
        """
        cursor = db.stock_basic_info.find(
            {
                "$and": [
                    {
                        "$or": [
                            {"market_info.market": "CN"},
                            {"category": "stock_cn"},
                            {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}},
                        ]
                    },
                    {"is_active": {"$ne": False}},
                ]
            },
            {"code": 1, "name": 1},
        )
        # 使用 set 去重：stock_basic_info 按 code + source 存三源，需要按 code 唯一
        unique_codes: set = set()
        names: dict[str, str] = {}
        async for doc in cursor:
            c = doc.get("code")
            if c:
                unique_codes.add(c)
                if c not in names and doc.get("name"):
                    names[c] = str(doc["name"])

        # 兜底：全库尚未回填 is_active 时，用近45日成交 + 名称含退 过滤已退市代码
        status_backfilled = await db.stock_basic_info.count_documents(
            {"is_active": {"$exists": True}}, limit=1
        )
        if trade_date and not status_backfilled:
            try:
                cutoff = (
                    datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=45)
                ).strftime("%Y-%m-%d")
                traded_codes: set = set()
                cursor_daily = db.stock_daily_quotes.aggregate(
                    [
                        {"$match": {"period": "daily", "trade_date": {"$gte": cutoff, "$lt": trade_date}}},
                        {"$group": {"_id": "$code"}},
                    ]
                )
                async for doc in cursor_daily:
                    if doc.get("_id"):
                        traded_codes.add(doc["_id"])
                before = len(unique_codes)
                # 只剔除「无成交且名称含退/退市」的代码；长期停牌的在市股票保留
                unique_codes = {
                    c for c in unique_codes
                    if c in traded_codes or "退" not in names.get(c, "")
                }
                logger.info(
                    f"应同步股票口径兜底过滤（is_active 未回填）: 基础列表 {before} 只 → "
                    f"{len(unique_codes)} 只"
                )
            except Exception as e:
                logger.warning(f"⚠️ 应同步股票口径兜底过滤失败，回退到基础列表: {e}")

        return sorted(unique_codes)

    async def _find_low_quality_codes(self, db, trade_date: str, expected_set: set) -> list[str]:
        """值级校验：找出该交易日「有记录但 pct_chg/pre_close 全为 null」的股票。

        存在记录但涨跌字段全缺失（如仅被 AKShare 兜底、而此前 AKShare 写入 null 涨跌字段）
        的数据对下游展示无效，视为低质量，需一并补数修复（F4/F6）。
        """
        if not expected_set:
            return []
        try:
            pipeline = [
                {
                    "$match": {
                        "trade_date": trade_date,
                        "period": "daily",
                        "code": {"$in": list(expected_set)},
                    }
                },
                {
                    "$group": {
                        "_id": "$code",
                        # 该 code 在该日期有多少条「涨跌字段齐全（pct_chg 与 pre_close 均有效）」的记录
                        "valid": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$ne": [{"$ifNull": ["$pct_chg", None]}, None]},
                                            {"$ne": [{"$ifNull": ["$pre_close", None]}, None]},
                                        ]
                                    },
                                    1,
                                    0,
                                ]
                            }
                        },
                    }
                },
                {"$match": {"valid": {"$lte": 0}}},
            ]
            cursor = db.stock_daily_quotes.aggregate(pipeline)
            codes = [d["_id"] async for d in cursor if d.get("_id")]
        except Exception as e:
            logger.warning(f"⚠️ 值级校验查询失败（忽略，不影响主流程）: {e}")
            return []
        return sorted(codes)

    # ==================== 缺口审计（只读） ====================

    # 健康口径：某交易日「有数据的在市股票」达到全市场的 95% 视为完整
    HEALTH_COVERAGE = 0.95
    # 整日缺口判定：覆盖度低于 70% 视为整日缺失，走「按日期批量拉取」补数
    WHOLE_DAY_GAP_COVERAGE = 0.70
    # 审计窗口默认交易日数
    DEFAULT_AUDIT_WINDOW = 20

    def _latest_settled_trade_day(self) -> str:
        """最近一个「理应已有K线数据」的交易日（YYYY-MM-DD）。

        规则：get_latest_trade_day 已处理 15:00 收盘前回退到上一交易日；
        仅当它返回「今天」且当前时间早于 18:30（当日K线尚未落地）时，再回退一个交易日。
        这样次日白天审计时，上一交易日（已结算）不会被漏掉。
        """
        try:
            from app.utils.trading_time import get_latest_trade_day, is_trading_day, prev_trading_day

            now = now_tz()
            target = get_latest_trade_day(now)
            if target.date() == now.date() and (now.hour, now.minute) < (18, 30):
                target = prev_trading_day(target)
            return target.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"⚠️ 计算最近已结算交易日失败: {e}")
            return ""

    @staticmethod
    def _norm_date_str(value) -> str | None:
        """把 list_date / 日期字段统一为 YYYY-MM-DD；无法识别返回 None。"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        s = str(value).strip()
        if len(s) >= 8 and s[:8].isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) >= 10:
            return s[:10]
        return None

    @staticmethod
    def _norm_trade_date_key(value) -> str:
        """聚合 _id 可能是 YYYYMMDD 或 YYYY-MM-DD，统一为 YYYY-MM-DD。"""
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s[:10]

    async def _get_universe_map(self, db) -> dict[str, str | None]:
        """在市 A 股代码 → 上市日期（YYYY-MM-DD 或 None）。

        在市口径复用 _get_expected_stock_codes（is_active != False），
        上市日期用于按交易日裁剪：未上市的股票不应计入当日应有数量。
        """
        codes = await self._get_expected_stock_codes(db)
        listing: dict[str, str | None] = {c: None for c in codes}
        if not codes:
            return listing
        async for doc in db.stock_basic_info.find(
            {"code": {"$in": codes}}, {"code": 1, "list_date": 1}
        ):
            c = doc.get("code")
            if not c:
                continue
            ld = self._norm_date_str(doc.get("list_date"))
            if ld and listing.get(c) is None:
                listing[c] = ld
        return listing

    async def _load_unavailable(self, db, days: list[str], scopes: tuple[str, ...]) -> dict:
        """加载「已确认数据源无数据」的 (code, trade_date) 标记，避免反复重试。

        只有成功查询了数据源、但该代码确实没有数据（停牌/未上市/无估值）时才登记；
        接口失败不会登记，避免把瞬态故障永久当成「无数据」。
        """
        date_values = list(days) + [d.replace("-", "") for d in days]
        out: dict[str, dict[str, set]] = {s: {} for s in scopes}
        try:
            cursor = db.data_integrity_unavailable.find(
                {"scope": {"$in": list(scopes)}, "trade_date": {"$in": date_values}}
            )
            async for doc in cursor:
                d = self._norm_trade_date_key(doc.get("trade_date"))
                out.setdefault(doc.get("scope"), {}).setdefault(d, set()).add(doc.get("symbol"))
        except Exception as e:
            logger.warning(f"读取不可得数据标记失败（忽略）: {e}")
        return out

    async def _mark_unavailable(self, scope: str, pairs: list[tuple[str, str]], reason: str) -> int:
        """登记「该代码该日期数据源确实无数据」，供后续审计跳过。"""
        if not pairs:
            return 0
        try:
            db = await self._get_db()
            from pymongo import UpdateOne

            ops = [
                UpdateOne(
                    {"scope": scope, "symbol": code, "trade_date": date},
                    {"$setOnInsert": {
                        "scope": scope,
                        "symbol": code,
                        "trade_date": date,
                        "reason": reason,
                        "created_at": now_tz(),
                    }},
                    upsert=True,
                )
                for code, date in pairs
            ]
            await db.data_integrity_unavailable.bulk_write(ops, ordered=False)
            return len(ops)
        except Exception as e:
            logger.warning(f"登记不可得数据标记失败（忽略）: {e}")
            return 0

    async def _audit_quotes_dataset(
        self, db, days: list[str], universe: dict[str, str | None], unavailable: dict | None = None
    ):
        """审计 stock_daily_quotes 逐日覆盖度与低质量记录。"""
        date_values = list(days) + [d.replace("-", "") for d in days]

        # 1) 逐日实际有数据的代码集合（一次聚合）
        actual_by_date: dict[str, set] = {}
        pipeline = [
            {"$match": {"period": "daily", "trade_date": {"$in": date_values}}},
            {"$group": {"_id": "$trade_date", "codes": {"$addToSet": {"$ifNull": ["$code", "$symbol"]}}}},
        ]
        async for doc in db.stock_daily_quotes.aggregate(pipeline):
            key = self._norm_trade_date_key(doc.get("_id"))
            actual_by_date.setdefault(key, set()).update(
                c for c in (doc.get("codes") or []) if c
            )

        # 2) 低质量：当日该代码所有记录的 pct_chg/pre_close 均为空
        low_quality_by_date: dict[str, set] = {}
        pipeline_lq = [
            {"$match": {"period": "daily", "trade_date": {"$in": date_values}}},
            {
                "$group": {
                    "_id": {"d": "$trade_date", "c": "$code"},
                    "valid": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$ne": [{"$ifNull": ["$pct_chg", None]}, None]},
                                        {"$ne": [{"$ifNull": ["$pre_close", None]}, None]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
            {"$match": {"valid": {"$lte": 0}}},
        ]
        async for doc in db.stock_daily_quotes.aggregate(pipeline_lq):
            d = self._norm_trade_date_key(doc["_id"].get("d"))
            c = doc["_id"].get("c")
            if c:
                low_quality_by_date.setdefault(d, set()).add(c)

        details = []
        for d in days:
            active = {c for c, ld in universe.items() if not ld or ld <= d}
            actual = actual_by_date.get(d, set()) & active
            unavail = (unavailable or {}).get("quotes", {}).get(d, set())
            missing = (active - actual) - unavail
            low_quality = ((low_quality_by_date.get(d, set()) & active) - missing) - unavail
            expected_n = len(active)
            coverage = (len(actual) / expected_n) if expected_n else 0.0
            # 完整性口径只看「去重股票数覆盖率」：≥95% 视为该日完整。
            # 低质量（pct_chg/pre_close 为空）单独计数，不再让整日变 partial——
            # 新股上市首日 Tushare 本身没有 pre_close/pct_chg，永久无法补齐，
            # 若计入会让 99.8% 覆盖的日期长期显示「不完整」。
            if coverage < self.WHOLE_DAY_GAP_COVERAGE:
                status = "gap"
            elif coverage < self.HEALTH_COVERAGE:
                status = "partial"
            else:
                status = "ok"
            details.append(
                {
                    "trade_date": d,
                    "expected": expected_n,
                    "actual": len(actual),
                    "coverage_pct": round(coverage * 100, 2),
                    "missing_count": len(missing),
                    "low_quality_count": len(low_quality),
                    "status": status,
                    "missing_codes": sorted(missing)[:50],
                    "low_quality_codes": sorted(low_quality)[:50],
                    # 完整集合仅供内部修复使用，对外 API 会剔除
                    "_missing_all": sorted(missing),
                    "_low_quality_all": sorted(low_quality),
                }
            )
        return details, actual_by_date, low_quality_by_date

    async def _audit_simple_dataset(
        self, db, collection: str, days: list[str], universe: dict[str, str | None],
        unavailable: dict | None = None,
    ):
        """审计 daily_basic / moneyflow 这类「按 (code, trade_date) 唯一」的数据集。"""
        date_values = list(days) + [d.replace("-", "") for d in days]
        actual_by_date: dict[str, set] = {}
        pipeline = [
            {"$match": {"trade_date": {"$in": date_values}}},
            {"$group": {"_id": "$trade_date", "codes": {"$addToSet": "$code"}}},
        ]
        async for doc in db[collection].aggregate(pipeline):
            key = self._norm_trade_date_key(doc.get("_id"))
            actual_by_date.setdefault(key, set()).update(
                c for c in (doc.get("codes") or []) if c
            )

        details = []
        for d in days:
            active = {c for c, ld in universe.items() if not ld or ld <= d}
            actual = actual_by_date.get(d, set()) & active
            unavail = (unavailable or {}).get("daily_basic" if collection == "stock_daily_basic" else "moneyflow", {}).get(d, set())
            missing = (active - actual) - unavail
            expected_n = len(active)
            coverage = (len(actual) / expected_n) if expected_n else 0.0
            status = "ok" if coverage >= self.HEALTH_COVERAGE else "gap"
            details.append(
                {
                    "trade_date": d,
                    "expected": expected_n,
                    "actual": len(actual),
                    "coverage_pct": round(coverage * 100, 2),
                    "missing_count": len(missing),
                    "status": status,
                    "missing_codes": sorted(missing)[:50],
                    "_missing_all": sorted(missing),
                }
            )
        return details, actual_by_date

    async def _last_record_update(self, db, collection: str, date_field: str) -> dict[str, Any]:
        """取集合最近更新时间与总记录数（用于财务/新闻这类非逐日数据集）。"""
        try:
            doc = await db[collection].find_one(
                {}, sort=[(date_field, -1)], projection={date_field: 1}
            )
            count = await db[collection].estimated_document_count()
            latest = doc.get(date_field) if doc else None
            if isinstance(latest, datetime):
                latest = latest.isoformat()
            return {"last_update": latest, "count": count}
        except Exception as e:
            logger.warning(f"读取 {collection} 更新时间失败: {e}")
            return {"last_update": None, "count": 0}

    async def audit_coverage(
        self,
        window_trading_days: int = DEFAULT_AUDIT_WINDOW,
        include_codes: bool = False,
    ) -> dict[str, Any]:
        """审计最近 N 个交易日的逐日覆盖度，返回缺口清单（不写库）。

        Args:
            window_trading_days: 审计窗口（交易日数）
            include_codes: 是否返回每个日期的完整缺失/低质量代码集合（内部修复用，
                           对外 API 会剔除，避免响应过大）
        """
        db = await self._get_db()
        window_end = self._latest_settled_trade_day() or await self._get_latest_trade_date(db)
        if not window_end:
            return {
                "generated_at": now_tz().isoformat(),
                "has_gaps": False,
                "window_trading_days": 0,
                "message": "stock_daily_quotes 为空，无法审计",
                "quotes": {"dates": [], "gap_dates": [], "scattered_dates": []},
                "daily_basic": {"dates": []},
                "moneyflow": {"dates": []},
                "totals": {},
                "estimated_seconds": 0,
            }

        try:
            from app.services.trade_calendar_service import query_trade_days

            probe_start = (
                datetime.strptime(window_end, "%Y-%m-%d")
                - timedelta(days=max(1, window_trading_days) * 2 + 15)
            ).strftime("%Y-%m-%d")
            days = await query_trade_days(probe_start, window_end)
        except Exception as e:
            logger.warning(f"⚠️ 交易日历查询失败，退化到仅审计窗口终点: {e}")
            days = []
        if not days:
            days = [window_end]
        days = days[-max(1, int(window_trading_days)):]

        universe = await self._get_universe_map(db)
        unavailable = await self._load_unavailable(db, days, ("quotes", "daily_basic", "moneyflow"))
        quotes_details, _, _ = await self._audit_quotes_dataset(db, days, universe, unavailable)
        basic_details, _ = await self._audit_simple_dataset(db, "stock_daily_basic", days, universe, unavailable)
        moneyflow_details, _ = await self._audit_simple_dataset(db, "stock_daily_moneyflow", days, universe, unavailable)
        financial = await self._last_record_update(db, "stock_financial_data", "updated_at")
        news = await self._last_record_update(db, "stock_news", "publish_time")

        if not include_codes:
            for d in quotes_details + basic_details + moneyflow_details:
                d.pop("_missing_all", None)
                d.pop("_low_quality_all", None)

        gap_dates = [d for d in quotes_details if d["status"] == "gap"]
        # 散点缺口：覆盖率达标（>=95%）但仍有个别股票缺失/低质量的日期，也要补
        scattered_dates = [
            d for d in quotes_details
            if d["status"] != "gap" and (d["missing_count"] > 0 or d["low_quality_count"] > 0)
        ]
        basic_gaps = [d for d in basic_details if d["missing_count"] > 0]
        moneyflow_gaps = [d for d in moneyflow_details if d["missing_count"] > 0]

        total_missing = sum(d["missing_count"] for d in gap_dates + scattered_dates)
        total_low_quality = sum(d["low_quality_count"] for d in gap_dates + scattered_dates)
        has_gaps = bool(gap_dates or scattered_dates or basic_gaps or moneyflow_gaps)

        # 粗估耗时：整日缺口按每日 20s，散点按每只 1.5s，估值/资金每日 10s
        estimated = (
            len(gap_dates) * 20
            + sum(d["missing_count"] for d in scattered_dates) * 1.5
            + len(basic_gaps) * 10
            + len(moneyflow_gaps) * 10
        )
        estimated = int(min(max(estimated, 5), 3600)) if has_gaps else 0

        result: dict[str, Any] = {
            "generated_at": now_tz().isoformat(),
            "window_trading_days": len(days),
            "window_start": days[0],
            "window_end": days[-1],
            "universe_count": len(universe),
            "has_gaps": has_gaps,
            "health_coverage_pct": round(self.HEALTH_COVERAGE * 100, 1),
            "whole_day_gap_pct": round(self.WHOLE_DAY_GAP_COVERAGE * 100, 1),
            "totals": {
                "quotes_missing": total_missing,
                "quotes_low_quality": total_low_quality,
                "quotes_gap_dates": len(gap_dates),
                "quotes_scattered_dates": len(scattered_dates),
                "daily_basic_gap_dates": len(basic_gaps),
                "moneyflow_gap_dates": len(moneyflow_gaps),
            },
            "quotes": {
                "dates": quotes_details,
                "gap_dates": [
                    {"trade_date": d["trade_date"], "missing_count": d["missing_count"],
                     "coverage_pct": d["coverage_pct"]}
                    for d in gap_dates
                ],
                "scattered_dates": [
                    {"trade_date": d["trade_date"], "missing_count": d["missing_count"],
                     "low_quality_count": d["low_quality_count"], "coverage_pct": d["coverage_pct"]}
                    for d in scattered_dates
                ],
            },
            "daily_basic": {
                "dates": basic_details,
                "gap_dates": [
                    {"trade_date": d["trade_date"], "missing_count": d["missing_count"]}
                    for d in basic_gaps
                ],
            },
            "moneyflow": {
                "dates": moneyflow_details,
                "gap_dates": [
                    {"trade_date": d["trade_date"], "missing_count": d["missing_count"]}
                    for d in moneyflow_gaps
                ],
            },
            "financial": financial,
            "news": news,
            "estimated_seconds": estimated,
        }

        if include_codes:
            result["_code_sets"] = {
                "quotes": {
                    d["trade_date"]: {
                        "expected": d["expected"],
                        "actual": d["actual"],
                        "coverage": (d["actual"] / d["expected"]) if d["expected"] else 0.0,
                        "missing": d.get("_missing_all", []),
                        "low_quality": d.get("_low_quality_all", []),
                    }
                    for d in quotes_details
                },
                "daily_basic": {
                    d["trade_date"]: {
                        "coverage": (d["actual"] / d["expected"]) if d["expected"] else 0.0,
                        "missing": d.get("_missing_all", []),
                    }
                    for d in basic_details
                },
                "moneyflow": {
                    d["trade_date"]: {
                        "coverage": (d["actual"] / d["expected"]) if d["expected"] else 0.0,
                        "missing": d.get("_missing_all", []),
                    }
                    for d in moneyflow_details
                },
            }
        return result

    # ==================== 缺口修复（按缺口驱动补数） ====================

    async def start_repair(self, window_trading_days: int = DEFAULT_AUDIT_WINDOW) -> dict[str, Any]:
        """启动一次缺口修复（后台执行），立即返回 run_id 供前端轮询。

        单飞约束：进程内标记 + Redis 分布式锁；重复点击不会再开第二个任务。
        """
        db = await self._get_db()
        if self._repair_inflight:
            return {"status": "busy", "message": "已有修复任务正在执行"}

        now = now_tz()
        recent = await db["data_integrity_repairs"].find_one(
            {"status": "running"}, sort=[("started_at", -1)]
        )
        if recent and isinstance(recent.get("started_at"), datetime):
            started = recent["started_at"]
            if started.tzinfo is None:
                started = started.replace(tzinfo=now.tzinfo)
            if (now - started).total_seconds() < 7200:
                return {
                    "status": "busy",
                    "message": "已有修复任务正在执行",
                    "run_id": recent.get("run_id"),
                }

        run_id = uuid.uuid4().hex
        doc = {
            "run_id": run_id,
            "status": "running",
            "window_trading_days": int(window_trading_days),
            "started_at": now,
            "updated_at": now,
            "progress": 0,
            "message": "正在审计数据缺口…",
            "written": {"quotes": 0, "daily_basic": 0, "moneyflow": 0},
            "errors": [],
        }
        await db["data_integrity_repairs"].insert_one(doc)
        self._repair_inflight = True
        asyncio.create_task(self._execute_repair(run_id, window_trading_days))
        return {"status": "started", "run_id": run_id, "message": "已开始修复数据缺口"}

    async def _update_repair_run(self, run_id: str, **fields) -> None:
        fields["updated_at"] = now_tz()
        try:
            db = await self._get_db()
            await db["data_integrity_repairs"].update_one(
                {"run_id": run_id}, {"$set": fields}
            )
        except Exception as e:
            logger.warning(f"更新修复任务状态失败: {e}")

    async def _execute_repair(self, run_id: str, window_trading_days: int) -> None:
        """执行缺口修复：整日缺口按日期批量拉取，散点缺口按股票合并区间拉取。

        硬约束：只写「缺失 ∪ 低质量」的 (code, trade_date)，不整批写、不删除历史行、
        不写 market_quotes；写入依赖 (symbol, trade_date, data_source, period) 唯一索引幂等。
        """
        redis_service = None
        lock_value = None
        redis_ok = False
        written = {"quotes": 0, "daily_basic": 0, "moneyflow": 0}
        errors: list[dict] = []
        rollback_keys: list[dict] = []
        try:
            try:
                from app.core.redis_client import get_redis_service

                redis_service = get_redis_service()
                lock_value = await redis_service.acquire_lock(
                    "lock:data_integrity:repair", timeout=3600
                )
                redis_ok = True
            except Exception as e:
                logger.warning(f"Redis 锁不可用，退化为进程内单飞: {e}")
                redis_ok = False

            if redis_ok and not lock_value:
                await self._update_repair_run(
                    run_id, status="busy", progress=100,
                    finished_at=now_tz(), message="已有修复任务正在执行（分布式锁）",
                )
                return

            audit = await self.audit_coverage(window_trading_days, include_codes=True)
            code_sets = audit.pop("_code_sets", {})
            await self._update_repair_run(
                run_id, audit_before=audit, message="审计完成，开始补数"
            )

            if not audit.get("has_gaps"):
                await self._update_repair_run(
                    run_id, status="no_gaps", progress=100, finished_at=now_tz(),
                    message="数据完整，无需修复", audit_after=audit,
                )
                return

            from app.services.data_sources.tushare_adapter import TushareAdapter

            adapter = TushareAdapter()

            # 1) 行情：整日缺口 → 按日期批量；散点 → 按股票合并区间
            quote_sets = code_sets.get("quotes", {})
            missing_pairs = {
                (c, d) for d, info in quote_sets.items() for c in (info.get("missing") or [])
            }
            stock_dates: dict[str, set] = {}
            total_dates = len([1 for info in quote_sets.values() if info.get("missing") or info.get("low_quality")])
            done_dates = 0
            for date, info in quote_sets.items():
                missing = set(info.get("missing") or [])
                low_quality = set(info.get("low_quality") or [])
                targets = missing | low_quality
                if not targets:
                    continue
                if info.get("coverage", 0.0) < self.WHOLE_DAY_GAP_COVERAGE:
                    res = await self._repair_quotes_by_date(adapter, date, targets, missing)
                    written["quotes"] += res["written"]
                    if res.get("error"):
                        errors.append({"scope": "quotes", "trade_date": date, "error": res["error"]})
                    rollback_keys.extend(res.get("rollback_keys") or [])
                else:
                    for c in targets:
                        stock_dates.setdefault(c, set()).add(date)
                done_dates += 1
                await self._update_repair_run(
                    run_id,
                    progress=min(60, int(done_dates / max(1, total_dates) * 60)),
                    message=f"行情整日缺口处理中 {date}",
                    written=dict(written),
                )

            if stock_dates:
                total_stocks = len(stock_dates)
                for i, (code, dates) in enumerate(stock_dates.items(), start=1):
                    res = await self._repair_quotes_by_stock(adapter, code, dates)
                    written["quotes"] += res["written"]
                    if res.get("error"):
                        errors.append({"scope": "quotes", "code": code, "error": res["error"]})
                    for d in dates:
                        if (code, d) in missing_pairs:
                            rollback_keys.append({"symbol": code, "trade_date": d})
                    if i % 20 == 0 or i == total_stocks:
                        await self._update_repair_run(
                            run_id,
                            progress=min(85, 60 + int(i / total_stocks * 25)),
                            message=f"散点缺口补数中 {code} ({i}/{total_stocks})",
                            written=dict(written),
                        )
                    await asyncio.sleep(0.15)  # Tushare 频控保护

            # 2) 估值 / 资金流：逐日按缺失代码补写（唯一键，不会产生重复）
            for collection, scope, adapter_fn in (
                ("stock_daily_basic", "daily_basic", adapter.get_daily_basic),
                ("stock_daily_moneyflow", "moneyflow", adapter.get_moneyflow),
            ):
                dataset_sets = code_sets.get(scope, {})
                for date, info in dataset_sets.items():
                    missing = info.get("missing") or []
                    if not missing:
                        continue
                    res = await self._repair_simple_dataset(
                        collection, scope, adapter_fn, date, set(missing)
                    )
                    written[scope] += res["written"]
                    if res.get("error"):
                        errors.append({"scope": scope, "trade_date": date, "error": res["error"]})
                    await self._update_repair_run(
                        run_id, progress=min(95, 85 + len(written) * 3),
                        message=f"{scope} 补数中 {date}",
                        written=dict(written),
                    )

            # 3) 复检（只回传汇总，不再回传代码集合）
            after = await self.audit_coverage(window_trading_days, include_codes=False)
            status = "completed" if not after.get("has_gaps") else "partial"
            await self._update_repair_run(
                run_id,
                status=status,
                progress=100,
                finished_at=now_tz(),
                message="修复完成" if status == "completed" else "修复完成，仍有缺口未自愈",
                written=dict(written),
                errors=errors[:50],
                audit_after=after,
                rollback={
                    "collection": "stock_daily_quotes",
                    "data_source": "tushare",
                    "keys": rollback_keys[:20000],
                    "truncated": len(rollback_keys) > 20000,
                },
            )
            logger.info(
                f"✅ 缺口修复完成: run={run_id}, 写入={written}, "
                f"新增可回滚={len(rollback_keys)}, 错误={len(errors)}"
            )
        except Exception as e:
            logger.error(f"❌ 缺口修复失败: {e}", exc_info=True)
            await self._update_repair_run(
                run_id, status="failed", progress=100, finished_at=now_tz(),
                message=f"修复失败: {e}", written=dict(written), errors=errors[:50] + [{"error": str(e)}],
            )
        finally:
            self._repair_inflight = False
            if redis_ok and redis_service and lock_value:
                try:
                    await redis_service.release_lock("lock:data_integrity:repair", lock_value)
                except Exception as e:
                    logger.warning(f"释放修复锁失败: {e}")

    @staticmethod
    def _to_ts_code(code: str) -> str:
        if code.startswith(("6", "90")):
            return f"{code}.SH"
        if code.startswith(("8", "4", "92")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    @staticmethod
    def _build_quote_row(row, trade_date: str) -> dict | None:
        """把 Tushare pro.daily 一行转换为统一口径的入库行（volume=股, amount=元）。"""
        def _f(key):
            v = row.get(key)
            if v is None:
                return None
            try:
                x = float(v)
            except (TypeError, ValueError):
                return None
            return None if x != x else x  # NaN

        close = _f("close")
        if close is None or close <= 0:
            return None
        high, low = _f("high"), _f("low")
        if high is not None and low is not None and high < low:
            return None
        amount = _f("amount")
        amount = amount * 1000.0 if amount is not None else None  # 千元 → 元
        if amount is not None and amount < 0:
            return None
        volume = _f("vol")
        volume = volume * 100.0 if volume is not None else None  # 手 → 股
        pct_chg = _f("pct_chg")
        # 新股上市首日涨幅可远超 100%（如 +400%），这是真实数据；只拦截明显异常值
        if pct_chg is not None and not (-100.0 <= pct_chg <= 1000.0):
            return None
        return {
            "trade_date": trade_date,
            "open": _f("open"),
            "high": high,
            "low": low,
            "close": close,
            "pre_close": _f("pre_close"),
            "pct_chg": pct_chg,
            "volume": volume,
            "amount": amount,
        }

    def _extract_quote_rows(self, df, trade_date: str, targets: set) -> list[tuple[str, dict]]:
        rows: list[tuple[str, dict]] = []
        for _, r in df.iterrows():
            ts_code = str(r.get("ts_code") or "")
            if "." not in ts_code:
                continue
            code = ts_code.split(".")[0].zfill(6)
            if targets and code not in targets:
                continue
            row = self._build_quote_row(r, trade_date)
            if row is None:
                continue
            rows.append((code, row))
        return rows

    @staticmethod
    def _codes_in_df(df, targets: set) -> set:
        """从 Tushare 返回的 DataFrame 中提取目标代码集合。"""
        present = set()
        for _, r in df.iterrows():
            ts_code = str(r.get("ts_code") or "")
            if "." in ts_code:
                c = ts_code.split(".")[0].zfill(6)
                if c in targets:
                    present.add(c)
        return present

    async def _write_quote_rows(self, rows: list[tuple[str, dict]]) -> dict[str, Any]:
        """按 (symbol, trade_date, data_source, period) 幂等 upsert，只写传入的行。"""
        if not rows:
            return {"written": 0, "errors": []}
        try:
            from pymongo import ReplaceOne
            from app.services.historical_data_service import get_historical_data_service

            service = await get_historical_data_service()
            if service.collection is None:
                await service.initialize()

            ops = []
            for code, row in rows:
                doc = service._standardize_record(
                    code, row, "tushare", "CN", "daily", row["trade_date"]
                )
                # 新股首日涨跌幅可能超过标准化器的 ±35% 上限，按 Tushare 原始值落库
                if row.get("pct_chg") is not None:
                    doc["pct_chg"] = round(float(row["pct_chg"]), 4)
                if row.get("pre_close") is not None:
                    doc["pre_close"] = round(float(row["pre_close"]), 4)
                ops.append(
                    ReplaceOne(
                        {
                            "symbol": code,
                            "trade_date": row["trade_date"],
                            "data_source": "tushare",
                            "period": "daily",
                        },
                        doc,
                        upsert=True,
                    )
                )

            written = 0
            errors: list[str] = []
            for i in range(0, len(ops), 500):
                batch = ops[i:i + 500]
                for attempt in range(3):
                    try:
                        res = await service.collection.bulk_write(batch, ordered=False)
                        written += res.upserted_count + res.modified_count
                        break
                    except Exception as e:
                        if attempt == 2:
                            errors.append(str(e))
                            logger.error(f"❌ 缺口行情写入失败（批次 {i // 500 + 1}）: {e}")
                        else:
                            await asyncio.sleep(1.5 * (attempt + 1))
            return {"written": written, "errors": errors}
        except Exception as e:
            logger.error(f"❌ 缺口行情写入异常: {e}")
            return {"written": 0, "errors": [str(e)]}

    async def _repair_quotes_by_date(
        self, adapter, trade_date: str, targets: set, missing_targets: set
    ) -> dict[str, Any]:
        """整日缺口：一次 pro.daily(trade_date) 拉全市场，按目标代码过滤后 upsert。"""
        try:
            df = await asyncio.to_thread(
                adapter.get_daily_by_date, trade_date.replace("-", "")
            )
        except Exception as e:
            return {"written": 0, "rollback_keys": [], "error": str(e)}
        if df is None:
            return {"written": 0, "rollback_keys": [], "error": f"{trade_date} 接口调用失败"}
        if getattr(df, "empty", True):
            # 接口成功但整日无数据：登记后不再反复重试
            await self._mark_unavailable(
                "quotes", [(c, trade_date) for c in targets], "source_no_data"
            )
            return {"written": 0, "rollback_keys": []}

        present = self._codes_in_df(df, targets)
        absent = targets - present
        if absent:
            await self._mark_unavailable(
                "quotes", [(c, trade_date) for c in absent], "source_no_data"
            )
        rows = self._extract_quote_rows(df, trade_date, present)
        res = await self._write_quote_rows(rows)
        rollback_keys = [
            {"symbol": c, "trade_date": trade_date} for c, _ in rows if c in missing_targets
        ]
        if res["errors"]:
            return {**res, "rollback_keys": rollback_keys, "error": "; ".join(res["errors"][:3])}
        return {**res, "rollback_keys": rollback_keys}

    async def _repair_quotes_by_stock(self, adapter, code: str, dates: set) -> dict[str, Any]:
        """散点缺口：每股一次 API（合并日期区间），结果只保留目标日期后 upsert。"""
        try:
            start = min(dates).replace("-", "")
            end = max(dates).replace("-", "")
            df = await asyncio.to_thread(
                adapter.get_daily_by_stock, self._to_ts_code(code), start, end
            )
        except Exception as e:
            return {"written": 0, "error": str(e)}
        if df is None:
            return {"written": 0}  # 接口失败：不登记「无数据」，下次重试
        if getattr(df, "empty", True):
            await self._mark_unavailable(
                "quotes", [(code, d) for d in dates], "stock_no_data"
            )
            return {"written": 0}

        present_dates = set()
        for _, r in df.iterrows():
            d = self._norm_date_str(r.get("trade_date"))
            if d in dates:
                present_dates.add(d)
        absent = dates - present_dates
        if absent:
            await self._mark_unavailable(
                "quotes", [(code, d) for d in absent], "stock_no_data"
            )

        rows = []
        for _, r in df.iterrows():
            d = self._norm_date_str(r.get("trade_date"))
            if d not in dates:
                continue
            row = self._build_quote_row(r, d)
            if row is not None:
                rows.append((code, row))
        res = await self._write_quote_rows(rows)
        if res["errors"]:
            return {**res, "error": "; ".join(res["errors"][:3])}
        return res

    async def _repair_simple_dataset(
        self, collection: str, scope: str, adapter_fn, trade_date: str, targets: set
    ) -> dict[str, Any]:
        """daily_basic / moneyflow：按日期拉全市场，仅写目标代码（唯一键幂等）。"""
        try:
            df = await asyncio.to_thread(adapter_fn, trade_date.replace("-", ""))
        except Exception as e:
            return {"written": 0, "error": str(e)}
        if df is None:
            return {"written": 0, "error": f"{trade_date} 无返回数据"}
        if getattr(df, "empty", True):
            return {"written": 0}

        present = self._codes_in_df(df, targets)
        absent = targets - present
        if absent:
            await self._mark_unavailable(
                scope, [(c, trade_date) for c in absent], "source_no_data"
            )

        def _f(v):
            try:
                x = float(v)
                return None if x != x else x
            except (TypeError, ValueError):
                return None

        from pymongo import UpdateOne

        ops = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code") or "")
            if "." not in ts_code:
                continue
            code = ts_code.split(".")[0].zfill(6)
            if code not in targets:
                continue
            if scope == "moneyflow":
                doc = {
                    "symbol": code,
                    "code": code,
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "main_net": _f(row.get("main_net")),
                    "data_source": "tushare",
                    "updated_at": now_tz(),
                }
            else:
                total_mv, circ_mv = _f(row.get("total_mv")), _f(row.get("circ_mv"))
                doc = {
                    "symbol": code,
                    "code": code,
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "total_mv": round(total_mv / 10000.0, 6) if total_mv is not None else None,
                    "circ_mv": round(circ_mv / 10000.0, 6) if circ_mv is not None else None,
                    "pe": _f(row.get("pe")),
                    "pb": _f(row.get("pb")),
                    "ps": _f(row.get("ps")),
                    "pe_ttm": _f(row.get("pe_ttm")),
                    "pb_mrq": _f(row.get("pb_mrq")),
                    "ps_ttm": _f(row.get("ps_ttm")),
                    "turnover_rate": _f(row.get("turnover_rate")),
                    "volume_ratio": _f(row.get("volume_ratio")),
                    "total_share": _f(row.get("total_share")),
                    "float_share": _f(row.get("float_share")),
                    "data_source": "tushare",
                    "updated_at": now_tz(),
                }
            ops.append(UpdateOne({"code": code, "trade_date": trade_date}, {"$set": doc}, upsert=True))

        if not ops:
            return {"written": 0}
        try:
            db = await self._get_db()
            res = await db[collection].bulk_write(ops, ordered=False)
            return {"written": res.upserted_count + res.modified_count}
        except Exception as e:
            return {"written": 0, "error": str(e)}

    async def get_latest_repair_run(self) -> dict | None:
        """最近一次修复任务状态（含进度），供前端轮询。"""
        try:
            db = await self._get_db()
            doc = await db["data_integrity_repairs"].find_one({}, sort=[("started_at", -1)])
            if not doc:
                return None
            doc.pop("_id", None)
            for field in ("started_at", "updated_at", "finished_at"):
                v = doc.get(field)
                if isinstance(v, datetime):
                    doc[field] = v.isoformat()
            for field in ("audit_before", "audit_after"):
                v = doc.get(field)
                if isinstance(v, dict):
                    v.pop("_code_sets", None)
            return doc
        except Exception as e:
            logger.warning(f"读取修复任务状态失败: {e}")
            return None

    async def _remediate_missing(
        self,
        missing_codes: list[str],
        trade_date: str,
        source: str,
        batch_size: int,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        对缺失数据的股票进行补数

        策略：
        - 优先使用配置的源（akshare/tushare/baostock）
        - 补数范围：缺失日期往前推 lookback_days 天到缺失日期
        - 分批处理，避免内存压力
        - 失败批次重试一次
        - 补数源初始化或同步失败时，自动降级到下一个源：
            akshare   → tushare
            baostock  → akshare → tushare
        """
        result = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
        }

        if not missing_codes:
            return result

        logger.info(
            f"🔧 开始自动补数: {len(missing_codes)} 只股票, "
            f"日期={trade_date}, 数据源={source}, 回看天数={lookback_days}"
        )

        # 计算补数日期范围（往前推 lookback_days 天确保覆盖）
        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except Exception:
            end_dt = now_tz()
        start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # 构建降级链：先尝试配置的源，失败则依次降级
        # 配置默认为 tushare（付费源，字段最全/最准），失败降级到 akshare；
        # akshare 失败再降级到 tushare（兜底链互斥，保证有源可用）。
        remediate_sources = [source]
        if source == "tushare":
            remediate_sources.extend(["akshare"])  # tushare 失败降级到 akshare
        elif source == "akshare":
            remediate_sources.extend(["tushare"])  # akshare 失败降级到 tushare
        elif source == "baostock":
            remediate_sources.extend(["akshare", "tushare"])  # baostock → akshare → tushare

        remaining_codes = list(missing_codes)

        for src in remediate_sources:
            if not remaining_codes:
                break

            # 初始化补数服务（失败则降级到下一个源）
            try:
                service = await self._get_sync_service(src)
            except Exception as e:
                logger.warning(f"⚠️ 补数源 {src} 初始化失败: {e}，尝试降级...")
                result["errors"].append({"source": src, "error": f"初始化失败: {str(e)}"})
                continue

            logger.info(f"🔄 使用 {src} 源补数: {len(remaining_codes)} 只股票")
            src_result = await self._run_remediation_batches(
                src, service, remaining_codes, start_date, trade_date, batch_size, lookback_days
            )

            result["success_count"] += src_result["success_count"]
            result["error_count"] += src_result["error_count"]
            if src_result["errors"]:
                result["errors"].extend(src_result["errors"][:50])

            # 仍有失败的股票 → 降级到下一个源
            if src_result["failed_codes"]:
                remaining_codes = src_result["failed_codes"]
                if src != remediate_sources[-1]:
                    logger.warning(
                        f"⚠️ 源 {src} 有 {len(remaining_codes)} 只股票补数失败，尝试降级到下一个源..."
                    )
            else:
                remaining_codes = []
                break  # 全部成功，不再降级

        logger.info(
            f"✅ 补数完成: 成功 {result['success_count']}/{len(missing_codes)}, "
            f"失败 {result['error_count']}"
        )

        return result

    async def _get_sync_service(self, source: str):
        """获取对应数据源的同步服务（已初始化）"""
        if source == "akshare":
            from app.worker.akshare_sync_service import get_akshare_sync_service
            return await get_akshare_sync_service()
        elif source == "baostock":
            # baostock_sync_service 暂无单例获取函数，直接实例化并异步初始化
            from app.worker.baostock_sync_service import BaoStockSyncService
            service = BaoStockSyncService()
            await service.initialize()
            return service
        else:  # tushare
            from app.worker.tushare_sync_service import get_tushare_sync_service
            return await get_tushare_sync_service()

    async def _sync_one_batch(
        self,
        source: str,
        service,
        batch: list[str],
        start_date: str,
        end_date: str,
        lookback_days: int,
    ) -> dict[str, Any]:
        """执行单批次补数，归一化不同数据源接口差异

        - akshare/tushare: 调用 sync_historical_data(symbols, start_date, end_date, incremental)
        - baostock: 调用 _sync_historical_batch(code_batch, days, end_date, period, incremental)
                   （其 sync_historical_data 不接受 symbols 参数）
        """
        if source == "baostock":
            stats = await service._sync_historical_batch(
                code_batch=batch,
                days=lookback_days,
                end_date=end_date,
                period="daily",
                incremental=False,
            )
            # BaoStockSyncStats: historical_records, errors(list[str])
            error_count = len(stats.errors)
            success_count = max(0, len(batch) - error_count)
            return {
                "success_count": success_count,
                "error_count": error_count,
                "errors": [{"error": e} for e in stats.errors[:10]],
            }

        # akshare / tushare 接口一致
        batch_result = await service.sync_historical_data(
            symbols=batch,
            start_date=start_date,
            end_date=end_date,
            incremental=False,
        )
        return {
            "success_count": batch_result.get("success_count", 0),
            "error_count": batch_result.get("error_count", 0),
            "errors": batch_result.get("errors", []),
        }

    async def _run_remediation_batches(
        self,
        source: str,
        service,
        codes: list[str],
        start_date: str,
        end_date: str,
        batch_size: int,
        lookback_days: int,
    ) -> dict[str, Any]:
        """对给定股票列表分批补数，并对失败批次重试一次

        Returns:
            含 success_count / error_count / errors / failed_codes 的字典；
            failed_codes 为重试后仍失败的股票，供上层降级使用。
        """
        result = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
            "failed_codes": [],
        }

        failed_codes: list[str] = []

        # 主循环：分批补数
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            try:
                batch_result = await self._sync_one_batch(
                    source, service, batch, start_date, end_date, lookback_days
                )
                result["success_count"] += batch_result["success_count"]
                result["error_count"] += batch_result["error_count"]
                if batch_result["errors"]:
                    result["errors"].extend(batch_result["errors"][:10])

                logger.info(
                    f"📈 补数进度: {min(i + batch_size, len(codes))}/{len(codes)}, "
                    f"本批成功: {batch_result['success_count']}"
                )

                # 批次间延迟，避免API限流
                if i + batch_size < len(codes):
                    await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"❌ 补数批次 {i}-{i+len(batch)} 失败: {e}")
                failed_codes.extend(batch)
                result["errors"].append({"batch": f"{i}-{i+len(batch)}", "error": str(e)})

        # 对失败的股票进行一次重试
        if failed_codes:
            logger.info(f"🔄 对 {len(failed_codes)} 只失败的股票进行重试...")
            for i in range(0, len(failed_codes), batch_size):
                batch = failed_codes[i:i + batch_size]
                try:
                    batch_result = await self._sync_one_batch(
                        source, service, batch, start_date, end_date, lookback_days
                    )
                    result["success_count"] += batch_result["success_count"]
                    result["error_count"] += batch_result["error_count"]
                    if batch_result["errors"]:
                        result["errors"].extend(batch_result["errors"][:10])
                except Exception as e:
                    logger.error(f"❌ 重试批次 {i}-{i+len(batch)} 仍失败: {e}")
                    # 重试仍失败：计入 error_count 并交给上层降级
                    result["failed_codes"].extend(batch)
                    result["error_count"] += len(batch)
                    result["errors"].append(
                        {"batch": f"retry-{i}-{i+len(batch)}", "error": str(e)}
                    )

        return result

    async def _save_data_metrics(self, db, result: dict, orphan_count: int) -> None:
        """把完整性检查结果落为一条可时序查询的指标（P1-2）。

        落到 `data_metrics` 集合，用于观察「缺失/低质量/无法自愈孤立记录」的收敛趋势，
        支撑告警与后续逐个核对；失败仅记日志，不影响主流程。
        """
        try:
            expected = result.get("expected_count", 0)
            metric = {
                "metric": "data_integrity",
                "date": result.get("trade_date"),
                "check_time": result.get("check_time"),
                "expected_count": expected,
                "actual_count": result.get("actual_count", 0),
                "missing_count": result.get("missing_count", 0),
                "low_quality_count": result.get("low_quality_count", 0),
                "orphan_count": orphan_count,
                "remediated_count": result.get("remediated_count", 0),
                "needs_fix_count": result.get("needs_fix_count", orphan_count + result.get("remediated_count", 0)),
                "completeness_pct": round((result.get("actual_count", 0) / expected) * 100, 2) if expected else 0.0,
                "status": result.get("status"),
                "source_coverage": result.get("source_coverage", {}),
                "recorded_at": now_tz(),
            }
            await db["data_metrics"].insert_one(metric)
        except Exception as e:
            logger.warning(f"保存数据指标失败（不影响主流程）: {e}")

    async def _save_check_result(self, db, result: dict):
        """保存检查结果到 MongoDB"""
        try:
            # 复制一份，避免修改原始引用
            save_doc = dict(result)
            # 确保 check_time 是字符串（MongoDB 也可以存 datetime，但读取时需处理）
            await db[self.check_collection].insert_one(save_doc)
        except Exception as e:
            logger.warning(f"保存完整性检查结果失败（不影响主流程）: {e}")

    async def get_latest_check_result(self) -> dict | None:
        """获取最近一次完整性检查结果"""
        try:
            db = await self._get_db()
            doc = await db[self.check_collection].find_one(
                {}, sort=[("check_time", -1)]
            )
            if doc:
                doc.pop("_id", None)
                # 确保 check_time 可序列化
                ct = doc.get("check_time")
                if isinstance(ct, datetime):
                    doc["check_time"] = ct.isoformat()
            return doc
        except Exception as e:
            logger.error(f"获取检查结果失败: {e}")
            return None


# 单例
_integrity_service: DataIntegrityService | None = None


async def get_data_integrity_service() -> DataIntegrityService:
    global _integrity_service
    if _integrity_service is None:
        _integrity_service = DataIntegrityService()
    return _integrity_service
