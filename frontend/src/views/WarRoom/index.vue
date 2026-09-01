<template>
  <div class="war-room app-page">
    <!-- 顶部横幅 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">今日作战 · {{ todayText }}</h2>
          <p class="page-hero-sub">盘前 / 盘中 / 盘后 / 周度复盘一屏走完</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="refreshCurrent">
          刷新
        </el-button>
        <el-button :icon="Setting" @click="goScheduled">任务调度</el-button>
      </div>
    </div>

    <!-- 流程引导条 -->
    <div class="flow-bar">
      <div
        v-for="seg in flowSegments"
        :key="seg.key"
        class="flow-seg"
        :class="{ active: seg.key === activeTab }"
        @click="onTabChange(tabIndexMap[seg.key])"
      >
        <span class="flow-dot">{{ seg.key === currentPeriod ? '●' : '○' }}</span>
        <span class="flow-name">{{ seg.label }}</span>
        <span v-if="seg.count > 0" class="flow-badge">{{ seg.count }}</span>
      </div>
      <div class="flow-spacer"></div>
      <span class="flow-todo">待办合计 <b>{{ todayData?.total_todo ?? 0 }}</b>
        <span class="flow-todo-sub">计划 {{ todayData?.pre_market?.plan_pending ?? 0 }} · 预警 {{ alertsUnread }} · 信号 {{ todayData?.post_market?.signal_pending ?? 0 }}</span>
      </span>
    </div>

    <!-- 时段 Tab -->
    <el-tabs v-model="activeTab" class="war-tabs" @tab-change="onTabChange">
      <!-- ============ 盘前 ============ -->
      <el-tab-pane label="盘前" name="pre_market">
        <template v-if="macro">
          <!-- ① 宏观方向判断（置顶大卡） -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Compass /></el-icon> 宏观方向判断</span>
              <span v-if="macro.created_at" class="block-hint">生成于 {{ fmtClock(macro.created_at) }}</span>
              <div class="block-actions">
                <span v-if="!macro.llm_available" class="block-hint llm-off">解读不可用（仅规则结果）</span>
                <el-button size="small" :icon="Refresh" :loading="macroRefreshing" @click="refreshMacro">立即刷新</el-button>
              </div>
            </div>
            <el-card shadow="never" class="direction-card">
              <div class="dir-row">
                <span class="dir-badge" :class="directionClass">{{ ruleDirection }}</span>
                <span class="dir-score">规则总分 <b>{{ rule?.score ?? 0 }}</b></span>
              </div>
              <div class="signal-list" v-if="rule?.signals?.length">
                <div v-for="(s, i) in rule.signals" :key="i" class="signal-row">
                  <span class="sig-name">{{ s.name }}</span>
                  <span class="sig-detail">{{ s.detail }}</span>
                  <span class="sig-score" :class="s.score > 0 ? 'up' : s.score < 0 ? 'down' : ''">
                    {{ s.score > 0 ? `+${s.score}` : s.score }}
                  </span>
                </div>
              </div>
              <el-empty v-else :image-size="40" description="暂无规则依据" />
            </el-card>
            <div v-if="llm" class="llm-card">
              <div class="llm-sec">
                <div class="llm-tag">今日关键词</div>
                <div class="llm-body">
                  <template v-if="llm.keywords?.length">
                    <span v-for="(k, i) in llm.keywords" :key="i" class="llm-kw">{{ k }}</span>
                  </template>
                  <span v-else>—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">事件影响</div>
                <div class="llm-body">
                  <div v-for="(line, i) in splitItems(llm.event_impact)" :key="'ei' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.event_impact">—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">风格倾向</div>
                <div class="llm-body">
                  <div v-for="(line, i) in splitItems(llm.style_tendency)" :key="'st' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.style_tendency">—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">风险提示</div>
                <div class="llm-body risk">
                  <div v-for="(line, i) in splitItems(llm.risk_tips)" :key="'rt' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.risk_tips">—</span>
                </div>
              </div>
            </div>
          </section>

          <!-- ② 外围市场快照（指数 / 美股 / 港股分类，样式仿大盘看板全球市场） -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Position /></el-icon> 外围市场快照</span>
              <div class="block-actions">
                <span class="block-hint">指数 / 美股 / 港股</span>
                <el-button size="small" :icon="Refresh" :loading="macroRefreshing || foreignStocksLoading" @click="refreshForeignMarket">刷新</el-button>
              </div>
            </div>

            <div class="sub-block">
              <div class="sub-title"><el-icon><DataLine /></el-icon> 指数</div>
              <div class="grid grid-4">
                <el-card v-for="idx in macro.indices || []" :key="idx.key" shadow="never" class="idx-card">
                  <div class="idx-name">{{ idx.name }}<span class="region">{{ idx.region }}</span></div>
                  <div class="idx-price">{{ idx.price != null ? idx.price.toFixed(2) : '—' }}</div>
                  <div class="idx-pct" :class="clsByVal(idx.change_pct, '')">{{ fmtPct(idx.change_pct) }}</div>
                </el-card>
                <el-empty v-if="!macro.indices?.length" :image-size="48" description="暂无指数数据" />
              </div>
            </div>

            <div class="sub-block">
              <div class="sub-title"><el-icon><DataLine /></el-icon> 美股</div>
              <div class="grid grid-4">
                <el-card v-for="s in foreignUsStocks" :key="s.secid" shadow="never" class="idx-card">
                  <div class="idx-name">{{ s.name }}<span class="region">美股</span></div>
                  <div class="idx-price">{{ s.price != null ? s.price.toFixed(2) : '—' }}</div>
                  <div class="idx-pct" :class="clsByVal(s.change_pct, '')">{{ fmtPct(s.change_pct) }}</div>
                </el-card>
                <el-empty v-if="!foreignUsStocks.length" :image-size="48" description="暂无美股数据" />
              </div>
            </div>

            <div class="sub-block">
              <div class="sub-title"><el-icon><DataLine /></el-icon> 港股</div>
              <div class="grid grid-4">
                <el-card v-for="s in foreignHkStocks" :key="s.secid" shadow="never" class="idx-card">
                  <div class="idx-name">{{ s.name }}<span class="region">港股</span></div>
                  <div class="idx-price">{{ s.price != null ? s.price.toFixed(2) : '—' }}</div>
                  <div class="idx-pct" :class="clsByVal(s.change_pct, '')">{{ fmtPct(s.change_pct) }}</div>
                </el-card>
                <el-empty v-if="!foreignHkStocks.length" :image-size="48" description="暂无港股数据" />
              </div>
            </div>
          </section>

          <!-- ③ 今日财经日历 -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Calendar /></el-icon> 今日财经日历</span>
              <span class="block-hint">未来 7 日（东财优先 · AKShare 兜底）</span>
            </div>
            <el-table v-loading="loading" :data="macro.calendar || []" stripe size="small" class="app-table app-table--compact">
              <el-table-column label="日期" width="110">
                <template #default="{ row }">{{ row.date }}</template>
              </el-table-column>
              <el-table-column label="地区" width="80">
                <template #default="{ row }">{{ regionLabel(row.region) }}</template>
              </el-table-column>
              <el-table-column prop="event" label="事件" min-width="220" />
              <el-table-column label="重要性" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="importanceTag(row.importance)">{{ importanceLabel(row.importance) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="forecast" label="预期" width="90" />
              <el-table-column prop="actual" label="实际" width="90" />
            </el-table>
            <el-empty v-if="!macro.calendar?.length" description="暂无财经日历数据" />
          </section>

          <!-- ④ 重要快讯 -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Bell /></el-icon> 重要快讯</span>
              <span class="block-hint">近 24 小时 · 高/中重要性</span>
            </div>
            <div class="news-list">
              <div v-for="(n, i) in macro.news_top || []" :key="i" class="news-row">
                <el-tag size="small" :type="importanceTag(n.importance)">{{ importanceLabel(n.importance) }}</el-tag>
                <a v-if="n.url" class="news-title" :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
                <span v-else class="news-title">{{ n.title }}</span>
                <span class="news-time">{{ newsTime(n.publish_time) }}</span>
              </div>
              <el-empty v-if="!macro.news_top?.length" :image-size="48" description="暂无快讯" />
            </div>
          </section>
        </template>
        <template v-else-if="macroRefreshing">
          <el-empty loading description="正在生成今日宏观快照…" />
        </template>
        <el-empty v-else-if="!loading" description="今日宏观快照未生成">
          <el-button size="small" type="primary" :icon="Refresh" :loading="macroRefreshing" @click="refreshMacro">立即生成</el-button>
        </el-empty>

        <!-- ⑤ 当日计划 -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Tickets /></el-icon> 当日计划</span>
            <el-button size="small" type="primary" :icon="Plus" @click="openPlanDialog">添加计划</el-button>
          </div>
          <el-table v-loading="plansLoading" :data="plans" stripe size="small" class="app-table app-table--compact">
            <el-table-column prop="name" label="标的" min-width="120">
              <template #default="{ row }">{{ row.name || row.code }}</template>
            </el-table-column>
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <span :class="row.direction === 'buy' ? 'up' : 'down'">{{ row.direction_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触发价" width="100">
              <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="仓位" width="110">
              <template #default="{ row }">{{ positionText(row.position) }}</template>
            </el-table-column>
            <el-table-column prop="stop_loss" label="止损" width="100">
              <template #default="{ row }">{{ row.stop_loss ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="sell_condition" label="卖出条件" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="planStatusTag(row.status)">{{ planStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!plans.length" description="今日暂无计划，盘前写下来盘中严格执行" />
        </section>
      </el-tab-pane>

      <!-- ============ 盘中 ============ -->
      <el-tab-pane label="盘中" name="intraday">
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Odometer /></el-icon> 大盘状态条</span>
          </div>
          <div v-if="regime" class="regime-bar" :class="'regime-' + regime.trend">
            <div class="regime-chip">
              <el-icon><TrendCharts v-if="regime.trend === 'bull'" /><Bottom v-else-if="regime.trend === 'bear'" /><Minus v-else /></el-icon>
              <span class="regime-label">{{ regime.trend_label }}</span>
              <span class="regime-vol">· {{ regime.volatility_label }}</span>
            </div>
            <div v-if="regime.advice" class="regime-advice">
              <el-icon><InfoFilled /></el-icon>
              <span>{{ regime.advice }}</span>
            </div>
            <span v-if="regime.as_of" class="regime-asof">{{ regime.as_of }}</span>
          </div>
          <el-empty v-else :image-size="48" description="暂无市场环境数据" />
        </section>

        <!-- ①.5 今日预警（角标数字对应本列表行数，顶部「盘中」待办） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Bell /></el-icon> 今日预警
              <span class="block-hint">今日触发 {{ todayData?.intraday?.alert_count ?? todayAlerts.length }} 条</span>
            </span>
            <router-link to="/stock-alerts" class="more-link">监控中心页 →</router-link>
          </div>
          <el-table v-loading="alertsLoading" :data="todayAlerts" stripe size="small" class="app-table app-table--compact" max-height="360">
            <el-table-column label="标的" min-width="110">
              <template #default="{ row }">{{ row.name }} <span class="fav-code">{{ row.symbol }}</span></template>
            </el-table-column>
            <el-table-column label="级别" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.severity === 'critical' ? 'danger' : row.severity === 'warn' ? 'warning' : 'info'">{{ severityLabel(row.severity) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="rule_name" label="触发规则" min-width="170" show-overflow-tooltip />
            <el-table-column label="现价 / 涨跌" min-width="110">
              <template #default="{ row }">
                <span>{{ row.price ?? '—' }}</span>
                <span v-if="row.change_pct != null" :class="clsByVal(row.change_pct, '')" class="sep">{{ fmtPct(row.change_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="80">
              <template #default="{ row }">{{ alertTime(row.ts) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!todayAlerts.length && !alertsLoading" :image-size="48" description="今日暂无触发预警" />
        </section>

        <!-- ② 监控中心（复用现有组件：价格/涨跌幅/持仓退出信号预警） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Lightning /></el-icon> 监控中心</span>
            <router-link to="/stock-alerts" class="more-link">监控中心页 →</router-link>
          </div>
          <MonitorCenter />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Coin /></el-icon> 持仓追踪</span>
            <router-link to="/portfolio" class="more-link">持仓追踪页 →</router-link>
          </div>
          <div class="kpi-row" v-if="posSummary">
            <div class="kpi-cell">
              <div class="kpi-label">持仓数</div>
              <div class="kpi-value">{{ posSummary.total_positions }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">总市值</div>
              <div class="kpi-value">{{ fmtMoney(posSummary.total_market_value, '¥') }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">浮动盈亏</div>
              <div class="kpi-value" :class="clsByVal(posSummary.total_profit_loss, '')">{{ fmtSigned(posSummary.total_profit_loss) }} 元</div>
            </div>
          </div>
          <el-table v-loading="plansLoading" :data="posSummary?.positions || []" stripe size="small" class="app-table app-table--compact" max-height="360">
            <el-table-column prop="stock_name" label="名称" min-width="120" />
            <el-table-column label="现价" width="100">
              <template #default="{ row }">{{ row.current_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="盈亏率" width="110">
              <template #default="{ row }">
                <span :class="clsByVal(row.profit_loss_rate, '')">{{ fmtPct(row.profit_loss_rate) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="止损 / 止盈" min-width="150">
              <template #default="{ row }">
                <span>{{ row.stop_loss_price ?? '—' }}</span>
                <span class="sep">/</span>
                <span>{{ row.take_profit_price ?? '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!posSummary?.positions?.length" :image-size="48" description="暂无持仓" />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><AlarmClock /></el-icon> 计划执行 · 实时价触达</span>
            <el-button size="small" :icon="Refresh" :loading="evalLoading" @click="evaluatePlans">对照实时价评估</el-button>
          </div>
          <el-table v-loading="evalLoading" :data="evalPlans" stripe size="small" class="app-table app-table--compact">
            <el-table-column prop="name" label="标的" min-width="120">
              <template #default="{ row }">{{ row.name || row.code }}</template>
            </el-table-column>
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <span :class="row.direction === 'buy' ? 'up' : 'down'">{{ row.direction_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触发价" width="100">
              <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="实时价" width="100">
              <template #default="{ row }">{{ row.last_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="可执行" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.triggered" type="danger" size="small">可执行</el-tag>
                <el-tag v-else type="info" size="small">待触达</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button v-if="row.triggered" size="small" type="primary" @click="goTrade(row)">去交易</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!evalPlans.length" :image-size="48" description="今日无待执行计划" />
        </section>

        <!-- ⑤ 自选重点（≤5 只实时行情） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Star /></el-icon> 自选重点</span>
            <router-link to="/favorites" class="more-link">全部自选 →</router-link>
          </div>
          <div class="grid grid-4">
            <el-card v-for="f in favorites.slice(0, 5)" :key="f.symbol || f.stock_code" shadow="never" class="idx-card">
              <div class="idx-name">{{ f.stock_name }} <span class="fav-code">{{ f.symbol || f.stock_code }}</span></div>
              <div class="idx-price">{{ f.current_price != null ? f.current_price.toFixed(2) : '—' }}</div>
              <div class="idx-pct" :class="clsByVal(f.change_percent, '')">{{ fmtPct(f.change_percent) }}</div>
            </el-card>
            <el-empty v-if="!favorites.length" :image-size="48" description="暂无自选重点，去自选页添加" />
          </div>
        </section>
      </el-tab-pane>

      <!-- ============ 盘后 ============ -->
      <el-tab-pane label="盘后" name="post_market">
        <!-- ① 信号扫描结果（三买三卖，扫描后自动落库 signal_tracking） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><MagicStick /></el-icon> 信号扫描结果</span>
            <el-button size="small" type="primary" :icon="Search" :loading="scanLoading" @click="runScan">
              运行三买三卖扫描（自动落库）
            </el-button>
          </div>
          <div v-if="scanResult" class="scan-summary">
            <span>共 <b>{{ scanResult.total }}</b> 只命中<template v-if="scanResult.scanned_count"> · 扫描 {{ scanResult.scanned_count }} 只</template></span>
            <span v-if="scanResult.market_trend"> · 大盘趋势 {{ scanResult.market_trend }}</span>
          </div>
          <el-table v-loading="scanLoading" :data="scanResult?.items || []" stripe size="small" class="app-table app-table--compact" max-height="420">
            <el-table-column label="标的" min-width="120">
              <template #default="{ row }">{{ row.name }} <span class="fav-code">{{ row.code }}</span></template>
            </el-table-column>
            <el-table-column prop="primary_signal_label" label="信号" width="100" />
            <el-table-column label="收盘" width="90">
              <template #default="{ row }">{{ row.close ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="BIAS60" width="90">
              <template #default="{ row }">{{ row.bias60?.toFixed(2) ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="ma60_direction" label="MA60" width="80" />
            <el-table-column label="触发价" width="90">
              <template #default="{ row }">{{ row.signals?.[0]?.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" :icon="Plus" @click="addScanToPlan(row)">加入计划</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!scanResult" :image-size="48" description="点击上方按钮运行盘后信号扫描，命中信号自动写入「信号跟踪」" />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Search /></el-icon> 信号跟踪</span>
            <div class="block-actions">
              <el-button size="small" :icon="Refresh" :loading="signalsLoading" @click="loadSignals">刷新</el-button>
              <el-button size="small" type="primary" :loading="backfillLoading" @click="triggerBackfill">回填到期信号</el-button>
            </div>
          </div>
          <div class="kpi-row" v-if="signalStats?.total">
            <div class="kpi-cell">
              <div class="kpi-label">已回填</div>
              <div class="kpi-value">{{ signalStats.total.count ?? signalStats.total?.count ?? 0 }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">胜率</div>
              <div class="kpi-value up">{{ fmtPct(signalStats.total.win_rate) }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">待验证</div>
              <div class="kpi-value">{{ signalStats.pending_count ?? 0 }}</div>
            </div>
          </div>
          <el-table v-loading="signalsLoading" :data="signals" stripe size="small" class="app-table app-table--compact" max-height="420">
            <el-table-column prop="signal_type" label="信号" width="90" />
            <el-table-column label="标的" width="120">
              <template #default="{ row }">{{ row.name || row.code }}</template>
            </el-table-column>
            <el-table-column prop="trigger_date" label="触发日" width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'filled' ? 'success' : 'info'">
                  {{ row.status === 'filled' ? '已回填' : '待验证' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="实际表现" min-width="140">
              <template #default="{ row }">
                <template v-if="row.filled">
                  <span :class="clsByVal(row.filled.ret, '')">{{ fmtPct(row.filled.ret) }}</span>
                  <span class="sep">·</span>
                  <span :class="row.filled.outcome === 'win' ? 'up' : row.filled.outcome === 'loss' ? 'down' : ''">{{ outcomeLabel(row.filled.outcome) }}</span>
                  <span v-if="row.filled.hit_stop" class="hit-stop">触止损</span>
                </template>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="快照" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ snapshotText(row.snapshot) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!signals.length" :image-size="48" description="暂无信号记录，三买三卖扫描后自动落库" />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Document /></el-icon> 交易复盘 · 当日成交</span>
            <router-link to="/paper/review" class="more-link">交易复盘页 →</router-link>
          </div>
          <el-table v-loading="tradesLoading" :data="todayTrades" stripe size="small" class="app-table app-table--compact" max-height="360">
            <el-table-column label="标的" min-width="120">
              <template #default="{ row }">{{ row.name }} <span class="fav-code">{{ row.code }}</span></template>
            </el-table-column>
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="90">
              <template #default="{ row }">{{ row.quantity }}</template>
            </el-table-column>
            <el-table-column label="价格" width="100">
              <template #default="{ row }">{{ row.price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="金额" width="120">
              <template #default="{ row }">{{ row.amount != null ? Number(row.amount).toFixed(2) : '—' }}</template>
            </el-table-column>
            <el-table-column label="盈亏" width="110">
              <template #default="{ row }">
                <span v-if="row.pnl != null" :class="clsByVal(row.pnl, '')">{{ fmtSigned(row.pnl) }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="strategy" label="策略" width="100" />
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ tradeTime(row.timestamp) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!todayTrades.length" :image-size="48" description="今日暂无成交记录" />
          <p class="block-tip" style="margin-top: 10px">盘后 Step1 更新数据 · Step2 信号扫描落库 · Step3 次日计划预填，见上方信号跟踪与盘前 Tab 计划。</p>
        </section>

        <!-- ④ 次日计划预填（接近买点标的 → 一键加入计划） -->
        <section class="block" v-if="scanResult?.items?.length">
          <div class="block-head">
            <span class="block-title"><el-icon><Tickets /></el-icon> 次日计划预填</span>
            <span class="block-hint">接近买点标的，点击卡片加入明日计划</span>
          </div>
          <div class="scan-prefill-grid">
            <div v-for="row in scanResult.items.slice(0, 6)" :key="row.code" class="prefill-card" @click="addScanToPlan(row)">
              <div class="prefill-name">{{ row.name }} <span class="fav-code">{{ row.code }}</span></div>
              <div class="prefill-line">触发 <b>{{ row.signals?.[0]?.trigger_price ?? row.close }}</b> · 止损 {{ row.stop_price ?? '—' }}</div>
              <div class="prefill-line sub">{{ row.primary_signal_label }} · BIAS60 {{ row.bias60?.toFixed(2) }}</div>
            </div>
          </div>
        </section>
      </el-tab-pane>

      <!-- ============ 周度复盘 ============ -->
      <el-tab-pane label="周度复盘" name="weekly">
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Histogram /></el-icon> 定量统计</span>
            <div class="block-actions">
              <el-button v-if="!weekly" size="small" type="primary" :loading="genWeeklyLoading" @click="generateWeekly">
                生成周报
              </el-button>
              <el-button v-else size="small" :icon="Refresh" :loading="genWeeklyLoading" @click="generateWeekly">
                重新生成
              </el-button>
            </div>
          </div>
          <template v-if="weekly">
            <div class="kpi-row">
              <div class="kpi-cell">
                <div class="kpi-label">本周收益率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.weekly_return, '')">{{ fmtPct(weekly.quant?.weekly_return) }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">vs 沪深300</div>
                <div class="kpi-value" :class="clsByVal(weekly.excess_return, '')">{{ fmtPct(weekly.excess_return) }}</div>
                <div class="kpi-sub">基准 {{ fmtPct(weekly.benchmark?.ret_pct) }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">交易笔数</div>
                <div class="kpi-value">{{ weekly.quant?.trade_count }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">胜率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.win_rate, '')">{{ fmtPct(weekly.quant?.win_rate) }}</div>
                <div class="kpi-sub">{{ weekly.quant?.win_count }}/{{ weekly.quant?.sell_count }} 笔盈利</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">持仓全红率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.all_red_rate, '')">{{ fmtPct(weekly.quant?.all_red_rate) }}</div>
                <div class="kpi-sub">{{ weekly.quant?.profitable_count }}/{{ weekly.quant?.holding_count }} 持仓</div>
              </div>
            </div>
            <div v-if="!weekly.benchmark?.available" class="benchmark-warn">
              <el-icon><Warning /></el-icon> 沪深300 数据不可用：{{ weekly.benchmark?.message }}
            </div>
          </template>
          <el-empty v-else :image-size="48" description="本周复盘待生成（顶部「周度」待办 1）：周五盘后自动生成，或点右上角立即生成" />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Coin /></el-icon> 信号有效性（P1 回填聚合）</span>
          </div>
          <el-table v-if="weekly?.signal_stats?.by_type?.length" :data="weekly.signal_stats.by_type" stripe size="small" class="app-table app-table--compact">
            <el-table-column prop="signal_type" label="信号类型" width="110" />
            <el-table-column prop="count" label="样本数" width="90" />
            <el-table-column label="胜率" width="110">
              <template #default="{ row }">
                <span :class="clsByVal(row.win_rate, '')">{{ fmtPct(row.win_rate) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="平均收益" width="110">
              <template #default="{ row }">
                <span :class="clsByVal(row.avg_ret, '')">{{ fmtPct(row.avg_ret) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触止损率" width="110">
              <template #default="{ row }">{{ fmtPct(row.hit_stop_rate) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!weekly?.signal_stats?.by_type?.length" :image-size="48" description="暂无已回填信号统计" />
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><EditPen /></el-icon> 定性回顾</span>
            <router-link to="/paper/review" class="more-link">写复盘笔记 →</router-link>
          </div>
          <p class="block-tip">做对了什么 / 做错了什么 / 有没有违反系统规则 / 三系统信号一致性 —— 在交易复盘页记录。</p>
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Calendar /></el-icon> 下周计划</span>
            <router-link to="/war-room?tab=pre_market" class="more-link">去盘前写计划 →</router-link>
          </div>
          <p class="block-tip">大盘趋势判断 + 关注标的 + 预期操作，在盘前 Tab 的「当日计划」中落地。</p>
        </section>
      </el-tab-pane>
    </el-tabs>

    <!-- 添加计划弹窗 -->
    <el-dialog v-model="planDialog" title="添加当日计划" width="520px">
      <el-form :model="planForm" label-width="90px">
        <el-form-item label="代码">
          <el-input v-model="planForm.code" placeholder="如 600519" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="planForm.name" placeholder="可选，自动解析" />
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="planForm.direction">
            <el-radio value="buy">买入</el-radio>
            <el-radio value="sell">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="触发价">
          <el-input-number v-model="planForm.trigger_price" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="止损位">
          <el-input-number v-model="planForm.stop_loss" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="卖出条件">
          <el-input v-model="planForm.sell_condition" placeholder="如 跌破MA60 / 涨超+5% 减半" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingPlan" @click="submitPlan">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Aim, Refresh, Setting, Compass, Position, Calendar, Bell, Tickets, Plus,
          Odometer, TrendCharts, Bottom, Minus, InfoFilled, Coin, AlarmClock,
          Search, Document, Histogram, Warning, EditPen, Star, Lightning, MagicStick, DataLine
} from '@element-plus/icons-vue'
import { warRoomApi, type WarRoomToday } from '@/api/warRoom'
import { portfolioApi } from '@/api/portfolio'
import { favoritesApi } from '@/api/favorites'
import { screeningApi } from '@/api/screening'
import MonitorCenter from '@/components/Dashboard/MonitorCenter.vue'
import { subscribeQuotesUpdate, type QuotesUpdateSignal } from '@/utils/quotesSSE'
import { fmtPct, fmtSigned, fmtMoney, clsByVal } from '@/utils/format'

defineOptions({ name: 'WarRoomHome' })

const route = useRoute()
const router = useRouter()

const activeTab = ref('pre_market')
const loading = ref(false)
const plansLoading = ref(false)
const evalLoading = ref(false)
const signalsLoading = ref(false)
const backfillLoading = ref(false)
const genWeeklyLoading = ref(false)
const creatingPlan = ref(false)
const macroRefreshing = ref(false)
const tradesLoading = ref(false)
const todayTrades = ref<any[]>([])
const todayAlerts = ref<any[]>([])
const alertsLoading = ref(false)

// 今日预警「已读」标记（按日期维度）：查看过盘中预警列表后即视为已读，角标清零
const ALERTS_READ_KEY = 'war_alerts_read_date'
function alertReadKey() {
  const d = new Date()
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}
let alertsReadDate = localStorage.getItem(ALERTS_READ_KEY) || ''
const alertsReadToday = computed(() => alertsReadDate === alertReadKey())
const alertsUnread = computed(() => {
  if (alertsReadToday.value) return 0
  return todayData.value?.intraday?.alert_count || todayAlerts.value.length || 0
})

const todayData = ref<WarRoomToday | null>(null)
const macro = ref<any>(null)
const foreignStocksLoading = ref(false)
const foreignStocks = ref<any[]>([])
const foreignUsStocks = computed(() => foreignStocks.value.filter(s => s.region === '美股'))
const foreignHkStocks = computed(() => foreignStocks.value.filter(s => s.region === '港股'))
const llm = computed(() => macro.value?.llm_interpretation || null)
const rule = computed(() => macro.value?.rule || null)
const plans = ref<any[]>([])
const evalPlans = ref<any[]>([])
const regime = ref<any>(null)
const posSummary = ref<any>(null)
const signals = ref<any[]>([])
const signalStats = ref<any>(null)
const weekly = ref<any>(null)
const favorites = ref<any[]>([])
const scanResult = ref<any>(null)
const scanLoading = ref(false)

const todayText = computed(() => {
  const d = new Date()
  const wd = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 周${wd}`
})

const flowSegments = computed(() => [
  { key: 'pre_market', label: '盘前', count: (todayData.value?.pre_market?.plan_pending || 0) + (todayData.value?.pre_market?.macro_snapshot_ready ? 0 : 1) },
  { key: 'intraday', label: '盘中', count: alertsUnread.value },
  { key: 'post_market', label: '盘后', count: todayData.value?.post_market?.signal_pending || 0 },
  { key: 'weekly', label: '周度', count: todayData.value?.weekly?.todo ?? 0 }
])
const tabIndexMap: Record<string, string> = { pre_market: 'pre_market', intraday: 'intraday', post_market: 'post_market', weekly: 'weekly' }
const currentPeriod = computed(() => todayData.value?.current_period || 'pre_market')

// 将含编号（①.../1. 1、1)）的 LLM 解读文本切分为独立行，便于逐条阅读。
// 用「编号后不紧跟数字」排除百分比/小数（如 1.14%、0.94%）误切分。
function splitItems(text?: string | string[]): string[] {
  if (!text) return []
  // 后端可能直接返回数组（如 risk_tips 风险提示），无需再拆分
  if (Array.isArray(text)) return text
  return text
    .split(/(?=[①-⑩]|第[一二三四五六七八九十]+[、]|(?<![.\d])\d{1,2}[.、)](?!\d))/)
    .map(s => s.trim())
    .filter(Boolean)
}

// 快照生成时间格式化：今日显示「今日 HH:MM」，否则「M/D HH:MM」
function fmtClock(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.toDateString() === new Date().toDateString()
    ? `今日 ${hm}`
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

const ruleDirection = computed(() => {
  const d = rule.value?.direction
  if (!d) return '—'
  if (d.includes('多')) return '偏多'
  if (d.includes('空')) return '偏空'
  return '中性'
})
const directionClass = computed(() => {
  const d = rule.value?.direction
  if (d?.includes('多')) return 'bull'
  if (d?.includes('空')) return 'bear'
  return 'neutral'
})

// ---- 数据加载 ----
async function loadToday() {
  try {
    todayData.value = await warRoomApi.getToday()
  } catch (e) {
    console.warn('[WarRoom] loadToday', e)
  }
}

async function loadMacro(retry = true) {
  loading.value = true
  try {
    const data = await warRoomApi.getMacroOverview()
    macro.value = data
    // Debug 标记：成功时写入 generated_at
    if (data && typeof document !== 'undefined') {
      document.body.setAttribute('data-macro-state', 'ok-' + (data.created_at ? 'has-created_at' : 'no-created_at'))
    }
  } catch (e: any) {
    macro.value = null
    if (typeof document !== 'undefined') {
      document.body.setAttribute('data-macro-error', String(e?.message || e).slice(0, 200))
    }
  }
  // 兜底：读取返回空（快照尚未生成/后端生成延迟）时自动重试一次，
  // 避免进入盘前就撞上空态，之后仍为空再由用户点「立即生成」。
  if (macro.value === null && retry) {
    await new Promise(r => setTimeout(r, 1500))
    try {
      const data = await warRoomApi.getMacroOverview()
      macro.value = data
      if (data && typeof document !== 'undefined') {
        document.body.setAttribute('data-macro-state', 'ok-retry')
      }
    } catch (e: any) {
      macro.value = null
      if (typeof document !== 'undefined') {
        document.body.setAttribute('data-macro-error', 'retry:' + String(e?.message || e).slice(0, 200))
      }
    }
  }
  loading.value = false
}

async function loadGlobalStocks() {
  foreignStocksLoading.value = true
  try {
    const { vibeApi } = await import('@/api/vibe')
    const res: any = await vibeApi.getGlobalStocks()
    foreignStocks.value = res?.data || []
  } catch (e) {
    console.warn('[WarRoom] loadGlobalStocks', e)
  } finally {
    foreignStocksLoading.value = false
  }
}

async function refreshForeignMarket() {
  // 外围市场快照刷新：宏观快照（含外围指数）+ 美股/港股个股行情
  await Promise.all([refreshMacro(), loadGlobalStocks()])
}

async function loadPlans() {
  plansLoading.value = true
  try {
    const data = await warRoomApi.getPlans()
    plans.value = data?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadPlans', e)
  } finally {
    plansLoading.value = false
  }
}

async function loadSignals() {
  signalsLoading.value = true
  try {
    const [list, stats] = await Promise.all([
      warRoomApi.getSignals(undefined, 50),
      warRoomApi.getSignalStats()
    ])
    signals.value = list?.items || []
    signalStats.value = stats || null
  } catch (e) {
    console.warn('[WarRoom] loadSignals', e)
  } finally {
    signalsLoading.value = false
  }
}

async function loadTodayTrades() {
  tradesLoading.value = true
  try {
    const res = await warRoomApi.getTodayTrades()
    todayTrades.value = res?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadTodayTrades', e)
  } finally {
    tradesLoading.value = false
  }
}

async function loadTodayAlerts() {
  alertsLoading.value = true
  try {
    const res = await warRoomApi.getTodayAlerts()
    todayAlerts.value = res?.items || []
    // 用户已进入盘中查看预警列表 → 标记今日已读，红色角标清零
    if (todayAlerts.value.length > 0) {
      alertsReadDate = alertReadKey()
      localStorage.setItem(ALERTS_READ_KEY, alertsReadDate)
    }
  } catch (e) {
    console.warn('[WarRoom] loadTodayAlerts', e)
  } finally {
    alertsLoading.value = false
  }
}

async function refreshMacro() {
  macroRefreshing.value = true
  try {
    macro.value = await warRoomApi.refreshMacro()
    ElMessage.success('宏观快照已刷新')
    await loadToday()
  } catch (e) {
    ElMessage.error('宏观快照刷新失败，请稍后重试')
  } finally {
    macroRefreshing.value = false
  }
}

async function loadRegime() {
  try {
    // 设计文档 A.3 Tab2①：大盘状态条复用市场看板 regime（趋势/波动/建议）
    const { vibeApi } = await import('@/api/vibe')
    const res: any = await vibeApi.getDashboard()
    regime.value = res?.data?.regime || null
  } catch (e) {
    console.warn('[WarRoom] loadRegime', e)
  }
}

async function loadPositions() {
  try {
    const res = await portfolioApi.getSummary()
    posSummary.value = res?.data || null
  } catch (e) {
    console.warn('[WarRoom] loadPositions', e)
  }
}

async function loadWeekly() {
  try {
    weekly.value = await warRoomApi.getWeeklyReview()
  } catch (e) {
    console.warn('[WarRoom] loadWeekly', e)
  }
}

async function loadFavorites() {
  try {
    const res: any = await favoritesApi.list()
    favorites.value = (res?.data || []) as any[]
  } catch (e) {
    console.warn('[WarRoom] loadFavorites', e)
  }
}

async function runScan() {
  scanLoading.value = true
  try {
    const res: any = await screeningApi.scanThreeBuysThreeSells({ top_n: 30, limit: 20 })
    scanResult.value = res?.data || null
    ElMessage.success(`扫描完成，命中 ${scanResult.value?.total ?? 0} 只，信号已自动落库`)
    await loadSignals()
    await loadToday()
  } catch (e) {
    ElMessage.error('三买三卖扫描失败（可能超时，可重试）')
  } finally {
    scanLoading.value = false
  }
}

function addScanToPlan(row: any) {
  planForm.value = {
    code: row.code,
    name: row.name,
    direction: 'buy',
    trigger_price: row.signals?.[0]?.trigger_price ?? row.close,
    stop_loss: row.stop_price ?? undefined,
    sell_condition: `${row.primary_signal_label ?? '三买三卖'} · MA60 ${row.ma60_direction ?? ''}`.trim()
  }
  planDialog.value = true
}

async function evaluatePlans() {
  evalLoading.value = true
  try {
    const pending = await warRoomApi.getPlans(undefined, 'pending')
    const codes = (pending?.items || []).map((p: any) => p.code)
    if (codes.length === 0) {
      evalPlans.value = []
      return
    }
    // 批量取实时价（复用 vibe 行情）
    const { vibeApi } = await import('@/api/vibe')
    const qres: any = await vibeApi.getQuotes(codes)
    const quotes: Record<string, number> = {}
    for (const q of qres?.data || []) {
      if (q?.price != null) quotes[q.code] = q.price
    }
    const res: any = await warRoomApi.getPlans(undefined, 'pending')
    evalPlans.value = (res?.items || []).map((p: any) => {
      const last = quotes[p.code]
      const triggered = p.direction === 'buy'
        ? (last != null && p.trigger_price != null && last <= p.trigger_price)
        : (last != null && p.trigger_price != null && last >= p.trigger_price)
      return { ...p, last_price: last ?? null, triggered: !!triggered }
    })
  } catch (e) {
    console.warn('[WarRoom] evaluatePlans', e)
  } finally {
    evalLoading.value = false
  }
}

// ---- 盘中实时（SSE 订阅 + 30s 轮询兜底）----
// 设计文档 A.3 Tab2④ / A.5：SSE 订阅计划标的实时价，价格触达目标自动高亮"可执行"
let stopQuotes: (() => void) | null = null
let intradayPoll: number | null = null

function onQuotesUpdate(signal: QuotesUpdateSignal) {
  const qs = signal.quotes
  if (!qs) return
  evalPlans.value = evalPlans.value.map((p) => {
    const q = qs[p.code]
    if (!q || q.close == null) return p
    const triggered = p.direction === 'buy'
      ? (p.trigger_price != null && q.close <= p.trigger_price)
      : (p.trigger_price != null && q.close >= p.trigger_price)
    return { ...p, last_price: q.close, triggered: !!triggered }
  })
}

function startIntradayLive() {
  stopIntradayLive()
  stopQuotes = subscribeQuotesUpdate(onQuotesUpdate, (status) => {
    // connected / degraded：由轮询兜底，无需额外提示
  })
  intradayPoll = window.setInterval(() => { evaluatePlans() }, 30000)
}

function stopIntradayLive() {
  if (stopQuotes) { stopQuotes(); stopQuotes = null }
  if (intradayPoll) { window.clearInterval(intradayPoll); intradayPoll = null }
}

// ---- 操作 ----
async function triggerBackfill() {
  backfillLoading.value = true
  try {
    const res = await warRoomApi.triggerBackfill()
    ElMessage.success(`已回填 ${res?.filled ?? 0} 条到期信号`)
    await loadSignals()
    await loadWeekly()
  } catch (e) {
    ElMessage.error('回填失败')
  } finally {
    backfillLoading.value = false
  }
}

async function generateWeekly() {
  genWeeklyLoading.value = true
  try {
    await warRoomApi.generateWeeklyReview()
    ElMessage.success('周度复盘已生成')
    await loadWeekly()
  } catch (e) {
    ElMessage.error('周报生成失败')
  } finally {
    genWeeklyLoading.value = false
  }
}

const planDialog = ref(false)
const planForm = ref({ code: '', name: '', direction: 'buy', trigger_price: undefined as number | undefined, stop_loss: undefined as number | undefined, sell_condition: '' })

function openPlanDialog() {
  planForm.value = { code: '', name: '', direction: 'buy', trigger_price: undefined, stop_loss: undefined, sell_condition: '' }
  planDialog.value = true
}

async function submitPlan() {
  if (!planForm.value.code.trim()) {
    ElMessage.warning('请填写代码')
    return
  }
  creatingPlan.value = true
  try {
    await warRoomApi.createPlan({
      code: planForm.value.code.trim(),
      name: planForm.value.name || undefined,
      direction: planForm.value.direction,
      trigger_price: planForm.value.trigger_price,
      stop_loss: planForm.value.stop_loss,
      sell_condition: planForm.value.sell_condition || undefined
    })
    ElMessage.success('计划已保存')
    planDialog.value = false
    await loadPlans()
    await loadToday()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    creatingPlan.value = false
  }
}

function goTrade(row: any) {
  router.push(`/paper?code=${encodeURIComponent(row.code)}`)
}

function goScheduled() {
  router.push('/tasks')
}

function refreshCurrent() {
  loadToday()
  // 设计文档 A.5：进入 Tab/点刷新即拉取该时段静态数据
  if (activeTab.value === 'pre_market') { ensureMacroAuto(); loadGlobalStocks(); loadPlans() }
  if (activeTab.value === 'intraday') { loadTodayAlerts(); loadRegime(); loadPositions(); evaluatePlans(); loadFavorites(); startIntradayLive() }
  if (activeTab.value === 'post_market') { loadSignals(); loadTodayTrades() }
  if (activeTab.value === 'weekly') loadWeekly()
}

// 盘前宏观：读取已生成的今日快照（后端在快照缺失时会自动生成一次），
// 不强制重置；生成时间展示在卡片上，由用户自行判断是否点击「立即刷新」更新。
function ensureMacroAuto() {
  loadMacro()
}

function onTabChange(name: string | number) {
  // 流程引导条 .flow-seg 点击时会显式调用本函数（不会触发 el-tabs 内部 v-model 更新），
  // 所以先手动同步 activeTab，保证 UI 高亮 + 后续依赖 activeTab.value 的逻辑一致。
  activeTab.value = String(name)
  if (name === 'pre_market') { ensureMacroAuto(); loadGlobalStocks(); loadPlans() }
  if (name === 'intraday') { loadTodayAlerts(); loadRegime(); loadPositions(); evaluatePlans(); loadFavorites(); startIntradayLive() }
  if (name === 'post_market') { loadSignals(); loadTodayTrades() }
  if (name === 'weekly') loadWeekly()
  // 离开盘中 → 关闭 SSE 订阅与轮询
  if (name !== 'intraday') stopIntradayLive()
}

// ---- 格式化辅助 ----
function regionLabel(r?: string) {
  if (!r) return '—'
  if (r.toUpperCase().includes('CN')) return '中国'
  if (r.toUpperCase().includes('US')) return '美国'
  return r
}
function importanceLabel(v?: string) {
  if (v === 'high' || v === '高') return '高'
  if (v === 'medium' || v === '中') return '中'
  if (v === 'low' || v === '低') return '低'
  return v || '—'
}
type TagType = 'success' | 'warning' | 'info' | 'danger' | 'primary'
function importanceTag(v?: string): TagType {
  if (v === 'high' || v === '高') return 'danger'
  if (v === 'medium' || v === '中') return 'warning'
  return 'info'
}
function newsTime(t?: string) {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function tradeTime(t?: string) {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function severityLabel(s?: string) {
  return { critical: '严重', warn: '警告', info: '提示' }[s || ''] || s || '—'
}
function alertTime(ts?: number) {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}
function planStatusLabel(s: string) {
  return { pending: '待执行', executed: '已执行', cancelled: '已取消' }[s] || s
}
function planStatusTag(s: string): TagType {
  return { pending: 'warning', executed: 'success', cancelled: 'info' }[s] as TagType || 'info'
}
function positionText(p: any) {
  if (!p) return '—'
  if (p.shares) return `${p.shares}股 (${fmtPct(p.ratio * 100, 0)})`
  if (p.ratio) return fmtPct(p.ratio * 100, 0)
  return JSON.stringify(p)
}
function outcomeLabel(o: string) {
  return { win: '胜', loss: '负', flat: '平' }[o] || o
}
function snapshotText(s: any) {
  if (!s) return '—'
  const parts = ['bias', 'ma60', 'quadrant', 'price'].filter(k => s[k] != null)
  return parts.map(k => `${k}: ${s[k]}`).join(' ')
}

onMounted(async () => {
          // 从 query 支持 ?tab=pre_market 直达（速览引导条跳转）
          const q = route.query.tab
          if (typeof q === 'string' && tabIndexMap[q]) {
            activeTab.value = q
          }
          // today 聚合 + 当前时段 Tab 自动定位；与 macro 并发拉取，避免互相阻塞
          await loadToday()
          if (!(typeof q === 'string' && tabIndexMap[q])) {
            const cp = todayData.value?.current_period
            if (cp && tabIndexMap[cp]) activeTab.value = cp
          }
          refreshCurrent()
        })

onUnmounted(() => { stopIntradayLive() })
</script>

<style lang="scss" scoped>
.war-room {
  // 流程引导条
  .flow-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding: 12px 16px;
    margin-bottom: 20px;
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color-light);
    border-radius: 10px;

    .flow-seg {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 16px;
      cursor: pointer;
      color: var(--el-text-color-secondary);
      transition: all .2s;

      &.active {
        background: var(--el-color-primary-light-9);
        color: var(--el-color-primary);
        font-weight: 600;
      }
      .flow-dot { font-size: 12px; }
      .flow-badge {
        background: var(--el-color-danger);
        color: #fff;
        font-size: 11px;
        line-height: 1;
        padding: 2px 6px;
        border-radius: 10px;
      }
    }
    .flow-spacer { flex: 1; }
    .flow-todo { color: var(--el-text-color-secondary); font-size: 13px; b { color: var(--el-color-primary); } }
    .flow-todo-sub { margin-left: 8px; color: var(--el-text-color-placeholder); font-size: 12px; }
  }

  // 时段切换已由顶部「流程引导条」承载，隐藏 el-tabs 原生头部，避免出现两行重复导航
  .war-tabs :deep(.el-tabs__header) { display: none; }

  .block { margin-bottom: 24px; }
  .block-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    .block-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      .el-icon { color: var(--el-color-primary); }
    }
    .block-hint { font-size: 12px; color: var(--el-text-color-secondary); &.llm-off { color: var(--el-color-warning); } }
    .block-actions { display: flex; gap: 8px; }
  }
  .block-tip { color: var(--el-text-color-secondary); font-size: 13px; margin: 0; }

  // 宏观方向卡
  .direction-card {
    .dir-row { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
    .dir-badge {
      font-size: 18px; font-weight: 700; padding: 4px 14px; border-radius: 8px;
      &.bull { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
      &.bear { background: var(--el-color-success-light-9); color: var(--el-color-success); }
      &.neutral { background: var(--el-bg-color-page); color: var(--el-text-color-secondary); }
    }
    .dir-score { font-size: 13px; color: var(--el-text-color-secondary); b { color: var(--el-text-color-primary); } }
    .signal-list { display: flex; flex-direction: column; gap: 6px; }
    .signal-row {
      display: flex; align-items: center; gap: 12px; padding: 6px 10px;
      background: var(--el-bg-color-page); border-radius: 6px; font-size: 13px;
      .sig-name { flex: 0 0 160px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .sig-detail { flex: 1; color: var(--el-text-color-secondary); word-break: break-word; }
      .sig-score { width: 40px; text-align: right; font-weight: 600; }
    }
  }

  .llm-card {
    margin-top: 12px; padding: 14px 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-left: 3px solid var(--el-color-primary);
    border-radius: 8px;
    background: var(--el-bg-color);
    display: flex; flex-direction: column; gap: 12px;
    .llm-sec { display: flex; gap: 12px; font-size: 13px; color: var(--el-text-color-primary); }
    .llm-tag { flex: 0 0 76px; color: var(--el-color-primary); font-weight: 600; padding-top: 2px; }
    .llm-body { flex: 1; line-height: 1.75; word-break: break-word; }
    .llm-line { padding: 2px 0; }
    .llm-kw {
      display: inline-block; padding: 2px 10px; margin: 0 6px 6px 0;
      background: var(--el-color-primary-light-9); color: var(--el-color-primary);
      border-radius: 12px; font-size: 12px;
    }
    .llm-body.risk { color: var(--el-color-danger); }
  }

  .grid-4 {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px;
    .idx-card { text-align: center; }
    .idx-name { font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
    .idx-price { font-size: 20px; font-weight: 700; }
    .idx-pct { font-size: 14px; font-weight: 600; }
  }

  .region {
    display: inline-block; margin-left: 4px; padding: 0 6px;
    font-size: 11px; line-height: 16px; color: var(--el-text-color-secondary);
    background: var(--el-fill-color); border-radius: 4px; vertical-align: 1px;
  }

  .sub-block { margin-bottom: 18px; &:last-child { margin-bottom: 0; } }
  .sub-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 13px; font-weight: 600; color: var(--el-text-color-primary);
    margin-bottom: 10px;
    .el-icon { color: var(--el-color-primary); }
  }

  .news-list { display: flex; flex-direction: column; gap: 6px; }
  .news-row {
    display: flex; align-items: center; gap: 10px; padding: 6px 8px;
    border-bottom: 1px dashed var(--el-border-color-lighter); font-size: 13px;
    .news-title { flex: 1; color: var(--el-text-color-primary); text-decoration: none; word-break: break-word; }
    a.news-title:hover { color: var(--el-color-primary); }
    .news-time { color: var(--el-text-color-secondary); font-size: 12px; flex: 0 0 auto; }
  }

  .kpi-row {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 12px;
    .kpi-cell {
      background: var(--el-bg-color); border: 1px solid var(--el-border-color-light);
      border-radius: 8px; padding: 12px 14px; text-align: center;
      .kpi-label { font-size: 12px; color: var(--el-text-color-secondary); }
      .kpi-value { font-size: 22px; font-weight: 700; margin: 4px 0; }
      .kpi-sub { font-size: 12px; color: var(--el-text-color-secondary); }
    }
  }

  .regime-bar {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    padding: 12px 16px; border-radius: 10px; margin-bottom: 8px;
    &.regime-bull { background: var(--el-color-danger-light-9); }
    &.regime-bear { background: var(--el-color-success-light-9); }
    &.regime-sideways { background: var(--el-bg-color-page); }
    .regime-chip { display: flex; align-items: center; gap: 8px; font-weight: 600; }
    .regime-advice { display: flex; align-items: center; gap: 6px; font-size: 13px; flex: 1; }
    .regime-asof { font-size: 12px; color: var(--el-text-color-secondary); }
  }

  .more-link { color: var(--el-color-primary); font-size: 13px; text-decoration: none; }
  .sep { margin: 0 4px; color: var(--el-text-color-secondary); }
  .hit-stop { margin-left: 6px; color: var(--el-color-danger); font-size: 12px; }
  .benchmark-warn {
    display: flex; align-items: center; gap: 6px; margin-top: 10px;
    font-size: 13px; color: var(--el-color-warning);
  }

  .fav-code { color: var(--el-text-color-secondary); font-size: 12px; font-weight: 400; }

  .scan-summary {
    display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
    margin-bottom: 12px; padding: 8px 12px; font-size: 13px;
    background: var(--el-bg-color-page); border-radius: 8px;
    b { color: var(--el-color-primary); }
  }

  .scan-prefill-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px;
    .prefill-card {
      padding: 12px 14px; border: 1px solid var(--el-border-color-light);
      border-radius: 8px; background: var(--el-bg-color); cursor: pointer;
      transition: all .2s;
      &:hover { border-color: var(--el-color-primary); box-shadow: var(--el-box-shadow-light); }
      .prefill-name { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
      .prefill-line { font-size: 13px; color: var(--el-text-color-primary); b { color: var(--el-color-primary); } }
      .prefill-line.sub { color: var(--el-text-color-secondary); margin-top: 4px; }
    }
  }
}
</style>
