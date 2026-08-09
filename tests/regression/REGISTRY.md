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
| 010 | 股票详情页周末显示"数据已过期2天"误导用户 | 前端 `getDataExpiredDays` 用自然日差值判断过期，后端未返回 `stale_days`。项目中有 6+ 处碎片化的"周末判断"但全部只查 `weekday()` 不查节假日。 | frontend/src/views/Stocks/Detail.vue, app/utils/trading_time.py | test_bug_010_holiday_check.py | (本轮) | ✅ |
| 011 | 回测交易价格与K线数据不一致（603186卖出价超出当天 [low, high]） | 分批减仓后最终清仓时 sell_price=跨日期加权均价avg_sell，该均价无法落在清仓日当天K线区间；同时入库层缺少OHLC校验。 | app/services/three_buys_three_sells_service.py | test_bug_011_data_contract.py | (本轮) | ✅ |
| 012 | **688669 成交额显示 2.41 万，实际应为 241.29 万**：全局 amount/volume 单位混乱** | 缺少「数据契约」缺失：每条链路各自做单位转换（Tushare千元→万元直接入库、AKShare元÷10000→万元、Tushare rt_k×0.1→万元、Tushare pro_bar×0.1→万元），前端 fmtAmount 再按"元"除10000，多次乘除叠加 → 数值错乱。统一口径：后端入库/API返回 amount=永远是元，volume永远是股；临时中间变量 amount_wan(万元)仅用在 quotes_service 内立即 ×10000 转元输出；前端 Screening 阈值×10000 改为元量级。 | historical_data_service.py, tushare_adapter.py(rt_k+pro_bar), akshare_adapter.py, unified_quotes.py, quotes_service.py, database_screening_service.py, Screening/index.vue | test_bug_012_amount_unit_conversion.py | (本轮) | ✅ |
| 017 | 回测任务提示"任务不存在或已过期" | 异步回测任务注册表是纯进程内存 dict，多 worker / 进程重启后任务丢失，get(task_id) 返回 None | app/strategy_system/task_manager.py | test_bug_017_backtest_task_redis.py | (本轮) | ✅ |
| 018 | 低估值高股息策略回测提示"在指定区间内未产生买入信号" | `_low_pe_high_dividend_leader` 行业龙头用 `grp.head(top_n)` 按"行"而非"只股票"取数：筛选侧每股票仅1行正常，回测多日面板每股票多行，排序后误取同一只股票的多行，正式区间 0 信号 | app/strategy_system/strategies.py | test_bug_018_backtest_leader_topn.py | (本轮) | ✅ |
| 019 | 回测期末强制平仓价=买入价，期末盈亏恒为0 | `_simulate_portfolio` 期末强制平仓 `px = pos["entry_price"]` 直接用建仓价结算，未用最后交易日收盘价 → 买入价==卖出价，total_return 失真 | app/strategy_system/backtest.py | test_bug_019_backtest_end_liquidation.py | (本轮) | ✅ |
| 020 | 回测估值用最新快照按日广播，估值变化无法触发卖出；**前端仅传空 params 时估值退出被静默跳过，策略全程持有** | `_enrich_panel_fundamentals` 用最新快照 pe_ttm/pb/total_mv 按 symbol 广播到所有日期行；且 `_entry_exit_mask` 仅在 params 明确含 max_pe/max_pb 键时才生成估值退出掩码，调用方传空 params（`{}`）时退出逻辑失效 → 依赖估值条件的策略买在起点卖在终点、全部持仓持有到期末 | app/strategy_system/backtest.py, app/worker/tushare_sync_service.py | test_bug_020_backtest_daily_valuation.py | (本轮) | ✅ |

---

## 状态说明

- ✅ **测试已通过**：已写入防回归测试并能在当前套件中跑通
- ⏳ **正在编写**：bug 已修复但防回归测试仍在编写中
- ❌ **已复发**：测试失败，说明对应 bug 又出现了，需立即定位

## 新增 bug 流程

1. 修复代码 → 2. 创建 `tests/regression/test_bug_XXX_描述.py`（标记 `@pytest.mark.regression`）
3. 在上方表格新增一行 → 4. 本地 `pytest -m regression` 全通 → 5. 提交 PR
