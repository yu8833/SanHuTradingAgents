# 防回归测试库注册表 (Bug Regression Registry)

**使用规范**：每当修复一个 bug，必须立即新增一条记录，同时在 `tests/regression/` 下创建对应的 `test_bug_XXX_*.py`，钉住这个 bug 防止复发。CI 门禁强制要求：每个 bug PR 必须新增 1 条记录 + 1 个测试文件，否则拒绝合入。

---

| Bug ID | 简述 | 根因 | 模块 | 测试文件 | 修复 commit | 状态 |
|--------|------|------|------|----------|-------------|------|
| 001 | SSE 端点 500: `user.role` AttributeError | User 模型只有 `is_admin: bool`，SSE 认证函数误访问不存在的属性 `user.role` | app/routers/sse.py | test_bug_001_sse_user_role.py | 61496ae | ✅ |
| 002 | 新闻数据新鲜度永远显示旧数据 | 筛选接口查询 `published_at`，实际写入字段是 `publish_time`，导致永远拿到历史最旧记录 | app/routers/screening.py | test_bug_002_publish_time_field.py | bdca575 | ✅ |
| 003 | 财务数据同步报错 `str has no attribute get` | `get_fundamentals` 返回纯文本字符串，`_save_financial_data` 直接当 dict 调 `.get()`，未做解析 | app/worker/tushare_sync_service.py | test_bug_003_financial_str_dict_mismatch.py | (待查) | ✅ |
| 004 | 定时任务执行混乱、一键更新卡住 | 后端以 `--workers 4` 启动 uvicorn，每个 worker 都各自创建一个 APScheduler 实例，任务重复执行并抢占 | Dockerfile.backend | test_bug_004_scheduler_single_worker.py | (待查) | ✅ |
| 005 | token 刷新定时器泄漏：每次登录都创建新定时器不清理 | `setupTokenRefreshTimer` 没有返回/保存定时器 ID，登出时无法清除，旧定时器永久存活 | frontend/src/utils/auth.ts | test_bug_005_token_timer_leak.e2e.py | (待查) | ✅ |
| 006 | 登出后 notifications WebSocket 进入空转重连循环 | notifications store watch token 时，token 变空未主动 `ws.close()`，WS 因鉴权失效反复触发自动重连 | frontend/src/stores/notifications.ts | test_bug_006_logout_ws_disconnect.e2e.py | (待查) | ✅ |
| 007 | AI 对话接口 401: token key 不一致 | vibe.ts `chatStream` 写死 `localStorage.getItem('token')`，而全站统一使用 `'auth-token'`，导致 LLM 请求无认证 | frontend/src/api/vibe.ts | test_bug_007_vibe_token_key.e2e.py | (待查) | ✅ |
| 008 | 历史行情导入静默失败，stock_daily_quotes 数据不全 | 跨集合查询 `trade_date` 格式不一致：一方存 "YYYY-MM-DD"，另一方返回 "YYYYMMDD"，导致查不到数据 | app/services/quotes_ingestion_service.py | test_bug_008_trade_date_format.py | (待查) | ✅ |
| 009 | **后端无法启动**：startup_validator.py 抛出 TypeError | Python 3.10 下把内建函数 `callable`（不是类型）直接写在 union `callable | None`，注解求值时报 `unsupported operand for |`。应使用 `collections.abc.Callable` | app/core/startup_validator.py | test_bug_009_callable_type_hint.py | (本轮) | ✅ |

---

## 状态说明

- ✅ **测试已通过**：已写入防回归测试并能在当前套件中跑通
- ⏳ **正在编写**：bug 已修复但防回归测试仍在编写中
- ❌ **已复发**：测试失败，说明对应 bug 又出现了，需立即定位

## 新增 bug 流程

1. 修复代码 → 2. 创建 `tests/regression/test_bug_XXX_描述.py`（标记 `@pytest.mark.regression`）
3. 在上方表格新增一行 → 4. 本地 `pytest -m regression` 全通 → 5. 提交 PR
