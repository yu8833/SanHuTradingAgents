"""
自选股服务
"""

from datetime import datetime
from typing import Any
from app.utils.timezone import now_tz, to_display_iso

from bson import ObjectId

from app.core.database import get_mongo_db
from app.services.quotes_service import get_quotes_service


class FavoritesService:
    """自选股服务类"""
    
    def __init__(self):
        self.db = None
    
    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _is_valid_object_id(self, user_id: str) -> bool:
        """
        检查是否是有效的ObjectId格式
        注意：这里只检查格式，不代表数据库中实际存储的是ObjectId类型
        为了兼容性，我们统一使用 user_favorites 集合存储自选股
        """
        # 强制返回 False，统一使用 user_favorites 集合
        return False

    def _format_favorite(self, favorite: dict[str, Any]) -> dict[str, Any]:
        """格式化收藏条目（仅基础信息，不包含实时行情）。
        行情将在 get_user_favorites 中批量富集。
        注意：market 字段统一表示「市场类型」（A股/港股/美股），
        历史数据可能存储了板块信息（如中小板/创业板），此处会规范化。
        """
        import re

        added_at = favorite.get("added_at")
        if isinstance(added_at, datetime):
            added_at = to_display_iso(added_at)

        raw_market = favorite.get("market", "A股")
        code = str(favorite.get("stock_code", "")).strip().upper()

        # 规范化 market：如果是板块值或非标准值，按股票代码推断市场类型
        board_keywords = ("主板", "创业板", "科创板", "中小板", "北交所")
        exchange_keywords = ("上海", "深圳", "上交所", "深交所", "沪市", "深市")
        if raw_market in board_keywords or raw_market in exchange_keywords or raw_market not in ("A股", "港股", "美股"):
            if re.match(r"^[A-Z]{1,5}$", code):
                normalized_market = "美股"
            elif re.match(r"^\d{6}$", code):
                normalized_market = "A股"
            else:
                normalized_market = "港股"
        else:
            normalized_market = raw_market

        return {
            "stock_code": favorite.get("stock_code"),
            "stock_name": favorite.get("stock_name"),
            "market": normalized_market,
            "added_at": added_at,
            "tags": favorite.get("tags", []),
            "notes": favorite.get("notes", ""),
            "alert_price_high": favorite.get("alert_price_high"),
            "alert_price_low": favorite.get("alert_price_low"),
            # 行情占位，稍后填充
            "current_price": None,
            "change_percent": None,
            "volume": None,
        }

    async def get_user_favorites(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户自选股列表，并批量拉取实时行情进行富集（兼容字符串ID与ObjectId）。"""
        db = await self._get_db()

        favorites: list[dict[str, Any]] = []
        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if user is None:
                user = await db.users.find_one({"_id": user_id})
            favorites = (user or {}).get("favorite_stocks", [])
        else:
            doc = await db.user_favorites.find_one({"user_id": user_id})
            favorites = (doc or {}).get("favorites", [])

        # 先格式化基础字段
        items = [self._format_favorite(fav) for fav in favorites]

        # 批量获取股票基础信息（板块、交易所等）
        codes = [it.get("stock_code") for it in items if it.get("stock_code")]
        if codes:
            try:
                # 从 stock_basic_info 获取板块信息。
                # 注意：不同数据源的板块字段质量不一（tushare 的 market 常为空字符串），
                # 因此这里跨源查询，取第一个 market 非空的有效结果，并做规范化。
                basic_info_coll = db["stock_basic_info"]
                cursor = basic_info_coll.find(
                    {"code": {"$in": codes}},
                    {"code": 1, "sse": 1, "market": 1, "source": 1, "_id": 0}
                )
                basic_docs = await cursor.to_list(length=None)

                # 按代码聚合所有数据源的记录
                basic_map: dict[str, list[dict]] = {}
                for d in (basic_docs or []):
                    key = str(d.get("code")).zfill(6)
                    basic_map.setdefault(key, []).append(d)

                for it in items:
                    code = str(it.get("stock_code") or "").strip().upper()
                    docs = basic_map.get(code, [])
                    # 优先选择 market 非空的数据源记录
                    board = next(
                        (d.get("market") for d in docs if d.get("market")),
                        ""
                    )
                    exchange = next(
                        (d.get("sse") for d in docs if d.get("sse")),
                        ""
                    )
                    it["board"] = self._normalize_board(board, code)
                    it["exchange"] = exchange or "-"
            except Exception:
                # 查询失败时设置默认值
                for it in items:
                    it["board"] = self._normalize_board("", it.get("stock_code"))
                    it["exchange"] = "-"

        # 批量获取行情（优先使用入库的 market_quotes，30秒更新）
        if codes:
            try:
                coll = db["market_quotes"]
                cursor = coll.find({"code": {"$in": codes}}, {"code": 1, "close": 1, "pct_chg": 1, "amount": 1})
                docs = await cursor.to_list(length=None)
                quotes_map = {str(d.get("code")).zfill(6): d for d in (docs or [])}
                for it in items:
                    code = it.get("stock_code")
                    q = quotes_map.get(code)
                    if q:
                        it["current_price"] = q.get("close")
                        it["change_percent"] = q.get("pct_chg")
                # 兜底：对未命中的代码使用在线源补齐（可选）
                missing = [c for c in codes if c not in quotes_map]
                if missing:
                    try:
                        quotes_online = await get_quotes_service().get_quotes(missing)
                        for it in items:
                            code = it.get("stock_code")
                            if it.get("current_price") is None:
                                q2 = quotes_online.get(code, {}) if quotes_online else {}
                                it["current_price"] = q2.get("close")
                                it["change_percent"] = q2.get("pct_chg")
                    except Exception:
                        pass
            except Exception:
                # 查询失败时保持占位 None，避免影响基础功能
                pass

        # 计算「加入自选后的收益率」：基准价 = 加入当日（及之前最近一个交易日）的日线收盘价
        for it in items:
            it["return_pct"] = await self._return_since_added(db, it)

        return items

    async def _return_since_added(self, db, it: dict[str, Any]) -> float | None:
        """计算自选股加入后的累计收益率（百分数口径，如 8.34 = +8.34%）。

        仅 A 股参与计算；基准价取加入日期所在（或之前最近）交易日的日线收盘价。
        缺少行情/基准/非叶数时返回 None，前端展示为 '-'.
        """
        if it.get("market") != "A股":
            return None
        cur = it.get("current_price")
        added_at = it.get("added_at")
        if cur is None or not added_at:
            return None
        date_str = str(added_at)[:10]
        try:
            doc = await db["stock_daily_quotes"].find_one(
                {"symbol": str(it.get("stock_code", "")).zfill(6), "trade_date": {"$lte": date_str}},
                {"close": 1, "_id": 0},
                sort=[("trade_date", -1)],
            )
        except Exception:
            return None
        base = (doc or {}).get("close")
        if not base or base <= 0:
            return None
        return round((cur / base - 1) * 100, 2)

    async def get_user_symbols(self, user_id: str) -> list[str]:
        """轻量获取用户自选股代码列表（不富集行情、不查基础信息）。

        供监控规则以「自选股」为作用域时动态解析标的，保证新增自选股自动纳入已建规则。
        """
        db = await self._get_db()
        doc = await db.user_favorites.find_one(
            {"user_id": user_id}, {"favorites": 1, "_id": 0}
        )
        if not doc:
            return []
        codes = []
        for fav in doc.get("favorites", []):
            code = fav.get("stock_code") or fav.get("symbol")
            if code:
                codes.append(str(code))
        return codes

    async def add_favorite(
        self,
        user_id: str,
        stock_code: str,
        stock_name: str,
        market: str = "A股",
        tags: list[str] = None,
        notes: str = "",
        alert_price_high: float | None = None,
        alert_price_low: float | None = None
    ) -> bool:
        """添加股票到自选股（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [add_favorite] 开始添加自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()
            logger.info("🔧 [add_favorite] 数据库连接获取成功")

            favorite_stock = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "market": market,
                "added_at": now_tz(),
                "tags": tags or [],
                "notes": notes,
                "alert_price_high": alert_price_high,
                "alert_price_low": alert_price_low
            }

            logger.info(f"🔧 [add_favorite] 自选股数据构建完成: {favorite_stock}")

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [add_favorite] 用户ID类型检查: is_valid_object_id={is_oid}")

            if is_oid:
                logger.info("🔧 [add_favorite] 使用 ObjectId 方式添加到 users 集合")

                # 先尝试使用 ObjectId 查询
                result = await db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$push": {"favorite_stocks": favorite_stock},
                        "$setOnInsert": {"favorite_stocks": []}
                    }
                )
                logger.info(f"🔧 [add_favorite] ObjectId查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if result.matched_count == 0:
                    logger.info("🔧 [add_favorite] ObjectId查询失败，尝试使用字符串ID查询")
                    result = await db.users.update_one(
                        {"_id": user_id},
                        {
                            "$push": {"favorite_stocks": favorite_stock}
                        }
                    )
                    logger.info(f"🔧 [add_favorite] 字符串ID查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                success = result.matched_count > 0
                logger.info(f"🔧 [add_favorite] 返回结果: {success}")
                return success
            else:
                logger.info("🔧 [add_favorite] 使用字符串ID方式添加到 user_favorites 集合")
                result = await db.user_favorites.update_one(
                    {"user_id": user_id},
                    {
                        "$setOnInsert": {"user_id": user_id, "created_at": now_tz()},
                        "$push": {"favorites": favorite_stock},
                        "$set": {"updated_at": now_tz()}
                    },
                    upsert=True
                )
                logger.info(f"🔧 [add_favorite] 更新结果: matched_count={result.matched_count}, modified_count={result.modified_count}, upserted_id={result.upserted_id}")
                logger.info("🔧 [add_favorite] 返回结果: True")
                return True
        except Exception as e:
            logger.error(f"❌ [add_favorite] 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def remove_favorite(self, user_id: str, stock_code: str) -> bool:
        """从自选股中删除股票（兼容字符串ID与ObjectId）"""
        return (await self.remove_favorites_batch(user_id, [stock_code])) > 0

    async def remove_favorites_batch(self, user_id: str, stock_codes: list[str]) -> int:
        """批量删除自选股，返回实际删除的条目数（兼容字符串ID与ObjectId）。"""
        if not stock_codes:
            return 0

        db = await self._get_db()
        codes = [str(c).strip() for c in stock_codes if c not in (None, "")]
        if not codes:
            return 0

        is_oid = self._is_valid_object_id(user_id)
        pull_cond = {"stock_code": {"$in": codes}}

        if is_oid:
            result1 = await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"favorite_stocks": pull_cond}}
            )
            modified = result1.modified_count
            if modified == 0:
                result2 = await db.users.update_one(
                    {"_id": user_id},
                    {"$pull": {"favorite_stocks": pull_cond}}
                )
                modified = result2.modified_count
            # ObjectId 场景下 favorite_stocks 是嵌套数组，无法精确统计子文档删除数，兜底返回修改次数
            return modified or (0 if result1.matched_count == 0 else len(codes))

        # 先数匹配到的条目数（用于报告真实删除数量）
        doc = await db.user_favorites.find_one(
            {"user_id": user_id},
            {"favorites": 1, "_id": 0}
        )
        before = 0
        if doc:
            before = sum(
                1 for fav in doc.get("favorites", [])
                if str(fav.get("stock_code") or fav.get("symbol") or "").strip() in set(codes)
            )
        result = await db.user_favorites.update_one(
            {"user_id": user_id},
            {
                "$pull": {"favorites": pull_cond},
                "$set": {"updated_at": now_tz()}
            }
        )
        if result.modified_count == 0:
            return 0
        # 再次 count，得出实际删除量
        doc_after = await db.user_favorites.find_one(
            {"user_id": user_id},
            {"favorites": 1, "_id": 0}
        )
        after = 0
        if doc_after:
            _codes = set(codes)
            after = sum(
                1 for fav in doc_after.get("favorites", [])
                if str(fav.get("stock_code") or fav.get("symbol") or "").strip() in _codes
            )
        return max(0, before - after)

    async def update_favorite(
        self,
        user_id: str,
        stock_code: str,
        tags: list[str] | None = None,
        notes: str | None = None,
        alert_price_high: float | None = None,
        alert_price_low: float | None = None
    ) -> bool:
        """更新自选股信息（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        # 统一构建更新字段（根据不同集合的字段路径设置前缀）
        is_oid = self._is_valid_object_id(user_id)
        prefix = "favorite_stocks.$." if is_oid else "favorites.$."
        update_fields: dict[str, Any] = {}
        if tags is not None:
            update_fields[prefix + "tags"] = tags
        if notes is not None:
            update_fields[prefix + "notes"] = notes
        if alert_price_high is not None:
            update_fields[prefix + "alert_price_high"] = alert_price_high
        if alert_price_low is not None:
            update_fields[prefix + "alert_price_low"] = alert_price_low

        if not update_fields:
            return True

        if is_oid:
            result = await db.users.update_one(
                {
                    "_id": ObjectId(user_id),
                    "favorite_stocks.stock_code": stock_code
                },
                {"$set": update_fields}
            )
            return result.modified_count > 0
        else:
            result = await db.user_favorites.update_one(
                {
                    "user_id": user_id,
                    "favorites.stock_code": stock_code
                },
                {
                    "$set": {
                        **update_fields,
                        "updated_at": now_tz()
                    }
                }
            )
            return result.modified_count > 0

    async def is_favorite(self, user_id: str, stock_code: str) -> bool:
        """检查股票是否在自选股中（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [is_favorite] 检查自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [is_favorite] 用户ID类型: is_valid_object_id={is_oid}")

            if is_oid:
                # 先尝试使用 ObjectId 查询
                user = await db.users.find_one(
                    {
                        "_id": ObjectId(user_id),
                        "favorite_stocks.stock_code": stock_code
                    }
                )

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if user is None:
                    logger.info("🔧 [is_favorite] ObjectId查询未找到，尝试使用字符串ID查询")
                    user = await db.users.find_one(
                        {
                            "_id": user_id,
                            "favorite_stocks.stock_code": stock_code
                        }
                    )

                result = user is not None
                logger.info(f"🔧 [is_favorite] 查询结果: {result}")
                return result
            else:
                doc = await db.user_favorites.find_one(
                    {
                        "user_id": user_id,
                        "favorites.stock_code": stock_code
                    }
                )
                result = doc is not None
                logger.info(f"🔧 [is_favorite] 字符串ID查询结果: {result}")
                return result
        except Exception as e:
            logger.error(f"❌ [is_favorite] 检查自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def get_user_tags(self, user_id: str) -> list[str]:
        """获取用户使用的所有标签（从 user_favorites 集合中提取）"""
        db = await self._get_db()
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {"$unwind": "$favorites"},
            {"$unwind": {"path": "$favorites.tags", "preserveNullAndEmptyArrays": False}},
            {"$group": {"_id": "$favorites.tags"}},
            {"$sort": {"_id": 1}}
        ]
        result = await db.user_favorites.aggregate(pipeline).to_list(None)
        return [item["_id"] for item in result if item.get("_id")]

    @staticmethod
    def _normalize_board(board: str, stock_code: str) -> str:
        """规范化板块值。

        - 处理历史遗留值（中小板已并入主板）与异常值（如"未知"）
        - 空值或无有效值时按股票代码前缀兜底推导
        """
        import re
        b = str(board or "").strip()
        if b in ("中小板", "未知"):
            b = ""
        if b in ("主板", "创业板", "科创板", "北交所"):
            return b
        # 兜底：按 A 股代码前缀推导板块
        m = re.match(r"^(\d{6})", stock_code.strip())
        if not m:
            return b or "-"
        code = m.group(1)
        # 北交所代码以 4/8 开头
        if code.startswith(("4", "8")):
            return "北交所"
        if code.startswith(("300", "301", "302")):
            return "创业板"
        if code.startswith(("688", "689")):
            return "科创板"
        return "主板"

    def _get_mock_price(self, stock_code: str) -> float:
        """获取模拟股价"""
        # 基于股票代码生成模拟价格
        base_price = hash(stock_code) % 100 + 10
        return round(base_price + (hash(stock_code) % 1000) / 100, 2)
    
    def _get_mock_change(self, stock_code: str) -> float:
        """获取模拟涨跌幅"""
        # 基于股票代码生成模拟涨跌幅
        change = (hash(stock_code) % 2000 - 1000) / 100
        return round(change, 2)
    
    def _get_mock_volume(self, stock_code: str) -> int:
        """获取模拟成交量"""
        # 基于股票代码生成模拟成交量
        return (hash(stock_code) % 10000 + 1000) * 100


# 创建全局实例
favorites_service = FavoritesService()
