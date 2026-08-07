<template>
  <div class="strategy-screener">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        策略
      </h1>
      <p class="page-description">基于本地行情数据 · 策略筛选与评分排序</p>
      <p v-if="computedAt" class="computed-at">结果更新于 {{ computedAt }}</p>
      <div class="header-actions">
        <el-select v-model="asOf" placeholder="选择交易日" size="small" style="width: 150px" filterable @change="onAsOfChange">
          <el-option v-for="d in tradeDates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button size="small" :loading="runningAll" @click="runAll(true)">
          <el-icon><Refresh /></el-icon>
          运行全部
        </el-button>
      </div>
    </div>

    <!-- 策略卡片 -->
    <el-card class="strategy-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <span>策略池 ({{ strategies.length }})</span>
          <el-tag size="small" type="info" effect="plain">点击卡片查看选股结果</el-tag>
        </div>
      </template>
      <el-empty v-if="!loading && strategies.length === 0" description="暂无可用策略" :image-size="120" />
      <div v-else class="strategy-grid">
        <div
          v-for="s in strategies"
          :key="s.id"
          class="strategy-card"
          :class="{ active: activeStrategy === s.id, loading: runningAll }"
          @click="handleRun(s)"
        >
          <div class="strategy-top">
            <div class="strategy-name">{{ s.name }}</div>
            <el-tag v-if="hitCounts[s.id] !== undefined" size="small" :type="hitCounts[s.id] > 0 ? 'success' : 'info'">
              {{ hitCounts[s.id] }} 只
            </el-tag>
            <el-icon v-else class="spinner"><Loading /></el-icon>
          </div>
          <div class="strategy-desc">{{ s.description }}</div>
          <div class="strategy-tags">
            <el-tag v-for="t in s.tags" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 结果 -->
    <el-card v-if="result || showAllResult" class="result-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <span>
            <el-icon><DataLine /></el-icon>
            {{ showAll ? '全部策略' : (activeStrategyName || '') }} 命中 {{ displayRows.length }} 只
            <span class="text-muted">· {{ asOf }}</span>
          </span>
          <div class="header-actions">
            <el-button size="small" :type="showAll ? 'primary' : 'default'" @click="toggleShowAll" :disabled="!allStrategyRunning">
              <el-icon><Connection /></el-icon>
              全部
            </el-button>
            <el-button size="small" @click="batchAddToFavorites" :disabled="displayRows.length === 0">
              <el-icon><Star /></el-icon>
              批量加自选
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="displayRows" stripe border size="small" style="width: 100%">
        <el-table-column prop="code" label="代码" width="110">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.code}`" target="_blank">{{ row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="120">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.code}`" target="_blank">{{ row.name || row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="close" label="收盘价" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.close != null">{{ row.close.toFixed(2) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="change_pct" label="涨跌幅" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.change_pct != null" :class="row.change_pct >= 0 ? 'text-red' : 'text-green'">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ (row.change_pct * 100).toFixed(2) }}%
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol_ratio" label="量比" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.vol_ratio != null">{{ row.vol_ratio.toFixed(2) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="90" align="right" sortable>
          <template #default="{ row }">
            <span class="score-text">{{ (row.score ?? 0).toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="addToFavorite(row)">加自选</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-else-if="!loading && !runningAll" description="点击策略卡片查看选股结果" :image-size="160" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { TrendCharts, DataLine, Refresh, Loading, Connection, Star } from '@element-plus/icons-vue'
import { strategyApi, type StrategyMeta, type StrategyRunItem, type StrategyRunAllItem } from '@/api/strategy'
import { favoritesApi } from '@/api/favorites'

defineOptions({ name: 'StrategyScreener' })

const strategies = ref<StrategyMeta[]>([])
const loading = ref(false)
const runningAll = ref(false)
const hitCounts = ref<Record<string, number>>({})
const activeStrategy = ref<string | null>(null)
const activeStrategyName = ref('')
const result = ref<{ items: StrategyRunItem[]; as_of: string; strategy_id: string; strategy_name: string } | null>(null)
const showAllResult = ref<StrategyRunAllItem[] | null>(null)
const showAll = ref(false)
const asOf = ref('')
const tradeDates = ref<string[]>([])
const computedAt = ref('')
const allStrategyRunning = ref(false)

const displayRows = computed<StrategyRunItem[]>(() => {
  if (showAll.value && showAllResult.value) {
    const seen = new Set<string>()
    const merged: StrategyRunItem[] = []
    for (const s of showAllResult.value) {
      for (const row of s.top) {
        if (!seen.has(row.code)) {
          seen.add(row.code)
          merged.push(row)
        }
      }
    }
    return merged
  }
  return result.value?.items ?? []
})

const loadStrategies = async () => {
  loading.value = true
  try {
    // 并行加载策略列表与交易日下拉
    const [listRes, datesRes] = await Promise.allSettled([
      strategyApi.list(),
      strategyApi.tradeDates(30),
    ])
    if (listRes.status === 'fulfilled') {
      const list = (listRes.value as any)?.data ?? listRes.value
      strategies.value = Array.isArray(list) ? list : []
    } else {
      ElMessage.error('加载策略列表失败')
    }
    if (datesRes.status === 'fulfilled') {
      const dres = datesRes.value as any
      const dates = dres?.data?.dates ?? []
      tradeDates.value = Array.isArray(dates) ? dates : []
    }
    // 首次进入自动加载全部策略结果（后端缓存命中时秒回，否则后台计算）
    if (strategies.value.length > 0) {
      await runAll()
    }
  } catch (e) {
    ElMessage.error('加载策略失败')
  } finally {
    loading.value = false
  }
}

const runAll = async (refresh = false) => {
  if (runningAll.value) return
  runningAll.value = true
  try {
    const res = await strategyApi.runAll({ as_of: asOf.value || null, limit: 30, refresh })
    const data = (res as any)?.data ?? res
    if (data?.as_of) asOf.value = data.as_of
    if (data?.computed_at) computedAt.value = data.computed_at
    const counts: Record<string, number> = {}
    for (const s of data?.strategies ?? []) {
      counts[s.id] = s.count
    }
    hitCounts.value = counts
    showAllResult.value = data?.strategies ?? null
    allStrategyRunning.value = true
    const strategiesData = data?.strategies ?? []
    // 默认展示第一个策略的完整结果（行数与命中数一致），其余策略点击卡片切换
    if (!activeStrategy.value || !showAll.value) {
      const first = strategiesData[0]
      if (first) {
        activeStrategy.value = first.id
        activeStrategyName.value = first.name
        showAll.value = false
        result.value = {
          strategy_id: first.id,
          strategy_name: first.name,
          as_of: data.as_of,
          total: first.count,
          items: first.top ?? [],
        }
      }
    } else {
      const cur = strategiesData.find((x: any) => x.id === activeStrategy.value)
      if (cur) {
        result.value = {
          strategy_id: cur.id,
          strategy_name: cur.name,
          as_of: data.as_of,
          total: cur.count,
          items: cur.top ?? [],
        }
      }
    }
  } catch (e) {
    ElMessage.error('运行全部策略失败')
  } finally {
    runningAll.value = false
  }
}

const runSingle = async (id: string) => {
  try {
    const res = await strategyApi.run({ strategy_id: id, as_of: asOf.value || null, limit: 100 })
    const data = (res as any)?.data ?? res
    if (data?.as_of) asOf.value = data.as_of
    result.value = data
    if (data?.strategy_id) {
      hitCounts.value = { ...hitCounts.value, [data.strategy_id]: data.total ?? 0 }
    }
  } catch (e) {
    ElMessage.error('运行策略失败')
  }
}

const handleRun = (s: StrategyMeta) => {
  activeStrategy.value = s.id
  activeStrategyName.value = s.name
  showAll.value = false
  // 立即用后端缓存/已加载的 run-all 结果展示，无需等待慢接口
  const cachedStrategy = showAllResult.value?.find((x) => x.id === s.id)
  if (cachedStrategy) {
    result.value = {
      strategy_id: s.id,
      strategy_name: cachedStrategy.name,
      as_of: asOf.value,
      total: cachedStrategy.count,
      items: cachedStrategy.top ?? [],
    }
  }
  // 后台刷新完整明细（limit=100），完成后更新表格
  runSingle(s.id)
}

const onAsOfChange = () => {
  // 切换交易日：清空当前明细并重新加载该交易日结果（后端缓存命中则秒回）
  result.value = null
  showAllResult.value = null
  activeStrategy.value = null
  runAll()
}

const toggleShowAll = () => {
  showAll.value = !showAll.value
  if (showAll.value && !showAllResult.value) {
    runAll()
  }
}

const addToFavorite = async (row: StrategyRunItem) => {
  try {
    const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
    ElMessage.success(`已加入自选：${row.name || row.code}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '加自选失败')
  }
}

const batchAddToFavorites = async () => {
  const rows = displayRows.value
  if (!rows.length) return
  let added = 0
  for (const row of rows) {
    try {
      const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
      if ((res as any)?.success !== false) added++
    } catch { /* 忽略单只失败 */ }
  }
  ElMessage.success(`已添加 ${added} 只到自选`)
}

onMounted(() => {
  loadStrategies()
})
</script>

<style lang="scss" scoped>
.strategy-screener {
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;

  .page-header {
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 2px solid var(--el-border-color-lighter);

    .page-title {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 28px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;

      .el-icon {
        color: var(--el-color-primary);
        font-size: 28px;
      }
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0 0 16px 0;
      font-size: 14px;
    }

    .computed-at {
      color: var(--el-color-success);
      margin: 0 0 12px 0;
      font-size: 13px;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }

  .strategy-panel {
    margin-bottom: 24px;
    border-radius: 12px;
    overflow: hidden;

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
      padding: 14px 20px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      span {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .strategy-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 16px;
    }

    .strategy-card {
      padding: 16px;
      background: var(--el-fill-color-light);
      border-radius: 12px;
      cursor: pointer;
      border: 2px solid transparent;
      transition: all 0.3s ease;

      &:hover {
        background: var(--el-fill-color-lighter);
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
      }

      &.active {
        border-color: var(--el-color-primary);
        background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
      }

      &.loading {
        opacity: 0.7;
        pointer-events: none;
      }

      .strategy-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;

        .strategy-name {
          font-size: 16px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }

        .spinner {
          color: var(--el-color-primary);
        }
      }

      .strategy-desc {
        font-size: 13px;
        color: var(--el-text-color-regular);
        margin-bottom: 10px;
        line-height: 1.4;
      }

      .strategy-tags {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }
    }
  }

  .result-panel {
    border-radius: 12px;
    overflow: hidden;

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-color-success-light-9) 0%, var(--el-color-success-light-8) 100%);
      padding: 14px 20px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      span {
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .text-muted {
        color: var(--el-text-color-secondary);
        font-weight: 400;
      }
    }
  }

  .text-red { color: var(--el-color-danger); font-weight: 600; }
  .text-green { color: var(--el-color-success); font-weight: 600; }
  .text-muted { color: var(--el-text-color-secondary); }
  .score-text { font-weight: 600; color: var(--el-color-primary); }
}

html.dark {
  .strategy-screener {
    .strategy-panel,
    .result-panel {
      :deep(.el-card__header) {
        background: linear-gradient(135deg, var(--el-bg-color-overlay) 0%, var(--el-fill-color-darker) 100%);
      }
    }
    .strategy-card {
      background: var(--el-fill-color-darker);
      &:hover { background: var(--el-fill-color-dark); }
      &.active {
        background: linear-gradient(135deg, var(--el-fill-color-dark) 0%, var(--el-fill-color) 100%);
        border-color: var(--el-text-color-secondary);
      }
    }
  }
}
</style>