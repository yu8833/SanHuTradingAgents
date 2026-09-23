<template>
  <div class="review-page app-page">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">交易复盘</h2>
          <p class="page-hero-sub">买入卖出一行览 · 沉淀经验反哺策略</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button :icon="Refresh" text size="small" :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 复盘统计 -->
    <section class="stats-strip">
      <div class="stats-item">
        <span class="stats-label">已平仓交易</span>
        <span class="stats-value">{{ stats?.total_cycles ?? '—' }}</span>
        <span class="stats-sub">完整买卖周期</span>
      </div>
      <div class="stats-item">
        <span class="stats-label">胜率</span>
        <span class="stats-value" :class="(stats?.win_rate ?? 50) >= 50 ? 'up' : 'down'">{{ stats ? fmtPctFromFraction(stats.win_rate, 1) : '—' }}</span>
        <span class="stats-sub">已平仓统计</span>
      </div>
      <div class="stats-item">
        <span class="stats-label">盈亏比</span>
        <span class="stats-value">{{ stats ? fmtNum(stats.profit_loss_ratio) : '—' }}</span>
        <span class="stats-sub">平均盈利 / 平均亏损</span>
      </div>
      <div class="stats-item">
        <span class="stats-label">累计盈亏</span>
        <span class="stats-value" :class="(stats?.total_pnl ?? 0) >= 0 ? 'up' : 'down'">{{ stats ? fmtSigned(stats.total_pnl) : '—' }}</span>
        <span class="stats-sub">已平仓合计</span>
      </div>
      <div class="stats-item">
        <span class="stats-label">复盘笔记</span>
        <span class="stats-value">{{ notes.length }}</span>
        <span class="stats-sub">经验沉淀</span>
      </div>
    </section>

    <!-- 分区 Tab -->
    <el-tabs v-model="activeTab" class="review-tabs">
      <!-- 交易记录（融合：已平仓 + 持仓中，买卖一行） -->
      <el-tab-pane label="交易记录" name="trades">
        <!-- 盈亏可视化：累计曲线 + 单笔分布 -->
        <div v-if="closedRows.length > 0" class="trades-charts">
          <div class="chart-card">
            <div class="chart-card-title">累计盈亏曲线（已平仓）</div>
            <v-chart class="chart chart--line" :option="cumPnlOption" autoresize />
          </div>
          <div class="chart-card">
            <div class="chart-card-title">单笔盈亏分布（最近 30 笔已平仓）</div>
            <v-chart class="chart chart--bar" :option="tradePnlOption" autoresize />
          </div>
        </div>
        <div class="table-card">
          <div class="table-card-hd">
            <span class="table-card-sub">{{ tradeRows.length }} 条待处理记录（含 {{ holdingRows.length }} 持仓中 · 已复盘/已删除的默认隐藏）</span>
          </div>
          <el-table :data="tradeRows" v-loading="loading" size="small" stripe empty-text="暂无交易记录" class="app-table app-table--trades">
            <el-table-column label="股票" min-width="130">
              <template #default="{ row }">
                <div class="stk">
                  <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stk-name">{{ row.name || row.code }}</router-link>
                  <span class="stk-code">{{ row.code }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="88">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row)" effect="plain">
                  {{ row.status === 'closed' ? '已平仓' : '持仓中' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="策略" width="96">
              <template #default="{ row }">
                <el-tag size="small" v-if="row.strategy">{{ strategyLabel(row.strategy) }}</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="建仓价" width="92" align="right" sortable>
              <template #default="{ row }"><span class="money">{{ row.status === 'closed' ? row.buy_price : row.avg_cost }}</span></template>
            </el-table-column>
            <el-table-column label="平仓价/现价" width="104" align="right" sortable>
              <template #default="{ row }">
                <span class="money">{{ row.status === 'closed' ? row.sell_price : row.last_price }}</span>
                <span v-if="row.status === 'open'" class="tag-live">现</span>
              </template>
            </el-table-column>
            <el-table-column label="建仓时间" width="152">
              <template #default="{ row }">{{ row.status === 'closed' ? formatTime(row.buy_time) : formatTime(row.buy_time) }}</template>
            </el-table-column>
            <el-table-column label="平仓时间" width="152">
              <template #default="{ row }">
                <span v-if="row.status === 'closed'">{{ formatTime(row.sell_time) }}</span>
                <span v-else class="muted">持仓中</span>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="80" align="right" sortable>
              <template #default="{ row }">{{ row.quantity }}</template>
            </el-table-column>
            <el-table-column label="盈亏" width="110" align="right" sortable>
              <template #default="{ row }">
                <span class="pct" :class="tradePnl(row) >= 0 ? 'up' : 'down'">{{ fmtSigned(tradePnl(row)) }}</span>
                <span v-if="row.status === 'open'" class="muted small">(浮)</span>
              </template>
            </el-table-column>
            <el-table-column label="盈亏率" width="86" align="right" sortable>
              <template #default="{ row }">
                <span class="pct" :class="tradePnlPct(row) >= 0 ? 'up' : 'down'">{{ fmtPct(tradePnlPct(row)) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180">
              <template #default="{ row }">
                <div class="row-ops">
                  <el-button size="small" type="primary" link @click="openAddNote(row)">记录复盘</el-button>
                  <el-button v-if="row.status === 'closed' && row.id" size="small" type="danger" link :icon="Delete" @click="removeTrade(row)">删除</el-button>
                  <el-button v-if="row.status === 'open'" size="small" type="danger" link @click="sellHolding(row)">卖出</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 策略收益率分析 -->
      <el-tab-pane label="策略收益率" name="strategy">
        <div class="strategy-returns" v-if="strategyReturns.length > 0">
          <div class="chart-card strategy-return-chart">
            <div class="chart-card-title">策略累计收益率排行</div>
            <v-chart class="chart chart--strategy" :option="strategyReturnOption" autoresize />
          </div>
          <div class="strategy-grid">
            <div class="strategy-card" v-for="s in strategyReturns" :key="s.strategy">
              <div class="strategy-card-header">
                <span class="strategy-name">{{ s.label }}</span>
                <el-tag size="small" :type="getStrategyTagType(s.strategy)">{{ s.strategy || '默认' }}</el-tag>
              </div>
              <div class="return-hero">
                <div class="return-hero-label">累计收益率</div>
                <div class="return-hero-value" :class="s.total_return >= 0 ? 'up' : 'down'">{{ fmtPct(s.total_return) }}</div>
              </div>
              <div class="return-stats">
                <div class="return-stat"><span class="rs-label">交易次数</span><span class="rs-value">{{ s.count }}</span></div>
                <div class="return-stat"><span class="rs-label">胜率</span><span class="rs-value" :class="s.win_rate >= 50 ? 'up' : 'down'">{{ fmtPct(s.win_rate, 1) }}</span></div>
                <div class="return-stat"><span class="rs-label">累计盈亏</span><span class="rs-value" :class="s.total_pnl >= 0 ? 'up' : 'down'">{{ fmtSigned(s.total_pnl) }}</span></div>
                <div class="return-stat"><span class="rs-label">平均收益</span><span class="rs-value" :class="s.avg_return >= 0 ? 'up' : 'down'">{{ fmtPct(s.avg_return) }}</span></div>
                <div class="return-stat"><span class="rs-label">最大盈利</span><span class="rs-value up">{{ fmtPct(s.max_win) }}</span></div>
                <div class="return-stat"><span class="rs-label">最大亏损</span><span class="rs-value down">{{ fmtPct(s.max_loss) }}</span></div>
              </div>
              <div class="return-bar" v-if="s.count > 0">
                <div class="bar-track">
                  <div class="bar-fill up" :style="{ width: Math.min(s.win_rate, 100) + '%' }"></div>
                </div>
                <div class="bar-label">胜率分布</div>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无策略收益数据" />
      </el-tab-pane>

      <!-- 复盘笔记面板 -->
      <el-tab-pane label="复盘笔记" name="notes">
        <div class="notes-toolbar">
          <span class="notes-count">{{ notes.length }} 篇笔记</span>
          <el-button type="primary" size="small" :icon="Plus" @click="openAddNote()">新增复盘</el-button>
        </div>
        <el-empty v-if="!loading && notes.length === 0" description="暂无复盘笔记" />
        <div v-else class="notes-list">
          <div v-for="n in notes" :key="n.id" class="note-row">
            <div class="note-head">
              <div class="note-subject">
                <template v-if="n.code">
                  <span class="note-name">{{ n.name || n.code }}</span>
                  <span class="note-code">{{ n.code }}</span>
                </template>
                <el-tag v-else size="small" type="info" effect="plain">自由记录</el-tag>
              </div>
              <div class="note-actions">
                <el-tag v-if="n.result" size="small" :type="resultTagType(n.result)">{{ resultLabel(n.result) }}</el-tag>
                <el-tag v-if="n.strategy" size="small" type="primary" effect="plain">{{ strategyLabel(n.strategy) }}</el-tag>
                <span class="note-time">{{ formatTime(n.updated_at) }}</span>
                <el-button size="small" text :icon="Edit" @click="openEditNote(n)">编辑</el-button>
                <el-button size="small" text type="danger" :icon="Delete" @click="removeNote(n)">删除</el-button>
              </div>
            </div>
            <div class="note-body">
              <div v-if="n.lesson" class="note-line">
                <span class="line-label">经验教训</span>
                <span class="line-text">{{ n.lesson }}</span>
              </div>
              <div v-if="n.improvement" class="note-line">
                <span class="line-label">改进计划</span>
                <span class="line-text">{{ n.improvement }}</span>
              </div>
              <div v-if="n.tags && n.tags.length" class="note-tags">
                <el-tag v-for="t in n.tags" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 复盘笔记弹窗 -->
    <el-dialog v-model="noteDialogVisible" :title="editingId ? '编辑复盘' : '新增复盘'" width="560px">
      <el-form :model="noteForm" label-width="80px">
        <el-form-item label="股票代码">
          <StockCodeAutocomplete
            v-model="noteForm.code"
            :markets="['CN', 'HK', 'US']"
            placeholder="可空，输入代码或名称联想匹配；留空表示自由记录"
            @select="onNoteStockPicked"
            @clear="onNoteStockCleared"
          />
        </el-form-item>
        <el-form-item label="股票名称">
          <template v-if="noteForm.code">
            <router-link target="_blank" rel="noopener" :to="`/stocks/${noteForm.code}`" class="stk-name">
              {{ noteForm.name || noteForm.code }}
            </router-link>
          </template>
          <span v-else class="note-empty-name">—（未绑定股票）</span>
        </el-form-item>
        <el-form-item label="交易策略">
          <el-select v-model="noteForm.strategy" placeholder="该笔交易所用策略（可空）" clearable style="width:100%">
            <el-option v-for="opt in strategyOptions" :key="opt.id" :label="opt.name" :value="opt.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="交易结果">
          <el-select v-model="noteForm.result" placeholder="选择交易结果归因" clearable style="width:100%">
            <el-option v-for="opt in resultOptions" :key="opt" :label="resultLabel(opt)" :value="opt" />
          </el-select>
        </el-form-item>
        <el-form-item label="经验教训">
          <el-input v-model="noteForm.lesson" type="textarea" :rows="3" placeholder="本次交易的经验教训…" />
        </el-form-item>
        <el-form-item label="改进计划">
          <el-input v-model="noteForm.improvement" type="textarea" :rows="3" placeholder="下次如何改进…" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="noteForm.tags" multiple filterable allow-create default-first-option placeholder="纪律/心态/仓位/择时" style="width:100%">
            <el-option v-for="t in ['纪律', '心态', '仓位', '择时']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="noteDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNote">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'
import { paperApi, reviewApi, type ReviewCycleItem, type ReviewNoteItem, type ReviewStats } from '@/api/paper'
import { stocksApi } from '@/api/stocks'
import { getStrategyNameMap, strategyNameSync } from '@/utils/strategyName'
import { fmtPct, fmtPctFromFraction, fmtNum, fmtSigned } from '@/utils/format'
import { use as echartsUse } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

echartsUse([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

defineOptions({ name: 'PaperReview' })

const router = useRouter()

const activeTab = ref('trades')
const loading = ref(false)
const saving = ref(false)
const cycles = ref<ReviewCycleItem[]>([])
const holdings = ref<any[]>([])
const notes = ref<ReviewNoteItem[]>([])
const stats = ref<ReviewStats | null>(null)
const resultOptions = ref<string[]>([])

// ── 交易记录融合视图：已平仓（买卖一行） + 持仓中 ──
interface TradeRow {
  id?: string
  handled?: boolean
  code: string
  name?: string
  strategy?: string
  reason?: string
  status: 'closed' | 'open'
  buy_price?: number
  sell_price?: number
  avg_cost?: number
  last_price?: number
  quantity: number
  pnl?: number
  pnl_pct?: number
  buy_time?: string
  sell_time?: string
}

const holdingRows = computed<TradeRow[]>(() => {
  return (holdings.value || []).map(p => ({
    code: p.code,
    name: p.name,
    strategy: p.strategy,
    status: 'open' as const,
    avg_cost: Number(p.avg_cost ?? 0),
    last_price: p.last_price != null ? Number(p.last_price) : undefined,
    quantity: Number(p.quantity ?? 0),
    buy_time: undefined,
  }))
})

/** 全部已平仓周期：用于图表/统计（含已复盘、已移除的记录） */
const closedRows = computed<TradeRow[]>(() => {
  return (cycles.value || []).map(c => ({
    id: c.id,
    code: c.code,
    name: c.name,
    strategy: c.strategy,
    reason: c.reason,
    status: 'closed' as const,
    buy_price: Number(c.buy_price ?? 0),
    sell_price: Number(c.sell_price ?? 0),
    quantity: Number(c.quantity ?? 0),
    pnl: Number(c.pnl ?? 0),
    pnl_pct: Number(c.pnl_pct ?? 0),
    buy_time: c.buy_time,
    sell_time: c.sell_time,
  }))
})

/** 待复盘周期：未记录复盘、未被删除的已平仓记录（列表只展示这些） */
const pendingClosedRows = computed<TradeRow[]>(() => {
  return (cycles.value || [])
    .filter(c => !c.handled)
    .map(c => ({
      id: c.id,
      code: c.code,
      name: c.name,
      strategy: c.strategy,
      reason: c.reason,
      status: 'closed' as const,
      buy_price: Number(c.buy_price ?? 0),
      sell_price: Number(c.sell_price ?? 0),
      quantity: Number(c.quantity ?? 0),
      pnl: Number(c.pnl ?? 0),
      pnl_pct: Number(c.pnl_pct ?? 0),
      buy_time: c.buy_time,
      sell_time: c.sell_time,
    }))
})

/** 交易记录 = 持仓中（进行中，置顶） + 待复盘已平仓（按平仓时间倒序） */
const tradeRows = computed<TradeRow[]>(() => [
  ...holdingRows.value,
  ...pendingClosedRows.value.sort((a, b) => (b.sell_time || '').localeCompare(a.sell_time || '')),
])

/** el-tag 状态类型（已平仓=success / 持仓中=warning） */
function statusTagType(row: TradeRow): 'success' | 'warning' {
  return row.status === 'closed' ? 'success' : 'warning'
}

function tradePnl(row: TradeRow): number {
  if (row.status === 'closed') return row.pnl ?? 0
  const last = row.last_price != null ? row.last_price : row.avg_cost ?? 0
  return (last - (row.avg_cost ?? 0)) * row.quantity
}

function tradePnlPct(row: TradeRow): number {
  if (row.status === 'closed') return row.pnl_pct ?? 0
  const avg = row.avg_cost ?? 0
  const last = row.last_price != null ? row.last_price : avg
  if (!avg) return 0
  return (last / avg - 1) * 100
}

// 跳转模拟交易卖出（带代码预填，减少操作）
function sellHolding(row: TradeRow) {
  router.push({ path: '/paper', query: { code: row.code, side: 'sell', quantity: row.quantity } })
}

const noteDialogVisible = ref(false)
const editingId = ref<string | null>(null)
const noteForm = reactive({
  code: '',
  name: '',
  strategy: '',
  result: '',
  lesson: '',
  improvement: '',
  tags: [] as string[],
  tradeId: null as string | null,
})

const RESULT_LABELS: Record<string, string> = {
  executed: '执行到位',
  stop_loss_timely: '止损及时',
  chasing_high: '追高',
  cut_loss_early: '割肉太早',
  missed: '踏空',
  other: '其他'
}

function resultLabel(v: string) {
  return RESULT_LABELS[v] || v
}

const strategyNames = ref<Record<string, string>>({})
function strategyLabel(s?: string | null): string {
  if (!s) return '-'
  return strategyNames.value[s] || strategyNameSync(s)
}

function formatTime(t?: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}

// ── 持仓：批量补全股票名称 ──
async function fetchStockNames(items: any[]) {
  if (!items || items.length === 0) return
  const codes = [...new Set(items.map(item => item.code).filter(Boolean))]
  await Promise.all(
    codes.map(async (code) => {
      try {
        const res = await stocksApi.getQuote(code)
        if (res.success && res.data && res.data.name) {
          items.forEach(item => {
            if (item.code === code) item.name = res.data.name
          })
        }
      } catch (e) {
        console.warn(`获取股票 ${code} 名称失败:`, e)
      }
    })
  )
}

async function loadHoldings() {
  try {
    const res = await paperApi.getPositions()
    if (res.success) {
      holdings.value = res.data.items || []
      await fetchStockNames(holdings.value)
    }
  } catch (e) {
    console.warn('[Review] 持仓加载失败', e)
  }
}

// 复盘笔记名称补全：历史笔记可能只存了代码没有名称（如北交所 92 开头），
// 按代码异步取行情名称填充展示；会话内缓存避免重复请求。
const noteNameCache = new Map<string, string>()
async function fillNoteNames() {
  const missing = [...new Set(
    (notes.value || [])
      .filter(n => n.code && !n.name)
      .map(n => n.code!)
  )]
  if (missing.length === 0) return
  const apply = (code: string, name: string) => {
    notes.value.forEach(n => {
      if (n.code === code && !n.name) n.name = name
    })
  }
  await Promise.all(
    missing.map(async (code) => {
      const cached = noteNameCache.get(code)
      if (cached) {
        apply(code, cached)
        return
      }
      try {
        const res = await stocksApi.getQuote(code)
        const nm = res.data?.name
        if (nm) {
          noteNameCache.set(code, nm)
          apply(code, nm)
        }
      } catch (e) {
        console.warn(`获取股票 ${code} 名称失败:`, e)
      }
    })
  )
}

async function loadAll() {
  loading.value = true
  try {
    const [tradesRes, notesRes, statsRes] = await Promise.all([
      reviewApi.getTrades(),
      reviewApi.getNotes(),
      reviewApi.getStats()
    ])
    cycles.value = tradesRes.data.items || []
    notes.value = notesRes.data.items || []
    fillNoteNames() // 不阻塞加载：历史笔记缺名称的按代码异步补全
    stats.value = statsRes.data
    resultOptions.value = statsRes.data?.result_options || []
    // 预载策略名称映射，保证店铺展示与「常用策略」名称对齐
    getStrategyNameMap().then((m) => {
      strategyNames.value = m
    })
    await loadHoldings()
  } catch (e) {
    ElMessage.error('加载交易复盘数据失败')
  } finally {
    loading.value = false
  }
}

function openAddNote(row?: TradeRow) {
  editingId.value = null
  // 已平仓周期关联成交流水 id：保存复盘笔记后该记录自动从「交易记录」列表隐藏
  noteForm.tradeId = (row?.status === 'closed' && row?.id) ? row.id : null
  noteForm.code = row?.code || ''
  noteForm.name = row?.name || ''
  noteForm.strategy = row?.strategy || ''
  noteForm.result = ''
  noteForm.lesson = ''
  noteForm.improvement = ''
  noteForm.tags = []
  noteDialogVisible.value = true
}

function openEditNote(n: ReviewNoteItem) {
  editingId.value = n.id || null
  noteForm.tradeId = n.trade_id || null
  noteForm.code = n.code || ''
  noteForm.name = n.name || ''
  noteForm.strategy = n.strategy || ''
  noteForm.result = n.result || ''
  noteForm.lesson = n.lesson || ''
  noteForm.improvement = n.improvement || ''
  noteForm.tags = n.tags || []
  noteDialogVisible.value = true
}

// 股票联想选中 → 自动回填代码+名称
function onNoteStockPicked(stock: any) {
  if (stock?.name) noteForm.name = stock.name
}

// 清空代码 → 名称同步清空
function onNoteStockCleared() {
  noteForm.name = ''
}

async function saveNote() {
  saving.value = true
  try {
    const payload = {
      code: noteForm.code || null,
      name: noteForm.name || null,
      strategy: noteForm.strategy || null,
      result: noteForm.result || null,
      lesson: noteForm.lesson || null,
      improvement: noteForm.improvement || null,
      tags: noteForm.tags,
      trade_id: noteForm.tradeId,
    }
    if (editingId.value) {
      await reviewApi.updateNote(editingId.value, payload)
    } else {
      await reviewApi.createNote(payload)
    }
    ElMessage.success('已保存')
    noteDialogVisible.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function removeTrade(row: TradeRow) {
  if (!row.id) return
  try {
    await ElMessageBox.confirm(
      `确定将「${row.name || row.code}」从交易记录中删除？\n删除后该记录将不再计入胜率/盈亏等复盘统计。`,
      '删除交易记录', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await reviewApi.deleteTrade(row.id)
    ElMessage.success('已删除，复盘统计已更新')
    await loadAll()
  } catch (e) {
    /* 取消则不处理 */
  }
}

async function removeNote(n: ReviewNoteItem) {
  try {
    await ElMessageBox.confirm('确定删除这条复盘笔记？', '提示', { type: 'warning' })
    await reviewApi.deleteNote(n.id!)
    ElMessage.success('已删除')
    await loadAll()
  } catch (e) {
    /* 取消则不处理 */
  }
}

interface StrategyReturnStat {
  strategy: string
  label: string
  count: number
  win_rate: number
  total_pnl: number
  total_return: number
  avg_return: number
  max_win: number
  max_loss: number
}

const strategyReturns = computed<StrategyReturnStat[]>(() => {
  if (!cycles.value.length) return []

  const byStrategy = new Map<string, { pnls: number[]; pcts: number[]; wins: number }>()

  for (const c of cycles.value) {
    const key = c.strategy || 'default'
    if (!byStrategy.has(key)) {
      byStrategy.set(key, { pnls: [], pcts: [], wins: 0 })
    }
    const entry = byStrategy.get(key)!
    const pnl = Number(c.pnl) || 0
    const pct = Number(c.pnl_pct) || 0
    entry.pnls.push(pnl)
    entry.pcts.push(pct)
    if (pnl > 0) entry.wins++
  }

  const results: StrategyReturnStat[] = []
  for (const [strategy, data] of byStrategy) {
    const count = data.pnls.length
    const total_pnl = data.pnls.reduce((a, b) => a + b, 0)
    const total_return = data.pcts.reduce((a, b) => a + b, 0)
    const avg_return = count > 0 ? total_return / count : 0
    const win_rate = count > 0 ? (data.wins / count) * 100 : 0
    const max_win = count > 0 ? Math.max(...data.pcts, 0) : 0
    const max_loss = count > 0 ? Math.min(...data.pcts, 0) : 0

    results.push({
      strategy,
      label: strategyLabel(strategy),
      count,
      win_rate,
      total_pnl,
      total_return,
      avg_return,
      max_win,
      max_loss,
    })
  }

  return results.sort((a, b) => b.total_return - a.total_return)
})

// ---------- 复盘图表 ----------
// 累计盈亏曲线：按平仓时间升序累加（仅已平仓）
const cumPnlOption = computed(() => {
  const closed = closedRows.value
    .filter(t => t.sell_time)
    .map(t => ({ time: t.sell_time!, pnl: Number(t.pnl ?? 0) }))
    .sort((a, b) => a.time.localeCompare(b.time))
  let acc = 0
  const data = closed.map(p => {
    acc += p.pnl
    return [p.time.slice(0, 10), Math.round(acc * 100) / 100]
  })
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtSigned(v) },
    grid: { left: 70, right: 20, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.map(d => d[0]),
      axisTick: { alignWithLabel: true },
      axisLabel: {
        fontSize: 10,
        margin: 12,
        hideOverlap: true,
        // 平仓日期压缩为 MM-DD，缩短标签宽度，避免横轴重叠
        formatter: (v: string) => (v || '').slice(5),
      },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    series: [{
      name: '累计盈亏',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.08 },
      data,
    }],
  }
})

// 单笔盈亏分布（最近 30 笔，红盈绿亏）
const tradePnlOption = computed(() => {
  const closed = closedRows.value
    .filter(t => t.sell_time)
    .sort((a, b) => (b.sell_time || '').localeCompare(a.sell_time || ''))
    .slice(0, 30)
    .reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any) => {
      const p = params[0]
      if (!p) return ''
      const t = closed[p.dataIndex]
      if (!t) return ''
      return `${t.name || t.code}<br/>盈亏：${fmtSigned(t.pnl ?? 0)}（${fmtPct(t.pnl_pct ?? 0)}）`
    } },
    grid: { left: 70, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      axisLabel: { fontSize: 9, interval: Math.max(0, Math.floor(closed.length / 12) - 1), rotate: 30 },
      data: closed.map((t, i) => `${t.code || i + 1}`),
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    series: [{
      type: 'bar',
      barMaxWidth: 16,
      data: closed.map(t => ({
        value: Math.round(Number(t.pnl ?? 0) * 100) / 100,
        itemStyle: { color: (t.pnl ?? 0) >= 0 ? '#f56c6c' : '#67c23a', borderRadius: 2 },
      })),
    }],
  }
})

// 策略累计收益率排行（横向条，红盈绿亏）
const strategyReturnOption = computed(() => {
  const items = strategyReturns.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any) => {
      const p = params[0]
      if (!p) return ''
      return `${p.name}<br/>累计收益率：${fmtPct(p.value)}`
    } },
    grid: { left: 8, right: 60, top: 8, bottom: 4, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    yAxis: { type: 'category', inverse: true, axisLabel: { fontSize: 11 }, data: items.map(i => i.label) },
    series: [{
      type: 'bar',
      barWidth: 14,
      data: items.map(i => ({
        value: Math.round(i.total_return * 100) / 100,
        itemStyle: { color: i.total_return >= 0 ? '#f56c6c' : '#67c23a', borderRadius: 3 },
      })),
      label: { show: true, position: 'right', fontSize: 10, formatter: (p: any) => `${p.value}%` },
    }],
  }
})

function getStrategyTagType(s: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    extreme_reversal: 'danger',
    turnaround: 'warning',
    small_cap_value: 'success',
    convertible_arbitrage: 'info',
    ma_golden_cross: 'success',
    tbs: 'success',
    default: 'primary',
  }
  return map[s] || 'primary'
}

/** 交易结果 → 标签颜色（正向=绿，负向=红，中性=灰/黄） */
function resultTagType(s: string): 'success' | 'danger' | 'warning' | 'info' {
  const map: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
    executed: 'success',
    stop_loss_timely: 'success',
    chasing_high: 'danger',
    cut_loss_early: 'warning',
    missed: 'info',
    other: 'info',
  }
  return map[s] || 'info'
}

// 策略下拉选项：注册表映射 + 历史策略兜底（与持仓页一致）
const LEGACY_STRATEGY_POOL: [string, string][] = [
  ['extreme_reversal', '极端反转'],
  ['turnaround', '困境反转'],
  ['small_cap_value', '小盘价值'],
  ['convertible_arbitrage', '转债套利'],
  ['ma_golden_cross', 'MA金叉'],
  ['macd_golden', 'MACD金叉'],
]
const strategyOptions = computed<{ id: string; name: string }[]>(() => {
  const seen = new Set<string>()
  const out: { id: string; name: string }[] = []
  const push = (id: string, name: string | undefined) => {
    const n = (name || '').trim()
    if (!id || !n || seen.has(id)) return
    seen.add(id)
    out.push({ id, name: n })
  }
  // 注册表 + 兜底映射（跳过旧数据别名 tbs，避免与 MA金叉重复）
  for (const [id, name] of Object.entries(strategyNames.value)) {
    if (id === 'tbs') continue
    push(id, name)
  }
  // 注册表未命中的历史项兜底
  for (const [id, name] of LEGACY_STRATEGY_POOL) push(id, name)
  // 「默认」置顶，其余保持注册表顺序
  out.sort((a, b) => (a.id === 'default' ? -1 : b.id === 'default' ? 1 : 0))
  return out
})

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.review-page {
  padding: 24px;
}
.page-hero {
  margin-bottom: 4px;
}

/* ═══════════ 复盘统计条 ═══════════ */
.stats-strip {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin: 20px 0 8px;
}
.stats-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  border-radius: var(--app-radius);
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  transition: background .2s ease, transform .2s ease;
}
.stats-item:hover {
  background: var(--el-fill-color);
  transform: translateY(-1px);
}
.stats-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.stats-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--app-font-mono);
  color: var(--el-text-color-primary);
  letter-spacing: .3px;
}
.stats-sub {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.up { color: var(--app-up); }
.down { color: var(--app-down); }

/* ═══════════ 分区 Tab ═══════════ */
.review-tabs {
  margin-top: 10px;
}
.review-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--el-border-color-lighter);
}
.review-tabs :deep(.el-tabs__item) {
  font-weight: 600;
}

/* 盈亏可视化图表 */
.trades-charts {
  display: grid;
  grid-template-columns: 2fr 3fr;
  gap: 12px;
  margin-bottom: 12px;
}
.chart-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  background: var(--el-fill-color-blank);
  padding: 12px 14px;
}
.chart-card-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.chart--line {
  height: 200px;
}
.chart--bar {
  height: 200px;
}
.strategy-return-chart {
  margin-bottom: 14px;
}
.chart--strategy {
  height: 200px;
}

/* 表格卡片 */
.table-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  background: var(--el-fill-color-blank);
  padding: 14px;
}
.table-card-hd {
  display: flex;
  align-items: baseline;
  justify-content: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}
.table-card-sub {
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
}

/* 交易记录单元格 */
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
.muted { color: var(--el-text-color-placeholder); }
.small { font-size: 10.5px; margin-left: 2px; }
.tag-live {
  margin-left: 5px;
  font-size: 10px;
  color: var(--el-color-warning);
  border: 1px solid rgba(230, 162, 60, .4);
  border-radius: 4px;
  padding: 0 3px;
  vertical-align: 1px;
}

/* 订单方向 */
.side-tag {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
}
.side-buy { color: var(--app-up); }
.side-sell { color: var(--app-down); }

/* 交易记录操作按钮组 */
.row-ops {
  display: flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}

/* 复盘笔记：分割线列表（一行一笔记，轻镶边，强文字层级） */
.notes-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.notes-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: var(--app-font-mono);
}
.notes-list {
  display: flex;
  flex-direction: column;
}
.note-row {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  transition: background .15s ease;
}
.note-row:first-child {
  padding-top: 6px;
}
.note-row:last-child {
  border-bottom: none;
}
.note-row:hover {
  background: var(--el-fill-color-lighter);
}
.note-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.note-subject {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.note-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.note-code {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
  flex-shrink: 0;
}
.note-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.note-time {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
  margin-left: 4px;
}
.note-empty-name {
  color: var(--el-text-color-placeholder);
  font-size: 12.5px;
}
.note-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 2px;
}
.note-line {
  display: flex;
  gap: 10px;
  font-size: 13px;
  line-height: 1.65;
}
.line-label {
  flex-shrink: 0;
  width: 52px;
  padding-top: 2px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.line-text {
  color: var(--el-text-color-regular);
  word-break: break-word;
  white-space: pre-wrap;
}
.note-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ═══════════ 策略收益率 ═══════════ */
.strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}
.strategy-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius);
  background: var(--el-fill-color-blank);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: transform .15s ease, box-shadow .15s ease;
}
.strategy-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, .08);
}
.strategy-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.strategy-name {
  font-weight: 600;
  font-size: 14px;
}
.return-hero {
  text-align: center;
  padding: 14px 10px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(43, 108, 176, 0.08) 0%, rgba(43, 108, 176, 0.02) 100%);
  border: 1px solid var(--el-border-color-lighter);
}
.return-hero-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.return-hero-value {
  font-size: 32px;
  font-weight: 700;
  font-family: var(--app-font-mono);
  letter-spacing: -0.5px;
}
.return-hero-value.up { color: var(--app-up); }
.return-hero-value.down { color: var(--app-down); }
.return-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.return-stat {
  display: flex;
  flex-direction: column;
  padding: 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
}
.rs-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}
.rs-value {
  font-size: 14px;
  font-weight: 600;
  font-family: var(--app-font-mono);
}
.rs-value.up { color: var(--app-up); }
.rs-value.down { color: var(--app-down); }
.return-bar .bar-track {
  height: 6px;
  background: var(--el-fill-color-lighter);
  border-radius: 3px;
  overflow: hidden;
}
.return-bar .bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.return-bar .bar-fill.up { background: var(--app-up); }
.return-bar .bar-fill.down { background: var(--app-down); }
.bar-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.dash { color: #909399; }

/* ═══════════ 响应式 ═══════════ */
@media (max-width: 1400px) {
  .stats-strip { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 900px) {
  .stats-strip { grid-template-columns: repeat(2, 1fr); }
  .notes-list { grid-template-columns: 1fr; }
  .strategy-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .review-page { padding: 12px; }
  .stats-strip { grid-template-columns: repeat(2, 1fr); }
  .return-stats { grid-template-columns: repeat(2, 1fr); }
  .trades-charts { grid-template-columns: 1fr; }
}
</style>