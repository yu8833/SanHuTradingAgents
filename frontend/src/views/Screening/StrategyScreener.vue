<template>
  <div class="strategy-screener app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">常用策略</h2>
          <p class="page-hero-sub">
            基于本地行情数据 · 策略筛选与评分排序
            <template v-if="isRealtimeResult">
              ·
              <el-icon :size="13"><Connection /></el-icon>
              {{ decisionWindow ? '收盘定格（可成交窗口）' : '盘中预警（暂定，15:00 定格确认）' }}
            </template>
            <template v-else-if="computedAt"> · <el-icon :size="13"><Clock /></el-icon> 数据更新于 {{ computedAt }}</template>
          </p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-select v-model="asOf" placeholder="选择交易日" size="default" class="date-select" filterable @change="onAsOfChange" :disabled="realtimeScan">
          <el-option v-for="d in tradeDates" :key="d" :label="d" :value="d" />
        </el-select>
        <div class="realtime-switch" :title="realtimeNote">
          <span class="rt-label">盘中预警</span>
          <el-switch :model-value="realtimeScan" size="default" @change="toggleRealtime" />
        </div>
        <el-button type="primary" size="default" :loading="runningAll" @click="runAll(true)">
          <el-icon><Refresh /></el-icon>
          运行全部
        </el-button>
      </div>
    </div>

    <!-- 收盘定格窗口：15:00-15:30 数据已定格、可按收盘价成交的决策黄金期 -->
    <div v-if="decisionWindow" class="close-window-banner">
      <div class="cw-orbit">
        <span class="cw-pulse"></span>
        <el-icon :size="16"><Clock /></el-icon>
      </div>
      <div class="cw-body">
        <span class="cw-title">收盘定格窗口 · 15:00–15:30</span>
        <span class="cw-sub">行情数据已定格，今日可按收盘价成交，无需等次日开盘。当前结果为收盘级判断，可据此直接决策。</span>
      </div>
      <div class="cw-side">
        <span class="cw-chip">可执行</span>
      </div>
    </div>

    <!-- 盘中预警条：开启盘中预警时，标识结果仍为暂定信号 -->
    <div v-else-if="isRealtimeResult" class="preview-banner">
      <el-icon :size="15"><Warning /></el-icon>
      <span>盘中预警 · 当前为暂定信号（盘中数据未完全定格），15:00 收盘定格后再做最终判断。</span>
    </div>

    <!-- 大盘行情上下文：直接告诉用户该用哪些策略 -->
    <div class="market-bar" :class="'trend-' + marketTrend">
      <div class="market-left">
        <div class="verdict-chip" :class="'trend-' + marketTrend">
          <span class="verdict-icon">
            <el-icon v-if="marketTrend === 'bull'"><TrendCharts /></el-icon>
            <el-icon v-else-if="marketTrend === 'bear'"><Bottom /></el-icon>
            <el-icon v-else-if="marketTrend === 'sideways'"><Minus /></el-icon>
            <el-icon v-else><QuestionFilled /></el-icon>
          </span>
          <span class="verdict-label">{{ trendText.label }}</span>
          <span v-if="!marketLoading && marketCtx" class="verdict-vol">· {{ volText.label }}</span>
        </div>
        <div v-if="!marketLoading && marketCtx" class="verdict-advice">
          <span class="advice-icon"><el-icon><Opportunity /></el-icon></span>
          <span class="advice-text">{{ adviceText }}</span>
        </div>
      </div>
      <div class="market-right">
        <el-switch
          v-model="showRecommendedOnly"
          active-text="只看推荐"
          inactive-text="全部"
          inline-prompt
          :disabled="marketLoading"
        />
      </div>
    </div>

    <!-- 策略卡片 -->
    <el-card class="strategy-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot" />
            策略池
            <span class="panel-count">{{ strategies.length }}</span>
          </div>
          <el-tag size="small" type="info" effect="plain" round>点击卡片查看选股结果</el-tag>
        </div>
      </template>
      <el-empty v-if="!loading && strategies.length === 0" description="暂无可用策略" :image-size="120" />
      <div v-else class="strategy-grid">
        <div
          v-for="(s, i) in filteredStrategies"
          :key="s.id"
          class="strategy-card"
          :class="{
            active: activeStrategy === s.id,
            loading: runningAll,
            'card-recommended': !marketLoading && marketCtx && fit(s).level === 1,
            'card-caution': !marketLoading && marketCtx && fit(s).level === -1,
          }"
          :style="{ '--sc': palette[i % palette.length] }"
          @click="handleRun(s)"
        >
          <div class="strategy-top">
            <div class="strategy-name">
              <span class="strategy-icon">
                <el-icon><component :is="cardIcon(i)" /></el-icon>
              </span>
              <span class="strategy-title">{{ s.name }}</span>
            </div>
            <div class="strategy-count">
              <template v-if="hitCounts[s.id] !== undefined">
                <span class="count-num">{{ hitCounts[s.id] }}</span>
                <span class="count-unit">只</span>
              </template>
              <el-icon v-else class="spinner"><Loading /></el-icon>
            </div>
          </div>
          <div class="strategy-desc">{{ s.description }}</div>
          <div class="strategy-rules" v-if="(s.buy_rules && s.buy_rules.length) || (s.sell_rules && s.sell_rules.length)">
            <div v-if="s.buy_rules && s.buy_rules.length" class="rule-row">
              <span class="rule-flag buy">买入</span>
              <span class="rule-text">{{ s.buy_rules.join(' · ') }}</span>
            </div>
            <div v-if="s.sell_rules && s.sell_rules.length" class="rule-row">
              <span class="rule-flag sell">卖出</span>
              <span class="rule-text">{{ s.sell_rules.join(' · ') }}</span>
            </div>
          </div>
          <div class="strategy-tags">
            <el-tag v-for="t in s.tags" :key="t" size="small" effect="plain" class="strategy-tag">{{ t }}</el-tag>
          </div>
          <!-- 行情适配：视觉化推荐标记 -->
          <div v-if="!marketLoading && marketCtx" class="strategy-fit-mark" :class="'lv-' + fit(s).level">
            <template v-if="fit(s).level === 1">
              <span class="mark-pill recommended">
                <el-icon :size="12"><Promotion /></el-icon>
                今日推荐
              </span>
            </template>
            <template v-else-if="fit(s).level === -1">
              <span class="mark-pill caution">
                <el-icon :size="12"><Warning /></el-icon>
                谨慎使用
              </span>
            </template>
          </div>
          <div class="strategy-foot">
            <div class="strategy-monitor">
              <el-switch
                :model-value="monitorOn(s.id)"
                size="small"
                :loading="monitorSaving === s.id"
                data-monitor
                @change="(v) => toggleMonitor(s, v)"
                @click.stop
              />
              <span class="monitor-label" :class="{ on: monitorOn(s.id) }">监控</span>
            </div>
            <span v-if="monitorOn(s.id)" class="monitor-hint">命中自动入自选 · 触发买卖待确认</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 结果 -->
    <el-card v-if="result || showAllResult" class="result-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <span class="panel-dot result-dot" />
            <span class="result-title">{{ showAll ? '全部策略' : (activeStrategyName || '') }}</span>
            <span class="result-hit">命中 <b>{{ displayRows.length }}</b> 只</span>
            <span v-if="isRealtimeResult">
              <el-tag v-if="decisionWindow" size="small" type="success" effect="light" round>收盘定格</el-tag>
              <el-tag v-else size="small" type="warning" effect="light" round>盘中预警</el-tag>
            </span>
            <span v-else class="text-muted">· {{ asOf }}</span>
          </div>
          <div class="header-actions">
            <el-button size="small" :type="showAll ? 'primary' : 'default'" @click="toggleShowAll" :disabled="!allStrategyRunning">
              <el-icon><Connection /></el-icon>
              全部
            </el-button>
            <el-button size="small" @click="batchAddToFavorites" :disabled="displayRows.length === 0">
              <el-icon><Star /></el-icon>
              批量加自选
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="displayRows" stripe size="default" style="width: 100%" class="hit-table app-table app-table--ranking">
        <el-table-column prop="code" label="代码" min-width="110">
          <template #default="{ row }">
            <router-link class="stock-code" :to="`/stocks/${row.code}`">{{ row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130">
          <template #default="{ row }">
            <router-link class="stock-name" :to="`/stocks/${row.code}`">{{ row.name || row.code }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="close" label="收盘价" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <span v-if="row.close != null">{{ fmtPrice(row.close) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="change_pct" label="涨跌幅" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <el-tag v-if="row.change_pct != null" size="small" :type="row.change_pct >= 0 ? 'danger' : 'success'" effect="plain" round class="pct-tag">
              {{ fmtPctFromFraction(row.change_pct) }}
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol_ratio" label="量比" min-width="100" align="right" sortable>
          <template #default="{ row }">
            <span v-if="row.vol_ratio != null">{{ fmtNum(row.vol_ratio) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" min-width="110" align="right" sortable>
          <template #default="{ row }">
            <span class="score-badge" :style="{ '--sc': scoreColor(row.score) }">{{ fmtNum(row.score, 1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作建议（买入依据 / 离场）" min-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="action-advice">
              <div class="advice-reason" :class="{ empty: !row.reason }">
                <span class="advice-dot" />
                <el-tooltip v-if="row.reason" :content="row.reason" placement="top" :show-after="160">
                  <span class="advice-text">{{ row.reason }}</span>
                </el-tooltip>
                <span v-else class="advice-text muted">已触发筛选条件</span>
              </div>
              <div v-if="row.sell_rules && row.sell_rules.length" class="advice-exit">
                <span class="exit-label">离场</span>
                <span class="exit-text">{{ row.sell_rules.join(' · ') }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="addToFavorite(row)">
              <el-icon><Star /></el-icon>
              加自选
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-else-if="!loading && !runningAll" description="点击策略卡片查看选股结果" :image-size="160" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts, Refresh, Loading, Connection, Star, Clock,
  Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard,
  CircleCheckFilled, WarningFilled, RemoveFilled, QuestionFilled,
  Opportunity, Promotion, Warning, Bottom, Minus,
} from '@element-plus/icons-vue'
import { strategyApi, type StrategyMeta, type StrategyRunItem, type StrategyRunAllItem } from '@/api/strategy'
import {
  marketFitLevel, type MarketContext, type FitResult,
} from '@/utils/marketFit'
import { favoritesApi } from '@/api/favorites'
import { monitorApi } from '@/api/monitor'
import { fmtPrice, fmtPctFromFraction, fmtNum } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

defineOptions({ name: 'StrategyScreener' })

const authStore = useAuthStore()
const currentUserId = computed(() => authStore.user?.id ?? null)

// 策略卡片配色画板（通过 --sc 变量注入，保证深浅色主题下都清晰）
const palette = [
  '#22568d', '#722ed1', '#13c2c2', '#fa8c16', '#f5222d', '#52c41a',
  '#eb2f96', '#2b6cb0', '#a0d911', '#fadb14', '#fa541c', '#36cfc9',
]

// 策略卡片图标画板（轮流使用，避免千篇一律）
const cardIcons = [TrendCharts, Histogram, DataAnalysis, Odometer, Aim, MagicStick, Sunny, Cpu, Coin, Files, DataBoard, TrendCharts]
const cardIcon = (i: number) => cardIcons[i % cardIcons.length]

// 评分配色：越高越偏暖红，越低越偏蓝
const scoreColor = (score: number) => {
  const s = score ?? 0
  if (s >= 80) return '#f5222d'
  if (s >= 60) return '#fa8c16'
  if (s >= 40) return '#faad14'
  if (s >= 20) return '#13c2c2'
  return '#22568d'
}

const strategies = ref<StrategyMeta[]>([])
const loading = ref(false)
const runningAll = ref(false)
const hitCounts = ref<Record<string, number>>({})
const activeStrategy = ref<string | null>(null)
const activeStrategyName = ref('')
const result = ref<{ items: StrategyRunItem[]; as_of: string; strategy_id: string; strategy_name: string } | null>(null)
const showAllResult = ref<StrategyRunAllItem[] | null>(null)
const showAll = ref(false)
const asOf = ref('')
const tradeDates = ref<string[]>([])
const computedAt = ref('')
const allStrategyRunning = ref(false)

// ── 大盘行情上下文（策略行情适配提醒） ────────────────────
const marketCtx = ref<MarketContext | null>(null)
const marketLoading = ref(false)

// 趋势态兜底归一化
const marketTrend = computed<MarketContext['trend']>(() => {
  const t = marketCtx.value?.trend
  return t === 'bull' || t === 'bear' || t === 'sideways' ? t : 'unknown'
})

// 某策略当前行情适配三态（适合 / 中性 / 慎用）
const fitResultCache = new Map<string, FitResult>()
const fit = (s: StrategyMeta): FitResult => {
  let r = fitResultCache.get(s.id)
  if (!r) {
    r = marketFitLevel(s.id, marketCtx.value || {})
    if (!r.meta) {
      // 未收录适配元数据的策略：保持中性，避免 null 访问
      r = { level: 0, label: '中性', meta: { suits: '', avoids: '', signals: { bull: 0, sideways: 0, bear: 0 } } }
    }
    fitResultCache.set(s.id, r)
  }
  return r
}
const fitIcon = (f: FitResult) =>
  f.level === 1 ? CircleCheckFilled : f.level === -1 ? WarningFilled : RemoveFilled

// 顶部行情条展示文案
const TREND_TEXT: Record<string, { label: string; dir: 'up' | 'down' | 'flat'; tip: string }> = {
  bull: { label: '偏强', dir: 'up', tip: '大盘整体上涨，多头趋势为宜' },
  bear: { label: '偏弱', dir: 'down', tip: '大盘整体下跌，宜谨慎' },
  sideways: { label: '中性', dir: 'flat', tip: '大盘窄幅震荡，区间操作为主' },
  unknown: { label: '待研判', dir: 'flat', tip: '暂无大盘行情数据' },
}
const trendText = computed(() => TREND_TEXT[marketTrend.value] || TREND_TEXT.unknown)
const volText = computed(() => {
  const v = marketCtx.value?.volatility
  if (v === 'high') return { label: '高波动' }
  if (v === 'low') return { label: '低波动' }
  return { label: '波动待研判' }
})

// 简洁的操作建议文案
const adviceText = computed(() => {
  const c = marketCtx.value
  if (!c) return '等待行情数据…'
  const t = c.trend
  const v = c.volatility
  if (t === 'bull') {
    if (v === 'high') return '偏强但波动大 → 优先选择突破/趋势类，注意控制仓位'
    return '偏强 → 优先选择趋势、突破、放量类策略'
  }
  if (t === 'bear') {
    if (v === 'high') return '偏弱且高波动 → 谨慎操作，可关注超跌反弹小仓试错'
    return '偏弱 → 降低仓位，关注低估值避险与超跌反弹'
  }
  if (t === 'sideways') {
    if (v === 'high') return '震荡高波动 → 区间操作为主，注意假突破风险'
    return '震荡 → 关注回踩支撑、反转类策略'
  }
  return '等待行情数据…'
})

// 只看推荐筛选
const showRecommendedOnly = ref(false)
const filteredStrategies = computed(() => {
  if (!showRecommendedOnly.value || !marketCtx.value) return strategies.value
  return strategies.value.filter(s => fit(s).level === 1)
})

const loadMarketContext = async () => {
  marketLoading.value = true
  try {
    const res = await strategyApi.marketContext()
    marketCtx.value = ((res as any)?.data as MarketContext | undefined) ?? null
    fitResultCache.clear()
  } catch (e) {
    console.warn('加载大盘行情上下文失败', e)
  } finally {
    marketLoading.value = false
  }
}

// ── 盘中实时触发（仅自选+持仓池） ─────────────────────────
const realtimeScan = ref(false)        // 是否开启盘中预警（实时扫描）开关
const isRealtimeResult = ref(false)    // 最近一次结果是否为实时合成面板
const realtimeNote = ref('')           // 实时扫描说明/失效提示
const decisionWindow = ref(false)      // 是否处于 15:00-15:30 收盘定格可成交窗口

// 实时扫描中，结果即时来自『历史日K + 当日实时合成K』，不展示旧的 computed_at
const dataFreshnessText = computed(() => {
  if (isRealtimeResult.value) return '盘中实时'
  return computedAt.value ? `数据更新于 ${computedAt.value}` : ''
})

const toggleRealtime = async (on: boolean) => {
  realtimeScan.value = on
  isRealtimeResult.value = false
  decisionWindow.value = false
  if (on) {
    if (!currentUserId.value) {
      ElMessage.warning('未获取到登录用户，无法扫描自选+持仓')
      realtimeScan.value = false
      return
    }
    ElMessage.info('盘中预警开启：基于自选+持仓，历史日K + 当日实时K合成（盘中为暂定信号，15:00 收盘定格确认）')
    await runAll(true)
  } else {
    // 关闭实时扫描：重置交易日，避免残留“今天”导致 EOD 面板取到无数据的当日而一直无结果
    asOf.value = ''
    isRealtimeResult.value = false
    result.value = null
    showAllResult.value = null
    activeStrategy.value = null
    await runAll()
  }
}

// ── 常用策略监控开关 ────────────────────────────────────
const monitorStatus = ref<Record<string, boolean>>({})
const monitorSaving = ref<string | null>(null)

const monitorOn = (id: string) => !!monitorStatus.value[id]

const loadMonitorStatus = async () => {
  try {
    const res = await monitorApi.strategyMonitorStatus()
    const items = (res as any)?.data?.items ?? []
    const map: Record<string, boolean> = {}
    for (const it of items) map[it.strategy_id] = !!it.enabled
    monitorStatus.value = map
  } catch (e) {
    console.warn('加载策略监控状态失败', e)
  }
}

const toggleMonitor = async (s: StrategyMeta, on: boolean) => {
  monitorSaving.value = s.id
  try {
    await monitorApi.toggleStrategyMonitor(s.id, on, s.name)
    monitorStatus.value = { ...monitorStatus.value, [s.id]: on }
    ElMessage.success(on ? `已开启「${s.name}」监控` : `已关闭「${s.name}」监控`)
  } catch (e: any) {
    ElMessage.error('切换监控失败：' + (e?.message || '未知错误'))
  } finally {
    monitorSaving.value = null
  }
}

const displayRows = computed<StrategyRunItem[]>(() => {
  if (showAll.value && showAllResult.value) {
    const seen = new Set<string>()
    const merged: StrategyRunItem[] = []
    for (const s of showAllResult.value) {
      for (const row of s.top) {
        if (!seen.has(row.code)) {
          seen.add(row.code)
          merged.push(row)
        }
      }
    }
    return merged
  }
  return result.value?.items ?? []
})

const loadStrategies = async () => {
  loading.value = true
  try {
    // 并行加载策略列表与交易日下拉
    const [listRes, datesRes] = await Promise.allSettled([
      strategyApi.list(),
      strategyApi.tradeDates(30),
    ])
    if (listRes.status === 'fulfilled') {
      const list = (listRes.value as any)?.data ?? listRes.value
      strategies.value = Array.isArray(list) ? list : []
    } else {
      ElMessage.error('加载策略列表失败')
    }
    if (datesRes.status === 'fulfilled') {
      const dres = datesRes.value as any
      const dates = dres?.data?.dates ?? []
      tradeDates.value = Array.isArray(dates) ? dates : []
    }
    // 首次进入自动加载全部策略结果（后端缓存命中时秒回，否则后台计算）
    if (strategies.value.length > 0) {
      await runAll()
    }
  } catch (e) {
    ElMessage.error('加载策略失败')
  } finally {
    loading.value = false
  }
}

const runAll = async (refresh = false) => {
  if (runningAll.value) return
  runningAll.value = true
  try {
    const res = await strategyApi.runAll({
      as_of: asOf.value || null, limit: 30, refresh,
      realtime: realtimeScan.value || undefined,
      user_id: (realtimeScan.value ? currentUserId.value : null),
    })
    const data = (res as any)?.data ?? res
    isRealtimeResult.value = !!data?.realtime
    decisionWindow.value = !!data?.decision_window
    if (isRealtimeResult.value) {
      // 实时结果以当日为准，交易日下拉与 computed_at 不适用
      asOf.value = data.as_of || asOf.value
    } else {
      if (data?.as_of) asOf.value = data.as_of
      if (data?.computed_at) computedAt.value = data.computed_at
    }
    const counts: Record<string, number> = {}
    for (const s of data?.strategies ?? []) {
      counts[s.id] = s.count
    }
    hitCounts.value = counts
    showAllResult.value = data?.strategies ?? null
    allStrategyRunning.value = true
    const strategiesData = data?.strategies ?? []
    // 默认展示第一个策略的完整结果（行数与命中数一致），其余策略点击卡片切换
    if (!activeStrategy.value || !showAll.value) {
      const first = strategiesData[0]
      if (first) {
        activeStrategy.value = first.id
        activeStrategyName.value = first.name
        showAll.value = false
        result.value = {
          strategy_id: first.id,
          strategy_name: first.name,
          as_of: data.as_of,
          total: first.count,
          items: first.top ?? [],
        }
      }
    } else {
      const cur = strategiesData.find((x: any) => x.id === activeStrategy.value)
      if (cur) {
        result.value = {
          strategy_id: cur.id,
          strategy_name: cur.name,
          as_of: data.as_of,
          total: cur.count,
          items: cur.top ?? [],
        }
      }
    }
  } catch (e) {
    ElMessage.error('运行全部策略失败')
  } finally {
    runningAll.value = false
  }
}

const runSingle = async (id: string) => {
  try {
    const res = await strategyApi.run({
      strategy_id: id, as_of: asOf.value || null, limit: 100,
      realtime: realtimeScan.value || undefined,
      user_id: (realtimeScan.value ? currentUserId.value : null),
    })
    const data = (res as any)?.data ?? res
    isRealtimeResult.value = !!data?.realtime
    decisionWindow.value = !!data?.decision_window
    if (data?.as_of) asOf.value = data.as_of
    result.value = data
    if (data?.strategy_id) {
      hitCounts.value = { ...hitCounts.value, [data.strategy_id]: data.total ?? 0 }
    }
  } catch (e) {
    ElMessage.error('运行策略失败')
  }
}

const handleRun = (s: StrategyMeta) => {
  activeStrategy.value = s.id
  activeStrategyName.value = s.name
  showAll.value = false
  // 立即用后端缓存/已加载的 run-all 结果展示，无需等待慢接口
  const cachedStrategy = showAllResult.value?.find((x) => x.id === s.id)
  if (cachedStrategy) {
    result.value = {
      strategy_id: s.id,
      strategy_name: cachedStrategy.name,
      as_of: asOf.value,
      total: cachedStrategy.count,
      items: cachedStrategy.top ?? [],
    }
  }
  // 后台刷新完整明细（limit=100），完成后更新表格
  runSingle(s.id)
}

const onAsOfChange = () => {
  // 切换交易日：清空当前明细并重新加载该交易日结果（后端缓存命中则秒回）
  result.value = null
  showAllResult.value = null
  activeStrategy.value = null
  runAll()
}

const toggleShowAll = () => {
  showAll.value = !showAll.value
  if (showAll.value && !showAllResult.value) {
    runAll()
  }
}

const addToFavorite = async (row: StrategyRunItem) => {
  try {
    const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
    ElMessage.success(`已加入自选：${row.name || row.code}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '加自选失败')
  }
}

const batchAddToFavorites = async () => {
  const rows = displayRows.value
  if (!rows.length) return
  let added = 0
  for (const row of rows) {
    try {
      const res = await favoritesApi.add({ symbol: row.code, stock_code: row.code, stock_name: row.name || row.code, market: 'A股' })
      if ((res as any)?.success !== false) added++
    } catch { /* 忽略单只失败 */ }
  }
  ElMessage.success(`已添加 ${added} 只到自选`)
}

onMounted(() => {
  loadStrategies()
  loadMonitorStatus()
  loadMarketContext()
  // 盘中预警开启时，交易时段内每 5 分钟自动刷新一次（个人分析用，不需要秒级；15:00 后自动定格）
  realtimeTimer = window.setInterval(() => {
    if (realtimeScan.value && !runningAll.value) {
      runAll(true)
    }
  }, 300_000)
})

onBeforeUnmount(() => {
  if (realtimeTimer) window.clearInterval(realtimeTimer)
})

let realtimeTimer: number | undefined
</script>

<style lang="scss" scoped>
.strategy-screener {
  padding: 20px 24px 32px;
  max-width: 1680px;
  margin: 0 auto;

  /* ===== 顶部横幅（由全局 .page-hero 提供，此处仅保留选择器宽度） ===== */
  .date-select {
    width: 160px;
  }

  .realtime-switch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px;
    .rt-label {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }

  /* ===== 收盘定格窗口横幅（15:00-15:30 可成交决策黄金期） ===== */
  .close-window-banner {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 20px;
    margin-bottom: 16px;
    border-radius: 14px;
    border: 1px solid rgba(250, 173, 20, 0.45);
    background:
      radial-gradient(600px 120px at 12% 0%, rgba(250, 173, 20, 0.18), transparent 60%),
      linear-gradient(120deg, color-mix(in srgb, #faad14 14%, transparent), var(--el-bg-color) 55%);
    box-shadow: 0 2px 14px rgba(250, 173, 20, 0.12);

    .cw-orbit {
      position: relative;
      display: grid;
      place-items: center;
      width: 38px;
      height: 38px;
      flex: none;
      border-radius: 50%;
      color: #b8860b;
      background: rgba(250, 173, 20, 0.16);
      border: 1px dashed rgba(250, 173, 20, 0.6);

      .cw-pulse {
        position: absolute;
        inset: 6px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(250, 173, 20, 0.35), transparent 70%);
        animation: cwPulse 1.8s ease-in-out infinite;
      }
    }

    .cw-body {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;

      .cw-title {
        font-size: 15px;
        font-weight: 700;
        color: #8a6d1a;
        letter-spacing: 0.2px;
      }

      .cw-sub {
        font-size: 12.5px;
        color: var(--el-text-color-secondary);
        line-height: 1.5;
      }
    }

    .cw-side {
      flex: none;
      .cw-chip {
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        color: #fff;
        background: linear-gradient(135deg, #f5b93c, #b8860b);
        box-shadow: 0 2px 8px rgba(184, 134, 11, 0.35);
      }
    }
  }

  @keyframes cwPulse {
    0%, 100% { transform: scale(0.9); opacity: 0.45; }
    50% { transform: scale(1.15); opacity: 1; }
  }

  /* ===== 盘中预警条（暂定信号提示） ===== */
  .preview-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    margin-bottom: 16px;
    border-radius: 10px;
    font-size: 12.5px;
    color: var(--el-color-warning);
    background: color-mix(in srgb, var(--el-color-warning) 10%, var(--el-bg-color));
    border: 1px solid color-mix(in srgb, var(--el-color-warning) 30%, transparent);
  }

  /* ===== 大盘行情上下文条 ===== */
  .market-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 20px;
    margin-bottom: 18px;
    border-radius: 14px;
    border: 1px solid var(--el-border-color-lighter);
    background: linear-gradient(135deg, color-mix(in srgb, var(--mbc) 8%, transparent), var(--el-bg-color) 50%);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
    --mbc: var(--el-color-primary);

    &.trend-bull { --mbc: var(--el-color-danger); }
    &.trend-bear { --mbc: var(--el-color-success); }
    &.trend-sideways { --mbc: var(--el-color-warning); }
    &.trend-unknown { --mbc: var(--el-text-color-secondary); }

    .market-left {
      display: flex;
      align-items: center;
      gap: 14px;
      flex: 1;
      min-width: 0;
      flex-wrap: wrap;
    }

    .verdict-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 700;
      color: var(--mbc);
      background: color-mix(in srgb, var(--mbc) 12%, transparent);
      border: 1px solid color-mix(in srgb, var(--mbc) 28%, transparent);

      .verdict-icon {
        font-size: 16px;
      }
      .verdict-label {
        letter-spacing: 0.5px;
      }
      .verdict-vol {
        font-size: 12px;
        font-weight: 500;
        opacity: 0.8;
      }
    }

    .verdict-advice {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13.5px;
      color: var(--el-text-color-regular);
      flex: 1;
      min-width: 200px;

      .advice-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        border-radius: 50%;
        background: color-mix(in srgb, var(--mbc) 14%, transparent);
        color: var(--mbc);
        flex-shrink: 0;
      }
      .advice-text {
        line-height: 1.5;
        font-weight: 500;
      }
    }

    .market-right {
      flex-shrink: 0;
    }
  }

  /* ===== 卡片通用 ===== */
  .strategy-panel,
  .result-panel {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--el-border-color-lighter);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);

    :deep(.el-card__header) {
      padding: 14px 22px;
      border-bottom: 1px solid var(--el-border-color-lighter);
      background: var(--el-fill-color-lighter);
    }

    :deep(.el-card__body) {
      padding: 20px 22px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;

      .card-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);

        .panel-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--el-color-primary);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
        }

        .result-dot {
          background: var(--el-color-success);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent);
        }

        .panel-count {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 22px;
          height: 20px;
          padding: 0 7px;
          border-radius: 20px;
          font-size: 12px;
          color: #fff;
          background: var(--el-color-primary);
        }

        .result-hit {
          font-weight: 400;
          color: var(--el-text-color-regular);
          b {
            color: var(--el-color-danger);
            font-size: 16px;
            margin: 0 2px;
          }
        }

        .text-muted { font-weight: 400; }
      }
    }
  }

  /* ===== 策略卡片 ===== */
  .strategy-panel {
    margin-bottom: 22px;

    .strategy-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
      gap: 16px;
    }

    .strategy-card {
      position: relative;
      padding: 18px;
      background: var(--el-fill-color-light);
      border-radius: 14px;
      cursor: pointer;
      border: 2px solid transparent;
      transition: all 0.25s ease;
      overflow: hidden;

      &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--sc), transparent);
        opacity: 0;
        transition: opacity 0.25s ease;
      }

      &:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        border-color: color-mix(in srgb, var(--sc) 45%, transparent);
        background: var(--el-bg-color);

        &::before { opacity: 1; }
      }

      &.active {
        border-color: var(--sc);
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--sc) 8%, transparent) 0%, transparent 60%),
          var(--el-bg-color);

        &::before { opacity: 1; }
      }

      &.card-recommended {
        border-color: color-mix(in srgb, var(--el-color-success) 50%, transparent);
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--el-color-success) 6%, transparent) 0%, transparent 50%),
          var(--el-bg-color);
        box-shadow: 0 4px 16px color-mix(in srgb, var(--el-color-success) 12%, transparent);

        &::before {
          opacity: 1;
          background: linear-gradient(90deg, var(--el-color-success), transparent);
        }
      }

      &.card-caution {
        opacity: 0.65;
      }

      &.loading {
        opacity: 0.7;
        pointer-events: none;
      }

      .strategy-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;

        .strategy-name {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;

          .strategy-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 38px;
            flex-shrink: 0;
            border-radius: 10px;
            font-size: 19px;
            color: var(--sc);
            background: color-mix(in srgb, var(--sc) 12%, transparent);
          }

          .strategy-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--el-text-color-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }

        .strategy-count {
          display: flex;
          align-items: baseline;
          gap: 2px;
          flex-shrink: 0;

          .count-num {
            font-size: 22px;
            font-weight: 800;
            line-height: 1;
            color: var(--sc);
          }

          .count-unit {
            font-size: 12px;
            color: var(--el-text-color-secondary);
          }
        }

        .spinner {
          color: var(--sc);
        }
      }

      .strategy-desc {
        font-size: 13px;
        color: var(--el-text-color-regular);
        margin-bottom: 10px;
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        min-height: 39px;
      }

      /* ===== 买卖规则：明确告诉用户何时买 / 何时卖 ===== */
      .strategy-rules {
        margin-bottom: 10px;
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding: 9px 10px;
        border-radius: 8px;
        background: color-mix(in srgb, var(--el-fill-color) 55%, transparent);
        border-left: 2px solid var(--sc);

        .rule-row {
          display: flex;
          align-items: baseline;
          gap: 8px;
          min-width: 0;
        }

        .rule-flag {
          flex: none;
          font-size: 11px;
          font-weight: 700;
          padding: 1px 7px;
          border-radius: 5px;
          line-height: 1.7;

          &.buy {
            color: #fff;
            background: var(--el-color-danger);
          }
          &.sell {
            color: #fff;
            background: var(--el-color-success);
          }
        }

        .rule-text {
          font-size: 12px;
          color: var(--el-text-color-secondary);
          line-height: 1.45;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
      }

      .strategy-tags {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;

        .strategy-tag {
          --el-tag-bg-color: color-mix(in srgb, var(--sc) 9%, transparent);
          --el-tag-border-color: color-mix(in srgb, var(--sc) 25%, transparent);
          --el-tag-text-color: var(--sc);
        }
      }

      /* ===== 行情适配：视觉化推荐标记 ===== */
      .strategy-fit-mark {
        margin-top: 10px;
        min-height: 0;

        .mark-pill {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 12px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
        }

        .mark-pill.recommended {
          color: var(--el-color-success);
          background: color-mix(in srgb, var(--el-color-success) 12%, transparent);
          border: 1px solid color-mix(in srgb, var(--el-color-success) 30%, transparent);
          animation: recommend-glow 2.5s ease-in-out infinite;
        }

        .mark-pill.caution {
          color: var(--el-color-danger);
          background: color-mix(in srgb, var(--el-color-danger) 8%, transparent);
          border: 1px solid color-mix(in srgb, var(--el-color-danger) 22%, transparent);
          opacity: 0.75;
        }

        &.lv--1 {
          opacity: 0.75;
        }
      }

      @keyframes recommend-glow {
        0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--el-color-success) 30%, transparent); }
        50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--el-color-success) 10%, transparent); }
      }

      .strategy-foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-top: 12px;
        padding-top: 10px;
        border-top: 1px dashed var(--el-border-color-lighter);

        .strategy-monitor {
          display: flex;
          align-items: center;
          gap: 6px;

          .monitor-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--el-text-color-secondary);
            &.on { color: var(--sc); }
          }
        }

        .monitor-hint {
          font-size: 11px;
          color: var(--el-text-color-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }
  }

  /* ===== 结果表格 ===== */
  .result-panel {
    .pct-tag {
      font-weight: 600;
      min-width: 64px;
      justify-content: center;
    }

    .score-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 36px;
      height: 22px;
      padding: 0 8px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: var(--sc);
    }

    /* ===== 操作建议列：买入依据 + 离场规则 ===== */
    .action-advice {
      display: flex;
      flex-direction: column;
      gap: 5px;
      padding: 2px 0;

      .advice-reason {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;

        .advice-dot {
          flex: none;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--el-color-primary);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
        }

        .advice-text {
          font-size: 12.5px;
          color: var(--el-text-color-primary);
          line-height: 1.4;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 320px;

          &.muted {
            color: var(--el-text-color-secondary);
          }
        }
      }

      .advice-exit {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;

        .exit-label {
          flex: none;
          font-size: 11px;
          font-weight: 600;
          color: var(--el-color-success);
        }

        .exit-text {
          font-size: 12px;
          color: var(--el-text-color-secondary);
          line-height: 1.4;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }

    .text-muted { color: var(--el-text-color-secondary); }
  }
}

@media (max-width: 900px) {
  .strategy-screener {
    .strategy-grid {
      grid-template-columns: 1fr;
    }
  }
}

@media (max-width: 768px) {
  .strategy-screener {
    .market-bar {
      flex-direction: column;
      align-items: stretch;
      gap: 12px;
      padding: 12px 14px;

      .market-left {
        flex-direction: column;
        align-items: stretch;
        gap: 10px;
      }

      .verdict-advice {
        font-size: 13px;
      }

      .market-right {
        display: flex;
        justify-content: flex-end;
      }
    }
  }
}

html.dark {
  .strategy-screener {
    .strategy-panel,
    .result-panel {
      :deep(.el-card__header) {
        background: var(--el-fill-color-dark);
      }
    }

    .strategy-card {
      background: var(--el-fill-color-darker);
      &:hover {
        background: var(--el-fill-color-dark);
      }
      &.active {
        background: linear-gradient(135deg, color-mix(in srgb, var(--sc) 14%, transparent) 0%, transparent 60%),
          var(--el-fill-color-dark);
      }
      &.card-recommended {
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--el-color-success) 10%, transparent) 0%, transparent 50%),
          var(--el-fill-color-dark);
      }
    }
  }
}
</style>