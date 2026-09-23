"""
候选池默认视图（stocks-overview）「全量行业扫描」 单元测试。

验证 get_candidate_stocks_overview：
1. 未传 industries 时：从全量本地行业名单扫描（而非强势 top_n），聚合各行业 B 信号；
2. 只保留 B1/B2/B3，过滤 S 类卖出信号；
3. 分批并发执行不报错（批大小逻辑）；
4. 空行业集 → 返回空；
5. 显式传入 industries 时仍只扫描该集合。

统一 monkeypatch _all_local_industry_names / get_candidate_stocks / Redis，避免真实面板与缓存。
"""
import pytest

pytestmark = [pytest.mark.unit]


def _patch(monkeypatch, ind_names: list[str], signals: dict):
    import app.services.candidate_pool.candidate_pool_service as svc

    monkeypatch.setattr(svc, "_all_local_industry_names", lambda as_of: ind_names)

    async def fake_stocks(industry, limit=30, as_of=None, pool=None, with_timing=True, **kw):
        sigs = signals.get(industry, [])
        items = [
            {
                "code": f"{industry}{i}01",
                "name": f"{industry}股{i}",
                "industry": industry,
                "quality_score": 90 - i,
                "signal_type": s,
            }
            for i, s in enumerate(sigs)
        ]
        return {"as_of": as_of or "", "industry": industry, "items": items, "total": len(items)}

    monkeypatch.setattr(svc, "get_candidate_stocks", fake_stocks)

    async def _no_redis(*a, **k):
        raise RuntimeError("redis down")

    # get_redis_client 在函数内部按模块导入，直接 patch 定义模块
    monkeypatch.setattr("app.core.database.get_redis_client", _no_redis)
    return svc


async def test_overview_all_industries_collects_buy_only(monkeypatch):
    """未传 industries → 全量行业名单扫描，只保留 B 信号，聚合并去重。"""
    svc = _patch(
        monkeypatch,
        ind_names=["电子", "银行", "生物制药"],
        signals={
            # 电子：B2（应入选）+ S3（应剔除）
            "电子": ["B2", "S3", "B1"],
            # 银行：S2（剔除）
            "银行": ["S2"],
            # 生物制药：B3（入选）
            "生物制药": ["B3"],
        },
    )

    r = await svc.get_candidate_stocks_overview(top_n=10, per_industry=3, limit=30)
    items = r["items"]
    types = [it["signal_type"] for it in items]
    assert sorted(types) == ["B1", "B2", "B3"], f"应只保留 B 信号，实际 {types}"
    assert "银行" not in [it["industry"] for it in items], "银行(S2) 不应入选"


async def test_overview_empty_industries(monkeypatch):
    """全量行业名单为空 → 直接返回空，不报错。"""
    svc = _patch(monkeypatch, ind_names=[], signals={})
    r = await svc.get_candidate_stocks_overview()
    assert r["total"] == 0, "空行业集应返回 0"
    assert r["items"] == [], "空行业集应返回空列表"


async def test_overview_explicit_industries_limited(monkeypatch):
    """显式传入 industries → 仅扫描该集合且受 top_n 截断。"""
    svc = _patch(
        monkeypatch,
        ind_names=["电子", "银行", "生物制药", "船舶"],
        signals={
            "电子": ["B2"], "银行": ["B1"], "生物制药": ["B3"], "船舶": ["S2"],
        },
    )
    r = await svc.get_candidate_stocks_overview(top_n=2, per_industry=3, industries=["电子", "银行", "生物制药"])
    inds = {it["industry"] for it in r["items"]}
    assert "船舶" not in inds, "显式行业集外不应扫描"
    assert "生物制药" not in inds, "超出 top_n 截断的行业不应入选"


async def test_overview_batch_execution(monkeypatch):
    """行业数 > 批大小时仍能全部聚合（分批并发路径）。"""
    svc = _patch(
        monkeypatch,
        ind_names=[f"行业{i}" for i in range(20)],
        signals={f"行业{i}": ["B1"] for i in range(20)},
    )
    # 限制 limit=5（每行业最多贡献，去重后总量=5）
    r = await svc.get_candidate_stocks_overview(top_n=10, per_industry=3, limit=5)
    assert len(r["items"]) == 5, f"limit=5 应截断，实际 {len(r['items'])}"
    assert all(it["signal_type"] == "B1" for it in r["items"])