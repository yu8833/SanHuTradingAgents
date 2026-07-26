<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  TrendCharts,
  List,
  Refresh,
  Search,
  CircleCheck,
  Warning,
  InfoFilled,
  Position,
  PieChart,
  Histogram,
  DataAnalysis,
  DataLine,
  QuestionFilled
} from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { RadarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { screeningApi } from '@/api/screening'
import type {
  ThreeBuysThreeSellsScanReq,
  ThreeBuysThreeSellsItem,
  ThreeBuysThreeSellsBacktestReq,
  ThreeBuysThreeSellsBacktestResp
} from '@/api/screening'
import RetailBuyDialog from './components/RetailBuyDialog.vue'

echartsUse([RadarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const STORAGE_KEY = 'three_buys_three_sells_scan_result'
const BACKTEST_STORAGE_KEY = 'three_buys_three_sells_backtest_result'

const loading = ref(false)
const backtestLoading = ref(false)
const hasSearched = ref(false)
const activeTab = ref('scan')
const results = ref<ThreeBuysThreeSellsItem[]>([])
const tookMs = ref<number>(0)
const scannedCount = ref<number>(0)
const marketTrend = ref<string>('')
const introCollapsed = ref<string[]>([])

function saveScanResult() {
  const data = {
    results: results.value,
    tookMs: tookMs.value,
    scannedCount: scannedCount.value,
    marketTrend: marketTrend.value,
    scanParams: scanParams.value,
    timestamp: Date.now()
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch (e) {
    console.warn('Failed to save scan result to localStorage', e)
  }
}

function loadScanResult() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const data = JSON.parse(stored)
      if (data.results && data.results.length > 0) {
        results.value = data.results
        tookMs.value = data.tookMs || 0
        scannedCount.value = data.scannedCount || 0
        marketTrend.value = data.marketTrend || ''
        if (data.scanParams) {
          scanParams.value = { ...defaultScanParams, ...data.scanParams }
        }
        hasSearched.value = true
        return true
      }
    }
  } catch (e) {
    console.warn('Failed to load scan result from localStorage', e)
  }
  return false
}

function clearScanResult() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    console.warn('Failed to clear scan result from localStorage', e)
  }
}

function saveBacktestResult() {
  if (!backtestResult.value) return
  const data = {
    backtestResult: backtestResult.value,
    backtestParams: backtestParams.value,
    timestamp: Date.now()
  }
  try {
    localStorage.setItem(BACKTEST_STORAGE_KEY, JSON.stringify(data))
  } catch (e) {
    console.warn('Failed to save backtest result to localStorage', e)
  }
}

function loadBacktestResult() {
  try {
    const stored = localStorage.getItem(BACKTEST_STORAGE_KEY)
    if (stored) {
      const data = JSON.parse(stored)
      if (data.backtestResult) {
        backtestResult.value = data.backtestResult
        if (data.backtestParams) {
          backtestParams.value = { ...defaultBacktestParams, ...data.backtestParams }
        }
        return true
      }
    }
  } catch (e) {
    console.warn('Failed to load backtest result from localStorage', e)
  }
  return false
}

function clearBacktestResult() {
  try {
    localStorage.removeItem(BACKTEST_STORAGE_KEY)
  } catch (e) {
    console.warn('Failed to clear backtest result from localStorage', e)
  }
}

const defaultScanParams: Required<ThreeBuysThreeSellsScanReq> = {
  top_n: 10,
  hold_days: 60,
  initial_capital: 1000000,
  max_position_pct: 0.15,
  limit: 50
}

const scanParams = ref<ThreeBuysThreeSellsScanReq>({ ...defaultScanParams })

const defaultBacktestParams: Required<ThreeBuysThreeSellsBacktestReq> = {
  ...defaultScanParams,
  start_date: '',
  end_date: ''
}

const backtestParams = ref<ThreeBuysThreeSellsBacktestReq>({ ...defaultBacktestParams })
const backtestResult = ref<ThreeBuysThreeSellsBacktestResp | null>(null)

const strategyCards = [
  {
    type: 'B1',
    label: '左侧买点',
    icon: '🎯',
    desc: 'BIAS(60) ∈ [-30%, -20%]，超跌反弹概率高',
    color: '#67c23a'
  },
  {
    type: 'B2',
    label: '突破买点',
    icon: '🚀',
    desc: '放量 + 中阳 + 站上MA55&MA60，趋势启动',
    color: '#e6a23c'
  },
  {
    type: 'B3',
    label: '回踩买点',
    icon: '💎',
    desc: '回调至MA60附近 + 放量中阳支撑，加仓机会',
    color: '#409eff'
  },
  {
    type: 'S1',
    label: '减仓预警',
    icon: '⚠️',
    desc: 'BIAS超阈值 或 GMMA慢组压缩>30%',
    color: '#e6a23c'
  },
  {
    type: 'S2',
    label: '主减仓',
    icon: '📉',
    desc: '连续2日跌破短期均线组，趋势转弱',
    color: '#f56c6c'
  },
  {
    type: 'S3',
    label: '清仓卖出',
    icon: '🛑',
    desc: '跌破MA55&MA60且MA60拐头向下',
    color: '#909399'
  }
]

const evolutionSteps = [
  {
    phase: '阶段一：下跌筑底 · 左侧建仓',
    signals: ['B1 左侧买点'],
    desc: '股价经历长期下跌后，BIAS(60)进入极度超跌区间（-30%~-20%），此时下跌动能衰竭，反弹概率大幅提升。操作建议：设置多档分批建仓，首仓10%试探，若继续下跌5%-8%再补10%，总仓位控制在20%以内。止损位设在买入价下方8%-10%，跌破则无条件止损。',
    risk: '高风险：可能继续下跌或横盘磨底',
    position: '小仓位试探（10%-20%），分批建仓',
    action: '买入动作：BIAS60跌破-25%时分批买入；止损：跌破前期低点或亏损8%止损'
  },
  {
    phase: '阶段二：趋势启动 · 突破加仓',
    signals: ['B2 突破买点'],
    desc: '放量（≥1.5倍均量）中阳线（涨幅≥3%）同时站上MA55和MA60，标志着下跌趋势正式结束、上升趋势开启。这是最具性价比的加仓点，成功率最高。操作建议：确认突破后加仓至40%-60%，止损位上移至MA60下方。',
    risk: '中等风险：可能假突破（需结合放量确认）',
    position: '主力仓位建仓（40%-60%），重仓参与',
    action: '买入动作：放量突破MA60当日尾盘或次日开盘买入；止损：跌破MA60超过3%止损'
  },
  {
    phase: '阶段三：趋势延续 · 回踩加仓',
    signals: ['B3 回踩买点'],
    desc: '股价沿短期均线组（GMMA快组）稳步上行，期间回调至MA60附近获得支撑时为加仓机会。缩量回踩+放量中阳确认支撑有效，说明主力仍在，趋势未改。操作建议：回踩MA60企稳时分批加仓，总仓位提升至60%-80%，止损位继续上移保护利润。',
    risk: '低风险：趋势行情，顺势而为',
    position: '加仓至重仓（60%-80%），让利润奔跑',
    action: 'B3买入：回踩MA60缩量企稳时加仓；止损：跌破MA60超过3%止损'
  },
  {
    phase: '阶段四：高位过热 · 减仓预警',
    signals: ['S1 减仓预警'],
    desc: '当BIAS超过阈值（如BIAS20＞15%）或GMMA慢组压缩超过30%时，说明短期涨幅过大、市场过热，随时可能回调。此时不是清仓信号，而是减仓锁定部分利润的信号。操作建议：减仓1/3浮动仓位，保留底仓继续吃主升浪，用部分利润换更高收益。',
    risk: '中等风险：过热区域，谨防快速回调',
    position: '减仓锁定利润（40%-60%），保留底仓',
    action: 'S1卖出：BIAS过大或慢组压缩时减仓1/3；纪律：不贪多，落袋为安'
  },
  {
    phase: '阶段五：趋势转弱 · 主减仓',
    signals: ['S2 主减仓'],
    desc: 'BIAS达到极端值（如BIAS20＞25%）、股价出现滞涨（上影线增多、量价背离），此时顶部风险加大。当连续2日跌破GMMA短期均线组时，确认短期趋势转弱，需大幅减仓。操作建议：S2确认后再减仓1/2，仅保留少量底仓观察。',
    risk: '中高风险：顶部区域，谨防快速回调',
    position: '大幅减仓（10%-20%），落袋为安',
    action: 'S2减仓：跌破短期均线组再减1/2；纪律：不要等反弹，趋势破了就走'
  },
  {
    phase: '阶段六：趋势反转 · 清仓离场',
    signals: ['S3 清仓卖出'],
    desc: '股价有效跌破MA55和MA60，且MA60拐头向下，确认中长期趋势反转。此时必须无条件清仓，不要抱有侥幸心理。操作建议：清仓后空仓观望，等待下一轮B1信号出现，期间不要盲目抄底。',
    risk: '清仓离场：趋势反转，空仓等待下一轮周期',
    position: '空仓观望，保存实力',
    action: '卖出动作：跌破MA60且MA60拐头向下，当日清仓；纪律：宁可错过，不可做错'
  }
]

const signalStatsList = computed(() => {
  if (!backtestResult.value) return []
  return Object.entries(backtestResult.value.signal_stats).map(([signal_type, v]) => ({
    signal_type,
    count: v.count,
    win_rate: v.win_rate,
    avg_return: v.avg_return
  }))
})

const sellReasonStatsList = computed(() => {
  if (!backtestResult.value) return []
  return Object.entries(backtestResult.value.sell_reason_stats).map(([sell_reason, v]) => ({
    sell_reason,
    count: v.count,
    win_rate: v.win_rate,
    avg_return: v.avg_return
  }))
})

const equityCurveOption = computed(() => {
  if (!backtestResult.value?.daily_results?.length) return {}
  const initial = backtestResult.value.initial_capital || backtestResult.value.daily_results[0]?.total_value || 1
  const dates = backtestResult.value.daily_results.map((d: any) => d.date)
  const values = backtestResult.value.daily_results.map((d: any) => {
    return ((d.total_value - initial) / initial * 100).toFixed(2)
  })
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>收益率: <strong>${p.value}%</strong>`
      }
    },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: 30 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: 10 }
    },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      lineStyle: { color: '#409eff', width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.02)' }
          ]
        }
      },
      itemStyle: { color: '#409eff' },
      symbol: 'none'
    }]
  }
})

function getSignalTypeTag(type: string): string {
  if (type.includes('B1')) return 'success'
  if (type.includes('B2')) return 'warning'
  if (type.includes('B3')) return 'primary'
  if (type.includes('S1')) return 'warning'
  if (type.includes('S2')) return 'danger'
  if (type.includes('S3')) return 'info'
  return 'info'
}

function getSellReasonTag(reason: string): string {
  if (reason.includes('S1') || reason.includes('止盈') || reason.includes('超涨')) return 'warning'
  if (reason.includes('S2') || reason.includes('跌破')) return 'danger'
  if (reason.includes('S3') || reason.includes('清仓')) return 'info'
  if (reason.includes('安全网') || reason.includes('ATR')) return 'danger'
  if (reason.includes('持有到期')) return 'primary'
  return 'info'
}

function getStockTypeTag(type: string): string {
  if (type === 'st') return 'danger'
  if (type.includes('底部') || type.includes('反转')) return 'success'
  if (type.includes('突破') || type.includes('启动')) return 'warning'
  if (type.includes('回踩') || type.includes('趋势')) return 'primary'
  if (type.includes('顶部') || type.includes('见顶')) return 'danger'
  return 'info'
}

function getScoreColor(score: number): string {
  if (score >= 8) return '#67c23a'
  if (score >= 6) return '#409eff'
  if (score >= 4) return '#e6a23c'
  return '#f56c6c'
}

function formatValue(val: number | undefined, digits = 2, suffix = ''): string {
  if (val === undefined || val === null) return '-'
  return val.toFixed(digits) + suffix
}

async function doScan() {
  loading.value = true
  hasSearched.value = true
  try {
    const resp = await screeningApi.scanThreeBuysThreeSells(scanParams.value, { timeout: 180000 })
    results.value = resp.items
    tookMs.value = resp.took_ms || 0
    scannedCount.value = resp.scanned_count || 0
    marketTrend.value = resp.market_trend || ''
    saveScanResult()
    ElMessage.success(`找到 ${resp.total} 只符合条件的股票`)
  } catch (e: any) {
    ElMessage.error(e?.message || '扫描失败')
  } finally {
    loading.value = false
  }
}

async function doBacktest() {
  backtestLoading.value = true
  backtestResult.value = null
  clearBacktestResult()
  try {
    const resp = await screeningApi.backtestThreeBuysThreeSells(backtestParams.value, { timeout: 600000 })
    backtestResult.value = resp
    saveBacktestResult()
    ElMessage.success(
      `回测完成：${resp.total_trades} 笔交易，胜率 ${resp.win_rate.toFixed(2)}%，总收益 ${resp.total_return.toFixed(2)}%`
    )
  } catch (e: any) {
    ElMessage.error(e?.message || '回测失败')
  } finally {
    backtestLoading.value = false
  }
}

function resetBacktestParams() {
  backtestParams.value = { ...defaultBacktestParams }
  ElMessage.info('回测参数已重置')
}

function addToFavorites(row: ThreeBuysThreeSellsItem) {
  ElMessage.success(`${row.name} 已加入自选`)
}

const buyDialogVisible = ref(false)
const buyTarget = reactive({
  code: '',
  stockName: '',
  price: 0,
  strategy: 'three_buys_three_sells',
})

const openBuyDialog = (row: any) => {
  buyTarget.code = row.code
  buyTarget.stockName = row.name || ''
  buyTarget.price = row.close || row.price || 0
  buyTarget.strategy = 'three_buys_three_sells'
  buyDialogVisible.value = true
}

const onBuySuccess = () => {
  ElMessage.info('持仓已更新，可在模拟交易或持仓监控中查看')
}

function formatMoney(val: number): string {
  if (val >= 100000000) return (val / 100000000).toFixed(2) + '亿'
  if (val >= 10000) return (val / 10000).toFixed(2) + '万'
  return val.toFixed(2)
}

const windowHeight = ref(window.innerHeight)

function handleResize() {
  windowHeight.value = window.innerHeight
}

const tableHeight = computed(() => {
  // 表格高度 = 视口高度 - 顶部空间（页眉+标题+参数区）
  const headerOffset = 380
  return Math.max(400, windowHeight.value - headerOffset)
})

const scoreDimMax: Record<string, number> = {
  '成交量': 20,
  'K线涨幅': 20,
  '均线形态': 20,
  '大盘配合': 20,
  'MACD': 20,
  'ΔG加分': 30,
}

function getScoreRadarOption(row: any) {
  const details = row.score_details
  if (!details || (Array.isArray(details) ? details.length === 0 : Object.keys(details).length === 0)) return null

  const dims: { name: string; value: number; max: number }[] = []

  if (Array.isArray(details)) {
    details.forEach((d: any) => {
      if (typeof d === 'string') {
        const match = d.match(/^(.+?)[:：]\s*(\d+(?:\.\d+)?)(?:\/(\d+))?/)
        if (match) {
          const name = match[1].trim()
          const value = parseFloat(match[2])
          const max = match[3] ? parseFloat(match[3]) : (scoreDimMax[name] || 100)
          dims.push({ name, value: (value / max) * 100, max: 100 })
        }
      }
    })
  } else {
    Object.entries(details).forEach(([key, val]: [string, any]) => {
      let value = 0
      const max = scoreDimMax[key] || 100
      if (typeof val === 'number') {
        value = val
      } else if (typeof val === 'string') {
        const match = val.match(/(\d+(?:\.\d+)?)\/(\d+)/)
        if (match) {
          value = parseFloat(match[1])
          dims.push({ name: key, value: (value / parseFloat(match[2])) * 100, max: 100 })
          return
        }
      }
      dims.push({ name: key, value: (value / max) * 100, max: 100 })
    })
  }

  if (!dims.length) return null

  return {
    tooltip: {
      formatter: (params: any) => {
        const data = params.value
        return dims.map((d, i) => `${d.name}: ${data[i].toFixed(0)}%`).join('<br/>')
      }
    },
    radar: {
      indicator: dims.map(d => ({ name: d.name, max: 100 })),
      radius: '60%',
      center: ['50%', '55%'],
      axisName: { fontSize: 11, color: '#606266' },
      splitArea: {
        areaStyle: {
          color: ['rgba(64, 158, 255, 0.02)', 'rgba(64, 158, 255, 0.05)', 'rgba(64, 158, 255, 0.08)', 'rgba(64, 158, 255, 0.12)']
        }
      }
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map(d => d.value),
        areaStyle: { color: 'rgba(64, 158, 255, 0.2)' },
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' }
      }]
    }]
  }
}

const avgScore = computed(() => {
  if (!results.value.length) return 0
  return results.value.reduce((sum, r) => sum + (r.score || 0), 0) / results.value.length
})

const highScoreCount = computed(() => {
  return results.value.filter(r => r.score >= 70).length
})

const backtestTableHeight = computed(() => {
  return Math.min(500, Math.max(300, windowHeight.value - 500))
})

onMounted(() => {
  loadScanResult()
  loadBacktestResult()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div class="three-buys-three-sells-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        三买三卖（趋势跟随）
      </h1>
      <p class="page-description">
        基于均线趋势、BIAS 超跌反弹和 GMMA 均线组的多级买卖点策略，捕捉完整趋势周期
      </p>
    </div>

    <!-- 策略原理卡片 -->
    <el-collapse class="strategy-intro-collapse" v-model="introCollapsed">
      <el-collapse-item name="intro">
        <template #title>
          <div class="collapse-title">
            <el-icon><InfoFilled /></el-icon>
            <span>策略原理</span>
            <el-tag type="primary" size="small" effect="plain">趋势跟随/多级买卖</el-tag>
          </div>
        </template>

        <div class="strategy-detail">
          <el-row :gutter="16" class="strategy-cards">
            <el-col :span="4" v-for="card in strategyCards" :key="card.type">
              <el-card shadow="hover" class="strategy-card">
                <div class="strategy-card-header" :style="{ borderColor: card.color }">
                  <span class="strategy-icon">{{ card.icon }}</span>
                  <span class="strategy-type" :style="{ color: card.color }">{{ card.type }}</span>
                </div>
                <div class="strategy-card-title">{{ card.label }}</div>
                <div class="strategy-card-desc">{{ card.desc }}</div>
              </el-card>
            </el-col>
          </el-row>

          <!-- 信号演化路径 - 改为垂直时间轴避免文字重叠 -->
          <div class="evolution-panel" style="margin-top: 16px;">
            <div class="card-header" style="margin-bottom: 12px;">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-icon :size="20"><TrendCharts /></el-icon>
                <span class="panel-title">信号演化路径（按时间顺序）</span>
              </div>
              <el-tag type="info" size="small" effect="plain">从下跌到反转的完整交易周期</el-tag>
            </div>

            <div class="evolution-timeline">
              <div v-for="(step, idx) in evolutionSteps" :key="idx" class="evolution-step">
                <div class="step-marker">
                  <div class="step-dot" :class="'phase-' + (idx + 1)">{{ idx + 1 }}</div>
                  <div v-if="idx < evolutionSteps.length - 1" class="step-line"></div>
                </div>
                <div class="step-content">
                  <div class="step-phase-row">
                    <span class="step-phase">{{ step.phase }}</span>
                    <div class="step-signals">
                      <el-tag
                        v-for="sig in step.signals"
                        :key="sig"
                        :type="getSignalTypeTag(sig) as any"
                        size="small"
                        effect="dark"
                        class="step-signal-tag"
                      >
                        {{ sig }}
                      </el-tag>
                    </div>
                  </div>
                  <div class="step-desc">{{ step.desc }}</div>
                  <div class="step-action">
                    <el-icon size="14" color="#409eff"><Position /></el-icon>
                    <span class="step-action-text"><strong>操作指南：</strong>{{ step.action }}</span>
                  </div>
                  <div class="step-meta">
                    <el-tag size="small" type="warning" effect="plain" class="step-meta-tag">{{ step.risk }}</el-tag>
                    <el-tag size="small" type="primary" effect="plain" class="step-meta-tag">{{ step.position }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- Tab切换 -->
    <el-tabs v-model="activeTab" style="margin-top: 16px;">
      <!-- 扫描结果Tab -->
      <el-tab-pane label="扫描结果" name="scan">
        <el-card class="result-panel" shadow="never">
          <template #header>
            <div class="card-header">
              <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-icon><List /></el-icon>
                  <span class="panel-title">扫描结果</span>
                  <el-tag v-if="marketTrend" type="success" size="small" effect="plain">
                    大盘趋势：{{ marketTrend }}
                  </el-tag>
                  <el-tag v-if="results.length > 0" type="success" size="small" effect="plain">
                    找到 {{ results.length }} 只
                  </el-tag>
                  <el-tag v-if="tookMs" type="info" size="small" effect="plain">
                    耗时 {{ (tookMs / 1000).toFixed(1) }}s
                  </el-tag>
                  <el-tag v-if="scannedCount" type="info" size="small" effect="plain">
                    扫描 {{ scannedCount }} 只
                  </el-tag>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-form-item label="返回数量" label-width="70px" style="margin-bottom: 0;">
                    <el-input-number v-model="scanParams.limit" :min="10" :max="200" :step="10" size="default" style="width: 130px;" />
                  </el-form-item>
                  <el-button type="primary" :loading="loading" @click="doScan" size="default">
                    <el-icon><Search /></el-icon>
                    开始扫描
                  </el-button>
                </div>
              </div>
            </div>
          </template>

          <!-- 评分分析 -->
          <el-row v-if="results.length > 0" :gutter="16" style="margin-bottom: 16px;">
            <el-col :span="24">
              <el-card shadow="never" class="score-stats-card">
                <template #header>
                  <div class="card-header">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <el-icon><DataLine /></el-icon>
                      <span class="panel-title">扫描结果统计</span>
                    </div>
                  </div>
                </template>
                <el-row :gutter="16">
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ results.length }}</div>
                      <div class="stat-label">符合条件股票</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ avgScore.toFixed(1) }}</div>
                      <div class="stat-label">平均综合评分</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ highScoreCount }}</div>
                      <div class="stat-label">高分股(≥70分)</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ (tookMs / 1000).toFixed(1) }}s</div>
                      <div class="stat-label">扫描耗时</div>
                    </div>
                  </el-col>
                </el-row>
              </el-card>
            </el-col>
          </el-row>

          <div v-if="!loading && results.length === 0 && !hasSearched" class="empty-state">
            <el-empty description="点击开始扫描全市场股票">
              <el-button type="primary" @click="doScan">立即扫描</el-button>
            </el-empty>
          </div>

          <div v-if="loading" class="loading-state">
            <el-loading fullscreen-text="正在扫描全市场股票，请稍候..." />
          </div>

          <el-table
            v-if="results.length > 0"
            :data="results"
            v-loading="loading"
            element-loading-text="扫描中..."
            stripe
            :height="tableHeight"
            row-key="code"
            style="width: 100%"
          >
            <el-table-column prop="code" label="代码" width="80" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" width="100" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="industry" label="行业" width="100" />
            <el-table-column label="市值" width="110" sortable :sort-method="(a: any, b: any) => a.market_cap - b.market_cap">
              <template #default="{ row }">{{ formatMoney(row.market_cap) }}</template>
            </el-table-column>
            <el-table-column prop="close" label="现价" width="90" sortable>
              <template #default="{ row }">
                <span class="price">{{ row.close.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="pct_chg" label="涨跌幅" width="100" sortable>
              <template #default="{ row }">
                <span :class="['pct', row.pct_chg >= 0 ? 'up' : 'down']">
                  {{ row.pct_chg >= 0 ? '+' : '' }}{{ row.pct_chg.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="股票状态" width="130">
              <template #default="{ row }">
                <el-tag :type="getStockTypeTag(row.stock_type) as any" size="small">
                  {{ row.stock_type_label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="主信号" width="130">
              <template #default="{ row }">
                <el-tag :type="getSignalTypeTag(row.primary_signal_type) as any" size="small" effect="dark">
                  {{ row.primary_signal_label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="bias60" label="BIAS60(%)" width="110" sortable>
              <template #default="{ row }">
                <span :class="['pct', row.bias60 >= 0 ? 'up' : 'down']">
                  {{ row.bias60 >= 0 ? '+' : '' }}{{ row.bias60.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="MA60方向" width="100">
              <template #default="{ row }">
                <el-tag :type="row.ma60_direction === 'up' ? 'success' : row.ma60_direction === 'down' ? 'danger' : 'info'" size="small">
                  {{ row.ma60_direction === 'up' ? '向上' : row.ma60_direction === 'down' ? '向下' : '走平' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="volume_ratio" label="量比" width="90" sortable>
              <template #default="{ row }">{{ row.volume_ratio?.toFixed(2) || '-' }}</template>
            </el-table-column>
            <el-table-column label="ΔG象限" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.dg_available" type="success" size="small" effect="plain">{{ row.dg_quadrant }}</el-tag>
                <span v-else class="empty-tag">暂无</span>
              </template>
            </el-table-column>
            <el-table-column label="S1止盈位" width="110">
              <template #default="{ row }">{{ row.s1_threshold?.toFixed(2) || '-' }}</template>
            </el-table-column>
            <el-table-column label="S3止损位" width="110">
              <template #default="{ row }">{{ row.stop_price?.toFixed(2) || '-' }}</template>
            </el-table-column>
            <el-table-column prop="score" label="综合评分" width="120" sortable fixed="right">
              <template #default="{ row }">
                <el-popover placement="left" :width="400" trigger="click">
                  <template #reference>
                    <div class="score-cell">
                      <el-progress :percentage="row.score" :color="getScoreColor(row.score)" :show-text="true" :stroke-width="12" />
                      <span class="score-hint">点击查看明细</span>
                    </div>
                  </template>
                  <div class="score-detail-popover">
                    <div class="score-detail-title">评分明细</div>
                    <div v-if="getScoreRadarOption(row)" class="score-radar-wrap">
                      <v-chart :option="getScoreRadarOption(row)" style="height: 220px;" autoresize />
                    </div>
                    <div v-if="row.score_details && row.score_details.length" class="score-detail-list">
                      <div v-for="(detail, idx) in row.score_details" :key="idx" class="score-detail-text-item">
                        {{ detail }}
                      </div>
                    </div>
                    <div v-else class="score-detail-empty">暂无评分明细</div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <router-link :to="{ path: '/analysis/single', query: { stock: row.code } }" class="table-link">分析</router-link>
                <el-button type="success" link @click="addToFavorites(row)">自选</el-button>
                <el-button type="primary" link @click="openBuyDialog(row)">买入</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 回测分析Tab -->
      <el-tab-pane label="回测分析" name="backtest">
        <!-- 回测参数 -->
        <el-card shadow="never" style="margin-bottom: 16px;">
          <template #header>
            <div class="card-header">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-icon><DataAnalysis /></el-icon>
                <span class="panel-title">回测参数配置</span>
              </div>
            </div>
          </template>

          <el-form :model="backtestParams" label-position="top" size="default" class="params-form">
            <el-row :gutter="32">
              <el-col :span="6">
                <el-form-item label="开始日期">
                  <el-date-picker v-model="backtestParams.start_date" type="date" placeholder="选择开始日期" value-format="YYYY-MM-DD" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="结束日期">
                  <el-date-picker v-model="backtestParams.end_date" type="date" placeholder="选择结束日期" value-format="YYYY-MM-DD" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="最大持有天数">
                  <el-input-number v-model="backtestParams.hold_days" :min="10" :max="120" :step="5" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="初始资金">
                  <el-input-number v-model="backtestParams.initial_capital" :min="10000" :max="100000000" :step="100000" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="32">
              <el-col :span="8">
                <el-form-item label="每次选前N只">
                  <el-input-number v-model="backtestParams.top_n" :min="1" :max="100" :step="1" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="单股最大仓位">
                  <el-input-number v-model="backtestParams.max_position_pct" :min="0.01" :max="1" :step="0.05" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>

            <div class="form-actions">
              <el-button type="success" :loading="backtestLoading" @click="doBacktest" size="large">
                <el-icon><TrendCharts /></el-icon>
                开始回测
              </el-button>
              <el-button :loading="backtestLoading" @click="resetBacktestParams" size="large">
                <el-icon><Refresh /></el-icon>
                重置参数
              </el-button>
            </div>
          </el-form>
        </el-card>

        <el-card v-if="!backtestResult && !backtestLoading" shadow="never">
          <el-empty description="配置回测参数后点击开始回测，回测可能耗时2-5分钟">
            <el-button type="success" @click="doBacktest">立即回测</el-button>
          </el-empty>
        </el-card>

        <el-card v-if="backtestLoading" shadow="never" v-loading="backtestLoading" element-loading-text="正在回测，请耐心等待（可能需要2-5分钟）...">
          <div style="height: 200px;"></div>
        </el-card>

        <div v-if="backtestResult">
          <el-row :gutter="16">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间所有买入信号触发的交易总数。每只股票每天只能买入一次，同一只股票不同日期会产生多笔交易。</div>
                  </template>
                  <div class="metric-label">总交易次数</div>
                </el-tooltip>
                <div class="metric-value">{{ backtestResult.total_trades }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">盈利交易数 ÷ 总交易数 × 100%。盈利定义为卖出价 > 买入价。胜率高不代表策略好，需要结合盈亏比分析。</div>
                  </template>
                  <div class="metric-label">胜率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.win_rate >= 50 ? 'up' : 'down'">
                  {{ backtestResult.win_rate.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">所有交易收益率的简单平均值。计算公式：(盈利交易收益 + 亏损交易收益) ÷ 总交易数。反映单笔交易的平均表现。</div>
                  </template>
                  <div class="metric-label">平均收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.avg_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.avg_return >= 0 ? '+' : '' }}{{ backtestResult.avg_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">从历史最高点到最低点的最大跌幅，按复利计算。计算公式：(最高点净值 - 当前净值) ÷ 最高点净值 × 100%。反映策略的最大风险暴露。</div>
                  </template>
                  <div class="metric-label">最大回撤</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.max_drawdown.toFixed(2) }}%</div>
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间的累计收益，按复利计算。计算公式：期末净值 ÷ 期初净值 - 1。期初净值=1，每天收益=当日选中股票平均收益。</div>
                  </template>
                  <div class="metric-label">总收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.total_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.total_return >= 0 ? '+' : '' }}{{ backtestResult.total_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">仅计算盈利交易的平均收益率。反映赚钱交易的平均盈利幅度。理想值应显著大于平均亏损的绝对值。</div>
                  </template>
                  <div class="metric-label">平均盈利</div>
                </el-tooltip>
                <div class="metric-value up">+{{ backtestResult.avg_win.toFixed(2) }}%</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">仅计算亏损交易的平均收益率（取负值）。反映亏钱交易的平均亏损幅度。策略能否盈利的关键：平均盈利 > 平均亏损 × 胜率补偿。</div>
                  </template>
                  <div class="metric-label">平均亏损</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.avg_loss.toFixed(2) }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间实际有交易的天数（不包含无信号的交易日）。总交易次数 ÷ 回测天数 = 日均交易笔数。</div>
                  </template>
                  <div class="metric-label">回测天数</div>
                </el-tooltip>
                <div class="metric-value">{{ backtestResult.backtest_days }}</div>
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">平均盈利 ÷ 平均亏损的绝对值。反映盈亏不对称性。>1表示赚的时候比亏的时候多，配合胜率评估策略质量。</div>
                  </template>
                  <div class="metric-label">盈亏比</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.profit_loss_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.profit_loss_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">年化超额收益 ÷ 年化波动率。衡量风险调整后收益。>1良好，>2优秀，>3卓越。</div>
                  </template>
                  <div class="metric-label">夏普比率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.sharpe_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.sharpe_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">年化收益 ÷ 最大回撤。衡量每承担1单位回撤能获得多少收益。>1良好，>3优秀。</div>
                  </template>
                  <div class="metric-label">卡玛比率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.calmar_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.calmar_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">按252个交易日年化后的收益率。便于不同周期的策略横向对比。</div>
                  </template>
                  <div class="metric-label">年化收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.annualized_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.annualized_return >= 0 ? '+' : '' }}{{ backtestResult.annualized_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">连续亏损交易的最大次数。反映策略的心理承受压力，连续亏损太多容易让人放弃。</div>
                  </template>
                  <div class="metric-label">最大连续亏损</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.max_consecutive_losses }} 次</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间所有交易的手续费和滑点估算。双边手续费0.1%+滑点0.3%。</div>
                  </template>
                  <div class="metric-label">手续费估算</div>
                </el-tooltip>
                <div class="metric-value down">¥{{ backtestResult.total_fees_est.toLocaleString() }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测结束时的总资产（现金 + 持仓市值清算后）。</div>
                  </template>
                  <div class="metric-label">最终资金</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.final_capital >= backtestResult.initial_capital ? 'up' : 'down'">
                  ¥{{ backtestResult.final_capital.toLocaleString() }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测开始时的初始资金。</div>
                  </template>
                  <div class="metric-label">初始资金</div>
                </el-tooltip>
                <div class="metric-value">¥{{ backtestResult.initial_capital.toLocaleString() }}</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-icon><TrendCharts /></el-icon>
                  <span class="panel-title">收益曲线</span>
                </div>
              </div>
            </template>
            <v-chart :option="equityCurveOption" style="height: 300px;" autoresize />
          </el-card>

          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="12">
              <el-card shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>信号类型统计</span>
                  </div>
                </template>
                <el-table :data="signalStatsList" stripe style="width: 100%">
                  <el-table-column prop="signal_type" label="信号类型" width="150">
                    <template #default="{ row }">
                      <el-tag :type="getSignalTypeTag(row.signal_type) as any" size="small">
                        {{ row.signal_type }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="count" label="交易次数" width="120" />
                  <el-table-column prop="win_rate" label="胜率" width="120">
                    <template #default="{ row }">
                      <span :class="['pct', row.win_rate >= 50 ? 'up' : 'down']">{{ row.win_rate.toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="avg_return" label="平均收益">
                    <template #default="{ row }">
                      <span :class="['pct', row.avg_return >= 0 ? 'up' : 'down']">
                        {{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>

            <el-col :span="12">
              <el-card shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>卖出原因统计</span>
                  </div>
                </template>
                <el-table :data="sellReasonStatsList" stripe style="width: 100%">
                  <el-table-column prop="sell_reason" label="卖出原因" width="180">
                    <template #default="{ row }">
                      <el-tag :type="getSellReasonTag(row.sell_reason) as any" size="small">
                        {{ row.sell_reason }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="count" label="交易次数" width="100" />
                  <el-table-column prop="win_rate" label="胜率" width="100">
                    <template #default="{ row }">
                      <span :class="['pct', row.win_rate >= 50 ? 'up' : 'down']">{{ row.win_rate.toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="avg_return" label="平均收益">
                    <template #default="{ row }">
                      <span :class="['pct', row.avg_return >= 0 ? 'up' : 'down']">
                        {{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <span>盈利最多 Top 20</span>
              </div>
            </template>
            <el-table :data="backtestResult.top_trades" stripe style="width: 100%" :height="backtestTableHeight" row-key="buy_date+code">
              <el-table-column prop="code" label="代码" width="80" />
              <el-table-column prop="name" label="名称" width="100" />
              <el-table-column prop="buy_date" label="买入日期" width="120" />
              <el-table-column prop="sell_date" label="卖出日期" width="120" />
              <el-table-column label="信号类型" width="100">
                <template #default="{ row }">
                  <el-tag :type="getSignalTypeTag(row.signal_type) as any" size="small">{{ row.signal_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="卖出原因" width="120">
                <template #default="{ row }">
                  <el-tag :type="getSellReasonTag(row.sell_reason) as any" size="small">{{ row.sell_reason }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="buy_price" label="买入价" width="100">
                <template #default="{ row }">{{ row.buy_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="100">
                <template #default="{ row }">{{ row.sell_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="120" sortable>
                <template #default="{ row }">
                  <span class="pct up">+{{ row.return_pct.toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="profit" label="盈利" width="120" sortable>
                <template #default="{ row }">
                  <span class="pct up">+{{ formatMoney(row.profit) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <span>亏损最多 Top 20</span>
              </div>
            </template>
            <el-table :data="backtestResult.worst_trades" stripe style="width: 100%" :height="backtestTableHeight" row-key="buy_date+code">
              <el-table-column prop="code" label="代码" width="80" />
              <el-table-column prop="name" label="名称" width="100" />
              <el-table-column prop="buy_date" label="买入日期" width="120" />
              <el-table-column prop="sell_date" label="卖出日期" width="120" />
              <el-table-column label="信号类型" width="100">
                <template #default="{ row }">
                  <el-tag :type="getSignalTypeTag(row.signal_type) as any" size="small">{{ row.signal_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="卖出原因" width="120">
                <template #default="{ row }">
                  <el-tag :type="getSellReasonTag(row.sell_reason) as any" size="small">{{ row.sell_reason }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="buy_price" label="买入价" width="100">
                <template #default="{ row }">{{ row.buy_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="100">
                <template #default="{ row }">{{ row.sell_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="120" sortable>
                <template #default="{ row }">
                  <span class="pct down">{{ row.return_pct.toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="profit" label="亏损" width="120" sortable>
                <template #default="{ row }">
                  <span class="pct down">{{ formatMoney(row.profit) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <RetailBuyDialog
      v-model:visible="buyDialogVisible"
      :code="buyTarget.code"
      :stock-name="buyTarget.stockName"
      :price="buyTarget.price"
      :strategy="buyTarget.strategy"
      @success="onBuySuccess"
    />
  </div>
</template>

<style scoped lang="scss">
.three-buys-three-sells-page {
  padding: 16px;
}

.page-header {
  margin-bottom: 20px;

  .page-title {
    font-size: 24px;
    font-weight: 600;
    margin: 0 0 8px 0;
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--el-text-color-primary);
  }

  .page-description {
    margin: 0;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }
}

.strategy-intro-collapse {
  margin-bottom: 0;
  :deep(.el-collapse-item__header) {
    height: 50px;
    font-weight: 500;
  }
  .collapse-title {
    display: flex; align-items: center; gap: 10px;
    font-size: 14px;
  }
  .strategy-cards {
    margin-bottom: 0;
  }
  .evolution-panel {
    border-radius: 8px;
    padding: 0;
  }
}

.strategy-card {
  text-align: center;
  border-radius: 8px;
  transition: transform 0.2s, box-shadow 0.2s;
  height: 100%;

  :deep(.el-card__body) {
    padding: 16px 12px;
  }

  &:hover {
    transform: translateY(-4px);
  }
}

.strategy-card-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 2px solid;
  margin-bottom: 10px;
}

.strategy-icon {
  font-size: 22px;
}

.strategy-type {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.strategy-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.strategy-card-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  text-align: left;
}

.evolution-panel {
  border-radius: 8px;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.evolution-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 8px 0;
}

.evolution-step {
  display: flex;
  gap: 16px;
  padding: 12px 0;
  position: relative;
}

.step-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 40px;
}

.step-dot {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  z-index: 1;

  &.phase-1 { background: linear-gradient(135deg, #f56c6c, #e6a23c); }
  &.phase-2 { background: linear-gradient(135deg, #67c23a, #85ce61); }
  &.phase-3 { background: linear-gradient(135deg, #409eff, #66b1ff); }
  &.phase-4 { background: linear-gradient(135deg, #e6a23c, #f0c78a); }
  &.phase-5 { background: linear-gradient(135deg, #f56c6c, #e6a23c); }
  &.phase-6 { background: linear-gradient(135deg, #909399, #606266); }
}

.step-line {
  width: 2px;
  flex: 1;
  min-height: 30px;
  background: linear-gradient(to bottom, var(--el-border-color-light), var(--el-border-color-lighter));
}

.step-content {
  flex: 1;
  min-width: 0;
  padding-top: 8px;
}

.step-phase-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.step-phase {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.step-signals {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.step-signal-tag {
  margin: 0;
}

.step-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  margin-bottom: 10px;
}

.step-action {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  border-left: 3px solid var(--el-color-primary);

  .step-action-text {
    font-size: 12px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
  }
}

.step-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.step-meta-tag {
  margin: 0;
}

.params-panel {
  border-radius: 8px;
}

.params-form {
  :deep(.el-form-item) {
    margin-bottom: 18px;
  }

  :deep(.el-form-item__label) {
    font-weight: 500;
    color: var(--el-text-color-regular);
  }
}

.form-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.result-panel {
  border-radius: 8px;
}

.empty-state,
.loading-state {
  padding: 60px 0;
}

.stock-code,
.stock-name {
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 13px;

  &:hover {
    text-decoration: underline;
  }
}

.price {
  font-family: 'Monaco', 'Consolas', monospace;
  font-weight: 500;
}

.pct {
  font-family: 'Monaco', 'Consolas', monospace;

  &.up {
    color: var(--el-color-danger);
  }
  &.down {
    color: var(--el-color-success);
  }
}

.table-link {
  color: var(--el-color-primary);
  cursor: pointer;
  margin-right: 8px;
  font-size: 13px;

  &:hover {
    text-decoration: underline;
  }
}

.empty-tag {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}

.metric-card {
  text-align: center;
  border-radius: 8px;

  :deep(.el-card__body) {
    padding: 16px 12px;
  }

  .metric-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
    margin-bottom: 10px;
  }

  .metric-value {
    font-size: 24px;
    font-weight: 700;
    font-family: 'Monaco', 'Consolas', monospace;
    letter-spacing: -0.5px;

    &.up {
      color: var(--el-color-danger);
    }
    &.down {
      color: var(--el-color-success);
    }
  }
}

.date-range {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}

.date-item {
  color: var(--el-text-color-primary);
}

.date-arrow {
  color: var(--el-text-color-placeholder);
}

.date-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;

  &.success {
    background: var(--el-color-success-light-9);
    color: var(--el-color-success);
  }
  &.warning {
    background: var(--el-color-warning-light-9);
    color: var(--el-color-warning);
  }
  &.info {
    background: var(--el-color-info-light-9);
    color: var(--el-color-info);
  }
}

.tooltip-detail {
  font-size: 13px;
  line-height: 1.5;
  max-width: 300px;
}

.help-icon {
  margin-left: 4px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;

  &:hover {
    color: var(--el-color-primary);
  }
}

.radar-card, .score-stats-card {
  height: 100%;
}

.score-cell {
  cursor: pointer;
  .score-hint {
    display: block;
    font-size: 10px;
    color: #909399;
    margin-top: 2px;
    text-align: center;
  }
}

.score-detail-popover {
  .score-detail-title {
    font-weight: 600;
    font-size: 13px;
    margin-bottom: 8px;
    color: var(--el-text-color-primary);
  }
  .score-radar-wrap {
    margin-bottom: 12px;
    border-bottom: 1px solid var(--el-border-color-lighter);
    padding-bottom: 8px;
  }
  .score-detail-list {
    max-height: 240px;
    overflow-y: auto;
  }
  .score-detail-text-item {
    font-size: 12px;
    color: var(--el-text-color-regular);
    margin-bottom: 4px;
    line-height: 1.5;
  }
  .score-detail-empty {
    font-size: 12px;
    color: #909399;
    text-align: center;
    padding: 8px 0;
  }
}

.stat-item {
  text-align: center;
  padding: 16px 0;
  .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--el-color-primary);
    margin-bottom: 4px;
  }
  .stat-label {
    font-size: 12px;
    color: #909399;
  }
}
</style>
