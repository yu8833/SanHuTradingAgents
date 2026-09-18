<template>
  <div class="paper-trading app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><CreditCard /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">模拟交易</h2>
          <p class="page-hero-sub">策略信号 · 虚拟资金 · 模拟下单</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button :icon="Refresh" text size="small" :loading="synLoading" @click="loadAll">刷新信号</el-button>
        <el-button type="primary" :icon="Plus" @click="openOrderDialog">下市场单</el-button>
        <el-button type="danger" plain :icon="Delete" @click="confirmReset">重置账户</el-button>
      </div>
    </div>

    <!-- ═══════════ ① 今日买卖信号 ═══════════ -->
    <section class="signal-shell">
      <div class="signal-hd">
        <div class="signal-hd-left">
          <div class="signal-title-row">
            <h3 class="signal-title">今日买卖信号</h3>
            <span class="signal-asof">更新于 {{ synAsOf }}</span>
          </div>
          <!-- 监控状态条 -->
          <div class="moni-bar">
            <span class="moni-strategy" :class="monitorStatus.strategyNames.length ? 'has' : ''">
              <span class="moni-label">常用策略</span>
              <template v-if="monitorStatus.strategyNames.length">
                <span v-for="n in monitorStatus.strategyNames" :key="n" class="moni-tag">{{ n }}</span>
              </template>
              <span v-else class="moni-empty">未启用</span>
            </span>
            <span class="moni-desc">监控中的策略信号将直接汇入买卖清单</span>
          </div>
        </div>
        <div class="signal-hd-right">
          <el-button size="small" type="primary" @click="goMonitorCenter">
            管理监控 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="synLoading" class="signal-loading">
        <el-skeleton :rows="4" animated />
        <div class="sync-tip">正在加载买卖信号…</div>
      </div>

      <template v-else-if="syn">
        <div class="list-wrap">
          <!-- 建议买入：富信息信号卡片 -->
          <div class="ls-col ls-buy">
            <div class="col-hd">
              <span class="col-title">
                <span class="dot dot-buy"></span>建议买入
              </span>
              <el-tag v-if="buys.length" size="small" type="danger" effect="plain">{{ buys.length }}</el-tag>
              <span v-else class="col-empty-note">暂无信号</span>
            </div>
            <div v-if="buys.length" class="buy-list">
              <div v-for="b in buys" :key="b.code + (b.plan_id || '')" class="buy-card">
                <div class="bc-hd">
                  <div class="bc-stk">
                    <router-link class="bc-name" :to="`/stocks/${b.code}`">{{ b.name || b.code }}</router-link>
                    <span class="bc-code">{{ b.code }}</span>
                  </div>
                  <div class="bc-tags">
                    <el-tooltip :content="buySource(b).full || buySource(b).text" placement="top" :disabled="!buySource(b).full">
                      <span class="src-tag" :class="'src-' + buySource(b).type">{{ buySource(b).text }}</span>
                    </el-tooltip>
                    <span v-if="b.signal_label" class="sig-badge">{{ b.signal_label }}</span>
                  </div>
                </div>
                <div class="bc-price">
                  <div class="bc-cell">
                    <span class="bc-label">触发价</span>
                    <span class="bc-val">{{ b.trigger_price ?? '—' }}</span>
                  </div>
                  <span class="bc-arrow">→</span>
                  <div class="bc-cell">
                    <span class="bc-label">现价</span>
                    <span class="bc-val">{{ b.last_price ?? '—' }}</span>
                  </div>
                  <div class="bc-cell bc-dist">
                    <span class="bc-label">距触发</span>
                    <span class="bc-val" :class="pctClass(b.distance_pct)">{{ fmtPct(b.distance_pct) }}</span>
                  </div>
                  <span class="bc-state" v-if="b.triggered">已触价</span>
                  <span v-else-if="b.confirmed === false" class="bc-state warn">待确认</span>
                  <span v-else-if="b.distance_pct != null && b.distance_pct <= 2" class="bc-state warn">接近触发</span>
                </div>
                <div class="bc-foot">
                  <span class="bc-advice" :title="b.buy_reason">{{ b.advice || '—' }}</span>
                  <el-button size="small" class="act act-buy" @click="buyFromSignal(b)">买入</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无建议买入" :image-size="56" />
            <p class="col-note" v-if="!buys.length">当日计划/候选池无买入触达信号，可前往监控中心查看策略监控结果。</p>
          </div>

          <!-- 持仓卖出（绿系） -->
          <div class="ls-col ls-sell">
            <div class="col-hd">
              <span class="col-title">
                <span class="dot dot-sell"></span>持仓卖出
              </span>
              <el-tag v-if="sells.length" size="small" type="success" effect="plain">{{ realSells.length }}</el-tag>
              <span v-else class="col-empty-note">暂无信号</span>
            </div>
            <el-table v-if="sells.length" :data="sortedSells" size="small" class="ms-table" :row-class-name="sellRowClass">
              <el-table-column label="股票" min-width="120">
                <template #default="{ row }">
                  <div class="stk">
                    <router-link class="stk-name" :to="`/stocks/${row.code}`">{{ row.name || row.code }}</router-link>
                    <span class="stk-code">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="100">
                <template #default="{ row }">
                  <span class="src-tag" :class="'src-' + sellSource(row).type">{{ sellSource(row).text }}</span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏" width="82" align="right">
                <template #default="{ row }">
                  <span class="pct" :class="pctClass(row.profit_loss_rate)">{{ fmtPct(row.profit_loss_rate) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="止损" width="80" align="right">
                <template #default="{ row }"><span class="money">{{ row.stop_loss_price ?? '—' }}</span></template>
              </el-table-column>
              <el-table-column label="建议" min-width="136">
                <template #default="{ row }">
                  <div class="advice">
                    <b v-if="row.advice_label" class="advice-label">{{ row.advice_label }}</b>
                    {{ row.advice_text || row.advice || '—' }}
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="" width="76" align="right">
                <template #default="{ row }">
                  <el-button size="small" class="act act-sell" :disabled="isHoldSell(row)" @click="sellFromSignal(row)">卖出</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="holdSells.length" class="hold-hint">置灰行 = 卖出信号外的持仓评估（继续持有），不参与卖出操作</div>
            <el-empty v-else description="暂无卖出建议" :image-size="56" />
            <p class="col-note" v-if="!sells.length">持仓暂无卖点触达，止损/止盈建议将在此汇总。</p>
          </div>
        </div>
        <div class="signal-foot">
          <span class="foot-item">
            <span class="foot-dot foot-dot-buy"></span>建议买入：当日计划 / 候选池 / 常用策略触发
          </span>
          <span class="foot-item">
            <span class="foot-dot foot-dot-sell"></span>持仓卖出：盈亏评估 / 止损止盈
          </span>
          <span class="foot-item">账户概览与持仓请前往「持仓追踪」</span>
        </div>
      </template>
    </section>

    <!-- ═══════════ 下市场单 ═══════════ -->
    <el-dialog v-model="orderDialog" title="下市场单" width="480px">
      <!-- 分析上下文提示 -->
      <div v-if="(order as any).analysis_id" class="analysis-context">
        <el-alert :closable="false" type="info" show-icon>
          <template #title>
            来自分析报告：<span style="font-family:monospace">{{ (order as any).analysis_id }}</span>
            <el-button link size="small" type="primary" style="margin-left:8px" @click="viewReport((order as any).analysis_id)">查看报告</el-button>
          </template>
          <div v-if="analysisLoading" style="color:#666">正在加载分析摘要…</div>
          <div v-else-if="analysisContext">
            <div style="font-size:12px;color:#666">
              <span>标的：{{ analysisContext.stock_symbol || '-' }}</span>
              <span style="margin-left:8px">模型建议：{{ analysisContext.recommendation || '-' }}</span>
            </div>
          </div>
        </el-alert>
      </div>

      <el-form label-width="90px">
        <el-form-item label="方向">
          <el-radio-group v-model="order.side">
            <el-radio-button value="buy">买入</el-radio-button>
            <el-radio-button value="sell">卖出</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="代码">
          <el-input v-model="order.code" placeholder="A股: 600519 | 港股: 0700 | 美股: AAPL" @input="detectMarket" />
        </el-form-item>
        <el-form-item label="市场" v-if="detectedMarket">
          <div>
            <el-tag v-if="detectedMarket === 'CN'" type="success">🇨🇳 A股市场 (CNY)</el-tag>
            <el-tag v-else-if="detectedMarket === 'HK'" type="warning">🇭🇰 港股市场 (HKD)</el-tag>
            <el-tag v-else-if="detectedMarket === 'US'" type="info">🇺🇸 美股市场 (USD)</el-tag>
            <div class="t0-hint">
              <span v-if="detectedMarket === 'CN'">💡 A股T+1，今天买入明天可卖</span>
              <span v-else-if="detectedMarket === 'HK'">💡 港股T+0，买入后立即可卖</span>
              <span v-else-if="detectedMarket === 'US'">💡 美股T+0，买入后立即可卖 | 零佣金</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="order.qty" :min="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialog=false">取消</el-button>
        <el-button type="primary" @click="submitOrder">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CreditCard, Refresh, Plus, Delete, ArrowRight } from '@element-plus/icons-vue'
import { paperApi } from '@/api/paper'
import { analysisApi } from '@/api/analysis'
import { vibeApi, type MarketSynthesis } from '@/api/vibe'
import { monitorApi, type StrategyMonitorStatus } from '@/api/monitor'
import { fmtPct } from '@/utils/format'

// 路由与初始化
const route = useRoute()
const router = useRouter()

const orderDialog = ref(false)
const order = ref({ side: 'buy', code: '', qty: 100 })
const detectedMarket = ref<string>('')

// ── 今日买卖信号（来自综合研判：计划/候选 + 持仓卖点评估） ──
const syn = ref<MarketSynthesis | null>(null)
const synLoading = ref(false)

// 常用策略监控状态（type=strategy 规则由 /api/monitor/strategies/status 独立提供，
// /api/monitor/rules 刻意跳过 strategy 类型，不能用于推断策略启用状态）
const strategyStatus = ref<StrategyMonitorStatus[]>([])
const monitorStatus = computed(() => {
  const enabled = (strategyStatus.value || []).filter(s => s.enabled)
  const strategyNames = enabled.map(s => s.name || s.strategy_id).filter(Boolean)
  return { strategyNames }
})

// 信号清单直接采用综合研判结果（三买三卖体系已废弃，不再按监控开关隐藏信号）
const buys = computed(() => syn.value?.buys || [])
const sells = computed(() => syn.value?.sells || [])

/** 是否真正卖出内容（sell_pct>0 为实质卖出建议；=0 的「继续持有」仅做持仓评估展示，非卖出） */
function isHoldSell(row: any): boolean {
  return !(Number(row?.sell_pct || 0) > 0)
}

/** 持仓卖出排序：真实卖出信号在前，非卖出的「继续持有」置灰并排在最低部 */
const realSells = computed(() => (sells.value || []).filter(s => !isHoldSell(s)))
const holdSells = computed(() => (sells.value || []).filter(isHoldSell))
const sortedSells = computed(() => [...realSells.value, ...holdSells.value])

/** 置灰行样式（非卖出内容） */
function sellRowClass({ row }: any): string {
  return isHoldSell(row) ? 'sell-row-hold' : ''
}

/** 买入信号来源徽标（来源类型，信号名由顶部 sig-badge 单独展示，避免重复） */
function buySource(b: any): { type: string; text: string; full: string } {
  if (b?.source?.type === 'strategy') {
    return { type: 'strategy', text: '常用策略', full: b.source.label || '' }
  }
  const st = b?.source?.type
  if (st === 'plan') return { type: 'signal', text: '当日计划', full: b?.source?.label || '' }
  if (st === 'candidate') return { type: 'signal', text: '候选池', full: b?.source?.label || '' }
  if (st === 'signal_verified') {
    // 已验证信号均属三买三卖体系（B1/B2/B3），徽章统一为"三买三卖"
    return { type: 'signal', text: '三买三卖', full: b?.source?.label || '' }
  }
  return { type: 'signal', text: b?.signal_label || st || '计划', full: b?.source?.label || '' }
}

/** 卖出信号来源徽标（S卖点属三买三卖体系，其余为持仓评估/仓位管理） */
function sellSource(s: any): { type: string; text: string } {
  const text = `${s?.advice || ''} ${s?.advice_label || ''}`
  if (/S\d|SafetyNet|TrailingStop|移动止损/.test(text)) {
    return { type: 'signal', text: '三买三卖·卖点' }
  }
  if (s?.source?.type === 'position_eval') {
    return { type: 'position', text: '持仓评估' }
  }
  return { type: 'position', text: '仓位管理' }
}

// 信号单快速下单
function buyFromSignal(row: any) {
  if (!row?.code) return
  ;(order.value as any).analysis_id = null
  order.value.side = 'buy'
  order.value.code = row.code
  order.value.qty = 100
  detectMarket()
  orderDialog.value = true
}

function sellFromSignal(row: any) {
  if (!row?.code) return
  ;(order.value as any).analysis_id = null
  order.value.side = 'sell'
  order.value.code = row.code
  order.value.qty = Math.max(1, Number(row.quantity || 0))
  detectMarket()
  orderDialog.value = true
}

const synAsOf = computed(() => {
  const s = syn.value?.as_of
  if (!s) return '—'
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    const p = (n: number) => String(n).padStart(2, '0')
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  } catch {
    return s
  }
})

const pctClass = (v: number | null | undefined) => {
  if (v == null) return 'flat'
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

async function loadStrategyStatus() {
  try {
    const res: any = await monitorApi.strategyMonitorStatus()
    const items: StrategyMonitorStatus[] =
      (res as any)?.data?.items ?? (res as any)?.items ?? []
    strategyStatus.value = items || []
  } catch (e) {
    console.warn('[PaperTrading] 常用策略监控状态加载失败（不影响信号展示）', e)
    strategyStatus.value = []
  }
}

async function loadSynthesis() {
  synLoading.value = true
  try {
    const res: any = await vibeApi.getSynthesis()
    if (res?.code === 401) {
      // 登录过期：不打断交易操作，静默跳过
      return
    }
    syn.value = res || null
  } catch (e) {
    console.warn('[PaperTrading] 买卖清单加载失败', e)
  } finally {
    synLoading.value = false
  }
}

/** 刷新信号 = 重新加载监控状态 + 综合研判（一次，避免频繁触发 AI 重算） */
function loadAll() {
  loadStrategyStatus()
  loadSynthesis()
}

// 跳转监控中心（history 路由，勿用 href="#/..."）
function goMonitorCenter() {
  router.push('/stock-alerts')
}

// 分析上下文
const analysisContext = ref<any | null>(null)
const analysisLoading = ref(false)

// 检测市场类型
function detectMarket() {
  const code = order.value.code.trim().toUpperCase()
  if (!code) {
    detectedMarket.value = ''
    return
  }
  // 美股：纯字母
  if (/^[A-Z]+$/.test(code)) {
    detectedMarket.value = 'US'
    return
  }
  // 港股：4-5位数字或.HK后缀
  if (/^\d{4,5}$/.test(code) || code.endsWith('.HK')) {
    detectedMarket.value = 'HK'
    return
  }
  // A股：6位数字
  if (/^\d{6}$/.test(code)) {
    detectedMarket.value = 'CN'
    return
  }
  detectedMarket.value = 'CN'
}

function openOrderDialog() {
  orderDialog.value = true
}

async function submitOrder() {
  try {
    const payload: any = { side: order.value.side as 'buy' | 'sell', code: order.value.code, quantity: Number(order.value.qty) }
    if ((order.value as any).analysis_id) payload.analysis_id = (order.value as any).analysis_id
    const res = await paperApi.placeOrder(payload)
    if (res.success) {
      ElMessage.success('下单成功')
      orderDialog.value = false
      loadAll()
    } else {
      ElMessage.error(res.message || '下单失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '下单失败')
  }
}

async function confirmReset() {
  try {
    await ElMessageBox.confirm('将清空所有订单与持仓，并重置账户为初始现金，确认重置？', '重置账户', { type: 'warning' })
    const res = await paperApi.resetAccount()
    if (res.success) {
      ElMessage.success('账户已重置')
    }
  } catch (e) {
    // 取消或失败
  }
}

// 查看报告详情
function viewReport(analysisId: string) {
  if (!analysisId) return
  router.push({ name: 'ReportDetail', params: { id: analysisId } })
}

async function fetchAnalysisContext(analysisId: string) {
  try {
    analysisLoading.value = true
    analysisContext.value = null
    const res = await analysisApi.getResult(analysisId)
    analysisContext.value = res as any
  } catch (e) {
    // 忽略错误，仅用于展示
  } finally {
    analysisLoading.value = false
  }
}

onMounted(() => {
  let hasPrefill = false
  const qCode = String(route.query.code || '').trim()
  if (qCode) {
    order.value.code = qCode
    hasPrefill = true
  }
  const qSide = String(route.query.side || '').trim().toLowerCase()
  if (qSide === 'buy' || qSide === 'sell') {
    order.value.side = qSide as 'buy' | 'sell'
    hasPrefill = true
  }
  const qQty = Number(route.query.qty || route.query.quantity || 0)
  if (!Number.isNaN(qQty) && qQty > 0) {
    order.value.qty = Math.round(qQty)
    hasPrefill = true
  }
  const qAnalysisId = String(route.query.analysis_id || '').trim()
  if (qAnalysisId) {
    ;(order as any).analysis_id = qAnalysisId
    fetchAnalysisContext(qAnalysisId)
    hasPrefill = true
  }
  if (hasPrefill) {
    orderDialog.value = true
  }
  // 监控状态 + 买卖信号（一次，避免频繁触发综合研判 AI 重算）
  loadAll()
})
</script>

<style scoped>
.paper-trading {
  padding: 24px;
}

/* ═══════════ ① 今日买卖信号 ═══════════ */
.signal-shell {
  margin-top: 20px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  padding: 18px 20px 14px;
  animation: rise-in .35s ease both;
}
.signal-hd {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.signal-hd-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.signal-title-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.signal-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--el-text-color-primary);
  letter-spacing: .4px;
}
.signal-asof {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: var(--app-font-mono);
}
.signal-hd-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 监控状态条 */
.moni-bar {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.moni-strategy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
}
.moni-strategy.has {
  border-color: rgba(64, 158, 255, .35);
  background: rgba(64, 158, 255, .06);
}
.moni-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.moni-tag {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-color-primary);
  background: rgba(64, 158, 255, .1);
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.moni-empty {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.moni-desc {
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

/* 信号双栏 */
.list-wrap {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
  gap: 16px;
}
.ls-col {
  min-width: 0;
  padding: 14px 14px 10px;
  border-radius: var(--app-radius);
  background: var(--el-fill-color-lighter);
}
.ls-buy {
  box-shadow: inset 3px 0 0 var(--app-up);
}
.ls-sell {
  box-shadow: inset 3px 0 0 var(--app-down);
}
.col-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.col-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.col-empty-note {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.col-note {
  margin: 10px 2px 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-placeholder);
}
.dot { width: 9px; height: 9px; border-radius: 50%; }
.dot-buy { background: var(--app-up); }
.dot-sell { background: var(--app-down); }

/* ── 建议买入 · 富信息卡片 ── */
.buy-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.buy-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  background: var(--el-fill-color-blank);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow .2s ease, transform .2s ease;
}
.buy-card:hover {
  box-shadow: 0 6px 18px rgba(0, 0, 0, .06);
  transform: translateY(-1px);
}
.bc-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.bc-stk {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.bc-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  text-decoration: none;
  white-space: nowrap;
}
.bc-name:hover { color: var(--el-color-primary); }
.bc-code {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
}
.bc-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.sig-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--app-up);
  background: rgba(245, 108, 108, .1);
  border: 1px solid rgba(245, 108, 108, .3);
  border-radius: 6px;
  padding: 1px 7px;
}
.bc-price {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
  white-space: nowrap;
}
.bc-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bc-label {
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}
.bc-val {
  font-family: var(--app-font-mono);
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.bc-val.up { color: var(--app-up); }
.bc-val.down { color: var(--app-down); }
.bc-val.flat { color: var(--el-text-color-regular); }
.bc-dist { margin-left: auto; }
.bc-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.bc-state {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  color: var(--app-up);
  background: rgba(245, 108, 108, .1);
  border-radius: 999px;
  padding: 2px 8px;
  flex-shrink: 0;
}
.bc-state.warn {
  color: var(--el-color-warning);
  background: rgba(230, 162, 60, .1);
}
.bc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.bc-advice {
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 持仓卖出表 ── */
.ms-table {
  background: transparent;
}
.ms-table :deep(.el-table__row) { cursor: default; }
.ms-table :deep(th.el-table__cell) {
  color: var(--el-text-color-secondary);
  font-weight: 600;
  background: var(--el-fill-color-lighter);
}
/* 非卖出内容置灰（继续持有类持仓评估，排在最低部） */
.ms-table :deep(.sell-row-hold) {
  opacity: .45;
  background: var(--el-fill-color-lighter);
}
.ms-table :deep(.sell-row-hold .el-button.is-disabled) {
  opacity: .55;
}
.hold-hint {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.stk {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.stk-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  text-decoration: none;
}
.stk-name:hover { color: var(--el-color-primary); }
.stk-code {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.money {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.pct {
  font-family: var(--app-font-mono);
  font-size: 12px;
  font-weight: 600;
}
.pct.up { color: var(--app-up); }
.pct.down { color: var(--app-down); }
.pct.flat { color: var(--el-text-color-regular); }
.advice {
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
}
.advice-label {
  color: var(--el-text-color-primary);
  margin-right: 4px;
}

/* 来源徽标 */
.src-tag {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}
.src-signal {
  color: var(--app-up);
  border-color: rgba(245, 108, 108, .35);
  background: rgba(245, 108, 108, .06);
}
.src-strategy {
  color: var(--el-color-primary);
  border-color: rgba(64, 158, 255, .35);
  background: rgba(64, 158, 255, .06);
}
.src-position {
  color: #909399;
}

/* 快捷下单按钮（买入红 / 卖出绿，A股惯例） */
.act {
  height: 26px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  color: #fff;
  border-radius: 6px;
  transition: transform .15s ease, box-shadow .15s ease;
  flex-shrink: 0;
}
.act:hover { transform: translateY(-1px); }
.act-buy { background: var(--app-up); }
.act-buy:hover { box-shadow: 0 3px 8px rgba(245, 108, 108, .35); }
.act-sell { background: var(--app-down); }
.act-sell:hover { box-shadow: 0 3px 8px rgba(103, 194, 58, .35); }

/* 来源脚注 */
.signal-foot {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.foot-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.foot-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.foot-dot-buy { background: var(--app-up); }
.foot-dot-sell { background: var(--app-down); }

.sync-tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

@keyframes rise-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.t0-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.analysis-context {
  margin-bottom: 12px;
}

/* ═══════════ 响应式 ═══════════ */
@media (max-width: 1200px) {
  .list-wrap { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .paper-trading { padding: 12px; }
  .signal-shell { padding: 14px; }
  .bc-price { flex-wrap: wrap; }
  .bc-dist { margin-left: 0; }
}
</style>