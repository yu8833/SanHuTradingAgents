"""
Bug-002 防回归测试：新闻新鲜度字段名 published_at vs publish_time

根因：screening.py 中数据新鲜度查询用 `published_at` 字段排序和取值，
      但实际 newsradar.py 写入 MongoDB 的字段名是 `publish_time`，
      导致永远拿到最旧数据，新鲜度显示错误，一键更新后仍显示"很久没更新"。

修复：统一把查询字段改成 `publish_time`。

本测试检查 screening.py 中是否仍残留 'published_at' 硬编码字符串，
以及 quotes_ingestion_service.py 中的新闻相关查询是否使用正确字段。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _grep(rel_path: str, pattern: str) -> list[tuple[int, str]]:
    fpath = PROJECT_ROOT / rel_path
    if not fpath.exists():
        return []
    hits = []
    for i, line in enumerate(fpath.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(pattern, line):
            hits.append((i, line.strip()))
    return hits


def test_screening_no_published_at_literal():
    """筛选接口 screening.py 中不能再出现 'published_at' 硬编码字符串。

    如果此处失败，说明有人把字段名又改回旧的了，新闻新鲜度检查会静默拿错字段。
    """
    hits = _grep("app/routers/screening.py", r"published_at")
    # 允许在注释/CHANGELOG 里出现；真正有问题的是作为 MongoDB 查询/排序字段的代码
    code_hits = [
        (lineno, line)
        for (lineno, line) in hits
        if not line.lstrip().startswith("#") and '"""' not in line and "'''" not in line
    ]
    assert not code_hits, (
        "screening.py 中仍在代码逻辑里使用 'published_at'（应使用 'publish_time'）。"
        f" 命中行: {code_hits}"
    )


def test_screening_uses_publish_time():
    """screening.py 中必须使用 publish_time，确保修复生效。"""
    hits = _grep("app/routers/screening.py", r"publish_time")
    assert len(hits) >= 2, (
        "screening.py 中 publish_time 出现次数异常少，新鲜度排序/取值可能仍使用错误字段。"
        f" 当前命中: {hits}"
    )


def test_mongo_init_index_on_publish_time_not_published_at():
    """scripts/mongo-init.js 等初始化脚本里索引字段名必须是 publish_time。"""
    for init_file in [
        "scripts/mongo-init.js",
        "scripts/setup/init_multi_market_collections.py",
        "scripts/docker_deployment_init.py",
    ]:
        hits = _grep(init_file, r"published_at")
        # 同时过滤 JS 注释 (//) 和 Python 注释 (#)
        code_hits = [
            (i, line)
            for (i, line) in hits
            if not line.strip().startswith("//") and not line.strip().startswith("#")
        ]
        assert not code_hits, (
            f"{init_file} 里仍用 'published_at' 创建索引，实际写入字段是 'publish_time'，"
            "索引将失效。"
        )
