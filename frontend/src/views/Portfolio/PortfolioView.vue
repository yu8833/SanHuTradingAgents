<template>
  <div class="portfolio-view">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Wallet /></el-icon>
        持仓追踪
      </h1>
      <p class="page-description">
        统一管理所有策略持仓，支持止损止盈设置、平仓记录、策略表现统计
      </p>
    </div>

    <!-- 汇总卡片 -->
    <el-row :gutter="16" style="margin-bottom:16px;">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-label">持仓数量</div>
            <div class="stat-value">{{ summary?.total_positions || 0 }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-label">总成本</div>
            <div class="stat-value">¥{{ formatNum(summary?.total_cost) }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-label">总市值</div>
            <div class="stat-value">¥{{ formatNum(summary?.total_market_value) }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-label">浮动盈亏</div>
            <div class="stat-value" :class="{ up: (summary?.total_profit_loss || 0) >= 0, down: (summary?.total_profit_loss || 0) < 0 }">
              {{ (summary?.total_profit_loss || 0) >= 0 ? '+' : '' }}¥{{ formatNum(summary?.total_profit_loss) }}
              <span class="stat-pct">({{ formatPct(summary?.profit_loss_rate) }})</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 标签页 -->
    <el-tabs v-model="activeTab" type="border-card">
      <!-- ============ Tab 1: 当前持仓 ============ -->
      <el-tab-pane label="当前持仓" name="positions">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><List /></el-icon>
              <span class="panel-title">当前持仓列表</span>
              <el-button size="small" type="primary" :loading="loading" @click="loadPositions" style="margin-left:auto;">刷新</el-button>
              <el-button size="small" @click="openAddDialog">+ 手动添加</el-button>
              <el-button size="small" type="success" @click="openImportDialog">导入CSV</el-button>
            </div>
          </template>

          <el-table :data="positions" v-loading="loading" stripe border style="width:100%">
            <el-table-column label="代码" width="100" prop="symbol" />
            <el-table-column label="名称" width="100" prop="stock_name" />
            <el-table-column label="策略" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="getStrategyTagType(row.strategy)">{{ strategyLabel(row.strategy) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="90" prop="quantity" />
            <el-table-column label="成本价" width="90">
              <template #default="{ row }">{{ formatNum(row.cost_price) }}</template>
            </el-table-column>
            <el-table-column label="现价" width="90">
              <template #default="{ row }">{{ row.current_price != null ? formatNum(row.current_price) : '-' }}</template>
            </el-table-column>
            <el-table-column label="市值" width="100">
              <template #default="{ row }">{{ row.market_value != null ? '¥' + formatNum(row.market_value) : '-' }}</template>
            </el-table-column>
            <el-table-column label="盈亏" width="110">
              <template #default="{ row }">
                <span v-if="row.profit_loss != null" :class="{ up: row.profit_loss >= 0, down: row.profit_loss < 0 }">
                  {{ row.profit_loss >= 0 ? '+' : '' }}¥{{ formatNum(row.profit_loss) }}
                  <span style="font-size:11px;">({{ formatPct(row.profit_loss_rate) }})</span>
                </span>
                <span v-else style="color:#909399;">-</span>
              </template>
            </el-table-column>
            <el-table-column label="止损价" width="90">
              <template #default="{ row }">
                <span v-if="row.stop_loss_price" style="color:#F56C6C;">{{ formatNum(row.stop_loss_price) }}</span>
                <span v-else style="color:#909399;">未设置</span>
              </template>
            </el-table-column>
            <el-table-column label="止盈价" width="90">
              <template #default="{ row }">
                <span v-if="row.take_profit_price" style="color:#67C23A;">{{ formatNum(row.take_profit_price) }}</span>
                <span v-else style="color:#909399;">未设置</span>
              </template>
            </el-table-column>
            <el-table-column label="买入日期" width="110" prop="buy_date" />
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link @click="openEditDialog(row)">编辑</el-button>
                <el-button size="small" type="warning" link @click="openCloseDialog(row)">平仓</el-button>
                <el-button size="small" type="danger" link @click="confirmDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 2: 策略表现 ============ -->
      <el-tab-pane label="策略表现" name="performance">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><DataLine /></el-icon>
              <span class="panel-title">策略表现统计</span>
              <span class="header-hint">基于已平仓交易记录的真实数据</span>
              <el-button size="small" :loading="perfLoading" @click="loadPerformance" style="margin-left:auto;">刷新</el-button>
            </div>
          </template>

          <el-row :gutter="16">
            <el-col :span="8" v-for="s in strategyKeys" :key="s" style="margin-bottom:16px;">
              <el-card shadow="hover">
                <template #header>
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-weight:600;">{{ strategyLabel(s) }}</span>
                    <el-tag size="small" :type="getStrategyTagType(s)">{{ s }}</el-tag>
                  </div>
                </template>
                <div v-if="perfMap[s]" class="perf-body">
                  <div class="perf-row"><span>交易次数:</span><strong>{{ perfMap[s].total_trades }}</strong></div>
                  <div class="perf-row"><span>胜率:</span><strong :class="{ up: perfMap[s].win_rate >= 0.5, down: perfMap[s].win_rate < 0.5 }">{{ (perfMap[s].win_rate * 100).toFixed(1) }}%</strong></div>
                  <div class="perf-row"><span>平均盈利:</span><strong class="up">¥{{ formatNum(perfMap[s].avg_win) }}</strong></div>
                  <div class="perf-row"><span>平均亏损:</span><strong class="down">¥{{ formatNum(perfMap[s].avg_loss) }}</strong></div>
                  <div class="perf-row"><span>盈亏比:</span><strong>{{ perfMap[s].profit_loss_ratio.toFixed(2) }}</strong></div>
                  <div class="perf-row"><span>平均收益:</span><strong :class="{ up: perfMap[s].avg_return >= 0, down: perfMap[s].avg_return < 0 }">¥{{ formatNum(perfMap[s].avg_return) }}</strong></div>
                </div>
                <div v-else style="color:#909399;text-align:center;padding:20px;">暂无交易数据</div>
              </el-card>
            </el-col>
          </el-row>
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 3: 交易复盘 ============ -->
      <el-tab-pane label="交易复盘" name="reviews">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><EditPen /></el-icon>
              <span class="panel-title">已平仓交易复盘</span>
              <span class="header-hint">回顾每笔交易，沉淀经验，形成学习闭环</span>
              <el-button size="small" :loading="closedLoading" @click="loadClosedTrades" style="margin-left:auto;">刷新</el-button>
            </div>
          </template>

          <el-table :data="closedTrades" v-loading="closedLoading" stripe border style="width:100%">
            <el-table-column label="代码" width="100" prop="code" />
            <el-table-column label="名称" width="100" prop="stock_name" />
            <el-table-column label="策略" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="getStrategyTagType(row.strategy)">{{ strategyLabel(row.strategy) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="买入日" width="110" prop="buy_date" />
            <el-table-column label="平仓日" width="110" prop="exit_date" />
            <el-table-column label="成本价" width="90">
              <template #default="{ row }">{{ formatNum(row.avg_cost) }}</template>
            </el-table-column>
            <el-table-column label="平仓价" width="90">
              <template #default="{ row }">{{ row.exit_price != null ? formatNum(row.exit_price) : '-' }}</template>
            </el-table-column>
            <el-table-column label="盈亏" width="120">
              <template #default="{ row }">
                <span v-if="row.realized_pnl != null" :class="{ up: row.realized_pnl >= 0, down: row.realized_pnl < 0 }">
                  {{ row.realized_pnl >= 0 ? '+' : '' }}¥{{ formatNum(row.realized_pnl) }}
                </span>
                <span v-else style="color:#909399;">-</span>
              </template>
            </el-table-column>
            <el-table-column label="平仓原因" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="getExitReasonTagType(row.exit_reason)">{{ exitReasonLabel(row.exit_reason) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="openReviewDialog(row)">写复盘</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!closedLoading && closedTrades.length === 0" description="暂无已平仓交易记录" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

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
          <el-descriptions-item label="股票">{{ reviewTarget.stock_name }} ({{ reviewTarget.code }})</el-descriptions-item>
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
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadInstance, UploadFile, UploadFiles } from 'element-plus'
import { Wallet, List, DataLine, EditPen } from '@element-plus/icons-vue'
import { portfolioApi, type PositionItem, type PositionSummary, type StrategyPerformance, type AddPositionPayload, type UpdatePositionPayload, type ClosedTrade } from '@/api/portfolio'
import { vibeApi } from '@/api/vibe'

defineOptions({ name: 'PortfolioView' })

const activeTab = ref('positions')
const loading = ref(false)
const positions = ref<PositionItem[]>([])
const summary = ref<PositionSummary | null>(null)

// 策略表现
const perfLoading = ref(false)
const perfMap = ref<Record<string, StrategyPerformance>>({})
const strategyKeys = ['extreme_reversal', 'turnaround', 'small_cap_value', 'convertible_arbitrage', 'default']

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

const loadPerformance = async () => {
  perfLoading.value = true
  try {
    const results: Record<string, StrategyPerformance> = {}
    for (const s of strategyKeys) {
      try {
        const res = await portfolioApi.getStrategyPerformance(s)
        results[s] = res.data
      } catch {
        // 忽略单个策略加载失败
      }
    }
    perfMap.value = results
  } catch (e: any) {
    ElMessage.error('加载策略表现失败：' + (e?.message || e))
  } finally {
    perfLoading.value = false
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

const strategyLabel = (s: string) => {
  const map: Record<string, string> = {
    extreme_reversal: '极端反转',
    turnaround: '困境反转',
    small_cap_value: '小盘价值',
    convertible_arbitrage: '转债套利',
    default: '默认',
  }
  return map[s] || s
}

const getStrategyTagType = (s: string) => {
  const map: Record<string, string> = {
    extreme_reversal: 'danger',
    turnaround: 'warning',
    small_cap_value: 'success',
    convertible_arbitrage: 'info',
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
  loadPerformance()
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

// 切换到复盘tab时懒加载
watch(activeTab, (tab) => {
  if (tab === 'reviews' && closedTrades.value.length === 0) {
    loadClosedTrades()
  }
})

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
.portfolio-view { padding: 16px; }
.page-header { margin-bottom: 16px; }
.page-title {
  font-size: 24px; font-weight: 600; margin: 0 0 8px 0;
  display: flex; align-items: center; gap: 10px;
}
.page-description { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
.stat-card {
  .stat-label { color: var(--el-text-color-secondary); font-size: 13px; margin-bottom: 8px; }
  .stat-value { font-size: 22px; font-weight: 600; }
  .stat-pct { font-size: 13px; margin-left: 6px; }
}
.card-header {
  display: flex; align-items: center; gap: 8px;
  .panel-title { font-weight: 600; }
  .header-hint { color: var(--el-text-color-secondary); font-size: 12px; }
}
.perf-body {
  .perf-row {
    display: flex; justify-content: space-between; padding: 6px 0;
    border-bottom: 1px solid #f0f0f0;
    &:last-child { border-bottom: none; }
  }
}
.up { color: #e6232a; }
.down { color: #19a519; }
.review-trade-summary {
  :deep(.el-descriptions) {
    .el-descriptions__label { width: 60px; }
  }
}
</style>
