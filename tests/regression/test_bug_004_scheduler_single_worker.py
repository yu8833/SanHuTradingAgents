"""
Bug-004 防回归测试：APScheduler 多 worker 实例冲突

根因：Dockerfile.backend 里 uvicorn 以 --workers 4 启动，每个 worker 进程都会创建独立的
      AsyncIOScheduler 实例，任务被重复触发、抢占，导致"一键更新卡住"、任务执行混乱。

修复：--workers 1，单 worker 进程内跑调度器。

本测试：静态扫描 Dockerfile 和 docker-compose，确认 workers 只能是 1。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _all_uvicorn_workers_values() -> list[tuple[str, int, str]]:
    """扫描所有配置文件，提取 uvicorn --workers N 里的 N。"""
    candidates = [
        "Dockerfile.backend",
        "docker-compose.yml",
        "docker-compose.hub.nginx.yml",
    ]
    hits = []
    for rel in candidates:
        fp = PROJECT_ROOT / rel
        if not fp.exists():
            continue
        for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
            # 匹配 shell 格式：--workers 4
            m = re.search(r"--workers\s+(\d+)", line)
            if m:
                hits.append((rel, i, m.group(1)))
            # 匹配 JSON 数组格式：--workers", "4" 或 --workers", "4
            m_json = re.search(r'--workers["\']?,?\s*["\']?(\d+)', line)
            if m_json:
                val = m_json.group(1)
                if not hits or hits[-1][2] != val:
                    hits.append((rel, i, val))
            # 也查 docker-compose command: 里的 workers: N（YAML 配置）
            m2 = re.search(r"(?i)workers[:=]\s*(\d+)", line)
            if m2 and "uvicorn" in line.lower():
                hits.append((rel, i, m2.group(1)))
    return hits


def test_uvicorn_workers_must_be_1():
    """任何 uvicorn 启动入口的 --workers 都必须为 1，否则 APScheduler 多实例冲突。"""
    hits = _all_uvicorn_workers_values()
    assert hits, "未找到任何 uvicorn --workers 配置，测试覆盖不足，请手动确认。"
    bad = [(f, ln, val) for (f, ln, val) in hits if int(val) != 1]
    assert not bad, (
        "发现非 1 的 uvicorn workers 配置，多 worker 会引发 APScheduler 重复任务冲突"
        f"（bug-004）。违规位置: {bad}"
    )
