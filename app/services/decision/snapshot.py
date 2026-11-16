"""构建决策快照（唯一含 IO 的部分）。

把环境闸门、今日结论方向、B2 信号、观察池、双账本持仓、账户现金拼成一个
不可变 Snapshot；后续 decide() 完全按规则执行，便于回测与复现。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from app.core.collections import Collections
from app.core.industry import OTHER_THS, normalize_to_ths
from app.services.cache_layer import cached
from app.services.cockpit import gate_service, position_service
from app.services.decision.models import Candidate, Direction, Holding, Snapshot
from app.services.industry_dashboard import get_industry_period_flows
from app.services.intraday_guide_service import (
    _advice_for,
    _load_open_positions,
    evaluate_sell_signal,
)
from app.utils.timezone import now_tz
from app.utils.trading_time import get_latest_trade_day, get_market_trade_date, is_trading_day

logger = logging.getLogger(__name__)


def _is_intraday(now: datetime) -> bool:
    if not is_trading_day(now.strftime("%Y%m%d")):
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 25) <= minutes <= (15 * 60 + 5)


def _fmt_trade_date(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else str(raw)


def _valid_signal_days(now: datetime) -> set[str]:
    """买入信号只对「当前交易日」有效。

    盘中：今日 + 最近已完成交易日（昨日盘后信号用于今日执行）；
    盘前/休息日：市场参考日与最近已完成交易日一致。
    """
    return {
        get_market_trade_date(now).strftime("%Y-%m-%d"),
        get_latest_trade_day(now).strftime("%Y-%m-%d"),
    }


def _ths_industry(doc: dict) -> str:
    return normalize_to_ths(doc.get("ths_industry") or doc.get("industry"))


def _safe_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _accum_reasons(doc: dict) -> tuple[dict, ...]:
    """观察池积累区四条件 → 可展开依据。"""
    reasons: list[dict] = []
    sideways = doc.get("sideways_days")
    volp = doc.get("volatility_pctile")
    conv = doc.get("converge_ratio")
    amount = doc.get("avg_amount_20d")
    if sideways is not None:
        reasons.append({"kind": "trend", "text": f"形态：横盘 {int(sideways)} 日未创新低（60 日低点之上，筹码在积累）"})
    if volp is not None:
        reasons.append({"kind": "trend", "text": f"波动收敛：20 日年化波动率处于自身 250 日的 {volp * 100:.0f}% 分位（阈值 <40%）"})
    if conv is not None:
        reasons.append({"kind": "trend", "text": f"振幅收敛：近 15 日均振幅 / 60 日均振幅 = {conv:.2f}（阈值 ≤0.9）"})
    if amount is not None:
        reasons.append({"kind": "liquidity", "text": f"流动性：20 日日均成交额 {amount / 1e8:.2f} 亿元（阈值 ≥1 亿）"})
    return tuple(reasons)


def _mainline_map(periods: dict) -> dict[str, dict]:
    net_by_name: dict[str, dict[str, float]] = {}
    pct_by_name: dict[str, float] = {}
    for key in ("3", "5", "10", "20"):
        for row in periods.get(key) or []:
            name = row.get("name")
            if not name:
                continue
            net_by_name.setdefault(name, {})[key] = row.get("net") or 0
            if key == "3":
                pct_by_name[name] = row.get("pct") or 0
    out: dict[str, dict] = {}
    for name, nets in net_by_name.items():
        streak = 0
        for key in ("3", "5", "10", "20"):
            if nets.get(key, 0) > 0:
                streak = int(key)
            else:
                break
        out[name] = {
            "streak": streak,
            "net_3d": nets.get("3", 0),
            "pct_3d": pct_by_name.get(name, 0),
            "is_mainline": streak >= 3,
        }
    return out


async def _gate_cached(db) -> dict:
    async def _build() -> dict:
        return await gate_service.build_gate(db)

    return await cached("cockpit:gate", _build, category="market")


async def _current_prices(db, codes: list[str]) -> tuple[dict[str, float], str | None, str]:
    """批量取现价，返回 (价格, 行情日期, 来源 live|close|none)。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}, None, "none"
    now = now_tz()
    if _is_intraday(now):
        try:
            from app.services.quotes_service import get_quotes_service

            quotes = await get_quotes_service().get_quotes(codes)
            got = {c: q["close"] for c, q in quotes.items() if q.get("close")}
            if got:
                return got, None, "live"
        except Exception as exc:
            logger.warning(f"今日待办-实时价获取失败（回退收盘快照）: {exc}")
    try:
        latest = await db[Collections.market_quotes].find_one({}, {"trade_date": 1}, sort=[("trade_date", -1)])
        trade_date = (latest or {}).get("trade_date")
        if not trade_date:
            return {}, None, "none"
        rows = await db[Collections.market_quotes].find(
            {"trade_date": trade_date, "code": {"$in": codes}}, {"code": 1, "close": 1, "_id": 0}
        ).to_list(None)
        return {r["code"]: r["close"] for r in rows if r.get("close")}, _fmt_trade_date(trade_date), "close"
    except Exception as exc:
        logger.warning(f"今日待办-收盘快照读取失败: {exc}")
        return {}, None, "none"


async def _prev_closes(db, codes: list[str], quote_date: str | None) -> dict[str, float]:
    """最近一个早于当前行情日的收盘价（用于计算单日回撤）。"""
    if not codes or not quote_date:
        return {}
    out: dict[str, float] = {}
    for code in codes:
        try:
            row = await db[Collections.market_quotes].find_one(
                {"code": code, "trade_date": {"$lt": quote_date.replace("-", "")}},
                {"close": 1, "_id": 0},
                sort=[("trade_date", -1)],
            )
            if row and row.get("close"):
                out[code] = float(row["close"])
        except Exception:
            continue
    return out


async def _load_market_b2(db, trade_date: str) -> tuple[str | None, list[dict]]:
    latest = await db[Collections.signal_tracking].find_one(
        {"signal_type": "B2", "trigger_date": {"$lte": trade_date}},
        {"trigger_date": 1},
        sort=[("trigger_date", -1)],
    )
    if not latest:
        return None, []
    day = latest.get("trigger_date")
    docs = await db[Collections.signal_tracking].find(
        {"signal_type": "B2", "trigger_date": day}, {"_id": 0}
    ).to_list(300)
    return day, docs


def _direction_from_market(market: dict | None) -> Direction:
    if not market:
        return Direction(note="今日结论尚未生成（后台生成中，下一轮刷新生效）")
    verdict = market.get("verdict") or {}
    status = verdict.get("direction_status")
    attack = tuple(verdict.get("attack_industries") or ())
    avoid = tuple(verdict.get("avoid_industries") or ())
    if status is None:
        # 旧缓存没有结构化字段：有值按 ok，否则明确降级，不当作「无过滤」
        status = "ok" if (attack or avoid) else "unavailable"
    usable = status == "ok"
    return Direction(
        status=status,
        attack=attack,
        avoid=avoid,
        as_of=market.get("as_of"),
        direction=verdict.get("direction"),
        conclusion=verdict.get("conclusion") or "",
        note="" if usable else "今日结论未给出可用的主攻/回避行业（旧缓存或规则兜底），本次未做方向过滤",
    )


def _load_cash(acc: dict) -> float:
    cash = (acc or {}).get("cash")
    if isinstance(cash, dict):
        return float(cash.get("CNY") or 0)
    return float(cash or 0)


def _paper_holding(pos: dict, price: float | None, advice: dict) -> Holding:
    code = pos["code"]
    state = "normal"
    if advice.get("advice") != "持有":
        state = "exit"
    elif any(r.get("kind") == "warn" for r in (advice.get("reasons") or [])):
        state = "warn"
    qty = float(pos.get("quantity") or 0)
    return Holding(
        code=code,
        name=pos.get("name") or code,
        industry=OTHER_THS,
        source="paper",
        state=state,
        quantity=qty,
        market_value=qty * float(price or pos.get("avg_cost") or 0),
        avg_cost=pos.get("avg_cost"),
        current_price=price,
        pnl_pct=advice.get("profit_loss_rate"),
        advice=advice.get("advice") or "持有",
        advice_label=advice.get("advice_label") or "",
        sell_pct=float(advice.get("sell_pct") or 0.0),
        reference_price=advice.get("trigger_price") or price,
        stop_loss_price=advice.get("stop_loss_price"),
        buy_date=pos.get("buy_date"),
        reasons=tuple(advice.get("reasons") or ()),
    )


def _cockpit_holding(pos: dict) -> Holding:
    code = pos["code"]
    state = pos.get("state") or "normal"
    if state not in ("exit", "warn"):
        state = "normal"
    reasons = tuple(
        {"kind": "exit" if state == "exit" else "warn", "text": str(r)}
        for r in (pos.get("reasons") or [])
    )
    return Holding(
        code=code,
        name=pos.get("name") or code,
        industry=normalize_to_ths(pos.get("industry")),
        source="cockpit",
        state=state,
        quantity=None,
        market_value=0.0,
        avg_cost=pos.get("buy_price"),
        current_price=pos.get("current_price"),
        pnl_pct=round((pos.get("pnl_pct") or 0) * 100, 2) if pos.get("pnl_pct") is not None else None,
        advice="离场" if state == "exit" else ("预警" if state == "warn" else "持有"),
        advice_label="",
        sell_pct=1.0 if state == "exit" else 0.0,
        reference_price=pos.get("current_price"),
        stop_loss_price=pos.get("stop_loss_line"),
        position_id=pos.get("id"),
        buy_date=pos.get("buy_date"),
        reasons=reasons,
        t1_locked=bool(pos.get("t1_locked")),
    )


def _merge_holding(old: Holding | None, new: Holding) -> Holding:
    """同码合并：exit 优先于 warn，预警不吞掉离场。"""
    if old is None:
        return new
    if old.state == "exit" and new.state != "exit":
        return replace(old, reasons=old.reasons + new.reasons)
    if new.state == "exit" and old.state != "exit":
        return replace(
            new,
            reasons=new.reasons + old.reasons,
            quantity=new.quantity or old.quantity,
        )
    base = old if old.quantity else new
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in list(old.reasons) + list(new.reasons):
        key = (r.get("kind", ""), r.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
    return replace(base, reasons=tuple(merged))


def _assign_holding_industries(holdings: list[Holding], industry_by_code: dict[str, str]) -> list[Holding]:
    return [
        replace(h, industry=industry_by_code.get(h.code) or h.industry) if h.industry == OTHER_THS else h
        for h in holdings
    ]


async def build_snapshot(db, user_id: str) -> tuple[Snapshot, dict]:
    """构建决策快照 + 页面展示所需的原始环境对象。"""
    now = now_tz()
    trade_date = now.strftime("%Y-%m-%d")
    is_intraday = _is_intraday(now)
    data_quality: list[str] = []

    # 环境闸门（失败降级为黄灯 + degraded）
    try:
        gate = await _gate_cached(db)
    except Exception as exc:
        logger.error(f"今日待办-环境闸门失败: {exc}", exc_info=True)
        gate = {
            "gate": "yellow",
            "label": "轻仓试错",
            "position_hint": "轻仓试错",
            "portrait": None,
            "emotion_phase": {},
            "hint": "环境数据缺失，按轻仓处理",
            "degraded": True,
            "degrade_note": "环境数据缺失，按轻仓处理",
        }

    # 行业主线（失败只影响解释文案）
    mainlines: dict[str, dict] = {}
    try:
        flows = await get_industry_period_flows()
        mainlines = _mainline_map((flows or {}).get("periods") or {})
    except Exception as exc:
        logger.warning(f"今日待办-行业主线失败: {exc}")
        data_quality.append("行业主线数据缺失，主线共振依据不可用")

    # L1 方向：只读缓存，未命中则后台预热，不阻塞页面
    direction = Direction(note="今日结论尚未生成（后台生成中，下一轮刷新生效）")
    try:
        from app.services.market_synthesis import (
            get_cached_market_synthesis,
            warm_market_synthesis,
        )

        market = await get_cached_market_synthesis()
        if market:
            direction = _direction_from_market(market)
        else:
            await warm_market_synthesis()
            data_quality.append("今日结论缓存未就绪，已在后台生成")
    except Exception as exc:
        logger.warning(f"今日待办-今日结论读取失败: {exc}")
        data_quality.append("今日结论读取失败，本次未做方向过滤")
        direction = Direction(note=f"今日结论读取失败：{exc}")

    # 持仓（模拟账本 + 纪律账本）
    try:
        paper_positions = await _load_open_positions(user_id)
    except Exception as exc:
        logger.warning(f"今日待办-模拟持仓读取失败: {exc}")
        paper_positions = []
        data_quality.append("模拟持仓读取失败")
    try:
        cockpit_data = await position_service.list_positions(db, user_id)
    except Exception as exc:
        logger.warning(f"今日待办-纪律持仓读取失败: {exc}")
        cockpit_data = {"items": []}
        data_quality.append("纪律持仓读取失败")
    cockpit_open = [p for p in (cockpit_data.get("items") or []) if p.get("status") == "open"]

    # 观察池（triggered + watching/near）
    try:
        pool_docs = await db[Collections.cockpit_watch_pool].find(
            {"status": {"$in": ["triggered", "watching", "near"]}}, {"_id": 0}
        ).to_list(600)
    except Exception as exc:
        logger.error(f"今日待办-观察池读取失败: {exc}", exc_info=True)
        pool_docs = []
        data_quality.append("观察池读取失败")

    # 全市场 B2
    try:
        b2_day, b2_docs = await _load_market_b2(db, trade_date)
    except Exception as exc:
        logger.error(f"今日待办-全市场 B2 读取失败: {exc}", exc_info=True)
        b2_day, b2_docs = None, []
        data_quality.append("全市场 B2 信号读取失败")

    codes = (
        [d["code"] for d in pool_docs]
        + [p["code"] for p in paper_positions]
        + [p["code"] for p in cockpit_open]
        + [d["code"] for d in b2_docs]
    )
    prices, quote_as_of, price_source = await _current_prices(db, codes)

    # 账户现金
    cash_cny = 0.0
    try:
        acc = await db[Collections.paper_accounts].find_one({"user_id": user_id})
        if not acc:
            data_quality.append("模拟账户未初始化，现金与总资产按 0 处理（需先在模拟交易初始化）")
        cash_cny = _load_cash(acc or {})
    except Exception as exc:
        logger.warning(f"今日待办-账户读取失败: {exc}")
        data_quality.append("模拟账户读取失败，现金按 0 处理")

    held_codes = {p["code"] for p in paper_positions} | {p["code"] for p in cockpit_open}

    # 行业映射（持仓行业用于行业集中度约束）
    industry_by_code: dict[str, str] = {}
    for d in pool_docs:
        industry_by_code[str(d.get("code"))] = _ths_industry(d)
    lookup_codes = list(set(industry_by_code.keys()) | held_codes)
    if lookup_codes:
        try:
            info_rows = await db[Collections.stock_basic_info].find(
                {"symbol": {"$in": lookup_codes}}, {"symbol": 1, "industry": 1, "_id": 0}
            ).to_list(None)
            for r in info_rows:
                industry_by_code.setdefault(str(r.get("symbol")), normalize_to_ths(r.get("industry")))
        except Exception:
            pass

    # ── 卖出结论：先模拟账本，再纪律账本，同码 exit 优先 ──
    merged: dict[str, Holding] = {}
    for pos in paper_positions:
        code = pos["code"]
        try:
            sig = await evaluate_sell_signal(code)
            price = prices.get(code) or (sig or {}).get("close")
            advice = _advice_for(pos, price, sig)
        except Exception as exc:
            logger.warning(f"今日待办-卖出评估失败 {code}: {exc}")
            continue
        h = _paper_holding(pos, price, advice)
        h = replace(h, industry=industry_by_code.get(code) or h.industry)
        merged[code] = _merge_holding(merged.get(code), h)

    for pos in cockpit_open:
        if pos["code"] in merged and merged[pos["code"]].state == "exit":
            continue
        h = _cockpit_holding(pos)
        merged[pos["code"]] = _merge_holding(merged.get(pos["code"]), h)

    holdings = _assign_holding_industries(list(merged.values()), industry_by_code)

    # 总资产 = 现金 + 模拟持仓市值（纪律账本无股数，不计入）
    paper_codes = [p["code"] for p in paper_positions]
    equity = cash_cny + sum(
        float(p.get("quantity") or 0) * float(prices.get(p["code"]) or p.get("avg_cost") or 0)
        for p in paper_positions
    )
    if cockpit_open:
        data_quality.append("纪律持仓无股数，未计入总资产与行业市值")

    # 单日回撤：用上一交易日收盘价还原昨日市值
    day_drawdown_pct = None
    prev = await _prev_closes(db, paper_codes, quote_as_of)
    if paper_codes and quote_as_of and len(prev) == len(set(paper_codes)):
        prev_equity = cash_cny + sum(
            float(p.get("quantity") or 0) * prev[p["code"]] for p in paper_positions
        )
        if prev_equity > 0:
            day_drawdown_pct = round(equity / prev_equity - 1, 4)
    elif paper_codes:
        data_quality.append("缺少上一交易日收盘价，单日回撤纪律未启用")

    # ── 候选：B2（全市场）+ 观察池 ──
    candidates: list[Candidate] = []
    valid_days = _valid_signal_days(now)
    for d in b2_docs:
        code = str(d.get("code") or "")
        if not code:
            continue
        snap = d.get("snapshot") or {}
        signal_close = snap.get("close") or d.get("signal_price")
        price = prices.get(code) or (float(signal_close) if signal_close else None)
        candidates.append(
            Candidate(
                code=code,
                name=d.get("name") or code,
                industry=_ths_industry(d),
                price=float(price) if price else None,
                price_source=price_source if code in prices else ("signal" if price else "none"),
                trigger_price=float(d.get("signal_price") or signal_close or 0) or None,
                source="b2",
                score=_safe_int(snap.get("score")),
                bias60=snap.get("bias60"),
                structure_stop=snap.get("stop_price"),
                trigger_date=_fmt_trade_date(d.get("trigger_date")),
                status="triggered",
                held=code in held_codes,
                stale=_fmt_trade_date(d.get("trigger_date")) not in valid_days,
            )
        )

    for d in pool_docs:
        code = str(d.get("code") or "")
        if not code:
            continue
        status = d.get("status")
        trigger_day = _fmt_trade_date(d.get("last_triggered_date") or d.get("triggered_at"))
        price = prices.get(code)
        if price is None:
            last = d.get("last_price") or d.get("close")
            price = float(last) if last else None
        stale = status == "triggered" and trigger_day not in valid_days
        candidates.append(
            Candidate(
                code=code,
                name=d.get("name") or code,
                industry=_ths_industry(d),
                price=float(price) if price else None,
                price_source=price_source if code in prices else ("signal" if price else "none"),
                trigger_price=float(d.get("trigger_price")) if d.get("trigger_price") else None,
                source="pool",
                score=_safe_int(d.get("signal_score") or d.get("score")),
                bias60=d.get("bias60"),
                structure_stop=d.get("b1_stop_loss_price"),
                trigger_date=trigger_day,
                status="triggered" if status == "triggered" else "watching",
                held=code in held_codes,
                stale=stale,
                reasons=_accum_reasons(d),
            )
        )

    snapshot = Snapshot(
        as_of=now.replace(microsecond=0).isoformat(),
        trade_date=trade_date,
        is_intraday=is_intraday,
        quote_as_of=quote_as_of,
        gate=gate.get("gate") or "yellow",
        gate_label=gate.get("label") or "轻仓试错",
        gate_degraded=bool(gate.get("degraded")),
        gate_position_hint=gate.get("position_hint") or "—",
        direction=direction,
        candidates=tuple(candidates),
        holdings=tuple(holdings),
        cash=cash_cny,
        equity=equity,
        day_drawdown_pct=day_drawdown_pct,
        mainlines=mainlines,
        data_quality=tuple(data_quality),
    )
    extras = {
        "gate": gate,
        "mainlines": mainlines,
        "session": {
            "is_intraday": is_intraday,
            "quote_as_of": quote_as_of,
            "price_source": price_source,
        },
        "account": {"cash_cny": round(cash_cny, 2), "equity": round(equity, 2)},
        "b2_day": _fmt_trade_date(b2_day),
        "valid_signal_days": sorted(valid_days),
    }
    return snapshot, extras
