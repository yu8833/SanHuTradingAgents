<template>
  <el-card class="data-health-card" shadow="hover">
    <template #header>
      <div class="card-header">
        <div class="card-title">
          <el-icon style="margin-right: 6px;"><DataBoard /></el-icon>
          <span>数据健康</span>
        </div>
        <div class="card-actions">
          <el-button
            v-if="!overallIsFresh"
            type="warning"
            size="small"
            @click="$emit('open-sync')"
          >
            <el-icon><Refresh /></el-icon> 一键更新
          </el-button>
          <el-button type="text" size="small" @click="goToSyncPage">
            管理 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="health-body">
      <!-- 数据源可用性 -->
      <div class="sources-row">
        <div
          v-for="source in dataSources"
          :key="source.name"
          class="source-pill"
          :class="source.available ? 'ok' : 'err'"
          :title="source.description"
        >
          <el-icon v-if="source.available"><SuccessFilled /></el-icon>
          <el-icon v-else><CircleCloseFilled /></el-icon>
          {{ source.name.toUpperCase() }}
        </div>
      </div>

      <!-- 总览状态 -->
      <div class="overall-row">
        <div :class="['health-badge', overallIsFresh ? 'fresh' : 'stale']">
          <el-icon v-if="overallIsFresh"><CircleCheck /></el-icon>
          <el-icon v-else><WarningFilled /></el-icon>
          {{ overallIsFresh ? '全部最新' : '有数据需要更新' }}
        </div>
        <span class="health-message">{{ freshness.message || '' }}</span>
      </div>

      <!-- 过期项明细（仅展示未最新项，全部最新时折叠） -->
      <div v-if="staleItems.length > 0" class="stale-list">
        <div v-for="item in staleItems" :key="item.key" class="stale-item">
          <span class="stale-label">{{ item.label }}</span>
          <el-tag type="warning" size="small" effect="plain">
            过期{{ item.stale_days > 0 ? item.stale_days + '天' : '' }}
          </el-tag>
        </div>
      </div>
      <div v-else class="all-fresh-hint">
        <span>数据新鲜度：{{ freshCount }}/{{ freshnessItems.length }} 项最新</span>
      </div>

      <!-- 同步状态 -->
      <div v-if="syncStatus" class="sync-status">
        <el-tag size="small" :type="syncType" effect="plain">{{ syncStatusText }}</el-tag>
        <span v-if="syncStatus.status === 'running'" class="sync-progress">
          {{ syncStatus.total > 0 ? `${syncStatus.inserted + syncStatus.updated}/${syncStatus.total}` : '同步中...' }}
        </span>
        <span v-else-if="syncStatus.finished_at" class="sync-time">
          {{ formatLastSync(syncStatus.finished_at) }}完成
        </span>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import {
  DataBoard, Refresh, ArrowRight, SuccessFilled,
  CircleCloseFilled, CircleCheck, WarningFilled,
} from '@element-plus/icons-vue'
import { screeningApi } from '@/api/screening'
import { getDataSourcesStatus, getSyncStatus, type DataSourceStatus, type SyncStatus } from '@/api/sync'
import { subscribeQuotesUpdate } from '@/utils/quotesSSE'

defineOptions({ name: 'DataHealthCard' })
defineEmits<{ (e: 'open-sync'): void }>()

const router = useRouter()

const loading = ref(false)
const dataSources = ref<DataSourceStatus[]>([])
const syncStatus = ref<SyncStatus | null>(null)
const freshness = ref<{
  overall_is_fresh: boolean
  message?: string
  items?: { key: string; label: string; is_fresh: boolean; stale_days: number }[]
}>({ overall_is_fresh: false, message: '', items: [] })

const overallIsFresh = computed(() => freshness.value.overall_is_fresh ?? false)
const freshnessItems = computed(() => freshness.value.items || [])
const freshCount = computed(() => freshnessItems.value.filter((i) => i.is_fresh).length)
const staleItems = computed(() => freshnessItems.value.filter((i) => !i.is_fresh))

const syncType = computed(() => {
  const map: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
    idle: 'info', running: 'warning', success: 'success',
    success_with_errors: 'warning', failed: 'danger', never_run: 'info',
  }
  return map[syncStatus.value?.status ?? 'never_run'] || 'info'
})
const syncStatusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲', running: '同步中', success: '成功', success_with_errors: '部分成功',
    failed: '失败', never_run: '未运行',
  }
  return map[syncStatus.value?.status ?? 'never_run'] || '未知'
})

const loadFreshness = async () => {
  try {
    const res = await screeningApi.checkDataFreshness()
    const data = (res as any)?.data?.data || (res as any)?.data || {}
    freshness.value = data
  } catch (e) {
    console.warn('加载数据新鲜度失败', e)
  }
}

const loadDataSources = async () => {
  try {
    const res = await getDataSourcesStatus()
    if (res.success) {
      dataSources.value = res.data
        .sort((a, b) => b.priority - a.priority)
        .slice(0, 3)
    }
  } catch (e) {
    console.warn('加载数据源状态失败', e)
  }
}

const loadSyncStatus = async () => {
  try {
    const res = await getSyncStatus()
    if (res.success) syncStatus.value = res.data
  } catch (e) {
    console.warn('获取同步状态失败', e)
  }
}

const loadAll = async () => {
  loading.value = true
  await Promise.all([loadFreshness(), loadDataSources(), loadSyncStatus()])
  loading.value = false
}

const goToSyncPage = () => router.push('/settings/sync')

const formatLastSync = (timeStr: string) => {
  const diff = Date.now() - new Date(timeStr).getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return new Date(timeStr).toLocaleDateString('zh-CN')
}

let pollTimer: ReturnType<typeof setInterval> | null = null
let sseUnsubscribe: (() => void) | null = null

onMounted(() => {
  loadAll()
  // 30 秒兜底轮询 + SSE 行情信号触发刷新
  pollTimer = setInterval(loadAll, 30000)
  sseUnsubscribe = subscribeQuotesUpdate(() => {
    loadFreshness()
    loadSyncStatus()
  })
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  sseUnsubscribe?.()
})
</script>

<style scoped lang="scss">
.data-health-card {
  height: 100%;

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .card-title {
      display: flex;
      align-items: center;
      font-weight: 600;
    }

    .card-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }

  .health-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .sources-row {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;

    .source-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;

      &.ok { background: var(--el-color-success-light-9); color: var(--el-color-success); }
      &.err { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
    }
  }

  .overall-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;

    .health-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      border-radius: 14px;
      font-size: 13px;
      font-weight: 600;

      &.fresh { background: var(--el-color-success-light-9); color: var(--el-color-success); }
      &.stale { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
    }

    .health-message {
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }
  }

  .stale-list {
    display: flex;
    flex-direction: column;
    gap: 6px;

    .stale-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      background: var(--el-color-warning-light-9);
      border-radius: 6px;

      .stale-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--el-color-warning);
      }
    }
  }

  .all-fresh-hint {
    font-size: 12px;
    color: var(--el-text-color-regular);
  }

  .sync-status {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--el-border-color-lighter);

    .sync-progress, .sync-time {
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }
  }
}
</style>