<template>
  <div class="dashboard app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Odometer /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">速览</h2>
          <p class="page-hero-sub">数据健康 · 模拟账户 · 自选行情 · 监控动态</p>
        </div>
      </div>
    </div>

    <!-- 今日待办：交易页「买 / 盯 / 卖」的提炼，点击进入今日待办处理 -->
    <div class="todo-bar" v-loading="todayLoading">
      <div class="todo-head">
        <span class="todo-title">今日待办</span>
        <span class="todo-sub" v-if="todayData">
          {{ todayData.trade_date }} · {{ todayData.session.is_intraday ? '盘中实时价' : '收盘快照' }}
        </span>
        <span class="todo-sub" v-else>加载中…</span>
      </div>

      <template v-if="todayData">
        <button
          class="todo-env"
          :class="`gate-${todayData.environment.gate}`"
          :title="todayData.environment.position.desc"
          @click="router.push('/paper')"
        >
          <span class="te-verdict">{{ todayData.environment.verdict }}</span>
          <span class="te-pos">{{ todayData.environment.headline }}</span>
        </button>

        <div class="todo-cols">
          <button
            v-for="c in todayCols"
            :key="c.key"
            class="todo-col"
            :class="`col-${c.key}`"
            @click="router.push('/paper')"
          >
            <div class="tc-hd">
              <span class="tc-badge">{{ c.badge }}</span>
              <b class="tc-num">{{ c.count }}</b>
              <span class="tc-text">{{ c.text }}</span>
            </div>
            <ul class="tc-list">
              <li v-for="it in c.items" :key="it.code">
                <span class="tc-name">{{ it.name }}</span>
                <span class="tc-code">{{ it.code }}</span>
                <span class="tc-meta">{{ it.meta }}</span>
              </li>
              <li v-if="!c.items.length" class="tc-empty">{{ c.empty }}</li>
            </ul>
          </button>
        </div>

        <el-button text size="small" class="todo-more" @click="router.push('/paper')">
          查看全部<el-icon><ArrowRight /></el-icon>
        </el-button>
      </template>
    </div>

    <!-- 监控中心（简要触发记录，查看详情跳转监控中心） -->
    <MonitorSummary style="margin-bottom: 24px;" />

    <!-- 顶部核心监控：数据健康 + 模拟账户 + 自选股行情 -->
    <el-row :gutter="24" class="monitor-top">
      <el-col :xs="24" :md="8">
        <DataHealthCard @open-sync="openSyncConfirm" />
      </el-col>

      <el-col :xs="24" :md="8">
        <!-- 持仓追踪（精简） -->
        <el-card class="paper-trading-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>持仓追踪</span>
              <el-button type="text" size="small" @click="goToPortfolio">
                查看详情 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <div v-if="paperAccount" class="paper-account-info">
            <div v-for="cur in activeCurrencies" :key="cur.code" class="account-section">
              <div class="account-section-title">{{ cur.flag }} {{ cur.label }}账户</div>
              <div class="account-item">
                <div class="account-label">总资产</div>
                <div class="account-value primary">{{ cur.prefix }}{{ formatMoney(cur.equity) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">现金</div>
                <div class="account-value">{{ cur.prefix }}{{ formatMoney(cur.cash) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">持仓市值</div>
                <div class="account-value">{{ cur.prefix }}{{ formatMoney(cur.positions_value) }}</div>
              </div>
            </div>
          </div>

          <div v-else class="empty-state">
            <el-icon class="empty-icon"><InfoFilled /></el-icon>
            <p>暂无持仓信息</p>
            <el-button type="primary" size="small" @click="goToPortfolio">
              查看持仓追踪
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="8">
        <!-- 我的自选股（精简，SSE 实时刷新） -->
        <el-card class="favorites-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>我的自选股</span>
              <el-button type="text" size="small" @click="goToFavorites">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <!-- P5-12：SSE 断连降级提示（仍在定时刷新，但非实时） -->
          <el-alert
            v-if="quotesStale"
            type="warning"
            :closable="false"
            show-icon
            class="quotes-stale-alert"
            title="行情实时中断，已切换定时刷新"
            description="连接恢复后将自动切回实时更新"
          />

          <div v-if="favoriteStocks.length === 0" class="empty-favorites">
            <el-empty description="暂无自选股" :image-size="60">
              <el-button type="primary" size="small" @click="goToFavorites">
                添加自选股
              </el-button>
            </el-empty>
          </div>

          <!-- 自选股涨跌幅横条图（红涨绿跌，行情缺失的股票自动跳过），弹性填满卡片高度 -->
          <div v-else-if="favoritesBarData.length > 0" class="favorites-chart">
            <v-chart class="chart" :option="favoritesBarOption" autoresize />
            <div class="favorites-footer">
              <span v-if="noQuoteCount > 0" class="favorites-chart-more">{{ noQuoteCount }} 只暂无行情</span>
              <el-button type="text" size="small" @click="goToFavorites">
                查看全部 {{ favoriteStocks.length }} 只自选股
              </el-button>
            </div>
          </div>

          <div v-else class="favorites-list">
            <div
              v-for="stock in favoriteStocks.slice(0, 8)"
              :key="stock.stock_code"
              class="favorite-item"
              @click="viewStockDetail(stock)"
            >
              <div class="stock-info">
                <router-link target="_blank" rel="noopener" :to="`/stocks/${stock.stock_code}`" class="stock-code" @click.stop>{{ stock.stock_code }}</router-link>
                <router-link target="_blank" rel="noopener" :to="`/stocks/${stock.stock_code}`" class="stock-name" @click.stop>{{ stock.stock_name }}</router-link>
              </div>
              <div class="stock-price">
                <div class="current-price">¥{{ stock.current_price }}</div>
                <div
                  class="change-percent"
                  :class="getPriceChangeClass(stock.change_percent)"
                >
                  {{ stock.change_percent == null ? '——' : fmtPct(stock.change_percent) }}
                </div>
              </div>
            </div>
            <div v-if="favoriteStocks.length > 8" class="favorites-footer">
              <el-button type="text" size="small" @click="goToFavorites">
                查看全部 {{ favoriteStocks.length }} 只自选股
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 数据缺口修复对话框 -->
    <el-dialog
      v-model="repairVisible"
      title="修复数据缺口"
      width="560px"
      :close-on-click-modal="false"
    >
      <div v-if="repairAuditLoading" class="confirm-body">
        <div class="tip-line"><el-icon><Loading /></el-icon><span>正在审计最近 {{ repairWindowDays }} 个交易日的覆盖度…</span></div>
      </div>
      <div v-else-if="!repairRunning" class="confirm-body">
        <template v-if="repairAudit">
          <el-alert
            v-if="repairAudit.has_gaps"
            type="warning"
            :closable="false"
            show-icon
            :title="`发现缺口：行情缺失 ${repairAudit.totals?.quotes_missing || 0} 只、低质量 ${repairAudit.totals?.quotes_low_quality || 0} 只，整日缺口 ${repairAudit.totals?.quotes_gap_dates || 0} 天`"
          />
          <el-alert
            v-else
            type="success"
            :closable="false"
            show-icon
            title="最近交易日数据完整，无需修复"
          />
          <div class="confirm-tip" style="margin-top: 16px;">
            <div class="tip-line">
              <el-icon><List /></el-icon>
              <span>窗口 {{ repairAudit.window_start }} ~ {{ repairAudit.window_end }}（{{ repairAudit.window_trading_days }} 交易日），在市 {{ repairAudit.universe_count }} 只</span>
            </div>
            <div v-if="repairAudit.has_gaps" class="tip-line">
              <el-icon><Timer /></el-icon>
              <span>预计耗时 {{ humanDuration(repairAudit.estimated_seconds) }}（仅补缺口，不重拉全量）</span>
            </div>
            <div v-if="repairAudit.totals?.quotes_gap_dates" class="tip-line">
              <el-icon><Warning /></el-icon>
              <span>整日缺口：{{ gapDateText(repairAudit.quotes?.gap_dates) }}</span>
            </div>
            <div v-if="repairAudit.totals?.quotes_scattered_dates" class="tip-line">
              <el-icon><Warning /></el-icon>
              <span>散点缺口：{{ repairAudit.totals.quotes_scattered_dates }} 个交易日存在个别股票缺失/低质量</span>
            </div>
            <div v-if="repairAudit.totals?.daily_basic_gap_dates || repairAudit.totals?.moneyflow_gap_dates" class="tip-line">
              <el-icon><Warning /></el-icon>
              <span>估值缺口 {{ repairAudit.totals?.daily_basic_gap_dates || 0 }} 天，资金流缺口 {{ repairAudit.totals?.moneyflow_gap_dates || 0 }} 天</span>
            </div>
            <div class="tip-line"><el-icon><Refresh /></el-icon><span>修复按缺失项补数，已有记录不会重复写入</span></div>
          </div>
        </template>
        <el-alert v-else type="info" :closable="false" title="未能获取审计结果，请关闭后重试" />
      </div>
      <div v-else class="progress-body">
        <div class="progress-title">
          <el-icon style="color: var(--el-color-primary); margin-right:8px;"><Loading /></el-icon>
          {{ repairMessage || '正在修复数据缺口…' }}
        </div>
        <el-progress
          :percentage="repairProgress"
          :status="repairFailed ? 'exception' : undefined"
          :stroke-width="16"
          :text-inside="false"
        />
        <div class="progress-meta">
          <div>已写入：行情 {{ repairWritten.quotes }} 条 / 估值 {{ repairWritten.daily_basic }} 条 / 资金流 {{ repairWritten.moneyflow }} 条</div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="!repairRunning" @click="repairVisible = false">取消</el-button>
        <el-button
          v-if="!repairRunning"
          type="primary"
          :loading="repairStarting"
          :disabled="!repairAudit?.has_gaps"
          @click="doRepair"
        >
          开始修复
        </el-button>
        <el-button v-if="repairRunning" :disabled="!repairFinished" @click="repairVisible = false">
          {{ repairFinished ? '关闭' : '修复中...' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'DashboardHome' })
import { ref, reactive, computed, onMounted, onBeforeUnmount, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  InfoFilled,
  List,
  Loading,
  Odometer,
  Refresh,
  Timer,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DataHealthCard from '@/components/Dashboard/DataHealthCard.vue'
import MonitorSummary from '@/components/Dashboard/MonitorSummary.vue'
import { favoritesApi } from '@/api/favorites'
import { paperApi, type PaperAccountSummary } from '@/api/paper'
import * as schedulerApi from '@/api/scheduler'
import { todayApi, type TodayActions } from '@/api/today'
import { subscribeQuotesUpdate } from '@/utils/quotesSSE'
import { fmtPct, fmtMoney } from '@/utils/format'
import { use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

echartsUse([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const router = useRouter()

// 自选股数据
const favoriteStocks = ref<any[]>([])

// 自选股涨跌幅横条图（红涨绿跌，行情缺失的股票自动跳过）
const FAVORITES_BAR_MAX = 18
const favoritesBarData = computed(() => {
  return (favoriteStocks.value || [])
    .filter((s: any) => s?.change_percent != null)
    .slice(0, FAVORITES_BAR_MAX)
})

// 暂无行情的自选股数量（供页脚提示，避免留白误导）
const noQuoteCount = computed(() => (favoriteStocks.value || []).filter((s: any) => s?.change_percent == null).length)

const favoritesBarOption = computed(() => {
  const data = favoritesBarData.value
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = params[0]
        const s = data[p?.dataIndex]
        if (!p || !s) return ''
        return `${s.stock_name || s.stock_code}（${s.stock_code}）<br/>涨跌幅：${fmtPct(s.change_percent)}`
      },
    },
    grid: { left: 66, right: 30, top: 4, bottom: 4 },
    xAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } },
    },
    yAxis: {
      type: 'category',
      data: data.map((s: any) => (s.stock_name || s.stock_code).slice(0, 6)),
      axisLabel: { fontSize: 11 },
    },
    series: [{
      type: 'bar',
      barWidth: 10,
      itemStyle: { borderRadius: 3 },
      data: data.map((s: any) => {
        const v = Number(s.change_percent)
        return {
          value: v,
          itemStyle: { color: v >= 0 ? '#f56c6c' : '#67c23a' },
        }
      }),
    }],
  }
})

// P5-12：SSE 实时行情信号是否进入降级态（断连后依赖定时刷新兜底）
const quotesStale = ref(false)

// 模拟交易账户数据
const paperAccount = ref<PaperAccountSummary | null>(null)

// ---------- 今日待办（交易页「买 / 盯 / 卖」结论的提炼，点击去交易页处理） ----------
const TODAY_TOP_N = 3
const todayLoading = ref(false)
const todayData = ref<TodayActions | null>(null)

const loadTodayTodo = async () => {
  todayLoading.value = true
  try {
    todayData.value = await todayApi.getActions()
  } catch (error) {
    console.error('加载今日待办失败:', error)
    todayData.value = null
  } finally {
    todayLoading.value = false
  }
}

interface TodayColItem { code: string; name: string; meta: string }
interface TodayCol { key: string; badge: string; count: number; text: string; items: TodayColItem[]; empty: string }

const todayCols = computed<TodayCol[]>(() => {
  const d = todayData.value
  if (!d) return []
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`

  const buyItems: TodayColItem[] = d.buy.items.slice(0, TODAY_TOP_N).map((b) => ({
    code: b.code,
    name: b.name,
    meta: b.blocked
      ? `现价 ${b.current_price} · 环境红灯暂停`
      : `现价 ${b.current_price} · 止损 ${b.stop_loss_price}`,
  }))

  const nearCount = d.watch.near_count
  const watchItems: TodayColItem[] = d.watch.items.slice(0, TODAY_TOP_N).map((w) => ({
    code: w.code,
    name: w.name,
    meta: `现价 ${w.current_price} · 距触发 ${pct(w.to_trigger_pct)}`,
  }))

  const sellItems: TodayColItem[] = d.sell.items
    .filter((s) => s.state !== 'normal')
    .slice(0, TODAY_TOP_N)
    .map((s) => ({
      code: s.code,
      name: s.name,
      meta: s.reference_price != null
        ? `${s.advice_label} · 参考价 ${s.reference_price}`
        : s.advice_label,
    }))

  return [
    {
      key: 'buy',
      badge: '买',
      count: d.buy.count,
      text: d.buy.count ? '只已触发' : '今日无触发',
      items: buyItems,
      empty: '今日无 B2 触发，不买',
    },
    {
      key: 'watch',
      badge: '盯',
      count: d.watch.count,
      text: nearCount ? `只待触发 · ${nearCount} 只临近` : '只待触发',
      items: watchItems,
      empty: '观察池暂无待触发标的',
    },
    {
      key: 'sell',
      badge: '卖',
      count: d.sell.exit_count,
      text: d.sell.exit_count
        ? (d.sell.warn_count ? `只需离场 · ${d.sell.warn_count} 只预警` : '只需离场')
        : '无需离场',
      items: sellItems,
      empty: '持仓无离场信号，继续持有',
    },
  ]
})

// ---------- 数据缺口修复（审计 → 只补缺口） ----------
const repairWindowDays = 20
const repairVisible = ref(false)
const repairAuditLoading = ref(false)
const repairAudit = ref<any | null>(null)
const repairStarting = ref(false)
const repairRunning = ref(false)
const repairFinished = ref(false)
const repairFailed = ref(false)
const repairProgress = ref(0)
const repairMessage = ref('')
const repairWritten = reactive({ quotes: 0, daily_basic: 0, moneyflow: 0 })
let repairPollTimer: ReturnType<typeof setInterval> | null = null

const stopRepairPoll = () => {
  if (repairPollTimer) {
    clearInterval(repairPollTimer)
    repairPollTimer = null
  }
}

const resetRepairState = () => {
  stopRepairPoll()
  repairAudit.value = null
  repairAuditLoading.value = false
  repairStarting.value = false
  repairRunning.value = false
  repairFinished.value = false
  repairFailed.value = false
  repairProgress.value = 0
  repairMessage.value = ''
  repairWritten.quotes = 0
  repairWritten.daily_basic = 0
  repairWritten.moneyflow = 0
}

const unwrap = (res: any) => (res as any)?.data?.data || (res as any)?.data || {}

const applyRepairRun = (run: any) => {
  if (!run) return
  repairProgress.value = Number(run.progress || 0)
  repairMessage.value = run.message || ''
  const w = run.written || {}
  repairWritten.quotes = Number(w.quotes || 0)
  repairWritten.daily_basic = Number(w.daily_basic || 0)
  repairWritten.moneyflow = Number(w.moneyflow || 0)
  if (run.status && run.status !== 'running') {
    repairFinished.value = true
    repairFailed.value = run.status === 'failed'
    stopRepairPoll()
    if (run.status === 'completed') ElMessage.success('数据缺口已修复')
    else if (run.status === 'partial') ElMessage.warning('修复完成，但仍有缺口未能自愈（可能为停牌/退市数据）')
    else if (run.status === 'failed') ElMessage.error(run.message || '修复失败')
  }
}

const pollRepairStatus = async () => {
  try {
    const res = await schedulerApi.getDataRepairStatus()
    const run = unwrap(res)
    if (run?.run_id) applyRepairRun(run)
  } catch (e) {
    console.warn('获取修复进度失败', e)
  }
}

const startRepairPoll = () => {
  stopRepairPoll()
  repairPollTimer = setInterval(pollRepairStatus, 2000)
}

const openSyncConfirm = async () => {
  resetRepairState()
  repairVisible.value = true
  repairAuditLoading.value = true
  try {
    // 已有修复任务在跑时直接进入进度视图，避免重复触发
    const statusRes = await schedulerApi.getDataRepairStatus()
    const run = unwrap(statusRes)
    if (run && run.status === 'running') {
      repairRunning.value = true
      repairFinished.value = false
      applyRepairRun(run)
      startRepairPoll()
      return
    }
    const auditRes = await schedulerApi.auditDataGaps(repairWindowDays)
    repairAudit.value = unwrap(auditRes)
  } catch (e: any) {
    ElMessage.error(`数据审计失败：${e?.message || '未知错误'}`)
    repairAudit.value = null
  } finally {
    repairAuditLoading.value = false
  }
}

const doRepair = async () => {
  repairStarting.value = true
  try {
    const res = await schedulerApi.startDataRepair(repairWindowDays)
    const data = unwrap(res)
    if (data.status === 'busy') {
      ElMessage.warning('已有修复任务正在执行')
      repairRunning.value = true
      startRepairPoll()
      return
    }
    repairRunning.value = true
    repairFinished.value = false
    repairFailed.value = false
    repairProgress.value = 0
    repairMessage.value = '任务已提交，正在审计…'
    startRepairPoll()
  } catch (e: any) {
    ElMessage.error(`启动修复失败：${e?.message || '未知错误'}`)
  } finally {
    repairStarting.value = false
  }
}

const humanDuration = (seconds: number) => {
  const s = Number(seconds || 0)
  if (s <= 0) return '数秒'
  if (s < 60) return `约 ${s} 秒`
  return `约 ${Math.ceil(s / 60)} 分钟`
}

const gapDateText = (rows: any[]) => {
  if (!rows || !rows.length) return '无'
  return rows.map((r: any) => `${r.trade_date}（缺 ${r.missing_count}）`).join('、')
}

// ---------- 通用 ----------
const getCurrencyAmount = (
  amount: number | { CNY: number; HKD: number; USD: number } | undefined,
  currency: 'CNY' | 'HKD' | 'USD',
  fallback = 0
): number => {
  if (typeof amount === 'number') return amount
  return amount?.[currency] ?? fallback
}

// 活跃账户币种（含总资产/现金/市值，供精简卡片渲染）
const activeCurrencies = computed(() => {
  if (!paperAccount.value) return []
  const acc = paperAccount.value
  const isObj = (v: any) => v && typeof v === 'object' && !Array.isArray(v)
  const codes = isObj(acc.cash) ? Object.keys(acc.cash) : ['CNY']
  const meta: Record<string, { label: string; flag: string; prefix: string }> = {
    CNY: { label: 'A股', flag: '🇨🇳', prefix: '¥' },
    HKD: { label: '港股', flag: '🇭🇰', prefix: 'HK$' },
    USD: { label: '美股', flag: '🇺🇸', prefix: '$' },
  }
  return codes.map(code => {
    const m = meta[code] || { label: code, flag: '', prefix: '' }
    return {
      code,
      label: m.label,
      flag: m.flag,
      prefix: m.prefix,
      cash: getCurrencyAmount(acc.cash, code as any),
      positions_value: getCurrencyAmount(acc.positions_value, code as any),
      equity: getCurrencyAmount(acc.equity, code as any),
    }
  })
})

onBeforeUnmount(() => {
  stopRepairPoll()
  favSseUnsubscribe?.()
})

// 跳转
const goToFavorites = () => {
  router.push('/favorites')
}

const goToPortfolio = () => {
  router.push('/portfolio')
}

const viewStockDetail = (stock: any) => {
  // 跳转到批量分析页并带入股票代码
  router.push(`/analysis/batch?stock=${stock.stock_code}`)
}

const getPriceChangeClass = (changePercent: number) => {
  if (changePercent > 0) return 'price-up'
  if (changePercent < 0) return 'price-down'
  return 'price-neutral'
}

// 格式化金额（千分位，由调用方携带货币符号）
const formatMoney = (value: number) => fmtMoney(value, '')

const loadFavoriteStocks = async () => {
  try {
    const response = await favoritesApi.list()
    if (response.success && response.data) {
      favoriteStocks.value = response.data.map((item: any) => ({
        stock_code: item.stock_code || item.symbol,
        stock_name: item.stock_name,
        current_price: item.current_price || 0,
        change_percent: item.change_percent == null ? null : item.change_percent
      }))
    }
  } catch (error) {
    console.error('加载自选股失败:', error)
  }
}

// 加载模拟交易账户信息
const loadPaperAccount = async () => {
  try {
    const response = await paperApi.getAccount()
    if (response.success && response.data) {
      paperAccount.value = response.data.account
    }
  } catch (error) {
    console.error('加载模拟交易账户失败:', error)
    paperAccount.value = null
  }
}

// 自选股实时刷新（SSE 行情信号触发）
let favSseUnsubscribe: (() => void) | null = null

// 生命周期
onMounted(async () => {
  await Promise.all([loadFavoriteStocks(), loadPaperAccount(), loadTodayTodo()])
  // 收到行情更新信号立即刷新自选股（延迟约 0-2 秒）。
  // P3-6：信号若带值则原地 patch 对应股票，避免全量重拉与陈旧读取；未带值才兜底全量刷新。
  favSseUnsubscribe = subscribeQuotesUpdate((signal) => {
    const patch = signal?.quotes
    if (patch && Object.keys(patch).length) {
      let changed = false
      favoriteStocks.value.forEach((s: any) => {
        const q = patch[s.stock_code]
        if (q) {
          s.current_price = q.close
          s.change_percent = q.pct_chg == null ? null : q.pct_chg
          changed = true
        }
      })
      if (changed) {
        favoriteStocks.value = [...favoriteStocks.value]
        return
      }
    }
    loadFavoriteStocks()
  }, (status) => {
    // P5-12：SSE 降级/恢复时同步 UI 提示
    quotesStale.value = status === 'degraded'
  })
})

// keep-alive 缓存恢复时刷新核心数据（SSE 订阅在缓存期间保持存活，不重复订阅）
let dashInited = false
onActivated(() => {
  if (dashInited) {
    loadFavoriteStocks()
    loadPaperAccount()
    loadTodayTodo()
  }
  dashInited = true
})
</script>

<style lang="scss" scoped>
.dashboard {
  // 页面容器交给全局 .app-page；顶部横幅由全局 .page-hero 提供

  // 今日待办：交易页买 / 盯 / 卖的提炼
  .todo-bar {
    display: grid;
    grid-template-columns: 210px 1fr auto;
    grid-template-areas:
      'head head head'
      'env cols more';
    align-items: stretch;
    gap: 10px 16px;
    margin-bottom: 24px;
    padding: 14px 18px;
    border-radius: 14px;
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color-light);
  }
  .todo-head {
    grid-area: head;
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .todo-title {
    font-size: 14px;
    font-weight: 700;
  }
  .todo-sub {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  // 环境结论（点击进入今日待办）
  .todo-env {
    grid-area: env;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 3px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);
    background: var(--el-fill-color-lighter);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    &:hover { border-color: var(--el-color-primary-light-5); }
    .te-verdict {
      font-size: 14px;
      font-weight: 700;
      line-height: 1.3;
    }
    .te-pos {
      font-size: 12px;
      color: var(--el-text-color-regular);
      line-height: 1.4;
    }
    &.gate-red {
      border-color: var(--el-color-danger-light-5);
      background: var(--el-color-danger-light-9);
      .te-verdict { color: var(--el-color-danger); }
    }
    &.gate-yellow {
      border-color: var(--el-color-warning-light-5);
      background: var(--el-color-warning-light-9);
      .te-verdict { color: var(--el-color-warning-dark-2); }
    }
    &.gate-green {
      border-color: var(--el-color-success-light-5);
      background: var(--el-color-success-light-9);
      .te-verdict { color: var(--el-color-success); }
    }
  }

  // 买 / 盯 / 卖 三列
  .todo-cols {
    grid-area: cols;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }
  .todo-col {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);
    background: var(--el-bg-color);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    &:hover { background: var(--el-fill-color-lighter); }
    &.col-buy { border-left: 3px solid var(--el-color-danger); }
    &.col-watch { border-left: 3px solid var(--el-color-warning); }
    &.col-sell { border-left: 3px solid var(--el-color-success); }
  }
  .tc-hd {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .tc-badge {
    display: inline-block;
    padding: 0 6px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    line-height: 18px;
    color: #fff;
    background: var(--el-text-color-secondary);
  }
  .col-buy .tc-badge { background: var(--el-color-danger); }
  .col-watch .tc-badge { background: var(--el-color-warning); }
  .col-sell .tc-badge { background: var(--el-color-success); }
  .tc-num {
    font-size: 18px;
    font-weight: 700;
    font-family: var(--app-font-mono, monospace);
    color: var(--el-text-color-primary);
  }
  .tc-text {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
  .tc-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
    margin: 0;
    padding: 0;
    list-style: none;
    li {
      display: flex;
      align-items: baseline;
      gap: 6px;
      font-size: 12px;
      line-height: 1.5;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tc-name {
      max-width: 6em;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--el-text-color-primary);
      font-weight: 600;
    }
    .tc-code {
      font-family: var(--app-font-mono, monospace);
      color: var(--el-text-color-secondary);
    }
    .tc-meta {
      color: var(--el-text-color-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tc-empty { color: var(--el-text-color-placeholder); }
  }
  .todo-more {
    grid-area: more;
    align-self: center;
  }

  @media (max-width: 1100px) {
    .todo-bar {
      grid-template-columns: 1fr;
      grid-template-areas:
        'head'
        'env'
        'cols'
        'more';
    }
    .todo-cols { grid-template-columns: 1fr; }
  }

  // 顶部卡片统一样式
  .monitor-top {
    .el-col {
      margin-bottom: 24px;
    }
    .el-card {
      border-radius: 14px;
      border: 1px solid var(--el-border-color-light);
      box-shadow: var(--el-box-shadow-light);
      transition: transform .2s, box-shadow .2s;
      &:hover {
        box-shadow: var(--el-box-shadow-medium);
      }
      .el-card__header {
        border-bottom: 1px solid var(--el-border-color-lighter);
        padding: 14px 18px;
      }
      .el-card__body {
        padding: 16px 18px;
      }
    }
  }

  // 自选股
  .favorites-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .empty-favorites {
      text-align: center;
      padding: 20px 0;
    }

    .quotes-stale-alert {
      margin-bottom: 12px;
    }

    .favorites-chart {
      height: 100%;
      display: flex;
      flex-direction: column;

      .chart {
        flex: 1;
        min-height: 160px;
        width: 100%;
      }

      .favorites-chart-more {
        font-size: 12px;
        color: var(--el-text-color-placeholder);
      }

      .favorites-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-top: 8px;
        border-top: none;
        margin-top: 4px;
      }
    }

    .favorites-list {
      .favorite-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid var(--el-border-color-lighter);
        cursor: pointer;
        transition: background-color 0.3s ease;

        &:hover {
          background-color: var(--el-fill-color-lighter);
          margin: 0 -16px;
          padding: 12px 16px;
          border-radius: 6px;
        }

        &:last-child {
          border-bottom: none;
        }

        .stock-info {
          .stock-code {
            font-weight: 600;
            font-size: 14px;
            color: var(--el-text-color-primary);
          }

          .stock-name {
            font-size: 12px;
            color: var(--el-text-color-regular);
            margin-top: 2px;
          }
        }

        .stock-price {
          text-align: right;

          .current-price {
            font-weight: 600;
            font-size: 14px;
            color: var(--el-text-color-primary);
          }

          .change-percent {
            font-size: 12px;
            margin-top: 2px;

            &.price-up { color: var(--app-up); }
            &.price-down { color: var(--app-down); }
            &.price-neutral { color: var(--el-text-color-regular); }
          }
        }
      }
    }

    .favorites-footer {
      text-align: center;
      padding-top: 12px;
      border-top: 1px solid var(--el-border-color-lighter);
      margin-top: 12px;
    }
  }

  // 模拟交易账户
  .paper-trading-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .paper-account-info {
      display: flex;
      flex-direction: column;
      gap: 12px;

      .account-section {
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 8px;
        padding: 10px 12px;
        background-color: var(--el-fill-color-blank);

        .account-section-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin-bottom: 8px;
          padding-bottom: 6px;
          border-bottom: 1px solid var(--el-border-color-lighter);
        }
      }

      .account-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 6px 0;

        .account-label {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }

        .account-value {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          &.primary {
            color: var(--el-color-primary);
            font-size: 15px;
          }
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 20px 0;

      .empty-icon {
        font-size: 48px;
        color: var(--el-text-color-placeholder);
        margin-bottom: 12px;
      }

      p {
        color: var(--el-text-color-secondary);
        margin-bottom: 16px;
      }
    }
  }

  .confirm-body {
    .confirm-tip {
      display: flex;
      flex-direction: column;
      gap: 8px;
      color: var(--el-text-color-regular);
      font-size: 13px;
      line-height: 1.6;

      .tip-line {
        display: flex;
        align-items: center;
        gap: 6px;

        .el-icon {
          color: var(--el-color-primary);
          flex-shrink: 0;
        }
      }
    }
  }

  .progress-body {
    .progress-title {
      font-weight: 600;
      margin-bottom: 16px;
      color: var(--el-text-color-primary);
      display: flex;
      align-items: center;
      font-size: 14px;

      .el-icon {
        animation: spin 1s linear infinite;
      }
    }

    .sync-phases {
      display: flex;
      gap: 8px;
      margin: 16px 0;
      flex-wrap: wrap;

      .sync-phase-item {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 12px;
        background: var(--el-fill-color-light);
        color: var(--el-text-color-secondary);

        &.active {
          background: var(--el-color-primary-light-9);
          color: var(--el-color-primary);
          font-weight: 600;
        }

        &.done {
          color: var(--el-color-success);
        }

        &.skipped {
          color: var(--el-text-color-placeholder);
          opacity: 0.7;
        }

        .sync-phase-icon {
          font-size: 14px;
          display: inline-flex;
          align-items: center;

          .phase-done {
            color: var(--el-color-success);
          }

          .phase-running {
            animation: spin 1s linear infinite;
            color: var(--el-color-primary);
          }
        }
      }
    }

    .progress-meta {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--el-text-color-regular);
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>