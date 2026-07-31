<template>
  <div class="dashboard">
    <!-- 欢迎区域 -->
    <div class="welcome-section">
      <div class="welcome-content">
        <h1 class="welcome-title">
          欢迎使用 股票分析系统
          <span class="version-badge">v1.0.1</span>
        </h1>
        <p class="welcome-subtitle">
          现代化的多智能体股票分析学习平台，辅助你掌握更全面的市场视角分析股票
        </p>
      </div>
      <div class="welcome-actions">
        <el-button type="primary" size="large" @click="quickAnalysis">
          <el-icon><TrendCharts /></el-icon>
          快速分析
        </el-button>
        <el-button size="large" @click="goToScreening">
          <el-icon><Search /></el-icon>
          股票筛选
        </el-button>
      </div>
    </div>


    <!-- 学习中心推荐卡片 -->
    <el-card class="learning-highlight-card">
      <div class="learning-highlight">
        <div class="learning-icon">
          <el-icon size="48"><Reading /></el-icon>
        </div>
        <div class="learning-content">
          <h2>📚 AI股票分析学习中心</h2>
          <p>从零开始学习AI、大语言模型和智能股票分析。了解多智能体系统如何协作分析股票，掌握提示词工程技巧，选择合适的大模型，理解AI的能力与局限性。</p>
          <div class="learning-features">
            <span class="feature-tag">🤖 AI基础知识</span>
            <span class="feature-tag">✍️ 提示词工程</span>
            <span class="feature-tag">🎯 模型选择</span>
            <span class="feature-tag">📊 分析原理</span>
            <span class="feature-tag">⚠️ 风险认知</span>
            <span class="feature-tag">🎓 实战教程</span>
          </div>
        </div>
        <div class="learning-action">
          <el-button type="primary" size="large" @click="goToLearning">
            <el-icon><Reading /></el-icon>
            开始学习
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 主要功能区域 -->
    <el-row :gutter="24" class="main-content">
      <!-- 左侧：快速操作 -->
      <el-col :span="16">
        <el-card class="quick-actions-card" header="快速操作">
          <div class="quick-actions">
            <div class="action-item" @click="goToBatchAnalysis">
              <div class="action-icon">
                <el-icon><Files /></el-icon>
              </div>
              <div class="action-content">
                <h3>批量分析</h3>
                <p>同时分析多只股票，提高效率</p>
              </div>
              <el-icon class="action-arrow"><ArrowRight /></el-icon>
            </div>

            <div class="action-item" @click="goToScreening">
              <div class="action-icon">
                <el-icon><Search /></el-icon>
              </div>
              <div class="action-content">
                <h3>股票筛选</h3>
                <p>通过多维度条件筛选优质股票</p>
              </div>
              <el-icon class="action-arrow"><ArrowRight /></el-icon>
            </div>

            <div class="action-item" @click="goToQueue">
              <div class="action-icon">
                <el-icon><List /></el-icon>
              </div>
              <div class="action-content">
                <h3>任务中心</h3>
                <p>查看和管理分析任务列表</p>
              </div>
              <el-icon class="action-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </el-card>

        <!-- 最近分析 -->
        <el-card class="recent-analyses-card" header="最近分析" style="margin-top: 24px;">
          <el-table :data="recentAnalyses" style="width: 100%">
            <el-table-column prop="stock_code" label="股票代码" width="120">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.stock_code}`" target="_blank">{{ row.stock_code }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="stock_name" label="股票名称" width="150" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)">
                  {{ getStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="start_time" label="创建时间" width="180">
              <template #default="{ row }">
                {{ formatTime(row.start_time) }}
              </template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button type="text" size="small" @click="viewAnalysis(row)">
                  查看
                </el-button>
                <el-button
                  v-if="row.status === 'completed'"
                  type="text"
                  size="small"
                  @click="downloadReport(row)"
                >
                  下载
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="table-footer">
            <el-button type="text" @click="goToHistory">
              查看全部历史 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </el-card>

        <!-- 市场快讯 -->
        <el-card class="market-news-card" style="margin-top: 24px;">
          <template #header>
            <span>市场快讯</span>
          </template>
          <div v-if="marketNews.length > 0" class="news-list">
            <div
              v-for="news in marketNews"
              :key="news.id"
              class="news-item"
              @click="openNewsUrl(news.url)"
            >
              <div class="news-title">{{ news.title }}</div>
              <div class="news-time">{{ formatTime(news.time) }}</div>
            </div>
          </div>
          <div v-else class="empty-state">
            <el-icon class="empty-icon"><InfoFilled /></el-icon>
            <p>暂无市场快讯</p>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：自选股和快讯 -->
      <el-col :span="8">
        <!-- 我的自选股 -->
        <el-card class="favorites-card">
          <template #header>
            <div class="card-header">
              <span>我的自选股</span>
              <el-button type="text" size="small" @click="goToFavorites">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <div v-if="favoriteStocks.length === 0" class="empty-favorites">
            <el-empty description="暂无自选股" :image-size="60">
              <el-button type="primary" size="small" @click="goToFavorites">
                添加自选股
              </el-button>
            </el-empty>
          </div>

          <div v-else class="favorites-list">
            <div
              v-for="stock in favoriteStocks.slice(0, 5)"
              :key="stock.stock_code"
              class="favorite-item"
              @click="viewStockDetail(stock)"
            >
              <div class="stock-info">
                <div class="stock-code">{{ stock.stock_code }}</div>
                <div class="stock-name">{{ stock.stock_name }}</div>
              </div>
              <div class="stock-price">
                <div class="current-price">¥{{ stock.current_price }}</div>
                <div
                  class="change-percent"
                  :class="getPriceChangeClass(stock.change_percent)"
                >
                  {{ stock.change_percent > 0 ? '+' : '' }}{{ Number(stock.change_percent).toFixed(2) }}%
                </div>
              </div>
            </div>
          </div>

          <div v-if="favoriteStocks.length > 5" class="favorites-footer">
            <el-button type="text" size="small" @click="goToFavorites">
              查看全部 {{ favoriteStocks.length }} 只自选股
            </el-button>
          </div>
        </el-card>

        <!-- 模拟交易账户 -->
        <el-card class="paper-trading-card" style="margin-top: 24px;">
          <template #header>
            <div class="card-header">
              <span>模拟交易账户</span>
              <el-button type="text" size="small" @click="goToPaperTrading">
                查看详情 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <div v-if="paperAccount" class="paper-account-info">
            <!-- A股账户 -->
            <div class="account-section">
              <div class="account-section-title">🇨🇳 A股账户</div>
              <div class="account-item">
                <div class="account-label">现金</div>
                <div class="account-value">¥{{ formatMoney(getCurrencyAmount(paperAccount.cash, 'CNY')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">持仓市值</div>
                <div class="account-value">¥{{ formatMoney(getCurrencyAmount(paperAccount.positions_value, 'CNY')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">总资产</div>
                <div class="account-value primary">¥{{ formatMoney(getCurrencyAmount(paperAccount.equity, 'CNY')) }}</div>
              </div>
            </div>

            <!-- 港股账户 -->
            <div class="account-section" v-if="typeof paperAccount.cash !== 'number' && paperAccount.cash?.HKD !== undefined">
              <div class="account-section-title">🇭🇰 港股账户</div>
              <div class="account-item">
                <div class="account-label">现金</div>
                <div class="account-value">HK${{ formatMoney(getCurrencyAmount(paperAccount.cash, 'HKD')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">持仓市值</div>
                <div class="account-value">HK${{ formatMoney(getCurrencyAmount(paperAccount.positions_value, 'HKD')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">总资产</div>
                <div class="account-value primary">HK${{ formatMoney(getCurrencyAmount(paperAccount.equity, 'HKD')) }}</div>
              </div>
            </div>

            <!-- 美股账户 -->
            <div class="account-section" v-if="typeof paperAccount.cash !== 'number' && paperAccount.cash?.USD !== undefined">
              <div class="account-section-title">🇺🇸 美股账户</div>
              <div class="account-item">
                <div class="account-label">现金</div>
                <div class="account-value">${{ formatMoney(getCurrencyAmount(paperAccount.cash, 'USD')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">持仓市值</div>
                <div class="account-value">${{ formatMoney(getCurrencyAmount(paperAccount.positions_value, 'USD')) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">总资产</div>
                <div class="account-value primary">${{ formatMoney(getCurrencyAmount(paperAccount.equity, 'USD')) }}</div>
              </div>
            </div>
          </div>

          <div v-else class="empty-state">
            <el-icon class="empty-icon"><InfoFilled /></el-icon>
            <p>暂无账户信息</p>
            <el-button type="primary" size="small" @click="goToPaperTrading">
              查看模拟交易
            </el-button>
          </div>
        </el-card>

        <!-- 数据新鲜度 -->
        <el-card class="freshness-card" shadow="hover" style="margin-top: 24px;">
          <template #header>
            <div class="card-header">
              <span><el-icon style="margin-right:6px;"><Refresh /></el-icon>数据新鲜度</span>
              <el-button v-if="!freshness.is_fresh && freshness.latest_data_date" type="warning" size="small" @click="openSyncConfirm">
                <el-icon><Refresh /></el-icon> 更新数据
              </el-button>
            </div>
          </template>
          <div class="freshness-body">
            <div v-if="freshnessLoading" class="freshness-loading">
              <el-icon class="loading-icon"><Loading /></el-icon> 加载中...
            </div>
            <div v-else-if="!freshness.latest_data_date" class="empty-state">
              <el-icon class="empty-icon"><Warning /></el-icon>
              <p>暂无数据</p>
              <el-button type="primary" size="small" @click="openSyncConfirm">初始化数据</el-button>
            </div>
            <div v-else class="freshness-info">
              <div class="freshness-status">
                <div :class="['freshness-badge', freshness.is_fresh ? 'fresh' : 'stale']">
                  {{ freshness.is_fresh ? '✅ 最新' : freshness.stale_days > 0 ? `⚠️ 过期 ${freshness.stale_days} 天` : '⏳ 待更新' }}
                </div>
                <div class="freshness-label">
                  数据日期：{{ freshness.latest_data_date }}
                </div>
              </div>
              <div class="freshness-meta">
                <div>预期：{{ freshness.expected_date || '-' }}</div>
                <div>{{ freshness.message || '' }}</div>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 数据覆盖率 -->
        <el-card class="coverage-card" shadow="hover" style="margin-top: 24px;">
          <template #header>
            <div class="card-header">
              <span><el-icon style="margin-right:6px;"><CircleCheck /></el-icon>数据覆盖率</span>
              <el-button v-if="coveragePercent < 95 && freshness.total_stocks > 0" type="warning" size="small" @click="openIntegrityConfirm">
                <el-icon><MagicStick /></el-icon> 检查并补数
              </el-button>
            </div>
          </template>
          <div class="coverage-body">
            <div v-if="!freshness.latest_data_date" class="empty-state coverage-empty">
              <el-icon class="empty-icon"><Warning /></el-icon>
              <p>暂无数据</p>
            </div>
            <div v-else>
              <el-progress
                :percentage="coveragePercent"
                :status="coverageStatus"
                :stroke-width="16"
                :text-inside="true"
              />
              <div class="coverage-meta">
                <div>有数据：{{ freshness.total_stocks || 0 }} 只</div>
                <div>预期：{{ freshness.expected_total || 0 }} 只</div>
                <div v-if="freshness.total_stocks > 0 && freshness.expected_total > 0 && (freshness.expected_total - freshness.total_stocks) > 0" class="coverage-gap">
                  缺失：{{ freshness.expected_total - freshness.total_stocks }} 只
                </div>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 多数据源同步 -->
        <MultiSourceSyncCard style="margin-top: 24px;" />
      </el-col>
    </el-row>
    <!-- 同步确认对话框 -->
    <el-dialog
      v-model="syncConfirmVisible"
      title="确认更新数据"
      width="480px"
      :close-on-click-modal="false"
    >
      <div v-if="!syncRunning" class="confirm-body">
        <el-alert
          :title="freshness.is_fresh ? '建议不要频繁同步，系统已设置自动同步任务' : '数据已过期，建议立即同步'"
          :type="freshness.is_fresh ? 'info' : 'warning'"
          :closable="false"
          show-icon
        />
        <div class="confirm-tip" style="margin-top: 16px;">
          <div>⏱️ 预估耗时：5 ~ 15 分钟</div>
          <div>📦 同步范围：股票基础信息、实时行情、历史K线</div>
          <div>🔄 同步完成后会自动刷新页面数据</div>
        </div>
      </div>
      <div v-else class="progress-body">
        <div class="progress-title">
          <el-icon style="color: var(--el-color-primary); margin-right:8px;"><Loading /></el-icon>
          正在同步数据，请勿关闭页面...
        </div>
        <el-progress
          :percentage="syncProgress"
          :status="syncError ? 'exception' : undefined"
          :stroke-width="16"
          :text-inside="false"
        />
        <div class="progress-meta">
          <div>状态：<b>{{ syncStatusMessage }}</b></div>
          <div v-if="syncPhase === 1 && syncTotal > 0">
            阶段1进度：{{ syncDone }} / {{ syncTotal }}
            （新增 {{ syncInserted }}，更新 {{ syncUpdated }}，错误 {{ syncErrors }}）
          </div>
          <div v-if="syncPhase === 2" class="phase-hint">
            阶段2正在同步历史K线数据，耗时较长（约10-30分钟），覆盖率将在全部完成后恢复。
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="!syncRunning" @click="syncConfirmVisible = false">取消</el-button>
        <el-button v-if="!syncRunning" type="primary" :loading="syncStarting" @click="doSync">
          确认同步
        </el-button>
        <el-button v-if="syncRunning" :disabled="!syncFinished" @click="syncConfirmVisible = false">
          {{ syncFinished ? '关闭' : '同步中...' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 完整性检查对话框 -->
    <el-dialog
      v-model="integrityConfirmVisible"
      title="确认执行完整性检查与补数"
      width="520px"
      :close-on-click-modal="false"
    >
      <div v-if="!integrityRunning" class="confirm-body">
        <el-alert
          title="系统将扫描最新交易日的数据缺失，并自动使用备用数据源补数"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="confirm-tip" style="margin-top: 16px;">
          <div>📊 当前覆盖率：<b>{{ coveragePercent }}%</b>（{{ freshness.total_stocks || 0 }} / {{ freshness.expected_total || 0 }} 只）</div>
          <div>🧩 补数降级链：AKShare → BaoStock → Tushare</div>
          <div>⏱️ 预估耗时：3 ~ 10 分钟</div>
        </div>
      </div>
      <div v-else class="progress-body">
        <div class="progress-title">
          <el-icon style="color: var(--el-color-primary); margin-right:8px;"><Loading /></el-icon>
          正在检查数据完整性并补数...
        </div>
        <el-progress
          :percentage="integrityProgress"
          :status="integrityError ? 'exception' : undefined"
          :stroke-width="16"
        />
        <div class="progress-meta">
          <div>状态：<b>{{ integrityStatusMessage }}</b></div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="!integrityRunning" @click="integrityConfirmVisible = false">取消</el-button>
        <el-button v-if="!integrityRunning" type="primary" :loading="integrityStarting" @click="doIntegrityCheck">
          确认执行
        </el-button>
        <el-button v-if="integrityRunning" :disabled="!integrityFinished" @click="onIntegrityClose">
          {{ integrityFinished ? '关闭' : '执行中...' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'DashboardHome' })
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  TrendCharts,
  Search,
  Document,
  Files,
  List,
  ArrowRight,
  InfoFilled,
  Reading,
  Loading,
  Warning,
  Refresh,
  CircleCheck,
  MagicStick
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { AnalysisTask, AnalysisStatus } from '@/types/analysis'
import MultiSourceSyncCard from '@/components/Dashboard/MultiSourceSyncCard.vue'
import { favoritesApi } from '@/api/favorites'
import { analysisApi } from '@/api/analysis'
import { newsApi } from '@/api/news'
import { paperApi, type PaperAccountSummary } from '@/api/paper'
import * as syncApi from '@/api/sync'
import * as schedulerApi from '@/api/scheduler'
import { screeningApi } from '@/api/screening'

const router = useRouter()
const authStore = useAuthStore()

// 响应式数据
const userStats = ref({
  totalAnalyses: 0,
  successfulAnalyses: 0,
  dailyQuota: 1000,
  dailyUsed: 0,
  concurrentLimit: 3
})

const recentAnalyses = ref<AnalysisTask[]>([])

// 自选股数据
const favoriteStocks = ref<any[]>([])

// 市场快讯数据
const marketNews = ref<any[]>([])

// 模拟交易账户数据
const paperAccount = ref<PaperAccountSummary | null>(null)

// ---------- 数据新鲜度 + 覆盖率 ----------
const freshnessLoading = ref(true)
const freshness = reactive({
  latest_data_date: '' as string,
  expected_date: '' as string,
  is_fresh: false,
  stale_days: 0,
  total_stocks: 0,
  expected_total: 0,
  message: '' as string,
})

const coveragePercent = computed(() => {
  if (!freshness.expected_total) return 0
  return Math.min(100, Math.round((freshness.total_stocks / freshness.expected_total) * 100))
})

const coverageStatus = computed(() => {
  if (coveragePercent.value >= 95) return 'success' as const
  if (coveragePercent.value >= 70) return 'warning' as const
  return 'exception' as const
})

// ---------- 同步对话框 ----------
const syncConfirmVisible = ref(false)
const syncStarting = ref(false)
const syncRunning = ref(false)
const syncFinished = ref(false)
const syncError = ref(false)
const syncProgress = ref(0)
const syncStatusMessage = ref('准备开始同步')
const syncTotal = ref(0)
const syncDone = ref(0)
const syncInserted = ref(0)
const syncUpdated = ref(0)
const syncErrors = ref(0)

const openSyncConfirm = () => {
  syncRunning.value = false
  syncFinished.value = false
  syncError.value = false
  syncProgress.value = 0
  syncStatusMessage.value = '准备开始同步'
  syncConfirmVisible.value = true
}

const closeSyncPoll = ref<any>(null)
const closeSyncTimer = ref<any>(null)
const stopSyncPoll = () => {
  if (closeSyncPoll.value) {
    clearInterval(closeSyncPoll.value)
    closeSyncPoll.value = null
  }
}
const stopSyncTimer = () => {
  if (closeSyncTimer.value) {
    clearTimeout(closeSyncTimer.value)
    closeSyncTimer.value = null
  }
}

// 同步阶段：1=基础信息同步 2=历史K线同步
const syncPhase = ref(1)

const doSync = async () => {
  syncStarting.value = true
  syncPhase.value = 1
  try {
    // 阶段1：触发基础数据同步
    await syncApi.runStockBasicsSync({ force: true })
    syncRunning.value = true
    syncProgress.value = 5
    syncStatusMessage.value = '阶段1/2：同步股票基础信息...'
    syncTotal.value = 0
    syncDone.value = 0
    syncInserted.value = 0
    syncUpdated.value = 0
    syncErrors.value = 0

    let pollCount = 0
    const MAX_POLL = 600
    stopSyncPoll()
    closeSyncPoll.value = setInterval(async () => {
      pollCount++
      if (pollCount >= MAX_POLL) {
        stopSyncPoll()
        syncStatusMessage.value = '轮询超时，任务可能仍在后台执行，请在任务中心查看'
        syncProgress.value = 90
        syncFinished.value = true
        return
      }
      try {
        // 阶段1：轮询基础信息同步状态
        if (syncPhase.value === 1) {
          const res = await syncApi.getSyncStatus()
          const status = (res as any)?.data?.data || (res as any)?.data || {}
          syncTotal.value = status.total || 0
          syncInserted.value = status.inserted || 0
          syncUpdated.value = status.updated || 0
          syncErrors.value = status.errors || 0
          syncDone.value = (status.inserted || 0) + (status.updated || 0)

          if (status.status === 'running') {
            syncStatusMessage.value = '阶段1/2：同步股票基础信息...'
            if (syncTotal.value > 0) {
              syncProgress.value = Math.min(45, Math.round((syncDone.value / syncTotal.value) * 45))
            } else {
              syncProgress.value = Math.min(45, syncProgress.value + 1)
            }
          } else if (status.status === 'success' || status.status === 'success_with_errors') {
            // 基础信息同步完成，进入阶段2
            syncPhase.value = 2
            syncProgress.value = 50
            syncStatusMessage.value = '阶段1完成 ✅，阶段2/2：同步历史K线数据（耗时较长）...'
            // 触发历史K线同步
            try {
              await schedulerApi.triggerJob('tushare_historical_sync', true)
            } catch (_) { /* 可能已在运行 */ }
          } else if (status.status === 'failed') {
            stopSyncPoll()
            syncError.value = true
            syncProgress.value = 100
            syncStatusMessage.value = `基础信息同步失败：${status.message || '未知错误'}`
            syncFinished.value = true
            ElMessage.error('基础信息同步失败')
          }
        } else if (syncPhase.value === 2) {
          // 阶段2：轮询历史K线同步状态
          const res = await schedulerApi.getJobExecutions({
            job_id: 'tushare_historical_sync',
            status: 'running',
            limit: 1,
          })
          const running = (res as any)?.data?.data?.items || (res as any)?.data?.items || []
          if (running.length > 0) {
            syncStatusMessage.value = '阶段2/2：同步历史K线数据中...'
            syncProgress.value = Math.min(95, 50 + (running[0].progress || 0) * 0.45)
          } else {
            // 没有 running 记录，检查是否已完成
            const res2 = await schedulerApi.getJobExecutions({
              job_id: 'tushare_historical_sync',
              status: 'completed',
              limit: 1,
            })
            const completed = (res2 as any)?.data?.data?.items || (res2 as any)?.data?.items || []
            if (completed.length > 0) {
              stopSyncPoll()
              syncProgress.value = 100
              syncStatusMessage.value = '全部同步完成 ✅'
              syncFinished.value = true
              ElMessage.success('数据同步全部完成')
              await loadFreshness()
              closeSyncTimer.value = setTimeout(() => {
                syncConfirmVisible.value = false
              }, 2500)
              return
            }
            // 检查是否失败
            const res3 = await schedulerApi.getJobExecutions({
              job_id: 'tushare_historical_sync',
              status: 'failed',
              limit: 1,
            })
            const failed = (res3 as any)?.data?.data?.items || (res3 as any)?.data?.items || []
            if (failed.length > 0) {
              stopSyncPoll()
              syncProgress.value = 100
              syncStatusMessage.value = '历史K线同步失败，基础信息已更新。可在任务中心查看详情。'
              syncFinished.value = true
              await loadFreshness()
              closeSyncTimer.value = setTimeout(() => {
                syncConfirmVisible.value = false
              }, 4000)
              return
            }
            // 既没有 running 也没有 completed/failed，可能在排队
            syncProgress.value = Math.min(95, syncProgress.value + 1)
            syncStatusMessage.value = '阶段2/2：等待历史K线同步任务调度...'
          }
        }
      } catch (_e) {
        // 轮询失败不终止
      }
    }, 5000)

    syncStarting.value = false
    syncConfirmVisible.value = true
  } catch (e: any) {
    syncError.value = true
    syncFinished.value = true
    syncStatusMessage.value = `启动失败：${e?.message || '未知错误'}`
    ElMessage.error('启动同步失败：' + (e?.message || '未知错误'))
  } finally {
    syncStarting.value = false
  }
}

// ---------- 完整性检查对话框 ----------
const integrityConfirmVisible = ref(false)
const integrityStarting = ref(false)
const integrityRunning = ref(false)
const integrityFinished = ref(false)
const integrityError = ref(false)
const integrityProgress = ref(0)
const integrityStatusMessage = ref('准备执行')

const openIntegrityConfirm = () => {
  integrityRunning.value = false
  integrityFinished.value = false
  integrityError.value = false
  integrityProgress.value = 0
  integrityStatusMessage.value = '准备执行完整性检查'
  integrityConfirmVisible.value = true
}

const integrityPollTimer = ref<any>(null)
const integrityCloseTimer = ref<any>(null)
const stopIntegrityPoll = () => {
  if (integrityPollTimer.value) {
    clearInterval(integrityPollTimer.value)
    integrityPollTimer.value = null
  }
}
const stopIntegrityTimer = () => {
  if (integrityCloseTimer.value) {
    clearTimeout(integrityCloseTimer.value)
    integrityCloseTimer.value = null
  }
}

const doIntegrityCheck = async () => {
  integrityStarting.value = true
  try {
    // 触发 data_integrity_check 定时任务（包含补数）
    await schedulerApi.triggerJob('data_integrity_check', true)
    integrityRunning.value = true
    integrityProgress.value = 10
    integrityStatusMessage.value = '任务已提交，正在执行完整性检查与补数...'

    let pollCount = 0
    const MAX_POLL = 240 // 最多 20 分钟
    stopIntegrityPoll()
    integrityPollTimer.value = setInterval(async () => {
      pollCount++
      if (pollCount >= MAX_POLL) {
        stopIntegrityPoll()
        integrityStatusMessage.value = '轮询超时，任务仍在后台执行'
        integrityProgress.value = 85
        integrityFinished.value = true
        return
      }
      try {
        // 通过 executions 接口查看任务状态
        const res = await schedulerApi.getJobExecutions({
          job_id: 'data_integrity_check',
          status: 'running',
          limit: 1,
        })
        const items = (res as any)?.data?.data?.items || (res as any)?.data?.items || []
        if (items.length > 0) {
          const exec = items[0]
          integrityProgress.value = Math.min(85, 15 + (exec.progress || 0))
          integrityStatusMessage.value = exec.message || '检查与补数中...'
        } else {
          // 没有 running 记录，检查是否已有 completed 记录或重新加载数据
          const res2 = await schedulerApi.getJobExecutions({
            job_id: 'data_integrity_check',
            status: 'completed',
            limit: 1,
          })
          const completed = (res2 as any)?.data?.data?.items || (res2 as any)?.data?.items || []
          if (completed.length > 0) {
            stopIntegrityPoll()
            integrityProgress.value = 100
            integrityStatusMessage.value = '检查与补数完成 ✅'
            integrityFinished.value = true
            ElMessage.success('完整性检查与补数完成')
            await loadFreshness()
            // 延迟自动关闭
            integrityCloseTimer.value = setTimeout(() => {
              integrityConfirmVisible.value = false
            }, 2500)
            return
          }
          const res3 = await schedulerApi.getJobExecutions({
            job_id: 'data_integrity_check',
            status: 'failed',
            limit: 1,
          })
          const failed = (res3 as any)?.data?.data?.items || (res3 as any)?.data?.items || []
          if (failed.length > 0) {
            stopIntegrityPoll()
            integrityError.value = true
            integrityProgress.value = 100
            integrityStatusMessage.value = `执行失败：${failed[0].error_message || failed[0].message || '未知'}`
            integrityFinished.value = true
            ElMessage.warning('完整性检查执行失败')
            // 失败时不自动关闭，让用户查看错误
            return
          }
          integrityProgress.value = Math.min(85, integrityProgress.value + 2)
          integrityStatusMessage.value = '检查与补数中...'
        }
      } catch (_e) {
        // 静默
      }
    }, 5000)

    integrityStarting.value = false
  } catch (e: any) {
    integrityError.value = true
    integrityFinished.value = true
    integrityStatusMessage.value = `启动失败：${e?.message || '未知错误'}`
    ElMessage.error('启动完整性检查失败：' + (e?.message || '未知错误'))
  } finally {
    integrityStarting.value = false
  }
}

const onIntegrityClose = () => {
  if (!integrityRunning.value) integrityConfirmVisible.value = false
  else if (integrityFinished.value) integrityConfirmVisible.value = false
}

const loadFreshness = async () => {
  freshnessLoading.value = true
  try {
    const res = await screeningApi.checkDataFreshness()
    const data = (res as any)?.data?.data || (res as any)?.data || {}
    Object.assign(freshness, data)
  } catch (e) {
    console.warn('加载数据新鲜度失败', e)
  } finally {
    freshnessLoading.value = false
  }
}

// ---------- 通用 ----------
const getCurrencyAmount = (
  amount: number | { CNY: number; HKD: number; USD: number } | undefined,
  currency: 'CNY' | 'HKD' | 'USD',
  fallback = 0
): number => {
  if (typeof amount === 'number') return amount
  return amount?.[currency] ?? fallback
}

onBeforeUnmount(() => {
  stopSyncPoll()
  stopSyncTimer()
  stopIntegrityPoll()
  stopIntegrityTimer()
})



// 方法
const quickAnalysis = () => {
  router.push('/analysis/batch')
}

const goToBatchAnalysis = () => {
  router.push('/analysis/batch')
}

const goToScreening = () => {
  router.push('/screening')
}

const goToQueue = () => {
  router.push('/queue')
}

const goToHistory = () => {
  router.push('/tasks?tab=completed')
}

const goToLearning = () => {
  router.push('/learning')
}

const viewAnalysis = (analysis: AnalysisTask) => {
  const status = (analysis as any)?.status
  if (status === 'completed') {
    router.push({ name: 'ReportDetail', params: { id: analysis.task_id } })
  } else {
    // 未完成任务跳转到任务中心的“进行中”标签页
    router.push('/tasks?tab=running')
  }
}

const downloadReport = async (analysis: AnalysisTask) => {
  try {
    const reportId = analysis.task_id
    const res = await fetch(`/api/reports/${reportId}/download?format=markdown`, {
      headers: {
        'Authorization': `Bearer ${authStore.token}`
      }
    })
    if (!res.ok) {
      const msg = `下载失败：HTTP ${res.status}`
      console.error(msg)
      ElMessage.error('下载失败，报告可能尚未生成')
      return
    }
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const code = (analysis as any).stock_code || (analysis as any).stock_symbol || 'stock'
    const dateStr = (analysis as any).analysis_date || (analysis as any).start_time || ''
    // 🔥 统一文件名格式：{code}_分析报告_{date}.md
    a.download = `${code}_分析报告_${String(dateStr).slice(0,10)}.md`
    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)
    ElMessage.success('报告已开始下载')
  } catch (err) {
    console.error('下载报告出错:', err)
    ElMessage.error('下载失败，请稍后重试')
  }
}

const openNewsUrl = (url?: string) => {
  if (url) {
    window.open(url, '_blank')
  } else {
    ElMessage.info('该新闻暂无详情链接')
  }
}

const getStatusType = (status: string | AnalysisStatus): 'success' | 'info' | 'warning' | 'danger' => {
  const statusMap: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
    pending: 'info',
    processing: 'warning',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info'
  }
  return statusMap[status] || 'info'
}

const getStatusText = (status: string | AnalysisStatus) => {
  const statusMap: Record<string, string> = {
    pending: '等待中',
    processing: '处理中',
    running: '处理中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }
  return statusMap[status] || String(status)
}

import { formatDateTime } from '@/utils/datetime'

const formatTime = (time: string) => {
  return formatDateTime(time)
}

// 自选股相关方法
const goToFavorites = () => {
  router.push('/favorites')
}

const viewStockDetail = (stock: any) => {
  // 跳转到批量分析页并带入股票代码
  router.push(`/analysis/batch?stock=${stock.stock_code}`)
}

const getPriceChangeClass = (changePercent: number) => {
  if (changePercent > 0) return 'price-up'
  if (changePercent < 0) return 'price-down'
  return 'price-neutral'
}

const loadFavoriteStocks = async () => {
  try {
    const response = await favoritesApi.list()
    if (response.success && response.data) {
      favoriteStocks.value = response.data.map((item: any) => ({
        stock_code: item.stock_code,
        stock_name: item.stock_name,
        current_price: item.current_price || 0,
        change_percent: item.change_percent || 0
      }))
    }
  } catch (error) {
    console.error('加载自选股失败:', error)
  }
}

const loadRecentAnalyses = async () => {
  try {
    // 使用任务中心的用户任务接口，获取最近10条
    const res = await analysisApi.getTaskList({
      limit: 10,
      offset: 0,
      // 不限定状态，展示最近任务；如需仅展示已完成可设为 'completed'
      status: undefined
    })

    // 兼容不同返回结构（ApiResponse 或直接 data）
    const body: any = (res as any)?.data?.data || (res as any)?.data || res || {}
    const tasks = body.tasks || []

    recentAnalyses.value = tasks
    // 优先使用后端返回的统计数据
    if (body.stats) {
      userStats.value.totalAnalyses = body.stats.total ?? tasks.length
      userStats.value.successfulAnalyses = body.stats.completed ?? 0
    } else {
      userStats.value.totalAnalyses = body.total ?? tasks.length
      userStats.value.successfulAnalyses = tasks.filter((item: any) => item.status === 'completed').length
    }
  } catch (error) {
    console.error('加载最近分析失败:', error)
    recentAnalyses.value = []
  }
}

const loadMarketNews = async () => {
  try {
    // 先尝试获取最近 24 小时的新闻
    let response = await newsApi.getLatestNews(undefined, 10, 24)

    // 如果最近 24 小时没有新闻，则获取最新的 10 条（不限时间）
    if (response.success && response.data && response.data.news.length === 0) {
      console.log('最近 24 小时没有新闻，获取最新的 10 条新闻（不限时间）')
      response = await newsApi.getLatestNews(undefined, 10, 24 * 365) // 回溯 1 年
    }

    if (response.success && response.data) {
      marketNews.value = response.data.news.map((item: any) => ({
        id: item.id || item.title,
        title: item.title,
        time: item.publish_time,
        url: item.url,
        source: item.source
      }))
    }
  } catch (error) {
    console.error('加载市场快讯失败:', error)
    // 如果加载失败，显示提示信息
    marketNews.value = []
  }
}

// 加载模拟交易账户信息
const loadPaperAccount = async () => {
  try {
    const response = await paperApi.getAccount()
    if (response.success && response.data) {
      paperAccount.value = response.data.account
    }
  } catch (error) {
    console.error('加载模拟交易账户失败:', error)
    paperAccount.value = null
  }
}

// 跳转到模拟交易页面
const goToPaperTrading = () => {
  router.push('/paper')
}

// 格式化金额
const formatMoney = (value: number) => {
  return value.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

// 生命周期
onMounted(async () => {
  // 加载自选股数据
  await loadFavoriteStocks()
  // 加载最近分析
  await loadRecentAnalyses()
  // 加载市场快讯
  await loadMarketNews()
  // 加载模拟交易账户
  await loadPaperAccount()
  // 加载数据新鲜度和覆盖率
  await loadFreshness()
})
</script>

<style lang="scss" scoped>
.dashboard {
  .welcome-section {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    padding: 40px;
    color: white;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;

    .welcome-content {
      .welcome-title {
        font-size: 32px;
        font-weight: 600;
        margin: 0 0 12px 0;
        display: flex;
        align-items: center;
        gap: 16px;

        .version-badge {
          background: rgba(255, 255, 255, 0.2);
          padding: 4px 12px;
          border-radius: 20px;
          font-size: 14px;
          font-weight: 400;
        }
      }

      .welcome-subtitle {
        font-size: 16px;
        opacity: 0.9;
        margin: 0;
      }
    }

    .welcome-actions {
      display: flex;
      gap: 16px;
    }
  }

  .learning-highlight-card {
    margin-bottom: 24px;
    border: 2px solid var(--el-color-primary);
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);

    .learning-highlight {
      display: flex;
      align-items: center;
      gap: 24px;
      padding: 8px;

      .learning-icon {
        flex-shrink: 0;
        width: 80px;
        height: 80px;
        border-radius: 12px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
      }

      .learning-content {
        flex: 1;

        h2 {
          font-size: 20px;
          font-weight: 600;
          margin: 0 0 12px 0;
          color: var(--el-text-color-primary);
        }

        p {
          font-size: 14px;
          color: var(--el-text-color-regular);
          line-height: 1.6;
          margin: 0 0 16px 0;
        }

        .learning-features {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;

          .feature-tag {
            padding: 4px 12px;
            background: var(--el-color-primary-light-9);
            color: var(--el-color-primary);
            border-radius: 16px;
            font-size: 13px;
            font-weight: 500;
          }
        }
      }

      .learning-action {
        flex-shrink: 0;
      }
    }
  }

  .quick-actions-card {
    .quick-actions {
      display: grid;
      gap: 16px;

      .action-item {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 20px;
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.3s ease;

        &:hover {
          border-color: var(--el-color-primary);
          background-color: var(--el-color-primary-light-9);
        }

        .action-icon {
          width: 40px;
          height: 40px;
          border-radius: 8px;
          background: var(--el-color-primary-light-8);
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--el-color-primary);
          font-size: 20px;
        }

        .action-content {
          flex: 1;

          h3 {
            margin: 0 0 4px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }

          p {
            margin: 0;
            font-size: 14px;
            color: var(--el-text-color-regular);
          }
        }

        .action-arrow {
          color: var(--el-text-color-placeholder);
          transition: transform 0.3s ease;
        }

        &:hover .action-arrow {
          transform: translateX(4px);
        }
      }
    }
  }

  .recent-analyses-card {
    .table-footer {
      text-align: center;
      margin-top: 16px;
    }
  }

  .system-status-card {
    .status-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;

      &:not(:last-child) {
        border-bottom: 1px solid var(--el-border-color-lighter);
      }

      .status-label {
        color: var(--el-text-color-regular);
      }

      .status-value {
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }
  }

  .market-news-card {
    .news-list {
      .news-item {
        padding: 12px 0;
        cursor: pointer;
        border-bottom: 1px solid var(--el-border-color-lighter);

        &:last-child {
          border-bottom: none;
        }

        &:hover {
          background-color: var(--el-fill-color-lighter);
          margin: 0 -16px;
          padding: 12px 16px;
          border-radius: 4px;
        }

        .news-title {
          font-size: 14px;
          color: var(--el-text-color-primary);
          margin-bottom: 4px;
          line-height: 1.4;
        }

        .news-time {
          font-size: 12px;
          color: var(--el-text-color-placeholder);
        }
      }
    }

    .news-footer {
      text-align: center;
      margin-top: 16px;
    }
  }

  .tips-card {
    .tip-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 0;
      font-size: 14px;
      color: var(--el-text-color-regular);

      .tip-icon {
        color: var(--el-color-primary);
      }
    }
  }

  .favorites-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .empty-favorites {
      text-align: center;
      padding: 20px 0;
    }

    .favorites-list {
      .favorite-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid var(--el-border-color-lighter);
        cursor: pointer;
        transition: background-color 0.3s ease;

        &:hover {
          background-color: var(--el-fill-color-lighter);
          margin: 0 -16px;
          padding: 12px 16px;
          border-radius: 6px;
        }

        &:last-child {
          border-bottom: none;
        }

        .stock-info {
          .stock-code {
            font-weight: 600;
            font-size: 14px;
            color: var(--el-text-color-primary);
          }

          .stock-name {
            font-size: 12px;
            color: var(--el-text-color-regular);
            margin-top: 2px;
          }
        }

        .stock-price {
          text-align: right;

          .current-price {
            font-weight: 600;
            font-size: 14px;
            color: var(--el-text-color-primary);
          }

          .change-percent {
            font-size: 12px;
            margin-top: 2px;

            &.price-up {
              color: #f56c6c;
            }

            &.price-down {
              color: #67c23a;
            }

            &.price-neutral {
              color: var(--el-text-color-regular);
            }
          }
        }
      }
    }

    .favorites-footer {
      text-align: center;
      padding-top: 12px;
      border-top: 1px solid var(--el-border-color-lighter);
      margin-top: 12px;
    }
  }

  .paper-trading-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .paper-account-info {
      display: flex;
      flex-direction: column;
      gap: 16px;

      .account-section {
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 8px;
        padding: 12px;
        background-color: var(--el-fill-color-blank);

        .account-section-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin-bottom: 12px;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--el-border-color-lighter);
        }
      }

      .account-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;

        .account-label {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }

        .account-value {
          font-size: 15px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          &.primary {
            color: var(--el-color-primary);
            font-size: 16px;
          }

          &.price-up {
            color: #f56c6c;
          }

          &.price-down {
            color: #67c23a;
          }

          &.price-neutral {
            color: var(--el-text-color-regular);
          }
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 20px 0;

      .empty-icon {
        font-size: 48px;
        color: var(--el-text-color-placeholder);
        margin-bottom: 12px;
      }

      p {
        color: var(--el-text-color-secondary);
        margin-bottom: 16px;
      }
    }
  }

  .freshness-card,
  .coverage-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }

  .freshness-card {
    .freshness-body {
      min-height: 80px;
    }

    .freshness-loading {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--el-text-color-secondary);

      .loading-icon {
        animation: spin 1s linear infinite;
        color: var(--el-color-primary);
      }
    }

    .freshness-info {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .freshness-status {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;

      .freshness-badge {
        padding: 4px 12px;
        border-radius: 16px;
        font-size: 13px;
        font-weight: 600;

        &.fresh {
          background: var(--el-color-success-light-9);
          color: var(--el-color-success);
        }

        &.stale {
          background: var(--el-color-warning-light-9);
          color: var(--el-color-warning);
        }
      }

      .freshness-label {
        color: var(--el-text-color-regular);
        font-size: 14px;
      }
    }

    .freshness-meta {
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }
  }

  .coverage-card {
    .coverage-body {
      min-height: 80px;
    }

    .coverage-meta {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 13px;
      color: var(--el-text-color-regular);
    }

    .coverage-gap {
      color: var(--el-color-warning);
      font-weight: 600;
    }

    .coverage-empty {
      padding: 16px 0;
    }
  }

  .confirm-body {
    .confirm-tip {
      display: flex;
      flex-direction: column;
      gap: 8px;
      color: var(--el-text-color-regular);
      font-size: 13px;
      line-height: 1.6;
    }
  }

  .progress-body {
    .progress-title {
      font-weight: 600;
      margin-bottom: 16px;
      color: var(--el-text-color-primary);
      display: flex;
      align-items: center;
      font-size: 14px;

      .el-icon {
        animation: spin 1s linear infinite;
      }
    }

    .progress-meta {
      margin-top: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--el-text-color-regular);
    }

    .phase-hint {
      color: var(--el-color-warning);
      font-size: 12px;
      line-height: 1.5;
      padding: 8px 12px;
      background: var(--el-color-warning-light-9);
      border-radius: 4px;
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

// 响应式设计
@media (max-width: 768px) {
  .dashboard {
    .welcome-section {
      flex-direction: column;
      text-align: center;
      gap: 24px;

      .welcome-actions {
        justify-content: center;
      }
    }

    .learning-highlight-card {
      .learning-highlight {
        flex-direction: column;
        text-align: center;

        .learning-content {
          .learning-features {
            justify-content: center;
          }
        }
      }
    }

    .main-content {
      .el-col {
        margin-bottom: 24px;
      }
    }
  }
}
</style>
