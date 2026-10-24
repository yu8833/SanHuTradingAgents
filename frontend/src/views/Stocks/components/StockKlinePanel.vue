<template>
  <el-card shadow="hover" class="kline-card">
    <template #header>
      <div class="kline-hd">
        <div class="kline-title">
          K线走势
          <el-tooltip content="价格K线与成交量同图联动。前复权：以最新价为基准还原历史除权除息缺口，适合看均线和技术形态；不复权：显示当日真实成交价。" placement="top">
            <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <div class="kline-controls">
          <el-segmented v-model="period" :options="periodOptions" size="small" />
          <el-segmented v-model="adj" :options="adjOptions" size="small" />
        </div>
      </div>
    </template>

    <div v-loading="loading" class="kline-body">
      <v-chart v-if="option" class="kline-chart" :option="option" autoresize />
      <el-empty v-else-if="!loading" :description="error || '暂无K线数据'" :image-size="60" />
    </div>

    <div v-if="option" class="kline-foot">
      {{ periodLabel }} · {{ adjLabel }} · 数据源 {{ sourceLabel }} · 最近 {{ lastTime || '-' }} · 收 {{ fmtPrice(lastClose) }}
      <el-tooltip v-if="adjNote" :content="adjNote" placement="top">
        <el-icon class="foot-warn"><WarningFilled /></el-icon>
      </el-tooltip>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use as echartsUse } from 'echarts/core'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { QuestionFilled, WarningFilled } from '@element-plus/icons-vue'
import { stocksApi } from '@/api/stocks'
import { fmtPrice } from '@/utils/format'

echartsUse([CandlestickChart, LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  code: string
  signals?: Array<{ type: string; type_label?: string; stop_loss_price?: number }>
  triggerDate?: string | null
  stopLoss?: number | null
}>()

const periodOptions = [
  { label: '日K', value: 'day' },
  { label: '周K', value: 'week' },
  { label: '月K', value: 'month' }
]
const adjOptions = [
  { label: '前复权', value: 'qfq' },
  { label: '不复权', value: 'none' }
]

const period = ref<'day' | 'week' | 'month'>('day')
const adj = ref<'qfq' | 'none'>('qfq')
const loading = ref(false)
const error = ref('')
const source = ref<string | undefined>(undefined)
const effectiveAdj = ref<'qfq' | 'none'>('qfq')
const adjNote = ref('')
const option = ref<EChartsOption | null>(null)
const lastTime = ref<string | null>(null)
const lastClose = ref<number>(NaN)

const periodLabel = computed(() => periodOptions.find(p => p.value === period.value)?.label || '日K')
const adjLabel = computed(() => {
  const base = effectiveAdj.value === 'qfq' ? '前复权' : '不复权'
  return adjNote.value ? `${base}*` : base
})
const sourceLabel = computed(() => {
  const s = String(source.value || '')
  if (!s) return '-'
  if (s.startsWith('mongodb(daily→week)')) return '本地库·日线聚合'
  if (s.startsWith('mongodb(daily→month)')) return '本地库·日线聚合'
  if (s.startsWith('mongodb')) return '本地库'
  return s
})

let seq = 0

function normalizeDate(v: string): string {
  return String(v || '').replace(/-/g, '')
}

function calculateMA(series: any[], n: number): Array<number | null> {
  return series.map((_, i) => {
    if (i < n - 1) return null
    let sum = 0
    for (let j = i - n + 1; j <= i; j++) sum += Number(series[j]?.close ?? 0)
    return sum / n
  })
}

function buildOption(items: any[]) {
  const dates = items.map((s: any) => String(s.time || s.trade_time || s.trade_date || ''))
  const klineData = items.map((s: any) => [Number(s.open ?? NaN), Number(s.close ?? NaN), Number(s.low ?? NaN), Number(s.high ?? NaN)])
  const volData = items.map((s: any) => ({
    value: Number(s.volume ?? 0),
    itemStyle: { color: Number(s.close ?? 0) >= Number(s.open ?? 0) ? '#f56c6c' : '#67c23a' }
  }))

  const markLines: any[] = []
  const target = normalizeDate(props.triggerDate || '')
  if (target) {
    const date = dates.find(d => normalizeDate(d) === target)
    if (date) {
      const isBuy = (props.signals || []).some(s => String(s.type).startsWith('B'))
      markLines.push({
        xAxis: date,
        label: { formatter: isBuy ? '信号·买' : '信号·卖', fontSize: 10 },
        lineStyle: { color: isBuy ? '#f56c6c' : '#67c23a', type: 'dashed', width: 1 }
      })
    }
  }
  const stop = Number(props.stopLoss)
  if (Number.isFinite(stop) && stop > 0) {
    markLines.push({
      yAxis: stop,
      label: { formatter: `止损 ${stop}`, fontSize: 10, position: 'insideEndTop' },
      lineStyle: { color: '#ef4444', type: 'dashed', width: 1 }
    })
  }

  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', 'MA5', 'MA20', 'MA60', '成交量'], top: 0, left: 0, textStyle: { fontSize: 11 } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 48, right: 16, top: 24, height: '58%' },
      { left: 48, right: 16, top: '72%', height: '18%' }
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false }, axisLabel: { fontSize: 10 } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false }, axisTick: { show: false } }
    ],
    yAxis: [
      { scale: true, type: 'value', axisLabel: { fontSize: 10 } },
      {
        gridIndex: 1,
        scale: true,
        type: 'value',
        axisLabel: {
          fontSize: 10,
          formatter: (v: number) => v >= 1e8 ? (v / 1e8).toFixed(1) + '亿' : v >= 1e4 ? (v / 1e4).toFixed(0) + '万' : String(v)
        }
      }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 65, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 65, end: 100, height: 16, bottom: 4 }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: klineData,
        itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' },
        markLine: markLines.length
          ? { symbol: 'none', silent: true, data: markLines }
          : undefined
      },
      { name: 'MA5', type: 'line', data: calculateMA(items, 5), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f97316' } },
      { name: 'MA20', type: 'line', data: calculateMA(items, 20), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
      { name: 'MA60', type: 'line', data: calculateMA(items, 60), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#2b6cb0' } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volData }
    ]
  } as EChartsOption
}

async function load() {
  if (!props.code) return
  const cur = ++seq
  loading.value = true
  error.value = ''
  try {
    const res = await stocksApi.getKline(props.code, period.value, 240, adj.value)
    if (cur !== seq) return
    const d: any = (res as any)?.data || {}
    const items: any[] = Array.isArray(d.items) ? d.items : []
    source.value = d.source
    effectiveAdj.value = d.adj === 'qfq' ? 'qfq' : 'none'
    adjNote.value = String(d.adj_note || '')
    if ((adj.value !== 'none') !== (effectiveAdj.value !== 'none')) {
      // 请求了复权但后端降级为不复权（或反之），需提示用户口径变化
      adjNote.value = adjNote.value || '当前数据未做复权处理'
    }
    if (!items.length) {
      option.value = null
      error.value = '暂无K线数据'
      return
    }
    lastTime.value = String(items[items.length - 1]?.time || items[items.length - 1]?.trade_date || '')
    lastClose.value = Number(items[items.length - 1]?.close ?? NaN)
    option.value = buildOption(items)
  } catch (e) {
    if (cur === seq) {
      option.value = null
      error.value = 'K线数据加载失败，请稍后重试'
    }
  } finally {
    if (cur === seq) loading.value = false
  }
}

watch([() => props.code, period, adj], load, { immediate: true })

defineExpose({ reload: load })
</script>

<style scoped lang="scss">
.kline-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.kline-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.kline-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
}

.kline-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.help-icon-inline {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  cursor: help;
}

.kline-body {
  min-height: 320px;
}

.kline-chart {
  width: 100%;
  height: 420px;
}

.kline-foot {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.foot-warn {
  margin-left: 4px;
  font-size: 12px;
  color: var(--el-color-warning);
  cursor: help;
  vertical-align: -1px;
}

@media (max-width: 768px) {
  .kline-hd {
    flex-direction: column;
    align-items: flex-start;
  }
  .kline-chart {
    height: 280px;
  }
  .kline-body {
    min-height: 220px;
  }
}
</style>
