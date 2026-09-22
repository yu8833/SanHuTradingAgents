"""
个股趋势「当日帧」clist 全市场分页 防回归测试。

背景（bug-实测）：东财 clist 单页返回被硬截断为 100 条，total 仍为全市场总数。
旧实现以「单页不足 5000 即停」作为停页条件，导致只取到第一页 100 只
（按代码倒序恰为 920 开头北交所），当日帧只剩 99 只有成交额的股票，
沪/深 A 全部缺失、搜索命中（meta）但图上看不到高亮。

修复：以 total + 首页实际条数推算总页数 → 并发补齐 → 失败页重试 → 总量不足顺延补页。
"""
import threading

import pytest

pytestmark = [pytest.mark.unit]


def _row(code, amount=1e8, name=None, industry=None):
    """构造一条 clist 原始行（f 字段与 _EM_FIELDS 对齐）。"""
    return {
        "f12": code,
        "f14": name or f"股票{code}",
        "f2": 10.0,
        "f3": 0.5,
        "f6": amount,           # 置 None 模拟停牌/无成交额 → 应被过滤
        "f8": 1.2,
        "f9": 20.0,
        "f20": 5e9,
        "f62": 1e7,
        "f100": industry or "测试行业",
    }


class _FakeItem:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"data": self._data}


def _make_fake_session(total, page_size, fail_first_page_2=False):
    """按 pn 返回分页数据（模拟东财当前单页硬截断 page_size 条 + total 全量）。"""
    import requests as real_requests

    n_pages = (total + page_size - 1) // page_size
    pages = {}
    hit = {}
    for pn in range(1, n_pages + 1):
        start = (pn - 1) * page_size
        rows = []
        for idx in range(page_size):
            global_idx = start + idx
            if global_idx >= total:
                break
            # 全球市场第 1 条（000001）置无成交额，验证「有成交额才入帧」过滤
            amount = None if global_idx == 0 else 1e8
            rows.append(_FakeItem(_row(
                f"{global_idx + 1:06d}", amount=amount,
                name=f"名称{global_idx + 1:03d}", industry="测试行业",
            )))
        pages[pn] = rows
        hit[pn] = 0

    class _FakeSession:
        trust_env = True

        def __init__(self):
            self._lock = threading.Lock()

        def get(self, url, params=None, headers=None, timeout=None):
            pn = int((params or {}).get("pn", 1))
            with self._lock:
                hit[pn] = hit[pn] + 1
                if fail_first_page_2 and pn == 2 and hit[pn] == 1:
                    raise real_requests.ConnectionError("mock page2 first fail")
            return _FakeResponse({"total": total, "diff": pages.get(pn, [])})

    _FakeSession.calls = hit
    return _FakeSession


def _expected_codes(total, excluded=("000001",)):
    """全量代码集合中排除无成交额（被过滤）的代码。"""
    return {f"{i:06d}" for i in range(1, total + 1)} - set(excluded)


def test_clist_pagination_collects_all_pages(monkeypatch):
    """单页 100 条、total=250（3 页）时应全部收齐，而非只取第一页 99 条。"""
    import requests

    import app.services.stock_quadrant_analysis as sq

    monkeypatch.setattr(requests, "Session", _make_fake_session(total=250, page_size=100), raising=True)

    rows = sq._fetch_clist_snapshot()

    codes = {r["code"] for r in rows}
    assert len(rows) == len(codes) == 249, f"应收齐 249 条（250-无成交额1条），实际 {len(rows)} 条"
    assert codes == _expected_codes(250), "代码集合应与全市场一致（含末页 000251 之前全部）"
    assert "000250" in codes, "末页截断条必须包含"
    assert "000001" not in codes, "无成交额股票应被过滤"


def test_clist_pagination_retries_failed_page(monkeypatch):
    """并发拉取中某页首次失败 → 顺序重试后仍应收齐全量。"""
    import requests

    import app.services.stock_quadrant_analysis as sq

    fake = _make_fake_session(total=250, page_size=100, fail_first_page_2=True)
    monkeypatch.setattr(requests, "Session", fake, raising=True)

    rows = sq._fetch_clist_snapshot()

    codes = {r["code"] for r in rows}
    assert len(codes) == 249, f"失败页重试后应收齐 249 条，实际 {len(rows)} 条"
    assert codes == _expected_codes(250)
    assert fake.calls[2] >= 2, "第 2 页首次失败后应至少重试一次"


def test_clist_pagination_single_page(monkeypatch):
    """total ≤ 单页容量时，仅首页即收齐。"""
    import requests

    import app.services.stock_quadrant_analysis as sq

    monkeypatch.setattr(requests, "Session", _make_fake_session(total=80, page_size=100), raising=True)

    rows = sq._fetch_clist_snapshot()
    codes = {r["code"] for r in rows}
    assert len(rows) == 79 and len(codes) == 79, f"应收齐 79 条，实际 {len(rows)} 条"