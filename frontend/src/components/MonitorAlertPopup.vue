<template>
  <el-dialog
    :model-value="visible"
    :title="popupTitle"
    width="560px"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    class="monitor-alert-popup"
  >
    <div class="popup-alerts">
      <div v-for="a in popupAlerts" :key="a.id" class="popup-alert">
        <div :class="['alert-severity-bar', a.severity || 'info']" />
        <div class="alert-main">
          <div class="alert-top">
            <span class="alert-symbol">{{ a.symbol || '—' }}</span>
            <span v-if="a.name" class="alert-name">{{ a.name }}</span>
            <span v-if="a.rule_name" class="alert-rule">{{ a.rule_name }}</span>
            <el-tag size="small" :type="severityTag(a.severity)" effect="plain">
              {{ severityLabel(a.severity) }}
            </el-tag>
          </div>
          <div v-if="a.price != null || a.change_pct != null" class="alert-price-row">
            <span v-if="a.price != null" class="alert-price" :class="(a.change_pct ?? 0) >= 0 ? 'up' : 'down'">
              现价 {{ a.price }}
            </span>
            <span v-if="a.change_pct != null" class="alert-pct" :class="a.change_pct >= 0 ? 'up' : 'down'">
              {{ a.change_pct >= 0 ? '+' : '' }}{{ a.change_pct.toFixed(2) }}%
            </span>
          </div>
          <div class="alert-message">{{ a.message || '命中监控规则' }}</div>
          <div class="alert-time">{{ formatTs(a.ts) }}</div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="gotoMonitor">前往监控中心</el-button>
      <el-button type="primary" @click="acknowledge">我知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { monitorApi, type MonitorAlert } from '@/api/monitor'
import router from '@/router'

// 上次已确认（已读）的最大触发时间戳（毫秒），跨页面刷新持久化。
const LAST_SEEN_KEY = 'monitor_alert_last_seen_ts'
const POLL_INTERVAL = 15000 // 每 15 秒检测一次新告警（后端每 60 秒评估一次）

const visible = ref(false)
const popupAlerts = ref<MonitorAlert[]>([])
let lastSeenTs = 0
let pollTimer: number | null = null
let initialized = false

const popupTitle = computed(() => {
  const n = popupAlerts.value.length
  return n > 1 ? `监控触发提醒 · ${n} 条` : '监控触发提醒'
})

// 是否有登录态（与 request.ts 拦截器一致）
const hasToken = () => !!localStorage.getItem('auth-token')

// 拉取最近告警，返回按 ts 倒序的列表（无登录态或失败返回空）
const fetchAlerts = async (): Promise<MonitorAlert[]> => {
  if (!hasToken()) return []
  try {
    const res = await monitorApi.listAlerts(
      { days: 1, limit: 30 },
      { skipAuthError: true, skipErrorHandler: true },
    )
    const data = (res as any)?.data ?? {}
    return data.alerts || []
  } catch (e) {
    // 后台轮询失败不打扰用户，静默跳过
    return []
  }
}

// 主检测逻辑：找出 lastSeenTs 之后的新告警并弹出
const checkForNewAlerts = async () => {
  const alerts = await fetchAlerts()
  if (alerts.length === 0) return

  // 首次初始化：不弹历史告警，仅把游标定位到当前最新时间戳
  if (!initialized) {
    initialized = true
    lastSeenTs = alerts[0].ts > 0 ? alerts[0].ts : 0
    localStorage.setItem(LAST_SEEN_KEY, String(lastSeenTs))
    return
  }

  const pending = alerts.filter((a) => a.ts > lastSeenTs)
  if (pending.length === 0) return

  // 有新的未确认告警 → 弹出页面（不可自动关闭，需手动点按钮）
  popupAlerts.value = pending
  visible.value = true
}

// 确认：把游标推进到本次弹窗中最新告警时间，关闭弹窗
const acknowledge = () => {
  if (popupAlerts.value.length > 0) {
    const maxTs = Math.max(...popupAlerts.value.map((a) => a.ts))
    lastSeenTs = maxTs
    localStorage.setItem(LAST_SEEN_KEY, String(maxTs))
  }
  visible.value = false
  popupAlerts.value = []
}

// 前往监控中心页面并确认
const gotoMonitor = () => {
  acknowledge()
  router.push('/stock-alerts')
}

// ── 展示辅助（与 MonitorCenter 保持一致） ──────────────
const severityTag = (s: string): 'info' | 'warning' | 'danger' => {
  const map: Record<string, any> = { info: 'info', warn: 'warning', critical: 'danger' }
  return map[s] || 'info'
}
const severityLabel = (s: string) => {
  const map: Record<string, string> = { info: '普通', warn: '警告', critical: '重要' }
  return map[s] || s
}
const formatTs = (ts: number) => {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(() => {
  // 恢复上次已确认游标；已有历史游标 → 直接进入增量检测（会把关闭页面期间的新告警补弹出来），
  // 无历史游标（首次使用）→ 先初始化游标，不弹历史告警。
  const stored = localStorage.getItem(LAST_SEEN_KEY)
  if (stored) {
    lastSeenTs = Number(stored) || 0
    initialized = true
  } else {
    lastSeenTs = 0
    initialized = false
  }

  checkForNewAlerts()
  pollTimer = window.setInterval(checkForNewAlerts, POLL_INTERVAL)
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style lang="scss" scoped>
.monitor-alert-popup {
  :deep(.el-dialog__header) {
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid var(--el-border-color-lighter);
    .el-dialog__title {
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
  }
}

.popup-alerts {
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;

  .popup-alert {
    display: flex;
    gap: 10px;
    padding: 10px 12px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
    background: var(--el-fill-color-blank);

    .alert-severity-bar {
      width: 3px;
      border-radius: 2px;
      flex-shrink: 0;
      &.info { background: var(--el-color-primary); }
      &.warn { background: var(--el-color-warning); }
      &.critical { background: var(--el-color-danger); }
    }

    .alert-main {
      flex: 1;
      min-width: 0;

      .alert-top {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        .alert-symbol { font-family: monospace; font-weight: 600; font-size: 14px; }
        .alert-name { font-size: 12px; color: var(--el-text-color-secondary); }
        .alert-rule { font-size: 12px; color: var(--el-color-primary); }
      }

      .alert-price-row {
        margin-top: 4px;
        display: flex;
        align-items: center;
        gap: 12px;
        .alert-price { font-family: monospace; font-size: 13px; font-weight: 600; }
        .alert-pct { font-family: monospace; font-size: 13px; font-weight: 600; }
        .up { color: var(--el-color-danger); }
        .down { color: var(--el-color-success); }
      }

      .alert-message {
        margin-top: 4px;
        font-size: 13px;
        color: var(--el-text-color-regular);
      }

      .alert-time {
        margin-top: 4px;
        font-size: 11px;
        color: var(--el-text-color-placeholder);
        font-family: monospace;
      }
    }
  }
}
</style>