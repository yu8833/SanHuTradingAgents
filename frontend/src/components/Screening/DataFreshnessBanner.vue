<template>
  <div class="data-freshness-banner" :class="statusClass">
    <div class="freshness-info">
      <el-icon class="freshness-icon">
        <CircleCheck v-if="isFresh" />
        <Warning v-else-if="!isChecking && hasChecked" />
        <Loading v-else />
      </el-icon>
      <span class="freshness-text" v-if="isUpdating && progressText">{{ progressText }}</span>
      <span class="freshness-text" v-else-if="isChecking">正在检查数据新鲜度...</span>
      <span class="freshness-text" v-else-if="hasChecked && info">
        <template v-if="isFresh">
          数据最新（{{ info.latest_data_date }}）
        </template>
        <template v-else>
          数据已过期 {{ info.stale_days >= 999 ? '多' : info.stale_days }} 天（最新数据：{{ info.latest_data_date || '无数据' }}）
        </template>
        <span class="coverage" v-if="info && info.expected_total > 0">
          ｜覆盖：{{ info.total_stocks }}/{{ info.expected_total }} 只
        </span>
      </span>
      <span class="freshness-text" v-else>数据新鲜度未知</span>
    </div>
    <el-button
      size="small"
      :type="isFresh ? 'info' : 'warning'"
      :disabled="isFresh || isUpdating || isChecking"
      :loading="isUpdating"
      @click="handleUpdate"
    >
      <el-icon><Refresh /></el-icon>
      更新数据
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, Warning, Loading, Refresh } from '@element-plus/icons-vue'
import { screeningApi } from '@/api/screening'

interface FreshnessData {
  latest_data_date: string | null
  expected_date: string
  is_fresh: boolean
  stale_days: number
  total_stocks: number
  expected_total: number
  message: string
}

const CHECK_INTERVAL = 1 * 60 * 60 * 1000 // 1小时
const POLL_INTERVAL = 30 * 1000 // 30秒轮询同步进度

const isChecking = ref(false)
const isUpdating = ref(false)
const hasChecked = ref(false)
const info = ref<FreshnessData | null>(null)
const progressText = ref('')
let timer: ReturnType<typeof setInterval> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

const isFresh = computed(() => {
  if (!hasChecked.value || !info.value) return false
  return info.value.is_fresh
})

const statusClass = computed(() => {
  if (!hasChecked.value) return 'checking'
  return isFresh.value ? 'fresh' : 'stale'
})

async function checkFreshness() {
  isChecking.value = true
  try {
    const resp = await screeningApi.checkDataFreshness()
    info.value = resp.data
    hasChecked.value = true
  } catch (e) {
    console.error('[data-freshness] 检查失败:', e)
    hasChecked.value = true
  } finally {
    isChecking.value = false
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * 轮询同步任务执行状态，展示进度并在完成或失败时停止
 */
async function pollExecutionStatus() {
  try {
    const token = localStorage.getItem('auth-token')
    const runningResp = await fetch(
      '/api/scheduler/executions?job_id=tushare_historical_sync&status=running&limit=1',
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      }
    )
    const runningData = await runningResp.json()
    const runningItems = runningData.items || []
    if (runningItems.length > 0 && runningItems[0].status === 'running') {
      const pct = runningItems[0].progress ?? 0
      progressText.value = `正在更新数据... 进度: ${pct}%`
      return
    }

    // 无运行中的记录，查询最新执行记录以判定最终状态
    const latestResp = await fetch(
      '/api/scheduler/executions?job_id=tushare_historical_sync&limit=1',
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      }
    )
    const latestData = await latestResp.json()
    const latestItems = latestData.items || []
    if (latestItems.length === 0) {
      // 暂无执行记录，继续等待
      return
    }
    const latest = latestItems[0]
    if (latest.status === 'success') {
      stopPolling()
      isUpdating.value = false
      progressText.value = ''
      ElMessage.success('数据同步已完成')
      await checkFreshness()
    } else if (latest.status === 'failed') {
      stopPolling()
      isUpdating.value = false
      progressText.value = ''
      ElMessage.error('数据同步失败：' + (latest.error_message || '未知错误'))
      await checkFreshness()
    } else {
      const pct = latest.progress ?? 0
      progressText.value = `正在更新数据... 进度: ${pct}%`
    }
  } catch (e) {
    console.error('[data-freshness] 轮询执行状态失败:', e)
  }
}

async function handleUpdate() {
  if (isFresh.value) return

  try {
    await ElMessageBox.confirm(
      '数据同步预计需要数小时完成，是否确认触发更新？',
      '更新确认',
      {
        confirmButtonText: '确认更新',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    // 用户点击取消
    return
  }

  isUpdating.value = true
  progressText.value = '正在更新数据...'
  try {
    const token = localStorage.getItem('auth-token')
    const resp = await fetch('/api/scheduler/jobs/tushare_historical_sync/trigger?force=true', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    })
    const data = await resp.json()
    if (data.success !== false) {
      ElMessage.success('数据同步任务已触发，预计需要数小时完成')
      // 启动轮询，跟踪执行进度；isUpdating 在轮询到终态时才重置
      stopPolling()
      pollTimer = setInterval(pollExecutionStatus, POLL_INTERVAL)
      // 立即轮询一次，尽快拿到执行记录
      pollExecutionStatus()
    } else {
      ElMessage.warning(data.message || '触发同步失败')
      isUpdating.value = false
      progressText.value = ''
    }
  } catch (e) {
    console.error('[data-freshness] 触发同步失败:', e)
    ElMessage.error('触发数据同步失败')
    isUpdating.value = false
    progressText.value = ''
  }
}

function handleVisibilityChange() {
  // 页面切回前台时立即检查一次数据新鲜度
  if (document.visibilityState === 'visible') {
    checkFreshness()
  }
}

onMounted(() => {
  checkFreshness()
  timer = setInterval(checkFreshness, CHECK_INTERVAL)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.data-freshness-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  border: 1px solid;
  transition: all 0.3s;
}

.data-freshness-banner.fresh {
  background: #f0f9eb;
  border-color: #e1f3d8;
  color: #67c23a;
}

.data-freshness-banner.stale {
  background: #fdf6ec;
  border-color: #faecd8;
  color: #e6a23c;
}

.data-freshness-banner.checking {
  background: #f4f4f5;
  border-color: #e9e9eb;
  color: #909399;
}

.freshness-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.freshness-icon {
  font-size: 18px;
}

.freshness-text {
  line-height: 1.5;
}

.coverage {
  color: #909399;
  font-size: 13px;
}
</style>
