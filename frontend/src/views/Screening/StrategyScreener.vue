<template>
  <div class="strategy-screener app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">常用策略</h2>
          <p class="page-hero-sub">
            基于本地行情数据 · 策略筛选与评分排序
            <template v-if="computedAt"> · <el-icon :size="13"><Clock /></el-icon> 数据更新于 {{ computedAt }}</template>
          </p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-select v-model="asOf" placeholder="选择交易日" size="default" class="date-select" filterable @change="onAsOfChange">
          <el-option v-for="d in tradeDates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button type="primary" size="default" :loading="runningAll" @click="runAll(true)">
          <el-icon><Refresh /></el-icon>
          运行全部
        </el-button>
      </div>
    </div>

    <!-- 策略卡片 -->
    <el-card class="strategy-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot" />
            策略池
            <span class="panel-count">{{ strategies.length }}</span>
          </div>
          <el-tag size="small" type="info" effect="plain" round>点击卡片查看选股结果</el-tag>
        </div>
      </template>
      <el-empty v-if="!loading && strategies.length === 0" description="暂无可用策略" :image-size="120" />
      <div v-else class="strategy-grid">
        <div
          v-for="(s, i) in strategies"
          :key="s.id"
          class="strategy-card"
          :class="{ active: activeStrategy === s.id, loading: runningAll }"
          :style="{ '--sc': palette[i % palette.length] }"
          @click="handleRun(s)"
        >
          <div class="strategy-top">
            <div class="strategy-name">
              <span class="strategy-icon">
                <el-icon><component :is="cardIcon(i)" /></el-icon>
              </span>
              <span class="strategy-title">{{ s.name }}</span>
            </div>
            <div class="strategy-count">
              <template v-if="hitCounts[s.id] !== undefined">
                <span class="count-num">{{ hitCounts[s.id] }}</span>
                <span class="count-unit">只</span>
              </template>
              <el-icon v-else class="spinner"><Loading /></el-icon>
            </div>
          </div>
          <div class="strategy-desc">{{ s.description }}</div>
          <div class="strategy-tags">
            <el-tag v-for="t in s.tags" :key="t" size="small" effect="plain" class="strategy-tag">{{ t }}</el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 结果 -->
    <el-card v-if="result || showAllResult" class="result-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot result-dot" />
            <span class="result-title">{{ showAll ? '全部策略' : (activeStrategyName || '') }}</span>
            <span class="result-hit">命中 <b>{{ displayRows.length }}</b> 只</span>
            <span class="text-muted">· {{ asOf }}</span>
          </div>
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

      <el-table :data="displayRows" stripe border size="default" style="width: 100%" class="hit-table">
        <el-table-column prop="code" label="代码" min-width="110">
          <template #default="{ row }">
            <router-link class="link-code" :to="`/stocks/${row.code}`" target="_blank">{{ row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130">
          <template #default="{ row }">
            <router-link class="link-name" :to="`/stocks/${row.code}`" target="_blank">{{ row.name || row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="close" label="收盘价" min-width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.close != null">{{ row.close.toFixed(2) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="change_pct" label="涨跌幅" min-width="110" align="right">
          <template #default="{ row }">
            <el-tag v-if="row.change_pct != null" size="small" :type="row.change_pct >= 0 ? 'danger' : 'success'" effect="plain" round class="pct-tag">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ (row.change_pct * 100).toFixed(2) }}%
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol_ratio" label="量比" min-width="100" align="right" sortable>
          <template #default="{ row }">
            <span v-if="row.vol_ratio != null">{{ row.vol_ratio.toFixed(2) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <span class="score-badge" :style="{ '--sc': scoreColor(row.score) }">{{ (row.score ?? 0).toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="addToFavorite(row)">
              <el-icon><Star /></el-icon>
              加自选
            </el-button>
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
import {
  TrendCharts, Refresh, Loading, Connection, Star, Clock,
  Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard,
} from '@element-plus/icons-vue'
import { strategyApi, type StrategyMeta, type StrategyRunItem, type StrategyRunAllItem } from '@/api/strategy'
import { favoritesApi } from '@/api/favorites'

defineOptions({ name: 'StrategyScreener' })

// 策略卡片配色画板（通过 --sc 变量注入，保证深浅色主题下都清晰）
const palette = [
  '#1890ff', '#722ed1', '#13c2c2', '#fa8c16', '#f5222d', '#52c41a',
  '#eb2f96', '#2f54eb', '#a0d911', '#fadb14', '#fa541c', '#36cfc9',
]

// 策略卡片图标画板（轮流使用，避免千篇一律）
const cardIcons = [TrendCharts, Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard, TrendCharts]
const cardIcon = (i: number) => cardIcons[i % cardIcons.length]

// 评分配色：越高越偏暖红，越低越偏蓝
const scoreColor = (score: number) => {
  const s = score ?? 0
  if (s >= 80) return '#f5222d'
  if (s >= 60) return '#fa8c16'
  if (s >= 40) return '#faad14'
  if (s >= 20) return '#13c2c2'
  return '#1890ff'
}

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
  padding: 20px 24px 32px;
  max-width: 1680px;
  margin: 0 auto;

  /* ===== 顶部横幅（由全局 .page-hero 提供，此处仅保留选择器宽度） ===== */
  .date-select {
    width: 160px;
  }

  /* ===== 卡片通用 ===== */
  .strategy-panel,
  .result-panel {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--el-border-color-lighter);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);

    :deep(.el-card__header) {
      padding: 14px 22px;
      border-bottom: 1px solid var(--el-border-color-lighter);
      background: var(--el-fill-color-lighter);
    }

    :deep(.el-card__body) {
      padding: 20px 22px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;

      .card-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);

        .panel-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--el-color-primary);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
        }

        .result-dot {
          background: var(--el-color-success);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent);
        }

        .panel-count {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 22px;
          height: 20px;
          padding: 0 7px;
          border-radius: 20px;
          font-size: 12px;
          color: #fff;
          background: var(--el-color-primary);
        }

        .result-hit {
          font-weight: 400;
          color: var(--el-text-color-regular);
          b {
            color: var(--el-color-danger);
            font-size: 16px;
            margin: 0 2px;
          }
        }

        .text-muted { font-weight: 400; }
      }
    }
  }

  /* ===== 策略卡片 ===== */
  .strategy-panel {
    margin-bottom: 22px;

    .strategy-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
      gap: 16px;
    }

    .strategy-card {
      position: relative;
      padding: 18px;
      background: var(--el-fill-color-light);
      border-radius: 14px;
      cursor: pointer;
      border: 2px solid transparent;
      transition: all 0.25s ease;
      overflow: hidden;

      &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--sc), transparent);
        opacity: 0;
        transition: opacity 0.25s ease;
      }

      &:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        border-color: color-mix(in srgb, var(--sc) 45%, transparent);
        background: var(--el-bg-color);

        &::before { opacity: 1; }
      }

      &.active {
        border-color: var(--sc);
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--sc) 8%, transparent) 0%, transparent 60%),
          var(--el-bg-color);

        &::before { opacity: 1; }
      }

      &.loading {
        opacity: 0.7;
        pointer-events: none;
      }

      .strategy-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;

        .strategy-name {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;

          .strategy-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 38px;
            flex-shrink: 0;
            border-radius: 10px;
            font-size: 19px;
            color: var(--sc);
            background: color-mix(in srgb, var(--sc) 12%, transparent);
          }

          .strategy-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--el-text-color-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }

        .strategy-count {
          display: flex;
          align-items: baseline;
          gap: 2px;
          flex-shrink: 0;

          .count-num {
            font-size: 22px;
            font-weight: 800;
            line-height: 1;
            color: var(--sc);
          }

          .count-unit {
            font-size: 12px;
            color: var(--el-text-color-secondary);
          }
        }

        .spinner {
          color: var(--sc);
        }
      }

      .strategy-desc {
        font-size: 13px;
        color: var(--el-text-color-regular);
        margin-bottom: 12px;
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        min-height: 39px;
      }

      .strategy-tags {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;

        .strategy-tag {
          --el-tag-bg-color: color-mix(in srgb, var(--sc) 9%, transparent);
          --el-tag-border-color: color-mix(in srgb, var(--sc) 25%, transparent);
          --el-tag-text-color: var(--sc);
        }
      }
    }
  }

  /* ===== 结果表格 ===== */
  .result-panel {
    .hit-table {
      --el-table-header-bg-color: var(--el-fill-color-light);
      --el-table-header-text-color: var(--el-text-color-primary);

      :deep(.el-table__header th) {
        font-weight: 600;
        font-size: 13px;
      }

      :deep(.el-table__row) {
        transition: background 0.2s ease;
      }
    }

    .link-code {
      color: var(--el-color-primary);
      font-weight: 600;
      text-decoration: none;
      &:hover { text-decoration: underline; }
    }

    .link-name {
      color: var(--el-text-color-primary);
      text-decoration: none;
      &:hover { color: var(--el-color-primary); }
    }

    .pct-tag {
      font-weight: 600;
      min-width: 64px;
      justify-content: center;
    }

    .score-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 36px;
      height: 22px;
      padding: 0 8px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: var(--sc);
    }

    .text-muted { color: var(--el-text-color-secondary); }
  }
}

@media (max-width: 900px) {
  .strategy-screener {
    .strategy-grid {
      grid-template-columns: 1fr;
    }
  }
}

html.dark {
  .strategy-screener {
    .strategy-panel,
    .result-panel {
      :deep(.el-card__header) {
        background: var(--el-fill-color-dark);
      }
    }

    .strategy-card {
      background: var(--el-fill-color-darker);
      &:hover {
        background: var(--el-fill-color-dark);
      }
      &.active {
        background: linear-gradient(135deg, color-mix(in srgb, var(--sc) 14%, transparent) 0%, transparent 60%),
          var(--el-fill-color-dark);
      }
    }
  }
}
</style>