"""
监控中心服务 — 通用监控规则引擎 + 触发记录存储。

移植自 tickflow-stock-panel 的监控中心，适配 SanHu 架构（MongoDB + 异步 + 实时行情）。

支持三类监控规则：
  - signal: 信号型（布尔条件，如涨停/放量）
  - price:  价格/涨跌型（阈值比较，如涨跌幅>5）
  - market: 市场异动型（全市场范围，如全市场跌超5%）

规则条件 (conditions) 支持：
  - op=truth: 布尔信号字段（涨停/跌停/涨幅超5%/跌幅超5%）
  - op 比较:  阈值字段（最新价/涨跌幅/成交额/换手率/市值/PE/PB）+ 值

作用域 (scope)：
  - symbols:  指定标的（用 unified_quotes 实时行情，字段全）
  - watchlist: 自选股（动态解析创建用户的自选股，用 unified_quotes 实时行情，字段全）
  - all:      全市场（用 market_quotes 已入库快照，字段为 close/pct_chg/amount）

冷却机制：同一 (rule_id, symbol) 在 cooldown_seconds 内不重复触发。

存储：
  - 规则:  monitor_rules 集合
  - 触发记录: monitor_alerts 集合（含 severity/message/price 等，按创建时间倒序）
"""
from __future__ import annotations

import logging
import re
import time
import hashlib
from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel

from app.core.database import get_mongo_db
from app.services.candidate_pool.auxiliary_signal_layer import compute_auxiliary
from app.utils.trading_time import is_trading_time

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────
ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
RULE_TYPES = {"signal", "price", "market", "aux", "tbs"}
SCOPES = {"symbols", "watchlist", "all", "positions"}
LOGICS = {"and", "or"}
SEVERITIES = {"info", "warn", "critical"}
OPS = {">", ">=", "<", "<=", "==", "!="}

TRUTH_SIGNALS = {"signal_", "csg_"}

# 阈值字段白名单（来自实时行情）：key -> 中文名
THRESHOLD_FIELDS: dict[str, str] = {
    "price": "最新价",
    "pct_chg": "涨跌幅(%)",
    "change_amt": "涨跌额",
    "amount": "成交额(元)",
    "turnover_pct": "换手率(%)",
    "mcap_yi": "总市值(亿)",
    "pe_ttm": "市盈率TTM",
    "pb": "市净率",
}

# 布尔信号字段（op=truth 可用）：key -> 中文名
SIGNAL_FIELDS: dict[str, str] = {
    "signal_limit_up": "涨停",
    "signal_limit_down": "跌停",
    "signal_pct_up_5": "涨幅超5%",
    "signal_pct_down_5": "跌幅超5%",
}

# 辅助信号预警字段（type=aux，op=truth 可用）：key -> 中文名
# 来自教材第三章辅助信号系统（见 auxiliary_signal_layer），只预警不触发买卖。
AUX_WARNING_FIELDS: dict[str, str] = {
    "aux_vol_price_divergence": "量价背离",
    "aux_macd_top_divergence": "MACD顶背离",
    "aux_weak_but_strong": "当弱不弱",
    "aux_strong_but_weak": "当强不强",
}
# 辅助预警字段前缀（判断 op=truth 是否为辅助预警）
AUX_FIELD_PREFIX = "aux_"
# 辅助信号规则作用域：需要逐股算 K 线指标，全市场过于繁重，仅允许指定标的/自选股
AUX_ALLOWED_SCOPES = {"symbols", "watchlist"}

# 三买三卖（type=tbs）规则：把择时信号映射为交易指令
# 买入方向信号（监控自选/指定标的 → 建仓）
TBS_BUY_SIGNALS = {"B1", "B2", "B3", "B2G"}
# 卖出方向信号（监控持仓 → 减仓/清仓）
TBS_SELL_SIGNALS = {"S1", "S2", "S3", "SafetyNet", "TrailingStop"}
# tbs_dir 允许值
TBS_DIRS = {"buy", "sell", "both"}
# tbs 规则允许的作用域（买1监自选；卖1/2/3监持仓）
TBS_ALLOWED_SCOPES = {"watchlist", "positions", "symbols"}

# 内置三买三卖默认规则模板（本系统核心，默认启用、可修改、可关闭、不可删除）。
# 方向映射：买1监自选（建仓）；买2/3、卖1/2/3监持仓（加仓/减仓）。
DEFAULT_TBS_RULES: list[dict] = [
    {
        "id": "tbs_default_buy1",
        "name": "三买三卖·左侧买点（自选建仓）",
        "enabled": True,
        "type": "tbs",
        "scope": "watchlist",
        "tbs_dir": "buy",
        "tbs_signals": ["B1"],
        "severity": "warn",
        "message": "三买三卖左侧买点信号：自选股触发买点，可建仓",
    },
    {
        "id": "tbs_default_buy23",
        "name": "三买三卖·突破买点/回踩买点（持仓加仓）",
        "enabled": True,
        "type": "tbs",
        "scope": "positions",
        "tbs_dir": "buy",
        "tbs_signals": ["B2", "B3"],
        "severity": "warn",
        "message": "三买三卖突破买点/回踩买点信号：持仓触发加仓点",
    },
    {
        "id": "tbs_default_sell123",
        "name": "三买三卖·加速卖点/跌破卖点/清仓卖出（持仓减仓）",
        "enabled": True,
        "type": "tbs",
        "scope": "positions",
        "tbs_dir": "sell",
        "tbs_signals": ["S1", "S2", "S3"],
        "severity": "critical",
        "message": "三买三卖加速卖点/跌破卖点/清仓卖出信号：持仓触发卖出点",
    },
]

# 涨跌停近似阈值（%）。主板 10%，创业板/科创板 20%。简化用 9.85 判定涨停。
LIMIT_PCT = 9.85


# ── Pydantic 模型 ───────────────────────────────────────
class ConditionModel(BaseModel):
    field: str
    op: str            # truth | > >= < <= == !=
    value: float | None = None   # op 非 truth 时必填


class RuleModel(BaseModel):
    id: str
    name: str
    enabled: bool = True
    type: str          # signal | price | market | aux | tbs
    scope: str = "symbols"   # symbols | watchlist | all | positions
    symbols: list[str] = []
    user_id: str | None = None   # scope=watchlist/positions 时绑定所属用户
    conditions: list[ConditionModel] = []
    logic: str = "and"        # and | or
    cooldown_seconds: int = 3600
    severity: str = "info"    # info | warn | critical
    message: str = ""
    tbs_dir: str = "buy"      # type=tbs 时：buy | sell | both
    tbs_signals: list[str] = []   # type=tbs 时：限定监听的信号（B1/B2/B3/S1/S2/S3）
    builtin: bool = False     # 内置规则（三买三卖核心，不可删除）


# ── 校验 ────────────────────────────────────────────────
def _is_signal_field(field: str) -> bool:
    return (any(field.startswith(p) for p in TRUTH_SIGNALS)
            or field.startswith(AUX_FIELD_PREFIX))


def validate(rule: dict) -> None:
    """校验规则字段，非法抛 ValueError（含中文信息）。"""
    rid = rule.get("id", "")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        raise ValueError(f"规则 id 非法（仅小写字母数字下划线，1-40字符）: {rid!r}")
    if not isinstance(rule.get("name"), str) or not rule["name"].strip():
        raise ValueError("规则 name 不能为空")
    if rule.get("type") not in RULE_TYPES:
        raise ValueError(f"type 必须是 {RULE_TYPES} 之一")
    if rule.get("scope", "symbols") not in SCOPES:
        raise ValueError(f"scope 必须是 {SCOPES} 之一")
    # 辅助信号规则需逐股算 K 线指标，全市场过于繁重，仅允许指定标的/自选股
    if rule.get("type") == "aux" and rule.get("scope", "symbols") not in AUX_ALLOWED_SCOPES:
        raise ValueError("辅助信号规则作用域仅支持「指定标的」或「自选股」")
    # 三买三卖规则：按信号生成交易指令，作用域限自选/持仓/指定标的，需绑定用户以执行纸面交易
    if rule.get("type") == "tbs":
        if rule.get("scope", "symbols") not in TBS_ALLOWED_SCOPES:
            raise ValueError("三买三卖规则作用域仅支持「自选股」「持仓」或「指定标的」")
        if rule.get("tbs_dir", "buy") not in TBS_DIRS:
            raise ValueError(f"tbs_dir 必须是 {TBS_DIRS} 之一")
        if not rule.get("user_id"):
            raise ValueError("三买三卖规则必须绑定 user_id（指令归属执行账户）")
        cd = rule.get("cooldown_seconds", 3600)
        if not isinstance(cd, int) or cd < 0:
            raise ValueError("cooldown_seconds 必须是非负整数")
        # 限定信号必须是合法三买三卖信号
        valid_signals = TBS_BUY_SIGNALS | TBS_SELL_SIGNALS
        tbs_signals = rule.get("tbs_signals", []) or []
        if not isinstance(tbs_signals, list) or not all(s in valid_signals for s in tbs_signals):
            raise ValueError(f"tbs_signals 必须是 {valid_signals} 的子集")
        # tbs 规则不需要阈值/信号 conditions
        return
    if rule.get("scope") == "symbols":
        syms = rule.get("symbols")
        if not isinstance(syms, list) or len(syms) == 0:
            raise ValueError("scope=symbols 时 symbols 不能为空")
    elif rule.get("scope") == "watchlist":
        if not rule.get("user_id"):
            raise ValueError("scope=watchlist 时必须绑定 user_id")
    if rule.get("severity", "info") not in SEVERITIES:
        raise ValueError(f"severity 必须是 {SEVERITIES} 之一")
    cd = rule.get("cooldown_seconds", 3600)
    if not isinstance(cd, int) or cd < 0:
        raise ValueError("cooldown_seconds 必须是非负整数")

    conds = rule.get("conditions")
    if not isinstance(conds, list) or len(conds) == 0:
        raise ValueError("conditions 不能为空")
    if len(conds) > 8:
        raise ValueError("conditions 最多 8 条")
    if rule.get("logic", "and") not in LOGICS:
        raise ValueError(f"logic 必须是 {LOGICS} 之一")
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            raise ValueError(f"第 {i+1} 个条件格式错误")
        field = c.get("field", "")
        op = c.get("op", "")
        if op == "truth":
            if not _is_signal_field(field):
                raise ValueError(f"第 {i+1} 个条件: op=truth 时 field 必须是信号列: {field!r}")
        elif op in OPS:
            if field not in THRESHOLD_FIELDS:
                raise ValueError(f"第 {i+1} 个条件: 阈值字段 {field!r} 不在白名单")
            if not isinstance(c.get("value"), (int, float)):
                raise ValueError(f"第 {i+1} 个条件: value 必须是数字")
        else:
            raise ValueError(f"第 {i+1} 个条件: op {op!r} 非法（应为 truth 或 {OPS}）")


def normalize(rule: dict) -> dict:
    """补全默认字段，返回规范化后的规则（不校验）。"""
    r = dict(rule)
    r.setdefault("enabled", True)
    r.setdefault("scope", "symbols")
    r.setdefault("symbols", [])
    r.setdefault("conditions", [])
    r.setdefault("logic", "and")
    r.setdefault("cooldown_seconds", 3600)
    r.setdefault("severity", "info")
    r.setdefault("message", "")
    r.setdefault("user_id", None)
    r.setdefault("tbs_dir", "buy")
    r.setdefault("tbs_signals", [])
    r.setdefault("builtin", False)
    # 非「指定标的」作用域时清空 symbols，避免展示冗余代码
    if r.get("scope") != "symbols":
        r["symbols"] = []
    # 非 tbs 规则无需 tbs_dir；非 aux 规则无需 aux 字段
    if r.get("type") != "tbs":
        r.pop("tbs_dir", None)
        r.pop("tbs_signals", None)
    r.setdefault("created_at", datetime.now().isoformat())
    return r


# ── 服务 ────────────────────────────────────────────────
class MonitorService:
    """监控服务：规则 CRUD + 行情评估 + 告警存储。"""

    def __init__(self):
        self.db = None
        self.rules_coll = "monitor_rules"
        self.alerts_coll = "monitor_alerts"
        self.tbs_orders_coll = "monitor_tbs_orders"
        # (rule_id, symbol[, signal]) -> 上次触发时间(秒)。内存态，重启后重置。
        self._last_fire: dict[tuple[str, str], float] = {}

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def ensure_indexes(self) -> None:
        db = await self._get_db()
        await db[self.rules_coll].create_index("id", unique=True)
        await db[self.alerts_coll].create_index([("ts", -1)])
        await db[self.tbs_orders_coll].create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
        await db[self.tbs_orders_coll].create_index([("rule_id", 1), ("symbol", 1), ("status", 1)])

    # ── 规则 CRUD ─────────────────────────────────────
    def _serialize(self, doc: dict[str, Any]) -> dict[str, Any]:
        if doc is None:
            return None
        result = dict(doc)
        if "_id" in result:
            result["id"] = str(result["_id"])
            del result["_id"]
        return result

    async def list_rules(self, user_id: str | None = None) -> list[dict]:
        db = await self._get_db()
        await self.ensure_default_rules(user_id)
        # 全局规则（未绑定用户）+ 当前用户的规则；隔离其他用户的自选/持仓/tbs 规则
        query: dict[str, Any] = {"$or": [{"user_id": None}, {"user_id": user_id}]}
        cursor = db[self.rules_coll].find(query).sort("created_at", -1)
        docs = await cursor.to_list(length=None)
        rules = []
        for d in docs:
            r = dict(d)
            r.pop("_id", None)
            rules.append(r)
        return rules

    async def ensure_default_rules(self, user_id: str | None) -> None:
        """为指定用户播种内置三买三卖规则（幂等，已存在则保留用户的自定义 enabled/name 等）。

        id 字段在 DB 上有唯一索引，故内置规则 id 需按用户作用域唯一（追加 user_id 哈希后缀），
        避免多用户内置规则冲突。
        """
        if not user_id:
            return
        db = await self._get_db()
        suffix = hashlib.sha1(user_id.encode()).hexdigest()[:8]
        # 清理旧版（无用户后缀）内置规则，避免残留重复
        legacy_ids = {tpl["id"] for tpl in DEFAULT_TBS_RULES}
        await db[self.rules_coll].delete_many({
            "id": {"$in": list(legacy_ids)},
            "user_id": user_id,
            "builtin": True,
        })
        for tpl in DEFAULT_TBS_RULES:
            rule = dict(tpl)
            rule["id"] = f"{tpl['id']}_{suffix}"
            rule["user_id"] = user_id
            rule["builtin"] = True
            rule.setdefault("cooldown_seconds", 3600)
            rule.setdefault("logic", "and")
            rule.setdefault("conditions", [])
            existing = await db[self.rules_coll].find_one({
                "id": rule["id"], "user_id": user_id})
            if existing:
                continue
            rule.setdefault("created_at", datetime.now().isoformat())
            await db[self.rules_coll].update_one(
                {"id": rule["id"], "user_id": user_id},
                {"$set": rule},
                upsert=True,
            )

    async def save_rule(self, rule: dict) -> dict:
        db = await self._get_db()
        # 内置规则保护：用户新建不得标记 builtin；编辑内置规则时保留 builtin 标志
        existing = await db[self.rules_coll].find_one({"id": rule["id"]})
        rule = normalize(rule)
        if existing and existing.get("builtin"):
            rule["builtin"] = True
        else:
            rule["builtin"] = False
        validate(rule)
        if existing and existing.get("created_at"):
            rule["created_at"] = existing["created_at"]
        await db[self.rules_coll].update_one(
            {"id": rule["id"]},
            {"$set": rule},
            upsert=True,
        )
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        db = await self._get_db()
        existing = await db[self.rules_coll].find_one({"id": rule_id})
        if existing and existing.get("builtin"):
            raise ValueError("内置规则（三买三卖核心）不可删除，可关闭或修改")
        result = await db[self.rules_coll].delete_one({"id": rule_id})
        return result.deleted_count > 0

    # ── 告警存储 ──────────────────────────────────────
    async def list_alerts(self, days: int = 7, limit: int = 500,
                          source: str | None = None) -> tuple[list[dict], int]:
        db = await self._get_db()
        cutoff = (time.time() - days * 86400) * 1000
        query: dict[str, Any] = {"ts": {"$gte": cutoff}}
        if source:
            query["source"] = source
        total = await db[self.alerts_coll].count_documents({})
        cursor = db[self.alerts_coll].find(query).sort("ts", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        alerts = []
        for d in docs:
            a = dict(d)
            a["id"] = str(a.pop("_id"))
            alerts.append(a)
        return alerts, total

    async def clear_alerts(self) -> int:
        db = await self._get_db()
        result = await db[self.alerts_coll].delete_many({})
        return result.deleted_count

    async def delete_alert(self, alert_id: str) -> bool:
        db = await self._get_db()
        try:
            result = await db[self.alerts_coll].delete_one({"_id": ObjectId(alert_id)})
            return result.deleted_count > 0
        except Exception:
            return False

    # ── 行情获取 ──────────────────────────────────────
    async def _fetch_symbol_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """获取指定标的实时行情（字段全）。"""
        import asyncio

        from app.services.unified_quotes import get_unified_quotes
        raw = await asyncio.to_thread(get_unified_quotes, symbols)
        out: dict[str, dict] = {}
        for code, q in raw.items():
            out[code] = {
                "name": q.get("name", ""),
                "price": _to_float(q.get("price")),
                "pct_chg": _to_float(q.get("change_pct")),
                "change_amt": _to_float(q.get("change_amt")),
                "amount": _to_float(q.get("amount_wan")) * 10000 if q.get("amount_wan") is not None else None,
                "turnover_pct": _to_float(q.get("turnover_pct")),
                "mcap_yi": _to_float(q.get("mcap_yi")),
                "pe_ttm": _to_float(q.get("pe_ttm")),
                "pb": _to_float(q.get("pb")),
            }
        return out

    async def _fetch_all_quotes(self) -> dict[str, dict]:
        """获取全市场实时行情（从 market_quotes 已入库快照读取）。"""
        db = await self._get_db()
        latest = await db["market_quotes"].find_one(
            {}, sort=[("updated_at", -1)]
        )
        if not latest:
            return {}
        trade_date = latest.get("trade_date")
        query: dict[str, Any] = {}
        if trade_date:
            query["trade_date"] = trade_date
        cursor = db["market_quotes"].find(query)
        out: dict[str, dict] = {}
        async for doc in cursor:
            code = str(doc.get("code", "")).zfill(6)
            out[code] = {
                "name": doc.get("name", ""),
                "price": _to_float(doc.get("close")),
                "pct_chg": _to_float(doc.get("pct_chg")),
                "amount": _to_float(doc.get("amount")),
            }
        return out

    async def _resolve_watchlist_symbols(self, user_id: str | None) -> list[str]:
        """解析某用户自选股的当前代码列表（动态，新增自选股自动纳入）。"""
        if not user_id:
            return []
        try:
            from app.services.favorites_service import favorites_service
            return await favorites_service.get_user_symbols(user_id)
        except Exception as e:
            logger.error(f"❌ 解析自选股失败 user_id={user_id}: {e}", exc_info=True)
            return []

    async def _resolve_position_symbols(self, user_id: str | None) -> list[str]:
        """解析某用户纸面交易未平仓持仓的代码列表（动态，用于卖信号监控）。"""
        if not user_id:
            return []
        try:
            db = await self._get_db()
            cursor = db["paper_positions"].find(
                {"user_id": user_id, "quantity": {"$gt": 0}},
                {"_id": 0, "code": 1},
            )
            return [str(d.get("code", "")).zfill(6) async for d in cursor]
        except Exception as e:
            logger.error(f"❌ 解析持仓失败 user_id={user_id}: {e}", exc_info=True)
            return []

    # ── 三买三卖（type=tbs）待确认指令 ──────────────────
    @staticmethod
    def _tbs_direction(sig_type: str, tbs_dir: str) -> str | None:
        """按规则方向与信号类型，返回交易方向（buy/sell），不适用返回 None。"""
        if sig_type in TBS_BUY_SIGNALS and tbs_dir in ("buy", "both"):
            return "buy"
        if sig_type in TBS_SELL_SIGNALS and tbs_dir in ("sell", "both"):
            return "sell"
        return None

    @staticmethod
    def _tbs_reason(direction: str, sig: dict, item: dict) -> str:
        label = sig.get("type_label", sig.get("type", ""))
        if direction == "buy":
            return f"三买三卖·{label}：{item.get('name', '')} 触发买入，现价 {item.get('close')}"
        return f"三买三卖·{label}：{item.get('name', '')} 触发卖出，现价 {item.get('close')}"

    async def scan_tbs_instructions(self) -> int:
        """评估所有启用的 tbs 规则，把三买三卖信号落为待确认指令。

        对不同规则的目标股票集合并集做一次扫描，再按规则切分信号、写库。
        同一 (rule, symbol, signal) 已有 pending 指令或处于冷却期内不再重复生成。
        """
        db = await self._get_db()
        rules = await db[self.rules_coll].find(
            {"enabled": True, "type": "tbs"}).to_list(length=None)
        if not rules:
            return 0

        # 1. 解析每条的股票集合并收集全体
        rule_symbols: dict[str, list[str]] = {}
        all_syms: set[str] = set()
        for r in rules:
            scope = r.get("scope", "watchlist")
            if scope == "symbols":
                syms = {str(s).zfill(6) for s in r.get("symbols", []) if s}
            elif scope == "positions":
                syms = set(await self._resolve_position_symbols(r.get("user_id")))
            else:  # watchlist
                syms = set(await self._resolve_watchlist_symbols(r.get("user_id")))
            rule_symbols[r["id"]] = list(syms)
            all_syms.update(syms)
        if not all_syms:
            return 0

        # 2. 一次扫描（关闭 ΔG/流动性与评分过滤，保留全部信号）
        try:
            from app.services.three_buys_three_sells_service import (
                get_three_buys_three_sells_service,
            )
            svc = get_three_buys_three_sells_service()
            res = await svc.scan_three_buys_three_sells({
                "pool": list(all_syms),
                "enable_dg_filter": False,
                "include_signaless": True,
                "min_score": 0,
                "enable_liquidity_filter": False,
                "enable_gmma_filter": False,
            })
        except Exception as e:
            logger.error(f"❌ 三买三卖监控扫描失败: {e}", exc_info=True)
            return 0

        items = {str(i.get("code", "")).zfill(6): i for i in res.get("items", [])}

        # 3. 按规则生成指令
        now = time.time()
        now_iso = datetime.now().isoformat()
        created = 0
        for r in rules:
            user_id = r.get("user_id")
            for sym in rule_symbols.get(r["id"], []):
                item = items.get(sym)
                if not item:
                    continue
                for sig in item.get("signals", []):
                    stype = sig.get("type", "")
                    # 按规则限定信号过滤（内置规则细分买1/买2/3/卖1/2/3）
                    tbs_signals = r.get("tbs_signals") or []
                    if tbs_signals and stype not in tbs_signals:
                        continue
                    direction = self._tbs_direction(stype, r.get("tbs_dir", "buy"))
                    if not direction:
                        continue
                    # 去重：已有同源 pending 指令
                    existing = await db[self.tbs_orders_coll].find_one({
                        "user_id": user_id,
                        "rule_id": r["id"],
                        "symbol": sym,
                        "signal_type": stype,
                        "status": "pending",
                    })
                    if existing:
                        continue
                    # 冷却
                    key = (r["id"], sym, stype)
                    last = self._last_fire.get(key)
                    if last is not None and (now - last) < r.get("cooldown_seconds", 3600):
                        continue
                    self._last_fire[key] = now
                    position_pct = sig.get("position_pct") if direction == "buy" else sig.get("sell_pct")
                    await db[self.tbs_orders_coll].insert_one({
                        "user_id": user_id,
                        "rule_id": r["id"],
                        "rule_name": r.get("name", ""),
                        "symbol": sym,
                        "name": item.get("name", ""),
                        "signal_type": stype,
                        "signal_label": sig.get("type_label", stype),
                        "direction": direction,
                        "position_pct": position_pct,
                        "stop_loss_price": sig.get("stop_loss_price") if direction == "buy" else None,
                        "reference_price": item.get("close"),
                        "status": "pending",
                        "created_at": now_iso,
                        "executed_at": None,
                        "reason": self._tbs_reason(direction, sig, item),
                    })
                    created += 1
        if created:
            logger.info(f"✅ 三买三卖监控: 生成 {created} 条待确认指令")
        return created

    async def list_tbs_orders(self, user_id: str | None, status: str | None = None,
                              limit: int = 200) -> list[dict]:
        """列出某用户的待确认指令（时间倒序）。"""
        db = await self._get_db()
        query: dict[str, Any] = {}
        if user_id:
            query["user_id"] = user_id
        if status and status != "all":
            query["status"] = status
        cursor = db[self.tbs_orders_coll].find(query).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        out = []
        for d in docs:
            o = dict(d)
            o["id"] = str(o.pop("_id"))
            out.append(o)
        return out

    async def cancel_tbs_order(self, order_id: str, user_id: str | None) -> bool:
        """取消待确认指令（pending → cancelled）。"""
        db = await self._get_db()
        query: dict[str, Any] = {"_id": ObjectId(order_id), "status": "pending"}
        if user_id:
            query["user_id"] = user_id
        result = await db[self.tbs_orders_coll].update_one(
            query, {"$set": {"status": "cancelled"}})
        return result.modified_count > 0

    async def dismiss_tbs_order(self, order_id: str, user_id: str | None) -> bool:
        """忽略待确认指令（pending → dismissed，不再执行也不占用冷却）。"""
        db = await self._get_db()
        query: dict[str, Any] = {"_id": ObjectId(order_id), "status": "pending"}
        if user_id:
            query["user_id"] = user_id
        result = await db[self.tbs_orders_coll].update_one(
            query, {"$set": {"status": "dismissed"}})
        return result.modified_count > 0

    async def execute_tbs_order(self, order_id: str, user_id: str | None) -> dict[str, Any]:
        """确认执行待确认指令：按建议仓位折算数量并走纸面交易成交入口。"""
        db = await self._get_db()
        query: dict[str, Any] = {"_id": ObjectId(order_id), "status": "pending"}
        if user_id:
            query["user_id"] = user_id
        order = await db[self.tbs_orders_coll].find_one(query)
        if not order:
            raise ValueError("指令不存在或已处理")

        symbol = order["symbol"]
        direction = order["direction"]
        position_pct = float(order.get("position_pct") or 0)
        if position_pct <= 0:
            position_pct = 1.0

        from app.services.paper_executor import (
            execute_market_order,
            get_last_price,
            get_or_create_account,
        )

        price = await get_last_price(symbol, "CN")
        if price is None or price <= 0:
            raise ValueError(f"无法获取 {symbol} 的最新价格")

        target_user = order.get("user_id") or user_id
        if not target_user:
            raise ValueError("指令缺少执行账户")

        # 折算数量（A股按 100 股一手取整）
        if direction == "buy":
            acc = await get_or_create_account(target_user)
            cash = float((acc.get("cash") or {}).get("CNY", 0.0))
            alloc = cash * position_pct
            qty = int(alloc / price / 100) * 100
            if qty <= 0:
                qty = 100 if cash >= price * 100 else 0
            if qty <= 0:
                raise ValueError("可用资金不足，无法买入一手")
        else:
            pos = await db["paper_positions"].find_one(
                {"user_id": target_user, "code": symbol})
            avail = int((pos or {}).get("available_qty", (pos or {}).get("quantity", 0)))
            if order.get("signal_type") == "S3" or position_pct >= 1.0:
                qty = max(0, avail)
            else:
                qty = int(avail * position_pct / 100) * 100
            if qty <= 0:
                raise ValueError("可用持仓不足，无法卖出")

        order_result = await execute_market_order(
            user_id=target_user,
            code=symbol,
            side=direction,
            quantity=qty,
            market="CN",
            strategy="tbs",
            stock_name=order.get("name"),
            stop_loss_price=order.get("stop_loss_price") if direction == "buy" else None,
        )
        await db[self.tbs_orders_coll].update_one(
            {"_id": order["_id"]},
            {"$set": {
                "status": "executed",
                "executed_at": datetime.now().isoformat(),
                "executed_qty": qty,
                "executed_price": order_result.get("price"),
            }},
        )
        return order_result

    # ── 辅助信号预警（type=aux） ─────────────────────────
    def _aux_fields_from_result(self, aux: dict[str, Any], name: str) -> dict[str, Any]:
        """把 auxiliary_signal_layer 的结果映射为 aux 预警布尔字段（供 op=truth 判定）。"""
        warnings = aux.get("warnings", [])
        regime_label = (((aux.get("details") or {}).get("regime_quadrant") or {}).get("label", ""))
        return {
            "name": name,
            "aux_vol_price_divergence": any("量价背离" in w for w in warnings),
            "aux_macd_top_divergence": any("MACD 顶背离" in w for w in warnings),
            "aux_weak_but_strong": "当弱不弱" in regime_label,
            "aux_strong_but_weak": any("当强不强" in w for w in warnings),
        }

    async def _fetch_aux_fields(self, symbols: list[str]) -> dict[str, dict]:
        """对指定标的算辅助信号预警字段（需 K 线指标，仅用于 type=aux 规则）。

        复用三买三卖 `_batch_get_quotes` + `_precompute_indicators` 与辅助信号层
        `compute_auxiliary`，避免重复实现指标计算。市场趋势取上证指数，失败时回落 neutral。
        """
        if not symbols:
            return {}
        from datetime import timedelta

        from app.services.three_buys_three_sells_service import (
            get_three_buys_three_sells_service,
        )
        from app.utils.technical_indicators import calc_market_trend

        end = datetime.now()
        start = end - timedelta(days=150)
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')

        svc = get_three_buys_three_sells_service()
        quotes = await svc._batch_get_quotes(list(symbols), start_str, end_str)

        # 大盘趋势（指数，避免命中个股 000001）
        market_trend = "neutral"
        try:
            idx = await svc._get_market_index_klines(start_str, end_str)
            if len(idx) > 60:
                idx_ind = svc._precompute_indicators(idx, "000001", "上证指数", "", 0)
                if idx_ind:
                    market_trend = calc_market_trend(
                        idx_ind["closes"], idx_ind["ma60"], idx_ind["ma20"])
        except Exception as e:
            logger.warning(f"辅助信号大盘趋势计算失败（回落 neutral）: {e}")

        # 名称查询（复用行情快照/基础信息）
        names: dict[str, str] = {}
        try:
            db = await self._get_db()
            cursor = db["stock_basic_info"].find(
                {"code": {"$in": list(symbols)}},
                {"_id": 0, "code": 1, "name": 1})
            async for doc in cursor:
                names[str(doc.get("code", "")).zfill(6)] = doc.get("name", "")
        except Exception as e:
            logger.warning(f"辅助信号名称查询失败: {e}")

        out: dict[str, dict] = {}
        for code in symbols:
            kline = quotes.get(code, [])
            if len(kline) < 70:
                continue
            try:
                ind = svc._precompute_indicators(kline, code, names.get(code, ""), "", 0)
                if ind is None:
                    continue
                aux = compute_auxiliary(ind, market_trend)
                out[code] = self._aux_fields_from_result(aux, names.get(code, "") or code)
            except Exception as e:
                logger.warning(f"辅助信号计算失败 {code}: {e}")
        return out

    # ── 评估 ──────────────────────────────────────────
    def _compute_signals(self, q: dict[str, Any]) -> dict[str, bool]:
        """根据行情计算布尔信号。"""
        pct = q.get("pct_chg")
        signals: dict[str, bool] = {}
        if pct is None:
            return signals
        signals["signal_limit_up"] = pct >= LIMIT_PCT
        signals["signal_limit_down"] = pct <= -LIMIT_PCT
        signals["signal_pct_up_5"] = pct >= 5
        signals["signal_pct_down_5"] = pct <= -5
        return signals

    def _match_condition(self, q: dict[str, Any], cond: dict) -> bool:
        """判断单条条件是否命中。"""
        field = cond["field"]
        op = cond["op"]
        if op == "truth":
            if field.startswith(AUX_FIELD_PREFIX):
                return bool(q.get(field, False))
            return self._compute_signals(q).get(field, False)
        value = q.get(field)
        if value is None:
            return False
        target = cond.get("value")
        try:
            if op == ">":
                return value > target
            if op == ">=":
                return value >= target
            if op == "<":
                return value < target
            if op == "<=":
                return value <= target
            if op == "==":
                return value == target
            if op == "!=":
                return value != target
        except TypeError:
            return False
        return False

    def _rule_hits(self, q: dict[str, Any], rule: dict) -> list[str]:
        """返回命中的条件 field 列表。"""
        conds = rule.get("conditions", [])
        logic = rule.get("logic", "and")
        if logic == "or":
            return [c["field"] for c in conds if self._match_condition(q, c)]
        return [c["field"] for c in conds] if all(self._match_condition(q, c) for c in conds) else []

    def _default_message(self, rule: dict, name: str, pct: float | None,
                         price: float | None, hit_fields: list[str]) -> str:
        """生成默认 message。"""
        cond_text = self._format_conditions_text(rule)
        parts = []
        if cond_text:
            parts.append(cond_text)
        if price is not None:
            parts.append(f"现价 {price}")
        if pct is not None:
            sign = "+" if pct >= 0 else ""
            parts.append(f"{sign}{pct:.2f}%")
        return " · ".join(parts) or "监控触发"

    def _format_conditions_text(self, rule: dict) -> str:
        conds = rule.get("conditions", [])
        if not conds:
            return ""
        logic_word = "且" if rule.get("logic", "and") == "and" else "或"
        parts = []
        for c in conds:
            field = c.get("field", "")
            op = c.get("op", "truth")
            value = c.get("value")
            label = (THRESHOLD_FIELDS.get(field) or SIGNAL_FIELDS.get(field)
                     or AUX_WARNING_FIELDS.get(field) or field)
            if op == "truth":
                parts.append(label)
            else:
                op_map = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "==": "=", "!=": "≠"}
                parts.append(f"{label}{op_map.get(op, op)}{value}")
        return f" {logic_word} ".join(parts)

    async def run_evaluation(self, respect_trading_time: bool = True) -> int:
        """评估所有启用规则，触发条件时写入告警记录。返回触发条数。

        respect_trading_time=True 时，非 A 股交易时间（含收盘后缓冲期）跳过评估，
        避免基于盘后冻结行情在夜间反复触发重复告警。
        """
        if respect_trading_time and not is_trading_time():
            logger.debug("非交易时间，跳过监控规则评估")
            return 0
        try:
            db = await self._get_db()
            cursor = db[self.rules_coll].find({"enabled": True})
            rules = await cursor.to_list(length=None)
            if not rules:
                return 0

            now = time.time()
            events: list[dict] = []
            # tbs 规则走三买三卖扫描（scan_tbs_instructions），不参与行情布尔评估
            non_tbs = [r for r in rules if r.get("type") != "tbs"]
            symbol_rules = [r for r in non_tbs if r.get("scope") == "symbols"]
            watchlist_rules = [r for r in non_tbs if r.get("scope") == "watchlist"]
            all_rules = [r for r in non_tbs if r.get("scope") == "all"]

            # 1. 指定标的 + 自选股：取并集按 unified_quotes（实时行情，字段全）
            symbol_quotes: dict[str, dict] = {}
            watchlist_by_rule: dict[str, list[str]] = {}
            if symbol_rules or watchlist_rules:
                syms: set[str] = set()
                for r in symbol_rules:
                    syms.update(str(s) for s in r.get("symbols", []) if s)
                for r in watchlist_rules:
                    resolved = await self._resolve_watchlist_symbols(r.get("user_id"))
                    watchlist_by_rule[r["id"]] = resolved
                    syms.update(resolved)
                if syms:
                    symbol_quotes = await self._fetch_symbol_quotes(list(syms))

            # 2. 全市场：从 market_quotes 读取
            all_quotes: dict[str, dict] = {}
            if all_rules:
                all_quotes = await self._fetch_all_quotes()

            # 2.5 辅助信号预警（type=aux）：逐股算 K 线指标，得到 aux_* 预警字段
            aux_quotes: dict[str, dict] = {}
            aux_rules = [r for r in rules if r.get("type") == "aux"]
            if aux_rules:
                aux_syms: set[str] = set()
                for r in aux_rules:
                    if r.get("scope") == "symbols":
                        aux_syms.update(str(s) for s in r.get("symbols", []) if s)
                    else:  # watchlist
                        aux_syms.update(watchlist_by_rule.get(r["id"], []))
                if aux_syms:
                    aux_quotes = await self._fetch_aux_fields(list(aux_syms))

            for rule in rules:
                scope = rule.get("scope", "symbols")
                if scope == "all":
                    quotes = all_quotes
                    symbols = list(quotes.keys())
                elif scope == "watchlist":
                    quotes = symbol_quotes
                    symbols = watchlist_by_rule.get(rule["id"], [])
                else:
                    quotes = symbol_quotes
                    symbols = [str(s) for s in rule.get("symbols", []) if s]
                for sym in symbols:
                    q = quotes.get(sym)
                    if not q:
                        continue
                    # 辅助信号规则：把 aux_* 预警字段合入行情字典（无 K 线算不出则跳过）
                    if rule.get("type") == "aux":
                        af = aux_quotes.get(sym)
                        if not af:
                            continue
                        q = {**q, **af}
                    hit_fields = self._rule_hits(q, rule)
                    if not hit_fields:
                        continue
                    key = (rule["id"], sym)
                    last = self._last_fire.get(key)
                    if last is not None and (now - last) < rule.get("cooldown_seconds", 3600):
                        continue
                    self._last_fire[key] = now
                    name = q.get("name") or sym
                    pct = q.get("pct_chg")
                    price = q.get("price")
                    message = rule.get("message") or self._default_message(
                        rule, name, pct, price, hit_fields,
                    )
                    events.append({
                        "ts": int(now * 1000),
                        "rule_id": rule["id"],
                        "rule_name": rule.get("name", ""),
                        "source": rule.get("type", "signal"),
                        "rule_type": rule.get("type", "signal"),
                        "symbol": sym,
                        "name": name,
                        "message": message,
                        "price": price,
                        "change_pct": pct,
                        "signals": [f for f in hit_fields if _is_signal_field(f)],
                        "severity": rule.get("severity", "info"),
                        "conditions": rule.get("conditions", []),
                        "logic": rule.get("logic", "and"),
                    })

            if events:
                await db[self.alerts_coll].insert_many(events)
                logger.info(f"✅ 监控评估: 检查 {len(rules)} 条规则, 触发 {len(events)} 条")

            # tbs 规则：把三买三卖信号落为待确认指令（独立于行情布尔评估）
            try:
                await self.scan_tbs_instructions()
            except Exception as e:
                logger.error(f"❌ 三买三卖指令生成失败: {e}", exc_info=True)

            return len(events)
        except Exception as e:
            logger.error(f"❌ 监控评估失败: {e}", exc_info=True)
            return 0


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


# 全局实例
monitor_service = MonitorService()