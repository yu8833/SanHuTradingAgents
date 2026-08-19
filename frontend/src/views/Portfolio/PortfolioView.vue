<template>
  <div class="portfolio-view">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Wallet /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">持仓追踪</h2>
          <p class="page-hero-sub">
            统一管理所有策略持仓，支持止损止盈设置、平仓记录
          </p>
        </div>
      </div>
    </div>

    <!-- 汇总卡片 -->
    <el-row :gutter="16" class="summary-row">
      <el-col :span="6">
        <div class="summary-card">
          <div class="summary-icon summary-icon--blue">
            <el-icon :size="22"><Wallet /></el-icon>
          </div>
          <div class="summary-body">
            <div class="stat-label">持仓数量</div>
            <div class="stat-value">{{ summary?.total_positions || 0 }} <span class="stat-unit">只</span></div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="summary-card">
          <div class="summary-icon summary-icon--indigo">
            <el-icon :size="22"><Money /></el-icon>
          </div>
          <div class="summary-body">
            <div class="stat-label">总成本</div>
            <div class="stat-value">¥{{ formatNum(summary?.total_cost) }}</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="summary-card">
          <div class="summary-icon summary-icon--teal">
            <el-icon :size="22"><TrendCharts /></el-icon>
          </div>
          <div class="summary-body">
            <div class="stat-label">总市值</div>
            <div class="stat-value">¥{{ formatNum(summary?.total_market_value) }}</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="summary-card" :class="{ 'summary-card--up': (summary?.total_profit_loss || 0) >= 0, 'summary-card--down': (summary?.total_profit_loss || 0) < 0 }">
          <div class="summary-icon" :class="(summary?.total_profit_loss || 0) >= 0 ? 'summary-icon--red' : 'summary-icon--green'">
            <el-icon :size="22"><Odometer /></el-icon>
          </div>
          <div class="summary-body">
            <div class="stat-label">浮动盈亏</div>
            <div class="stat-value" :class="{ up: (summary?.total_profit_loss || 0) >= 0, down: (summary?.total_profit_loss || 0) < 0 }">
              {{ (summary?.total_profit_loss || 0) >= 0 ? '+' : '' }}¥{{ formatNum(summary?.total_profit_loss) }}
              <span class="stat-pct">({{ formatPct(summary?.profit_loss_rate) }})</span>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 持仓列表 -->
    <div class="positions-panel">
      <div class="positions-toolbar">
        <div class="toolbar-left">
          <span class="toolbar-count">共 <strong>{{ positions.length }}</strong> 只持仓</span>
          <el-tag v-if="loading" size="small" type="info" effect="plain">加载中...</el-tag>
        </div>
        <div class="toolbar-actions">
          <el-button size="small" :loading="loading" @click="loadPositions">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
          <el-button size="small" type="primary" @click="openAddDialog">
            <el-icon><Plus /></el-icon>
            手动添加
          </el-button>
          <el-button size="small" type="success" @click="openImportDialog">
            <el-icon><Upload /></el-icon>
            导入CSV
          </el-button>
        </div>
      </div>

      <el-table :data="positions" v-loading="loading" stripe class="positions-table">
        <el-table-column label="代码" width="100" prop="symbol">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.symbol}`" class="stock-code">{{ row.symbol }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="名称" width="100" prop="stock_name">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.symbol}`" class="stock-name">{{ row.stock_name }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="策略" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="getStrategyTagType(row.strategy)">{{ strategyLabel(row.strategy) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="90" prop="quantity" align="right" />
        <el-table-column label="成本价" width="90" align="right">
          <template #default="{ row }">{{ formatNum(row.cost_price) }}</template>
        </el-table-column>
        <el-table-column label="现价" width="90" align="right">
          <template #default="{ row }">{{ row.current_price != null ? formatNum(row.current_price) : '-' }}</template>
        </el-table-column>
        <el-table-column label="市值" width="100" align="right">
          <template #default="{ row }">{{ row.market_value != null ? '¥' + formatNum(row.market_value) : '-' }}</template>
        </el-table-column>
        <el-table-column label="盈亏" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.profit_loss != null" :class="{ up: row.profit_loss >= 0, down: row.profit_loss < 0 }">
              {{ row.profit_loss >= 0 ? '+' : '' }}¥{{ formatNum(row.profit_loss) }}
              <span class="stat-pct">({{ formatPct(row.profit_loss_rate) }})</span>
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="止损价" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.stop_loss_price" class="price-down">{{ formatNum(row.stop_loss_price) }}</span>
            <span v-else class="text-muted">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="止盈价" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.take_profit_price" class="price-up">{{ formatNum(row.take_profit_price) }}</span>
            <span v-else class="text-muted">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="买入日期" width="110" prop="buy_date" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="warning" link @click="openCloseDialog(row)">平仓</el-button>
            <el-button size="small" type="danger" link @click="confirmDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && positions.length === 0" description="暂无持仓，点击「手动添加」或「导入CSV」开始追踪" />
    </div>

    <!-- 添加/编辑持仓对话框 -->
    <el-dialog v-model="editDialogVisible" :title="editingId ? '编辑持仓' : '手动添加持仓'" width="520px">
      <el-form :model="editForm" label-width="100px" size="default">
        <el-form-item label="股票代码" v-if="!editingId">
          <el-input v-model="editForm.symbol" placeholder="如 600519" />
        </el-form-item>
        <el-form-item label="股票名称" v-if="!editingId">
          <el-input v-model="editForm.stock_name" placeholder="如 贵州茅台" />
        </el-form-item>
        <el-form-item label="策略" v-if="!editingId">
          <el-select v-model="editForm.strategy" style="width:100%">
            <el-option label="默认" value="default" />
            <el-option label="极端反转" value="extreme_reversal" />
            <el-option label="困境反转" value="turnaround" />
            <el-option label="小盘价值" value="small_cap_value" />
            <el-option label="转债套利" value="convertible_arbitrage" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" v-if="!editingId">
          <el-input-number v-model="editForm.quantity" :min="1" style="width:100%" />
        </el-form-item>
        <el-form-item label="成本价" v-if="!editingId">
          <el-input-number v-model="editForm.cost_price" :min="0" :step="0.1" :precision="2" style="width:100%" />
        </el-form-item>
        <el-form-item label="买入日期" v-if="!editingId">
          <el-date-picker v-model="editForm.buy_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="止损价">
          <el-input-number v-model="editForm.stop_loss_price" :min="0" :step="0.1" :precision="2" style="width:100%" />
        </el-form-item>
        <el-form-item label="止盈价">
          <el-input-number v-model="editForm.take_profit_price" :min="0" :step="0.1" :precision="2" style="width:100%" />
        </el-form-item>
        <el-form-item label="投资逻辑">
          <el-input v-model="editForm.thesis" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.notes" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePosition">保存</el-button>
      </template>
    </el-dialog>

    <!-- 平仓对话框 -->
    <el-dialog v-model="closeDialogVisible" title="平仓" width="440px">
      <el-form :model="closeForm" label-width="100px">
        <el-form-item label="股票">
          <span>{{ closeTarget?.stock_name }} ({{ closeTarget?.symbol }})</span>
        </el-form-item>
        <el-form-item label="平仓价">
          <el-input-number v-model="closeForm.exit_price" :min="0" :step="0.1" :precision="2" style="width:100%" />
        </el-form-item>
        <el-form-item label="平仓日期">
          <el-date-picker v-model="closeForm.exit_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="平仓原因">
          <el-select v-model="closeForm.exit_reason" style="width:100%">
            <el-option label="止损" value="stop_loss" />
            <el-option label="止盈" value="take_profit" />
            <el-option label="时间止损" value="time_stop" />
            <el-option label="逻辑证伪" value="thesis_invalid" />
            <el-option label="手动平仓" value="manual" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDialogVisible = false">取消</el-button>
        <el-button type="warning" :loading="closing" @click="confirmClose">确认平仓</el-button>
      </template>
    </el-dialog>

    <!-- CSV导入对话框 -->
    <el-dialog v-model="importDialogVisible" title="导入实盘交易记录（CSV）" width="560px">
      <el-alert
        title="CSV第一行必须为表头，支持以下列名（中英文均可）"
        type="info"
        :closable="false"
        style="margin-bottom:16px;"
      >
        <div style="font-size:12px;line-height:1.8;">
          代码/symbol/code · 名称/name · 数量/quantity · 成本价/cost_price · 买入日期/buy_date · 止损价/stop_loss · 止盈价/take_profit
        </div>
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="策略标签">
          <el-select v-model="importStrategy" style="width:100%">
            <el-option label="默认" value="default" />
            <el-option label="极端反转" value="extreme_reversal" />
            <el-option label="困境反转" value="turnaround" />
            <el-option label="小盘价值" value="small_cap_value" />
            <el-option label="转债套利" value="convertible_arbitrage" />
          </el-select>
        </el-form-item>
        <el-form-item label="CSV文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            accept=".csv"
            :on-change="handleFileChange"
            :on-exceed="handleExceed"
          >
            <el-button type="primary">选择文件</el-button>
            <template #tip>
              <div style="font-size:12px;color:#909399;margin-top:4px;">支持UTF-8/GBK编码的CSV文件</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">开始导入</el-button>
      </template>
    </el-dialog>

    <!-- 交易复盘对话框 -->
    <el-dialog v-model="reviewDialogVisible" title="交易复盘" width="640px" :close-on-click-modal="false">
      <div v-if="reviewTarget" class="review-trade-summary">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="股票">
            <router-link :to="`/stocks/${reviewTarget.code}`" class="stock-name">{{ reviewTarget.stock_name }} ({{ reviewTarget.code }})</router-link>
          </el-descriptions-item>
          <el-descriptions-item label="策略">{{ strategyLabel(reviewTarget.strategy || 'default') }}</el-descriptions-item>
          <el-descriptions-item label="盈亏">
            <span :class="{ up: (reviewTarget.realized_pnl || 0) >= 0, down: (reviewTarget.realized_pnl || 0) < 0 }">
              {{ (reviewTarget.realized_pnl || 0) >= 0 ? '+' : '' }}¥{{ formatNum(reviewTarget.realized_pnl) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="买入">{{ reviewTarget.buy_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="平仓">{{ reviewTarget.exit_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="原因">{{ exitReasonLabel(reviewTarget.exit_reason) }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <el-input
        v-model="reviewContent"
        type="textarea"
        :rows="14"
        placeholder="按模板填写复盘内容..."
        style="margin-top:12px;"
      />
      <template #footer>
        <el-button @click="reviewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="reviewSaving" @click="saveReview">保存复盘</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadInstance, UploadFile, UploadFiles } from 'element-plus'
import { Wallet, Money, TrendCharts, Odometer, Refresh, Plus, Upload } from '@element-plus/icons-vue'
import { portfolioApi, type PositionItem, type PositionSummary, type AddPositionPayload, type UpdatePositionPayload, type ClosedTrade } from '@/api/portfolio'
import { vibeApi } from '@/api/vibe'
import { getStrategyNameMap, strategyNameSync } from '@/utils/strategyName'

defineOptions({ name: 'PortfolioView' })

const loading = ref(false)
const positions = ref<PositionItem[]>([])
const summary = ref<PositionSummary | null>(null)

const loadPositions = async () => {
  loading.value = true
  try {
    const res = await portfolioApi.getSummary()
    const data = res.data
    summary.value = data
    positions.value = data.positions || []
  } catch (e: any) {
    ElMessage.error('加载持仓失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

// 添加/编辑
const editDialogVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const editForm = reactive<AddPositionPayload & UpdatePositionPayload>({
  symbol: '',
  stock_name: '',
  quantity: 100,
  cost_price: 0,
  position_ratio: 0,
  buy_date: new Date().toISOString().slice(0, 10),
  strategy: 'default',
  stop_loss_price: null,
  take_profit_price: null,
  thesis: '',
  notes: '',
})

const openAddDialog = () => {
  editingId.value = null
  Object.assign(editForm, {
    symbol: '', stock_name: '', quantity: 100, cost_price: 0, position_ratio: 0,
    buy_date: new Date().toISOString().slice(0, 10), strategy: 'default',
    stop_loss_price: null, take_profit_price: null, thesis: '', notes: '',
  })
  editDialogVisible.value = true
}

const openEditDialog = (row: PositionItem) => {
  editingId.value = row.id
  Object.assign(editForm, {
    symbol: row.symbol, stock_name: row.stock_name, quantity: row.quantity,
    cost_price: row.cost_price, position_ratio: row.position_ratio,
    buy_date: row.buy_date, strategy: row.strategy || 'default',
    stop_loss_price: row.stop_loss_price ?? null,
    take_profit_price: row.take_profit_price ?? null,
    thesis: row.thesis || '', notes: row.notes || '',
  })
  editDialogVisible.value = true
}

const savePosition = async () => {
  if (!editingId.value) {
    // 新增
    if (!editForm.symbol || !editForm.stock_name || editForm.quantity <= 0) {
      ElMessage.warning('请填写代码、名称、数量')
      return
    }
  }
  saving.value = true
  try {
    if (editingId.value) {
      // 编辑：仅更新元数据
      const updates: UpdatePositionPayload = {
        stop_loss_price: editForm.stop_loss_price,
        take_profit_price: editForm.take_profit_price,
        thesis: editForm.thesis,
        notes: editForm.notes,
      }
      await portfolioApi.updatePosition(editingId.value, updates)
      ElMessage.success('持仓已更新')
    } else {
      await portfolioApi.addPosition({
        symbol: editForm.symbol,
        stock_name: editForm.stock_name,
        quantity: editForm.quantity,
        cost_price: editForm.cost_price,
        position_ratio: editForm.position_ratio,
        buy_date: editForm.buy_date,
        strategy: editForm.strategy,
        stop_loss_price: editForm.stop_loss_price,
        take_profit_price: editForm.take_profit_price,
        thesis: editForm.thesis,
        notes: editForm.notes,
      })
      ElMessage.success('持仓已添加')
    }
    editDialogVisible.value = false
    await loadPositions()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

const confirmDelete = async (row: PositionItem) => {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.stock_name}(${row.symbol}) 的持仓记录？`, '确认', { type: 'warning' })
    await portfolioApi.deletePosition(row.id)
    ElMessage.success('已删除')
    await loadPositions()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// 平仓
const closeDialogVisible = ref(false)
const closeTarget = ref<PositionItem | null>(null)
const closing = ref(false)
const closeForm = reactive({
  exit_price: 0,
  exit_date: new Date().toISOString().slice(0, 10),
  exit_reason: 'manual',
})

const openCloseDialog = (row: PositionItem) => {
  closeTarget.value = row
  closeForm.exit_price = row.current_price || row.cost_price
  closeForm.exit_date = new Date().toISOString().slice(0, 10)
  closeForm.exit_reason = 'manual'
  closeDialogVisible.value = true
}

const confirmClose = async () => {
  if (!closeTarget.value) return
  closing.value = true
  try {
    await portfolioApi.closePosition(closeTarget.value.id, {
      exit_price: closeForm.exit_price,
      exit_date: closeForm.exit_date,
      exit_reason: closeForm.exit_reason,
    })
    ElMessage.success('平仓成功')
    closeDialogVisible.value = false
    await loadPositions()
  } catch (e: any) {
    ElMessage.error('平仓失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    closing.value = false
  }
}

// 工具函数
const formatNum = (n: any) => (typeof n === 'number' ? n.toFixed(2) : '0.00')
const formatPct = (n: any) => (typeof n === 'number' ? n.toFixed(2) + '%' : '0.00%')

const strategyNames = ref<Record<string, string>>({})
const strategyLabel = (s: string) => {
  return strategyNames.value[s] || strategyNameSync(s) || s
}

const getStrategyTagType = (s: string) => {
  const map: Record<string, string> = {
    extreme_reversal: 'danger',
    turnaround: 'warning',
    small_cap_value: 'success',
    convertible_arbitrage: 'info',
    ma_golden_cross: 'success',
    tbs: 'success',
    default: '',
  }
  return map[s] || ''
}

// CSV导入
const importDialogVisible = ref(false)
const importing = ref(false)
const importStrategy = ref('default')
const uploadRef = ref<UploadInstance>()
const importFile = ref<File | null>(null)

const openImportDialog = () => {
  importStrategy.value = 'default'
  importFile.value = null
  uploadRef.value?.clearFiles()
  importDialogVisible.value = true
}

const handleFileChange = (file: UploadFile, files: UploadFiles) => {
  if (files.length > 1) {
    files.splice(0, 1)
  }
  importFile.value = file.raw || null
}

const handleExceed = () => {
  ElMessage.warning('只能上传一个文件，请先移除当前文件')
}

const confirmImport = async () => {
  if (!importFile.value) {
    ElMessage.warning('请先选择CSV文件')
    return
  }
  importing.value = true
  try {
    const res: any = await portfolioApi.importCsv(importFile.value, importStrategy.value)
    const importResult = res.data || res
    ElMessage.success(`导入成功：${importResult.success_count} 条` + (importResult.skipped > 0 ? `（跳过 ${importResult.skipped} 行）` : ''))
    importDialogVisible.value = false
    await loadPositions()
  } catch (e: any) {
    ElMessage.error('导入失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadPositions()
  getStrategyNameMap().then((m) => {
    strategyNames.value = m
  })
})

// ============ 交易复盘 ============
const closedLoading = ref(false)
const closedTrades = ref<ClosedTrade[]>([])

const loadClosedTrades = async () => {
  closedLoading.value = true
  try {
    closedTrades.value = await portfolioApi.getClosedTrades()
  } catch (e: any) {
    ElMessage.error('加载已平仓交易失败：' + (e?.message || e))
  } finally {
    closedLoading.value = false
  }
}

// 切换到复盘tab时懒加载（已移除交易复盘tab，保留结构兼容）

// 复盘对话框
const reviewDialogVisible = ref(false)
const reviewTarget = ref<ClosedTrade | null>(null)
const reviewContent = ref('')
const reviewSaving = ref(false)

const openReviewDialog = (row: ClosedTrade) => {
  reviewTarget.value = row
  // 预填复盘模板
  const pnl = row.realized_pnl != null ? `¥${formatNum(row.realized_pnl)}` : '未知'
  const pnlSign = (row.realized_pnl || 0) >= 0 ? '盈利' : '亏损'
  reviewContent.value = [
    '## 买入逻辑回顾',
    row.thesis ? `原投资逻辑：${row.thesis}` : '（未记录买入逻辑）',
    '',
    '## 实际走势',
    `买入价 ${formatNum(row.avg_cost)}，平仓价 ${row.exit_price != null ? formatNum(row.exit_price) : '-'}，${pnlSign} ${pnl}`,
    '',
    '## 失误总结',
    '（哪些判断错了？哪些信号被忽略了？）',
    '',
    '## 经验提炼',
    '（下次遇到类似情况应该怎么做？）',
  ].join('\n')
  reviewDialogVisible.value = true
}

const saveReview = async () => {
  if (!reviewTarget.value || !reviewContent.value.trim()) {
    ElMessage.warning('请填写复盘内容')
    return
  }
  reviewSaving.value = true
  try {
    const t = reviewTarget.value
    await vibeApi.saveNote(
      '交易复盘',
      `${t.stock_name || t.code} 复盘 (${t.exit_date || t.buy_date || ''})`,
      reviewContent.value,
      {
        related_code: t.code,
        related_strategy: t.strategy || 'default',
        related_trade_id: t.id,
      }
    )
    ElMessage.success('复盘已保存到研究记录')
    reviewDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error('保存复盘失败：' + (e?.message || e))
  } finally {
    reviewSaving.value = false
  }
}

// 平仓原因标签
const exitReasonLabel = (r?: string | null) => {
  const map: Record<string, string> = {
    stop_loss: '止损',
    take_profit: '止盈',
    time_stop: '时间止损',
    thesis_invalid: '逻辑证伪',
    sell_order: '卖出',
    manual: '手动',
  }
  return map[r || ''] || r || '-'
}

const getExitReasonTagType = (r?: string | null) => {
  const map: Record<string, string> = {
    stop_loss: 'danger',
    take_profit: 'success',
    time_stop: 'warning',
    thesis_invalid: 'danger',
    sell_order: 'info',
    manual: 'info',
  }
  return map[r || ''] || 'info'
}
</script>

<style lang="scss" scoped>
.portfolio-view {
  padding: 24px;
  max-width: 1600px;
  margin: 0 auto;
}

// ============ 汇总卡片 ============
.summary-row {
  margin-bottom: 20px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
  }

  &--up {
    border-color: rgba(245, 108, 108, 0.3);
    background: linear-gradient(135deg, var(--el-bg-color) 0%, rgba(245, 108, 108, 0.04) 100%);
  }

  &--down {
    border-color: rgba(103, 194, 58, 0.3);
    background: linear-gradient(135deg, var(--el-bg-color) 0%, rgba(103, 194, 58, 0.04) 100%);
  }
}

.summary-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  color: #fff;
  flex-shrink: 0;

  &--blue { background: linear-gradient(135deg, #409eff 0%, #2b6cb0 100%); }
  &--indigo { background: linear-gradient(135deg, #667eea 0%, #5a67d8 100%); }
  &--teal { background: linear-gradient(135deg, #38b2ac 0%, #2c7a7b 100%); }
  &--red { background: linear-gradient(135deg, #f56565 0%, #c53030 100%); }
  &--green { background: linear-gradient(135deg, #48bb78 0%, #2f855a 100%); }
}

.summary-body {
  flex: 1;
  min-width: 0;

  .stat-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
    margin-bottom: 6px;
  }

  .stat-value {
    font-size: 22px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--el-text-color-primary);
  }

  .stat-unit {
    font-size: 14px;
    font-weight: 500;
    color: var(--el-text-color-secondary);
    margin-left: 2px;
  }

  .stat-pct {
    font-size: 13px;
    margin-left: 6px;
    font-weight: 500;
  }
}

.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }

// ============ 持仓面板 ============
.positions-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  overflow: hidden;
}

.positions-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: linear-gradient(135deg, var(--el-fill-color-lighter) 0%, var(--el-bg-color) 100%);

  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .toolbar-count {
    font-size: 14px;
    color: var(--el-text-color-primary);

    strong {
      font-size: 18px;
      color: var(--el-color-primary);
      margin: 0 2px;
    }
  }

  .toolbar-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

.positions-table {
  :deep(.el-table__header th) {
    background: var(--el-fill-color-lighter);
    color: var(--el-text-color-primary);
    font-weight: 600;
    font-size: 13px;
  }

  :deep(.el-table__row td) {
    padding: 10px 0;
  }

  :deep(.el-table__row:hover) {
    background: var(--el-color-primary-light-9) !important;
  }
}

.stock-code {
  color: var(--el-color-primary);
  font-weight: 500;
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.stock-name {
  color: var(--el-text-color-primary);
  text-decoration: none;

  &:hover {
    color: var(--el-color-primary);
    text-decoration: underline;
  }
}

.price-down {
  color: var(--el-color-danger);
  font-weight: 500;
}

.price-up {
  color: var(--el-color-success);
  font-weight: 500;
}

.text-muted {
  color: var(--el-text-color-regular);
}

.review-trade-summary {
  :deep(.el-descriptions) {
    .el-descriptions__label { width: 60px; }
  }
}

// ============ 响应式 ============
@media (max-width: 768px) {
  .portfolio-view {
    padding: 12px;
  }

  .summary-row :deep(.el-col) {
    flex: 0 0 50% !important;
    max-width: 50% !important;
    margin-bottom: 12px;
  }

  .summary-card {
    padding: 14px 16px;
    gap: 12px;

    .summary-icon {
      width: 40px;
      height: 40px;
    }

    .summary-body .stat-value {
      font-size: 18px;
    }
  }

  .positions-toolbar {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;

    .toolbar-actions {
      width: 100%;
      flex-wrap: wrap;
    }
  }

  .positions-table {
    :deep(.el-table) {
      font-size: 13px;
    }
  }
}

@media (max-width: 480px) {
  .summary-row :deep(.el-col) {
    flex: 0 0 100% !important;
    max-width: 100% !important;
  }
}

html.dark {
  .summary-card {
    &--up {
      background: linear-gradient(135deg, var(--el-bg-color) 0%, rgba(245, 108, 108, 0.08) 100%);
    }

    &--down {
      background: linear-gradient(135deg, var(--el-bg-color) 0%, rgba(103, 194, 58, 0.08) 100%);
    }
  }

  .positions-toolbar {
    background: linear-gradient(135deg, var(--el-fill-color) 0%, var(--el-bg-color) 100%);
  }
}
</style>
