<template>
  <div class="scheduled-tasks-view">
    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ schedulerStats.total_jobs }}</div><div class="label">定时任务总数</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value running">{{ schedulerStats.running_jobs }}</div><div class="label">运行中</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value paused">{{ schedulerStats.paused_jobs }}</div><div class="label">已暂停</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ runningExecutions }}</div><div class="label">执行中记录</div></div></el-card>
      </el-col>
    </el-row>

    <!-- 定时任务列表 -->
    <el-card class="jobs-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">定时任务列表</span>
          <el-button @click="loadJobs" :loading="jobsLoading" size="small">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table :data="jobs" v-loading="jobsLoading" style="width: 100%" :default-sort="{ prop: 'category' }">
        <el-table-column label="任务名称" min-width="200">
          <template #default="{ row }">
            <div class="job-name-cell">
              <span class="job-display-name">{{ getJobDisplayName(row) }}</span>
              <span class="job-id">{{ row.id }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="120" :filters="categoryFilters" :filter-method="filterCategory">
          <template #default="{ row }">
            <el-tag :type="getCategoryTagType(row.id)" size="small" effect="plain">{{ getCategory(row.id) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.paused ? 'info' : 'success'" size="small">
              {{ row.paused ? '已暂停' : '运行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="下次执行" width="180">
          <template #default="{ row }">
            <span v-if="row.next_run_time">{{ formatTime(row.next_run_time) }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="触发器" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-muted">{{ row.trigger }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="triggerJob(row)" :disabled="jobActionLoading[row.id]">
              触发
            </el-button>
            <el-button v-if="!row.paused" type="text" size="small" @click="pauseJob(row)" :disabled="jobActionLoading[row.id]">
              暂停
            </el-button>
            <el-button v-else type="text" size="small" @click="resumeJob(row)" :disabled="jobActionLoading[row.id]">
              恢复
            </el-button>
            <el-button type="text" size="small" @click="viewJobExecutions(row)">执行记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 执行记录 -->
    <el-card class="executions-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">执行记录</span>
          <div class="filter-bar">
            <el-select v-model="execFilter.job_id" placeholder="全部任务" clearable filterable size="small" style="width: 220px" @change="loadExecutions">
              <el-option v-for="job in jobs" :key="job.id" :label="getJobDisplayName(job)" :value="job.id" />
            </el-select>
            <el-select v-model="execFilter.status" placeholder="全部状态" clearable size="small" style="width: 120px" @change="loadExecutions">
              <el-option label="执行中" value="running" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="错过" value="missed" />
            </el-select>
            <el-select v-model="execFilter.is_manual" placeholder="全部触发" clearable size="small" style="width: 120px" @change="loadExecutions">
              <el-option label="手动触发" :value="true" />
              <el-option label="自动触发" :value="false" />
            </el-select>
            <el-button @click="loadExecutions" :loading="execLoading" size="small">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="executions" v-loading="execLoading" style="width: 100%">
        <el-table-column label="任务" min-width="180">
          <template #default="{ row }">
            <span>{{ row.job_name || row.job_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getExecStatusType(row.status)" size="small">{{ getExecStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_manual ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.is_manual ? '手动' : '自动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress
              v-if="row.status === 'running'"
              :percentage="row.progress || 0"
              :stroke-width="14"
              :text-inside="true"
            />
            <span v-else class="text-muted">{{ row.progress != null ? row.progress + '%' : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            <span v-if="row.execution_time != null">{{ formatDuration(row.execution_time) }}</span>
            <span v-else-if="row.status === 'running' && row.timestamp" class="text-muted">
              {{ formatDuration((Date.now() - new Date(row.timestamp).getTime()) / 1000) }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'failed'" type="text" size="small" @click="showErrorDetail(row)">查看错误</el-button>
            <el-button v-if="row.status === 'running'" type="text" size="small" @click="cancelExecution(row)" style="color: #e6a23c;">取消</el-button>
            <el-button v-if="row.status === 'running'" type="text" size="small" @click="markFailed(row)" style="color: #f56c6c;">标记失败</el-button>
            <el-button type="text" size="small" @click="deleteExecution(row)" style="color: #f56c6c;">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="execPage.current"
          v-model:page-size="execPage.size"
          :page-sizes="[20, 50, 100]"
          :total="execPage.total"
          layout="total, sizes, prev, pager, next"
          @size-change="loadExecutions"
          @current-change="loadExecutions"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import * as schedulerApi from '@/api/scheduler'
import { formatDateTime } from '@/utils/datetime'

// 任务友好名称映射
const JOB_NAME_MAP: Record<string, string> = {
  basics_sync_service: '多源股票基础信息同步',
  quotes_ingestion_service: '行情数据采集',
  tushare_basic_info_sync: 'Tushare 基础信息同步',
  tushare_quotes_sync: 'Tushare 行情同步',
  tushare_historical_sync: 'Tushare 历史数据同步',
  tushare_financial_sync: 'Tushare 财务数据同步',
  tushare_status_check: 'Tushare 数据源状态检查',
  akshare_basic_info_sync: 'AKShare 基础信息同步',
  akshare_quotes_sync: 'AKShare 行情同步',
  akshare_historical_sync: 'AKShare 历史数据同步',
  akshare_financial_sync: 'AKShare 财务数据同步',
  akshare_status_check: 'AKShare 数据源状态检查',
  baostock_basic_info_sync: 'BaoStock 基础信息同步',
  baostock_daily_quotes_sync: 'BaoStock 日行情同步',
  baostock_historical_sync: 'BaoStock 历史数据同步',
  baostock_status_check: 'BaoStock 数据源状态检查',
  data_integrity_check: '数据完整性检查',
  news_sync: '新闻数据同步',
  retail_exit_check: '散户退出信号扫描',
  retail_exit_check_close: '散户收盘退出扫描',
  retail_regime_detect: '散户市场环境检测',
  stock_alert_check: '个股预警检查',
  stock_alert_check_close: '个股预警收盘检查',
  retail_intraday_scan: '盘中统一扫描（预警+退出）',
  check_zombie_tasks: '僵尸任务检测',
}

function getJobDisplayName(job: any): string {
  return job.display_name || JOB_NAME_MAP[job.id] || job.name || job.id
}

// 任务分类
function getCategory(jobId: string): string {
  if (jobId.startsWith('tushare_') || jobId.startsWith('akshare_') || jobId.startsWith('baostock_') ||
      jobId === 'basics_sync_service' || jobId === 'quotes_ingestion_service' ||
      jobId === 'data_integrity_check' || jobId === 'news_sync') {
    return '数据同步'
  }
  if (jobId.startsWith('retail_') || jobId.startsWith('stock_alert')) {
    return '散户策略'
  }
  if (jobId === 'check_zombie_tasks') {
    return '系统'
  }
  return '其他'
}

function getCategoryTagType(jobId: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const cat = getCategory(jobId)
  if (cat === '数据同步') return 'primary'
  if (cat === '散户策略') return 'success'
  if (cat === '系统') return 'warning'
  return 'info'
}

const categoryFilters = [
  { text: '数据同步', value: '数据同步' },
  { text: '散户策略', value: '散户策略' },
  { text: '系统', value: '系统' },
  { text: '其他', value: '其他' },
]
function filterCategory(value: string, row: any) {
  return getCategory(row.id) === value
}

// 调度器统计
const schedulerStats = reactive({ total_jobs: 0, running_jobs: 0, paused_jobs: 0, scheduler_running: false, scheduler_state: 0 })

// 任务列表
const jobs = ref<any[]>([])
const jobsLoading = ref(false)
const jobActionLoading = reactive<Record<string, boolean>>({})

const runningExecutions = computed(() => executions.value.filter(e => e.status === 'running').length)

async function loadJobs() {
  jobsLoading.value = true
  try {
    const res = await schedulerApi.getJobs()
    const body = (res as any)?.data?.data || (res as any)?.data || []
    jobs.value = Array.isArray(body) ? body : []
    // 统计
    schedulerStats.total_jobs = jobs.value.length
    schedulerStats.running_jobs = jobs.value.filter((j: any) => !j.paused).length
    schedulerStats.paused_jobs = jobs.value.filter((j: any) => j.paused).length
  } catch (e: any) {
    ElMessage.error(e?.message || '加载定时任务失败')
  } finally {
    jobsLoading.value = false
  }
}

async function loadSchedulerStats() {
  try {
    const res = await schedulerApi.getSchedulerStats()
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    if (body && typeof body === 'object' && body.total_jobs != null) {
      Object.assign(schedulerStats, body)
    }
  } catch {
    // 忽略，loadJobs 会兜底计算
  }
}

async function triggerJob(job: any) {
  try {
    await ElMessageBox.confirm(`确定要手动触发任务「${getJobDisplayName(job)}」吗？`, '确认触发', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    jobActionLoading[job.id] = true
    await schedulerApi.triggerJob(job.id, true)
    ElMessage.success('任务已触发')
    setTimeout(() => { loadExecutions(); loadJobs() }, 1000)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '触发失败')
  } finally {
    jobActionLoading[job.id] = false
  }
}

async function pauseJob(job: any) {
  try {
    jobActionLoading[job.id] = true
    await schedulerApi.pauseJob(job.id)
    ElMessage.success('任务已暂停')
    await loadJobs()
  } catch (e: any) {
    ElMessage.error(e?.message || '暂停失败')
  } finally {
    jobActionLoading[job.id] = false
  }
}

async function resumeJob(job: any) {
  try {
    jobActionLoading[job.id] = true
    await schedulerApi.resumeJob(job.id)
    ElMessage.success('任务已恢复')
    await loadJobs()
  } catch (e: any) {
    ElMessage.error(e?.message || '恢复失败')
  } finally {
    jobActionLoading[job.id] = false
  }
}

function viewJobExecutions(job: any) {
  execFilter.job_id = job.id
  execPage.current = 1
  loadExecutions()
  // 滚动到执行记录区域
  setTimeout(() => {
    document.querySelector('.executions-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 100)
}

// 执行记录
const executions = ref<any[]>([])
const execLoading = ref(false)
const execFilter = reactive<{ job_id: string; status: string; is_manual: boolean | null }>({
  job_id: '', status: '', is_manual: null
})
const execPage = reactive({ current: 1, size: 20, total: 0 })

async function loadExecutions() {
  execLoading.value = true
  try {
    const params: any = {
      limit: execPage.size,
      offset: (execPage.current - 1) * execPage.size,
    }
    if (execFilter.job_id) params.job_id = execFilter.job_id
    if (execFilter.status) params.status = execFilter.status
    if (execFilter.is_manual !== null) params.is_manual = execFilter.is_manual

    const res = await schedulerApi.getJobExecutions(params)
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    executions.value = body.items || []
    execPage.total = body.total || 0
  } catch (e: any) {
    ElMessage.error(e?.message || '加载执行记录失败')
  } finally {
    execLoading.value = false
  }
}

async function cancelExecution(row: any) {
  try {
    await ElMessageBox.confirm(`确定要取消执行中的任务「${row.job_name || row.job_id}」吗？`, '确认取消', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await schedulerApi.cancelExecution(row._id)
    ElMessage.success('已发送取消请求')
    setTimeout(() => loadExecutions(), 1000)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '取消失败')
  }
}

async function markFailed(row: any) {
  try {
    await ElMessageBox.confirm(`确定要将执行记录标记为失败吗？`, '确认操作', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await schedulerApi.markExecutionFailed(row._id, '用户手动标记为失败')
    ElMessage.success('已标记为失败')
    await loadExecutions()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '标记失败')
  }
}

async function deleteExecution(row: any) {
  try {
    await ElMessageBox.confirm(`确定要删除这条执行记录吗？此操作不可恢复！`, '确认删除', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'error'
    })
    await schedulerApi.deleteExecution(row._id)
    ElMessage.success('记录已删除')
    await loadExecutions()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}

async function showErrorDetail(row: any) {
  const error = row.error_message || '未知错误'
  const tb = row.traceback ? `\n\n--- Traceback ---\n${row.traceback}` : ''
  try {
    await ElMessageBox.alert(
      (error + tb).replace(/\n/g, '<br>'),
      '错误详情',
      { confirmButtonText: '确定', type: 'error', dangerouslyUseHTMLString: true, customStyle: { width: '700px' } }
    )
  } catch {}
}

// 状态映射
function getExecStatusType(status: string): 'success' | 'info' | 'warning' | 'danger' {
  const map: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
    running: 'warning', success: 'success', failed: 'danger', missed: 'info'
  }
  return map[status] || 'info'
}
function getExecStatusText(status: string): string {
  const map: Record<string, string> = {
    running: '执行中', success: '成功', failed: '失败', missed: '错过'
  }
  return map[status] || status
}

// 格式化
function formatTime(t: string): string {
  return t ? formatDateTime(t) : '-'
}
function formatDuration(seconds: number): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${Math.floor(seconds % 60)}秒`
  return `${(seconds / 3600).toFixed(1)}小时`
}

// 轮询：运行中有记录时自动刷新
let pollTimer: any = null
function setupPolling() {
  clearInterval(pollTimer)
  pollTimer = setInterval(() => {
    // 有执行中的记录或筛选了 running 状态时才刷新
    const hasRunning = executions.value.some(e => e.status === 'running')
    if (hasRunning || execFilter.status === 'running') {
      loadExecutions()
    }
  }, 5000)
}

onMounted(() => {
  loadJobs()
  loadSchedulerStats()
  loadExecutions()
  setupPolling()
})

onUnmounted(() => {
  clearInterval(pollTimer)
})
</script>

<style scoped lang="scss">
.scheduled-tasks-view {
  .stat {
    text-align: center;
    .value {
      font-size: 28px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      &.running { color: var(--el-color-success); }
      &.paused { color: var(--el-text-color-secondary); }
    }
    .label {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin-top: 4px;
    }
  }

  .jobs-card, .executions-card {
    margin-bottom: 16px;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    .card-title {
      font-size: 16px;
      font-weight: 600;
    }
    .filter-bar {
      display: flex;
      gap: 8px;
      align-items: center;
    }
  }

  .job-name-cell {
    display: flex;
    flex-direction: column;
    .job-display-name {
      font-weight: 500;
    }
    .job-id {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      font-family: var(--app-font-mono);
    }
  }

  .text-muted {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .pagination-wrapper {
    display: flex;
    justify-content: center;
    margin-top: 16px;
  }
}
</style>
