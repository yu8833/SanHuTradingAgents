<template>
  <div class="concept-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="title-block">
        <h1 class="page-title">
          <el-icon class="title-icon"><DataAnalysis /></el-icon>
          {{ today }} · 概念分析
        </h1>
        <p class="page-subtitle">概念实时行情 / 轮动 RPS / 领涨领跌一屏看全</p>
      </div>
      <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
        刷新
      </el-button>
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
          <div class="kpi-value accent" :class="pctClass(data?.breadth?.avg_pct)">{{ sign(data?.breadth?.avg_pct) }}{{ formatPct(data?.breadth?.avg_pct) }}%</div>
          <div class="kpi-sub">全概念均值</div>
        </div>
      </div>
    </section>

    <!-- 领涨 / 领跌 / 资金流 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 概念热度</span>
      </div>
      <div class="rank-grid">
        <el-card shadow="never" class="rank-card">
          <div class="rank-title up">🔥 领涨概念</div>
          <div v-for="(c, i) in data?.gainers || []" :key="c.code" class="rank-row">
            <span class="rank-idx">{{ i + 1 }}</span>
            <span class="rank-name">{{ c.name }}</span>
            <span class="rank-lead">
              <router-link v-if="c.lead_code" :to="`/stocks/${c.lead_code}`" class="stock-link">{{ c.lead_name }}</router-link>
              <template v-else>{{ c.lead_name }}</template>
            </span>
            <span class="rank-pct up">{{ sign(c.pct_chg) }}{{ formatPct(c.pct_chg) }}%</span>
          </div>
          <el-empty v-if="!data?.gainers?.length" :image-size="48" description="暂无数据" />
        </el-card>

        <el-card shadow="never" class="rank-card">
          <div class="rank-title down">🌀 领跌概念</div>
          <div v-for="(c, i) in data?.losers || []" :key="c.code" class="rank-row">
            <span class="rank-idx">{{ i + 1 }}</span>
            <span class="rank-name">{{ c.name }}</span>
            <span class="rank-lead">
              <router-link v-if="c.lead_code" :to="`/stocks/${c.lead_code}`" class="stock-link">{{ c.lead_name }}</router-link>
              <template v-else>{{ c.lead_name }}</template>
            </span>
            <span class="rank-pct down">{{ sign(c.pct_chg) }}{{ formatPct(c.pct_chg) }}%</span>
          </div>
          <el-empty v-if="!data?.losers?.length" :image-size="48" description="暂无数据" />
        </el-card>

        <el-card shadow="never" class="rank-card">
          <div class="rank-title accent">💰 资金流榜</div>
          <div v-for="(c, i) in data?.money_leaders || []" :key="c.code" class="rank-row">
            <span class="rank-idx">{{ i + 1 }}</span>
            <span class="rank-name">{{ c.name }}</span>
            <span class="rank-lead">
              <router-link v-if="c.lead_code" :to="`/stocks/${c.lead_code}`" class="stock-link">{{ c.lead_name }}</router-link>
              <template v-else>{{ c.lead_name }}</template>
            </span>
            <span class="rank-pct up">{{ sign(c.money_flow) }}{{ fmtNum(c.money_flow) }}亿</span>
          </div>
          <el-empty v-if="!data?.money_leaders?.length" :image-size="48" description="暂无数据" />
        </el-card>
      </div>
    </section>

    <!-- 概念实时行情表 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Grid /></el-icon> 概念实时行情</span>
        <el-input
          v-model="keyword"
          placeholder="搜索概念 / 领涨股"
          clearable
          style="width: 220px"
          size="small"
        />
      </div>
      <el-table
        v-loading="loading"
        :data="filteredConcepts"
        stripe
        size="small"
        class="concept-table"
        :max-height="560"
      >
        <el-table-column label="概念" min-width="160">
          <template #default="{ row }">
            <span class="col-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌幅" width="110" align="right" sortable :sort-method="sortPct">
          <template #default="{ row }">
            <span :class="pctClass(row.pct_chg)">{{ sign(row.pct_chg) }}{{ formatPct(row.pct_chg) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="领涨股" min-width="120">
          <template #default="{ row }">
            <router-link v-if="row.lead_code" :to="`/stocks/${row.lead_code}`" class="col-lead stock-link">{{ row.lead_name || '—' }}</router-link>
            <span v-else class="col-lead">{{ row.lead_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="资金净流入" width="130" align="right" sortable :sort-method="sortMoney">
          <template #default="{ row }">
            <span :class="pctClass(row.money_flow)">{{ sign(row.money_flow) }}{{ fmtNum(row.money_flow) }}亿</span>
          </template>
        </el-table-column>
        <el-table-column label="换手" width="90" align="right">
          <template #default="{ row }">{{ row.turnover }}%</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!filteredConcepts.length && !loading" description="暂无概念数据" />
    </section>

    <!-- 概念轮动 RPS 矩阵 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Histogram /></el-icon> 概念轮动 RPS（热门概念多窗口涨幅）</span>
        <div class="head-actions">
          <el-button
            size="small"
            :type="rotationLoading ? 'info' : 'primary'"
            plain
            :icon="DataAnalysis"
            :loading="rotationLoading"
            @click="loadRotation"
          >
            {{ rotation?.rows?.length ? '刷新轮动' : '加载轮动' }}
          </el-button>
        </div>
      </div>
      <p v-if="!rotation?.rows?.length && !rotationLoading" class="rotation-hint">
        点击「加载轮动」计算当日热门概念在 5 / 10 / 20 / 60 日窗口的累计涨幅，识别主力资金脉络。
      </p>
      <el-table
        v-loading="rotationLoading"
        :data="rotation?.rows || []"
        stripe
        size="small"
        class="rotation-table"
        :max-height="460"
      >
        <el-table-column label="概念" min-width="150">
          <template #default="{ row }">
            <span class="col-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="今日" width="90" align="right">
          <template #default="{ row }">
            <span :class="pctClass(row.pct_chg)">{{ sign(row.pct_chg) }}{{ formatPct(row.pct_chg) }}%</span>
          </template>
        </el-table-column>
        <el-table-column
          v-for="w in rotation?.windows || []"
          :key="w"
          :label="w + '日'"
          width="90"
          align="right"
        >
          <template #default="{ row }">
            <span v-if="row.returns?.[w] != null" :class="pctClass(row.returns[w])">{{ sign(row.returns[w]) }}{{ formatPct(row.returns[w]) }}%</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="rotation?.rows?.length === 0 && !rotationLoading" description="暂无轮动数据" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Refresh, DataAnalysis, TrendCharts, Odometer, Grid, Histogram } from '@element-plus/icons-vue'
import { vibeApi } from '@/api/vibe'
import type { ConceptAnalysis, ConceptRotation } from '@/api/vibe'

const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
const loading = ref(false)
const rotationLoading = ref(false)
const data = ref<ConceptAnalysis | null>(null)
const rotation = ref<ConceptRotation | null>(null)
const keyword = ref('')

function sign(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? '+' : ''
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toFixed(2)
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toFixed(2)
}

function pctClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}

function sortPct(a: any, b: any): number {
  return (a.pct_chg ?? 0) - (b.pct_chg ?? 0)
}

function sortMoney(a: any, b: any): number {
  return (a.money_flow ?? 0) - (b.money_flow ?? 0)
}

const filteredConcepts = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return data.value?.concepts || []
  return (data.value?.concepts || []).filter(
    (c) => c.name.toLowerCase().includes(kw) || (c.lead_name || '').toLowerCase().includes(kw)
  )
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

async function loadRotation() {
  rotationLoading.value = true
  try {
    const res = await vibeApi.getConceptRotation(40)
    rotation.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('加载概念轮动失败', e)
  } finally {
    rotationLoading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadAnalysis(), loadRotation()])
}

onMounted(() => {
  // 首次进入自动加载概念行情 + 轮动 RPS，避免"暂无数据、手动点加载"
  loadAnalysis()
  loadRotation()
})
</script>

<style lang="scss" scoped>
.concept-page {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;

    .title-block {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      font-size: 22px;
      font-weight: 600;

      .title-icon {
        color: var(--el-color-primary);
      }
    }

    .page-subtitle {
      margin: 0;
      color: var(--el-text-color-secondary);
      font-size: 13px;
    }
  }

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

      .head-actions {
        display: flex;
        gap: 8px;
      }
    }

    .rotation-hint {
      margin: 4px 0 12px;
      color: var(--el-text-color-secondary);
      font-size: 13px;
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

  .rank-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;

    .rank-card {
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
        }

        .rank-pct {
          font-size: 13px;
          font-weight: 600;
          white-space: nowrap;
        }
      }
    }
  }

  .concept-table,
  .rotation-table {
    .col-name {
      font-weight: 500;
    }

    .col-lead {
      color: var(--el-text-color-secondary);
      font-size: 12px;
    }

    .stock-link {
      color: var(--el-color-primary);
      text-decoration: none;
      cursor: pointer;
    }

    .stock-link:hover {
      text-decoration: underline;
    }

    .muted {
      color: var(--el-text-color-placeholder);
    }
  }

  .up {
    color: var(--el-color-danger);
  }

  .down {
    color: var(--el-color-success);
  }

  .accent {
    color: var(--el-color-warning);
  }
}

@media (max-width: 1100px) {
  .rank-grid {
    grid-template-columns: 1fr;
  }
}
</style>