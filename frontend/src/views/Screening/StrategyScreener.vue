<template>
  <div class="strategy-screener app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 常用策略</h2>
          <p class="page-hero-sub">
            基于本地行情数据 · 策略筛选与评分排序
            <template v-if="isRealtimeResult">
              ·
              <el-icon :size="13"><Connection /></el-icon>
              {{ decisionWindow ? '收盘定格（可成交窗口）' : '盘中预警（暂定，15:00 定格确认）' }}
            </template>
            <template v-else-if="computedAt"> · <el-icon :size="13"><Clock /></el-icon> 数据更新于 {{ computedTime }}</template>
          </p>
          <!-- 行情时效：卡片日期 = 本地日线最新交易日，今日尚未入库时明确提示，避免被误读为「今日结果」 -->
          <p v-if="stalenessHint" class="page-hero-stale" :class="{ warn: latestLagDays > 1 }">
            <el-icon :size="13"><Warning /></el-icon>
            {{ stalenessHint }}
          </p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-select v-model="asOf" placeholder="选择交易日" size="default" class="date-select" filterable @change="onAsOfChange" :disabled="realtimeScan">
          <el-option v-for="d in tradeDates" :key="d" :label="d" :value="d" />
        </el-select>
        <div class="realtime-switch" :title="realtimeNote">
          <span class="rt-label">盘中预警</span>
          <el-switch :model-value="realtimeScan" size="default" @change="(v: string | number | boolean) => toggleRealtime(v as boolean)" />
        </div>
        <el-button type="primary" size="default" :loading="runningAll" @click="runAll(true)">
          <el-icon><Refresh /></el-icon>
          运行全部
        </el-button>
      </div>
    </div>

    <!-- 运行进度：全部策略为一个后端任务，无法按策略回填；
         这里给出已运行时长 + 停止等待，避免"卡死还是没跑"的猜测 -->
    <div v-if="runningAll" class="run-progress">
      <el-icon class="rp-spin"><Loading /></el-icon>
      <span class="rp-text">正在计算全部策略（包含行情与评分），已运行 {{ fmtElapsed(runElapsed) }}</span>
      <span class="rp-hint">通常 10~60 秒，最多等待 10 分钟</span>
      <el-button size="small" text type="primary" @click="stopWaiting">停止等待</el-button>
    </div>

    <!-- 收盘定格窗口：15:00-15:30 数据已定格、可按收盘价成交的决策黄金期 -->
    <div v-if="decisionWindow" class="close-window-banner">
      <div class="cw-orbit">
        <span class="cw-pulse"></span>
        <el-icon :size="16"><Clock /></el-icon>
      </div>
      <div class="cw-body">
        <span class="cw-title">收盘定格窗口 · 15:00–15:30</span>
        <span class="cw-sub">行情数据已定格，今日可按收盘价成交，无需等次日开盘。当前结果为收盘级判断，可据此直接决策。</span>
      </div>
      <div class="cw-side">
        <span class="cw-chip">可执行</span>
      </div>
    </div>

    <!-- 盘中预警条：开启盘中预警时，标识结果仍为暂定信号 -->
    <div v-else-if="isRealtimeResult" class="preview-banner">
      <el-icon :size="15"><Warning /></el-icon>
      <span>盘中预警 · 当前为暂定信号（盘中数据未完全定格），15:00 收盘定格后再做最终判断。</span>
    </div>

    <!-- 大盘×策略适配矩阵：仅盘中预警（实时模式）下展示 —— 矩阵四维=今日实时检测（60s 跟随），与「选择交易日」无关；
         平时隐藏，避免用户切换选股日期时误以为矩阵应随日期回看历史环境 -->
    <StrategyExplainPanel
      v-if="realtimeScan"
      :initial-dims="initialMatrixDims"
      :initial-portrait="marketState?.portrait"
      :auto-sync="realtimeScan"
      :live-metrics="liveMetrics"
      @portrait-change="syncPortrait"
    />

    <!-- 行情画像轮盘：把策略按大盘状态分组（8 组），当前画像高亮；
         解决「20+ 策略平铺看不过来」与「不知道什么行情该开哪个」两个问题 -->
    <el-card class="regime-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot" />
            行情画像分组
            <span class="panel-count">{{ strategyGroups.length }}</span>
          </div>
          <span class="header-hint">按大盘画像分成 8 组（9 个画像，熊市反弹并入熊市恐慌组）· 每组只建议开 1~2 个（同族信号重叠，同开=重复买同一笔）</span>
        </div>
      </template>
      <!-- 当前大盘状态：画像 + 四维 + 一句话建议 + 数据质量（唯一事实源的后端结论，页面不再自行判断） -->
      <div v-if="marketState" class="regime-advice" :class="{ degraded: marketState.data_quality !== 'ok' }">
        <el-tooltip placement="bottom-start" :content="marketState.reasons.join('\n')" popper-class="regime-reason-tip">
          <el-tag type="warning" effect="dark" size="small" round class="ra-portrait">{{ marketState.portrait }}</el-tag>
        </el-tooltip>
        <div class="ra-dims">
          <span v-for="d in portraitDims" :key="d.key" class="ra-dim" :title="d.tip">
            <em>{{ d.label }}</em>{{ d.value }}
          </span>
        </div>
        <span class="ra-text">{{ marketState.advice }}</span>
        <span v-if="marketState.as_of" class="ra-meta">行情截至 {{ marketState.as_of }}</span>
        <span v-if="marketState.data_quality !== 'ok'" class="ra-warn">
          <el-icon :size="13"><Warning /></el-icon>
          数据降级：{{ marketState.missing.join(' / ') }} 缺失，结论可能偏差
        </span>
        <span v-else class="ra-ok">数据完整</span>
      </div>
      <div class="regime-body">
        <MarketRegimeWheel
          :groups="wheelGroups"
          :current="currentGroupId"
          :current-label="currentPortraitLabel"
          :current-desc="currentGroupDesc"
          @pick="pickGroup"
        />
        <div class="regime-legend">
          <div
            v-for="g in strategyGroups"
            :key="g.id"
            class="regime-row"
            :class="{ current: g.id === currentGroupId }"
            @click="pickGroup(g.id)"
          >
            <span class="regime-swatch" :style="{ background: g.color }" />
            <div class="regime-info">
              <div class="regime-row-head">
                <span class="regime-name">{{ g.label || g.id }}</span>
                <el-tag v-if="g.id === currentGroupId" size="small" type="warning" effect="dark" round>当前</el-tag>
                <span class="regime-count">{{ g.members.length }} 个策略</span>
              </div>
              <div class="regime-line earn">赚：{{ g.earn }}</div>
              <div class="regime-line lose">失效：{{ g.lose }}</div>
              <div class="regime-line pick" v-if="g.visible.length">
                建议开：<b>{{ g.visible.map((s: any) => s.name).join(' / ') }}</b>
              </div>
              <div class="regime-line pick warn" v-else>本组无独立可开策略，建议全部关闭</div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 策略卡片 -->
    <el-card class="strategy-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot" />
            策略池
            <span class="panel-count">{{ displayStrategies.length }}</span>
          </div>
          <el-tag size="small" type="info" effect="plain" round v-if="matrixPortrait">
            适配「{{ matrixPortrait }}」{{ adaptedCount }} 个高亮 · 未适配半透明显示 · 修改上方矩阵维度可调整 · 点击卡片查看选股结果
          </el-tag>
          <el-tag size="small" type="info" effect="plain" round v-else>点击卡片查看选股结果</el-tag>
        </div>
      </template>

      <!-- 策略命中数排行（当存在命中数据时展示） -->
      <div v-if="strategyHitChartData.length > 0" class="strategy-hit-chart">
        <div class="hit-chart-title">策略命中排行（按命中只数）</div>
        <v-chart class="hit-chart" :option="strategyHitOption" autoresize />
      </div>

      <el-empty v-if="!loading && strategies.length === 0" description="暂无可用策略" :image-size="120" />
      <!-- 按行情画像分组：每组默认只展示「首选 + 备选」，其余同族折叠，
           避免 20+ 张卡片平铺；同族信号高度重叠，同开等于重复买同一笔 -->
      <div v-else class="regime-groups">
        <section
          v-for="g in strategyGroups"
          :id="`rg-${g.id}`"
          :key="g.id"
          class="regime-group"
          :class="{ current: g.id === currentGroupId }"
        >
          <div class="rg-head">
            <span class="rg-swatch" :style="{ background: g.color }" />
            <span class="rg-name">{{ g.label || g.id }}</span>
            <span class="rg-cond">{{ g.condition }}</span>
            <el-tag v-if="g.id === currentGroupId" size="small" type="warning" effect="dark" round>当前画像</el-tag>
            <span class="rg-role">{{ g.visible.length ? `建议开 ${g.visible.length} 个` : '建议全部关闭' }}</span>
          </div>
          <div class="strategy-grid" v-if="shownMembers(g).length">
        <div
          v-for="s in shownMembers(g)"
          :key="s.id"
          class="strategy-card"
          :class="{
            active: activeStrategy === s.id,
            loading: runningAll,
            // 非内置策略不参与策略池筛选，置为不可点并给出原因
            disabled: s.source !== 'builtin',
            // 仅当存在矩阵画像上下文（盘中预警开启）时才做适配高亮/未适配半透明；
            // 平时无画像 → 全部正常显示，避免策略池整体变灰
            dimmed: !!matrixPortrait && !isAdapted(s.id),
          }"
          :style="{ '--sc': palette[strategyIndex(s.id) % palette.length] }"
          @click="handleRun(s)"
        >
          <div class="strategy-top">
            <div class="strategy-name">
              <span class="strategy-icon">
                <el-icon><component :is="cardIcon(strategyIndex(s.id))" /></el-icon>
              </span>
              <span class="strategy-title">{{ s.name }}</span>
              <el-tag
                v-if="STRATEGY_ROLE[s.id] === 'primary'"
                size="small" type="success" effect="plain" round class="role-tag"
              >首选</el-tag>
              <el-tag
                v-else-if="STRATEGY_ROLE[s.id] === 'secondary'"
                size="small" type="info" effect="plain" round class="role-tag"
              >备选</el-tag>
            </div>
            <div class="strategy-count">
              <template v-if="hitCounts[s.id] !== undefined">
                <span class="count-num">{{ hitCounts[s.id] }}</span>
                <span class="count-unit">只</span>
              </template>
              <el-icon v-else class="spinner"><Loading /></el-icon>
            </div>
          </div>
          <div class="strategy-desc">{{ s.description }}</div>
          <div class="strategy-rules" v-if="(s.buy_rules && s.buy_rules.length) || (s.sell_rules && s.sell_rules.length)">
            <div v-if="s.buy_rules && s.buy_rules.length" class="rule-row">
              <span class="rule-flag buy">买入</span>
              <span class="rule-text">{{ s.buy_rules.join(' · ') }}</span>
            </div>
            <div v-if="s.sell_rules && s.sell_rules.length" class="rule-row">
              <span class="rule-flag sell">卖出</span>
              <span class="rule-text">{{ s.sell_rules.join(' · ') }}</span>
            </div>
          </div>
          <div class="strategy-tags">
            <el-tag v-for="t in s.tags" :key="t" size="small" effect="plain" class="strategy-tag">{{ t }}</el-tag>
          </div>
          <div class="strategy-foot">
            <div class="strategy-monitor">
              <el-switch
                :model-value="monitorOn(s.id)"
                size="small"
                :loading="monitorSaving === s.id"
                :disabled="s.source !== 'builtin'"
                data-monitor
                @change="(v: string | number | boolean) => toggleMonitor(s, v as boolean)"
                @click.stop
              />
              <span class="monitor-label" :class="{ on: monitorOn(s.id) }">监控</span>
            </div>
            <span v-if="monitorOn(s.id)" class="monitor-hint">命中自动入自选 · 触发买卖待确认</span>
            <span v-else-if="s.source !== 'builtin'" class="monitor-hint">非内置策略，仅展示规则</span>
          </div>
        </div>
          </div>
          <div v-else class="rg-empty">本组策略在当前行情不产生独立买点，已折叠</div>
          <div v-if="g.rest.length" class="rg-more" @click="toggleGroup(g.id)">
            <el-icon><component :is="expandedGroups.has(g.id) ? ArrowUp : ArrowDown" /></el-icon>
            <span>{{ expandedGroups.has(g.id) ? '收起同族策略' : `同族其他 ${g.rest.length} 个` }}</span>
            <span class="rg-more-names">{{ g.rest.map(x => x.name).join(' · ') }} —— 与上述策略信号高度重叠，建议不开启</span>
          </div>
        </section>
      </div>
    </el-card>

    <!-- 结果 -->
    <el-card v-if="result || showAllResult" class="result-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot result-dot" />
            <span class="result-title">{{ showAll ? '全部策略' : (activeStrategyName || '') }}</span>
            <span class="result-hit">命中 <b>{{ displayRows.length }}</b> 只</span>
            <span v-if="isRealtimeResult">
              <el-tag v-if="decisionWindow" size="small" type="success" effect="light" round>收盘定格</el-tag>
              <el-tag v-else size="small" type="warning" effect="light" round>盘中预警</el-tag>
            </span>
            <span v-else class="result-date" :title="stalenessHint">
              · 行情截至 {{ asOf }}
              <em v-if="resultLagDays > 0" class="result-lag">（{{ resultLagDays }} 天前）</em>
            </span>
          </div>
          <div class="header-actions">
            <el-button size="small" :type="showAll ? 'primary' : 'default'" @click="toggleShowAll" :disabled="!allStrategyRunning">
              <el-icon><Connection /></el-icon>
              全部
            </el-button>
            <el-button size="small" @click="batchAddToFavorites" :disabled="displayRows.length === 0">
              <el-icon><Star /></el-icon>
              批量加自选
            </el-button>
            <el-button v-if="!showAll && activeStrategy" size="small" @click="gotoBacktest">
              <el-icon><Histogram /></el-icon>
              回测该策略
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="displayRows" stripe size="default" style="width: 100%" class="hit-table app-table app-table--ranking">
        <el-table-column prop="code" label="代码" min-width="110">
          <template #default="{ row }">
            <router-link class="stock-code" target="_blank" rel="noopener" :to="`/stocks/${row.code}`">{{ row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130">
          <template #default="{ row }">
            <router-link class="stock-name" target="_blank" rel="noopener" :to="`/stocks/${row.code}`">{{ row.name || row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="close" label="收盘价" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <span v-if="row.close != null">{{ fmtPrice(row.close) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="change_pct" label="涨跌幅" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <el-tag v-if="row.change_pct != null" size="small" :type="row.change_pct >= 0 ? 'danger' : 'success'" effect="plain" round class="pct-tag">
              {{ fmtPctFromFraction(row.change_pct) }}
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol_ratio" label="量比" min-width="100" align="right" sortable>
          <template #default="{ row }">
            <span v-if="row.vol_ratio != null">{{ fmtNum(row.vol_ratio) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <span class="score-badge" :style="{ '--sc': scoreColor(row.score) }">{{ fmtNum(row.score, 1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作建议（买入依据 / 离场）" min-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="action-advice">
              <div class="advice-reason" :class="{ empty: !row.reason }">
                <span class="advice-dot" />
                <el-tooltip v-if="row.reason" :content="row.reason" placement="top" :show-after="160">
                  <span class="advice-text">{{ row.reason }}</span>
                </el-tooltip>
                <span v-else class="advice-text muted">已触发筛选条件</span>
              </div>
              <div v-if="row.sell_rules && row.sell_rules.length" class="advice-exit">
                <span class="exit-label">离场</span>
                <span class="exit-text">{{ row.sell_rules.join(' · ') }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="addToFavorite(row)">
              <el-icon><Star /></el-icon>
              加自选
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-else-if="!loading && !runningAll" description="点击策略卡片查看选股结果" :image-size="160" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import StrategyExplainPanel from '@/components/Strategy/StrategyExplainPanel.vue'
import MarketRegimeWheel from '@/components/Strategy/MarketRegimeWheel.vue'
import { REGIME_GROUPS, STRATEGY_ROLE, homeRegimeOf, portraitOf, portraitToGroup } from '@/utils/marketFit'
import {
  TrendCharts, Refresh, Loading, Connection, Star, Clock,
  Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard,
  Warning, ArrowDown, ArrowUp,
} from '@element-plus/icons-vue'
import { strategyApi, type StrategyMeta, type StrategyRunItem, type StrategyRunAllItem, type MarketState } from '@/api/strategy'
import { favoritesApi } from '@/api/favorites'
import { monitorApi } from '@/api/monitor'
import { vibeApi } from '@/api/vibe'
import { fmtPrice, fmtPctFromFraction, fmtNum } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

echartsUse([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

defineOptions({ name: 'StrategyScreener' })

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const currentUserId = computed(() => authStore.user?.id ?? null)

// 策略卡片配色画板（通过 --sc 变量注入，保证深浅色主题下都清晰）
const palette = [
  '#22568d', '#722ed1', '#13c2c2', '#fa8c16', '#f5222d', '#52c41a',
  '#eb2f96', '#2b6cb0', '#a0d911', '#fadb14', '#fa541c', '#36cfc9',
]

// 策略卡片图标画板（轮流使用，避免千篇一律）
const cardIcons = [TrendCharts, Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard, TrendCharts]
const cardIcon = (i: number) => cardIcons[i % cardIcons.length]

// 评分配色：越高越偏暖红，越低越偏蓝
const scoreColor = (score: number) => {
  const s = score ?? 0
  if (s >= 80) return '#f5222d'
  if (s >= 60) return '#fa8c16'
  if (s >= 40) return '#faad14'
  if (s >= 20) return '#13c2c2'
  return '#22568d'
}

const strategies = ref<StrategyMeta[]>([])
const loading = ref(false)
const runningAll = ref(false)
const hitCounts = ref<Record<string, number>>({})
const activeStrategy = ref<string | null>(null)
const activeStrategyName = ref('')
const result = ref<{ items: StrategyRunItem[]; as_of: string; strategy_id: string; strategy_name: string; total?: number } | null>(null)
const showAllResult = ref<StrategyRunAllItem[] | null>(null)
const showAll = ref(false)
const asOf = ref('')
// 标题日期：最新交易日（轻量接口预取）
const titleDate = ref('')

// 策略命中数排行（横向条，命中越多的策略靠上）
const strategyHitChartData = computed(() =>
  strategies.value
    .filter((s) => hitCounts.value[s.id] !== undefined)
    .map((s) => ({ name: s.name, value: Number(hitCounts.value[s.id]) || 0 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12)
    .reverse()
)

const strategyHitOption = computed(() => {
  const items = strategyHitChartData.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any) => {
      const p = params[0]
      if (!p) return ''
      return `${p.name}<br/>命中：${p.value} 只`
    } },
    grid: { left: 8, right: 50, top: 6, bottom: 4, containLabel: true },
    xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    yAxis: { type: 'category', inverse: true, axisLabel: { fontSize: 11 }, data: items.map(i => i.name) },
    series: [{
      type: 'bar',
      barWidth: 12,
      data: items.map((i, idx) => ({
        value: i.value,
        itemStyle: { color: palette[idx % palette.length], borderRadius: 3 },
      })),
      label: { show: true, position: 'right', fontSize: 10, formatter: (p: any) => p.value },
    }],
  }
})
const tradeDates = ref<string[]>([])
const computedAt = ref('')
// 「数据更新于」仅显示时间（HH:MM）：数据日期已由页头标题的最新交易日承载，避免出现非交易日日期
const computedTime = computed(() => computedAt.value ? String(computedAt.value).slice(11, 16) : '')
const allStrategyRunning = ref(false)

// ── 行情时效 ────────────────────────────────────────────────
// 结果日期来自后端 _resolve_as_of：未指定日期时取本地日线（stock_daily_quotes）
// 的最新交易日。今日日线是收盘后入库的，白天打开页面必然拿到「上一个交易日」，
// 这里把这件事讲清楚，而不是只给一个裸日期。
const todayStr = computed(() => {
  const n = new Date()
  const p = (x: number) => String(x).padStart(2, '0')
  return `${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())}`
})
const latestTradeDate = computed(() => tradeDates.value[0] || titleDate.value || asOf.value)
const daysBetween = (from: string, to: string) => {
  const a = new Date(`${from}T00:00:00`).getTime()
  const b = new Date(`${to}T00:00:00`).getTime()
  if (Number.isNaN(a) || Number.isNaN(b)) return 0
  return Math.max(0, Math.round((b - a) / 86400000))
}
// 本地最新交易日距今日的天数（周末/节假日为 1~3 天属正常）
const latestLagDays = computed(() => (latestTradeDate.value ? daysBetween(latestTradeDate.value, todayStr.value) : 0))
// 当前结果日期距今日的天数（用于卡片上标注「N 天前」）
const resultLagDays = computed(() => (asOf.value ? daysBetween(asOf.value, todayStr.value) : 0))
const stalenessHint = computed(() => {
  if (realtimeScan.value) return ''
  const latest = latestTradeDate.value
  if (!latest) return ''
  if (latestLagDays.value <= 0) return `行情已更新至今日 ${latest}`
  return `本地行情最新交易日为 ${latest}，今日 ${todayStr.value} 的日线尚未入库（收盘后同步）；卡片与命中数均为 ${latest} 收盘数据`
})

// 画像四维：把后端 dims 摊开给用户看，避免「只给一个画像名，不知道为什么」
const portraitDims = computed(() => {
  const d = marketState.value?.dims || {}
  return [
    { key: 'trend', label: '中期', value: d.trend || '未知', tip: '沪深300 相对年线(MA250)，偏离 ±5% 判牛/熊，其余为震荡' },
    { key: 'vol', label: '波动', value: d.vol || '未知', tip: '个股日均振幅 + 涨跌家数摆动，综合定高/正常/低波动' },
    { key: 'breadth', label: '宽度', value: d.breadth || '中性', tip: '近 5 个交易日全市场上涨家数占比（≥55% 普涨 / ≤45% 分化）' },
    { key: 'sentiment', label: '情绪', value: d.sentiment || '未知', tip: '融资余额变化 + 换手率相对 20 日均值；数据缺失显示「未知」' },
  ]
})

// ── 大盘状态（唯一事实源 /api/strategy/market-state）──────────────────
// 后端合并「中期年线 × 短期宽度 × 波动 × 情绪」，前端不再用 retail 口径自行判断，
// 避免同一时刻页头说熊市、筛选取用近 5 日宽度说偏强。
const marketState = ref<MarketState | null>(null)
const regimeUpdatedAt = ref('')
const loadMarketRegime = async () => {
  try {
    const res: any = await strategyApi.marketState()
    const data: MarketState | null = res?.data ?? res ?? null
    if (!data?.portrait) throw new Error('empty market state')
    marketState.value = data
    regimeUpdatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    console.warn('加载大盘状态失败', e)
    marketState.value = null
  }
}

// 盘中预警开启时：矩阵展示实时大盘快照（值 + 检测时刻），让刷新肉眼可见
const liveMetrics = computed(() => {
  if (!realtimeScan.value || !marketState.value) return null
  const m = marketState.value.metrics || {}
  const breadth = m.breadth_ratio ?? m.up_ratio
  return {
    price: m.index_price != null ? Number(m.index_price) : null,
    breadthPct: breadth != null ? Math.round(Number(breadth) * 1000) / 10 : null,
    updatedAt: regimeUpdatedAt.value,
  }
})

// 矩阵初始维度：统一状态的四维中文标签（缺失项不传，矩阵保留默认值）
const initialMatrixDims = computed<Record<string, string> | undefined>(() => {
  const d = marketState.value?.dims
  if (!d) return undefined
  const out: Record<string, string> = {}
  for (const k of ['trend', 'vol', 'breadth', 'sentiment'] as const) {
    const v = d[k]
    if (v) out[k] = String(v)
  }
  return Object.keys(out).length ? out : undefined
})

// 矩阵画像 → 策略池适配标记（画像由矩阵组件广播）
const matrixPortrait = ref('')
const syncPortrait = (p: string) => { matrixPortrait.value = p }

// 策略池展示全部策略：适配当前画像的策略亮色显示，未适配的半透明（可正常点击运行）
const displayStrategies = computed(() => strategies.value)
const adaptedSet = computed(() => {
  const set = new Set<string>()
  if (!matrixPortrait.value) return set
  for (const s of strategies.value) {
    if ((s.market_regimes || []).includes(matrixPortrait.value) || (s.market_regimes || []).includes('全面适用')) {
      set.add(s.id)
    }
  }
  return set
})
const adaptedCount = computed(() => adaptedSet.value.size)
const isAdapted = (id: string) => adaptedSet.value.has(id)

// ── 行情画像分组（每组默认只展示首选/备选，其余同族折叠） ──────────────
const expandedGroups = ref<Set<string>>(new Set())
const toggleGroup = (id: string) => {
  const next = new Set(expandedGroups.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedGroups.value = next
}

// 策略在原始列表中的下标（用于卡片配色/图标，保证同一策略始终同色）
const strategyIndexMap = computed(() => {
  const m = new Map<string, number>()
  strategies.value.forEach((s, i) => m.set(s.id, i))
  return m
})
const strategyIndex = (id: string) => strategyIndexMap.value.get(id) ?? 0

// 当前画像：优先后端统一状态（含「熊市反弹」），其次矩阵广播 / 四维推导
const currentGroupId = computed(() => {
  if (matrixPortrait.value) return portraitToGroup(matrixPortrait.value)
  const p = marketState.value?.portrait
  if (p) return portraitToGroup(p)
  const d = initialMatrixDims.value
  if (!d) return ''
  return portraitOf(d)
})

const strategyGroups = computed(() => {
  const buckets = new Map<string, StrategyMeta[]>()
  REGIME_GROUPS.forEach((g) => buckets.set(g.id, []))
  for (const s of strategies.value) {
    const home = homeRegimeOf(s.id, s.market_regimes)
    buckets.get(home)?.push(s)
  }
  const rank: Record<string, number> = { primary: 0, secondary: 1 }
  return REGIME_GROUPS
    .map((meta) => {
      const members = buckets.get(meta.id) || []
      const visible = members
        .filter((m) => !!STRATEGY_ROLE[m.id])
        .sort((a, b) => rank[STRATEGY_ROLE[a.id]] - rank[STRATEGY_ROLE[b.id]])
      const rest = members.filter((m) => !STRATEGY_ROLE[m.id])
      return { ...meta, members, visible, rest }
    })
    .filter((g) => g.members.length > 0)
})

// 展开后才显示同族其他策略
const shownMembers = (g: { id: string; visible: StrategyMeta[]; rest: StrategyMeta[] }) =>
  expandedGroups.value.has(g.id) ? [...g.visible, ...g.rest] : g.visible

const wheelGroups = computed(() =>
  strategyGroups.value.map((g) => ({ id: g.id, label: g.label || g.id, color: g.color, count: g.members.length }))
)
const currentGroupDesc = computed(
  () => REGIME_GROUPS.find((g) => g.id === currentGroupId.value)?.earn || ''
)
// 圆心展示真实画像名（不含分组合并后的名字）
const currentPortraitLabel = computed(() => matrixPortrait.value || marketState.value?.portrait || '')

// 轮盘/图例点击 → 滚动到对应分组
const pickGroup = (id: string) => {
  const el = document.getElementById(`rg-${id}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ── 盘中实时触发（仅自选+持仓池） ─────────────────────────
const realtimeScan = ref(false)        // 是否开启盘中预警（实时扫描）开关
const isRealtimeResult = ref(false)    // 最近一次结果是否为实时合成面板
const realtimeNote = ref('')           // 实时扫描说明/失效提示
const decisionWindow = ref(false)      // 是否处于 15:00-15:30 收盘定格可成交窗口

// 收盘定格窗口（15:00-15:30 可成交）只对「今日/实时」有意义：
// 后端 decision_window 是当前时刻的全局判定，与查询日期无关；历史交易日查询时强制不显示该窗口
const isTodayAsOf = (d?: string | null) => {
  if (!d) return true
  const now = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d === `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`
}

const toggleRealtime = async (on: boolean) => {
  realtimeScan.value = on
  isRealtimeResult.value = false
  decisionWindow.value = false
  if (on) {
    if (!currentUserId.value) {
      ElMessage.warning('未获取到登录用户，无法扫描自选+持仓')
      realtimeScan.value = false
      return
    }
    ElMessage.info('盘中预警开启：基于自选+持仓，历史日K + 当日实时K合成（盘中为暂定信号，15:00 收盘定格确认）')
    // 大盘实际检测：开启即拉取，之后 60s 独立轮询（不受 runAll 阻塞）
    await Promise.allSettled([runAll(true), loadMarketRegime()])
    startRegimeLivePoll()
  } else {
    // 关闭实时扫描：重置交易日，避免残留“今天”导致 EOD 面板取到无数据的当日而一直无结果
    asOf.value = ''
    isRealtimeResult.value = false
    result.value = null
    showAllResult.value = null
    activeStrategy.value = null
    // 清空矩阵画像：矩阵随预警关闭而卸载，画像残留会让策略池继续按旧画像半透明高亮
    matrixPortrait.value = ''
    stopRegimeLivePoll()
    await runAll()
  }
}

// ── 盘中预警：大盘情况独立按实际刷新 ─────────────────────────────
// 与 runAll 的 5 分钟周期解耦（runAll 可能长时间占用），60s 轮询一次检测，
// 与后端 market 分类交易时段 TTL(60s) 对齐，矩阵自动跟随最新检测并刷新策略池适配。
let regimeTimer: number | undefined
const startRegimeLivePoll = () => {
  stopRegimeLivePoll()
  regimeTimer = window.setInterval(() => {
    if (realtimeScan.value) loadMarketRegime()
  }, 60_000)
}
const stopRegimeLivePoll = () => {
  if (regimeTimer) {
    window.clearInterval(regimeTimer)
    regimeTimer = undefined
  }
}

// ── 常用策略监控开关 ────────────────────────────────────
const monitorStatus = ref<Record<string, boolean>>({})
const monitorSaving = ref<string | null>(null)

const monitorOn = (id: string) => !!monitorStatus.value[id]

const loadMonitorStatus = async () => {
  try {
    const res = await monitorApi.strategyMonitorStatus()
    const items = (res as any)?.data?.items ?? []
    const map: Record<string, boolean> = {}
    for (const it of items) map[it.strategy_id] = !!it.enabled
    monitorStatus.value = map
  } catch (e) {
    console.warn('加载策略监控状态失败', e)
  }
}

const toggleMonitor = async (s: StrategyMeta, on: boolean) => {
  monitorSaving.value = s.id
  try {
    await monitorApi.toggleStrategyMonitor(s.id, on, s.name)
    monitorStatus.value = { ...monitorStatus.value, [s.id]: on }
    ElMessage.success(on ? `已开启「${s.name}」监控` : `已关闭「${s.name}」监控`)
  } catch (e: any) {
    ElMessage.error('切换监控失败：' + (e?.message || '未知错误'))
  } finally {
    monitorSaving.value = null
  }
}

const displayRows = computed<StrategyRunItem[]>(() => {
  if (showAll.value && showAllResult.value) {
    const seen = new Set<string>()
    const merged: StrategyRunItem[] = []
    for (const s of showAllResult.value) {
      for (const row of s.top) {
        if (!seen.has(row.code)) {
          seen.add(row.code)
          merged.push(row)
        }
      }
    }
    return merged
  }
  return result.value?.items ?? []
})

const loadStrategies = async () => {
  loading.value = true
  try {
    // 并行加载策略列表与交易日下拉
    const [listRes, datesRes] = await Promise.allSettled([
      strategyApi.list(),
      strategyApi.tradeDates(30),
    ])
    if (listRes.status === 'fulfilled') {
      const list = (listRes.value as any)?.data ?? listRes.value
      strategies.value = Array.isArray(list) ? list : []
    } else {
      ElMessage.error('加载策略列表失败')
    }
    if (datesRes.status === 'fulfilled') {
      const dres = datesRes.value as any
      const dates = dres?.data?.dates ?? []
      tradeDates.value = Array.isArray(dates) ? dates : []
      // 标题日期兜底：trade-date 轻量接口不可用时，取交易日下拉的最新一个
      if (!titleDate.value && tradeDates.value.length > 0) {
        titleDate.value = tradeDates.value[0]
      }
    }
    // 首次进入自动加载全部策略结果（后端缓存命中时秒回，否则后台计算）
    if (strategies.value.length > 0) {
      await runAll()
    }
  } catch (e) {
    ElMessage.error('加载策略失败')
  } finally {
    loading.value = false
  }
}

// 运行全部：已运行时长与停止等待（后端任务无法中断，停止仅放弃本次等待）
const runElapsed = ref(0)
let runTimer: number | undefined
let stopRequested = false
const fmtElapsed = (sec: number) => sec < 60 ? `${sec} 秒` : `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
const stopWaiting = () => {
  stopRequested = true
  runningAll.value = false
  if (runTimer) { window.clearInterval(runTimer); runTimer = undefined }
  ElMessage.info('已停止等待，后台任务仍会继续，可稍后刷新查看结果')
}

const runAll = async (refresh = false) => {
  if (runningAll.value) return
  runningAll.value = true
  stopRequested = false
  runElapsed.value = 0
  if (runTimer) window.clearInterval(runTimer)
  runTimer = window.setInterval(() => { runElapsed.value += 1 }, 1000)
  try {
    const res = await strategyApi.runAll({
      as_of: asOf.value || null, limit: 30, refresh,
      realtime: realtimeScan.value || undefined,
      user_id: (realtimeScan.value ? currentUserId.value : null),
    })
    const task = (res as any)?.data ?? res
    if (!task?.task_id) throw new Error('提交筛选任务失败')
    // 后端缓存命中时任务秒完成（同交易日幂等），否则后台计算后轮询取回
    const done = await strategyApi.waitTask(task.task_id, {
      timeoutMs: 600000,
      shouldStop: () => stopRequested,
    })
    if (stopRequested) return
    const data = done.result
    isRealtimeResult.value = !!data?.realtime
    // 收盘定格窗口仅对「今日/实时」生效：历史交易日查询一律不显示
    decisionWindow.value = !!data?.decision_window && isTodayAsOf(data?.as_of || asOf.value)
    if (isRealtimeResult.value) {
      // 实时结果以当日为准，交易日下拉与 computed_at 不适用
      asOf.value = data.as_of || asOf.value
    } else {
      if (data?.as_of) asOf.value = data.as_of
      if (data?.computed_at) computedAt.value = data.computed_at
    }
    const counts: Record<string, number> = {}
    for (const s of data?.strategies ?? []) {
      counts[s.id] = s.count
    }
    hitCounts.value = counts
    showAllResult.value = data?.strategies ?? null
    allStrategyRunning.value = true
    const strategiesData = data?.strategies ?? []
    // 默认展示第一个策略的完整结果（行数与命中数一致），其余策略点击卡片切换
    if (!activeStrategy.value || !showAll.value) {
      const first = strategiesData[0]
      if (first) {
        activeStrategy.value = first.id
        activeStrategyName.value = first.name
        showAll.value = false
        result.value = {
          strategy_id: first.id,
          strategy_name: first.name,
          as_of: data.as_of,
          total: first.count,
          items: first.top ?? [],
        }
      }
    } else {
      const cur = strategiesData.find((x: any) => x.id === activeStrategy.value)
      if (cur) {
        result.value = {
          strategy_id: cur.id,
          strategy_name: cur.name,
          as_of: data.as_of,
          total: cur.count,
          items: cur.top ?? [],
        }
      }
    }
  } catch (e: any) {
    if (e?.message !== 'TASK_WAIT_CANCELLED') ElMessage.error('运行全部策略失败')
  } finally {
    if (runTimer) { window.clearInterval(runTimer); runTimer = undefined }
    runningAll.value = false
  }
}

const runSingle = async (id: string) => {
  try {
    const res = await strategyApi.run({
      strategy_id: id, as_of: asOf.value || null, limit: 100,
      realtime: realtimeScan.value || undefined,
      user_id: (realtimeScan.value ? currentUserId.value : null),
    })
    const task = (res as any)?.data ?? res
    if (!task?.task_id) throw new Error('提交筛选任务失败')
    const done = await strategyApi.waitTask(task.task_id, { timeoutMs: 600000 })
    const data = done.result
    isRealtimeResult.value = !!data?.realtime
    // 收盘定格窗口仅对「今日/实时」生效：历史交易日查询一律不显示
    decisionWindow.value = !!data?.decision_window && isTodayAsOf(data?.as_of || asOf.value)
    if (data?.as_of) asOf.value = data.as_of
    result.value = data
    if (data?.strategy_id) {
      hitCounts.value = { ...hitCounts.value, [data.strategy_id]: data.total ?? 0 }
    }
  } catch (e) {
    ElMessage.error('运行策略失败')
  }
}

const handleRun = (s: StrategyMeta) => {
  // 非内置策略（零售扫描 / 对话模板）由独立通道执行，不参与本策略池筛选，
  // 避免对它调用 run 接口产生「全市场全命中」的误导结果。
  if (s.source !== 'builtin') {
    ElMessage.info(
      s.source === 'retail'
        ? `「${s.name}」由零售扫描器独立执行，请在其专属页面查看结果`
        : `「${s.name}」由对话引擎 / 辅助信号执行，不参与策略池筛选`
    )
    return
  }
  activeStrategy.value = s.id
  activeStrategyName.value = s.name
  showAll.value = false
  // 立即用后端缓存/已加载的 run-all 结果展示，无需等待慢接口
  const cachedStrategy = showAllResult.value?.find((x) => x.id === s.id)
  if (cachedStrategy) {
    result.value = {
      strategy_id: s.id,
      strategy_name: cachedStrategy.name,
      as_of: asOf.value,
      total: cachedStrategy.count,
      items: cachedStrategy.top ?? [],
    }
  }
  // 后台刷新完整明细（limit=100），完成后更新表格
  runSingle(s.id)
}

// 跳到回测页并预选当前策略
const gotoBacktest = () => {
  if (!activeStrategy.value) return
  router.push({ path: '/screening/backtest', query: { strategy: activeStrategy.value } })
}

const onAsOfChange = () => {
  // 切换交易日：清空当前明细并重新加载该交易日结果（后端缓存命中则秒回）
  result.value = null
  showAllResult.value = null
  activeStrategy.value = null
  decisionWindow.value = false
  runAll()
}

const toggleShowAll = () => {
  showAll.value = !showAll.value
  if (showAll.value && !showAllResult.value) {
    runAll()
  }
}

const addToFavorite = async (row: StrategyRunItem) => {
  try {
    const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
    ElMessage.success(`已加入自选：${row.name || row.code}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '加自选失败')
  }
}

const batchAddToFavorites = async () => {
  const rows = displayRows.value
  if (!rows.length) return
  let added = 0
  for (const row of rows) {
    try {
      const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
      if ((res as any)?.success !== false) added++
    } catch { /* 忽略单只失败 */ }
  }
  ElMessage.success(`已添加 ${added} 只到自选`)
}

onMounted(() => {
  // 标题日期：最新交易日（轻量接口预取，首屏即正确）
  vibeApi.getLatestTradeDate().then((d) => { if (d) titleDate.value = d })
  // 支持从策略回测结果页带 ?strategy=xxx 直接预选并运行该策略
  loadStrategies().then(() => {
    const sid = String(route.query.strategy || '')
    if (sid && strategies.value.some(s => s.id === sid)) {
      activeStrategy.value = sid
      activeStrategyName.value = strategies.value.find(s => s.id === sid)?.name || ''
      runSingle(sid)
    }
  })
  loadMonitorStatus()
  loadMarketRegime()
  // 盘中预警开启时，交易时段内每 5 分钟自动刷新一次选股结果（个人分析用，不需要秒级；15:00 后自动定格）。
  // 大盘情况的实时刷新由独立的 60s regimeLivePoll 负责（见 startRegimeLivePoll），不在此重复。
  realtimeTimer = window.setInterval(() => {
    if (realtimeScan.value && !runningAll.value) {
      runAll(true)
    }
  }, 300_000)
})

onBeforeUnmount(() => {
  if (realtimeTimer) window.clearInterval(realtimeTimer)
  if (runTimer) window.clearInterval(runTimer)
  stopRegimeLivePoll()
})

let realtimeTimer: number | undefined
</script>

<style lang="scss" scoped>
.strategy-screener {
  padding: 20px 24px 32px;
  max-width: 1680px;
  margin: 0 auto;

  /* ===== 顶部横幅（由全局 .page-hero 提供，此处仅保留选择器宽度） ===== */
  .date-select {
    width: 160px;
  }

  /* ===== 行情时效提示（页头）===== */
  .page-hero-stale {
    display: flex;
    align-items: center;
    gap: 5px;
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--el-text-color-secondary);

    &.warn {
      color: var(--el-color-warning-dark-2);
    }
  }

  /* ===== 结果卡片：行情截至日期 ===== */
  .result-date {
    color: var(--el-text-color-secondary);

    .result-lag {
      font-style: normal;
      color: var(--el-color-warning-dark-2);
    }
  }

  .realtime-switch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px;
    .rt-label {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }

  /* ===== 运行全部进度条 ===== */
  .run-progress {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 16px;
    padding: 10px 16px;
    border-radius: 12px;
    background: var(--el-color-primary-light-9);
    border: 1px solid var(--el-color-primary-light-7);
  }
  .rp-spin {
    color: var(--el-color-primary);
    animation: rp-rotate 1.2s linear infinite;
  }
  @keyframes rp-rotate {
    to { transform: rotate(360deg); }
  }
  .rp-text {
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }
  .rp-hint {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  /* ===== 收盘定格窗口横幅（15:00-15:30 可成交决策黄金期） ===== */
  .close-window-banner {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 20px;
    margin-bottom: 16px;
    border-radius: 14px;
    border: 1px solid rgba(250, 173, 20, 0.45);
    background:
      radial-gradient(600px 120px at 12% 0%, rgba(250, 173, 20, 0.18), transparent 60%),
      linear-gradient(120deg, color-mix(in srgb, #faad14 14%, transparent), var(--el-bg-color) 55%);
    box-shadow: 0 2px 14px rgba(250, 173, 20, 0.12);

    .cw-orbit {
      position: relative;
      display: grid;
      place-items: center;
      width: 38px;
      height: 38px;
      flex: none;
      border-radius: 50%;
      color: #b8860b;
      background: rgba(250, 173, 20, 0.16);
      border: 1px dashed rgba(250, 173, 20, 0.6);

      .cw-pulse {
        position: absolute;
        inset: 6px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(250, 173, 20, 0.35), transparent 70%);
        animation: cwPulse 1.8s ease-in-out infinite;
      }
    }

    .cw-body {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;

      .cw-title {
        font-size: 15px;
        font-weight: 700;
        color: #8a6d1a;
        letter-spacing: 0.2px;
      }

      .cw-sub {
        font-size: 12.5px;
        color: var(--el-text-color-secondary);
        line-height: 1.5;
      }
    }

    .cw-side {
      flex: none;
      .cw-chip {
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        color: #fff;
        background: linear-gradient(135deg, #f5b93c, #b8860b);
        box-shadow: 0 2px 8px rgba(184, 134, 11, 0.35);
      }
    }
  }

  @keyframes cwPulse {
    0%, 100% { transform: scale(0.9); opacity: 0.45; }
    50% { transform: scale(1.15); opacity: 1; }
  }

  /* ===== 盘中预警条（暂定信号提示） ===== */
  .preview-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    margin-bottom: 16px;
    border-radius: 10px;
    font-size: 12.5px;
    color: var(--el-color-warning);
    background: color-mix(in srgb, var(--el-color-warning) 10%, var(--el-bg-color));
    border: 1px solid color-mix(in srgb, var(--el-color-warning) 30%, transparent);
  }

  /* ===== 大盘行情上下文条 ===== */


  /* ===== 卡片通用 ===== */
  .regime-panel,
  .strategy-panel,
  .result-panel {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--el-border-color-lighter);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);

    :deep(.el-card__header) {
      padding: 14px 22px;
      border-bottom: 1px solid var(--el-border-color-lighter);
      background: var(--el-fill-color-lighter);
    }

    :deep(.el-card__body) {
      padding: 20px 22px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;

      .card-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);

        .panel-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--el-color-primary);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
        }

        .result-dot {
          background: var(--el-color-success);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent);
        }

        .panel-count {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 22px;
          height: 20px;
          padding: 0 7px;
          border-radius: 20px;
          font-size: 12px;
          color: #fff;
          background: var(--el-color-primary);
        }

        .result-hit {
          font-weight: 400;
          color: var(--el-text-color-regular);
          b {
            color: var(--el-color-danger);
            font-size: 16px;
            margin: 0 2px;
          }
        }

        .text-muted { font-weight: 400; }
      }
    }
  }

  /* ===== 行情画像轮盘 ===== */
  .regime-panel {
    margin-bottom: 22px;

    .header-hint {
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }

    .regime-body {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      gap: 24px;
      align-items: start;

      @media (max-width: 900px) {
        grid-template-columns: 1fr;
      }
    }

    /* 当前大盘状态条：画像 + 建议 + 数据质量 */
    .regime-advice {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      padding: 9px 12px;
      border-radius: 10px;
      background: var(--el-fill-color-lighter);
      border-left: 3px solid var(--el-color-warning);
      font-size: 13px;

      &.degraded {
        border-left-color: var(--el-color-danger);
      }

      .ra-portrait {
        cursor: help;
      }

      .ra-text {
        color: var(--el-text-color-primary);
      }

      .ra-warn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        margin-left: auto;
        color: var(--el-color-danger);
        font-size: 12px;
      }

      .ra-dims {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 6px;
      }

      .ra-dim {
        padding: 1px 8px;
        border-radius: 999px;
        background: var(--el-fill-color);
        color: var(--el-text-color-regular);
        font-size: 12px;
        cursor: help;
        white-space: nowrap;

        em {
          margin-right: 3px;
          font-style: normal;
          color: var(--el-text-color-secondary);
        }
      }

      .ra-meta {
        color: var(--el-text-color-secondary);
        font-size: 12px;
      }

      .ra-ok {
        margin-left: auto;
        color: var(--el-text-color-secondary);
        font-size: 12px;
      }
    }

    .regime-legend {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 8px;
    }

    .regime-row {
      display: flex;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid transparent;
      cursor: pointer;
      transition: background 0.2s ease, border-color 0.2s ease;

      &:hover {
        background: var(--el-fill-color-light);
        border-color: var(--el-border-color-lighter);
      }

      &.current {
        background: color-mix(in srgb, var(--el-color-warning) 8%, var(--el-bg-color));
        border-color: color-mix(in srgb, var(--el-color-warning) 35%, transparent);
      }
    }

    .regime-swatch {
      width: 4px;
      border-radius: 2px;
      flex-shrink: 0;
    }

    .regime-info {
      min-width: 0;
    }

    .regime-row-head {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
    }

    .regime-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .regime-count {
      margin-left: auto;
      font-size: 11px;
      color: var(--el-text-color-secondary);
    }

    .regime-line {
      font-size: 12px;
      line-height: 1.6;
      color: var(--el-text-color-regular);

      &.pick b {
        color: var(--el-color-primary);
      }

      &.warn {
        color: var(--el-color-warning);
      }
    }
  }

  /* ===== 策略卡片 ===== */
  .strategy-panel {
    margin-bottom: 22px;

    .strategy-hit-chart {
      margin-bottom: 16px;
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 12px;
      background: var(--el-bg-color);
      padding: 12px 14px;

      .hit-chart-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        margin-bottom: 8px;
      }

      .hit-chart {
        height: 220px;
      }
    }

    .strategy-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
      gap: 16px;
    }

    /* ===== 画像分组：组标题 + 组内卡片 ===== */
    .regime-groups {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .regime-group {
      border-top: 1px solid var(--el-border-color-lighter);
      padding-top: 16px;
      scroll-margin-top: 84px;

      &:first-child {
        border-top: none;
        padding-top: 0;
      }
    }

    .rg-head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }

    .rg-swatch {
      width: 4px;
      height: 16px;
      border-radius: 2px;
      flex-shrink: 0;
    }

    .rg-name {
      font-size: 14px;
      font-weight: 700;
      color: var(--el-text-color-primary);
    }

    .rg-cond {
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }

    .rg-role {
      margin-left: auto;
      font-size: 12px;
      font-weight: 600;
      color: var(--el-color-primary);
    }

    .rg-empty {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      padding: 4px 0 2px;
    }

    .rg-more {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 10px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
      cursor: pointer;
      transition: color 0.2s ease;

      &:hover {
        color: var(--el-color-primary);
      }

      .rg-more-names {
        color: var(--el-text-color-placeholder);
      }
    }

    .role-tag {
      margin-left: 4px;
    }

    .strategy-card {
      position: relative;
      padding: 18px;
      background: var(--el-fill-color-light);
      border-radius: 14px;
      cursor: pointer;
      border: 2px solid transparent;
      transition: all 0.25s ease;
      overflow: hidden;

      &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--sc), transparent);
        opacity: 0;
        transition: opacity 0.25s ease;
      }

      &:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        border-color: color-mix(in srgb, var(--sc) 45%, transparent);
        background: var(--el-bg-color);

        &::before { opacity: 1; }
      }

      &.active {
        border-color: var(--sc);
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--sc) 8%, transparent) 0%, transparent 60%),
          var(--el-bg-color);

        &::before { opacity: 1; }
      }

      /* 非内置策略：不可运行，仅展示规则 */
      &.disabled {
        cursor: not-allowed;
        opacity: 0.62;

        &:hover {
          transform: none;
          box-shadow: none;
          border-color: transparent;
          background: var(--el-fill-color-light);
          &::before { opacity: 0; }
        }
      }

      /* 未适配当前大盘画像：半透明显示，与适配策略区分（仍可点击运行） */
      &.dimmed {
        opacity: 0.42;
        filter: grayscale(0.55) saturate(0.6);

        .strategy-icon { opacity: 0.7; }

        &:hover {
          opacity: 0.8;
          filter: grayscale(0.15) saturate(0.9);
        }
      }





      &.loading {
        opacity: 0.7;
        pointer-events: none;
      }

      .strategy-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;

        .strategy-name {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;

          .strategy-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 38px;
            flex-shrink: 0;
            border-radius: 10px;
            font-size: 19px;
            color: var(--sc);
            background: color-mix(in srgb, var(--sc) 12%, transparent);
          }

          .strategy-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--el-text-color-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }

        .strategy-count {
          display: flex;
          align-items: baseline;
          gap: 2px;
          flex-shrink: 0;

          .count-num {
            font-size: 22px;
            font-weight: 800;
            line-height: 1;
            color: var(--sc);
          }

          .count-unit {
            font-size: 12px;
            color: var(--el-text-color-secondary);
          }
        }

        .spinner {
          color: var(--sc);
        }
      }

      .strategy-desc {
        font-size: 13px;
        color: var(--el-text-color-regular);
        margin-bottom: 10px;
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        min-height: 39px;
      }

      /* ===== 买卖规则：明确告诉用户何时买 / 何时卖 ===== */
      .strategy-rules {
        margin-bottom: 10px;
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding: 9px 10px;
        border-radius: 8px;
        background: color-mix(in srgb, var(--el-fill-color) 55%, transparent);
        border-left: 2px solid var(--sc);

        .rule-row {
          display: flex;
          align-items: baseline;
          gap: 8px;
          min-width: 0;
        }

        .rule-flag {
          flex: none;
          font-size: 11px;
          font-weight: 700;
          padding: 1px 7px;
          border-radius: 5px;
          line-height: 1.7;

          &.buy {
            color: #fff;
            background: var(--el-color-danger);
          }
          &.sell {
            color: #fff;
            background: var(--el-color-success);
          }
        }

        .rule-text {
          font-size: 12px;
          color: var(--el-text-color-secondary);
          line-height: 1.45;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
      }

      .strategy-tags {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;

        .strategy-tag {
          --el-tag-bg-color: color-mix(in srgb, var(--sc) 9%, transparent);
          --el-tag-border-color: color-mix(in srgb, var(--sc) 25%, transparent);
          --el-tag-text-color: var(--sc);
        }
      }

      /* ===== 行情适配：视觉化推荐标记 ===== */


      @keyframes recommend-glow {
        0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--el-color-success) 30%, transparent); }
        50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--el-color-success) 10%, transparent); }
      }

      .strategy-foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-top: 12px;
        padding-top: 10px;
        border-top: 1px dashed var(--el-border-color-lighter);

        .strategy-monitor {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 8px;
          border-radius: 16px;
          transition: background .2s, box-shadow .2s;
          // 监控开启：高亮，一眼找到已开启监控的策略
          &:has(.el-switch.is-checked) {
            background: color-mix(in srgb, var(--sc) 14%, transparent);
            box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--sc) 45%, transparent);
          }

          .monitor-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--el-text-color-secondary);
            &.on { color: var(--sc); font-weight: 700; }
          }
        }

        .monitor-hint {
          font-size: 11px;
          color: var(--el-text-color-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }
  }

  /* ===== 结果表格 ===== */
  .result-panel {
    .pct-tag {
      font-weight: 600;
      min-width: 64px;
      justify-content: center;
    }

    .score-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 36px;
      height: 22px;
      padding: 0 8px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: var(--sc);
    }

    /* ===== 操作建议列：买入依据 + 离场规则 ===== */
    .action-advice {
      display: flex;
      flex-direction: column;
      gap: 5px;
      padding: 2px 0;

      .advice-reason {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;

        .advice-dot {
          flex: none;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--el-color-primary);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
        }

        .advice-text {
          font-size: 12.5px;
          color: var(--el-text-color-primary);
          line-height: 1.4;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 320px;

          &.muted {
            color: var(--el-text-color-secondary);
          }
        }
      }

      .advice-exit {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;

        .exit-label {
          flex: none;
          font-size: 11px;
          font-weight: 600;
          color: var(--el-color-success);
        }

        .exit-text {
          font-size: 12px;
          color: var(--el-text-color-secondary);
          line-height: 1.4;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }

    .text-muted { color: var(--el-text-color-secondary); }
  }
}

@media (max-width: 900px) {
  .strategy-screener {
    .strategy-grid {
      grid-template-columns: 1fr;
    }
  }
}

@media (max-width: 768px) {
  .strategy-screener {
    .strategy-grid {
      grid-template-columns: 1fr;
    }
  }
}

html.dark {
  .strategy-screener {
    .strategy-panel,
    .result-panel {
      :deep(.el-card__header) {
        background: var(--el-fill-color-dark);
      }
    }

    .strategy-card {
      background: var(--el-fill-color-darker);
      &:hover {
        background: var(--el-fill-color-dark);
      }
      &.active {
        background: linear-gradient(135deg, color-mix(in srgb, var(--sc) 14%, transparent) 0%, transparent 60%),
          var(--el-fill-color-dark);
      }

    }
  }
}
</style>