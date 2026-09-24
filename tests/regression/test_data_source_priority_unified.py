"""
防回归测试：数据源优先级必须收敛为单一事实来源。

背景：历史上有 3 套互相矛盾的取源优先级实现——
  1. app/strategy_system/data_adapter.py   ["tushare", "baostock", "akshare"]（缺 sina）
  2. three_buys_three_sells / limit_up_pullback  {"tushare":4,"sina":3,"baostock":2,"akshare":1}（sina 排第2）
  3. app/core/data_source_priority.py      ["tushare", "baostock", "akshare", "sina"]（统一口径）
三套顺序不一致会导致不同服务对同一 (code,date) 重复数据选出不同的源，产生口径漂移。

本测试：静态扫描 app/，断言全项目只有 data_source_priority.py 一处定义优先级，
且所有行情读取点都通过统一 source_rank() 判定，防止未来再次引入第二套定义。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent
APP_DIR = PROJECT_ROOT / "app"

# 唯一允许定义优先级的文件
CANONICAL_FILE = "app/core/data_source_priority.py"

# 统一顺序（tushare 最优，sina 兜底）
CANONICAL_ORDER = ["tushare", "baostock", "akshare", "sina"]

# 已知使用统一 source_rank 的读取点（新增读取点必须接入统一常量）
UNIFIED_USERS = [
    "app/strategy_system/data_adapter.py",
    "app/services/three_buys_three_sells_service.py",
    "app/services/limit_up_pullback_service.py",
    "app/services/plan_generation_service.py",
    "app/services/stock_quadrant_analysis.py",
    "app/routers/stocks.py",
    "app/services/quotes_ingestion_service.py",
]


def _iter_py_files():
    for p in APP_DIR.rglob("*.py"):
        yield p


def test_only_one_priority_definition():
    """全项目只允许 data_source_priority.py 定义 DATA_SOURCE_PRIORITY 列表/dict。"""
    bad = []
    for p in _iter_py_files():
        if str(p.relative_to(PROJECT_ROOT)) == CANONICAL_FILE:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        # 匹配 DATA_SOURCE_PRIORITY = [...] 或 {...} 或 _SRC_PRIORITY = {...}
        if re.search(r"(DATA_SOURCE_PRIORITY|_SRC_PRIORITY|_SOURCE_PRIORITY)\s*=\s*(\[|\{)", text):
            bad.append(str(p.relative_to(PROJECT_ROOT)))
    assert not bad, f"发现第二处数据源优先级定义: {bad}"


def test_canonical_order_is_stable():
    """统一常量顺序必须为 tushare > baostock > akshare > sina。"""
    src = (APP_DIR / "core" / "data_source_priority.py").read_text(encoding="utf-8")
    m = re.search(r"DATA_SOURCE_PRIORITY\s*=\s*\[([^\]]+)\]", src)
    assert m, "data_source_priority.py 中未找到 DATA_SOURCE_PRIORITY 列表"
    order = [x.strip().strip('"\'') for x in m.group(1).split(",") if x.strip()]
    assert order == CANONICAL_ORDER, f"统一顺序被改动: {order}，应为 {CANONICAL_ORDER}"


def test_core_readers_use_unified_source_rank():
    """关键行情读取点必须 import 统一 source_rank，禁止本地自建优先级。"""
    missing = []
    for rel in UNIFIED_USERS:
        fp = PROJECT_ROOT / rel
        if not fp.exists():
            missing.append(f"{rel} (文件不存在)")
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        if "source_rank" not in text:
            missing.append(rel)
    assert not missing, f"以下读取点未接入统一 source_rank: {missing}"
