<script setup lang="ts">
defineOptions({ name: 'Cockpit' })

import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Aim, Reading } from '@element-plus/icons-vue'
import { cockpitApi } from '@/api/cockpit'
import type {
  GateData,
  MainlineData,
  PoolData,
  PoolItem,
  PositionItem,
  PositionsData,
  SignalsData
} from '@/api/cockpit'
import GateCard from './components/GateCard.vue'
import MainlineCard from './components/MainlineCard.vue'
import PoolTable from './components/PoolTable.vue'
import SignalsPanel from './components/SignalsPanel.vue'
import PositionsPanel from './components/PositionsPanel.vue'
import MethodologyCard from './components/MethodologyCard.vue'

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const gate = ref<GateData | null>(null)
const mainline = ref<MainlineData | null>(null)
const pool = ref<PoolData | null>(null)
const signals = ref<SignalsData | null>(null)
const positions = ref<PositionsData | null>(null)

const loading = ref({
  gate: false,
  mainline: false,
  pool: false,
  signals: false,
  positions: false
})
const rescanLoading = ref(false)
const updatedAt = ref('')
const firstLoaded = ref(false)

const todayLabel = computed(() => {
  const d = new Date()
  const w = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}（周${w}）`
})

// ---------------------------------------------------------------------------
// 数据加载（区块独立成败）
// ---------------------------------------------------------------------------
function errText(e: any): string {
  return e?.message || String(e)
}

async function loadGate() {
  loading.value.gate = true
  try {
    gate.value = await cockpitApi.getGate()
  } catch (e) {
    ElMessage.warning(`环境闸门加载失败：${errText(e)}`)
  } finally {
    loading.value.gate = false
  }
}

async function loadMainline() {
  loading.value.mainline = true
  try {
    mainline.value = await cockpitApi.getMainline()
  } catch (e) {
    ElMessage.warning(`主线方向加载失败：${errText(e)}`)
  } finally {
    loading.value.mainline = false
  }
}

async function loadPool() {
  loading.value.pool = true
  try {
    pool.value = await cockpitApi.getPool()
  } catch (e) {
    ElMessage.warning(`观察池加载失败：${errText(e)}`)
  } finally {
    loading.value.pool = false
  }
}

async function loadSignals() {
  loading.value.signals = true
  try {
    signals.value = await cockpitApi.getSignals()
  } catch (e) {
    ElMessage.warning(`突破信号加载失败：${errText(e)}`)
  } finally {
    loading.value.signals = false
  }
}

async function loadPositions() {
  loading.value.positions = true
  try {
    positions.value = await cockpitApi.getPositions()
  } catch (e) {
    ElMessage.warning(`纪律持仓加载失败：${errText(e)}`)
  } finally {
    loading.value.positions = false
  }
}

async function loadAll() {
  const results = await Promise.allSettled([
    loadGate(),
    loadMainline(),
    loadPool(),
    loadSignals(),
    loadPositions()
  ])
  const failed = results.filter(r => r.status === 'rejected').length
  if (!failed) {
    const d = new Date()
    updatedAt.value = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    firstLoaded.value = true
  }
}

/** 盘中轻量刷新：只刷信号 + 持仓 + 闸门（池与主线变化慢） */
async function pollRefresh() {
  const results = await Promise.allSettled([loadSignals(), loadPositions(), loadGate()])
  if (results.some(r => r.status === 'fulfilled')) {
    const d = new Date()
    updatedAt.value = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
}

// ---------------------------------------------------------------------------
// 轮询（盘中每 2 分钟；页面隐藏/失活时暂停）
// ---------------------------------------------------------------------------
const POLL_MS = 120000
let timer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  if (timer) return
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') pollRefresh()
  }, POLL_MS)
}
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function onVisibility() {
  if (document.visibilityState === 'visible' && firstLoaded.value) pollRefresh()
}

// ---------------------------------------------------------------------------
// 重扫观察池
// ---------------------------------------------------------------------------
async function handleRescan() {
  rescanLoading.value = true
  try {
    const res = await cockpitApi.rescanPool()
    ElMessage.success(`重扫完成：入池 ${res?.total ?? 0} 只`)
    await Promise.allSettled([loadPool(), loadSignals(), loadMainline()])
  } catch (e) {
    ElMessage.error(`重扫失败：${errText(e)}`)
  } finally {
    rescanLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// 标记买入
// ---------------------------------------------------------------------------
const buyDialog = ref(false)
const buyTarget = ref<PoolItem | null>(null)
const buyPrice = ref<number>(0)
const buySubmitting = ref(false)

function openBuy(item: PoolItem) {
  buyTarget.value = item
  buyPrice.value = Number(
    (item.current_price ?? item.last_price ?? item.trigger_price ?? item.close).toFixed(2)
  )
  buyDialog.value = true
}

async function submitBuy() {
  const t = buyTarget.value
  if (!t) return
  if (!buyPrice.value || buyPrice.value <= 0) {
    ElMessage.warning('请输入有效的买入价')
    return
  }
  buySubmitting.value = true
  try {
    await cockpitApi.createPosition(t.code, buyPrice.value)
    ElMessage.success(`已标记买入 ${t.name}，进入纪律跟踪`)
    buyDialog.value = false
    await Promise.allSettled([loadPositions(), loadSignals(), loadPool()])
  } catch (e) {
    ElMessage.error(`标记买入失败：${errText(e)}`)
  } finally {
    buySubmitting.value = false
  }
}

// ---------------------------------------------------------------------------
// 了结持仓
// ---------------------------------------------------------------------------
const closeDialog = ref(false)
const closeTarget = ref<PositionItem | null>(null)
const closePrice = ref<number>(0)
const closeSubmitting = ref(false)

function openClose(item: PositionItem) {
  closeTarget.value = item
  closePrice.value = Number((item.current_price ?? item.buy_price).toFixed(2))
  closeDialog.value = true
}

async function submitClose() {
  const t = closeTarget.value
  if (!t) return
  if (!closePrice.value || closePrice.value <= 0) {
    ElMessage.warning('请输入有效的卖出价')
    return
  }
  closeSubmitting.value = true
  try {
    await cockpitApi.closePosition(t.id, closePrice.value)
    ElMessage.success(`已了结 ${t.name}`)
    closeDialog.value = false
    await loadPositions()
  } catch (e) {
    ElMessage.error(`了结失败：${errText(e)}`)
  } finally {
    closeSubmitting.value = false
  }
}

const buyPnlPreview = computed(() => {
  const t = buyTarget.value
  if (!t || !buyPrice.value) return ''
  const trigger = t.trigger_price
  const stop = buyPrice.value * 0.92
  return `若跌破 ${stop.toFixed(2)}（-8%）执行止损；B2 触发价 ${trigger?.toFixed(2) ?? '—'}`
})

// ---------------------------------------------------------------------------
// 今日动作：把闸门 + 信号 + 池子合成一句话，直接回答「今天买不买、买什么」
// ---------------------------------------------------------------------------
const actionBrief = computed(() => {
  const g = gate.value
  if (!g) return null
  const triggered = signals.value?.triggered?.length ?? 0
  const near = signals.value?.near?.length ?? 0
  const total = pool.value?.total ?? signals.value?.watching_count ?? 0

  if (triggered > 0 && g.gate !== 'red') {
    return {
      tone: 'green',
      title: `${triggered} 只满足 B2 突破买点`,
      text: '右侧确认已出现：按纪律买入，成交即设 -8% 止损，次日才能卖（T+1）。'
    }
  }
  if (g.gate === 'red') {
    return {
      tone: 'red',
      title: '今天不买',
      text: `环境不支持（${g.portrait} · ${g.label}），仓位建议 ${g.position_hint}。观察池 ${total} 只只做跟踪，等闸门转黄/绿再谈买点。`
    }
  }
  if (near > 0) {
    return {
      tone: 'yellow',
      title: `${near} 只临近触发`,
      text: '盯住触发价：满足 B2（放量 + 中阳 + 站上 MA55/60）才算确认，不提前埋伏。'
    }
  }
  return {
    tone: 'yellow',
    title: '继续观察',
    text: `观察池 ${total} 只，暂无票临近触发，今天不买，等信号。`
  }
})

/** 最近一只距触发（池按距离升序，取第一只） */
const nearestText = computed(() => {
  const first = pool.value?.items?.[0]
  if (!first || first.distance_to_trigger == null) return ''
  return `${first.name} 距触发 ${(first.distance_to_trigger * 100).toFixed(1)}%`
})

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------
onMounted(() => {
  loadAll()
  document.addEventListener('visibilitychange', onVisibility)
  startPolling()
})
onActivated(() => {
  if (firstLoaded.value) pollRefresh()
  startPolling()
})
onDeactivated(stopPolling)
onUnmounted(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div class="cockpit">
    <!-- 页头 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ todayLabel }} · 交易驾驶舱</h2>
          <p class="page-hero-sub">环境闸门 → 主线方向 → 左侧观察 → 右侧确认 → 纪律离场，一条可执行的买卖链</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span v-if="gate" class="ck-gate-pill" :class="`is-${gate.gate}`">{{ gate.label }}</span>
        <span class="page-hero-tag">日线 {{ gate?.as_of_portrait || '—' }}</span>
        <span v-if="pool?.quote_as_of" class="page-hero-tag">快照 {{ pool.quote_as_of }}</span>
        <span class="page-hero-tag">更新于 {{ updatedAt || '—' }}</span>
        <el-button
          type="primary"
          plain
          :icon="Refresh"
          :loading="loading.gate || loading.mainline || loading.pool || loading.signals || loading.positions"
          @click="loadAll"
        >
          刷新
        </el-button>
      </div>
    </div>

    <!-- 今日动作：一句话结论 -->
    <div v-if="actionBrief" class="ck-action" :class="`is-${actionBrief.tone}`">
      <span class="ck-action-title">{{ actionBrief.title }}</span>
      <span class="ck-action-text">{{ actionBrief.text }}</span>
      <span v-if="nearestText" class="ck-action-extra">{{ nearestText }}</span>
    </div>

    <!-- 00 方法论 -->
    <section class="ck-sec">
      <MethodologyCard />
    </section>

    <!-- 01 环境闸门 -->
    <section id="gate" class="ck-sec">
      <div class="ck-sec-head">
        <span class="ck-sec-no">01</span>
        <span class="ck-sec-title">环境闸门</span>
        <span class="ck-sec-hint">今天能不能打？红灯不买、黄灯轻仓、绿灯按信号打</span>
        <span class="ck-sec-actions">
          <span v-if="gate?.as_of_portrait" class="ck-sec-time">画像 {{ gate.as_of_portrait }}</span>
        </span>
      </div>
      <GateCard :data="gate" :loading="loading.gate" />
    </section>

    <!-- 02 主线方向 -->
    <section id="mainline" class="ck-sec">
      <div class="ck-sec-head">
        <span class="ck-sec-no">02</span>
        <span class="ck-sec-title">主线方向</span>
        <span class="ck-sec-hint">资金持续流入的方向 → 只在这些方向里挑票（集中兵力）</span>
        <span class="ck-sec-actions">
          <span v-if="mainline?.updated_at" class="ck-sec-time">更新 {{ mainline.updated_at }}</span>
        </span>
      </div>
      <div class="ck-panel">
        <MainlineCard :data="mainline" :loading="loading.mainline" />
      </div>
    </section>

    <!-- 03 积累区观察池 -->
    <section id="pool" class="ck-sec">
      <div class="ck-sec-head">
        <span class="ck-sec-no">03</span>
        <span class="ck-sec-title">积累区观察池 · B1 ∩ 积累区</span>
        <span class="ck-sec-hint">全市场 B1 左侧买点再叠积累区四条件 = 精选。这里只观察，不买</span>
        <span class="ck-sec-actions">
          <span v-if="pool?.scanned_at" class="ck-sec-time">扫描 {{ pool.scanned_at }}</span>
        </span>
      </div>
      <div class="ck-panel">
        <PoolTable
          :data="pool"
          :loading="loading.pool || rescanLoading"
          @buy="openBuy"
          @rescan="handleRescan"
        />
      </div>
    </section>

    <!-- 04 B2 突破买点 -->
    <section id="signals" class="ck-sec">
      <div class="ck-sec-head">
        <span class="ck-sec-no">04</span>
        <span class="ck-sec-title">B2 突破买点</span>
        <span class="ck-sec-hint">与 Candidate 同一真源 —— 确认一只买一只，不提前埋伏</span>
        <span class="ck-sec-actions">
          <el-tag v-if="signals" size="small" :type="signals.triggered.length ? 'success' : 'info'" effect="plain">
            已触发 {{ signals.triggered.length }}
          </el-tag>
        </span>
      </div>
      <div class="ck-panel">
        <SignalsPanel :data="signals" :loading="loading.signals" @buy="openBuy" />
      </div>
    </section>

    <!-- 05 纪律持仓 -->
    <section id="positions" class="ck-sec">
      <div class="ck-sec-head">
        <span class="ck-sec-no">05</span>
        <span class="ck-sec-title">纪律持仓</span>
        <span class="ck-sec-hint">买入后交给统一离场：假突破 / 止损 / S1-S3 卖点 / MA5 / 止盈 / 时间止损</span>
        <span class="ck-sec-actions">
          <el-tag
            v-if="positions"
            size="small"
            :type="positions.items.some(i => i.state === 'exit') ? 'danger' : 'info'"
            effect="plain"
          >
            持仓 {{ positions.items.length }}
          </el-tag>
        </span>
      </div>
      <div class="ck-panel">
        <PositionsPanel :data="positions" :loading="loading.positions" @close="openClose" />
      </div>
    </section>

    <!-- 买入口径提示 -->
    <div class="ck-bottom-note">
      <el-icon><Reading /></el-icon>
      <span>
        信号来自盘中每 15 分钟统一扫描（09:30-15:00），触发后会推送到通知中心；
        页面盘中每 2 分钟自动刷新，切走页面时自动暂停。
      </span>
    </div>

    <!-- 标记买入弹窗 -->
    <el-dialog v-model="buyDialog" title="标记买入" width="420px" append-to-body>
      <div v-if="buyTarget" class="ck-dialog">
        <div class="ck-dialog-stock">
          <b>{{ buyTarget.name }}</b>
          <span>{{ buyTarget.code }} · {{ buyTarget.industry || '—' }}</span>
        </div>
        <div class="ck-dialog-row">
          <span class="ck-dialog-label">触发价</span>
          <span class="ck-dialog-val">{{ buyTarget.trigger_price?.toFixed(2) ?? '—' }}</span>
          <span class="ck-dialog-label">现价</span>
          <span class="ck-dialog-val">
            {{ (buyTarget.current_price ?? buyTarget.last_price ?? buyTarget.close)?.toFixed(2) }}
          </span>
        </div>
        <div class="ck-dialog-row">
          <span class="ck-dialog-label">买入价</span>
          <el-input-number v-model="buyPrice" :min="0.01" :step="0.01" :precision="2" size="small" />
        </div>
        <div class="ck-dialog-tip">{{ buyPnlPreview }}</div>
        <div class="ck-dialog-tip">
          买入后进入「纪律持仓」，系统按统一离场规则（假突破 / 8% 止损 / S1-S3 卖点 / MA5 / 止盈 / 30 日时间止损）逐条跟踪
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="buyDialog = false">取消</el-button>
        <el-button size="small" type="primary" :loading="buySubmitting" @click="submitBuy">
          确认买入
        </el-button>
      </template>
    </el-dialog>

    <!-- 了结弹窗 -->
    <el-dialog v-model="closeDialog" title="了结持仓" width="400px" append-to-body>
      <div v-if="closeTarget" class="ck-dialog">
        <div class="ck-dialog-stock">
          <b>{{ closeTarget.name }}</b>
          <span>{{ closeTarget.code }}</span>
        </div>
        <div class="ck-dialog-row">
          <span class="ck-dialog-label">成本</span>
          <span class="ck-dialog-val">{{ closeTarget.buy_price?.toFixed(2) }}</span>
          <span class="ck-dialog-label">现价</span>
          <span class="ck-dialog-val">{{ closeTarget.current_price?.toFixed(2) ?? '—' }}</span>
        </div>
        <div class="ck-dialog-row">
          <span class="ck-dialog-label">卖出价</span>
          <el-input-number v-model="closePrice" :min="0.01" :step="0.01" :precision="2" size="small" />
        </div>
        <div v-if="closeTarget.reasons?.length" class="ck-dialog-tip">
          离场原因：{{ closeTarget.reasons.join('；') }}
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="closeDialog = false">取消</el-button>
        <el-button size="small" type="primary" :loading="closeSubmitting" @click="submitClose">
          确认了结
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cockpit { padding-bottom: 24px; }

.ck-gate-pill {
  font-size: 12px;
  font-weight: 700;
  border-radius: 20px;
  padding: 3px 11px;
}
.ck-gate-pill.is-green { background: #dcfce7; color: #15803d; }
.ck-gate-pill.is-yellow { background: #fef3c7; color: #b45309; }
.ck-gate-pill.is-red { background: #fee2e2; color: #b91c1c; }

/* 今日动作结论条 */
.ck-action {
  margin-top: 12px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  padding: 11px 16px;
  border-radius: 10px;
  border-left: 4px solid var(--el-border-color);
  background: var(--el-fill-color-lighter);
}
.ck-action.is-red { border-left-color: #ef4444; background: #fef2f2; }
.ck-action.is-yellow { border-left-color: #f59e0b; background: #fffbeb; }
.ck-action.is-green { border-left-color: #16a34a; background: #f0fdf4; }
.ck-action-title { font-size: 14px; font-weight: 700; }
.ck-action.is-red .ck-action-title { color: #b91c1c; }
.ck-action.is-yellow .ck-action-title { color: #b45309; }
.ck-action.is-green .ck-action-title { color: #15803d; }
.ck-action-text { font-size: 12px; line-height: 1.7; color: var(--el-text-color-regular); flex: 1 1 320px; }
.ck-action-extra {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  border: 1px dashed var(--el-border-color);
  border-radius: 12px;
  padding: 2px 10px;
  white-space: nowrap;
}

.ck-sec { margin-top: 18px; }
.ck-sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.ck-sec-no {
  font-size: 11px;
  font-weight: 700;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 4px;
  padding: 2px 7px;
}
.ck-sec-title { font-size: 15px; font-weight: 700; }
.ck-sec-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex: 1;
  min-width: 200px;
}
.ck-sec-actions { display: flex; align-items: center; gap: 8px; }
.ck-sec-time { font-size: 11px; color: var(--el-text-color-placeholder); }

.ck-panel {
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-bg-color);
  padding: 14px 16px;
}

.ck-bottom-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 10px 14px;
}

.ck-dialog { display: flex; flex-direction: column; gap: 12px; }
.ck-dialog-stock { display: flex; align-items: baseline; gap: 10px; }
.ck-dialog-stock b { font-size: 15px; }
.ck-dialog-stock span { font-size: 12px; color: var(--el-text-color-secondary); }
.ck-dialog-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ck-dialog-label { font-size: 12px; color: var(--el-text-color-secondary); }
.ck-dialog-val { font-size: 14px; font-weight: 600; margin-right: 8px; }
.ck-dialog-tip { font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
</style>
