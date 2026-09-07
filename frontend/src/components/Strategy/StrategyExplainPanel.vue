<template>
  <div class="dashboard-container explain-panel">
    <!-- 大盘×策略 静态适配矩阵（纯规则，无日期；当日情形见作战室盘前 + 顶部四维判断） -->
    <el-card shadow="never" class="dashboard-card market-overview-card">
      <template #header>
        <div class="card-header">
          <el-icon><TrendCharts /></el-icon>
          <span class="panel-title">大盘×策略适配矩阵</span>
          <span class="header-hint">选择环境组合（默认=今日检测结果）→ 下方策略池展示适配策略</span>
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
      <div class="matrix-result">
        <div class="matrix-portrait">
          <span class="matrix-portrait-label">当前组合画像</span>
          <el-tag type="warning" effect="dark" size="large">{{ matchedPortrait }}</el-tag>
          <span class="matrix-portrait-desc">{{ portraitDesc }}</span>
          <span class="matrix-fit-count">适配 <b>{{ recommendedStrategies.length }}</b> 个策略（见下方策略池）</span>
        </div>
        <!-- 盘中预警：实时大盘快照（指示大盘按实际刷新，60s 轮询） -->
        <div v-if="liveMetrics" class="matrix-live">
          <el-icon class="matrix-live-dot"><Connection /></el-icon>
          <span class="matrix-live-label">盘中按实际刷新</span>
          <template v-if="liveMetrics.price != null">
            <span class="matrix-live-item">沪深300 <b>{{ liveMetrics.price.toFixed(2) }}</b></span>
          </template>
          <template v-if="liveMetrics.breadthPct != null">
            <span class="matrix-live-item">市场宽度 <b>{{ liveMetrics.breadthPct }}%</b></span>
          </template>
          <span class="matrix-live-time" v-if="liveMetrics.updatedAt">检测于 {{ liveMetrics.updatedAt }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { TrendCharts, Connection } from '@element-plus/icons-vue'
import { strategyApi } from '@/api/strategy'

defineOptions({ name: 'StrategyExplainPanel' })

export interface LiveMetrics {
  price: number | null
  breadthPct: number | null
  updatedAt: string
}

// 受控初值（今日检测四维，中文标签），首次到位时初始化矩阵，之后用户手动调整不再覆盖；
// autoSync=true 时（盘中预警开启）跟随最新检测结果，检测刷新即覆盖矩阵维度（按实际行情）。
const props = defineProps<{
  initialDims?: Record<string, string>
  autoSync?: boolean
  liveMetrics?: LiveMetrics | null
}>()
const emit = defineEmits<{ (e: 'portrait-change', portrait: string): void }>()

// ---- 大盘×策略 静态适配矩阵（选择环境 → 下方策略池联动） ----
const strategyApiList = ref<any[]>([])
const matrixDims = [
  { key: 'trend', label: '趋势', options: ['牛市', '震荡', '熊市'] },
  { key: 'vol', label: '波动率', options: ['高波动', '正常', '低波动'] },
  { key: 'breadth', label: '市场宽度', options: ['普涨', '中性', '分化'] },
  { key: 'sentiment', label: '情绪', options: ['狂热', '中性', '恐慌'] },
]
const regimeDims = reactive({ trend: '震荡', vol: '正常', breadth: '中性', sentiment: '中性' })
let initialized = false

const applyInitialDims = (d: Record<string, string>, force = false) => {
  if (!d || (initialized && !force)) return
  const next: Record<string, string> = {}
  for (const k of ['trend', 'vol', 'breadth', 'sentiment']) {
    if (d[k]) next[k] = d[k]
  }
  if (!Object.keys(next).length) return
  Object.assign(regimeDims, next)
  // 仅当四维检测值全部到位才视为「已与今日检测同步」，此后用户手动调整不再被覆盖；
  // 若检测部分缺失，允许后续更完整的初始化继续补齐，避免矩阵维度与检测不一致。
  initialized = ['trend', 'vol', 'breadth', 'sentiment'].every((k) => !!next[k])
}
watch(
  () => props.initialDims,
  (d) => {
    if (props.autoSync) applyInitialDims(d, true)
    else applyInitialDims(d)
  },
  { deep: true }
)
// 盘中预警开启 → 立即以最新检测结果强制同步一次
watch(
  () => props.autoSync,
  (on) => {
    if (on) applyInitialDims(props.initialDims as any, true)
  }
)

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

// 画像变化 → 通知父组件（策略池联动过滤）
watch(matchedPortrait, p => emit('portrait-change', p), { immediate: true })

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

onMounted(() => {
  loadStrategyCatalog()
  applyInitialDims(props.initialDims as any)
})
</script>

<style scoped>
.explain-panel { display: flex; flex-direction: column; gap: 16px; }
.card-header { display: flex; align-items: center; gap: 8px; }
.panel-title { font-weight: 600; font-size: 15px; }
.header-hint { color: #909399; font-size: 12px; margin-left: 8px; }
.dashboard-card { border-radius: 8px; }

/* 大盘×策略适配矩阵 */
.matrix-dims { margin-bottom: 4px; }
.matrix-dim { background: #f5f7fa; border-radius: 8px; padding: 12px 14px; height: 100%; }
.matrix-dim-label { font-size: 13px; color: #606266; font-weight: 600; margin-bottom: 10px; }
.matrix-dim-opts { display: flex; flex-wrap: wrap; gap: 6px; }
.matrix-result { padding: 4px 0; }
.matrix-portrait { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.matrix-portrait-label { font-size: 14px; color: #909399; }
.matrix-portrait-desc { font-size: 13px; color: #606266; }
.matrix-fit-count { font-size: 12px; color: #909399; margin-left: auto; }
.matrix-fit-count b { color: #E6A23C; }

/* 盘中预警：实时大盘快照条 */
.matrix-live {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 14px;
  border-radius: 10px;
  background: linear-gradient(120deg, rgba(250, 173, 20, 0.10), rgba(64, 158, 255, 0.08));
  border: 1px solid rgba(230, 162, 60, 0.30);
  font-size: 13px;
}
.matrix-live-dot {
  color: #E6A23C;
  animation: matrixLivePulse 1.6s ease-in-out infinite;
}
@keyframes matrixLivePulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.matrix-live-label { font-weight: 600; color: #E6A23C; font-size: 12px; }
.matrix-live-item { color: #606266; }
.matrix-live-item b { color: #E6A23C; font-family: 'SFMono-Regular', Consolas, monospace; }
.matrix-live-time { color: #909399; font-size: 12px; }
/* 深色主题微调 */
:global(html.dark) .matrix-live { border-color: rgba(230, 162, 60, 0.4); }
:global(html.dark) .matrix-live-item { color: #a3a6ad; }
:global(html.dark) .matrix-live-time { color: #6f7278; }
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
</style>