"""
个股趋势「当日帧」防回归测试（market_quotes 主源 + clist 增强）。

背景（2026-09-23）：当日帧曾以东财 clist 60 页抓取为主源，push2 行情域风控
（连接重置/限流）导致 clist 抓不全甚至为空 → 当日帧股票数在 14/1755/5567 之间
漂移，且 PE 双口径（clist 动态 PE vs 历史 pe_ttm）混在同一帧内不可比。

修复：当日帧改以 market_quotes 当日实时全量为主源（120s 采集轮，全市场统一口径），
clist 仅作增强（实时 f62 / 实时现价 / 名称行业），失败或抓不全不影响帧完整性；
pe 统一取 pe_ttm（与历史帧一致）；main 仍按「clist f62 → 当日 moneyflow → None」。

测试要点：
    - 帧完整性不依赖 clist（clist 空/部分成功时帧仍为 market_quotes 全量）
    - 停牌/无成交额（amount<=0）占位记录不入帧
    - pe 单一口径：clist 提供 pe 也不覆盖 TTM
    - main：f62 > 当日 moneyflow > None
    - meta/price：clist 提供的名称/实时价优先，否则 basic/close 兜底
"""
import asyncio

import pytest

pytestmark = [pytest.mark.unit]

_TD = "20260923"


def _market_docs():
    """market_quotes 当日全量（含一只 amount=0 的停牌占位）。"""
    return [
        {"trade_date": _TD, "code": "000001", "pct_chg": 0.5, "amount": 1e8, "close": 10.0},
        {"trade_date": _TD, "code": "600000", "pct_chg": 1.0, "amount": 2e9, "close": 15.0},
        {"trade_date": _TD, "code": "000002", "pct_chg": 0.0, "amount": 0, "close": 5.0},
        {"trade_date": _TD, "code": "300001", "pct_chg": 2.0, "amount": 3e8, "close": 20.0},
    ]


def _basic_docs():
    return [
        {"source": "tushare", "code": "000001", "name": "平安银行", "industry": "银行",
         "pe_ttm": 5.0, "turnover_rate": 1.2, "total_mv": 2000.0},
        {"source": "tushare", "code": "600000", "name": "浦发银行", "industry": "银行",
         "pe_ttm": 10.0, "turnover_rate": 2.0, "total_mv": 3000.0},
        {"source": "tushare", "code": "000002", "name": "万 科Ａ", "industry": "房地产",
         "pe_ttm": 8.0, "turnover_rate": 0.5, "total_mv": 1500.0},
        {"source": "tushare", "code": "300001", "name": "特锐德", "industry": "电气设备",
         "pe_ttm": 30.0, "turnover_rate": 3.0, "total_mv": 800.0},
    ]


def _fake_col_factory(market_docs, basic_docs):
    def _fake_col(name):
        if name == "market_quotes":
            return _FakeCollection(list(market_docs))
        return _FakeCollection(list(basic_docs))
    return _fake_col


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def __aiter__(self):
        for d in self._docs:
            yield d


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *_a, **_k):
        return _FakeCursor(list(self._docs))


def _run(monkeypatch, today_mf=None, snapshot=None, today_zt=None,
         market_docs=None, basic_docs=None):
    import app.services.stock_quadrant_analysis as sq

    monkeypatch.setattr(sq, "col", _fake_col_factory(
        market_docs if market_docs is not None else _market_docs(),
        basic_docs if basic_docs is not None else _basic_docs(),
    ))
    return asyncio.run(sq._build_today_frame(
        today_mf or {}, snapshot or [], today_zt or {}
    ))


def _snapshot_row(code="000001", main=1e7, pe=99.0, price=10.5, **kwargs):
    """构造 clist 快照行（main=元，pe 模拟动态 PE，price 模拟实时现价）。"""
    row = {"code": code, "name": f"股票{code}", "price": price, "pct": 0.5,
           "amount": 1e8, "turn": 1.2, "pe": pe, "mv": 5e9,
           "main": main, "industry": "测试行业"}
    row.update(kwargs)
    return row


# ========================================================================
# Axiom 1：帧完整性不依赖 clist —— 当日帧 = market_quotes 有成交额的全量
# ========================================================================

def test_today_frame_complete_without_clist(monkeypatch):
    """clist 完全不可用（空）→ 当日帧仍包含 market_quotes 全部有成交额股票。"""
    out = _run(monkeypatch, snapshot=[])
    assert set(out["frame"].keys()) == {"000001", "600000", "300001"}
    assert "000002" not in out["frame"]  # amount=0 停牌占位不入帧


def test_today_frame_complete_with_partial_clist(monkeypatch):
    """clist 只抓到部分股票 → 帧仍完整（缺失股票用 market_quotes 补齐）。"""
    sn = [_snapshot_row("000001", main=1e7)]
    out = _run(monkeypatch, snapshot=sn)
    assert set(out["frame"].keys()) == {"000001", "600000", "300001"}


def test_today_frame_excludes_zero_amount(monkeypatch):
    """amount<=0 的占位记录一律不入帧（总数口径=全市场有成交额）。"""
    out = _run(monkeypatch)
    assert len(out["frame"]) == 3
    assert all(out["frame"][c][1] > 0 for c in out["frame"])  # amt(亿)>0


# ========================================================================
# Axiom 2：pe 单一口径 —— 一律 pe_ttm，clist 动态 PE 不覆盖
# ========================================================================

def test_today_frame_pe_uses_ttm_not_clist_dynamic(monkeypatch):
    """clist 携带动态 PE(99.0) → 帧内 pe 仍然取 stock_basic_info 的 pe_ttm(5.0)。"""
    import app.services.stock_quadrant_analysis as sq

    sn = [_snapshot_row("000001", main=1e7, pe=99.0)]
    out = _run(monkeypatch, snapshot=sn)
    assert out["frame"]["000001"][sq.IDX_PE] == 5.0


# ========================================================================
# Axiom 3：main 优先级 = clist f62 > 当日 moneyflow > None
# ========================================================================

def test_today_frame_main_prefers_clist_f62(monkeypatch):
    import app.services.stock_quadrant_analysis as sq

    sn = [_snapshot_row("000001", main=1e7)]
    out = _run(monkeypatch, today_mf={"000001": 5e7}, snapshot=sn)
    assert out["frame"]["000001"][sq.IDX_MAIN] == 0.1  # 1e7 元 = 0.1 亿


def test_today_frame_main_falls_back_to_moneyflow(monkeypatch):
    """f62 缺失 → 回填当日已入库 moneyflow（真实值，非估计）。"""
    import app.services.stock_quadrant_analysis as sq

    sn = [_snapshot_row("000001", main=None)]
    out = _run(monkeypatch, today_mf={"000001": 5e7}, snapshot=sn)
    assert out["frame"]["000001"][sq.IDX_MAIN] == 0.5


def test_today_frame_main_moneyflow_without_clist(monkeypatch):
    """clist 整体不可用 → main 回填 moneyflow（原 fallback 链路等价）。"""
    import app.services.stock_quadrant_analysis as sq

    out = _run(monkeypatch, today_mf={"000001": 5e7}, snapshot=[])
    assert out["frame"]["000001"][sq.IDX_MAIN] == 0.5


def test_today_frame_main_none_when_no_source(monkeypatch):
    """f62 与 moneyflow 皆无 → main 置 None（不估计）。"""
    import app.services.stock_quadrant_analysis as sq

    sn = [_snapshot_row("000001", main=None)]
    out = _run(monkeypatch, snapshot=sn)
    assert out["frame"]["000001"][sq.IDX_MAIN] is None


def test_today_frame_main_skips_missing_moneyflow_entry(monkeypatch):
    """f62 缺失且 moneyflow 无该 code → main 置 None（不估计）。"""
    import app.services.stock_quadrant_analysis as sq

    sn = [_snapshot_row("000001", main=None)]
    out = _run(monkeypatch, today_mf={"600519": 1e7}, snapshot=sn)
    assert out["frame"]["000001"][sq.IDX_MAIN] is None


# ========================================================================
# Axiom 4：board / meta / price 联动
# ========================================================================

def test_today_frame_board_from_zt_pool(monkeypatch):
    import app.services.stock_quadrant_analysis as sq

    out = _run(monkeypatch, today_zt={"600000": 2})
    assert out["frame"]["600000"][sq.IDX_BOARD] == 2
    assert out["frame"]["000001"][sq.IDX_BOARD] is None  # 非涨停股


def test_today_frame_price_and_meta_prefer_clist(monkeypatch):
    """clist 提供实时价/名称行业时优先；缺失时回退 basic/close。"""
    sn = [_snapshot_row("000001", price=10.5)]
    out = _run(monkeypatch, snapshot=sn)
    assert out["price"]["000001"] == 10.5                # clist 实时价优先
    assert out["price"]["600000"] == 15.0                # 其余回退 market_quotes.close
    assert out["meta"]["000001"]["name"] == "股票000001"  # clist 名称优先
    assert out["meta"]["600000"]["name"] == "浦发银行"    # 无 clist → basic 兜底