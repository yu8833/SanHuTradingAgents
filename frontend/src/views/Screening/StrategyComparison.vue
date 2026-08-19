<template>
  <div class="strategy-comparison">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">策略对比</h2>
          <p class="page-hero-sub">
            选择多个策略进行回测对比，直观了解各策略的收益风险特征
          </p>
        </div>
      </div>
    </div>

    <el-card class="strategy-select-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <el-icon><List /></el-icon>
            <span class="panel-title">选择策略</span>
            <el-tag type="info" size="small" effect="plain">选择 2-3 个策略进行对比</el-tag>
          </div>
        </div>
      </template>

      <el-row :gutter="16">
        <el-col :span="8" v-for="strategy in strategyList" :key="strategy.key">
          <div
            class="strategy-card"
            :class="{ active: selectedStrategies.includes(strategy.key) }"
            @click="toggleStrategy(strategy.key)"
          >
            <el-checkbox
              :model-value="selectedStrategies.includes(strategy.key)"
              :label="strategy.key"
              @change.stop
              class="strategy-checkbox"
            >
              <div class="strategy-icon" :class="strategy.iconClass">
                <el-icon><component :is="strategy.icon" /></el-icon>
              </div>
              <div class="strategy-info">
                <h3>{{ strategy.name }}</h3>
                <p>{{ strategy.description }}</p>
              </div>
            </el-checkbox>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card class="params-panel" shadow="never" style="margin-top: 16px;">
      <template #header>
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <el-icon><DataLine /></el-icon>
            <span class="panel-title">回测参数配置</span>
          </div>
          <div class="header-actions">
            <el-button type="text" @click="resetParams">
              <el-icon><Refresh /></el-icon>
              重置
            </el-button>
          </div>
        </div>
      </template>

      <el-form :model="params" label-position="top" size="default" class="params-form">
        <el-row :gutter="24">
          <el-col :span="5">
            <el-form-item label="开始日期">
              <el-date-picker
                v-model="params.start_date"
                type="date"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                placeholder="选择开始日期"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="5">
            <el-form-item label="结束日期">
              <el-date-picker
                v-model="params.end_date"
                type="date"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                placeholder="选择结束日期"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="初始资金 (万)">
              <el-input-number
                v-model="params.initial_capital"
                :min="10000"
                :max="10000000"
                :step="10000"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="持有天数">
              <el-input-number
                v-model="params.hold_days"
                :min="1"
                :max="60"
                :step="1"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="选前 N 只">
              <el-input-number
                v-model="params.top_n"
                :min="1"
                :max="50"
                :step="1"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="2">
            <el-form-item label="&nbsp;">
              <el-button
                type="primary"
                :loading="loading"
                :disabled="!canStartComparison"
                @click="startComparison"
                style="width: 100%;"
              >
                <el-icon><TrendCharts /></el-icon>
                开始对比
              </el-button>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <div v-if="loading" style="margin-top: 16px;">
      <el-card shadow="never" v-loading="loading" element-loading-text="正在并行回测，请耐心等待（可能需要5-10分钟）...">
        <div style="height: 200px;"></div>
      </el-card>
    </div>

    <div v-if="hasResults" style="margin-top: 16px;">
      <el-card shadow="never" class="comparison-table-card">
        <template #header>
          <div class="card-header">
            <div style="display: flex; align-items: center; gap: 12px;">
              <el-icon><DataLine /></el-icon>
              <span class="panel-title">关键指标对比</span>
            </div>
          </div>
        </template>

        <el-table :data="metricRows" stripe style="width: 100%" class="app-table app-table--compact">
          <el-table-column prop="metric" label="指标" width="140" fixed="left" />
          <el-table-column
            v-for="strategyKey in selectedStrategies"
            :key="strategyKey"
            :label="getStrategyName(strategyKey)"
            align="right"
            sortable
          >
            <template #default="{ row }">
              <span :class="getValueClass(row.metric, row[strategyKey])">
                {{ formatValue(row.metric, row[strategyKey]) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="chart-card" style="margin-top: 16px;">
        <template #header>
          <div class="card-header">
            <div style="display: flex; align-items: center; gap: 12px;">
              <el-icon><TrendCharts /></el-icon>
              <span class="panel-title">收益曲线对比</span>
            </div>
          </div>
        </template>
        <v-chart :option="chartOption" style="height: 450px;" autoresize />
      </el-card>

      <el-card shadow="never" class="analysis-card" style="margin-top: 16px;">
        <template #header>
          <div class="card-header">
            <div style="display: flex; align-items: center; gap: 12px;">
              <el-icon><MagicStick /></el-icon>
              <span class="panel-title">策略优劣分析</span>
            </div>
          </div>
        </template>

        <el-row :gutter="16">
          <el-col :span="12" v-for="strategyKey in selectedStrategies" :key="strategyKey">
            <div class="strategy-analysis">
              <div class="analysis-header">
                <el-icon :color="getStrategyColor(strategyKey)"><CircleCheckFilled /></el-icon>
                <span class="analysis-title">{{ getStrategyName(strategyKey) }}</span>
              </div>
              <div class="analysis-content">
                <div class="analysis-item">
                  <span class="analysis-label">优势：</span>
                  <span class="analysis-value">{{ getStrategyAdvantages(strategyKey) }}</span>
                </div>
                <div class="analysis-item">
                  <span class="analysis-label">劣势：</span>
                  <span class="analysis-value">{{ getStrategyDisadvantages(strategyKey) }}</span>
                </div>
                <div class="analysis-item">
                  <span class="analysis-label">适用场景：</span>
                  <span class="analysis-value">{{ getStrategyScenario(strategyKey) }}</span>
                </div>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>
    </div>

    <el-card v-else-if="!loading" shadow="never" style="margin-top: 16px;">
      <el-empty description="选择 2-3 个策略，配置参数后点击开始对比">
        <el-button type="primary" :disabled="!canStartComparison" @click="startComparison">
          开始对比
        </el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'StrategyComparison' })

import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  InfoFilled,
  Refresh,
  Search,
  List,
  DataLine,
  DataAnalysis,
  MagicStick,
  CircleCheckFilled,
  Lightning,
  Wallet,
  ShoppingCart,
  Histogram,
  Money
} from '@element-plus/icons-vue'
import { screeningApi, type RetailBacktestResp, type LimitUpPullbackBacktestResp, type ThreeBuysThreeSellsBacktestResp } from '@/api/screening'

type StrategyKey = 'extreme_reversal' | 'small_cap_value' | 'turnaround' | 'convertible_arbitrage' | 'limit_up_pullback' | 'three_buys_three_sells' | 'ma_crossover' | 'macd_divergence' | 'volume_price'
type BacktestResult = RetailBacktestResp | LimitUpPullbackBacktestResp | ThreeBuysThreeSellsBacktestResp

interface StrategyInfo {
  key: StrategyKey
  name: string
  description: string
  icon: any
  iconClass: string
}

const strategyList: StrategyInfo[] = [
  { key: 'extreme_reversal', name: '极端反转', description: '连续跌停后博弈超跌反弹', icon: Lightning, iconClass: 'extreme' },
  { key: 'small_cap_value', name: '小盘价值', description: '小市值低估值价值投资', icon: Wallet, iconClass: 'value' },
  { key: 'turnaround', name: '困境反转', description: '基本面拐点反转机会', icon: DataAnalysis, iconClass: 'turnaround' },
  { key: 'convertible_arbitrage', name: '转债下修', description: '可转债下修博弈策略', icon: ShoppingCart, iconClass: 'convertible' },
  { key: 'limit_up_pullback', name: '涨停回调', description: '涨停后缩量回调买入', icon: Histogram, iconClass: 'limitup' },
  { key: 'three_buys_three_sells', name: '三买三卖', description: '趋势跟踪三买三卖法', icon: Money, iconClass: 'threebuys' },
  { key: 'ma_crossover', name: '均线交叉', description: '金叉死叉趋势跟踪策略', icon: DataLine, iconClass: 'macrossover' },
  { key: 'macd_divergence', name: 'MACD背离', description: '顶底背离反转信号识别', icon: TrendCharts, iconClass: 'macd' },
  { key: 'volume_price', name: '量价配合', description: '量价关系趋势确认', icon: InfoFilled, iconClass: 'volumeprice' }
]

const strategyColors: Record<StrategyKey, string> = {
  extreme_reversal: '#F56C6C',
  small_cap_value: '#67C23A',
  turnaround: '#E6A23C',
  convertible_arbitrage: '#909399',
  limit_up_pullback: '#2b6cb0',
  three_buys_three_sells: '#8E44AD',
  ma_crossover: '#00CED1',
  macd_divergence: '#FF69B4',
  volume_price: '#20B2AA'
}

const selectedStrategies = ref<StrategyKey[]>([])
const loading = ref(false)
const results = ref<Record<string, BacktestResult>>({})

const params = reactive({
  start_date: '2023-01-01',
  end_date: '2024-12-31',
  initial_capital: 100000,
  hold_days: 5,
  top_n: 10
})

const defaultParams = { ...params }

const canStartComparison = computed(() => selectedStrategies.value.length >= 2 && selectedStrategies.value.length <= 3)

const hasResults = computed(() => Object.keys(results.value).length > 0)

function toggleStrategy(key: StrategyKey) {
  const index = selectedStrategies.value.indexOf(key)
  if (index > -1) {
    selectedStrategies.value.splice(index, 1)
  } else {
    if (selectedStrategies.value.length >= 3) {
      ElMessage.warning('最多选择 3 个策略进行对比')
      return
    }
    selectedStrategies.value.push(key)
  }
}

function resetParams() {
  Object.assign(params, defaultParams)
  ElMessage.info('参数已重置')
}

function getStrategyName(key: string): string {
  const s = strategyList.find(s => s.key === key)
  return s?.name || key
}

function getStrategyColor(key: string): string {
  return strategyColors[key as StrategyKey] || '#2b6cb0'
}

const metricDefinitions = [
  { key: 'total_return', label: '总收益', isPercent: true, higherIsBetter: true },
  { key: 'annualized_return', label: '年化收益', isPercent: true, higherIsBetter: true },
  { key: 'win_rate', label: '胜率', isPercent: true, higherIsBetter: true },
  { key: 'profit_loss_ratio', label: '盈亏比', isPercent: false, higherIsBetter: true },
  { key: 'sharpe_ratio', label: '夏普比率', isPercent: false, higherIsBetter: true },
  { key: 'max_drawdown', label: '最大回撤', isPercent: true, higherIsBetter: false },
  { key: 'calmar_ratio', label: '卡尔曼比率', isPercent: false, higherIsBetter: true },
  { key: 'total_trades', label: '交易次数', isPercent: false, higherIsBetter: null }
]

const metricRows = computed(() => {
  return metricDefinitions.map(metric => {
    const row: Record<string, any> = { metric: metric.label }
    selectedStrategies.value.forEach(key => {
      const result = results.value[key]
      if (result) {
        row[key] = (result as any)[metric.key]
      }
    })
    return row
  })
})

function formatValue(metricLabel: string, value: any): string {
  if (value === null || value === undefined) return '-'
  const metric = metricDefinitions.find(m => m.label === metricLabel)
  if (!metric) return String(value)
  if (metric.isPercent) {
    return (value >= 0 ? '+' : '') + value.toFixed(2) + '%'
  }
  if (typeof value === 'number') {
    return value.toFixed(2)
  }
  return String(value)
}

function getValueClass(metricLabel: string, value: any): string {
  if (value === null || value === undefined) return ''
  const metric = metricDefinitions.find(m => m.label === metricLabel)
  if (!metric || metric.higherIsBetter === null) return ''
  if (metric.higherIsBetter) {
    return value >= 0 ? 'up' : 'down'
  } else {
    return value < 0 ? 'up' : 'down'
  }
}

const chartOption = computed(() => {
  const legend = selectedStrategies.value.map(key => getStrategyName(key))
  
  const series = selectedStrategies.value.map(key => {
    const result = results.value[key]
    const dailyResults = (result as any)?.daily_results || []
    const initialCapital = result?.initial_capital || 100000
    
    const data = dailyResults.map((d: any) => {
      const returnPct = ((d.total_value - initialCapital) / initialCapital) * 100
      return returnPct
    })

    return {
      name: getStrategyName(key),
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2 },
      itemStyle: { color: getStrategyColor(key) },
      data: data
    }
  })

  const dates = (() => {
    const firstKey = selectedStrategies.value[0]
    const firstResult = results.value[firstKey]
    const dailyResults = (firstResult as any)?.daily_results || []
    return dailyResults.map((d: any) => d.date)
  })()

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let result = params[0].axisValueLabel + '<br/>'
        params.forEach((item: any) => {
          result += `${item.marker} ${item.seriesName}: ${item.value >= 0 ? '+' : ''}${item.value.toFixed(2)}%<br/>`
        })
        return result
      }
    },
    legend: {
      data: legend,
      top: 10
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: 60,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLabel: { rotate: 45, fontSize: 10 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%' }
    },
    series: series
  }
})

function getStrategyAdvantages(key: string): string {
  const result = results.value[key]
  if (!result) return '-'
  
  const advantages: string[] = []
  const r = result as any
  
  if (r.total_return > 20) advantages.push('收益强劲')
  if (r.win_rate > 60) advantages.push('胜率高')
  if (r.profit_loss_ratio > 1.5) advantages.push('盈亏比优秀')
  if (r.sharpe_ratio > 1.5) advantages.push('风险调整收益好')
  if (r.max_drawdown < 15) advantages.push('回撤控制好')
  
  return advantages.length > 0 ? advantages.join('、') : '表现中等'
}

function getStrategyDisadvantages(key: string): string {
  const result = results.value[key]
  if (!result) return '-'
  
  const disadvantages: string[] = []
  const r = result as any
  
  if (r.total_return < 5) disadvantages.push('收益偏低')
  if (r.win_rate < 45) disadvantages.push('胜率偏低')
  if (r.profit_loss_ratio < 1) disadvantages.push('盈亏比不佳')
  if (r.sharpe_ratio < 0.5) disadvantages.push('风险调整收益差')
  if (r.max_drawdown > 30) disadvantages.push('回撤较大')
  
  return disadvantages.length > 0 ? disadvantages.join('、') : '暂无明显劣势'
}

function getStrategyScenario(key: string): string {
  const scenarios: Record<string, string> = {
    extreme_reversal: '市场恐慌下跌后的超跌反弹行情',
    small_cap_value: '震荡市、价值风格占优时',
    turnaround: '行业景气度回升、公司基本面改善阶段',
    convertible_arbitrage: '熊市末期、震荡市，追求稳健收益',
    limit_up_pullback: '牛市及结构性行情中强势股回调',
    three_buys_three_sells: '趋势明确的单边行情',
    ma_crossover: '趋势行情中的金叉买入、死叉卖出',
    macd_divergence: '趋势末端的反转信号识别',
    volume_price: '量价配合的趋势确认和追涨'
  }
  return scenarios[key] || '-'
}

async function startComparison() {
  if (!canStartComparison.value) {
    ElMessage.warning('请选择 2-3 个策略')
    return
  }
  
  if (!params.start_date || !params.end_date) {
    ElMessage.warning('请选择回测开始和结束日期')
    return
  }
  
  loading.value = true
  results.value = {}
  
  try {
    const promises = selectedStrategies.value.map(key => runBacktest(key))
    const resultsArray = await Promise.all(promises)
    
    selectedStrategies.value.forEach((key, index) => {
      if (resultsArray[index]) {
        results.value[key] = resultsArray[index]!
      }
    })
    
    const successCount = resultsArray.filter(r => r !== null).length
    ElMessage.success(`对比完成，成功回测 ${successCount}/${selectedStrategies.value.length} 个策略`)
  } catch (e: any) {
    ElMessage.error(e?.message || '对比失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// retail策略走retail_screening_base.py，百分比返回的是小数(0.55=55%)
// 涨停回调/三买三卖走自己的service，百分比已×100(55.0=55%)
// 这里统一归一化为×100的百分比格式
const retailStrategyKeys: StrategyKey[] = ['extreme_reversal', 'small_cap_value', 'turnaround', 'convertible_arbitrage', 'ma_crossover', 'macd_divergence', 'volume_price']

function normalizeBacktestResult(key: StrategyKey, result: any): any {
  if (!retailStrategyKeys.includes(key)) return result
  // 对retail策略的百分比值×100
  const percentFields = ['win_rate', 'avg_return', 'avg_win', 'avg_loss', 'total_return', 'max_drawdown', 'annualized_return']
  const normalized = { ...result }
  percentFields.forEach(field => {
    if (typeof normalized[field] === 'number') {
      normalized[field] = normalized[field] * 100
    }
  })
  // 交易记录里的return_pct也×100
  if (normalized.top_trades) {
    normalized.top_trades = normalized.top_trades.map((t: any) => ({ ...t, return_pct: t.return_pct * 100 }))
  }
  if (normalized.worst_trades) {
    normalized.worst_trades = normalized.worst_trades.map((t: any) => ({ ...t, return_pct: t.return_pct * 100 }))
  }
  // sell_reason_stats里的win_rate和avg_return也×100
  if (normalized.sell_reason_stats) {
    const stats: any = {}
    Object.entries(normalized.sell_reason_stats).forEach(([reason, v]: [string, any]) => {
      stats[reason] = { ...v, win_rate: v.win_rate * 100, avg_return: v.avg_return * 100 }
    })
    normalized.sell_reason_stats = stats
  }
  return normalized
}

async function runBacktest(key: StrategyKey): Promise<BacktestResult | null> {
  try {
    const payload = { ...params }
    
    let result: any = null
    switch (key) {
      case 'extreme_reversal':
        result = await screeningApi.backtestExtremeReversal(payload)
        break
      case 'small_cap_value':
        result = await screeningApi.backtestSmallCapValue(payload)
        break
      case 'turnaround':
        result = await screeningApi.backtestTurnaround(payload)
        break
      case 'convertible_arbitrage':
        result = await screeningApi.backtestConvertibleArbitrage(payload)
        break
      case 'limit_up_pullback':
        result = await screeningApi.backtestLimitUpPullback(payload)
        break
      case 'three_buys_three_sells':
        result = await screeningApi.backtestThreeBuysThreeSells(payload)
        break
      case 'ma_crossover':
        result = await screeningApi.backtestMaCrossover(payload)
        break
      case 'macd_divergence':
        result = await screeningApi.backtestMacdDivergence(payload)
        break
      case 'volume_price':
        result = await screeningApi.backtestVolumePrice(payload)
        break
      default:
        return null
    }
    return normalizeBacktestResult(key, result) as BacktestResult
  } catch (e: any) {
    console.error(`策略 ${key} 回测失败:`, e)
    ElMessage.error(`${getStrategyName(key)} 回测失败: ${e?.message || '未知错误'}`)
    return null
  }
}
</script>

<style lang="scss" scoped>
.strategy-comparison {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

  .panel-title {
    font-size: 16px;
    font-weight: 600;
  }

  .header-actions {
    display: flex;
    gap: 8px;
  }
}

.strategy-select-panel {
  .strategy-card {
    border: 2px solid var(--el-border-color);
    border-radius: 12px;
    padding: 16px;
    cursor: pointer;
    transition: all 0.3s ease;
    background: var(--el-bg-color);

    &:hover {
      border-color: var(--el-color-primary-light-5);
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    &.active {
      border-color: var(--el-color-primary);
      background: var(--el-color-primary-light-9);
    }
  }

  .strategy-checkbox {
    width: 100%;

    :deep(.el-checkbox__label) {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 12px;
      padding-left: 8px;
    }
  }

  .strategy-icon {
    width: 48px;
    height: 48px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    color: #fff;
    flex-shrink: 0;

    &.extreme { background: linear-gradient(135deg, #F56C6C, #E74C3C); }
    &.value { background: linear-gradient(135deg, #67C23A, #27AE60); }
    &.turnaround { background: linear-gradient(135deg, #E6A23C, #F39C12); }
    &.convertible { background: linear-gradient(135deg, #909399, #7F8C8D); }
    &.limitup { background: linear-gradient(135deg, #2b6cb0, #22568d); }
    &.threebuys { background: linear-gradient(135deg, #8E44AD, #9B59B6); }

    .el-icon {
      font-size: 24px;
    }
  }

  .strategy-info {
    flex: 1;

    h3 {
      margin: 0 0 4px 0;
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    p {
      margin: 0;
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }
}

.params-panel {
  .params-form {
    :deep(.el-form-item) {
      margin-bottom: 0;
    }
  }
}

.comparison-table-card {
  .up {
    color: var(--el-color-success);
    font-weight: 500;
  }

  .down {
    color: var(--el-color-danger);
    font-weight: 500;
  }
}

.analysis-card {
  .strategy-analysis {
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
    padding: 16px;
    background: var(--el-bg-color-page);

    &:hover {
      border-color: var(--el-border-color-light);
    }
  }

  .analysis-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;

    .el-icon {
      font-size: 20px;
    }

    .analysis-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }
  }

  .analysis-content {
    .analysis-item {
      margin-bottom: 8px;
      font-size: 14px;
      line-height: 1.6;

      &:last-child {
        margin-bottom: 0;
      }
    }

    .analysis-label {
      color: var(--el-text-color-secondary);
      font-weight: 500;
    }

    .analysis-value {
      color: var(--el-text-color-primary);
    }
  }
}
</style>