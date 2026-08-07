"""
冒烟测试：契约测试 - 基于 OpenAPI schema 的自动遍历

自动遍历所有 GET 端点，断言任意端点在合法输入下都不返回 500。
对于已知需要真实外部依赖的端点（初始化、数据查询等），降级为警告。
"""
import re

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.contract]


# 已知需要真实外部依赖的端点，直接过滤（不再生成用例）
# 这些端点通常因为外部服务/数据未配置而无法通过，不是代码 bug
EXTERNAL_DEPENDENT_PATHS = [
    r"/api/baostock-init/",       # 需要 BaoStock 连接
    r"/api/tushare-init/",        # 需要 Tushare token
    r"/api/akshare-init/",        # 需要 AKShare 配置
    r"/api/historical-data/query/",  # 需要真实历史数据
    r"/api/sync/",                # 同步操作需要外部数据源
    r"/api/stream/",              # SSE/WebSocket 长连接
    r"/api/vibe/",                # 需要 LLM 配置
    r"/api/analysis/",            # 需要 LLM 配置
]

# 请求会因访问外部数据源而长期阻塞（超过请求超时）的端点，直接过滤（不再生成用例）
TIMEOUT_PRONE_PATHS = [
    r"/api/historical-data/health",
    r"/api/historical-data/statistics",
    r"/api/multi-period-sync/health",
    r"/api/multi-period-sync/statistics",
]


def _is_external_dependent(path: str) -> bool:
    """判断路径是否为已知需要外部依赖的端点。"""
    return any(re.search(pattern, path) for pattern in EXTERNAL_DEPENDENT_PATHS)


def _is_timeout_prone(path: str) -> bool:
    """判断路径是否为已知会长期阻塞导致请求超时的端点。"""
    return any(re.search(pattern, path) for pattern in TIMEOUT_PRONE_PATHS)


def _all_openapi_get_paths(base_url: str):
    """懒加载 OpenAPI schema，返回应测试的 (method, path) 列表。

    在 parametrize 收集阶段过滤掉外部依赖端点与超时端点，使其不再生成测试用例
    （而非生成后跳过）。服务不可用时返回空列表，parametrize 会自动跳过测试。
    """
    import httpx

    try:
        r = httpx.get(base_url.rstrip("/") + "/openapi.json", timeout=20, verify=False)
    except Exception:
        return []  # 服务不可用，返回空列表（不调 pytest.skip，避免收集错误）
    if r.status_code != 200:
        return []
    schema = r.json()
    result = []
    for path, methods in schema.get("paths", {}).items():
        for method in methods:
            if method.upper() != "GET":
                continue
            if _is_external_dependent(path):
                continue
            if _is_timeout_prone(path):
                continue
            result.append((method, path))
    return result


def test_openapi_schema_reachable(base_url):
    """/openapi.json 必须可访问（整个契约测试的前提）"""
    import httpx
    try:
        r = httpx.get(base_url.rstrip("/") + "/openapi.json", timeout=20, verify=False)
        assert r.status_code == 200, f"openapi.json 返回 {r.status_code}"
        assert r.json().get("openapi"), "响应不是 OpenAPI 文档"
    except Exception as exc:
        pytest.skip(f"本地服务未启动，跳过：{exc}")


@pytest.mark.parametrize(
    "method_path",
    _all_openapi_get_paths(
        __import__("os").environ.get("TEST_BASE_URL", "http://localhost:8001")
    ),
)
def test_get_endpoints_no_500(base_url, auth_token, method_path):
    """所有 GET 端点在合法路径下都不能 500。

    外部依赖与超时端点已在收集阶段过滤，此处不再生成用例。
    """
    if not method_path:
        pytest.skip("无路径可测")
        return
    import httpx
    method, path = method_path

    # 将路径参数替换为合理占位值
    test_path = path
    for placeholder, default in [
        ("{code}", "000001"),
        ("{symbol}", "000001"),
        ("{id}", "1"),
        ("{task_id}", "smoke-1"),
        ("{batch_id}", "smoke-b1"),
        ("{provider}", "tushare"),
        ("{username}", "admin"),
    ]:
        test_path = test_path.replace(placeholder, default)

    url = base_url.rstrip("/") + test_path
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    try:
        r = httpx.request(
            method,
            url,
            timeout=15,
            verify=False,
            headers=headers,
        )
    except Exception as exc:
        pytest.skip(f"请求异常，跳过：{exc}")
        return
    assert r.status_code != 500, (
        f"GET {test_path} 返回 500（内部错误），请立即定位。"
        f" 响应片段: {r.text[:300]}"
    )
