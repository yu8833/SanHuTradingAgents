<template>
  <div class="dashboard-container explain-panel">
    <!-- 大盘×策略 静态适配矩阵（纯规则，无日期；当日情形见作战室盘前 + 顶部四维判断） -->
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { TrendCharts } from '@element-plus/icons-vue'
import { strategyApi } from '@/api/strategy'

defineOptions({ name: 'StrategyExplainPanel' })

// ---- 大盘×策略 静态适配矩阵（纯规则，无日期；当日情形见作战室盘前 + 顶部四维判断） ----
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

onMounted(() => {
  loadStrategyCatalog()
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
</style>