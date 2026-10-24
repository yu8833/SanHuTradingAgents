<template>
  <div class="vibe-emotion app-page">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 短线情绪</h2>
          <p class="page-hero-sub">连板梯队 / 打板情绪 · 客观公开榜单</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">更新于 {{ updatedAt }}</span>
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="refresh">
          刷新
        </el-button>
      </div>
    </div>

    <div class="emotion-content" v-loading="loading" element-loading-background="rgba(255,255,255,0.85)">

    <template v-if="emotion">
      <!-- 关键计数 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><DataLine /></el-icon> 关键计数
          </span>
        </div>
        <div class="grid grid-6">
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">涨停</div>
            <div class="cnt-num up">{{ emotion.zt_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">跌停</div>
            <div class="cnt-num down">{{ emotion.dt_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">最高连板</div>
            <div class="cnt-num">{{ emotion.max_boards }}</div>
            <div class="cnt-sub">板</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">连板（2板+）</div>
            <div class="cnt-num">{{ emotion.lianban_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">炸板</div>
            <div class="cnt-num neutral">{{ emotion.zb_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">昨涨停</div>
            <div class="cnt-num">{{ emotion.yzt_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
        </div>
      </section>

      <!-- 打板情绪比率 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><MagicStick /></el-icon> 打板情绪比率
          </span>
        </div>
        <div class="grid grid-3">
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">封板率</div>
            <div class="rt-num up">{{ fmtPctFromFraction(emotion.seal_rate, 1) }}</div>
            <div class="rt-bar">
              <div class="bar-fill up" :style="{ width: rateWidth(emotion.seal_rate) }"></div>
            </div>
          </el-card>
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">炸板率</div>
            <div class="rt-num down">{{ fmtPctFromFraction(emotion.break_rate, 1) }}</div>
            <div class="rt-bar">
              <div class="bar-fill down" :style="{ width: rateWidth(emotion.break_rate) }"></div>
            </div>
          </el-card>
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">晋级率</div>
            <div class="rt-num">{{ fmtPctFromFraction(emotion.promotion_rate, 1) }}</div>
            <div class="rt-bar">
              <div class="bar-fill neutral" :style="{ width: rateWidth(emotion.promotion_rate) }"></div>
            </div>
          </el-card>
        </div>
      </section>

      <!-- 情绪周期：近 10 日曲线 + 周期阶段 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><TrendCharts /></el-icon> 情绪周期 · 近 {{ history?.series?.length || 0 }} 个交易日
          </span>
          <span v-if="phase" class="phase-tag" :class="`phase-${phase.tone}`">{{ phase.label }}</span>
        </div>
        <el-card shadow="never" class="trend-card" v-loading="historyLoading">
          <div v-if="emotionChartOption" class="emotion-chart-wrap">
            <VChart :option="emotionChartOption" autoresize class="emotion-chart" />
          </div>
          <div v-else class="empty">历史情绪数据暂不可用（数据源未返回），稍后刷新重试</div>
          <p v-if="phase" class="phase-desc">{{ phase.desc }}</p>
        </el-card>
      </section>

      <!-- 连板梯队（点击梯队过滤下方清单） -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Sort /></el-icon> 连板梯队
          </span>
          <span class="block-hint">点击梯队筛选下方连板股 · 再点「全部」取消</span>
        </div>
        <el-card shadow="never" class="ladder-card">
          <div v-if="emotion.ladder.length" class="ladder-visual">
            <button
              v-for="l in emotion.ladder"
              :key="l.boards"
              class="ladder-item"
              :class="{ active: selectedTier === l.boards }"
              @click="toggleTier(l.boards)"
            >
              <span class="ladder-count">{{ l.count }}</span>
              <span class="ladder-bar" :style="{ height: ladderHeight(l.count) }"></span>
              <span class="ladder-tier">{{ l.boards }}{{ l.plus ? '+' : '' }}板</span>
            </button>
            <button
              v-if="selectedTier != null"
              class="ladder-item ladder-all"
              @click="selectedTier = null"
            >
              <span class="ladder-count">全部</span>
              <span class="ladder-bar" style="height: 8px"></span>
              <span class="ladder-tier">取消筛选</span>
            </button>
          </div>
          <div v-else class="empty">暂无连板梯队数据</div>
        </el-card>
      </section>

      <!-- 连板股清单 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Histogram /></el-icon> 连板股清单
            <el-tag v-if="selectedTier != null" size="small" type="danger" effect="plain" class="tier-tag">
              {{ selectedTierLabel }}
            </el-tag>
          </span>
          <span class="block-hint">共 {{ filteredLianbanStocks.length }} 只</span>
        </div>
        <el-card shadow="never" class="table-card">
          <el-table :data="filteredLianbanStocks" stripe size="default" class="app-table app-table--ranking">
            <el-table-column label="名称 / 代码" min-width="170">
              <template #default="{ row }">
                <div class="stock-cell">
                  <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                  <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="连板数" width="90" align="right" sortable>
              <template #default="{ row }">
                <el-tag type="danger" effect="plain">{{ row.boards }}板</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="现价" width="100" align="right" sortable>
              <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
            </el-table-column>
            <el-table-column label="涨停%" width="100" align="right" sortable>
              <template #default="{ row }">
                <span class="up">{{ fmtPct(row.pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="成交额(亿)" width="120" align="right" sortable>
              <template #default="{ row }">{{ fmtYi(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="流通市值(亿)" width="130" align="right" sortable>
              <template #default="{ row }">{{ fmtYi(row.float_cap) }}</template>
            </el-table-column>
            <el-table-column label="概念" min-width="120" prop="industry" />
          </el-table>
        </el-card>
      </section>

      <!-- 三池清单：涨停 / 炸板 / 跌停 -->
      <section v-if="emotion.pools" class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Tickets /></el-icon> 三池清单
          </span>
          <span class="block-hint">客观公开榜单 · 不评分不推荐</span>
        </div>
        <el-card shadow="never" class="table-card">
          <el-tabs v-model="poolTab" class="pool-tabs">
            <el-tab-pane :label="`涨停池 ${emotion.pools.zt.length}`" name="zt" />
            <el-tab-pane :label="`炸板池 ${emotion.pools.zb.length}`" name="zb" />
            <el-tab-pane :label="`跌停池 ${emotion.pools.dt.length}`" name="dt" />
          </el-tabs>
          <el-table :data="poolRows" stripe size="default" class="app-table app-table--ranking">
            <el-table-column label="名称 / 代码" min-width="170">
              <template #default="{ row }">
                <div class="stock-cell">
                  <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                  <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="现价" width="100" align="right" sortable prop="price">
              <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
            </el-table-column>
            <el-table-column label="涨跌幅" width="100" align="right" sortable prop="pct">
              <template #default="{ row }">
                <span :class="clsByVal(row.pct, '')">{{ fmtPct(row.pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column v-if="poolTab === 'zt'" label="连板" width="90" align="right" sortable prop="boards">
              <template #default="{ row }">
                <el-tag type="danger" effect="plain" size="small">{{ row.boards }}板</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="poolTab === 'zb'" label="炸板次数" width="100" align="right" sortable prop="break_times">
              <template #default="{ row }">{{ row.break_times }} 次</template>
            </el-table-column>
            <el-table-column v-if="poolTab === 'dt'" label="连续跌停" width="100" align="right" sortable prop="days">
              <template #default="{ row }">{{ row.days }} 天</template>
            </el-table-column>
            <el-table-column label="成交额(亿)" width="120" align="right" sortable prop="amount">
              <template #default="{ row }">{{ fmtYi(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="行业" min-width="120" prop="industry" />
          </el-table>
          <div v-if="!poolRows.length" class="empty">该池暂无个股</div>
        </el-card>
      </section>

      <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
    </template>

    <el-empty v-else-if="!loading" description="暂无短线情绪数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  DataLine,
  Refresh,
  MagicStick,
  Sort,
  Histogram,
  Tickets,
} from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { vibeApi, type ShortTermEmotion, type EmotionPoolRow, type EmotionHistory } from '@/api/vibe'
import { fmtPrice, fmtYi, fmtPctFromFraction, fmtPct, clsByVal } from '@/utils/format'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'

defineOptions({ name: 'ReviewEmotion' })

echartsUse([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

// 标题日期：优先情绪数据日期（最新交易日）；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => emotion.value?.date || tradeDate.value || '')

// 页头「更新于」：数据获取时刻（涨停池构建时刻）
const updatedAt = computed(() => emotion.value?.updated ? formatBeijingDateTimeMinute(emotion.value.updated) : '')

const loading = ref(false)
const emotion = ref<ShortTermEmotion | null>(null)

// ── 近 10 交易日情绪序列（独立接口，不阻塞主情绪；数据源不可用时明确空态） ──
const history = ref<EmotionHistory | null>(null)
const historyLoading = ref(false)

const emotionChartOption = computed<EChartsOption | null>(() => {
  const series = history.value?.series || []
  if (series.length < 2) return null
  const dates = series.map(p => p.date.slice(5))
  const maxBoard = Math.max(1, ...series.map(p => p.max_boards || 0))
  return {
    animationDuration: 500,
    grid: { left: 44, right: 42, top: 34, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: 'rgba(45,55,72,.08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#718096', fontSize: 11 },
      data: ['涨停', '炸板', '跌停', '最高连板'],
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '家数',
        nameTextStyle: { color: '#a0aec0', fontSize: 10 },
        axisLabel: { color: '#a0aec0', fontSize: 10 },
        splitLine: { lineStyle: { color: '#f0f4f8' } },
      },
      {
        type: 'value',
        name: '板',
        min: 0,
        max: maxBoard + 1,
        nameTextStyle: { color: '#a0aec0', fontSize: 10 },
        axisLabel: { color: '#a0aec0', fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '涨停',
        type: 'line',
        smooth: true,
        symbolSize: 5,
        data: series.map(p => p.zt),
        itemStyle: { color: '#f56c6c' },
        lineStyle: { width: 2.2 },
      },
      {
        name: '炸板',
        type: 'line',
        smooth: true,
        symbolSize: 4,
        data: series.map(p => p.zb),
        itemStyle: { color: '#e6a23c' },
        lineStyle: { width: 1.4, type: 'dashed' },
      },
      {
        name: '跌停',
        type: 'line',
        smooth: true,
        symbolSize: 4,
        data: series.map(p => p.dt),
        itemStyle: { color: '#67c23a' },
        lineStyle: { width: 1.4 },
      },
      {
        name: '最高连板',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbolSize: 4,
        data: series.map(p => p.max_boards),
        itemStyle: { color: '#7c3aed' },
        lineStyle: { width: 1.4, type: 'dotted' },
      },
    ],
  }
})

// 情绪周期阶段（基于涨停/跌停家数、炸板率、连板高度与环比变化）
type PhaseTone = 'hot' | 'mid' | 'cold'
interface PhaseInfo { label: string; tone: PhaseTone; desc: string }

const phase = computed<PhaseInfo | null>(() => {
  const e = emotion.value
  if (!e) return null
  const series = history.value?.series || []
  const prev = series.length >= 2 ? series[series.length - 2] : null
  const zt = Number(e.zt_count) || 0
  const zb = Number(e.zb_count) || 0
  const dt = Number(e.dt_count) || 0
  const attempts = zt + zb
  const breakRate = attempts ? zb / attempts : 0
  const delta = prev ? zt - prev.zt : 0
  if (zt < 30 && dt >= zt) {
    return { label: '冰点期', tone: 'cold', desc: '涨停家数少、跌停压制，赚钱效应偏弱，等待修复信号' }
  }
  if (prev && zt < prev.zt * 0.7 && (breakRate >= 0.3 || dt >= 10)) {
    return { label: '退潮期', tone: 'cold', desc: '涨停家数明显回落、炸板与跌停增多，注意高位股补跌风险' }
  }
  if (breakRate >= 0.35 || (prev && zt < prev.zt * 0.85)) {
    return { label: '分歧期', tone: 'mid', desc: '炸板率偏高、涨停家数环比回落，资金开始分歧，宜降低预期' }
  }
  if (zt >= 100 || Number(e.max_boards) >= 6) {
    return { label: '高潮期', tone: 'hot', desc: '涨停家数与连板高度双高，赚钱效应最强，警惕次日退潮' }
  }
  if (zt >= 60 && (Number(e.seal_rate) || 0) >= 0.65) {
    return { label: '发酵期', tone: 'hot', desc: '涨停家数扩张、封板率较高，情绪仍在向上发酵' }
  }
  if (delta > 0 || zt >= 40) {
    return { label: '修复期', tone: 'mid', desc: '涨停家数回暖，情绪自低位修复，关注主线持续性' }
  }
  return { label: '启动期', tone: 'mid', desc: '情绪温和、主线未明，适合轻仓试错' }
})

// ── 连板梯队：柱高 = 家数，点击梯队筛选下方连板股 ──
const selectedTier = ref<number | null>(null)
const ladderMax = computed(() => Math.max(1, ...(emotion.value?.ladder || []).map(l => l.count)))
const ladderHeight = (n: number) => `${Math.max(10, Math.round((n / ladderMax.value) * 100))}%`
const toggleTier = (boards: number) => {
  selectedTier.value = selectedTier.value === boards ? null : boards
}
const filteredLianbanStocks = computed(() => {
  const list = emotion.value?.lianban_stocks || []
  const tier = emotion.value?.ladder?.find(l => l.boards === selectedTier.value)
  if (selectedTier.value == null || !tier) return list
  return list.filter(r => tier.plus ? r.boards >= tier.boards : r.boards === tier.boards)
})
const selectedTierLabel = computed(() => {
  const tier = emotion.value?.ladder?.find(l => l.boards === selectedTier.value)
  return tier ? `${tier.boards}${tier.plus ? '+' : ''}板` : ''
})

// ── 三池清单（涨停 / 炸板 / 跌停） ──
const poolTab = ref<'zt' | 'zb' | 'dt'>('zt')
const poolRows = computed<EmotionPoolRow[]>(() => {
  const pools = emotion.value?.pools
  return pools ? (pools[poolTab.value] || []) : []
})

const rateWidth = (v: number | null | undefined) =>
  v == null ? '0%' : Math.min(100, Math.max(0, v * 100)).toFixed(1) + '%'

const load = async (refresh = false) => {
  loading.value = true
  try {
    const res = await vibeApi.getEmotion(refresh)
    emotion.value = (res as any).data || null
    if (!emotion.value) {
      ElMessage.warning('暂无短线情绪数据')
    } else if (selectedTier.value != null && !emotion.value.ladder?.some(l => l.boards === selectedTier.value)) {
      selectedTier.value = null
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

const loadHistory = async (refresh = false) => {
  historyLoading.value = true
  try {
    const res = await vibeApi.getEmotionHistory(10, refresh)
    history.value = (res as any)?.data || null
  } catch (e) {
    console.warn('情绪历史加载失败', e)
    history.value = null
  } finally {
    historyLoading.value = false
  }
}

// 页头刷新：两个接口并行刷新（含历史序列）
const refresh = async () => {
  await Promise.all([load(true), loadHistory(true)])
}
defineExpose({ refresh })

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) tradeDate.value = d })
  load()
  loadHistory()
})

// keep-alive 恢复：缓存 TTL 内不产生请求，仅刷新数据快照
let emotionInited = false
onActivated(() => {
  if (emotionInited) {
    load()
    loadHistory()
  }
  emotionInited = true
})
</script>

<style scoped>
.vibe-emotion {
  padding: 4px;
  min-height: 200px;
}

.block {
  margin-bottom: 24px;
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.block-title .el-icon {
  color: var(--el-color-primary);
}

.block-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.grid-6 {
  grid-template-columns: repeat(6, 1fr);
}

.count-card {
  border-radius: 8px;
  text-align: center;
}

.count-card :deep(.el-card__body) {
  padding: 18px 16px;
}

.cnt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.cnt-num {
  font-family: var(--app-font-mono);
  font-size: 32px;
  font-weight: 700;
  margin: 6px 0 2px;
  color: var(--el-text-color-primary);
}

.cnt-sub {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.ratio-card {
  border-radius: 8px;
}

.ratio-card :deep(.el-card__body) {
  padding: 18px 20px;
}

.rt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.rt-num {
  font-family: var(--app-font-mono);
  font-size: 28px;
  font-weight: 700;
  margin: 6px 0 12px;
  color: var(--el-text-color-primary);
}

.rt-bar {
  height: 6px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.ladder-card {
  border-radius: 8px;
}

/* 情绪周期：曲线 + 阶段标签 */
.trend-card {
  border-radius: 8px;
}

.emotion-chart-wrap {
  min-height: 240px;
}

.emotion-chart {
  width: 100%;
  height: 240px;
}

.phase-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  border: 1px solid transparent;
}

.phase-hot {
  color: #c0392b;
  background: #fdecea;
  border-color: #f5b7b1;
}

.phase-cold {
  color: #1e8449;
  background: #eafaf1;
  border-color: #a9dfbf;
}

.phase-mid {
  color: #a16207;
  background: #fef9e7;
  border-color: #f7dc6f;
}

.phase-desc {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

/* 连板梯队：柱状可视化 */
.ladder-visual {
  display: flex;
  align-items: flex-end;
  justify-content: flex-start;
  gap: 18px;
  height: 150px;
  padding: 8px 4px 0;
  overflow-x: auto;
}

.ladder-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  min-width: 54px;
  padding: 0 4px;
  background: none;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.ladder-item:hover { background: var(--el-fill-color-light); }
.ladder-item.active { background: var(--el-color-danger-light-9); }

.ladder-count {
  font-family: var(--app-font-mono);
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 4px;
}

.ladder-bar {
  width: 100%;
  max-width: 42px;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, #f87171 0%, #f56c6c 100%);
  transition: height 0.35s ease;
}

.ladder-item.active .ladder-bar {
  background: linear-gradient(180deg, #dc2626 0%, #b91c1c 100%);
}

.ladder-all .ladder-bar {
  background: var(--el-border-color);
}

.ladder-tier {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.ladder-item.active .ladder-tier {
  color: var(--el-color-danger);
  font-weight: 600;
}

.tier-tag {
  margin-left: 4px;
}

/* 三池清单 Tab */
.pool-tabs {
  margin-top: -6px;
}

.pool-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.pool-tabs :deep(.el-tabs__item) {
  height: 34px;
  font-size: 13px;
}

.empty {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 16px 0;
  font-size: 13px;
}

.bar-fill.up { background: var(--app-up); }
.bar-fill.down { background: var(--app-down); }
.bar-fill.neutral { background: var(--app-flat); }

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 992px) {
  .grid-3 { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .vibe-emotion {
    padding: 2px;
  }
  .grid-6 {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
  .grid-3 {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .count-card :deep(.el-card__body) {
    padding: 12px 8px;
  }
  .cnt-label {
    font-size: 12px;
    line-height: 1.2;
  }
  .cnt-num {
    font-size: 26px;
    margin: 4px 0 2px;
    line-height: 1;
    word-break: break-all;
  }
  .rt-num {
    font-size: 22px;
    margin: 4px 0 8px;
  }
  .block-head {
    flex-wrap: wrap;
    gap: 4px;
  }
  .ladder-visual {
    gap: 10px;
  }
}

@media (max-width: 480px) {
  .grid-6 {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
