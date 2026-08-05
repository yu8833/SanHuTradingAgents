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
  - symbols: 指定标的（用 unified_quotes 实时行情，字段全）
  - all:     全市场（用 market_quotes 已入库快照，字段为 close/pct_chg/amount）

冷却机制：同一 (rule_id, symbol) 在 cooldown_seconds 内不重复触发。

存储：
  - 规则:  monitor_rules 集合
  - 触发记录: monitor_alerts 集合（含 severity/message/price 等，按创建时间倒序）
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pydantic import BaseModel

from app.core.database import get_mongo_db
from app.utils.trading_time import is_trading_time

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────
ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
RULE_TYPES = {"signal", "price", "market"}
SCOPES = {"symbols", "all"}
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
    type: str          # signal | price | market
    scope: str = "symbols"   # symbols | all
    symbols: list[str] = []
    conditions: list[ConditionModel] = []
    logic: str = "and"        # and | or
    cooldown_seconds: int = 3600
    severity: str = "info"    # info | warn | critical
    message: str = ""


# ── 校验 ────────────────────────────────────────────────
def _is_signal_field(field: str) -> bool:
    return any(field.startswith(p) for p in TRUTH_SIGNALS)


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
    if rule.get("scope") == "symbols":
        syms = rule.get("symbols")
        if not isinstance(syms, list) or len(syms) == 0:
            raise ValueError("scope=symbols 时 symbols 不能为空")
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
    r.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    return r


# ── 服务 ────────────────────────────────────────────────
class MonitorService:
    """监控服务：规则 CRUD + 行情评估 + 告警存储。"""

    def __init__(self):
        self.db = None
        self.rules_coll = "monitor_rules"
        self.alerts_coll = "monitor_alerts"
        # (rule_id, symbol) -> 上次触发时间(秒)。内存态，重启后重置。
        self._last_fire: dict[tuple[str, str], float] = {}

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def ensure_indexes(self) -> None:
        db = await self._get_db()
        await db[self.rules_coll].create_index("id", unique=True)
        await db[self.alerts_coll].create_index([("ts", -1)])

    # ── 规则 CRUD ─────────────────────────────────────
    def _serialize(self, doc: dict[str, Any]) -> dict[str, Any]:
        if doc is None:
            return None
        result = dict(doc)
        if "_id" in result:
            result["id"] = str(result["_id"])
            del result["_id"]
        return result

    async def list_rules(self) -> list[dict]:
        db = await self._get_db()
        cursor = db[self.rules_coll].find({}).sort("created_at", -1)
        docs = await cursor.to_list(length=None)
        rules = []
        for d in docs:
            r = dict(d)
            r.pop("_id", None)
            rules.append(r)
        return rules

    async def save_rule(self, rule: dict) -> dict:
        db = await self._get_db()
        rule = normalize(rule)
        validate(rule)
        existing = await db[self.rules_coll].find_one({"id": rule["id"]})
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
            label = THRESHOLD_FIELDS.get(field) or SIGNAL_FIELDS.get(field) or field
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
            symbol_rules = [r for r in rules if r.get("scope") == "symbols"]
            all_rules = [r for r in rules if r.get("scope") == "all"]

            # 1. 指定标的：取并集按 unified_quotes
            symbol_quotes: dict[str, dict] = {}
            if symbol_rules:
                syms = list({str(s) for r in symbol_rules for s in r.get("symbols", []) if s})
                symbol_quotes = await self._fetch_symbol_quotes(syms)

            # 2. 全市场：从 market_quotes 读取
            all_quotes: dict[str, dict] = {}
            if all_rules:
                all_quotes = await self._fetch_all_quotes()

            for rule in rules:
                scope = rule.get("scope", "symbols")
                quotes = symbol_quotes if scope == "symbols" else all_quotes
                if scope == "symbols":
                    symbols = [str(s) for s in rule.get("symbols", []) if s]
                else:
                    symbols = list(quotes.keys())
                for sym in symbols:
                    q = quotes.get(sym)
                    if not q:
                        continue
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