# 功能精简分析报告(证据驱动 · 定稿)

> 生成日期:2026-09-07 | 依据:当前 HEAD 代码 + 近 90 天 git 历史 + 后端访问日志实测 + 用户决议
> 性质:纯分析,不含任何代码变更。执行需另行批准,并以容器内构建/回归为门槛。

## 一、系统规模快照

| 维度 | 数值 |
|---|---|
| 后端路由注册 | 48 个(唯一例外 `quick_analysis` include 被注释废弃) |
| 后端服务模块 | 40+(含 retail 引擎、同步体系、分析三档、screening 分层) |
| 前端业务视图 | 30+(含 3 个独立路由策略页、12 个无入口遗留页) |
| 脚本工具 | `scripts/` 378 个(7 类) |
| 双前端遗留 | Streamlit `web/`(自初始提交后从未更新) |

## 二、证据源

1. **静态引用**:路由表 + 全前端 import 比对(当前 HEAD 复核,排除自身导入)
2. **git 活跃度**:近 90 天提交分布
3. **真实调用量**:`logs/webapi.log` 最近 20000 行 API 访问频次(2026-09 运行窗口)

### 调用量 Top(近 2 万行)

monitor/alerts 2060 · notifications/unread_count 1264 · health 704 · strategy/run-all 128 · monitor/strategies 103 · favorites 84 · paper/positions 71 · retail/regime 53 · stream/monitor-orders 44 · war-room/today 59 · plan 20 · intraday 12 · macro 13 · vibe/global-stocks 11。低频:usage(4-6)、news-data(9)、social-media(8)、queue(6)。

## 三、决策清单(定稿)

### 保留(8 项:真实调用 × 闭环价值)

| # | 功能 | 证据 |
|---|---|---|
| 1 | 监控中心 | alerts 2060 / strategies 103 / tbs 71 次 |
| 2 | 通知中心 | unread_count 1264 次 |
| 3 | 策略筛选 StrategyScreener(统一入口,含市场×策略矩阵) | run-all 128 次;近 90 天 20 次提交 |
| 4 | 作战室 + 宏观 + 每日计划 | war-room 59 / plan 20 / intraday 12 / macro 13 次 |
| 5 | 零售引擎 API(regime / risk-scan / strategies) | regime 53 / strategies 10 次;矩阵数据源 |
| 6 | 持仓 / 自选 / 实时流(SSE) | positions / favorites / quotes / orders 活跃 |
| 7 | 分析服务层(simple / analysis / quick 服务) | 分级设计,被 config_bridge 引用 |
| 8 | 三买三卖 / 量价(组件) | 被 WarRoom、Stocks/Detail 引用 |

### 删除(17 项)

**前端视图(15 个):**

| # | 文件 | 证据 |
|---|---|---|
| 1 | views/Data/DataView.vue | 0 引用 |
| 2 | views/Screening/RetailCenter.vue | 0 引用 |
| 3 | views/Screening/StrategyComparison.vue | 0 引用;已由回测"结果对比 Tab"取代 |
| 4 | views/Screening/LimitUpPullback.vue | 仅宿主 #3,随删 |
| 5 | views/Screening/MaCrossover.vue | 仅宿主 #3,随删 |
| 6 | views/Screening/SmallCapValue.vue | 仅宿主 #3,随删 |
| 7 | views/Screening/Turnaround.vue | 仅宿主 #3,随删 |
| 8 | views/Screening/index.vue | 0 引用 |
| 9 | views/Queue/index.vue | 0 引用,路由已重定向 |
| 10 | views/Analysis/SingleAnalysis.vue | 已并入 StockAnalysis |
| 11 | views/Analysis/BatchAnalysis.vue | 已并入 StockAnalysis |
| 12 | views/Analysis/AnalysisHistory.vue | 已由任务中心取代 |
| 13 | views/Screening/ConvertibleArbitrage.vue | **用户决议**:与统一筛选入口重复 |
| 14 | views/Screening/MacdDivergence.vue | **用户决议**:同上 |
| 15 | views/Screening/ExtremeReversal.vue | **用户决议**:同上 |

**后端/遗留(2 项):**

| # | 项 | 证据 |
|---|---|---|
| 16 | 遗留 Streamlit `web/` | 最后修改 = 初始提交;docker-compose / README 无部署引用 |
| 17 | `app/routers/quick_analysis.py`(路由层) | include 注释废弃,日志 0 调用;`quick_analysis_service` 保留 |

**配套清理:** 路由占位 `/analysis/single`、`/analysis/batch`;删除 13-15 对应路由(macd-divergence、extreme-reversal、convertible-arbitrage);streamlit 依赖 3 处。

### 降级(4 项:API 存活、人机价值低;仅 meta 改动,不删页面/API)

- Token 统计(usage 4-6 次)→ `hideInMenu`
- 学习资料(纯静态零后端依赖)→ `hideInMenu`
- `/queue` → 重定向任务中心(保留)
- `/analysis/history` → 重定向任务中心(保留)

### 保留待收敛(4 项,后续另立课题)

- 同步体系(stock_sync / multi_source_sync / multi_period_sync / basics_sync):全部注册、职责各异
- 筛选分层(screening → enhanced → database):依赖链非重复
- 分析三档服务:分级设计
- retail 专属服务(convertible / macd / extreme):删除页面后**先保留**,待确认无其他调用再收敛

## 四、影响与保证

- **菜单收敛后**:速览 / 作战 / 分析 / 策略(常用策略、策略回测)/ 候选 / 自选 / 市场 / 问股 / 任务 / 报告 / 设置
- **后端零改动(唯一例外 #17)**:`/api/retail`(regime/strategies/risk-scan)、`/api/strategy`(run-all/list)、`/api/analysis`(single/batch)、`/api/war-room`、`/api/monitor` 全部保留
- 策略矩阵 / 策略池以 API 消费策略,不依赖被删静态页

## 五、执行建议(下一步)

| 次序 | 内容 | 验证 |
|---|---|---|
| 1 | 删除 15 视图 + 3 路由 + 配套 redirect | 前端 `npm run build` |
| 2 | 删除 web/ + streamlit 依赖;删除 quick_analysis 路由文件 | 后端 `import app.main` |
| 3 | Token 统计 / 学习资料 hideInMenu | 菜单快照 |
| 4 | 容器内回归 + 路由 smoke + retail/analysis/monitor API 冒烟 | 按用户容器测试工作流 |

**执行门禁**:用户批准后,在容器内完成构建与回归,验证通过后方可提交。