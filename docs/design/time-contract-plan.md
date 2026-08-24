# 时间契约统一方案（Time Contract Unification Plan）

> 本文档是"全系统时间一致性问题"的根治方案，供后续与代码实现逐批比对。
> 目标：把散落的时间处理收拢为**一条单一、可验证的管道**，三层各担其责。
> 推进方式：按批次实施，每批结束后在容器内回归测试，通过后再进入下一批。

---

## 0. 背景与根因

全系统多次出现时间相关 bug：速览数据"过期一天"、历史 K 线 unknown、
K 线缓存失效、T+1 判定错 8 小时等。根因不是某处代码写错，而是：

1. **存储形态混存**：同一时间字段被写成 4 种形态 —— aware datetime、naive 墙钟、
   ISO 字符串(+08:00)、ISO 字符串(无偏移)。
2. **naive 二义性**：MongoDB driver 未开 `tz_aware`，读回为 naive=UTC 墙钟；
   但后端多处按 naive=京时解释，前后端对"无时区字符串"的假设甚至**正好相反**。
3. **字符串/对象混存**：`isoformat()` 把 datetime 写成字符串存库，BSON 比较分类型，
   下游范围/新鲜度查询静默失效。

### 观察证据（关键反模式清单）

写路径三类并存：
- `now_tz()`（aware +08:00）→ 正确，driver 归一化 UTC。
- `now_tz().replace(tzinfo=None)`（naive 京时）→ 当 UTC 存，+8h 偏移。
  `app/services/scheduler_service.py:45`、`app/services/operation_log_service.py:44`、
  `app/worker/akshare_sync_service.py:222`
- `now_tz().isoformat()` → 字符串，几十处。

naive 读法互斥：
- `to_config_tz` / `to_display_iso`：naive → UTC。`app/utils/timezone.py:41,70`
- `strptime(...).replace(tzinfo=get_tz())`：naive → 京时。
  `app/routers/data_status.py:94`、`app/routers/analysis.py:1162`
- 手搓 `replace(tzinfo=utc) if naive`：`app/routers/analysis.py:180,225`
- `ensure_timezone`（naive=京时，且无调用者，属死代码）：`app/utils/timezone.py:45`

直引时区源分叉：
- `ZoneInfo(settings.TIMEZONE)`：`app/services/quotes_ingestion_service.py:49`、
  `app/routers/stocks.py:969`、`app/services/data_sources/baostock_adapter.py:291`

前端三套时钟：
- 集中工具 `frontend/src/utils/datetime.ts`：**naive=+08:00（与后端 opposite）**。
- 手写 `new Date(x).toLocaleString('zh-CN')`：
  `frontend/src/views/Queue/index.vue:433`、SyncControl、SyncHistory、
  ScheduledTasksView、MultiSourceSyncCard…
- 手写 `new Date(x).getTime()` 新鲜度/差值：
  `DataHealthCard.vue:276`、`SyncHistory.vue:257`、`MultiSourceSyncCard.vue:268`、
  MonitorAlertPopup、MonitorSummary、MonitorCenter。

---

## 1. 统一原则（唯一的"时间局"）

时间 = 一致性问题的唯一解法是：**写入、读出、显示各自的规则各只有一条。**

| 环节 | 唯一规则 |
|---|---|
| 写时刻 | 一律 `now_tz()`（aware datetime），禁 strip tzinfo、禁 ISO 字符串入时间字段 |
| 数据库读出 | naive = UTC（driver 未开 tz_aware 时的统一法律） |
| 读出→显示 | `to_display_iso()`（恒定 +08:00） |
| 读出→计算 | `to_config_tz()` |
| API 边界 | 所有 datetime 出参必须带 `+08:00` 偏移，无时区字符串永不过线 |
| 前端 | 只走 `datetime.ts` 单时钟，naive 一律告警并按 UTC 解释 |

---

## 2. 数据库层

存储契约：
- 所有"时刻"字段用 BSON `datetime` 存；**禁止 ISO 字符串入时间字段**。
- 写只允许 aware datetime（`now_tz()`）。

根因性修复（二选一）：
- **方案 A（推荐，最彻底）**：`AsyncIOMotorClient` 开启 `tz_aware=True`
  （`app/core/database.py:45`），driver 读回即带 UTC 偏移，从源头消灭 naive 二义性。
  代价大：所有读路径须能处理 aware 值（`to_display_iso`/`to_config_tz` 已兼容 aware），
  同时删除所有 `strptime naive` 与 `replace(tzinfo=get_tz())`。
- **方案 B（保守）**：保持 `tz_aware=False`，把"naive=UTC"写成唯一法律。

> 决策：长远取 A，分两步——先把后端收敛到 A 的语义，再切 `tz_aware=True`。

---

## 3. 后端层

以 `app/utils/timezone.py` 为唯一时间局：
- 写：`now_tz()`
- 显示：`to_display_iso()`
- 计算：`to_config_tz()`

清洗反模式：
1. 删除 `ensure_timezone`（死代码且语义相反）。
2. 删除所有 `now_tz().replace(tzinfo=None)`。
3. 裸 `.isoformat()` 序列化 DB 读回值 → 一律 `to_display_iso()`。
   覆盖：`research_notes_service.py:38`、`analysis_service.py:603/876/877`、
   `serialization.py:22/33`、tags_service、notifications_service、reports 等。
4. 手搓 `replace(tzinfo=utc) if naive` → `to_config_tz()`（`analysis.py:180/225`）。
5. `strptime(...).replace(tzinfo=get_tz())` → 统一语义（`data_status.py:94`、`analysis.py:1162`）。
6. `ZoneInfo(settings.TIMEZONE)` → `get_tz()`
   （`quotes_ingestion_service.py:49`、`stocks.py:969`、`baostock_adapter.py:291`）。

---

## 4. 前端层

`frontend/src/utils/datetime.ts` 为唯一时钟，修正其假设：
- 后端保证"无时区字符串永不越过 API 边界"→ 正常路径带偏移，按真实瞬时解析、按
  `Asia/Shanghai` 渲染。
- 遇 naive 字符串 → 打 warning + 按 UTC 解释（与后端一致），**不再静默当作 +08:00**
  （当前反面假设在 `datetime.ts:42`）。
- 收敛散落手写时钟：`new Date(x).toLocaleString('zh-CN')` 与
  `new Date(x).getTime()` 新鲜度/差值，一律改走 `datetime.ts` 转瞬时再算。

---

## 5. 收尾与防回归

- 调度/交易时间：APScheduler、`trading_time.py` cron 统一绑定 `get_tz()`，
  禁 `settings.TIMEZONE` 直引分叉。
- 回归测试：新增"穿越测试"，断言 API datetime 字段都带 `+08:00`；
  `ensure_timezone` 不得再出现；前端不再手写 naive 解析。
- 每批容器内回归测试通过后，再推 GitHub / 进入下一批。

---

## 6. 实施批次

- **批次 1（后端层，风险最低、收益最大）**：实现上述"清洗反模式 + 收敛唯一时间局"。
- **批次 2（数据库层）**：`tz_aware` 方案 A 切换。
- **批次 3（前端层）**：`datetime.ts` 收敛与组件迁移。

> 进度追踪见下方表格（每完成一批更新一行）。

| 批次 | 范围 | 状态 |
|---|---|---|
| — | 方案确认与文档落盘 | 完成 |
| 1 | 后端层 | 完成（容器内回归 119 passed） |
| 2 | 数据库 tz_aware | 完成（tz_aware=True 生效；读回 aware UTC，to_display_iso 归一 +08:00；容器回归 119 passed + 探针验证） |
| 3 | 前端层 | 完成（datetime.ts 修正 naive 假设：naive 一律按 UTC 解释+告警，新增共享 parseToInstant/toTimestamp；收敛 Queue/SyncControl/SyncHistory/ScheduledTasksView/MultiSourceSyncCard/DataHealthCard/MonitorAlertPopup 手写时钟；容器内 vite build 通过并重建 frontend 容器 healthy） |
| 4 | 收尾·防回归 | 完成（后端读回值裸 isoformat 收敛：scheduler_service 执行历史统一 to_display_iso，杜绝 tz_aware 下 +00:00 漏出；新增穿越测试 test_bug_025_time_contract_api.py 钉住统一契约：now_tz 必 +08:00、to_display_iso/to_config_tz naive=UTC、禁 ensure_timezone/禁 naive 写、禁 ZoneInfo(settings.TIMEZONE)和 timezone=settings.TIMEZONE 调度直引分叉、禁读回裸 isoformat；**据计划清单复查清剿最后一处调度时区分叉 app/services/retail/scheduler_jobs.py:283 tz=settings.TIMEZONE → get_tz()**；前端再收敛 database.ts/LogManagement/ReportDetail/TokenStatistics/ModelCatalogManagement/MarketCategoryManagement/StrategyBacktest/Stocks Detail/Dashboard 手写时钟；容器内穿越测试 9 passed + 全量套件 309 passed 3 skipped + backend/frontend healthy） |
| 5 | 写入存储契约（受控先行） | 部分完成（写入侧向 BSON datetime 收拢，先打地基：**to_display_iso/to_config_tz 兼容 str+datetime 双形态**（存量 ISO 字符串缺失时区按 UTC 解释、带偏移按偏移归一），使 tz_aware 混合读取成为可能；首个受控样例 **sync_status 集合**写侧 `now_tz().isoformat()` → `now_tz()`，并修复读侧陈旧检测中 naive `_dt.now()` 减 aware 的潜在 TypeError（改用 to_config_tz+now_tz）；穿越测试新增 3 项守卫：to_config_tz/to_display_iso 接收 ISO 字符串语义、sync_status 禁 isoformat 写入；容器内穿越 12 passed + 全量 295 passed 3 skipped + backend/worker/backtest_worker 重启 healthy） |

> **批次5 余下工作（写入契约全量落地）**：全库仍有约 40 处 `now_tz().isoformat()` 持久化时间字段写入（monitor/portfolio/paper/stock_alert/foreign_stock/basics_sync/tushare_sync/akshare_sync/data_integrity/backups/usage_statistics/baostock/he/多周期同步等）。受控转换需**逐集合核对读侧**：
>  1. 读侧走 `to_display_iso/to_config_tz`（已兼容字符串）→ 安全，可切 `now_tz()`。
>  2. 读侧用 `isinstance(..., str)`/`fromisoformat`/直接 `==` 字符串比较/范围查询 → 需先迁移读侧（如本批 sync_status 陈旧检测），否则会触发 naive/aware 或类型混比。
>  3. 存量字符串数据不迁移、只让新写变 datetime → 字段成混合类型，须依赖"工具双形态"归一显示；范围/排序查询需统一比较基准。
>  因此按"先打地基 + 逐个受控集合 + 逐批容器回归"推进，避免一次性大爆炸回归。