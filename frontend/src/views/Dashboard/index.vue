<template>
  <div class="dashboard app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Odometer /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">速览</h2>
          <p class="page-hero-sub">数据健康 · 模拟账户 · 自选行情 · 监控动态</p>
        </div>
      </div>
    </div>

    <!-- 监控中心（简要触发记录，查看详情跳转监控中心） -->
    <MonitorSummary style="margin-bottom: 24px;" />

    <!-- 顶部核心监控：数据健康 + 模拟账户 + 自选股行情 -->
    <el-row :gutter="24" class="monitor-top">
      <el-col :xs="24" :md="8">
        <DataHealthCard @open-sync="openSyncConfirm" />
      </el-col>

      <el-col :xs="24" :md="8">
        <!-- 模拟交易账户（精简） -->
        <el-card class="paper-trading-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>模拟交易账户</span>
              <el-button type="text" size="small" @click="goToPaperTrading">
                查看详情 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <div v-if="paperAccount" class="paper-account-info">
            <div v-for="cur in activeCurrencies" :key="cur.code" class="account-section">
              <div class="account-section-title">{{ cur.flag }} {{ cur.label }}账户</div>
              <div class="account-item">
                <div class="account-label">总资产</div>
                <div class="account-value primary">{{ cur.prefix }}{{ formatMoney(cur.equity) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">现金</div>
                <div class="account-value">{{ cur.prefix }}{{ formatMoney(cur.cash) }}</div>
              </div>
              <div class="account-item">
                <div class="account-label">持仓市值</div>
                <div class="account-value">{{ cur.prefix }}{{ formatMoney(cur.positions_value) }}</div>
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
      </el-col>

      <el-col :xs="24" :md="8">
        <!-- 我的自选股（精简，SSE 实时刷新） -->
        <el-card class="favorites-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>我的自选股</span>
              <el-button type="text" size="small" @click="goToFavorites">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <!-- P5-12：SSE 断连降级提示（仍在定时刷新，但非实时） -->
          <el-alert
            v-if="quotesStale"
            type="warning"
            :closable="false"
            show-icon
            class="quotes-stale-alert"
            title="行情实时中断，已切换定时刷新"
            description="连接恢复后将自动切回实时更新"
          />

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
                <router-link :to="`/stocks/${stock.stock_code}`" class="stock-code" @click.stop>{{ stock.stock_code }}</router-link>
                <router-link :to="`/stocks/${stock.stock_code}`" class="stock-name" @click.stop>{{ stock.stock_name }}</router-link>
              </div>
              <div class="stock-price">
                <div class="current-price">¥{{ stock.current_price }}</div>
                <div
                  class="change-percent"
                  :class="getPriceChangeClass(stock.change_percent)"
                >
                  {{ stock.change_percent == null ? '——' : fmtPct(stock.change_percent) }}
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
          <div class="tip-line"><el-icon><List /></el-icon><span>同步顺序：股票基础信息 → 历史K线 → 财务数据 → 新闻数据</span></div>
          <div class="tip-line"><el-icon><Timer /></el-icon><span>预估耗时：10 ~ 30 分钟</span></div>
          <div class="tip-line"><el-icon><Refresh /></el-icon><span>同步完成后会自动刷新数据新鲜度</span></div>
          <div class="tip-line"><el-icon><Warning /></el-icon><span>历史K线同步耗时较长，请耐心等待</span></div>
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
              <el-icon v-if="skippedPhases.has(p.id)"><DArrowRight /></el-icon>
              <el-icon v-else-if="syncPhase > p.id" class="phase-done"><CircleCheckFilled /></el-icon>
              <el-icon v-else-if="syncPhase === p.id" class="phase-running"><Loading /></el-icon>
              <el-icon v-else><Remove /></el-icon>
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
import {
  ArrowRight,
  CircleCheckFilled,
  DArrowRight,
  InfoFilled,
  List,
  Loading,
  Odometer,
  Refresh,
  Remove,
  Timer,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DataHealthCard from '@/components/Dashboard/DataHealthCard.vue'
import MonitorSummary from '@/components/Dashboard/MonitorSummary.vue'
import { favoritesApi } from '@/api/favorites'
import { paperApi, type PaperAccountSummary } from '@/api/paper'
import * as syncApi from '@/api/sync'
import * as schedulerApi from '@/api/scheduler'
import { screeningApi } from '@/api/screening'
import { subscribeQuotesUpdate } from '@/utils/quotesSSE'
import { fmtPct, fmtMoney } from '@/utils/format'
import { toTimestamp } from '@/utils/datetime'

const router = useRouter()

// 自选股数据
const favoriteStocks = ref<any[]>([])

// P5-12：SSE 实时行情信号是否进入降级态（断连后依赖定时刷新兜底）
const quotesStale = ref(false)

// 模拟交易账户数据
const paperAccount = ref<PaperAccountSummary | null>(null)

// ---------- 数据新鲜度（供全量同步对话框判断跳过阶段） ----------
const freshness = reactive({
  overall_is_fresh: false,
  overall_stale_days: 0,
  expected_date: '' as string,
  message: '' as string,
  items: [] as any[],
  latest_data_date: '' as string,
  is_fresh: false,
  stale_days: 0,
  total_stocks: 0,
  expected_total: 0,
})

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
// 触发失败标记（供轮询检测）
const triggerFailed = ref(false)
// 阶段1触发后等待同步启动的轮询计数（用于检测触发失败）
const phase1WaitCount = ref(0)
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
  triggerFailed.value = false
  phase1WaitCount.value = 0
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
// 后端执行记录的 status 为 'success'/'failed'/'running'/'missed'（非 'completed'）
// 时间字段为 updated_at（完成时间）或 timestamp（创建时间），无 end_time/created_at
const checkJobCompleted = async (jobId: string, sinceTs: number): Promise<{ done: boolean; failed: boolean }> => {
  try {
    // 查询最近的执行记录（不限状态），客户端筛选已完成且时间匹配的记录
    const res = await schedulerApi.getJobExecutions({ job_id: jobId, limit: 5 })
    const items = (res as any)?.data?.data?.items || (res as any)?.data?.items || []
    // 5秒容差，避免客户端与服务端时钟差异导致漏判
    const threshold = sinceTs - 5000
    for (const item of items) {
      if (item.status === 'success' || item.status === 'failed') {
        const timeStr = item.updated_at || item.timestamp
        if (timeStr) {
          const ts = toTimestamp(timeStr)
          if (ts !== null && ts >= threshold) {
            return { done: true, failed: item.status === 'failed' }
          }
        }
      }
    }
    return { done: false, failed: false }
  } catch {
    return { done: false, failed: false }
  }
}

// 跳转到下一个需要同步的阶段，跳过已最新的阶段
const advanceToNextPhase = async (syncStartTime: number) => {
  // 先重新加载新鲜度（静默模式，避免 UI 闪烁）
  await loadFreshness(true)

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
      // 阶段1：触发基础信息同步（非阻塞，立即开始轮询进度）
      // 后端 run_full_sync 会立即将状态持久化为 'running'，前端轮询 getSyncStatus 即可获取进度
      syncApi.runStockBasicsSync({ force: true }).catch(e => {
        console.warn('触发基础信息同步失败', e)
        triggerFailed.value = true
      })
    } else {
      // 阶段2-4：触发调度任务（triggerJob 是非阻塞的，立即返回）
      try {
        await schedulerApi.triggerJob(phase.job, true)
      } catch (e) {
        console.warn(`触发${phase.label}失败`, e)
        triggerFailed.value = true
      }
    }
    return true
  }

  // 所有阶段都已完成或跳过
  return false
}

const doSync = async () => {
  syncStarting.value = true
  skippedPhases.value = new Set()
  triggerFailed.value = false
  phase1WaitCount.value = 0
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
      syncStatusMessage.value = '所有数据均为最新，无需同步'
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

    // 记录同步开始时间（在触发之前，用于后续判断同步是否已启动）
    const syncStartTime = Date.now()

    if (firstPhase === 1) {
      // 阶段1：非阻塞触发，立即开始轮询进度（避免 HTTP 请求阻塞导致进度条卡住）
      syncApi.runStockBasicsSync({ force: true }).catch(e => {
        console.warn('触发基础信息同步失败', e)
        triggerFailed.value = true
      })
    } else {
      // 阶段2-4：triggerJob 是非阻塞的，立即返回
      try {
        await schedulerApi.triggerJob(firstPhaseInfo.job, true)
      } catch (e) {
        console.warn(`触发${firstPhaseInfo.label}失败`, e)
        triggerFailed.value = true
      }
    }

    let pollCount = 0
    const MAX_POLL = 720
    stopSyncPoll()
    closeSyncPoll.value = setInterval(async () => {
      pollCount++

      // 检测触发失败
      if (triggerFailed.value) {
        stopSyncPoll()
        syncError.value = true
        syncFinished.value = true
        const failLabel = syncPhases.find(p => p.id === syncPhase.value)?.label || ''
        syncStatusMessage.value = `触发${failLabel}同步失败，请检查权限或稍后重试`
        ElMessage.error(syncStatusMessage.value)
        return
      }

      if (pollCount >= MAX_POLL) {
        stopSyncPoll()
        syncStatusMessage.value = '同步超时，任务可能仍在后台执行，请在任务中心查看'
        syncProgress.value = 95
        syncFinished.value = true
        await loadFreshness(true)
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

          // 判断新同步是否已启动（started_at 在 syncStartTime 之后，含10秒容差）
          const startedAtTs = status.started_at ? (toTimestamp(status.started_at) ?? 0) : 0
          const syncStarted = startedAtTs >= syncStartTime - 10000

          if (status.status === 'running') {
            phase1WaitCount.value = 0
            syncStatusMessage.value = '同步股票基础信息中...'
            if (syncTotal.value > 0) {
              syncProgress.value = Math.min(15, Math.round((syncDone.value / syncTotal.value) * 15))
            } else {
              syncProgress.value = Math.min(15, syncProgress.value + 0.5)
            }
          } else if ((status.status === 'success' || status.status === 'success_with_errors' || status.status === 'failed') && syncStarted) {
            // 新同步已完成（通过 started_at 确认是新的一次同步，而非旧状态）
            phase1WaitCount.value = 0
            const advanced = await advanceToNextPhase(syncStartTime)
            if (!advanced) {
              stopSyncPoll()
              syncProgress.value = 100
              syncStatusMessage.value = '数据同步完成'
              syncFinished.value = true
              ElMessage.success('数据同步完成')
              await loadFreshness(true)
              closeSyncTimer.value = setTimeout(() => {
                syncConfirmVisible.value = false
              }, 2500)
            }
          } else {
            // 同步尚未启动（可能是旧的 success 状态或 idle），等待后端启动
            phase1WaitCount.value++
            syncProgress.value = Math.min(15, syncProgress.value + 0.3)
            syncStatusMessage.value = '正在启动基础信息同步...'
            // 连续6次（30秒）仍未启动，判定触发失败
            if (phase1WaitCount.value > 6) {
              stopSyncPoll()
              syncError.value = true
              syncFinished.value = true
              syncStatusMessage.value = '基础信息同步启动超时，请稍后重试'
              ElMessage.error('基础信息同步启动超时')
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
                syncStatusMessage.value = '全部数据同步完成'
                syncFinished.value = true
                ElMessage.success('全部数据同步完成')
                await loadFreshness(true)
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

const loadFreshness = async (silent = false) => {
  try {
    const res = await screeningApi.checkDataFreshness()
    const data = (res as any)?.data?.data || (res as any)?.data || {}
    Object.assign(freshness, data)
  } catch (e) {
    console.warn('加载数据新鲜度失败', e)
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

// 活跃账户币种（含总资产/现金/市值，供精简卡片渲染）
const activeCurrencies = computed(() => {
  if (!paperAccount.value) return []
  const acc = paperAccount.value
  const isObj = (v: any) => v && typeof v === 'object' && !Array.isArray(v)
  const codes = isObj(acc.cash) ? Object.keys(acc.cash) : ['CNY']
  const meta: Record<string, { label: string; flag: string; prefix: string }> = {
    CNY: { label: 'A股', flag: '🇨🇳', prefix: '¥' },
    HKD: { label: '港股', flag: '🇭🇰', prefix: 'HK$' },
    USD: { label: '美股', flag: '🇺🇸', prefix: '$' },
  }
  return codes.map(code => {
    const m = meta[code] || { label: code, flag: '', prefix: '' }
    return {
      code,
      label: m.label,
      flag: m.flag,
      prefix: m.prefix,
      cash: getCurrencyAmount(acc.cash, code as any),
      positions_value: getCurrencyAmount(acc.positions_value, code as any),
      equity: getCurrencyAmount(acc.equity, code as any),
    }
  })
})

onBeforeUnmount(() => {
  stopSyncPoll()
  stopSyncTimer()
  favSseUnsubscribe?.()
})

// 跳转
const goToFavorites = () => {
  router.push('/favorites')
}

const goToPaperTrading = () => {
  router.push('/paper')
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

// 格式化金额（千分位，由调用方携带货币符号）
const formatMoney = (value: number) => fmtMoney(value, '')

const loadFavoriteStocks = async () => {
  try {
    const response = await favoritesApi.list()
    if (response.success && response.data) {
      favoriteStocks.value = response.data.map((item: any) => ({
        stock_code: item.stock_code || item.symbol,
        stock_name: item.stock_name,
        current_price: item.current_price || 0,
        change_percent: item.change_percent == null ? null : item.change_percent
      }))
    }
  } catch (error) {
    console.error('加载自选股失败:', error)
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

// 自选股实时刷新（SSE 行情信号触发）
let favSseUnsubscribe: (() => void) | null = null

// 生命周期
onMounted(async () => {
  await loadFavoriteStocks()
  await loadPaperAccount()
  // 收到行情更新信号立即刷新自选股（延迟约 0-2 秒）。
  // P3-6：信号若带值则原地 patch 对应股票，避免全量重拉与陈旧读取；未带值才兜底全量刷新。
  favSseUnsubscribe = subscribeQuotesUpdate((signal) => {
    const patch = signal?.quotes
    if (patch && Object.keys(patch).length) {
      let changed = false
      favoriteStocks.value.forEach((s: any) => {
        const q = patch[s.stock_code]
        if (q) {
          s.current_price = q.close
          s.change_percent = q.pct_chg == null ? null : q.pct_chg
          changed = true
        }
      })
      if (changed) {
        favoriteStocks.value = [...favoriteStocks.value]
        return
      }
    }
    loadFavoriteStocks()
  }, (status) => {
    // P5-12：SSE 降级/恢复时同步 UI 提示
    quotesStale.value = status === 'degraded'
  })
})
</script>

<style lang="scss" scoped>
.dashboard {
  // 页面容器交给全局 .app-page；顶部横幅由全局 .page-hero 提供

  // 顶部卡片统一样式
  .monitor-top {
    .el-col {
      margin-bottom: 24px;
    }
    .el-card {
      border-radius: 14px;
      border: 1px solid var(--el-border-color-light);
      box-shadow: var(--el-box-shadow-light);
      transition: transform .2s, box-shadow .2s;
      &:hover {
        box-shadow: var(--el-box-shadow-medium);
      }
      .el-card__header {
        border-bottom: 1px solid var(--el-border-color-lighter);
        padding: 14px 18px;
      }
      .el-card__body {
        padding: 16px 18px;
      }
    }
  }

  // 自选股
  .favorites-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .empty-favorites {
      text-align: center;
      padding: 20px 0;
    }

    .quotes-stale-alert {
      margin-bottom: 12px;
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

            &.price-up { color: #f56c6c; }
            &.price-down { color: #67c23a; }
            &.price-neutral { color: var(--el-text-color-regular); }
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

  // 模拟交易账户
  .paper-trading-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .paper-account-info {
      display: flex;
      flex-direction: column;
      gap: 12px;

      .account-section {
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 8px;
        padding: 10px 12px;
        background-color: var(--el-fill-color-blank);

        .account-section-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin-bottom: 8px;
          padding-bottom: 6px;
          border-bottom: 1px solid var(--el-border-color-lighter);
        }
      }

      .account-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 6px 0;

        .account-label {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }

        .account-value {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          &.primary {
            color: var(--el-color-primary);
            font-size: 15px;
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

  .confirm-body {
    .confirm-tip {
      display: flex;
      flex-direction: column;
      gap: 8px;
      color: var(--el-text-color-regular);
      font-size: 13px;
      line-height: 1.6;

      .tip-line {
        display: flex;
        align-items: center;
        gap: 6px;

        .el-icon {
          color: var(--el-color-primary);
          flex-shrink: 0;
        }
      }
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
          display: inline-flex;
          align-items: center;

          .phase-done {
            color: var(--el-color-success);
          }

          .phase-running {
            animation: spin 1s linear infinite;
            color: var(--el-color-primary);
          }
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
</style>