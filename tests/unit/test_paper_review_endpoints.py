"""交易复盘 review 端点回归测试（内存假库，不依赖真实 MongoDB）。

覆盖本次修复与新增功能：
- list_review_notes 必须把 _id 转成字符串 id 返回（前端编辑/删除依赖；缺失会导致
  删除请求打到 /notes/undefined → ObjectId(undefined) 抛 InvalidId → 500）
- list_review_notes 过滤「交易记录移除」的 dismissed 隐藏标记
- review_trades 返回 id/buy_id 与 handled 标记；已删除周期从全量剔除（影响胜率/盈亏统计），
  已复盘周期保留计入但标记 handled（列表隐藏、统计保留）
- delete_review_trade 写 dismissed 隐藏标记、幂等、无效 ID 返回 400；
  $set/$setOnInsert 同路径冲突须抛 WriteError（防 Mongo code=40 回归）
- delete_review_note 可按 list 返回的 id 正常删除；不存在返回 404
"""
import asyncio

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import WriteError

from app.routers.paper import (
    delete_review_note,
    delete_review_trade,
    list_review_notes,
    review_trades,
)

# ---------------------------- 假 MongoDB（支持 find/sort/to_list/find_one/insert/delete/update-upsert） ----------------------------

def _match(doc: dict, query: dict) -> bool:
    """支持等值、$ne、$nin 的极简查询匹配（缺失字段视为 null，与 Mongo 对齐）。"""
    for key, cond in query.items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, target in cond.items():
                if op == "$ne":
                    if val == target:
                        return False
                elif op == "$nin":
                    if val in target:
                        return False
                else:
                    raise AssertionError(f"测试不支持的操作符: {op}")
        else:
            if val != cond:
                return False
    return True


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs
        self._sort = None

    def sort(self, key, direction):
        self._sort = (key, direction)
        return self

    async def to_list(self, _length=None):
        # 深拷贝：后端 list 逻辑会 pop _id，不能污染集合内真实 doc
        docs = [dict(d) for d in self._docs]
        if self._sort:
            key, direction = self._sort
            docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return docs


class _FakeColl:
    def __init__(self, seed):
        self._docs = [dict(d) for d in seed]

    def find(self, query):
        return _FakeCursor([d for d in self._docs if _match(d, query)])

    async def find_one(self, query):
        for d in self._docs:
            if _match(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        d = dict(doc)
        d["_id"] = ObjectId()
        self._docs.append(d)
        return type("_Ins", (), {"inserted_id": d["_id"]})()

    async def delete_one(self, query):
        for i, d in enumerate(self._docs):
            if _match(d, query):
                del self._docs[i]
                return type("_Del", (), {"deleted_count": 1})()
        return type("_Del", (), {"deleted_count": 0})()

    async def update_one(self, query, update, upsert=False):
        # 复刻 MongoDB：同一路径同时出现在 $set 与 $setOnInsert 会抛 WriteError(code=40)
        set_keys = set((update.get("$set") or {}).keys())
        oninsert_keys = set((update.get("$setOnInsert") or {}).keys())
        conflict = set_keys & oninsert_keys
        if conflict:
            path = sorted(conflict)[0]
            raise WriteError(
                f"Updating the path '{path}' would create a conflict at '{path}'"
            )
        for d in self._docs:
            if _match(d, query):
                d.update(update.get("$set", {}))
                d.update(update.get("$setOnInsert", {}))
                return type("_Upd", (), {"matched_count": 1})()
        if upsert:
            new_doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            new_doc.update(update.get("$set", {}))
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc["_id"] = ObjectId()
            self._docs.append(new_doc)
            return type("_Upd", (), {"matched_count": 0, "upserted_id": new_doc["_id"]})()
        return type("_Upd", (), {"matched_count": 0})()


class _FakeDB:
    def __init__(self, collections: dict):
        self._collections = collections

    def __getitem__(self, name: str):
        return self._collections[name]


def _make_db(collections: dict) -> _FakeDB:
    return _FakeDB(collections)


def _install(monkeypatch, db) -> None:
    monkeypatch.setattr("app.routers.paper.get_mongo_db", lambda: db, raising=True)


def _note(dismissed: bool = False, trade_id: str | None = None, **extra):
    doc = {
        "_id": extra.pop("_id", ObjectId()),
        "user_id": "u1",
        "trade_id": trade_id,
        "code": extra.pop("code", "600000"),
        "name": extra.pop("name", "浦发银行"),
        "lesson": extra.pop("lesson", "别追高"),
        "result": extra.pop("result", "chasing_high"),
        "created_at": "2026-09-01T10:00:00+08:00",
        "updated_at": "2026-09-01T10:00:00+08:00",
        **extra,
    }
    if dismissed:
        doc["dismissed"] = True
    return doc


def _trade(side: str, oid: ObjectId, price: float, ts: str, pnl: float = 0.0, **extra):
    return {
        "_id": oid,
        "user_id": "u1",
        "code": "600000",
        "side": side,
        "price": price,
        "quantity": 100,
        "pnl": pnl,
        "strategy": "ma_golden_cross",
        "stock_name": "浦发银行",
        "timestamp": ts,
        **extra,
    }


# ---------------------------- 用例 ----------------------------

def test_list_review_notes_returns_id_and_filters_dismissed(monkeypatch):
    rid = ObjectId()
    db = _make_db({
        "trade_reviews": _FakeColl([
            _note(_id=rid),
            _note(dismissed=True, trade_id="aa" * 12, lesson=None, result=None),
        ]),
    })
    _install(monkeypatch, db)

    res = asyncio.run(list_review_notes(current_user={"id": "u1"}))
    items = res["data"]["items"]
    assert len(items) == 1, "dismissed 隐藏标记不应出现在复盘笔记列表"
    assert items[0]["id"] == str(rid), "复盘笔记必须返回字符串 id（前端编辑/删除依赖）"
    assert items[0]["code"] == "600000"


def test_delete_review_note_uses_listed_id(monkeypatch):
    db = _make_db({"trade_reviews": _FakeColl([_note()])})
    _install(monkeypatch, db)

    items = asyncio.run(list_review_notes(current_user={"id": "u1"}))["data"]["items"]
    note_id = items[0]["id"]

    res = asyncio.run(delete_review_note(note_id, {"id": "u1"}))
    assert res["success"] is True
    assert asyncio.run(list_review_notes(current_user={"id": "u1"}))["data"]["items"] == []

    with pytest.raises(HTTPException) as ei:
        asyncio.run(delete_review_note(str(ObjectId()), {"id": "u1"}))
    assert ei.value.status_code == 404


def test_review_trades_handled_false_without_review(monkeypatch):
    buy_id, sell_id = ObjectId(), ObjectId()
    db = _make_db({
        "paper_trades": _FakeColl([
            _trade("buy", buy_id, 10.0, "2026-09-01T10:00:00+08:00"),
            _trade("sell", sell_id, 12.0, "2026-09-02T10:00:00+08:00", pnl=200.0),
        ]),
        "trade_reviews": _FakeColl([]),
    })
    _install(monkeypatch, db)

    items = asyncio.run(review_trades(current_user={"id": "u1"}))["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(sell_id)
    assert items[0]["buy_id"] == str(buy_id)
    assert items[0]["handled"] is False


def test_review_trades_handled_true_when_reviewed(monkeypatch):
    """复盘笔记关联（trade_id=卖出流水 id）后周期标记 handled=True。"""
    buy_id, sell_id = ObjectId(), ObjectId()
    db = _make_db({
        "paper_trades": _FakeColl([
            _trade("buy", buy_id, 10.0, "2026-09-01T10:00:00+08:00"),
            _trade("sell", sell_id, 12.0, "2026-09-02T10:00:00+08:00", pnl=200.0),
        ]),
        "trade_reviews": _FakeColl([_note(trade_id=str(sell_id))]),
    })
    _install(monkeypatch, db)

    items = asyncio.run(review_trades(current_user={"id": "u1"}))["data"]["items"]
    assert len(items) == 1
    assert items[0]["handled"] is True


def test_delete_review_trade_writes_dismissed_marker(monkeypatch):
    buy_id, sell_id = ObjectId(), ObjectId()
    reviews_coll = _FakeColl([])
    db = _make_db({
        "paper_trades": _FakeColl([
            _trade("buy", buy_id, 10.0, "2026-09-01T10:00:00+08:00"),
            _trade("sell", sell_id, 12.0, "2026-09-02T10:00:00+08:00", pnl=200.0),
        ]),
        "trade_reviews": reviews_coll,
    })
    _install(monkeypatch, db)

    res = asyncio.run(delete_review_trade(str(sell_id), {"id": "u1"}))
    assert res["success"] is True

    # 删除后周期从全量剔除：列表/统计/图表都不再出现（胜率、累计盈亏受影响）
    items = asyncio.run(review_trades(current_user={"id": "u1"}))["data"]["items"]
    assert items == [], "删除的周期不应再计入复盘统计"
    # 隐藏标记不出现在复盘笔记列表
    notes = asyncio.run(list_review_notes(current_user={"id": "u1"}))["data"]["items"]
    assert notes == []

    # 重复删除幂等
    assert asyncio.run(delete_review_trade(str(sell_id), {"id": "u1"}))["success"] is True

    # 无效 ID → 400
    with pytest.raises(HTTPException) as ei:
        asyncio.run(delete_review_trade("not-a-valid-id", {"id": "u1"}))
    assert ei.value.status_code == 400


def test_delete_review_trade_with_note_only_marks_handled(monkeypatch):
    """已有复盘笔记的周期：删除仅返回成功，周期保留计入统计但标记 handled（列表隐藏）。"""
    buy_id, sell_id = ObjectId(), ObjectId()
    db = _make_db({
        "paper_trades": _FakeColl([
            _trade("buy", buy_id, 10.0, "2026-09-01T10:00:00+08:00"),
            _trade("sell", sell_id, 12.0, "2026-09-02T10:00:00+08:00", pnl=200.0),
        ]),
        "trade_reviews": _FakeColl([_note(trade_id=str(sell_id))]),
    })
    _install(monkeypatch, db)

    res = asyncio.run(delete_review_trade(str(sell_id), {"id": "u1"}))
    assert res["success"] is True
    items = asyncio.run(review_trades(current_user={"id": "u1"}))["data"]["items"]
    assert len(items) == 1, "已复盘周期的交易应保留计入统计"
    assert items[0]["handled"] is True
    # 复盘笔记仍在（未被误标为 dismissed）
    notes = asyncio.run(list_review_notes(current_user={"id": "u1"}))["data"]["items"]
    assert len(notes) == 1