<template>
  <div class="concept-page">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ today }} · 概念分析</h2>
          <p class="page-hero-sub">概念涨跌 / 资金流向一屏看全</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAnalysis">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 概念宽度 KPI -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Odometer /></el-icon> 概念宽度</span>
        <span v-if="data?.as_of" class="block-hint">更新于 {{ data.as_of }}</span>
      </div>
      <div class="kpi-row">
        <div class="kpi-cell">
          <div class="kpi-label">概念总数</div>
          <div class="kpi-value accent">{{ data?.total ?? '—' }}</div>
          <div class="kpi-sub">同花顺概念板块</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">上涨 / 下跌</div>
          <div class="kpi-value">
            <span class="up">{{ data?.breadth?.up ?? '—' }}</span><span class="kpi-sep">/</span><span class="down">{{ data?.breadth?.down ?? '—' }}</span>
          </div>
          <div class="kpi-sub">概念涨跌家数</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">平均涨幅</div>
          <div class="kpi-value accent" :class="clsByVal(data?.breadth?.avg_pct, '')">{{ fmtPct(data?.breadth?.avg_pct) }}</div>
          <div class="kpi-sub">全概念均值</div>
        </div>
      </div>
    </section>

    <!-- 概念地图：涨跌幅 × 资金净流入 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 概念地图 · 涨跌 × 资金</span>
        <div class="map-search">
          <span v-if="!matchNames.length" class="block-hint">点击圆点跳转同花顺 · 滚轮缩放</span>
          <el-input
            v-model="searchKw"
            size="small"
            clearable
            placeholder="输入概念名称查找（如：半导体）"
            class="map-search-input"
            @keyup.enter="doSearch"
            @clear="clearMatch"
          />
          <el-button
            size="small"
            type="primary"
            plain
            :icon="Search"
            :disabled="!searchKw.trim()"
            @click="doSearch"
          >查找</el-button>
          <el-button v-if="matchNames.length" size="small" @click="clearMatch">清除高亮</el-button>
        </div>
      </div>
      <div class="concept-chart">
        <VChart
          v-if="mapReady"
          ref="chartRef"
          :option="mapOption"
          autoresize
          class="concept-chart-inner map-chart"
          @click="onMapClick"
        />
        <el-empty v-else :image-size="48" description="暂无数据" />
      </div>
      <div class="quadrant-tip">
        <span class="qt-item"><i class="qt-dot qt-red" />右上 流入+上涨 · 强势共振</span>
        <span class="qt-item"><i class="qt-dot qt-yellow" />左上 流出+上涨 · 缩量上行</span>
        <span class="qt-item"><i class="qt-dot qt-blue" />右下 流入+下跌 · 低位承接</span>
        <span class="qt-item"><i class="qt-dot qt-green" />左下 流出+下跌 · 弱势杀跌</span>
      </div>
    </section>

    <!-- 资金净流入分布 / 资金流榜 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Money /></el-icon> 资金净流入分布</span>
        <span class="block-hint">全量概念按净流入排序 · 流入红 / 流出绿 · 点击跳转 · 滚轮缩放</span>
      </div>
      <div class="concept-chart">
        <VChart
          v-if="data?.concepts?.length"
          :option="flowOption"
          autoresize
          class="concept-chart-inner flow-chart"
          @click="onFlowClick"
        />
        <el-empty v-else :image-size="48" description="暂无数据" />
      </div>
      <div class="rank-grid">
        <el-card shadow="never" class="rank-card">
          <div class="rank-title accent">💰 资金流入榜</div>
          <div v-for="(c, i) in data?.money_leaders || []" :key="c.code" class="rank-row">
            <span class="rank-idx">{{ i + 1 }}</span>
            <span class="rank-name">{{ c.name }}</span>
            <span class="rank-lead">
              <a
                v-if="c.lead_code"
                :href="thsConceptUrl(c.lead_code)"
                target="_blank"
                rel="noopener"
                class="stock-name"
              >{{ c.lead_name }}</a>
              <template v-else>{{ c.lead_name }}</template>
            </span>
            <span class="rank-pct up">{{ fmtSigned(c.money_flow) }}亿</span>
          </div>
          <el-empty v-if="!data?.money_leaders?.length" :image-size="48" description="暂无数据" />
        </el-card>
        <el-card shadow="never" class="rank-card">
          <div class="rank-title accent">🚰 资金流出榜</div>
          <div v-for="(c, i) in data?.money_followers || []" :key="c.code" class="rank-row">
            <span class="rank-idx">{{ i + 1 }}</span>
            <span class="rank-name">{{ c.name }}</span>
            <span class="rank-lead">
              <a
                v-if="c.lead_code"
                :href="thsConceptUrl(c.lead_code)"
                target="_blank"
                rel="noopener"
                class="stock-name"
              >{{ c.lead_name }}</a>
              <template v-else>{{ c.lead_name }}</template>
            </span>
            <span class="rank-pct down">{{ fmtSigned(c.money_flow) }}亿</span>
          </div>
          <el-empty v-if="!data?.money_followers?.length" :image-size="48" description="暂无数据" />
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, DataAnalysis, TrendCharts, Odometer, Money } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { vibeApi } from '@/api/vibe'
import type { ConceptAnalysis } from '@/api/vibe'
import { fmtPct, fmtSigned, clsByVal } from '@/utils/format'

echartsUse([CanvasRenderer, BarChart, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent])

const MONO = "'SFMono-Regular', ui-monospace, Menlo, monospace"

const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
const loading = ref(false)
const data = ref<ConceptAnalysis | null>(null)

// 同花顺概念详情页链接：cid 是概念板块代码，非股票代码
function thsConceptUrl(code: string): string {
  return `https://q.10jqka.com.cn/gn/detail/code/${code}/`
}

// 图表点击统一跳转同花顺概念详情页
function openThs(code: string | number | undefined | null) {
  if (!code) return
  window.open(thsConceptUrl(String(code)), '_blank', 'noopener')
}

const mapReady = computed(() => !!(data.value?.concepts?.length))

// ── 概念查找：匹配的概念圆点高亮 + 闪烁放大 ──
const searchKw = ref('')
const matchNames = ref<string[]>([])
// 图表实例引用：闪烁通过 dispatchAction 完成，避免每次重建 option 打断 tooltip
const chartRef = ref<{ getInstance?: () => any } | null>(null)
let blinkTimer: ReturnType<typeof setInterval> | null = null
let blinkOn = false

// 匹配概念在散点图中的位置（seriesIndex/dataIndex，与 mapOption 分组顺序一致）
const matchPoints = computed(() => {
  const set = new Set(matchNames.value)
  if (!set.size) return [] as { seriesIndex: number; dataIndex: number }[]
  const list = data.value?.concepts || []
  const groups: object[][] = [[], []]
  for (const c of list) {
    groups[(Number(c.pct_chg) || 0) >= 0 ? 0 : 1].push(c)
  }
  const pts: { seriesIndex: number; dataIndex: number }[] = []
  groups.forEach((arr, seriesIndex) => {
    arr.forEach((c: any, dataIndex) => {
      if (set.has(c.name)) pts.push({ seriesIndex, dataIndex })
    })
  })
  return pts
})

function applyBlink() {
  blinkOn = !blinkOn
  const inst = chartRef.value?.getInstance?.()
  if (!inst) return
  for (const p of matchPoints.value) {
    inst.dispatchAction({ type: blinkOn ? 'highlight' : 'downplay', seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
  }
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
function downplayAll() {
  const inst = chartRef.value?.getInstance?.()
  if (!inst) return
  for (const p of matchPoints.value) {
    inst.dispatchAction({ type: 'downplay', seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
  }
}
function clearMatch() {
  stopBlink()
  downplayAll()
  matchNames.value = []
}
function doSearch() {
  const kw = searchKw.value.trim()
  if (!kw) {
    clearMatch()
    return
  }
  const hits = (data.value?.concepts || [])
    .filter(c => c.name.includes(kw))
    .map(c => c.name)
  if (!hits.length) {
    clearMatch()
    ElMessage.warning(`未找到包含「${kw}」的概念`)
    return
  }
  stopBlink()
  matchNames.value = hits
  startBlink()
}
onBeforeUnmount(() => {
  stopBlink()
  downplayAll()
})

// ── 概念地图：涨跌幅(Y) × 资金净流入(X) 四象限散点图，293 全量 ──
const mapOption = computed<EChartsOption>(() => {
  const list = data.value?.concepts || []
  const flows = list.map(c => Number(c.money_flow) || 0)
  const chgs = list.map(c => Number(c.pct_chg) || 0)
  const [xMin, xMax] = [Math.min(0, ...flows), Math.max(0, ...flows)]
  const [yMin, yMax] = [Math.min(0, ...chgs), Math.max(0, ...chgs)]
  const padX = (xMax - xMin) * 0.08 || 1
  const padY = (yMax - yMin) * 0.12 || 0.2

  const matched = new Set(matchNames.value)
  const upData: object[] = []
  const downData: object[] = []
  for (const c of list) {
    const isMatch = matched.has(c.name)
    const item: Record<string, unknown> = {
      name: c.name,
      lead_code: c.lead_code,
      turnover: c.turnover,
      value: [Number(c.money_flow) || 0, Number(c.pct_chg) || 0],
    }
    if (isMatch) {
      const pct = Number(c.pct_chg) || 0
      // 被查找的概念：显著放大 + 宝蓝高亮（与红涨/绿跌对比最强）+ 光晕 + 数值标签（闪烁由 dispatchAction 驱动）
      item.symbolSize = 22
      item.itemStyle = {
        color: '#2563eb',
        borderColor: '#fff',
        borderWidth: 2.5,
        shadowBlur: 18,
        shadowColor: 'rgba(37,99,235,.95)',
      }
      item.label = {
        show: true,
        position: 'right',
        distance: 6,
        color: '#1d4ed8',
        fontSize: 13,
        fontWeight: 700,
        formatter: `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`,
      }
    }
    ;((Number(c.pct_chg) || 0) >= 0 ? upData : downData).push(item)
  }

  return {
    animationDuration: 600,
    grid: { left: 56, right: 28, top: 52, bottom: 52 },
    legend: {
      top: 8,
      left: 10,
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { color: '#4a5568', fontSize: 12 },
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (p: any) => {
        const d = p?.data ?? {}
        const v = Array.isArray(d.value) ? d.value.map(Number) : [0, 0]
        const cCls = v[1] >= 0 ? '#f56c6c' : '#67c23a'
        const fCls = v[0] >= 0 ? '#f56c6c' : '#67c23a'
        const turn = d.turnover != null ? `${Number(d.turnover).toFixed(2)}%` : '—'
        return `<b>${d.name || p?.name || ''}</b><br/>`
          + `涨跌 <b style="color:${cCls};font-family:${MONO}">${v[1] >= 0 ? '+' : ''}${v[1].toFixed(2)}%</b><br/>`
          + `资金 <b style="color:${fCls};font-family:${MONO}">${fmtSigned(v[0])}亿</b><br/>`
          + `换手 <span style="font-family:${MONO}">${turn}</span>`
      },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseWheel: true, moveOnMouseMove: true },
    ],
    xAxis: {
      name: '资金净流入（亿元）',
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: 'value',
      min: xMin - padX,
      max: xMax + padX,
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      name: '涨跌幅（%）',
      nameLocation: 'middle',
      nameGap: 36,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: 'value',
      min: yMin - padY,
      max: yMax + padY,
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      name: '上涨',
      type: 'scatter',
      symbolSize: 9,
      itemStyle: { color: 'rgba(245,108,108,.72)' },
      emphasis: {
        scale: 2.6,
        itemStyle: { borderColor: '#2d3748', borderWidth: 1, shadowBlur: 28, shadowColor: 'rgba(37,99,235,.9)' },
      },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: 'rgba(148,163,184,.65)', type: 'dashed' },
        label: { show: false },
        data: [{ xAxis: 0 }, { yAxis: 0 }],
      },
      markArea: {
        silent: true,
        label: { fontSize: 10, color: 'rgba(74,85,104,.55)' },
        data: [
          [
            { name: '强势 · 流入+上涨', coord: [0, 0], itemStyle: { color: 'rgba(255,235,238,.6)' } },
            { coord: [xMax + padX, yMax + padY] },
          ],
          [
            { name: '缩量 · 流出+上涨', coord: [xMin - padX, 0], itemStyle: { color: 'rgba(255,250,225,.6)' } },
            { coord: [0, yMax + padY] },
          ],
          [
            { name: '承接 · 流入+下跌', coord: [0, yMin - padY], itemStyle: { color: 'rgba(235,245,255,.6)' } },
            { coord: [xMax + padX, 0] },
          ],
          [
            { name: '弱势 · 流出+下跌', coord: [xMin - padX, yMin - padY], itemStyle: { color: 'rgba(240,249,240,.6)' } },
            { coord: [0, 0] },
          ],
        ],
      },
      data: upData,
    }, {
      name: '下跌',
      type: 'scatter',
      symbolSize: 9,
      itemStyle: { color: 'rgba(103,194,58,.72)' },
      emphasis: {
        scale: 2.6,
        itemStyle: { borderColor: '#2d3748', borderWidth: 1, shadowBlur: 28, shadowColor: 'rgba(37,99,235,.9)' },
      },
      data: downData,
    }],
  }
})

// ── 资金净流入分布：293 全量按净流入排序的横向条形图 ──
const flowOption = computed<EChartsOption>(() => {
  const list = [...(data.value?.concepts || [])]
    .sort((a, b) => Number(b.money_flow) - Number(a.money_flow))
  return {
    animationDuration: 600,
    grid: { left: 8, right: 64, top: 8, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(43, 108, 176, .06)' } },
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (ps: any) => {
        const p = Array.isArray(ps) ? ps[0] : ps
        const d = p?.data ?? {}
        const v = Number(d.value) || 0
        const cls = v >= 0 ? '#f56c6c' : '#67c23a'
        const chg = Number(d.chg) || 0
        const cCls = chg >= 0 ? '#f56c6c' : '#67c23a'
        return `<b>${d.name || p?.name || ''}</b><br/>`
          + `资金 <b style="color:${cls};font-family:${MONO}">${fmtSigned(v)}亿</b><br/>`
          + `涨跌 <b style="color:${cCls};font-family:${MONO}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</b>`
      },
    },
    // 293 个概念一屏放不下：支持鼠标滚轮/拖动缩放
    dataZoom: [
      { type: 'inside', yAxisIndex: 0 },
      { type: 'slider', yAxisIndex: 0, right: 4, width: 14, borderRadius: 6, bottom: 6 },
    ],
    xAxis: {
      type: 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10, formatter: '{value}亿' },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: list.map(c => c.name),
      inverse: true, // 净流入最多排最上方
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#4a5568', fontSize: 12 },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 10,
      data: list.map(c => {
        const v = Number(c.money_flow) || 0
        return {
          name: c.name,
          lead_code: c.lead_code,
          chg: c.pct_chg,
          value: v,
          itemStyle: {
            color: v >= 0 ? '#f56c6c' : '#67c23a',
            borderRadius: 2,
          },
        }
      }),
    }],
  }
})

function onMapClick(e: any) {
  if (e?.componentType !== 'series') return
  openThs(e?.data?.lead_code)
}

function onFlowClick(e: any) {
  if (e?.componentType !== 'series') return
  openThs(e?.data?.lead_code)
}

async function loadAnalysis() {
  loading.value = true
  try {
    const res = await vibeApi.getConceptAnalysis()
    data.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('加载概念分析失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // 首次进入自动加载概念热度数据，避免"暂无数据、手动点加载"
  loadAnalysis()
})
</script>

<style lang="scss" scoped>
.concept-page {
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

    .map-search {
      display: flex;
      align-items: center;
      gap: 8px;

      .map-search-input {
        width: 220px;
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

  .concept-chart {
    margin-bottom: 14px;

    .concept-chart-inner {
      width: 100%;
      height: 420px;
    }

    .map-chart {
      height: 400px;
    }
  }

  .quadrant-tip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 18px;
    padding: 10px 12px;
    margin-bottom: 4px;
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

  .rank-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;

    .rank-card {
      max-width: none;

      .rank-title {
        font-weight: 600;
        margin-bottom: 10px;
      }

      .rank-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 0;
        border-bottom: 1px dashed var(--el-border-color-lighter);

        .rank-idx {
          width: 18px;
          color: var(--el-text-color-placeholder);
          font-size: 12px;
        }

        .rank-name {
          flex: 1;
          font-size: 13px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .rank-lead {
          color: var(--el-text-color-secondary);
          font-size: 12px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 90px;

          .stock-name {
            color: var(--el-color-primary);
            text-decoration: none;
          }
          .stock-name:hover {
            text-decoration: underline;
          }
        }

        .rank-pct {
          font-size: 13px;
          font-weight: 600;
          white-space: nowrap;
        }
      }
    }
  }

  .accent {
    color: var(--el-color-warning);
  }
}

@media (max-width: 1100px) {
  .rank-grid {
    grid-template-columns: 1fr;

    .rank-card {
      max-width: none;
    }
  }
  .concept-chart-inner {
    height: 320px;
  }
}
</style>