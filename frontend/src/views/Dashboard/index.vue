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
              <el-button v-if="!freshness.overall_is_fresh" type="warning" size="small" @click="openSyncConfirm">
                <el-icon><Refresh /></el-icon> 一键更新
              </el-button>
            </div>
          </template>
          <div class="freshness-body">
            <div v-if="freshnessLoading" class="freshness-loading">
              <el-icon class="loading-icon"><Loading /></el-icon> 加载中...
            </div>
            <div v-else class="freshness-info">
              <div class="freshness-overall">
                <div :class="['freshness-badge', freshness.overall_is_fresh ? 'fresh' : 'stale']">
                  {{ freshness.overall_is_fresh ? '✅ 全部最新' : '⚠️ 有数据需要更新' }}
                </div>
                <div class="freshness-message">{{ freshness.message || '' }}</div>
              </div>
              <div class="freshness-items">
                <div v-for="item in freshnessItems" :key="item.key" class="freshness-item">
                  <div class="freshness-item-header">
                    <span class="freshness-item-label">{{ item.label }}</span>
                    <el-tag :type="item.is_fresh ? 'success' : 'warning'" size="small" effect="plain">
                      {{ item.is_fresh ? '最新' : `过期${item.stale_days > 0 ? item.stale_days + '天' : ''}` }}
                    </el-tag>
                  </div>
                  <div class="freshness-item-meta">
                    <span>最新：{{ item.latest }}</span>
                    <span class="freshness-item-count">{{ item.count }} 条</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 多数据源同步 -->
        <MultiSourceSyncCard style="margin-top: 24px;" />
      </el-col>
    </el-row>
    <!-- 全量同步对话框 -->
    <el-dialog
      v-model="syncConfirmVisible"
      title="一键更新所有数据"
      width="520px"
      :close-on-click-modal="false"
    >
      <div v-if="!syncRunning" class="confirm-body">
        <el-alert
          title="系统将按顺序同步所有过期数据，预计耗时 10~30 分钟"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="confirm-tip" style="margin-top: 16px;">
          <div>📋 同步顺序：股票基础信息 → 历史K线 → 财务数据 → 新闻数据</div>
          <div>⏱️ 预估耗时：10 ~ 30 分钟</div>
          <div>🔄 同步完成后会自动刷新数据新鲜度</div>
          <div>⚠️ 历史K线同步耗时较长，请耐心等待</div>
        </div>
      </div>
      <div v-else class="progress-body">
        <div class="progress-title">
          <el-icon style="color: var(--el-color-primary); margin-right:8px;"><Loading /></el-icon>
          {{ syncPhaseLabel }}
        </div>
        <el-progress
          :percentage="syncProgress"
          :status="syncError ? 'exception' : undefined"
          :stroke-width="16"
          :text-inside="false"
        />
        <div class="sync-phases">
          <div v-for="(p, i) in syncPhases" :key="i" :class="['sync-phase-item', syncPhase === p.id ? 'active' : '', syncPhase > p.id ? 'done' : '', skippedPhases.has(p.id) ? 'skipped' : '']">
            <span class="sync-phase-icon">
              <span v-if="skippedPhases.has(p.id)">⏭️</span>
              <span v-else-if="syncPhase > p.id">✅</span>
              <span v-else-if="syncPhase === p.id">⏳</span>
              <span v-else>⬜</span>
            </span>
            <span class="sync-phase-name">{{ p.label }}</span>
          </div>
        </div>
        <div class="progress-meta">
          <div>状态：<b>{{ syncStatusMessage }}</b></div>
          <div v-if="syncPhase === 1 && syncTotal > 0">
            基础信息：{{ syncDone }} / {{ syncTotal }}（新增 {{ syncInserted }}，更新 {{ syncUpdated }}）
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
  Refresh
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
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

// ---------- 数据新鲜度 ----------
const freshnessLoading = ref(true)
const freshness = reactive({
  overall_is_fresh: false,
  overall_stale_days: 0,
  expected_date: '' as string,
  message: '' as string,
  items: [] as any[],
  // 兼容旧字段
  latest_data_date: '' as string,
  is_fresh: false,
  stale_days: 0,
  total_stocks: 0,
  expected_total: 0,
})

const freshnessItems = computed(() => freshness.items || [])

// ---------- 全量同步对话框 ----------
const syncConfirmVisible = ref(false)
const syncStarting = ref(false)
const syncRunning = ref(false)
const syncFinished = ref(false)
const syncError = ref(false)
const syncProgress = ref(0)
const syncStatusMessage = ref('准备同步')
const syncTotal = ref(0)
const syncDone = ref(0)
const syncInserted = ref(0)
const syncUpdated = ref(0)
const syncErrors = ref(0)

// 同步阶段：1=基础信息 2=历史K线 3=财务数据 4=新闻数据
const syncPhase = ref(0)
// 记录哪些阶段需要跳过（数据已最新）
const skippedPhases = ref<Set<number>>(new Set())
const syncPhases = [
  { id: 1, label: '股票基础信息', job: 'basics_sync_service', freshnessKey: 'basics', range: [0, 15] },
  { id: 2, label: '历史K线数据', job: 'tushare_historical_sync', freshnessKey: 'quotes', range: [15, 70] },
  { id: 3, label: '财务数据', job: 'tushare_financial_sync', freshnessKey: 'financial', range: [70, 90] },
  { id: 4, label: '新闻数据', job: 'news_sync', freshnessKey: 'news', range: [90, 100] },
]
const syncPhaseLabel = computed(() => {
  const p = syncPhases.find(p => p.id === syncPhase.value)
  return p ? `正在同步：${p.label}...` : '正在同步数据...'
})

// 检查某个数据类型是否已最新（根据 freshness.items）
const isPhaseFresh = (phaseId: number): boolean => {
  const phase = syncPhases.find(p => p.id === phaseId)
  if (!phase) return false
  const item = freshness.items?.find((i: any) => i.key === phase.freshnessKey)
  return item?.is_fresh === true
}

const openSyncConfirm = () => {
  syncRunning.value = false
  syncFinished.value = false
  syncError.value = false
  syncProgress.value = 0
  syncPhase.value = 0
  skippedPhases.value = new Set()
  syncStatusMessage.value = '准备同步'
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

// 检查调度任务是否正在运行
const checkJobRunning = async (jobId: string): Promise<boolean> => {
  try {
    const res = await schedulerApi.getJobExecutions({ job_id: jobId, status: 'running', limit: 1 })
    const items = (res as any)?.data?.data?.items || (res as any)?.data?.items || []
    return items.length > 0
  } catch {
    return false
  }
}

// 检查调度任务最近一次是否已完成（在给定时间之后）
const checkJobCompleted = async (jobId: string, sinceTs: number): Promise<{ done: boolean; failed: boolean }> => {
  try {
    const res = await schedulerApi.getJobExecutions({ job_id: jobId, status: 'completed', limit: 1 })
    const items = (res as any)?.data?.data?.items || (res as any)?.data?.items || []
    if (items.length > 0) {
      const endTime = items[0].end_time || items[0].created_at
      if (endTime) {
        const ts = new Date(endTime).getTime()
        if (ts >= sinceTs) return { done: true, failed: false }
      }
    }
    const res2 = await schedulerApi.getJobExecutions({ job_id: jobId, status: 'failed', limit: 1 })
    const items2 = (res2 as any)?.data?.data?.items || (res2 as any)?.data?.items || []
    if (items2.length > 0) {
      const endTime = items2[0].end_time || items2[0].created_at
      if (endTime) {
        const ts = new Date(endTime).getTime()
        if (ts >= sinceTs) return { done: true, failed: true }
      }
    }
    return { done: false, failed: false }
  } catch {
    return { done: false, failed: false }
  }
}

// 跳转到下一个需要同步的阶段，跳过已最新的阶段
const advanceToNextPhase = async (syncStartTime: number) => {
  // 先重新加载新鲜度，获取最新状态
  await loadFreshness()

  for (let nextPhase = syncPhase.value + 1; nextPhase <= 4; nextPhase++) {
    if (isPhaseFresh(nextPhase)) {
      // 该数据类型已最新，跳过
      skippedPhases.value.add(nextPhase)
      const phase = syncPhases.find(p => p.id === nextPhase)
      const nextRange = syncPhases.find(p => p.id === nextPhase + 1)?.range?.[0] ?? 100
      syncProgress.value = nextRange
      continue
    }
    // 找到需要同步的阶段
    syncPhase.value = nextPhase
    const phase = syncPhases.find(p => p.id === nextPhase)
    if (!phase) break
    syncProgress.value = phase.range[0]
    syncStatusMessage.value = `开始同步${phase.label}...`

    if (nextPhase === 1) {
      // 阶段1：触发基础信息同步
      try {
        await syncApi.runStockBasicsSync({ force: true })
      } catch (_) {}
    } else {
      // 阶段2-4：触发调度任务
      try {
        await schedulerApi.triggerJob(phase.job, true)
      } catch (_) {}
    }
    return true
  }

  // 所有阶段都已完成或跳过
  return false
}

const doSync = async () => {
  syncStarting.value = true
  skippedPhases.value = new Set()
  try {
    // 先加载最新新鲜度，确定哪些阶段需要跳过
    await loadFreshness()

    // 从阶段1开始，如果阶段1已最新则跳到下一个
    syncRunning.value = true
    syncTotal.value = 0
    syncDone.value = 0
    syncInserted.value = 0
    syncUpdated.value = 0
    syncErrors.value = 0

    // 找到第一个需要同步的阶段
    let firstPhase = 0
    for (let i = 1; i <= 4; i++) {
      if (!isPhaseFresh(i)) {
        firstPhase = i
        break
      } else {
        skippedPhases.value.add(i)
      }
    }

    if (firstPhase === 0) {
      // 所有数据都最新
      syncProgress.value = 100
      syncStatusMessage.value = '所有数据均为最新，无需同步 ✅'
      syncFinished.value = true
      ElMessage.success('所有数据均为最新')
      syncStarting.value = false
      closeSyncTimer.value = setTimeout(() => {
        syncConfirmVisible.value = false
      }, 2000)
      return
    }

    // 触发第一个阶段
    syncPhase.value = firstPhase
    const firstPhaseInfo = syncPhases.find(p => p.id === firstPhase)!
    syncProgress.value = firstPhaseInfo.range[0]
    syncStatusMessage.value = `开始同步${firstPhaseInfo.label}...`

    if (firstPhase === 1) {
      await syncApi.runStockBasicsSync({ force: true })
    } else {
      try { await schedulerApi.triggerJob(firstPhaseInfo.job, true) } catch (_) {}
    }

    const syncStartTime = Date.now()
    let pollCount = 0
    const MAX_POLL = 720
    stopSyncPoll()
    closeSyncPoll.value = setInterval(async () => {
      pollCount++
      if (pollCount >= MAX_POLL) {
        stopSyncPoll()
        syncStatusMessage.value = '同步超时，任务可能仍在后台执行，请在任务中心查看'
        syncProgress.value = 95
        syncFinished.value = true
        await loadFreshness()
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
            syncStatusMessage.value = '同步股票基础信息中...'
            if (syncTotal.value > 0) {
              syncProgress.value = Math.min(15, Math.round((syncDone.value / syncTotal.value) * 15))
            } else {
              syncProgress.value = Math.min(15, syncProgress.value + 0.5)
            }
          } else if (status.status === 'success' || status.status === 'success_with_errors' || status.status === 'failed') {
            // 阶段1完成（无论成功失败），尝试跳到下一个需要同步的阶段
            const advanced = await advanceToNextPhase(syncStartTime)
            if (!advanced) {
              stopSyncPoll()
              syncProgress.value = 100
              syncStatusMessage.value = '数据同步完成 ✅'
              syncFinished.value = true
              ElMessage.success('数据同步完成')
              await loadFreshness()
              closeSyncTimer.value = setTimeout(() => {
                syncConfirmVisible.value = false
              }, 2500)
            }
          }
          return
        }

        // 阶段2-4：轮询调度任务状态
        if (syncPhase.value >= 2 && syncPhase.value <= 4) {
          const phase = syncPhases.find(p => p.id === syncPhase.value)!
          const running = await checkJobRunning(phase.job)
          if (running) {
            syncStatusMessage.value = `同步${phase.label}中...`
            syncProgress.value = Math.min(phase.range[1], syncProgress.value + 0.3)
          } else {
            const result = await checkJobCompleted(phase.job, syncStartTime)
            if (result.done) {
              // 当前阶段完成，尝试跳到下一个
              const advanced = await advanceToNextPhase(syncStartTime)
              if (!advanced) {
                stopSyncPoll()
                syncProgress.value = 100
                syncStatusMessage.value = '全部数据同步完成 ✅'
                syncFinished.value = true
                ElMessage.success('全部数据同步完成')
                await loadFreshness()
                closeSyncTimer.value = setTimeout(() => {
                  syncConfirmVisible.value = false
                }, 2500)
              }
            } else {
              syncProgress.value = Math.min(phase.range[1], syncProgress.value + 0.2)
              syncStatusMessage.value = `等待${phase.label}同步任务调度...`
            }
          }
          return
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

  .freshness-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

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

    .freshness-overall {
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

      .freshness-message {
        color: var(--el-text-color-secondary);
        font-size: 13px;
      }
    }

    .freshness-items {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .freshness-item {
      padding: 8px 12px;
      background: var(--el-fill-color-light);
      border-radius: 6px;

      .freshness-item-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;

        .freshness-item-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }
      }

      .freshness-item-meta {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: var(--el-text-color-secondary);

        .freshness-item-count {
          color: var(--el-text-color-regular);
        }
      }
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

    .sync-phases {
      display: flex;
      gap: 8px;
      margin: 16px 0;
      flex-wrap: wrap;

      .sync-phase-item {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 12px;
        background: var(--el-fill-color-light);
        color: var(--el-text-color-secondary);

        &.active {
          background: var(--el-color-primary-light-9);
          color: var(--el-color-primary);
          font-weight: 600;
        }

        &.done {
          color: var(--el-color-success);
        }

        &.skipped {
          color: var(--el-text-color-placeholder);
          opacity: 0.7;
        }

        .sync-phase-icon {
          font-size: 14px;
        }
      }
    }

    .progress-meta {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--el-text-color-regular);
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
