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

    <!-- 领涨 / 领跌 / 资金流 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 概念涨跌</span>
      </div>
      <div class="concept-chart">
        <VChart v-if="chartData" :option="conceptChartOption" autoresize class="concept-chart-inner" />
        <el-empty v-else :image-size="48" description="暂无涨跌数据" />
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
import { ref, computed, onMounted } from 'vue'
import { Refresh, DataAnalysis, TrendCharts, Odometer } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { vibeApi } from '@/api/vibe'
import type { ConceptAnalysis } from '@/api/vibe'
import { fmtPct, fmtSigned, clsByVal } from '@/utils/format'

echartsUse([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const MONO = "'SFMono-Regular', ui-monospace, Menlo, monospace"

const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
const loading = ref(false)
const data = ref<ConceptAnalysis | null>(null)

// 同花顺概念详情页链接：cid 是概念板块代码，非股票代码
function thsConceptUrl(code: string): string {
  return `https://q.10jqka.com.cn/gn/detail/code/${code}/`
}

// ── 领涨 / 领跌 双向条形图 ──
const chartData = computed(() => {
  const c = data.value
  return !!(c && ((c.gainers || []).length || (c.losers || []).length))
})

const conceptChartOption = computed<EChartsOption>(() => {
  const g = (data.value?.gainers || []).slice(0, 10)
  const l = (data.value?.losers || []).slice(0, 10)
  const cats = [...g.map(x => x.name), ...l.map(x => x.name)]
  const vals = [...g.map(x => Number(x.pct_chg)), ...l.map(x => -Math.abs(Number(x.pct_chg)))]
  return {
    animationDuration: 600,
    grid: { left: 8, right: 48, top: 10, bottom: 6, containLabel: true },
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
        const v = Number(p?.value ?? 0)
        const cls = v >= 0 ? '#f56c6c' : '#67c23a'
        return `${p?.name}<br/><b style="color:${cls};font-family:${MONO}">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</b>`
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: cats,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#4a5568', fontSize: 12 },
    },
    series: [{
      type: 'bar',
      barWidth: 9,
      data: vals.map((v, i) => ({
        value: v,
        itemStyle: { color: i < g.length ? '#f56c6c' : '#67c23a', borderRadius: 3 },
      })),
    }],
  }
})

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