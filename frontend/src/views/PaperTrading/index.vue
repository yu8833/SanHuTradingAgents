<template>
  <div class="today-page app-page">
    <!-- 页头 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><List /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">今日待办</h2>
          <p class="page-hero-sub">买 · 盯 · 卖 —— 每条都直接给结论，理由可展开查看</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">{{ tradeDateLabel }}</span>
        <span class="page-hero-tag">{{ sessionLabel }}</span>
        <el-button :icon="Refresh" text size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openOrderDialog">下市场单</el-button>
      </div>
    </div>

    <!-- 环境结论：熊市阴跌 · 高潮期 · 0~2 成（观察仓） -->
    <section v-if="data" class="env-banner" :class="`is-${data.environment.gate}`">
      <div class="env-top">
        <span class="env-verdict">{{ data.environment.verdict }}</span>
        <div class="env-verdicts">
          <div v-for="(layer, i) in envLayers" :key="layer.key" class="ev">
            <span v-if="i" class="ev-sep">·</span>
            <b class="ev-value" :class="`tone-${layer.data.tone}`">{{ layer.data.value }}</b>
            <span class="ev-label">{{ layer.label }}</span>
          </div>
        </div>
        <el-button text class="env-toggle" @click="toggle('env')">
          {{ expanded.env ? '收起说明' : '为什么？该怎么做？' }}
        </el-button>
      </div>
      <p class="env-hint">{{ data.environment.position.desc }}</p>
      <el-alert
        v-if="data.environment.degraded"
        :title="data.environment.degrade_note"
        type="warning"
        :closable="false"
        show-icon
        class="env-degrade"
      />

      <div v-if="expanded.env" class="env-detail">
        <div class="env-layers">
          <div v-for="layer in envLayers" :key="layer.key" class="env-layer">
            <div class="el-hd">
              <span class="el-label">{{ layer.label }}</span>
              <b class="el-value" :class="`tone-${layer.data.tone}`">{{ layer.data.value }}</b>
            </div>
            <p class="el-desc">{{ layer.data.desc }}</p>
            <ul class="el-points">
              <li v-for="(p, i) in layer.data.points" :key="i">{{ p }}</li>
            </ul>
          </div>
        </div>

        <div class="env-action-title">这个环境下，买卖这么做</div>
        <div class="env-actions">
          <div v-for="a in data.environment.actions" :key="a.side" class="env-action" :class="`side-${a.side}`">
            <span class="ea-badge">{{ a.side }}</span>
            <div class="ea-body">
              <b>{{ a.title }}</b>
              <p>{{ a.text }}</p>
            </div>
          </div>
        </div>
        <p class="env-foot">{{ data.environment.footnote }}</p>
      </div>
    </section>

    <!-- 一句话结论 -->
    <div v-if="data" class="today-brief">
      <span class="tb-item tb-buy">买 <b>{{ data.buy.count }}</b> 只已触发</span>
      <span class="tb-item tb-watch">盯 <b>{{ data.watch.count }}</b> 只</span>
      <span class="tb-item tb-sell">卖 <b>{{ data.sell.exit_count }}</b> 只需离场</span>
      <span class="tb-note">可用现金 ¥{{ fmtMoney(data.account.cash_cny) }}</span>
    </div>

    <el-skeleton v-if="loading && !data" :rows="8" animated class="today-skeleton" />

    <template v-else-if="data">
      <!-- ═══════════ 买 ═══════════ -->
      <section class="todo-block blk-buy">
        <div class="blk-hd">
          <span class="blk-badge">买</span>
          <h3 class="blk-title">
            <template v-if="data.buy.count">{{ data.buy.count }} 只已触发 → 代码 / 价格 / 仓位 / 止损（照做即可）</template>
            <template v-else>今日无 B2 触发 → 不买，等信号</template>
          </h3>
          <span class="blk-hint">右侧确认：放量 + 中阳 + 站上 MA55/MA60</span>
        </div>

        <div v-if="data.buy.items.length" class="card-list">
          <article v-for="b in data.buy.items" :key="b.code" class="todo-card">
            <div class="card-hd">
              <div class="card-stk">
                <router-link class="stk-name" :to="`/stocks/${b.code}`">{{ b.name }}</router-link>
                <span class="stk-code">{{ b.code }}</span>
                <span v-if="b.industry" class="stk-industry">{{ b.industry }}</span>
              </div>
              <div class="card-tags">
                <span class="tag tag-signal">{{ b.signal_label }}</span>
                <span v-if="b.blocked" class="tag tag-exit">环境红灯 · 暂停</span>
                <span v-if="b.held" class="tag tag-held">已持有</span>
                <span v-if="b.trigger_date" class="tag">{{ b.trigger_date }} 触发</span>
              </div>
            </div>

            <div class="metric-row">
              <div class="metric">
                <span class="m-label">现价</span>
                <span class="m-val">{{ b.current_price }}</span>
              </div>
              <div class="metric">
                <span class="m-label">触发价</span>
                <span class="m-val">{{ b.trigger_price ?? '—' }}</span>
              </div>
              <div class="metric">
                <span class="m-label">建议仓位</span>
                <span class="m-val">{{ (b.position_pct * 100).toFixed(1) }}%</span>
                <span class="m-sub">{{ b.suggest_qty }} 股 · ¥{{ fmtMoney(b.suggest_amount) }}</span>
              </div>
              <div class="metric">
                <span class="m-label">止损</span>
                <span class="m-val down">{{ b.stop_loss_price }}</span>
              </div>
            </div>

            <div class="card-ft">
              <span class="card-summary">{{ b.summary }}</span>
              <div class="card-acts">
                <el-button text size="small" @click="toggle('buy:' + b.code)">
                  {{ expanded['buy:' + b.code] ? '收起理由' : '为什么？' }}
                </el-button>
                <el-button class="act act-buy" size="small" :disabled="b.blocked" @click="quickOrder(b.code, 'buy', b.suggest_qty || 100, b.name, { stop_loss_price: b.stop_loss_price, take_profit_price: b.take_profit_price })">
                  {{ b.blocked ? '闸门红灯 · 暂停' : '照做买入' }}
                </el-button>
              </div>
            </div>

            <ul v-if="expanded['buy:' + b.code]" class="reason-list">
              <li v-for="(r, i) in b.reasons" :key="i" :class="`k-${r.kind}`">{{ r.text }}</li>
            </ul>
          </article>
        </div>
        <el-empty v-else description="暂无已触发的 B2 买点，今天不买" :image-size="56" />
      </section>

      <!-- ═══════════ 盯 ═══════════ -->
      <section class="todo-block blk-watch">
        <div class="blk-hd">
          <span class="blk-badge">盯</span>
          <h3 class="blk-title">
            <template v-if="data.watch.count">
              {{ data.watch.count }} 只待触发{{ data.watch.near_count ? `（${data.watch.near_count} 只已进入 2% 临近区）` : '' }} → 明天重点看这几只
            </template>
            <template v-else>观察池暂无待触发标的</template>
          </h3>
          <span class="blk-hint">B1 左侧信号 ∩ 积累区四条件，只观察，不提前埋伏</span>
        </div>

        <div v-if="data.watch.items.length" class="watch-list">
          <div v-for="w in data.watch.items" :key="w.code" class="watch-row" :class="{ near: w.distance_to_trigger >= -0.02 }">
            <div class="wr-main">
              <div class="card-stk">
                <router-link class="stk-name" :to="`/stocks/${w.code}`">{{ w.name }}</router-link>
                <span class="stk-code">{{ w.code }}</span>
                <span v-if="w.industry" class="stk-industry">{{ w.industry }}</span>
              </div>
              <div class="wr-price">
                <span class="m-val">{{ w.current_price }}</span>
                <span class="wr-arrow">→</span>
                <span class="wr-trigger">{{ w.trigger_price }}</span>
                <span class="wr-dist" :class="{ near: w.distance_to_trigger >= -0.02 }">
                  距触发 {{ (w.to_trigger_pct * 100).toFixed(2) }}%
                </span>
              </div>
            </div>
            <div class="wr-ft">
              <span class="card-summary">{{ w.summary }}</span>
              <el-button text size="small" @click="toggle('watch:' + w.code)">
                {{ expanded['watch:' + w.code] ? '收起理由' : '为什么是它？' }}
              </el-button>
            </div>
            <ul v-if="expanded['watch:' + w.code]" class="reason-list">
              <li v-for="(r, i) in w.reasons" :key="i" :class="`k-${r.kind}`">{{ r.text }}</li>
            </ul>
          </div>
        </div>
        <el-empty v-else description="观察池暂无待触发标的" :image-size="56" />
      </section>

      <!-- ═══════════ 卖 ═══════════ -->
      <section class="todo-block blk-sell">
        <div class="blk-hd">
          <span class="blk-badge">卖</span>
          <h3 class="blk-title">
            <template v-if="data.sell.exit_count">{{ data.sell.exit_count }} 只需离场 → 代码 / 原因 / 参考价</template>
            <template v-else>持仓无离场信号 → 继续持有</template>
          </h3>
          <span class="blk-hint">
            统一离场：止损 8% / 假突破 / S1-S3 卖点 / 跌破 MA5 / 止盈 / 30 日时间止损
          </span>
        </div>

        <div v-if="data.sell.items.length" class="card-list">
          <article v-for="s in data.sell.items" :key="s.code" class="todo-card" :class="{ warn: s.state === 'warn' }">
            <div class="card-hd">
              <div class="card-stk">
                <router-link class="stk-name" :to="`/stocks/${s.code}`">{{ s.name }}</router-link>
                <span class="stk-code">{{ s.code }}</span>
                <span class="tag" :class="s.source === 'cockpit' ? 'tag-cockpit' : 'tag-paper'">
                  {{ s.source === 'cockpit' ? '纪律持仓' : '模拟持仓' }}
                </span>
              </div>
              <div class="card-tags">
                <span class="tag" :class="s.state === 'exit' ? 'tag-exit' : 'tag-warn'">
                  {{ s.state === 'exit' ? '需离场' : '预警' }}
                </span>
                <span v-if="s.pnl_pct != null" class="tag" :class="s.pnl_pct >= 0 ? 'tag-up' : 'tag-down'">
                  {{ s.pnl_pct >= 0 ? '+' : '' }}{{ s.pnl_pct.toFixed(2) }}%
                </span>
              </div>
            </div>

            <div class="metric-row">
              <div class="metric">
                <span class="m-label">动作</span>
                <span class="m-val">{{ s.advice_label || s.advice }}</span>
              </div>
              <div class="metric">
                <span class="m-label">参考价</span>
                <span class="m-val">{{ s.reference_price ?? '—' }}</span>
              </div>
              <div class="metric">
                <span class="m-label">现价</span>
                <span class="m-val">{{ s.current_price ?? '—' }}</span>
              </div>
              <div class="metric" v-if="s.state === 'exit'">
                <span class="m-label">卖出比例</span>
                <span class="m-val">{{ Math.round((s.sell_pct || 0) * 100) }}%</span>
              </div>
            </div>

            <div class="card-ft">
              <span class="card-summary">
                {{ s.summary || (s.state === 'exit' ? '按纪律离场' : '今日仅预警，暂不卖出') }}
              </span>
              <div class="card-acts">
                <el-button text size="small" @click="toggle('sell:' + s.code)">
                  {{ expanded['sell:' + s.code] ? '收起原因' : '看原因' }}
                </el-button>
                <el-button
                  v-if="s.source === 'paper' && s.state === 'exit'"
                  class="act act-sell"
                  size="small"
                  @click="quickOrder(s.code, 'sell', Math.round((s.quantity || 0) * (s.sell_pct || 1)) || s.quantity || 1, s.name)"
                >
                  按建议卖出
                </el-button>
                <el-button
                  v-else-if="s.state === 'exit'"
                  class="act act-sell"
                  size="small"
                  @click="closeCockpit(s)"
                >
                  了结离场
                </el-button>
              </div>
            </div>

            <ul v-if="expanded['sell:' + s.code]" class="reason-list">
              <li v-for="(r, i) in s.reasons" :key="i" :class="`k-${r.kind}`">{{ r.text }}</li>
            </ul>
          </article>
        </div>
        <el-empty v-else description="持仓暂无离场信号，继续按纪律持有" :image-size="56" />

        <p v-if="data.sell.hold_count" class="blk-foot">
          其余 {{ data.sell.hold_count }} 只持仓未触发任何离场条件，继续持有；盘中每 15 分钟统一扫描一次。
        </p>
      </section>

      <p class="page-foot">
        <el-icon><InfoFilled /></el-icon>
        买 / 盯 来自 B1 ∩ 积累区观察池与 B2 突破扫描；卖 来自统一离场引擎（与持仓追踪同一份结论）。
        盘中每 2 分钟自动刷新，页面切走暂停。
      </p>
    </template>

    <!-- 下市场单 -->
    <el-dialog v-model="orderDialog" title="下市场单" width="480px">
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
          <StockCodeAutocomplete
            v-model="order.code"
            :markets="['CN', 'HK', 'US']"
            placeholder="A股: 600519 | 港股: 0700 | 美股: AAPL"
            @select="onOrderStockPicked"
          />
        </el-form-item>
        <el-form-item label="名称" v-if="orderName">
          <span style="font-weight:600">{{ orderName }}</span>
          <span style="color:#909399;font-size:12px;margin-left:8px;">所选标的，下单前请核对</span>
        </el-form-item>
        <el-form-item label="市场" v-if="detectedMarket">
          <div>
            <el-tag v-if="detectedMarket === 'CN'" type="success">A股市场 (CNY)</el-tag>
            <el-tag v-else-if="detectedMarket === 'HK'" type="warning">港股市场 (HKD)</el-tag>
            <el-tag v-else-if="detectedMarket === 'US'" type="info">美股市场 (USD)</el-tag>
            <div class="t0-hint">
              <span v-if="detectedMarket === 'CN'">A股 T+1，今天买入明天可卖</span>
              <span v-else-if="detectedMarket === 'HK'">港股 T+0，买入后立即可卖</span>
              <span v-else-if="detectedMarket === 'US'">美股 T+0，买入后立即可卖</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="order.qty" :min="1" :step="preview?.lot_size || 1" />
          <span v-if="preview" class="qty-hint">
            <template v-if="order.side === 'buy'">最大可买 {{ preview.max_qty }} 股</template>
            <template v-else>可用持仓 {{ preview.available_qty }} 股</template>
            · 每手 {{ preview.lot_size }} 股
          </span>
        </el-form-item>
        <el-form-item label="预览" v-if="order.code">
          <div class="order-preview" v-loading="previewLoading">
            <template v-if="preview">
              <div class="op-row"><span>最新价</span><b>{{ preview.price ? `${preview.price} ${preview.currency}` : '—' }}</b></div>
              <div class="op-row"><span>预估金额</span><b>{{ fmtMoney(preview.notional) }}</b></div>
              <div class="op-row"><span>预估费用</span><b>{{ fmtMoney(preview.fee) }}</b></div>
              <div class="op-row">
                <span>{{ order.side === 'buy' ? '预估总支出' : '预估净收入' }}</span>
                <b>{{ fmtMoney(order.side === 'buy' ? preview.total_cost : preview.net_proceeds) }}</b>
              </div>
              <el-alert
                v-for="err in preview.errors"
                :key="err"
                :title="err"
                type="error"
                :closable="false"
                show-icon
                class="op-alert"
              />
            </template>
            <span v-else-if="!previewLoading" class="op-empty">输入完整信息后显示预估</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialog = false">取消</el-button>
        <el-button type="primary" :disabled="submitDisabled" :loading="submitting" @click="submitOrder">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { List, Refresh, Plus, InfoFilled } from '@element-plus/icons-vue'
import { todayApi, type TodayActions, type TodaySellItem } from '@/api/today'
import { paperApi, type OrderPreview } from '@/api/paper'
import { cockpitApi } from '@/api/cockpit'
import { analysisApi } from '@/api/analysis'

const route = useRoute()
const router = useRouter()

// ── 今日待办数据 ──
const data = ref<TodayActions | null>(null)
const loading = ref(false)
const expanded = ref<Record<string, boolean>>({})

function toggle(key: string) {
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

const tradeDateLabel = computed(() => {
  if (!data.value?.trade_date) return '—'
  const w = ['日', '一', '二', '三', '四', '五', '六'][new Date(data.value.trade_date).getDay()]
  return `${data.value.trade_date}（周${w}）`
})

const sessionLabel = computed(() => {
  const s = data.value?.session
  if (!s) return '—'
  if (s.is_intraday) return '盘中 · 实时价'
  return s.quote_as_of ? `收盘快照 ${s.quote_as_of}` : '非交易时段'
})

const envLayers = computed(() => {
  const e = data.value?.environment
  if (!e) return []
  return [
    { key: 'portrait', label: '市场画像', data: e.portrait },
    { key: 'phase', label: '情绪阶段', data: e.phase },
    { key: 'position', label: '仓位纪律', data: e.position }
  ]
})

async function load() {
  loading.value = true
  try {
    data.value = await todayApi.getActions()
  } catch (e: any) {
    if (e?.code === 401) return
    ElMessage.error(e?.message || '今日待办加载失败')
  } finally {
    loading.value = false
  }
}

// 盘中每 2 分钟刷新（页面隐藏时暂停）
const POLL_MS = 120000
let timer: ReturnType<typeof setInterval> | null = null
function startPolling() {
  if (timer) return
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') load()
  }, POLL_MS)
}
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function onVisibility() {
  if (document.visibilityState === 'visible') load()
}

// ── 下单 ──
const orderDialog = ref(false)
const order = ref({ side: 'buy', code: '', qty: 100 })
const orderMeta = ref<{ stop_loss_price?: number; take_profit_price?: number; stock_name?: string }>({})
const detectedMarket = ref<string>('')
const orderName = ref('')

watch(() => order.value.code, (v) => {
  detectMarket()
  if (!v) orderName.value = ''
})

function onOrderStockPicked(stock: any) {
  if (stock?.name) orderName.value = stock.name
  detectMarket()
}

function quickOrder(
  code: string,
  side: 'buy' | 'sell',
  qty: number,
  name?: string,
  meta?: { stop_loss_price?: number; take_profit_price?: number }
) {
  ;(order.value as any).analysis_id = null
  order.value.side = side
  order.value.code = code
  order.value.qty = Math.max(1, Math.round(qty || 1))
  orderName.value = name || ''
  orderMeta.value = side === 'buy' ? { ...meta, stock_name: name } : {}
  detectMarket()
  orderDialog.value = true
}

function openOrderDialog() {
  order.value.code = ''
  orderName.value = ''
  orderMeta.value = {}
  preview.value = null
  orderDialog.value = true
}

/** 纪律持仓了结（驾驶舱账本，不经过模拟交易下单） */
async function closeCockpit(item: TodaySellItem) {
  if (!item.position_id) return
  const price = item.current_price ?? item.reference_price
  if (!price) {
    ElMessage.warning('暂无现价，无法了结')
    return
  }
  try {
    await ElMessageBox.confirm(
      `按参考价 ${price} 了结 ${item.name || item.code}？原因：${item.reasons?.[0]?.text || '纪律离场'}`,
      '了结持仓',
      { type: 'warning' }
    )
    await cockpitApi.closePosition(item.position_id, Number(price))
    ElMessage.success(`已了结 ${item.name || item.code}`)
    load()
  } catch {
    // 取消
  }
}

function detectMarket() {
  const code = order.value.code.trim().toUpperCase()
  if (!code) {
    detectedMarket.value = ''
    return
  }
  if (/^[A-Z]+$/.test(code)) {
    detectedMarket.value = 'US'
    return
  }
  if (/^\d{4,5}$/.test(code) || code.endsWith('.HK')) {
    detectedMarket.value = 'HK'
    return
  }
  if (/^\d{6}$/.test(code)) {
    detectedMarket.value = 'CN'
    return
  }
  detectedMarket.value = 'CN'
}

const preview = ref<OrderPreview | null>(null)
const previewLoading = ref(false)
const submitting = ref(false)
let previewTimer: ReturnType<typeof setTimeout> | null = null

const submitDisabled = computed(() => {
  if (!order.value.code.trim()) return true
  if (previewLoading.value || !preview.value) return true
  return preview.value.errors.length > 0
})

const fmtMoney = (v: number | null | undefined) => {
  if (v == null) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function fetchPreview() {
  const code = order.value.code.trim()
  if (!code || !orderDialog.value) {
    preview.value = null
    return
  }
  previewLoading.value = true
  try {
    const res: any = await paperApi.previewOrder({
      side: order.value.side as 'buy' | 'sell',
      code,
      quantity: Number(order.value.qty) || 0
    })
    preview.value = (res?.data || null) as OrderPreview | null
  } catch {
    preview.value = null
  } finally {
    previewLoading.value = false
  }
}

watch(
  [() => order.value.code, () => order.value.side, () => order.value.qty, orderDialog],
  () => {
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = setTimeout(fetchPreview, 300)
  }
)

async function submitOrder() {
  if (submitDisabled.value) return
  try {
    submitting.value = true
    const payload: any = { side: order.value.side as 'buy' | 'sell', code: order.value.code, quantity: Number(order.value.qty) }
    if ((order.value as any).analysis_id) payload.analysis_id = (order.value as any).analysis_id
    if (order.value.side === 'buy') Object.assign(payload, orderMeta.value)
    const res: any = await paperApi.placeOrder(payload)
    if (res.success) {
      const placed = res?.data?.order
      const receipt = placed ? `已成交 ${placed.quantity} 股 @ ${placed.price}` : '下单成功'
      ElNotification({
        title: '成交回执',
        message: `${receipt}（点击查看持仓）`,
        type: 'success',
        duration: 6000,
        onClick: () => router.push('/portfolio')
      })
      orderDialog.value = false
      load()
    } else {
      ElMessage.error(res.message || '下单失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '下单失败')
  } finally {
    submitting.value = false
  }
}

// 分析上下文
const analysisContext = ref<any | null>(null)
const analysisLoading = ref(false)

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
  } catch {
    // 仅用于展示
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
  if (hasPrefill) orderDialog.value = true

  load()
  startPolling()
  document.addEventListener('visibilitychange', onVisibility)
})

onUnmounted(() => {
  if (previewTimer) clearTimeout(previewTimer)
  stopPolling()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<style scoped>
.today-page { padding: 0 0 24px; }

/* 环境结论横幅 */
.env-banner {
  margin-top: 14px;
  padding: 14px 18px;
  border-radius: var(--app-radius-lg);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid var(--el-border-color);
  background: var(--el-fill-color-lighter);
}
.env-banner.is-red {
  border-left-color: var(--app-down);
  background: linear-gradient(90deg, #fef2f2 0%, #fff 62%);
}
.env-banner.is-yellow {
  border-left-color: var(--el-color-warning);
  background: linear-gradient(90deg, #fffbeb 0%, #fff 62%);
}
.env-banner.is-green {
  border-left-color: var(--app-up);
  background: linear-gradient(90deg, #f0fdf4 0%, #fff 62%);
}
.env-top {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.env-verdict {
  font-size: 13px;
  font-weight: 800;
  color: #fff;
  padding: 4px 12px;
  border-radius: 6px;
  white-space: nowrap;
}
.is-red .env-verdict { background: var(--app-down); }
.is-yellow .env-verdict { background: var(--el-color-warning); }
.is-green .env-verdict { background: var(--app-up); }

.env-verdicts {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.ev {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.ev-sep {
  color: var(--el-text-color-placeholder);
  font-size: 16px;
  margin: 0 2px;
}
.ev-value {
  font-size: 19px;
  font-weight: 800;
  letter-spacing: .3px;
  font-family: var(--app-font-mono);
}
.ev-label {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.tone-down { color: var(--app-down); }
.tone-up { color: var(--app-up); }
.tone-warn { color: var(--el-color-warning); }
.tone-flat { color: var(--el-text-color-primary); }
.env-toggle { margin-left: auto; }

.env-hint {
  margin-top: 8px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.env-degrade { margin-top: 8px; }

.env-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color);
}
.env-layers {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.env-layer {
  border-radius: 8px;
  background: rgba(255, 255, 255, .75);
  border: 1px solid var(--el-border-color-lighter);
  padding: 10px 12px;
}
.el-hd {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.el-label {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.el-value {
  font-size: 14px;
  font-weight: 800;
}
.el-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.el-points {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.el-points li {
  position: relative;
  padding-left: 11px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.el-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--el-border-color);
}

.env-action-title {
  margin: 14px 0 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.env-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.env-action {
  display: flex;
  gap: 9px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}
.ea-badge {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  color: #fff;
}
.side-买 .ea-badge { background: var(--app-up); }
.side-盯 .ea-badge { background: var(--el-color-warning); }
.side-卖 .ea-badge { background: var(--app-down); }
.ea-body b { font-size: 12px; }
.ea-body p {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.env-foot {
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

/* 一句话结论 */
.today-brief {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 12px;
  padding: 12px 16px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
}
.tb-item {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.tb-item b {
  font-family: var(--app-font-mono);
  font-size: 17px;
  font-weight: 800;
  margin: 0 2px;
}
.tb-buy b { color: var(--app-up); }
.tb-watch b { color: var(--el-color-warning); }
.tb-sell b { color: var(--app-down); }
.tb-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  border-left: 1px solid var(--el-border-color);
  padding-left: 14px;
}

.today-skeleton { margin-top: 18px; }

/* 区块 */
.todo-block {
  margin-top: 18px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  padding: 16px 18px 14px;
}
.blk-buy { box-shadow: inset 3px 0 0 var(--app-up); }
.blk-watch { box-shadow: inset 3px 0 0 var(--el-color-warning); }
.blk-sell { box-shadow: inset 3px 0 0 var(--app-down); }

.blk-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.blk-badge {
  font-size: 13px;
  font-weight: 800;
  color: #fff;
  border-radius: 6px;
  padding: 2px 10px;
}
.blk-buy .blk-badge { background: var(--app-up); }
.blk-watch .blk-badge { background: var(--el-color-warning); }
.blk-sell .blk-badge { background: var(--app-down); }
.blk-title { font-size: 15px; font-weight: 700; color: var(--el-text-color-primary); }
.blk-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-left: auto;
}
.blk-foot {
  margin: 12px 2px 2px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* 卡片 */
.card-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 12px;
}
.todo-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  background: var(--el-fill-color-blank);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow .2s ease, transform .2s ease;
}
.todo-card:hover {
  box-shadow: 0 6px 18px rgba(0, 0, 0, .06);
  transform: translateY(-1px);
}
.todo-card.warn { background: #fffdf5; }

.card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.card-stk {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.stk-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  text-decoration: none;
  white-space: nowrap;
}
.stk-name:hover { color: var(--el-color-primary); }
.stk-code {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
}
.stk-industry {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  border-radius: 4px;
  padding: 1px 6px;
}
.card-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.tag {
  font-size: 11px;
  border-radius: 5px;
  padding: 1px 7px;
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.tag-signal { color: var(--app-up); border-color: rgba(245, 108, 108, .35); background: rgba(245, 108, 108, .06); }
.tag-held { color: var(--el-color-primary); border-color: rgba(64, 158, 255, .35); background: rgba(64, 158, 255, .06); }
.tag-paper { color: var(--el-color-primary); border-color: rgba(64, 158, 255, .3); }
.tag-cockpit { color: #7c3aed; border-color: rgba(124, 58, 237, .3); background: rgba(124, 58, 237, .05); }
.tag-exit { color: var(--app-down); border-color: rgba(103, 194, 58, .4); background: rgba(103, 194, 58, .07); font-weight: 700; }
.tag-warn { color: var(--el-color-warning); border-color: rgba(230, 162, 60, .4); background: rgba(230, 162, 60, .07); font-weight: 700; }
.tag-up { color: var(--app-up); }
.tag-down { color: var(--app-down); }

/* 指标行 */
.metric-row {
  display: flex;
  align-items: flex-end;
  gap: 22px;
  flex-wrap: wrap;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.m-label { font-size: 10.5px; color: var(--el-text-color-placeholder); }
.m-val {
  font-family: var(--app-font-mono);
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.m-val.down { color: var(--app-down); }
.m-sub { font-size: 10.5px; color: var(--el-text-color-placeholder); }

/* 卡片底部 */
.card-ft {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.card-summary {
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-acts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.act {
  height: 26px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  color: #fff;
  border-radius: 6px;
}
.act-buy { background: var(--app-up); }
.act-sell { background: var(--app-down); }

/* 理由列表 */
.reason-list {
  margin: 0;
  padding: 10px 12px;
  list-style: none;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.reason-list li {
  position: relative;
  padding-left: 12px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--el-text-color-regular);
}
.reason-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--el-border-color);
}
.reason-list li.k-signal::before { background: var(--app-up); }
.reason-list li.k-trend::before { background: #7c3aed; }
.reason-list li.k-mainline::before { background: var(--el-color-warning); }
.reason-list li.k-liquidity::before { background: #0ea5e9; }
.reason-list li.k-env::before { background: #14b8a6; }
.reason-list li.k-risk::before { background: var(--app-down); }
.reason-list li.k-exit::before { background: var(--app-down); }
.reason-list li.k-warn::before { background: var(--el-color-warning); }

/* 盯盘列表 */
.watch-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.watch-row {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--el-fill-color-blank);
}
.watch-row.near {
  border-color: rgba(230, 162, 60, .45);
  background: #fffdf5;
}
.wr-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.wr-price {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-family: var(--app-font-mono);
}
.wr-arrow { color: var(--el-text-color-placeholder); font-size: 12px; }
.wr-trigger {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.wr-dist {
  font-size: 12px;
  font-weight: 700;
  color: var(--el-text-color-secondary);
}
.wr-dist.near { color: var(--el-color-warning); }
.wr-ft {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

/* 底部说明 */
.page-foot {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-placeholder);
}

/* 下单弹窗沿用 */
.t0-hint { margin-top: 8px; font-size: 12px; color: #909399; }
.qty-hint { margin-left: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.order-preview {
  width: 100%;
  min-height: 32px;
  padding: 8px 12px;
  border-radius: var(--app-radius);
  background: var(--el-fill-color-lighter);
}
.op-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  font-size: 12.5px;
  line-height: 22px;
  color: var(--el-text-color-secondary);
}
.op-row b {
  font-family: var(--app-font-mono);
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.op-alert { margin-top: 6px; }
.op-empty { font-size: 12px; color: var(--el-text-color-placeholder); }
.analysis-context { margin-bottom: 12px; }

@media (max-width: 768px) {
  .card-list { grid-template-columns: 1fr; }
  .blk-hint { margin-left: 0; }
  .env-layers,
  .env-actions { grid-template-columns: 1fr; }
  .env-toggle { margin-left: 0; }
}
</style>
