<template>
  <div class="board-quadrant-page">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ today }} · {{ heroTitle }}</h2>
          <p class="page-hero-sub">{{ heroSub }}</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 板块宽度 KPI（当前快照） -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Odometer /></el-icon> 板块宽度 · 当前</span>
        <span v-if="data?.as_of" class="block-hint">数据更新于 {{ data.as_of }}</span>
      </div>
      <div class="kpi-row">
        <div class="kpi-cell">
          <div class="kpi-label">{{ unitName }}总数</div>
          <div class="kpi-value accent">{{ data?.total ?? '—' }}</div>
          <div class="kpi-sub">{{ unitSub }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">上涨 / 下跌</div>
          <div class="kpi-value">
            <span class="up">{{ data?.breadth?.up ?? '—' }}</span><span class="kpi-sep">/</span><span class="down">{{ data?.breadth?.down ?? '—' }}</span>
          </div>
          <div class="kpi-sub">当前快照涨跌家数</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">平均涨幅</div>
          <div class="kpi-value accent" :class="clsByVal(data?.breadth?.avg_pct, '')">{{ fmtPct(data?.breadth?.avg_pct) }}</div>
          <div class="kpi-sub">全板块均值</div>
        </div>
      </div>
    </section>

    <!-- 搜索 -->
    <section class="block control-panel">
      <div class="control-main">
        <div class="control-search">
          <div class="search-head">
            <span class="block-title"><el-icon><Search /></el-icon> 查找{{ unitName }}（名称）</span>
            <span v-if="matchNames.length" class="block-hint">命中 {{ matchNames.length }} 个，图表同步高亮</span>
          </div>
          <div class="search-row">
            <el-input
              v-model="searchKw"
              size="small"
              clearable
              placeholder="如：半导体 或 银行"
              class="search-input"
              @keyup.enter="doSearch"
              @clear="clearMatch"
            />
            <el-button size="small" type="primary" plain :icon="Search" :disabled="!searchKw.trim()" @click="doSearch">
              查 找
            </el-button>
            <el-button v-if="matchNames.length" size="small" @click="clearMatch">清除高亮</el-button>
          </div>
        </div>
      </div>
      <div class="panel-hint">
        板块四象限 · 当前快照（无历史时间轴） · 点击圆点跳转外部详情 · 滚轮缩放
        <span v-if="!mainAvailable" class="warn-hint">当前快照部分维度不可用（板块级暂无数据），对应图表以空态提示</span>
      </div>
    </section>

    <!-- 六图四象限 -->
    <div v-if="mapReady" class="chart-grid">
      <section v-for="card in CARDS" :key="card.id" class="block chart-card">
        <div class="block-head">
          <span class="block-title"><el-icon><TrendCharts /></el-icon> {{ card.title }}</span>
          <span class="block-hint">{{ card.subtitle }}</span>
        </div>
        <div class="concept-chart">
          <VChart
            v-if="chartPointCount[card.id] > 0"
            :ref="(el: any) => setChartRef(card.id, el)"
            :option="chartOptions[card.id]"
            autoresize
            class="concept-chart-inner map-chart"
            @click="onChartClick"
          />
          <el-empty v-else :image-size="48" :description="card.emptyHint || '板块暂无该维度数据'" />
        </div>
        <div class="quadrant-tip">
          <span v-for="(t, i) in card.tips" :key="i" class="qt-item">
            <i class="qt-dot" :class="QT_DOT[i]" />{{ t }}
          </span>
        </div>
      </section>
    </div>
    <el-empty v-else :image-size="64" description="暂无数据，请刷新重试" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, DataAnalysis, TrendCharts, Odometer } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { vibeApi, SQ } from '@/api/vibe'
import type { BoardQuadrant } from '@/api/vibe'
import { makeQuadrantOption, computeMatchPoints, type QuadrantCfg } from '@/utils/quadrant'
import { fmtPct, clsByVal } from '@/utils/format'

defineOptions({ name: 'BoardQuadrant' })

echartsUse([CanvasRenderer, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent])

const props = defineProps<{ scope: 'concept' | 'industry' }>()

const QT_DOT = ['qt-red', 'qt-yellow', 'qt-blue', 'qt-green'] as const

const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
const loading = ref(false)
const data = ref<BoardQuadrant | null>(null)

const isConcept = computed(() => props.scope === 'concept')
const heroTitle = computed(() => (isConcept.value ? '概念趋势' : '行业趋势'))
const heroSub = computed(() => (isConcept.value ? '概念板块四象限 · 当前快照一屏看全' : '行业板块四象限 · 代表ETF快照一屏看全'))
const unitName = computed(() => (isConcept.value ? '概念' : '行业'))
const unitSub = computed(() => (isConcept.value ? '同花顺概念板块' : '行业代表ETF'))

// ── 图配置（xKey/yKey 对齐帧 8 元组）──
// 板块数据源仅提供 涨跌/换手/资金 能力；概念无市值，行业可叠加市值（代表ETF）。
// 市盈率/5日涨跌/连板为结构化不可得（板块无PE聚合、无历史序列、连板为个股专属），不提供图。
type BoardCard = QuadrantCfg & { subtitle: string; emptyHint: string }

const MONEY_CARD: BoardCard = {
  id: 'money_pct', title: '涨跌 × 主力资金', subtitle: '强弱共振定位',
  xKey: SQ.MAIN, yKey: SQ.P, xName: '主力净流入', xUnit: '亿', yName: '涨跌幅', yUnit: '%',
  quadrants: ['强势共振', '缩量上行', '低位承接', '弱势杀跌'],
  tips: ['流入+上涨 · 强势共振', '流出+上涨 · 缩量上行', '流入+下跌 · 低位承接', '流出+下跌 · 弱势杀跌'],
  emptyHint: '当前快照主力资金数据暂不可用',
}
const TURN_CARD: BoardCard = {
  id: 'pct_turn', title: '涨跌 × 换手率', subtitle: '量价关系',
  xKey: SQ.P, yKey: SQ.TURN, xName: '涨跌幅', xUnit: '%', yName: '换手率', yUnit: '%',
  quadrants: ['放量上攻', '放量下跌', '缩量回调', '缩量阴跌'],
  tips: ['高换手+上涨 · 抢筹', '高换手+下跌 · 出货', '低换手+上涨 · 惜售/临板', '低换手+下跌 · 阴跌'],
  emptyHint: '当前快照换手率数据暂不可用',
}
const MV_CARD: BoardCard = {
  id: 'pct_mv', title: '涨跌 × 总市值', subtitle: '体量风格（对数轴）',
  xKey: SQ.P, yKey: SQ.MV, xName: '涨跌幅', xUnit: '%', yName: '总市值', yUnit: '亿', logY: true,
  quadrants: ['权重搭台', '题材活跃', '权重杀跌', '题材退潮'],
  tips: ['大市值+上涨 · 权重搭台', '小市值+上涨 · 题材活跃', '大市值+下跌 · 权重杀跌', '小市值+下跌 · 题材退潮'],
  emptyHint: '板块暂无市值数据（仅支持个股维度）',
}
// 行业可用代表ETF总市值；概念无市值聚合 → 不展示该图
const CARDS = computed<BoardCard[]>(() => (isConcept.value ? [MONEY_CARD, TURN_CARD] : [MONEY_CARD, TURN_CARD, MV_CARD]))

const currentFrame = computed(() => data.value?.frame || {})
const mapReady = computed(() => !!data.value && Object.keys(currentFrame.value).length > 0)

// ── KPI（当前快照） ──
const mainAvailable = computed(() => {
  const f = currentFrame.value
  if (!f) return false
  let cnt = 0
  const values = Object.values(f)
  for (const v of values) {
    if (v[SQ.MAIN] != null) cnt++
  }
  return values.length > 0 && cnt / values.length > 0.05
})

// ── 六图 option ──
const chartOptions = computed<Record<string, EChartsOption>>(() => {
  const meta = data.value?.meta || {}
  const frame = currentFrame.value
  const out: Record<string, EChartsOption> = {}
  if (!frame || !Object.keys(frame).length) return out
  for (const card of CARDS.value) {
    out[card.id] = makeQuadrantOption(meta, frame, card, matchSet.value)
  }
  return out
})

const chartPointCount = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const card of CARDS.value) {
    const opt: any = chartOptions.value[card.id]
    const s0 = opt?.series?.[0]?.data?.length ?? 0
    const s1 = opt?.series?.[1]?.data?.length ?? 0
    out[card.id] = (s0 as number) + (s1 as number)
  }
  return out
})

// ── 多图实例与跨图闪烁 ──
const charts: Record<string, any> = {}
function setChartRef(id: string, el: any) {
  charts[id] = el?.getInstance?.() ?? null
}

const searchKw = ref('')
const matchNames = ref<string[]>([])
const matchSet = computed(() => new Set(matchNames.value))
let blinkTimer: ReturnType<typeof setInterval> | null = null
let blinkOn = false

const matchPoints = computed(() => {
  if (!matchSet.value.size) return []
  const frame = currentFrame.value
  if (!frame) return []
  const pts: { chartId: string; seriesIndex: number; dataIndex: number }[] = []
  for (const card of CARDS.value) {
    for (const p of computeMatchPoints(frame, card, matchSet.value)) {
      pts.push({ chartId: card.id, seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
    }
  }
  return pts
})

function applyBlink() {
  blinkOn = !blinkOn
  dispatchMatch(blinkOn ? 'highlight' : 'downplay')
}
function startBlink() {
  stopBlink()
  blinkOn = true
  applyBlink()
  blinkTimer = setInterval(applyBlink, 550)
}
function stopBlink() {
  if (blinkTimer) {
    clearInterval(blinkTimer)
    blinkTimer = null
  }
}
function clearMatch() {
  stopBlink()
  downplayAll()
  matchNames.value = []
}
function downplayAll() {
  dispatchMatch('downplay')
}
function dispatchMatch(type: 'highlight' | 'downplay') {
  for (const p of matchPoints.value) {
    const target = charts[p.chartId]
    if (!target) continue
    target.dispatchAction({ type, seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
  }
}
function doSearch() {
  const kw = searchKw.value.trim()
  if (!kw) {
    clearMatch()
    return
  }
  const meta = data.value?.meta || {}
  const hits: string[] = []
  for (const code of Object.keys(meta)) {
    if (meta[code]?.name.includes(kw)) hits.push(code)
  }
  if (!hits.length) {
    clearMatch()
    ElMessage.warning(`未找到名称包含「${kw}」的${unitName.value}`)
    return
  }
  if (hits.length > 200) hits.length = 200
  stopBlink()
  matchNames.value = hits
  startBlink()
}

// ── 点击跳转板块详情（概念→同花顺 / 行业→东财ETF） ──
function onChartClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.code ?? e?.data?.name
  if (!code || !data.value) return
  const link = data.value.meta[code]?.link
  if (link) window.open(link, '_blank', 'noopener')
}

async function loadAll() {
  loading.value = true
  try {
    const res = await vibeApi.getBoardQuadrant(props.scope)
    data.value = (res as any)?.data ?? null
  } catch (e) {
    console.error(`加载${heroTitle.value}失败`, e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAll()
})
watch(() => props.scope, () => {
  clearMatch()
  loadAll()
})
onBeforeUnmount(() => {
  stopBlink()
  downplayAll()
})
</script>

<style scoped lang="scss">
.board-quadrant-page {
  .block {
    margin-bottom: 16px;
    padding: 16px;
    background: var(--el-bg-color);
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);

    .block-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;

      .block-title {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 15px;
        font-weight: 600;
      }

      .block-hint {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .kpi-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    .kpi-cell {
      padding: 12px 16px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border: 1px solid var(--el-border-color-lighter);

      .kpi-label {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }

      .kpi-value {
        margin: 6px 0;
        font-size: 22px;
        font-weight: 600;

        .kpi-sep {
          margin: 0 6px;
          color: var(--el-text-color-placeholder);
          font-weight: 400;
        }
      }

      .kpi-sub {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .control-panel {
    .control-main {
      .search-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }

      .search-row {
        display: flex;
        align-items: center;
        gap: 8px;

        .search-input {
          width: 260px;
        }
      }
    }

    .panel-hint {
      margin-top: 12px;
      font-size: 12px;
      color: var(--el-text-color-secondary);

      .warn-hint {
        margin-left: 10px;
        color: var(--el-color-warning);
      }
    }
  }

  .chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
    gap: 16px;

    .chart-card {
      margin-bottom: 0;

      .concept-chart {
        .concept-chart-inner {
          width: 100%;
        }
        .map-chart {
          height: 440px;
        }
      }
    }
  }

  .quadrant-tip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 18px;
    padding: 10px 12px;
    margin-top: 10px;
    border-radius: 8px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-lighter);

    .qt-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
      white-space: nowrap;
    }

    .qt-dot {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      display: inline-block;
    }
    .qt-red { background: #fbe0e0; }
    .qt-yellow { background: #fdf3d1; }
    .qt-blue { background: #e3f0fd; }
    .qt-green { background: #e8f7e2; }
  }

  .accent {
    color: var(--el-color-warning);
  }
}

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: 1fr !important;
  }
}
</style>