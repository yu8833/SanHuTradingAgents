# 菜单与页面 UX/信息架构深度评审（2026-10-25）

评审范围：策略（常用策略、策略回测）、速览、自选、交易（模拟交易、持仓追踪、监控中心、交易复盘）、分析（股票分析、分析报告、Token 统计）、任务（任务中心）、设置（个人设置、标签管理、配置管理、系统管理）。

方法：以代码为准逐条核对，未做浏览器实测。每条结论都标注了文件与行号，便于直接落地。未验证的内容会明确标注“需实测”。

---

## 一、结论先行

1. 真正阻塞上线的只有四类：**接口权限缺口**、**入口指向错误**、**假按钮**、**状态与 URL/菜单不同步**。其余是体验优化。
2. 上一轮有 4 条判断需要修正，见下节“结论修正”，避免按错误结论实施方案。
3. 功能覆盖已经足够，主要矛盾是**同一件事有多个入口、多个说法**，以及**局部状态不落 URL 导致深链和回退失效**。
4. 建议按 4 个批次推进，批次 1 只做安全与失效入口，可独立验证、互不阻塞。

---

## 二、结论修正（上一轮判断有误，以本节为准）

| 上一轮结论 | 实际情况 | 证据 |
|---|---|---|
| 策略回测离开页面后结果与进度丢失 | **不成立**。后端有 `saveBacktestResult`，页面会持久化并恢复单次结果；真正缺的是“运行中任务的跨页可见性与取消” | StrategyBacktest.vue L690-L710 附近；GlobalSearch/L981 恢复逻辑 |
| 配置管理里 API Key 明文与普通配置同权重 | **不成立**。API Key 是只写掩码（`has_api_key`），页面不回显明文，已有“已配置/未配置”状态 | ConfigManagement.vue L115、L137、L171 |
| 持仓没有来源字段 | **不成立**。已有 `strategy` 字段；问题是手工添加默认写入 `"default"`，与真实策略仓无法区分 | portfolio_service.py L44、L164、L208 |
| 模拟下单缺少资金校验 | **部分不成立**。后端已校验可用资金与可用持仓；前端缺的是**提交前的预校验与金额/费用预览**，以及 A 股整手校验（后端也未做） | paper_executor.py L444-L451、L511-L513；L399-L414 无 lot 校验 |

---

## 三、系统性问题（跨页面）

### SEC-1 权限只做到页面级，接口层没有管理员校验（最高优先）

- 现象
  - `database.py` 的 11 个端点（备份、导入、导出、清空、清理分析数据、清理日志）只依赖 `get_current_user`，任一登录用户即可调用。
  - `logs.py` 的 5 个端点（列文件、读内容、导出、统计、删文件）同样只校验登录。
  - `multi_source_sync.py` **完全没有鉴权依赖**，`/api/sync/multi-source/*` 未登录即可触发全量同步。
  - 前端只有 `/settings/users` 配了 `requiresAdmin`。
- 影响：不只是“菜单看得见但点不进”，而是任意账号可清库、删日志、触发同步。隐藏菜单不能当作安全手段。
- 方案
  1. 在 `app/routers/auth_db.py` 增加 `require_admin` 依赖（复用 `authStore.isAdmin` 对应的后端判定）。
  2. 挂到 database / logs / operation_logs / multi_source_sync 的**写操作**；读操作（统计、列表）可保留登录级，但日志内容读取建议一并收管理员。
  3. 前端 `SidebarMenu` 用 `authStore.isAdmin` 过滤“系统管理”分组；`ConfigManagement` 的密钥页同样仅管理员可见。
  4. 为 database / logs / multi-source-sync 路由补 `meta.requiresAdmin`，防止直接输入 URL。
- 验收
  - 非管理员调用 `POST /api/system/database/backup`、`POST /api/system/database/cleanup`、`DELETE /api/system/logs/files/{name}`、`POST /api/sync/multi-source/sync` 全部返回 403。
  - 非管理员登录后侧边栏不出现“系统管理”分组；手动输入 `/settings/database` 被守卫弹回。
- 风险：运维脚本若用普通账号 token 会失效，需要在脚本中改用管理员账号。

### BUG-1 `/analysis/history` 深链落到错误的 Tab

- 证据：路由把 `/analysis/history` 重定向到 `/tasks?tab=completed`（[router/index.ts L308](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/router/index.ts#L308)）；但任务中心 `topTab` 默认是 `'scheduled'`（[TaskCenter.vue L196](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Tasks/TaskCenter.vue#L196)），query 处理只设置 `activeTab`、从不切换 `topTab`（[L577-L583](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Tasks/TaskCenter.vue#L577-L583)）。
- 影响：用户从“分析历史”入口进来，看到的是“定时任务”，且“已完成”筛选项在另一个 Tab 里，等于入口失效。
- 方案：query 中出现 `tab` 时同步 `topTab.value = 'analysis'`；`topTab` 切换时用 `router.replace({ query: { tab: activeTab } })` 回写，保证刷新/回退一致。同时把菜单“任务”默认 Tab 改为 `analysis`（当前默认落在运维性质的定时任务上）。
- 验收：直接访问 `/analysis/history` 显示“分析任务 → 已完成”；切到“定时任务”后 URL 变为 `/tasks?tab=scheduled`；浏览器回退能正确切回。

### BUG-2 任务搜索只过滤当前页

- 证据：`filteredList` 是对已取回的本页数据做 `keyword` 过滤（[L407-L414](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Tasks/TaskCenter.vue#L407-L414)）。
- 影响：搜索股票代码时，若目标不在当前页就“搜不到”，用户会误判任务不存在。
- 方案：把 `keyword` 并入查询参数交给后端（`loadList` 组装 params 时带上），翻页/切 Tab 时保持；前端只保留“当前页高亮”。
- 验收：构造跨页数据，搜索第 2 页的股票代码能返回该任务；清空搜索恢复全量。

### BUG-3 keep-alive 只有一个名字不匹配

- 证据：缓存名单用的是路由 name「StockScreeningCommon」（[BasicLayout.vue L106](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/layouts/BasicLayout.vue#L106)，路由 name 见 [router/index.ts L90](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/router/index.ts#L90)），而组件是 `defineOptions({ name: 'StrategyScreener' })`（[StrategyScreener.vue L272](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Screening/StrategyScreener.vue#L272)）。其余 9 个页面组件名与名单一致。
- 影响：只有“常用策略”没被缓存，切走再回来筛选条件、结果集、滚动位置全部丢失；其余页面正常。此前误判为整份名单失效。
- 方案：组件改名对齐路由 name，或把名单项改为 `StrategyScreener`。二选一，不要两边都改。
- 验收：在常用策略选中某策略、滚动到结果中部，切到自选再返回，状态完整保留。

### BUG-4 设置子项高亮与 query 脱节

- 证据：侧边栏 `activeMenu` 取 `route.path`（[SidebarMenu.vue L131-L135](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/components/Layout/SidebarMenu.vue#L131-L135)），而个人设置四项用 `/settings?tab=appearance` 这类 query 区分（[L84-L86](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/components/Layout/SidebarMenu.vue#L84-L86)）。页面内部确实响应了 query（[Settings/index.vue L432-L462](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Settings/index.vue#L432-L462)），所以内容会切，只有菜单不高亮。
- 影响：用户点“外观设置”，左侧仍高亮“通用设置”，产生“是不是没点中”的错觉。
- 方案（推荐 A）
  - A：`activeMenu = computed(() => route.path === '/settings' && route.query.tab ? '/settings?tab=' + route.query.tab : route.path)`。改动最小，保留现有 URL 结构。
  - B：把四项改成真实子路由（`/settings/appearance` 等）并配重定向，长期更干净，但要改菜单、路由、书签兼容，收益不如 A 明显。
- 验收：依次点击四个设置子项，侧边栏高亮跟随；刷新页面后高亮不变。

### UX-1 术语、命名、视觉符号不统一

- 菜单“分析报告” vs 页面标题“历史报告”（[Reports/index.vue L10](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Reports/index.vue#L10)）。
- “任务”菜单实际是“任务中心”，且首屏落在定时任务。
- 装饰性 emoji 出现在数据库页与模拟交易页（如 [DatabaseManagement.vue L23](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/System/DatabaseManagement.vue#L23)），与全站线性图标体系不一致。
- 方案：建立一张“页面名称对照表”，菜单标题 = 页头标题；移除正文 emoji，状态统一用 el-tag + 色彩语义。
- 验收：全局搜索 `历史报告` 无残留；关键页无 emoji 字符。

### UX-2 同一能力存在多个入口

| 能力 | 入口 A | 入口 B | 建议 |
|---|---|---|---|
| 设置导航 | 侧边栏三级项 | 设置页内左侧 el-menu | 只保留页面内 tab，侧边栏收为一个“通用设置”入口 |
| 策略监控开关 | 常用策略卡片开关 | 监控中心规则列表 | 两处都保留，但互相跳转并共享同一配置源 |
| 标签管理 | 设置→标签管理 | 自选页“标签管理”按钮 | 自选页改为跳转设置页 |
| 分析历史 | 分析页完成入口 | 任务中心 | 统一走任务中心，分析页只做“最近一次” |

---

## 四、分页问题与实施方案

### 策略 / 常用策略

问题
1. “运行全部”最长 600 秒，只有卡片级 loading，无整体进度、无取消（[L574](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Screening/StrategyScreener.vue#L574)）。用户无法判断是卡死还是在跑。
2. 非内置策略卡片可点击，点击后只弹提示（[L655](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Screening/StrategyScreener.vue#L655)），属于“可点但无效”的交互陷阱。
3. 结果表无导出、无二次筛选（评分/量比/涨跌幅排序以外的过滤），命中较多时难以收敛。
4. 被 BUG-3 影响，页面状态不保留。

方案
- 运行全部：任务化。发起后顶部显示“已完成 x/y 策略、当前策略名、耗时”，每完成一个策略回填命中数；提供“取消”调用后端取消/忽略结果；完成后 ElNotification 带“查看结果”。
- 非内置策略卡片：置为 disabled 并加“非内置策略，仅展示规则”说明；若要保留点击，则跳转到策略说明而不是弹错误。
- 结果表：增加“导出 CSV”（前端由已加载数据生成即可）与“仅看评分≥x / 仅看量比≥y”快速筛选条。
- 修 BUG-3 后再验证状态保留。

验收
- 点“运行全部”3 秒内出现整体进度；中途取消后按钮恢复可用，结果区不再继续追加。
- 点击非内置卡片不出现“提示型失败”，而是明确不可用原因。

### 策略 / 策略回测

问题
1. 11 个参数平铺，无预设/模板，新用户不知道该调什么（[L48-L95](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Screening/StrategyBacktest.vue#L48-L95)）。
2. 参数网格用 JSON textarea 输入（[L263](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Screening/StrategyBacktest.vue#L263)），格式错误只能提交后才知道。
3. 运行中无取消；离开页面后进度 UI 不再展示（结果本身有持久化，任务状态没有统一入口）。
4. 回测结果与模拟交易/自选之间没有动作出口，用户拿到结论后要手工切换页面。

方案
- 参数分两层：常用（策略、区间、初始资金、最大持仓）+ 高级（费率、滑点、止损止盈、持有天数）折叠；顶部提供 3 个预设（“稳健”“均衡”“激进”），一键填充。
- 参数网格改为二维可编辑表格（行=参数名，列=候选值），提交前本地校验数值范围与数量上限（如 ≤ 100 组）。
- 增加“取消回测”；新增“回测任务”轻量列表（复用任务中心的分析任务形态，或新增 `backtest_tasks`），展示运行中/已完成，支持从历史恢复到结果区。
- 结果区增加两个动作：“用该策略跑今日选股”（跳常用策略并预选）、“将命中股加入自选”。

验收
- 用预设能一键填满参数并通过校验；JSON 非法输入不再出现，改为表格内红框提示。
- 运行中取消后后端任务标记 canceled；从“回测任务”列表能重新打开历史结果。

### 速览

问题
1. 四块异质模块同权重堆在首屏（数据健康、持仓、自选、监控），没有“今天先看什么”的引导（[L20-L136](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Dashboard/index.vue#L20-L136)）。
2. 数据健康的主 CTA 是“一键更新”=10~30 分钟全量同步（[L138-L197](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Dashboard/index.vue#L138-L197)），把最重的操作放在最高频位置。
3. 监控摘要固定 30 秒轮询、只显示最近 5 条，且无法标记已读（[MonitorSummary.vue L138](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/components/Dashboard/MonitorSummary.vue#L138)）。
4. 自选模块内部有两套呈现（横条图 + 8 只列表），与自选页列表口径不同；各卡片“更新于”时间不统一。

方案
- 首屏顶部新增“今日待办”条：数据异常项、待确认指令数、重要告警数，按严重度排序，点击直达对应页。四块卡片保留但降为第二屏。
- 数据健康拆两个动作：主按钮“补最新缺口”（增量，通常秒级~分钟级），次按钮“全量同步”（弹窗内保留现有 10~30 分钟说明）。
- 监控摘要改为事件流（时间倒序、按严重级别着色），支持“标记已读”；轮询间隔改为页面可见时 30 秒、隐藏时暂停（`document.visibilityState`）。
- 自选模块只保留一个列表（去掉横条图或作为列表内嵌迷你条），与自选页共用同一“更新于”时间字段；每卡片统一右上角时间。

验收
- 首屏第一眼能看到“今天有几件待处理”；全量同步不再是一级按钮。
- 标签页切到后台再回来，监控请求不重复堆积。

### 自选

问题
1. 操作栏 7 个按钮平铺，“刷新 / 同步实时行情 / 批量同步数据”三个近义动作（[L54-L94](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Favorites/index.vue#L54-L94)）。
2. 表格无分页、客户端全量渲染；自选较多时首屏卡顿。
3. 标签管理入口与设置页重复；排序状态不持久。
4. 批量操作与筛选状态不写 URL，刷新即丢。

方案
- 操作栏收敛为：`添加自选股`（主按钮）+ `更新行情`（按当前选中/全部自动选择增量或全量）+ `更多`（批量删除、导入、导出、标签管理跳转）。
- 表格加服务端分页（每页 50/100/全部），或前端虚拟滚动；默认 100。
- “标签管理”改为 `router.push('/settings/tags')`，本页不再弹管理弹窗。
- 搜索、板块、标签、排序写入 query，刷新与分享可还原。

验收
- 三个近义按钮合并后，用户只需决定“更新范围”；自选 300 只时首屏渲染 < 1s（需实测）；刷新页面筛选条件保留。

### 模拟交易

问题
1. 下单弹窗只有数量输入，没有最大可买、预估金额、预估费用、A 股整手提示（[L169-L227](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/PaperTrading/index.vue#L169-L227)）。后端会校验资金/可用，但用户要提交后才知道失败。
2. 后端只校验 `quantity > 0`，未按市场最小交易单位校验（[paper_executor.py L399-L414](file:///Users/yupeng/stock/SanHuTradingAgents/app/services/paper_executor.py#L399-L414)）；而 `paper_market_rules` 已存 `lot_size`（[init_paper_trading_market_rules.py L36](file:///Users/yupeng/stock/SanHuTradingAgents/scripts/init_paper_trading_market_rules.py#L36)），规则没有被使用。
3. “持有评估”的置灰行与真实卖出信号混在同一张表（[L152](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/PaperTrading/index.vue#L152)）。
4. “重置账户”与日常操作同权重；emoji 与全站不一致；提交成功后无成交回执。

方案
- 新增后端 `POST /api/paper/order/preview`：入参同下单，复用 `paper_executor` 的市场识别与费用计算，返回 `price / notional / fee / total_cost / max_qty / lot_size / 校验错误`。前端数量变化时 300ms 防抖调用，把费用与最大可买直接显示在弹窗里；提交前若 preview 有错误则禁用提交。
- preview 内增加 lot_size 校验（从 `paper_market_rules` 读取，避免硬编码；科创板/北交所按规则表区分）。
- 持仓卖出表拆两块：`待卖出（有卖出信号）` 在上，`继续持有（评估通过）` 折叠在下，默认收起。
- “重置账户”移入“更多”菜单，二次确认文案写明“将清空持仓与交易记录”；移除 emoji；提交成功弹“已成交 x 股 @ 价格，剩余资金 y”并给“查看持仓”。

验收
- 输入数量超过可用资金时，提交按钮直接禁用并显示差额；A 股输入 1 股被拦截并提示最小 100 股；成交后回执可跳转持仓页。

### 持仓追踪

问题
1. 手工添加 / CSV 导入与策略仓共用同一集合，且默认 `strategy="default"`，无法区分来源（[portfolio_service.py L44、L164](file:///Users/yupeng/stock/SanHuTradingAgents/app/services/portfolio_service.py#L44)）。
2. 新增持仓表单字段多、无分组；汇总卡不区分策略收益与手工收益。
3. 平仓确认不展示触发来源（止损 / 信号 / 手动）。
4. 与监控中心缺少“指令执行后已落仓”的显式反馈。

方案
- 手工添加与 CSV 导入写入 `strategy="manual"` / `"import"`；策略仓保留原 strategy 名。列表增加“来源”列与筛选；汇总卡增加“策略仓 / 手动仓”切换或分段显示。
- 新增表单分两步：必填（代码、数量、成本、买入日期）+ 高级（止损、止盈、策略标签、逻辑）。
- 平仓确认展示来源与建议价格；若来自监控指令，显示指令 ID 可回溯。
- 监控中心执行成功后返回 `position_id`，前端提示“已落仓，查看持仓”。

验收
- 手工加仓记录来源为 `manual`；复盘统计默认只算非 manual 仓；平仓弹窗能看到来源。

### 监控中心

问题
1. 规则编辑器把触发条件、阈值、范围、冷却期、严重级别放一页，认知负荷高。
2. 执行指令后没有回执跳转（后端已真正落仓，[monitor_service.py L1071-L1099](file:///Users/yupeng/stock/SanHuTradingAgents/app/services/monitor_service.py#L1071-L1099)），用户不确定是否生效。
3. 触发记录只有“清空全部”，无规则/股票筛选、无批量已读。
4. 策略监控开关在“常用策略”和本页两处。

方案
- 规则编辑改 3 步 el-steps：类型与范围 → 触发条件 → 高级（冷却期、严重级别、通知方式）；每步可回退，最后一步展示“规则摘要”再保存。
- 指令执行成功后 toast + “查看持仓”按钮；失败保留弹窗并可重试。
- 触发记录加规则/股票/级别筛选，支持批量标记已读与导出。
- 两处开关统一读写同一配置接口；常用策略卡片点击“监控设置”跳到本页对应规则。

验收
- 新建一条规则最多 3 次点击完成；执行指令后 1 次点击可达持仓；触发记录可按规则筛选。

### 交易复盘

问题
1. 删除交易记录会改变胜率/盈亏比，但确认文案很轻。
2. 复盘笔记字段多、无模板；已平仓与持仓中混排，无状态筛选。
3. 缺“实盘（模拟）vs 回测”同区间对照。

方案
- 删除确认明确写“将从胜率、盈亏比、累计盈亏统计中移除，且不可恢复”。
- 提供复盘模板（做对了什么 / 做错了什么 / 下次改进），把自由文本拆成三个必填短文本。
- 记录表加“状态”筛选（已平仓/持仓中），默认已平仓。
- 若该股票有对应回测记录，增加“对比回测”入口展示同期策略收益。

验收
- 删除后统计即时变化且文案已说明；筛选后列表只含目标状态。

### 股票分析

问题
1. 输入、深度、模型配置、提交同卡，主流程与高级配置混在一起（[L23-L103](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Analysis/StockAnalysis.vue#L23-L103)）。
2. 失败只弹消息、无重试；SSE 断连没有“已降级为轮询”的提示（[L279-L343](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Analysis/StockAnalysis.vue#L279-L343)）。
3. 离开页面后没有“最近任务”入口，只能去任务中心找。

方案
- 模型配置折叠进“高级设置”，默认收起并显示当前模型名。
- 进度卡增加通道状态（实时/轮询）与失败重试按钮；重试复用上次参数。
- 右上角加“最近一次分析”浮条，读取最近任务并直达报告。

验收
- 断网模拟 SSE 失败时，进度卡明确显示“已切换轮询”；失败任务可一键重试。

### 分析报告

问题
1. 命名不一致（菜单“分析报告”，页头“历史报告”）。
2. 批量导出是“开发中”占位（[L401](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Reports/index.vue#L401)）。
3. 筛选与分页在前端；无按股票聚合、无同股历史对比。
4. 与任务中心、Token 统计没有互链。

方案
- 统一命名；批量导出若短期不做则隐藏按钮（不要暴露“开发中”）。若要实现：后端新增 `POST /api/reports/batch-export` 返回 zip（复用单份导出逻辑），前端传选中 ID 列表。
- 列表改服务端分页，筛选参数落 URL。
- 增加“按股票分组”视图：同一股票的历史报告时间线，便于对比结论变化。
- 报告详情页互链：查看对应任务、查看该次 Token 消耗。

验收
- 菜单与页头一致；批量导出要么可用要么不可见；同股历史能在 2 次点击内对比。

### 任务中心

问题
1. “重试”是假按钮，只提示“重试功能待实现”（[L455](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Tasks/TaskCenter.vue#L455)）。
2. 首屏默认落在“定时任务”，而菜单叫“任务”，用户预期是“我的分析任务”。
3. 定时任务与个人分析任务同页，职责混在一起。
4. 搜索只过滤当前页（BUG-2）；错误详情用弹窗，长日志阅读差；无批量操作。

方案
- 重试：若后端任务文档保存了原始参数，新增 `POST /api/analysis/tasks/{id}/retry` 原子重提交；否则前端用行内字段重建请求。短期无法实现则先隐藏按钮，不能留假按钮。
- 默认 `topTab='analysis'`，并在切换时回写 query（与 BUG-1 一起做）。
- 定时任务迁到“设置→系统管理→定时任务”，任务中心只保留个人分析任务；过渡期用 Tab 但文案明确区分。
- 错误详情改 el-drawer，支持复制/下载；增加批量删除与批量重试。

验收
- 失败任务重试后生成新任务且能看到新 ID；进入菜单默认看到分析任务；搜索可跨页命中。

### 设置 / 个人设置

问题
1. 双导航：侧边栏 4 项 + 页面内 el-menu（[L20-L78](file:///Users/yupeng/stock/SanHuTradingAgents/frontend/src/views/Settings/index.vue#L20-L78)）。
2. 高亮失效（BUG-4）。
3. 三级菜单折叠后只剩“个人设置”，用户找不到外观/通知/安全。

方案
- 侧边栏“设置”下只保留：通用设置（`/settings`）、配置管理、系统管理（管理员可见）；外观/通知/安全由页面内 tab 承载。
- 若短期不动结构，至少修 BUG-4 的 activeMenu，并让页内菜单与侧边栏二者只留一个可见。

验收
- 从任一入口进入设置，只有一处导航在指示当前位置。

### 设置 / 标签管理

问题
1. 缺少批量删除/合并/使用数量统计。
2. 入口两处（设置、自选）。
3. 删除正在使用的标签没有影响提示。

方案
- 列表增加“关联自选数”列（后端聚合一次查询）；支持多选批量删除、合并到目标标签。
- 自选页入口改为跳转本页。
- 删除确认显示“该标签下有 N 只自选，删除后将被移除标签”。

验收
- 批量合并后自选标签正确迁移；删除前能看到影响数量。

### 设置 / 配置管理

问题
1. 2751 行单页，分组多、密度高，找不到具体配置项。
2. 未见“未保存离开”提醒，切换分组可能丢改动（需实测确认是否按分组即时保存）。
3. 改动生效方式（即时 / 需重启 / 下次任务生效）没有标注。
4. 导入 JSON 前无 diff 预览。

方案
- 拆为子路由：`/settings/config/providers`、`/models`、`/datasources`、`/database`、`/system`、`/secrets`、`/import-export`，共用布局组件。
- 每个分组标题右侧标注生效方式（el-tag：即时生效 / 需重启 / 下次任务生效）。
- 增加 `onBeforeRouteLeave` + `beforeunload` 脏数据拦截；保存按钮区固定在底部。
- 导入前弹出 diff 预览（新增/修改/删除三类计数与明细）。

验收
- 修改某分组后未保存就切换路由会弹确认；导入能看到 diff 再确认。

### 设置 / 系统管理

问题
1. SEC-1 的权限缺口（见第三节）。
2. “操作日志”和“系统日志”概念易混，用户不知道该去哪个。
3. 高危操作（清库、删日志、导入）与查询操作同页同权重。
4. 多源同步页只有测试结果，缺“总体健康结论 + 最近同步时间”。

方案
- 权限按 SEC-1 处理。
- 日志合并为一个页面双 Tab：`操作日志（谁做了什么）` / `系统日志（系统报了什么错）`。
- 高危操作统一收进“更多”下拉 + 输入库名/文件名二次确认；页面主区域只留只读信息与查询。
- 多源同步页顶部增加总体结论卡：可用源数/总数、最近一次同步时间、失败源列表。

验收
- 非管理员看不到且调不通；清库需要二次确认；日志页能一眼分清两个 Tab。

---

## 五、实施批次

### 批次 1：安全与失效入口（无相互依赖，可并行）
- SEC-1 接口 `require_admin` + 前端菜单过滤 + 路由 `requiresAdmin`
- BUG-1 任务 Tab 与 query 双向同步
- BUG-2 任务搜索下沉后端
- BUG-3 keep-alive 名称对齐
- BUG-4 设置 activeMenu 支持 query
- UX-1 命名统一、移除 emoji
- 假按钮清理：任务“重试”、报告“批量导出”、Token“导出/详情” → 实现或隐藏

验收：本文各条验收项逐条走查；非管理员接口 403。

### 批次 2：交易闭环
- `POST /api/paper/order/preview` + 前端预校验与费用预览 + lot_size 校验
- 持仓来源字段（manual/import）+ 汇总分段 + 复盘默认排除手工仓
- 监控指令执行回执 + 跳转持仓
- 持仓卖出表拆分“待卖出/继续持有”

验收：一次完整链路“信号 → 下单 → 持仓 → 卖出 → 复盘”无需手工补数据。

### 批次 3：策略与回测
- 常用策略运行全部任务化（进度/取消/完成通知）
- 回测参数分层 + 预设 + 网格表格化 + 历史任务入口
- 回测结果动作出口（跑今日选股 / 加自选）

验收：策略页与回测页之间可通过结果互相跳转。

### 批次 4：信息架构收敛
- 速览“今日待办” + 数据健康双动作 + 监控摘要事件流
- 自选操作栏收敛 + 服务端分页 + URL 状态
- 设置去双导航 + 配置管理拆子路由 + 日志合并
- 标签管理增强（关联数/批量/合并）

验收：每个能力只有一个主入口；深链可还原页面状态。

---

## 六、回归测试重点（全部在容器内执行）

1. 权限：普通用户 token 调用 database/logs/multi-source 写端点返回 403；管理员正常。
2. 深链：`/settings?tab=appearance` 高亮正确；`/analysis/history` 落“分析任务-已完成”；`/tasks?tab=scheduled` 落定时任务。
3. 缓存：常用策略切走再回保留筛选与滚动；任务中心切走再回自动刷新。
4. 交易：超资金、超可用持仓、A 股非整手三种输入均在提交前被拦截；成交回执可跳持仓。
5. 数据：手工加仓来源为 manual，复盘统计不受影响；监控指令执行后持仓可见。
6. 兼容：批量导出若改为 zip 下载，验证 Chrome/Safari 下载行为；分页改动后原有筛选组合结果一致。

## 七、风险与取舍

- 给 database / logs 加管理员校验会影响现有运维脚本，需同步改脚本账号。
- lot_size 校验若硬编码会与后续市场规则冲突，必须读 `paper_market_rules`。
- 配置管理拆子路由会影响收藏的旧链接，需保留 `/settings/config` 到默认分组的重定向。
- 速览首屏重排会改变用户既有肌肉记忆，建议保留模块顺序，只新增顶部“今日待办”条，降低适应成本。
- 任务中心默认 Tab 改为“分析任务”属于行为变更，需在更新说明中告知。
