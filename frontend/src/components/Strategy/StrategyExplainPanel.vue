<template>
  <div class="dashboard-container explain-panel" v-loading="strategyLoading">
    <!-- 1. 大盘×策略 静态适配矩阵（纯规则，无日期；当日情形见作战室盘前） -->
    <el-card shadow="never" class="dashboard-card market-overview-card">
      <template #header>
        <div class="card-header">
          <el-icon><TrendCharts /></el-icon>
          <span class="panel-title">大盘×策略适配矩阵</span>
          <span class="header-hint">静态规则：选择环境组合 → 查看适配策略（数据来自后端策略注册表）</span>
        </div>
      </template>
      <el-row :gutter="16" class="matrix-dims">
        <el-col :span="6" v-for="d in matrixDims" :key="d.key">
          <div class="matrix-dim">
            <div class="matrix-dim-label">{{ d.label }}</div>
            <div class="matrix-dim-opts">
              <el-check-tag
                v-for="opt in d.options" :key="opt"
                :checked="regimeDims[d.key as keyof typeof regimeDims] === opt"
                @change="() => onPickDim(d.key, opt)"
              >{{ opt }}</el-check-tag>
            </div>
          </div>
        </el-col>
      </el-row>
      <el-divider />
      <div class="matrix-result">
        <div class="matrix-portrait">
          <span class="matrix-portrait-label">当前组合画像</span>
          <el-tag type="warning" effect="dark" size="large">{{ matchedPortrait }}</el-tag>
          <span class="matrix-portrait-desc">{{ portraitDesc }}</span>
        </div>
        <div class="matrix-strategies">
          <div class="matrix-strategies-hint">适配策略（{{ recommendedStrategies.length }}）——</div>
          <el-empty v-if="!recommendedStrategies.length" description="无匹配策略（全适用策略兜底）" :image-size="60" />
          <el-row v-else :gutter="12">
            <el-col :span="12" v-for="s in recommendedStrategies" :key="s.id" :style="{ marginBottom: '10px' }">
              <div class="matrix-strategy-card">
                <div class="matrix-strategy-head">
                  <span class="matrix-strategy-icon">{{ (s.frontend && s.frontend.icon) || '📊' }}</span>
                  <span class="matrix-strategy-name">{{ s.name }}</span>
                  <el-tag v-if="s.source === 'retail'" size="small" type="primary" effect="plain">零售</el-tag>
                  <el-tag v-else-if="s.source === 'template'" size="small" type="info" effect="plain">对话/辅助信号</el-tag>
                </div>
                <div class="matrix-strategy-desc">{{ s.description }}</div>
                <div v-if="s.buy_rules && s.buy_rules.length" class="matrix-strategy-rules">
                  <span class="matrix-rule-buy">买：{{ s.buy_rules[0] }}</span>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
      </div>
    </el-card>

    <!-- 2. 策略快速入口 -->
    <el-card shadow="never" class="dashboard-card">
      <template #header>
        <div class="card-header">
          <el-icon><Aim /></el-icon>
          <span class="panel-title">策略快速入口</span>
          <span class="header-hint">六大精选策略，点击直达筛选页面</span>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="8" v-for="strategy in strategyQuickEntries" :key="strategy.key" style="margin-bottom: 16px;">
          <div class="strategy-quick-card" :style="{ borderTopColor: strategy.borderColor }">
            <div class="strategy-quick-header">
              <span class="strategy-quick-name">{{ strategy.name }}</span>
              <el-tag :type="strategy.tagType" size="small" effect="plain">{{ strategy.marketTag }}</el-tag>
            </div>
            <div class="strategy-quick-desc">{{ strategy.description }}</div>
            <el-button type="primary" size="small" @click="goToStrategy(strategy.route)" class="strategy-quick-btn">
              立即查看 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 3. 策略表现统计 -->
    <el-card shadow="never" class="dashboard-card">
      <template #header>
        <div class="card-header">
          <el-icon><DataLine /></el-icon>
          <span class="panel-title">策略表现统计</span>
          <span class="header-hint">基于已平仓持仓的真实数据，交易满5次后自动反馈到仓位计算的胜率/盈亏比参数</span>
          <el-button size="small" :loading="perfLoading" @click="loadPerformance" style="margin-left:auto;">刷新统计</el-button>
        </div>
      </template>
      <div v-if="perfData">
        <el-descriptions :column="5" border size="small" style="margin-bottom: 12px;">
          <el-descriptions-item label="总交易次数">{{ perfData.overall.total_trades }}</el-descriptions-item>
          <el-descriptions-item label="总体胜率">
            <span :style="{color: perfData.overall.win_rate >= 0.5 ? 'var(--app-up)' : 'var(--app-down)', fontWeight:'bold'}">
              {{ fmtPctFromFraction(perfData.overall.win_rate, 1) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="盈亏比">{{ fmtNum(perfData.overall.profit_loss_ratio) }}</el-descriptions-item>
          <el-descriptions-item label="平均盈利">{{ fmtPctFromFraction(perfData.overall.avg_win) }}</el-descriptions-item>
          <el-descriptions-item label="平均亏损">{{ fmtPctFromFraction(perfData.overall.avg_loss) }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="perfTableData" size="small" class="app-table app-table--compact">
          <el-table-column label="策略" width="140">
            <template #default="{ row }">{{ getStrategyLabel(row.strategy) }}</template>
          </el-table-column>
          <el-table-column label="交易次数" prop="total_trades" width="100" sortable align="right" />
          <el-table-column label="胜率" width="100" sortable align="right">
            <template #default="{ row }">
              <span :style="{color: row.win_rate >= 0.5 ? 'var(--app-up)' : 'var(--app-down)', fontWeight:'bold'}">
                {{ fmtPctFromFraction(row.win_rate, 1) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="盈亏比" width="100" sortable align="right">
            <template #default="{ row }">{{ fmtNum(row.profit_loss_ratio) }}</template>
          </el-table-column>
          <el-table-column label="平均收益" width="120" sortable align="right">
            <template #default="{ row }">
              <span :style="{color: row.avg_return >= 0 ? 'var(--app-up)' : 'var(--app-down)'}">
                {{ fmtPctFromFraction(row.avg_return) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="建议胜率参数" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="row.total_trades >= 5 ? 'success' : 'info'">
                {{ fmtPctFromFraction(perfData.suggested_params[row.strategy].win_rate, 0) }}
                <template v-if="row.total_trades < 5"> (默认)</template>
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="建议盈亏比参数" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="row.total_trades >= 5 ? 'success' : 'info'">
                {{ fmtNum(perfData.suggested_params[row.strategy].profit_loss_ratio) }}
                <template v-if="row.total_trades < 5"> (默认)</template>
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:8px;font-size:12px;color:#909399;">
          注：交易次数不足5次的策略使用默认参数（胜率55%，盈亏比1.5），满5次后自动使用真实表现数据
        </div>
      </div>
      <el-empty v-else description="暂无已平仓持仓数据，平仓后将自动生成策略表现统计" />
    </el-card>

    <!-- 4. 策略详细说明（可折叠） -->
    <el-card shadow="never" class="dashboard-card">
      <template #header>
        <div class="card-header" style="cursor: pointer;" @click="strategyDetailVisible = !strategyDetailVisible">
          <el-icon><Aim /></el-icon>
          <span class="panel-title">策略详细说明</span>
          <span class="header-hint">点击展开/收起各策略的详细参数说明</span>
          <el-icon style="margin-left:auto; transition: transform 0.3s;" :style="{ transform: strategyDetailVisible ? 'rotate(180deg)' : 'rotate(0)' }">
            <ArrowDown />
          </el-icon>
        </div>
      </template>
      <div v-show="strategyDetailVisible">
        <el-row :gutter="16">
          <el-col :span="12" v-for="(info, key) in strategyList" :key="key" style="margin-bottom: 16px;">
            <el-card shadow="hover" class="strategy-card">
              <template #header>
                <div class="strategy-card-header">
                  <span class="strategy-name">{{ info.name }}</span>
                  <el-tag :type="getStrategyTagType(key)" size="small">{{ key }}</el-tag>
                </div>
              </template>
              <div class="strategy-info-body">
                <div class="info-row"><span class="info-label">散户优势：</span>{{ info.edge }}</div>
                <div class="info-row"><span class="info-label">持有周期：</span>{{ info.hold_days }}</div>
                <div class="info-row"><span class="info-label">盈利条件：</span>{{ info.win_condition }}</div>
                <el-divider content-position="left" style="margin: 12px 0;">风控参数</el-divider>
                <div class="risk-params" v-if="riskParams[key]">
                  <el-tag type="warning" size="small">单只≤{{ fmtPctFromFraction(riskParams[key].max_single_position, 0) }}</el-tag>
                  <el-tag type="warning" size="small">总仓≤{{ fmtPctFromFraction(riskParams[key].max_total_position, 0) }}</el-tag>
                  <el-tag type="danger" size="small">止损≤{{ fmtPctFromFraction(riskParams[key].max_single_loss, 0) }}</el-tag>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { TrendCharts, Aim, DataLine, ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import { retailApi, type StrategiesPerformanceResp, type StrategyPerformance } from '@/api/retail'
import { strategyApi } from '@/api/strategy'
import { fmtNum, fmtPctFromFraction } from '@/utils/format'

defineOptions({ name: 'StrategyExplainPanel' })

const router = useRouter()

// ---- 大盘×策略 静态适配矩阵（纯规则，无日期；当日情形见作战室盘前） ----
const strategyApiList = ref<any[]>([])
const matrixDims = [
  { key: 'trend', label: '趋势', options: ['牛市', '震荡', '熊市'] },
  { key: 'vol', label: '波动率', options: ['高波动', '正常', '低波动'] },
  { key: 'breadth', label: '市场宽度', options: ['普涨', '中性', '分化'] },
  { key: 'sentiment', label: '情绪', options: ['狂热', '中性', '恐慌'] },
]
const regimeDims = reactive({ trend: '震荡', vol: '正常', breadth: '中性', sentiment: '中性' })
const onPickDim = (key: string, opt: string) => {
  ;(regimeDims as any)[key] = opt
}

const matchedPortrait = computed(() => {
  const d = regimeDims
  if (d.vol === '高波动') return '高波动市'
  if (d.trend === '牛市') return d.breadth === '普涨' ? '牛市普涨' : '牛市强趋势'
  if (d.trend === '熊市') return (d.vol === '高波动' || d.sentiment === '恐慌') ? '熊市恐慌' : '熊市阴跌'
  return d.breadth === '分化' ? '震荡分化' : '震荡蓄势'
})
const portraitDesc = computed(() => {
  const p = matchedPortrait.value
  const m: Record<string, string> = {
    牛市强趋势: '趋势延续，强者恒强',
    牛市普涨: '全面上涨，弹性优先',
    熊市恐慌: '超跌反弹机会，快进快出',
    熊市阴跌: '谨慎防御，低估值优先',
    震荡蓄势: '低吸跟随，波段操作',
    震荡分化: '结构性行情，精选个股',
    高波动市: '快进快出，结构分析优先',
  }
  return m[p] || ''
})
const recommendedStrategies = computed(() => {
  const p = matchedPortrait.value
  return strategyApiList.value.filter((s: any) =>
    (s.market_regimes || []).includes(p) || (s.market_regimes || []).includes('全面适用')
  )
})

const loadStrategyCatalog = async () => {
  try {
    const data: any = await strategyApi.list()
    const body: any = Array.isArray(data) ? data : (data?.data ?? data?.items ?? [])
    strategyApiList.value = (Array.isArray(body) ? body : [])
      .filter((s: any) => s && s.id && (s.market_regimes || []).length)
  } catch (e: any) {
    console.error('加载策略适配矩阵失败', e)
  }
}

// ---- 策略快速入口 ----
const strategyQuickEntries = [
  { key: 'extreme_reversal', name: '极端反转', description: '市场情绪极端恐慌时抄底，高胜率短线策略', marketTag: '熊市/震荡市', tagType: 'danger', borderColor: '#e6232a', route: '/screening/extreme-reversal' },
  { key: 'small_cap_value', name: '小盘价值', description: '低估值小盘股价值投资，中长期持有策略', marketTag: '震荡市/牛市', tagType: 'success', borderColor: '#19a519', route: '/screening/small-cap-value' },
  { key: 'turnaround', name: '困境反转', description: '基本面拐点型公司，困境反转超额收益', marketTag: '熊市末期/牛市', tagType: 'warning', borderColor: '#e6a23c', route: '/screening/turnaround' },
  { key: 'convertible_arbitrage', name: '转债下修', description: '可转债下修博弈，低风险套利策略', marketTag: '全市场', tagType: 'primary', borderColor: '#2b6cb0', route: '/screening/convertible-arbitrage' },
  { key: 'limit_up_pullback', name: '涨停回调', description: '强势股涨停后回调买入，短线波段策略', marketTag: '牛市/震荡市', tagType: 'danger', borderColor: '#f56c6c', route: '/screening/limit-up-pullback' },
]
const goToStrategy = (route: string) => router.push(route)

// ---- 策略详细说明（retail 策略列表） ----
const strategyLoading = ref(false)
const strategyList = ref<Record<string, any>>({})
const riskParams = ref<Record<string, any>>({})
const strategyDetailVisible = ref(false)

const loadStrategies = async () => {
  strategyLoading.value = true
  try {
    const res = await retailApi.getStrategies()
    strategyList.value = res.strategies || {}
    riskParams.value = res.risk_params || {}
  } catch (e: any) {
    ElMessage.error('加载策略列表失败：' + (e.message || e))
  } finally {
    strategyLoading.value = false
  }
}

// ---- 策略表现统计 ----
const perfLoading = ref(false)
const perfData = ref<StrategiesPerformanceResp | null>(null)
const perfTableData = computed<StrategyPerformance[]>(() => {
  if (!perfData.value?.strategies) return []
  return Object.values(perfData.value.strategies).filter(s => s.strategy !== 'default')
})

const loadPerformance = async () => {
  perfLoading.value = true
  try {
    perfData.value = await retailApi.getStrategiesPerformance()
  } catch (e: any) {
    ElMessage.error('加载策略表现统计失败：' + (e.message || e))
  } finally {
    perfLoading.value = false
  }
}

// ---- 辅助函数 ----
const getStrategyTagType = (key: string) => {
  const map: Record<string, string> = { extreme_reversal: 'danger', turnaround: 'warning', small_cap_value: 'success', convertible_arbitrage: 'primary' }
  return map[key] || 'info'
}
const getStrategyLabel = (s: string) => {
  const map: Record<string, string> = {
    extreme_reversal: '极端反转', turnaround: '困境反转', small_cap_value: '小盘价值',
    convertible_arbitrage: '转债博弈', ma_golden_cross: 'MA金叉', macd_golden: 'MACD金叉',
    n_day_high_breakout: '创60日新高', n_day_low_reversal: 'N日低点反转', oversold_bounce: '超跌反弹',
    trend_breakout: '趋势突破', boll_breakout: '布林突破', volume_price_surge: '量价齐升',
    pullback_ma20_bounce: '回踩MA20反弹', strong_open: '强势高开', low_volatility_leader: '低波动龙头',
    low_pe_high_div_leader: '低估值高股息龙头', bottom_volume: '底部放量', one_yang_three_yin: '一阳夹三阴',
    chan_theory: '缠论', wave_theory: '波浪理论', event_driven: '事件驱动',
    expectation_repricing: '预期重估', emotion_cycle: '情绪周期',
  }
  return map[s] || s
}

onMounted(() => {
  loadStrategies()
  loadPerformance()
  loadStrategyCatalog()
})
</script>

<style scoped>
.explain-panel { display: flex; flex-direction: column; gap: 16px; }
.card-header { display: flex; align-items: center; gap: 8px; }
.panel-title { font-weight: 600; font-size: 15px; }
.header-hint { color: #909399; font-size: 12px; margin-left: 8px; }
.dashboard-card { border-radius: 8px; }
.strategy-card { height: 100%; }
.strategy-card-header { display: flex; justify-content: space-between; align-items: center; }
.strategy-name { font-weight: 600; font-size: 15px; }
.strategy-info-body { font-size: 13px; line-height: 1.8; }
.info-row { margin-bottom: 4px; }
.info-label { color: #909399; font-weight: 500; }
.risk-params { display: flex; gap: 8px; flex-wrap: wrap; }

/* 大盘×策略适配矩阵 */
.matrix-dims { margin-bottom: 4px; }
.matrix-dim { background: #f5f7fa; border-radius: 8px; padding: 12px 14px; height: 100%; }
.matrix-dim-label { font-size: 13px; color: #606266; font-weight: 600; margin-bottom: 10px; }
.matrix-dim-opts { display: flex; flex-wrap: wrap; gap: 6px; }
.matrix-result { padding: 4px 0; }
.matrix-portrait { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.matrix-portrait-label { font-size: 14px; color: #909399; }
.matrix-portrait-desc { font-size: 13px; color: #606266; }
.matrix-strategies-hint { font-size: 13px; color: #909399; margin-bottom: 12px; }
.matrix-strategy-card {
  border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px 14px;
  background: #fff; height: 100%; transition: box-shadow 0.25s ease;
}
.matrix-strategy-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.matrix-strategy-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.matrix-strategy-icon { font-size: 16px; }
.matrix-strategy-name { font-weight: 600; font-size: 14px; }
.matrix-strategy-desc { font-size: 12px; color: #606266; line-height: 1.6; margin-bottom: 6px; }
.matrix-strategy-rules { font-size: 12px; color: #909399; }
.matrix-rule-buy { color: #67C23A; }

/* 策略快速入口 */
.strategy-quick-card {
  background: #fff; border: 1px solid #e4e7ed; border-top: 3px solid;
  border-radius: 8px; padding: 16px; transition: all 0.3s ease;
  height: 100%; display: flex; flex-direction: column;
}
.strategy-quick-card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1); }
.strategy-quick-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.strategy-quick-name { font-size: 16px; font-weight: 600; color: #303133; }
.strategy-quick-desc { font-size: 13px; color: #606266; line-height: 1.6; margin-bottom: 16px; flex: 1; }
.strategy-quick-btn { align-self: flex-end; }
</style>