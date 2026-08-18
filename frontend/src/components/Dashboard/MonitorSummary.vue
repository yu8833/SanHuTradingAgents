<template>
  <el-card class="monitor-summary" shadow="hover">
    <template #header>
      <div class="card-header">
        <div class="card-title">
          <el-icon><Odometer /></el-icon>
          <span>监控中心</span>
        </div>
        <el-button type="text" size="small" @click="goToStockAlerts">
          查看详情 <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </template>

    <div v-loading="loading" class="summary-body">
      <!-- 关键指标 -->
      <div class="summary-stats">
        <div class="stat-item">
          <div class="stat-num" :class="{ danger: todayCount > 0 }">{{ todayCount }}</div>
          <div class="stat-label">今日触发</div>
        </div>
        <div class="stat-item">
          <div class="stat-num" :class="{ danger: criticalCount > 0 }">{{ criticalCount }}</div>
          <div class="stat-label">重要告警</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ enabledRules }}<span class="stat-sub">/{{ totalRules }}</span></div>
          <div class="stat-label">启用规则</div>
        </div>
      </div>

      <!-- 最近触发记录（简要） -->
      <div class="summary-section">
        <div v-if="recentAlerts.length === 0 && !loading" class="summary-empty">
          <el-empty description="暂无触发记录" :image-size="60" />
        </div>
        <div v-else class="summary-list">
          <div v-for="a in recentAlerts" :key="a.ts" class="summary-item">
            <span :class="['sev-dot', a.severity || 'info']" />
            <span :class="['summary-symbol', (a.change_pct ?? 0) >= 0 ? 'up' : 'down']">
              {{ a.symbol || '—' }}
            </span>
            <span class="summary-msg">{{ a.message }}</span>
            <span class="summary-time">{{ formatTs(a.ts) }}</span>
          </div>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Odometer, ArrowRight } from '@element-plus/icons-vue'
import { monitorApi, type MonitorAlert, type MonitorRule } from '@/api/monitor'

defineOptions({ name: 'MonitorSummary' })

const router = useRouter()

const loading = ref(false)
const alerts = ref<MonitorAlert[]>([])
const rules = ref<MonitorRule[]>([])

let pollTimer: number | null = null

// 今日触发（ts 为毫秒时间戳）
const todayStart = () => {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
}

const todayCount = computed(() =>
  alerts.value.filter(a => a.ts >= todayStart()).length
)
const criticalCount = computed(() =>
  alerts.value.filter(a => a.severity === 'critical').length
)
const enabledRules = computed(() =>
  rules.value.filter(r => r.enabled).length
)
const totalRules = computed(() => rules.value.length)

const recentAlerts = computed(() => alerts.value.slice(0, 5))

const formatTs = (ts: number) => {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const loadAlerts = async () => {
  try {
    const res = await monitorApi.listAlerts({ days: 1, limit: 50 })
    const data = (res as any)?.data ?? {}
    alerts.value = data.alerts || []
  } catch (e) {
    console.warn('加载触发记录失败', e)
  }
}

const loadRules = async () => {
  try {
    const res = await monitorApi.listRules()
    const data = (res as any)?.data ?? {}
    rules.value = data.rules || []
  } catch (e) {
    console.warn('加载监控规则失败', e)
  }
}

const loadAll = async () => {
  loading.value = true
  await Promise.all([loadAlerts(), loadRules()])
  loading.value = false
}

const goToStockAlerts = () => {
  router.push('/stock-alerts')
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  loadAll()
  pollTimer = window.setInterval(loadAll, 30000)
})
onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style lang="scss" scoped>
.monitor-summary {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .card-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;
    }
  }

  .summary-stats {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;

    .stat-item {
      flex: 1;
      padding: 12px;
      border-radius: 8px;
      background: var(--el-fill-color-light);
      text-align: center;

      .stat-num {
        font-size: 24px;
        font-weight: 700;
        color: var(--el-color-primary);
        font-family: monospace;

        &.danger { color: var(--el-color-danger); }

        .stat-sub {
          font-size: 13px;
          font-weight: 400;
          color: var(--el-text-color-secondary);
        }
      }

      .stat-label {
        margin-top: 4px;
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .summary-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .summary-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 6px;
      font-size: 12px;

      .sev-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;

        &.info { background: var(--el-color-primary); }
        &.warn { background: var(--el-color-warning); }
        &.critical { background: var(--el-color-danger); }
      }

      .summary-symbol {
        font-family: monospace;
        font-weight: 600;

        &.up { color: var(--el-color-danger); }
        &.down { color: var(--el-color-success); }
      }

      .summary-msg {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--el-text-color-regular);
      }

      .summary-time {
        font-size: 11px;
        color: var(--el-text-color-placeholder);
        font-family: monospace;
        flex-shrink: 0;
      }
    }
  }

  @media (max-width: 768px) {
    .card-header {
      flex-wrap: wrap;
      gap: 8px;
    }

    .summary-stats {
      gap: 8px;
      .stat-item {
        padding: 8px 6px;
        .stat-num {
          font-size: 20px;
        }
      }
    }

    .summary-list {
      .summary-item {
        flex-wrap: wrap;
        gap: 6px;
        .summary-msg {
          flex-basis: 100%;
          order: 3;
          white-space: normal;
          -webkit-line-clamp: 2;
          display: -webkit-box;
          -webkit-box-orient: vertical;
        }
      }
    }
  }
}
</style>