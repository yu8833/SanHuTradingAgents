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
      <!-- 🔥 系统健康总览 -->
      <div v-if="systemStatus" class="system-status-row">
        <div :class="['sys-badge', systemStatus.overall.status]">
          <el-icon v-if="systemStatus.overall.status === 'healthy'"><CircleCheck /></el-icon>
          <el-icon v-else-if="systemStatus.overall.status === 'degraded'"><WarningFilled /></el-icon>
          <el-icon v-else><CircleCloseFilled /></el-icon>
          {{ systemStatus.overall.message }}
        </div>
        <span class="sys-time" v-if="systemStatus.overall.checked_at">
          检查于 {{ formatCheckedAt(systemStatus.overall.checked_at) }}
        </span>
      </div>

      <!-- 🔥 各子系统状态 -->
      <div v-if="systemStatus" class="subsystems-row">
        <div
          v-for="(sub, key) in systemStatusSubsystems"
          :key="key"
          class="subsystem-item"
          :class="sub.status"
          :title="sub.message"
        >
          <span class="sub-label">{{ sub.label }}</span>
          <span class="sub-status-dot" :class="sub.status"></span>
          <span class="sub-status-text">{{ statusLabel(sub.status) }}</span>
        </div>
      </div>

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

      <!-- 数据明细：每项的名称、条数、截止时间、状态 -->
      <div v-if="freshnessItems.length > 0" class="freshness-list">
        <div
          v-for="item in freshnessItems"
          :key="item.key"
          class="freshness-item"
          :class="{ stale: !item.is_fresh }"
        >
          <div class="fi-left">
            <span class="fi-label">{{ item.label }}</span>
            <span class="fi-count">{{ fmtCount(item.count) }}条</span>
          </div>
          <div class="fi-right">
            <span class="fi-latest" :title="item.threshold">
              {{ item.key === 'quotes' ? '截至 ' + (item.latest || '—') : (item.latest || '—') }}
            </span>
            <el-tag v-if="!item.is_fresh" type="warning" size="small" effect="plain">
              过期{{ item.stale_days > 0 ? item.stale_days + '天' : '' }}
            </el-tag>
            <el-tag v-else type="success" size="small" effect="plain">最新</el-tag>
          </div>
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

// 🔥 新增：系统健康状态
const systemStatus = ref<any | null>(null)

const systemStatusSubsystems = computed(() => {
  if (!systemStatus.value) return {}
  const s = systemStatus.value
  return {
    realtime: {
      label: '实时行情',
      status: s.realtime_quotes?.status || 'unknown',
      message: s.realtime_quotes?.message || '',
    },
    historical: {
      label: '历史K线',
      status: s.historical_daily?.status || 'unknown',
      message: s.historical_daily?.message || '',
    },
    scheduler: {
      label: '任务调度',
      status: s.scheduler?.status || 'unknown',
      message: s.scheduler?.message || '',
    },
  }
})
const freshness = ref<{
  overall_is_fresh: boolean
  message?: string
  items?: {
    key: string
    label: string
    is_fresh: boolean
    stale_days: number
    latest?: string
    count?: number
    threshold?: string
  }[]
}>({ overall_is_fresh: false, message: '', items: [] })

const overallIsFresh = computed(() => freshness.value.overall_is_fresh ?? false)
const freshnessItems = computed(() => freshness.value.items || [])
const freshCount = computed(() => freshnessItems.value.filter((i) => i.is_fresh).length)

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
  await Promise.all([loadFreshness(), loadDataSources(), loadSyncStatus(), loadSystemStatus()])
  loading.value = false
}

// 🔥 加载系统健康状态
const loadSystemStatus = async () => {
  try {
    const res = await fetch('/api/v1/data/status')
    if (res.ok) {
      const result = await res.json()
      if (result.success && result.data) {
        systemStatus.value = result.data
      }
    }
  } catch (e) {
    console.warn('加载系统健康状态失败', e)
  }
}

// 🔥 辅助函数
const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    healthy: '正常',
    degraded: '降级',
    stale: '过期',
    critical: '严重',
    unavailable: '不可用',
    unknown: '未知',
  }
  return map[status] || status
}

const formatCheckedAt = (timeStr: string) => {
  if (!timeStr) return ''
  try {
    const d = new Date(timeStr)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return timeStr
  }
}

const goToSyncPage = () => router.push('/settings/sync')

const formatLastSync = (timeStr: string) => {
  const diff = Date.now() - new Date(timeStr).getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return new Date(timeStr).toLocaleDateString('zh-CN')
}

// 格式化数据条数（万/亿）
const fmtCount = (n: number | undefined) => {
  if (n == null) return '—'
  if (n >= 1e8) return (n / 1e8).toFixed(2).replace(/\.?0+$/, '') + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, '') + '万'
  return String(n)
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

  /* 🔥 系统健康总览样式 */
  .system-status-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    background: var(--el-fill-color-lighter);
    border-radius: 8px;

    .sys-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 12px;
      border-radius: 14px;
      font-size: 13px;
      font-weight: 600;

      &.healthy { background: var(--el-color-success-light-9); color: var(--el-color-success); }
      &.degraded { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
      &.critical { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
      &.unknown { background: var(--el-color-info-light-9); color: var(--el-color-info); }
    }

    .sys-time {
      font-size: 11px;
      color: var(--el-text-color-placeholder);
    }
  }

  /* 🔥 子系统状态 */
  .subsystems-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;

    .subsystem-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      padding: 8px 6px;
      background: var(--el-bg-color);
      border-radius: 6px;
      border: 1px solid var(--el-border-color-lighter);
      cursor: help;

      .sub-label {
        font-size: 11px;
        color: var(--el-text-color-secondary);
      }

      .sub-status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;

        &.healthy { background: var(--el-color-success); }
        &.degraded, &.stale { background: var(--el-color-warning); }
        &.critical, &.unavailable { background: var(--el-color-danger); }
        &.unknown { background: var(--el-color-info); }
      }

      .sub-status-text {
        font-size: 11px;
        font-weight: 500;

        .healthy { color: var(--el-color-success); }
        .degraded, .stale { color: var(--el-color-warning); }
        .critical, .unavailable { color: var(--el-color-danger); }
        .unknown { color: var(--el-color-info); }
      }

      &.healthy .sub-status-text { color: var(--el-color-success); }
      &.degraded .sub-status-text { color: var(--el-color-warning); }
      &.stale .sub-status-text { color: var(--el-color-warning); }
      &.critical .sub-status-text { color: var(--el-color-danger); }
      &.unavailable .sub-status-text { color: var(--el-color-danger); }
      &.unknown .sub-status-text { color: var(--el-color-info); }
    }
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

  .freshness-list {
    display: flex;
    flex-direction: column;
    gap: 6px;

    .freshness-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      background: var(--el-fill-color-light);
      border-radius: 6px;

      &.stale {
        background: var(--el-color-warning-light-9);
      }

      .fi-left {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;

        .fi-label {
          font-size: 12px;
          font-weight: 500;
          color: var(--el-text-color-primary);
          white-space: nowrap;
        }

        .fi-count {
          font-size: 11px;
          color: var(--el-text-color-secondary);
          white-space: nowrap;
        }
      }

      .fi-right {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;

        .fi-latest {
          font-size: 11px;
          color: var(--el-text-color-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
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

  /* 🔥 移动端适配 */
  @media (max-width: 768px) {
    .system-status-row {
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
    }

    .subsystems-row {
      grid-template-columns: repeat(3, 1fr);
      gap: 4px;
    }

    .subsystem-item {
      padding: 6px 4px;

      .sub-label { font-size: 10px; }
      .sub-status-text { font-size: 10px; }
    }
  }
}
</style>