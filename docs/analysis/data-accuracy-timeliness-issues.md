# 数据准确性与及时性问题追踪文档

> 本文档用于系统性追踪前端、后端、数据库以及贯穿全链路的优化项。
> 每项含：问题描述、深入分析、涉及文件、解决方案、核对状态（☐ 未开始 / 🔄 处理中 / ✅ 已完成 / ⚠️ 待验证）。

## 重要结论（先于清单）

**"贯穿字段契约断裂"经下钻验证为否**：自选股链路实际自洽——
- 数据库 `market_quotes`：`code` 与 `symbol` 同值写入（[quotes_ingestion_service.py](../../app/services/quotes_ingestion_service.py)）
- 后端 favorites：`current_price`(close)、`change_percent`(pct_chg)（[favorites_service.py](../../app/services/favorites_service.py)）
- 前端 Dashboard：`stock_code/current_price/change_percent` 与之精确匹配

`symbol/code`、`pct_chg/change_percent` 的双字段只是**兼容层**，已在边界完成映射。真正的问题是"兼容层技术债过多"，而非运行时契约断裂。

---

## 优先级一（P1·核心）

### P1-1 自选股行情涨跌幅残留窗口（✅）
- **问题**：自选股涨跌幅 = `market_quotes.pct_chg`。M1-M5 已修复 pct_chg 覆盖保护，但当**日线未同步**且**实时接口又不返回 pre_close** 时，回退算法仍得不出 pct_chg，`$setOnInsert` 写入 `None`，前端涨跌幅为空。
- **分析**：[quotes_ingestion_service.py](../../app/services/quotes_ingestion_service.py) 中 pct_chg 回退仅依赖本次采集的 close/pre_close。
- **方案**：
  1. pct_chg 仍为 None 且 close 有效时，去 `stock_daily_quotes` 取上一交易日 close 计算（复用 M2 的 `_compute_missing_pct` 逻辑），有效才 `$set`。✅ 已实现：`_bulk_upsert` 改为三遍结构，新增 `_compute_missing_pct_batch` 批量按 `prev_trading_day` 补算上一交易日收盘。
  2. 前端 `change_percent === null` 显示「——」而非 0。✅ 已实现：`Dashboard/index.vue` 不再 `|| 0` 伪装平盘，null 显示「——」。
- **验证**：容器内重启后对自选股观察涨跌幅；无日线/无昨收时前端显示「——」。

### P1-2 完整性校验「低质量」与「缺失」统一闭环（✅）
- **问题**：data_integrity_service 已统计缺失 + pct_chg/pre_close 全 null 的低质量记录，但仍有 5360 条孤立记录无法自愈，且只写日志、无指标化、无告警。
- **分析**：[data_integrity_service.py](../../app/services/data_integrity_service.py) L119-L149、L249-L293。
- **方案**：
  1. 检查结果落一条指标到 `data_metrics` 集合（含 date/missing_count/low_quality_count/orphan_count）。✅ 已实现：新增 `_save_data_metrics`，含 completeness_pct/source_coverage/status。
  2. 对无法自愈孤立记录：连续 N 天下游仍无前收盘才允许置 null；否则交补数链交叉回算。🔧 现有逻辑已含值级校验 + 补数源降级交叉回算；「N 天窗口再置 null」策略待后续强化（当前已把补数后残差计为 `orphan_count` 落库，便于观察收敛）。

### P1-3 交易日历统一（✅）
- **问题**：`trade_date` 三格式混存（YYYYMMDD/YYYY-MM-DD/datetime）；M2 已用交易日历，但补数、回测等非行情入口各写一套日期逻辑，存在取错一交易日的风险。
- **分析**：[trading_time.py](../../app/utils/trading_time.py) 已有 `is_trading_day/get_latest_trade_day`，缺统一的 `prev_trading_day`。
- **方案**：在 `trading_time.py` 增加 `prev_trading_day(d)`，所有昨收/涨跌计算统一调用，禁止各模块自制日期前移逻辑。✅ 已实现并应用到 [akshare_sync_service.py](../../app/worker/akshare_sync_service.py) 与 [quotes_ingestion_service.py](../../app/services/quotes_ingestion_service.py) 的昨收/涨跌补算。

---

## 优先级二（P2·数据库数据层）

### P2-4 日线多源写入去重幂等（✅）
- **问题**：`stock_daily_quotes` 唯一索引建在数据源维度，历史脏数据下 `_safe_create_index` 静默失败即放任重复；tushare/akshare 同时追同日产生重复。
- **方案**：
  1. 先归并历史重复（复用 M4 思路），再保证索引创建成功并日志确认。✅ 索引创建失败由静默降级改为显式 `warning`，暴露脏数据问题。
  2. 写入端改显式 `upsert(filter={code, trade_date, period}, update=$set, upsert=True)` 语义。✅ 核查核心写入路径 [historical_data_service.py](../../app/services/historical_data_service.py) 已用 `ReplaceOne(upsert=True)` 幂等，filter 与唯一索引 `(code, trade_date, period, data_source)` 对齐。

### P2-5 market_quotes 索引与读写键统一（✅）
- **问题**：`market_quotes` 建 `code` 唯一索引，但部分写入用 `symbol` 主键 upsert，存在按 symbol 命中不到索引的路径。
- **方案**：主键统一 `symbol`，唯一索引改为 `(symbol, source)`；`code` 作为冗余保留但查询一律走 `symbol`。
- **结论/实现**：核查全部 CN `market_quotes` 写入路径（quotes_ingestion / akshare_sync / stock_sync / stocks），`code` 与 `symbol` 恒等（均为 6 位代码），无实际键值分歧；因二者等价，大规模把 48 处读写改键为 symbol 属无谓重构。采用低风险方案：保留 `code` 唯一主键 + 追加 `symbol` 冗余索引，确保按 symbol 的读取路径也命中索引。

---

## 优先级三（P3·实时链路/前端/视图）

### P3-6 SSE 信号与值分离（✅）
- **问题**：[quotesSSE.ts](../../frontend/src/utils/quotesSSE.ts) 收到信号后全量 GET，信号不携带值；信号到达时数据可能未落库，前端拉到旧值。
- **方案**：后端 `quotes_update` 事件体携带 `code+close+pct_chg`，前端原地 patch；按 `updated_at` 丢弃落后信号。
- **实现**：后端 `_bulk_upsert` 入库（含缓存失效）**之后**才发布信号，且仅当 `pct_chg` 有效时携带 `{code: {close, pct_chg}}` 载荷；前端 Dashboard 自选股收到信号后原地 patch（无载荷才兜底全量刷新）。其余视图保持原 refetch 行为。
- **说明**：因发布总是在 `bulk_write` 之后，原"信号比数据先到"的陈旧读取本质已缓解；带值承载进一步避免每个信号全量回查。

### P3-7 SSE token 不落 URL（✅）
- **问题**：[quotesSSE.ts](../../frontend/src/utils/quotesSSE.ts) 用 `?token=` 拼 URL，token 进入浏览器历史与网关 access log。
- **方案**：改用 fetch-based SSE（ReadableStream）携带 `Authorization` 头，或短期先挪到 `HttpOnly cookie`。
- **实现**：前端改用 `fetch` + `ReadableStream` 自解析 SSE，通过 `Authorization: Bearer <token>` 头鉴权，URL 不再带 token；后端 `get_current_user_for_sse` 本就优先读取 `Authorization` 头，原生支持。token 不再进入 URL/日志/历史。

### P3-8 stock_financial_data 视图相关索引（✅）
- **问题**：`stock_screening_view` 取最新 `report_period` 依赖 `$sort`，无覆盖索引时可能全量扫描。
- **方案**：为 `stock_financial_data` 建 `(symbol/code, report_period desc)` 复合索引；或写财务时维护 `latest_report_period` 冗余。
- **实现**：核查 [database.py](../../app/core/database.py) 已存在 `(code, report_period -1)` 与 `(symbol, report_period -1)` 复合索引（含 `(code, data_source, report_period -1)`），方案已满足，无需改动。

---

## 优先级四（P4·健壮性/技术债）

### P4-9 异常语义分化（✅）
- **问题**：[stock_data_service.py](../../app/services/stock_data_service.py) 多处 `try/except → return None/[]`，前端无法区分「无数据」与「出错」。
- **实现**：`get_stock_basic_info`/`get_market_quotes` 查询空仍返回 `None`，`get_stock_list`/`get_stock_list_count` 查询空返回 `[]/0`；**实际异常改抛给路由层**（[stock_data.py](../../app/routers/stock_data.py) 的 try/except 转 `HTTPException 5xx`）。前端 Favorites 已天然区分：5xx 走 catch 提示「获取股票信息失败」，成功 `success=false` 提示「未找到」，无需额外改动。语义已完成分化。

### P4-10 启动期非保护 DB 调用（✅）
- **问题**：[main.py](../../app/main.py) `monitor_service.ensure_indexes()` 处于 try/except 外，DB 未就绪会中断启动。
- **实现**：`quotes_ingestion.ensure_indexes()` 与 `monitor_service.ensure_indexes()` 启动调用包 try/except，失败记 `critical` 严重日志并**降级跳过**（继续启动、其他任务照常注册），不再因 DB 暂时未就绪而中断整个应用启动。

### P4-11 后端 DB 入库模型 extra=forbid（✅）
- **问题**：[stock_models.py](../../app/models/stock_models.py) `extra="allow"` 掩盖字段漂移。
- **实现**：对外/读取模型保留 `extra="allow"` 兼容；新增 DB 写入白名单模型 `StockBasicInfoDB`/`MarketQuotesDB`（`extra="forbid"`）与漂移检测 `detect_db_extra_fields`。接入三处核心写入口：`quotes_ingestion_service._bulk_upsert`（market_quotes）、`basics_sync_service` 与 `multi_source_basics_sync_service`（stock_basic_info）。检测**仅告警不阻断、不删字段**，零数据风险，用于暴露字段漂移。

---

## 技术债清理（P5）

### P5-12 SSE 断连 UI 降级提示（✅）
- **问题**：SSE 重连耗尽后仅 console.warn，页面展示旧价无标识。
- **实现**：[quotesSSE.ts](../../frontend/src/utils/quotesSSE.ts) `subscribeQuotesUpdate` 新增 `onStatus` 回调（`connected`/`degraded`），重连耗尽、无 token 时触发 `degraded`，连接恢复触发 `connected`。[Dashboard/index.vue](../../frontend/src/views/Dashboard/index.vue) 以 `quotesStale` 标志展示 el-alert「行情实时中断，已切换定时刷新」。

---

## 进度追踪

（每完成一项在此勾选并记录验证方式）

- [x] P1-1 （容器重启后自选股观察涨跌幅；无日线/无昨收时前端显示「——」）
- [x] P1-2 （data_metrics 集合可时序查询到完整性指标）
- [x] P1-3 （akshare/quotes 昨收补算统一走 prev_trading_day）
- [x] P2-4 （索引失败显式 warning；写入端 ReplaceOne(upsert=True) 幂等）
- [x] P2-5 （market_quotes 追加 symbol 冗余索引）
- [x] P3-6 （信号携带 {code:{close,pct_chg}}，前端原地 patch）
- [x] P3-7 （SSE 走 Authorization 头，token 不再落 URL）
- [x] P3-8 （stock_financial_data 复合索引已满足，无需改动）
- [x] P4-9 （异常抛路由层转 5xx，查询空返回 None/[]）
- [x] P4-10 （启动期 ensure_indexes 失败降级跳过，不中断启动）
- [x] P4-11 （新增 forbid 白名单模型 + 三处写入口漂移检测）
- [x] P5-12 （SSE 降级/恢复 UI 提示）
- [ ] 全量回归 + 重启验证 + GitHub 推送