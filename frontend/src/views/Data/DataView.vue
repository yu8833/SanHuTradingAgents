<template>
  <div class="data-view">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">数据中心</h2>
          <p class="page-hero-sub">数据状态一览与快捷操作</p>
        </div>
      </div>
    </div>

    <!-- 状态卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value" :class="freshnessClass">{{ freshnessText }}</div>
            <div class="stat-label">数据新鲜度</div>
            <div class="stat-sub" v-if="freshness.latest_data_date">截至 {{ freshness.latest_data_date }}</div>
            <div class="stat-sub" v-else>暂无数据</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value">{{ coveragePercent }}%</div>
            <div class="stat-label">数据覆盖率</div>
            <div class="stat-sub">{{ freshness.total_stocks || 0 }} / {{ freshness.expected_total || 0 }} 只</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value">{{ availableSources }} / {{ totalSources }}</div>
            <div class="stat-label">可用数据源</div>
            <div class="stat-sub">{{ sourceNames }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value" :class="syncStatusClass">{{ syncStatusText }}</div>
            <div class="stat-label">同步状态</div>
            <div class="stat-sub" v-if="syncStatus.started_at">开始: {{ formatTime(syncStatus.started_at) }}</div>
            <div class="stat-sub" v-else>空闲</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 数据源状态 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">数据源状态</span>
          <div class="header-actions">
            <el-button @click="testAllSources" :loading="testing" size="small">
              <el-icon><Connection /></el-icon> 测试全部
            </el-button>
            <el-button @click="loadAll" size="small">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="sources" v-loading="loadingSources" style="width: 100%" class="app-table app-table--compact">
        <el-table-column label="数据源" width="140">
          <template #default="{ row }">
            <span class="source-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.available ? 'success' : 'danger'" size="small">
              {{ row.available ? '✅ 可用' : '❌ 不可用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-muted">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="testSingleSource(row.name)" :loading="testingSource === row.name">
              测试
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 数据操作 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">数据操作</span>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon sync"><el-icon><Refresh /></el-icon></div>
            <div class="action-info">
              <div class="action-title">基础数据同步</div>
              <div class="action-desc">同步股票基础信息（多数据源）</div>
            </div>
            <el-button type="primary" @click="triggerSync" :loading="syncing" :disabled="syncStatus.status === 'running'" size="small">
              {{ syncStatus.status === 'running' ? '同步中...' : '执行同步' }}
            </el-button>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon history"><el-icon><Clock /></el-icon></div>
            <div class="action-info">
              <div class="action-title">历史数据同步</div>
              <div class="action-desc">增量同步历史K线数据</div>
            </div>
            <el-button type="primary" @click="triggerJob('tushare_historical_sync')" :loading="jobLoading === 'tushare_historical_sync'" size="small">
              执行同步
            </el-button>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon integrity"><el-icon><CircleCheck /></el-icon></div>
            <div class="action-info">
              <div class="action-title">完整性检查</div>
              <div class="action-desc">检查数据缺失并自动补数</div>
            </div>
            <el-button type="primary" @click="triggerJob('data_integrity_check')" :loading="jobLoading === 'data_integrity_check'" size="small">
              执行检查
            </el-button>
          </div>
        </el-col>
      </el-row>
      <el-divider />
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon news"><el-icon><Document /></el-icon></div>
            <div class="action-info">
              <div class="action-title">新闻数据同步</div>
              <div class="action-desc">同步自选股与市场新闻</div>
            </div>
            <el-button @click="triggerJob('news_sync')" :loading="jobLoading === 'news_sync'" size="small">
              执行同步
            </el-button>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon financial"><el-icon><Money /></el-icon></div>
            <div class="action-info">
              <div class="action-title">财务数据同步</div>
              <div class="action-desc">同步财务指标数据</div>
            </div>
            <el-button @click="triggerJob('tushare_financial_sync')" :loading="jobLoading === 'tushare_financial_sync'" size="small">
              执行同步
            </el-button>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-block">
            <div class="action-icon task"><el-icon><List /></el-icon></div>
            <div class="action-info">
              <div class="action-title">定时任务管理</div>
              <div class="action-desc">查看和管理所有定时任务</div>
            </div>
            <el-button @click="$router.push('/tasks')" size="small">
              前往任务中心
            </el-button>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 同步进度 -->
    <el-card v-if="syncStatus.status === 'running'" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">同步进度</span>
        </div>
      </template>
      <el-progress :percentage="syncProgress" :stroke-width="20" :text-inside="true" status="success" />
      <div class="sync-detail">
        <span>总计: {{ syncStatus.total || 0 }}</span>
        <span>新增: {{ syncStatus.inserted || 0 }}</span>
        <span>更新: {{ syncStatus.updated || 0 }}</span>
        <span>错误: {{ syncStatus.errors || 0 }}</span>
        <span v-if="syncStatus.data_sources_used?.length">数据源: {{ syncStatus.data_sources_used.join(', ') }}</span>
      </div>
    </el-card>

    <!-- 最近同步记录 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">最近同步记录</span>
          <el-button @click="loadHistory" :loading="loadingHistory" size="small">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-table :data="history" v-loading="loadingHistory" style="width: 100%" size="small" class="app-table app-table--compact">
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getHistoryStatusType(row.status)" size="small">{{ getHistoryStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="180">
          <template #default="{ row }">{{ formatTime(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column label="统计" min-width="200">
          <template #default="{ row }">
            <span class="text-muted">
              总计 {{ row.total || 0 }} / 新增 {{ row.inserted || 0 }} / 更新 {{ row.updated || 0 }} / 错误 {{ row.errors || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="数据源" width="150">
          <template #default="{ row }">
            <span class="text-muted">{{ row.data_sources_used?.join(', ') || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Refresh, Connection, Clock, CircleCheck, Document, Money, List } from '@element-plus/icons-vue'
import * as syncApi from '@/api/sync'
import * as schedulerApi from '@/api/scheduler'
import { screeningApi } from '@/api/screening'
import { formatDateTime } from '@/utils/datetime'

// 数据新鲜度
const freshness = reactive({
  latest_data_date: '' as string,
  expected_date: '' as string,
  is_fresh: false,
  stale_days: 0,
  total_stocks: 0,
  expected_total: 0,
  message: '',
})

const freshnessText = computed(() => {
  if (!freshness.latest_data_date) return '无数据'
  if (freshness.is_fresh) return '最新'
  return `过期${freshness.stale_days}天`
})

const freshnessClass = computed(() => {
  if (!freshness.latest_data_date) return 'danger'
  if (freshness.is_fresh) return 'success'
  return 'warning'
})

const coveragePercent = computed(() => {
  if (!freshness.expected_total) return 0
  return Math.round((freshness.total_stocks / freshness.expected_total) * 100)
})

// 数据源状态
const sources = ref<any[]>([])
const loadingSources = ref(false)
const testing = ref(false)
const testingSource = ref('')

const availableSources = computed(() => sources.value.filter(s => s.available).length)
const totalSources = computed(() => sources.value.length)
const sourceNames = computed(() => sources.value.filter(s => s.available).map(s => s.name).join(', ') || '无可用源')

async function loadSources() {
  loadingSources.value = true
  try {
    const res = await syncApi.getDataSourcesStatus()
    const body = (res as any)?.data?.data || (res as any)?.data || []
    sources.value = Array.isArray(body) ? body : []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载数据源状态失败')
  } finally {
    loadingSources.value = false
  }
}

async function loadFreshness() {
  try {
    const res = await screeningApi.checkDataFreshness()
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    Object.assign(freshness, body)
  } catch (e: any) {
    // 静默失败，不打扰用户
    console.warn('加载数据新鲜度失败:', e)
  }
}

async function testAllSources() {
  testing.value = true
  try {
    const res = await syncApi.testDataSources()
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    if (body.results) {
      const successCount = body.results.filter((r: any) => r.available).length
      ElMessage.success(`${successCount}/${body.results.length} 个数据源可用`)
    } else {
      ElMessage.success('测试完成')
    }
    await loadSources()
  } catch (e: any) {
    ElMessage.error(e?.message || '测试失败')
  } finally {
    testing.value = false
  }
}

async function testSingleSource(name: string) {
  testingSource.value = name
  try {
    const res = await syncApi.testDataSources(name)
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    const result = body.results?.find((r: any) => r.name === name)
    if (result?.available) {
      ElMessage.success(`${name} 连接成功`)
    } else {
      ElMessage.warning(`${name} 不可用: ${result?.message || '未知原因'}`)
    }
    await loadSources()
  } catch (e: any) {
    ElMessage.error(e?.message || `测试 ${name} 失败`)
  } finally {
    testingSource.value = ''
  }
}

// 同步状态
const syncStatus = reactive<any>({})
const syncing = ref(false)

const syncStatusText = computed(() => {
  const s = syncStatus.status
  const map: Record<string, string> = {
    running: '同步中', success: '成功', success_with_errors: '部分成功',
    failed: '失败', idle: '空闲', never_run: '未运行',
  }
  return map[s] || '未知'
})

const syncStatusClass = computed(() => {
  const s = syncStatus.status
  if (s === 'running') return 'warning'
  if (s === 'success') return 'success'
  if (s === 'failed') return 'danger'
  return ''
})

const syncProgress = computed(() => {
  if (syncStatus.status !== 'running') return 0
  const total = syncStatus.total || 0
  if (!total) return 0
  const done = (syncStatus.inserted || 0) + (syncStatus.updated || 0)
  return Math.min(Math.round((done / total) * 100), 99)
})

async function loadSyncStatus() {
  try {
    const res = await syncApi.getSyncStatus()
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    Object.assign(syncStatus, body)
  } catch (e: any) {
    console.warn('加载同步状态失败:', e)
  }
}

async function triggerSync() {
  try {
    await ElMessageBox.confirm('确定要执行基础数据同步吗？此操作可能需要几分钟。', '确认', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
    })
    syncing.value = true
    await syncApi.runStockBasicsSync({ force: false })
    ElMessage.success('同步任务已启动')
    setTimeout(() => loadSyncStatus(), 1000)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '启动同步失败')
  } finally {
    syncing.value = false
  }
}

// 定时任务触发
const jobLoading = ref('')

async function triggerJob(jobId: string) {
  try {
    await ElMessageBox.confirm(`确定要执行「${getJobLabel(jobId)}」吗？`, '确认', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
    })
    jobLoading.value = jobId
    await schedulerApi.triggerJob(jobId, true)
    ElMessage.success('任务已触发')
    setTimeout(() => loadSyncStatus(), 2000)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '触发失败')
  } finally {
    jobLoading.value = ''
  }
}

function getJobLabel(jobId: string): string {
  const map: Record<string, string> = {
    tushare_historical_sync: '历史数据同步',
    data_integrity_check: '数据完整性检查',
    news_sync: '新闻数据同步',
    tushare_financial_sync: '财务数据同步',
  }
  return map[jobId] || jobId
}

// 同步历史
const history = ref<any[]>([])
const loadingHistory = ref(false)

async function loadHistory() {
  loadingHistory.value = true
  try {
    const res = await syncApi.getSyncHistory({ page: 1, page_size: 5 })
    const body = (res as any)?.data?.data || (res as any)?.data || {}
    history.value = body.records || []
  } catch (e: any) {
    console.warn('加载同步历史失败:', e)
  } finally {
    loadingHistory.value = false
  }
}

function getHistoryStatusType(status: string): 'success' | 'info' | 'warning' | 'danger' {
  const map: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
    success: 'success', success_with_errors: 'warning', failed: 'danger',
    running: 'warning', idle: 'info', never_run: 'info',
  }
  return map[status] || 'info'
}

function getHistoryStatusText(status: string): string {
  const map: Record<string, string> = {
    success: '成功', success_with_errors: '部分成功', failed: '失败',
    running: '运行中', idle: '空闲', never_run: '未运行',
  }
  return map[status] || status
}

function formatTime(t: string): string {
  return t ? formatDateTime(t) : '-'
}

// 加载全部
async function loadAll() {
  await Promise.all([loadFreshness(), loadSources(), loadSyncStatus(), loadHistory()])
}

// 轮询：同步进行中时刷新
let pollTimer: any = null
function setupPolling() {
  clearInterval(pollTimer)
  pollTimer = setInterval(() => {
    if (syncStatus.status === 'running') {
      loadSyncStatus()
    }
  }, 5000)
}

onMounted(() => {
  loadAll()
  setupPolling()
})

onUnmounted(() => {
  clearInterval(pollTimer)
})
</script>

<style scoped lang="scss">
.data-view {
  .stat-row { margin-bottom: 16px; }
  .stat-card {
    .stat-content { text-align: center; padding: 8px 0; }
    .stat-value {
      font-size: 28px; font-weight: 600; color: var(--el-text-color-primary);
      &.success { color: var(--el-color-success); }
      &.warning { color: var(--el-color-warning); }
      &.danger { color: var(--el-color-danger); }
    }
    .stat-label { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 4px; }
    .stat-sub { font-size: 12px; color: var(--el-text-color-placeholder); margin-top: 2px; }
  }

  .section-card { margin-bottom: 16px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; }
  .card-title { font-size: 16px; font-weight: 600; }
  .header-actions { display: flex; gap: 8px; }

  .source-name { font-weight: 500; text-transform: capitalize; }
  .text-muted { color: var(--el-text-color-secondary); font-size: 13px; }

  .action-block {
    display: flex; align-items: center; gap: 12px; padding: 12px;
    border: 1px solid var(--el-border-color-lighter); border-radius: 8px;
    transition: box-shadow 0.2s;
    &:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    .action-icon {
      width: 40px; height: 40px; border-radius: 8px; display: flex;
      align-items: center; justify-content: center; font-size: 20px; color: #fff;
      &.sync { background: var(--el-color-primary); }
      &.history { background: var(--el-color-success); }
      &.integrity { background: var(--el-color-warning); }
      &.news { background: #909399; }
      &.financial { background: #9c27b0; }
      &.task { background: #22568d; }
    }
    .action-info { flex: 1; min-width: 0; }
    .action-title { font-weight: 500; font-size: 14px; }
    .action-desc { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
  }

  .sync-detail {
    display: flex; gap: 24px; margin-top: 12px; font-size: 13px;
    color: var(--el-text-color-regular);
  }
}
</style>
