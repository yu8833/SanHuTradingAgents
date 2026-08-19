<template>
  <div class="review-page">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-text">
          <h2 class="page-hero-title">交易复盘</h2>
          <p class="page-hero-sub">记录与梳理交易中的各种得失，沉淀经验，反哺策略与规则。</p>
        </div>
      </div>
    </div>

    <!-- 复盘统计 -->
    <el-row :gutter="16" class="stats-row" v-if="stats">
      <el-col :span="5">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">已平仓交易</div>
          <div class="stat-value">{{ stats.total_cycles }}</div>
        </el-card>
      </el-col>
      <el-col :span="5">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">胜率</div>
          <div class="stat-value">{{ (stats.win_rate * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
      <el-col :span="5">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">盈亏比</div>
          <div class="stat-value">{{ stats.profit_loss_ratio.toFixed(2) }}</div>
        </el-card>
      </el-col>
      <el-col :span="5">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">累计盈亏</div>
          <div class="stat-value" :class="stats.total_pnl >= 0 ? 'up' : 'down'">
            {{ stats.total_pnl >= 0 ? '+' : '' }}{{ stats.total_pnl.toFixed(2) }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">复盘笔记</div>
          <div class="stat-value">{{ notes.length }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 三个面板 -->
    <el-tabs v-model="activeTab" class="review-tabs">
      <!-- 交易记录面板 -->
      <el-tab-pane label="交易记录" name="trades">
        <el-table :data="cycles" v-loading="loading" stripe empty-text="暂无已平仓交易" class="app-table app-table--trades">
          <el-table-column label="代码" width="100">
            <template #default="{ row }">
              <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
            </template>
          </el-table-column>
          <el-table-column label="名称" min-width="120">
            <template #default="{ row }">
              <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name || '-' }}</router-link>
            </template>
          </el-table-column>
          <el-table-column prop="strategy" label="策略" width="110">
            <template #default="{ row }">
              <el-tag size="small" v-if="row.strategy">{{ strategyLabel(row.strategy) }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="交易原因" min-width="220">
            <template #default="{ row }">
              <span class="reason-text">{{ row.reason || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="buy_price" label="建仓价" width="100" align="right" sortable />
          <el-table-column prop="sell_price" label="平仓价" width="100" align="right" sortable />
          <el-table-column prop="quantity" label="数量" width="90" align="right" sortable />
          <el-table-column prop="pnl" label="盈亏" width="110" align="right" sortable>
            <template #default="{ row }">
              <span :class="row.pnl >= 0 ? 'up' : 'down'">{{ row.pnl >= 0 ? '+' : '' }}{{ row.pnl }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="pnl_pct" label="盈亏率" width="100" align="right" sortable>
            <template #default="{ row }">
              <span :class="row.pnl >= 0 ? 'up' : 'down'">{{ row.pnl_pct }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="sell_time" label="平仓时间" width="170">
            <template #default="{ row }">{{ formatTime(row.sell_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openAddNote(row)">记录复盘</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 策略收益率分析 -->
      <el-tab-pane label="策略收益率" name="strategy">
        <div class="strategy-returns" v-if="strategyReturns.length > 0">
          <el-row :gutter="16">
            <el-col :span="8" v-for="s in strategyReturns" :key="s.strategy" style="margin-bottom: 16px;">
              <el-card shadow="hover" class="strategy-card">
                <template #header>
                  <div class="strategy-card-header">
                    <span class="strategy-name">{{ s.label }}</span>
                    <el-tag size="small" :type="getStrategyTagType(s.strategy)">{{ s.strategy || '默认' }}</el-tag>
                  </div>
                </template>
                <div class="strategy-card-body">
                  <div class="return-hero">
                    <div class="return-hero-label">累计收益率</div>
                    <div class="return-hero-value" :class="s.total_return >= 0 ? 'up' : 'down'">
                      {{ s.total_return >= 0 ? '+' : '' }}{{ s.total_return.toFixed(2) }}%
                    </div>
                  </div>
                  <div class="return-stats">
                    <div class="return-stat">
                      <span class="rs-label">交易次数</span>
                      <span class="rs-value">{{ s.count }}</span>
                    </div>
                    <div class="return-stat">
                      <span class="rs-label">胜率</span>
                      <span class="rs-value" :class="s.win_rate >= 50 ? 'up' : 'down'">{{ s.win_rate.toFixed(1) }}%</span>
                    </div>
                    <div class="return-stat">
                      <span class="rs-label">累计盈亏</span>
                      <span class="rs-value" :class="s.total_pnl >= 0 ? 'up' : 'down'">
                        {{ s.total_pnl >= 0 ? '+' : '' }}{{ s.total_pnl.toFixed(2) }}
                      </span>
                    </div>
                    <div class="return-stat">
                      <span class="rs-label">平均收益</span>
                      <span class="rs-value" :class="s.avg_return >= 0 ? 'up' : 'down'">
                        {{ s.avg_return >= 0 ? '+' : '' }}{{ s.avg_return.toFixed(2) }}%
                      </span>
                    </div>
                    <div class="return-stat">
                      <span class="rs-label">最大盈利</span>
                      <span class="rs-value up">+{{ s.max_win.toFixed(2) }}%</span>
                    </div>
                    <div class="return-stat">
                      <span class="rs-label">最大亏损</span>
                      <span class="rs-value down">{{ s.max_loss.toFixed(2) }}%</span>
                    </div>
                  </div>
                  <div class="return-bar" v-if="s.count > 0">
                    <div class="bar-track">
                      <div class="bar-fill up" :style="{ width: Math.min(s.win_rate, 100) + '%' }"></div>
                    </div>
                    <div class="bar-label">盈亏分布</div>
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
        <el-empty v-else description="暂无策略收益数据" />
      </el-tab-pane>

      <!-- 复盘笔记面板 -->
      <el-tab-pane label="复盘笔记" name="notes">
        <div class="notes-toolbar">
          <el-button type="primary" size="small" @click="openAddNote()">+ 新增复盘</el-button>
        </div>
        <el-empty v-if="!loading && notes.length === 0" description="暂无复盘笔记" />
        <el-card v-for="n in notes" :key="n.id" shadow="never" class="note-card">
          <div class="note-head">
            <div class="note-title">
              <el-tag size="small" type="warning" v-if="n.result">{{ resultLabel(n.result) }}</el-tag>
              <span class="note-subject">{{ n.code ? (n.name || n.code) : '自由记录' }}</span>
              <el-tag size="small" v-if="n.strategy">{{ strategyLabel(n.strategy) }}</el-tag>
            </div>
            <div class="note-actions">
              <el-button size="small" text @click="openEditNote(n)">编辑</el-button>
              <el-button size="small" text type="danger" @click="removeNote(n)">删除</el-button>
            </div>
          </div>
          <div class="note-body" v-if="n.lesson">
            <div class="note-field"><span class="field-label">教训</span>{{ n.lesson }}</div>
          </div>
          <div class="note-body" v-if="n.improvement">
            <div class="note-field"><span class="field-label">改进</span>{{ n.improvement }}</div>
          </div>
          <div class="note-tags" v-if="n.tags && n.tags.length">
            <el-tag v-for="t in n.tags" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
          <div class="note-time">{{ formatTime(n.updated_at) }}</div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 复盘笔记弹窗 -->
    <el-dialog v-model="noteDialogVisible" :title="editingId ? '编辑复盘' : '新增复盘'" width="560px">
      <el-form :model="noteForm" label-width="80px">
        <el-form-item label="股票代码">
          <el-input v-model="noteForm.code" placeholder="可空，留空表示自由记录" />
        </el-form-item>
        <el-form-item label="交易结果">
          <el-select v-model="noteForm.result" placeholder="选择交易结果归因" clearable style="width:100%">
            <el-option
              v-for="opt in resultOptions"
              :key="opt"
              :label="resultLabel(opt)"
              :value="opt"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="经验教训">
          <el-input v-model="noteForm.lesson" type="textarea" :rows="3" placeholder="本次交易的经验教训…" />
        </el-form-item>
        <el-form-item label="改进计划">
          <el-input v-model="noteForm.improvement" type="textarea" :rows="3" placeholder="下次如何改进…" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="noteForm.tags" multiple filterable allow-create default-first-option
            placeholder="纪律/心态/仓位/择时" style="width:100%">
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { reviewApi, type ReviewCycleItem, type ReviewNoteItem, type ReviewStats } from '@/api/paper'
import { getStrategyNameMap, strategyNameSync } from '@/utils/strategyName'

defineOptions({ name: 'PaperReview' })

const activeTab = ref('trades')
const loading = ref(false)
const saving = ref(false)
const cycles = ref<ReviewCycleItem[]>([])
const notes = ref<ReviewNoteItem[]>([])
const stats = ref<ReviewStats | null>(null)
const resultOptions = ref<string[]>([])

const noteDialogVisible = ref(false)
const editingId = ref<string | null>(null)
const noteForm = reactive({
  code: '',
  result: '',
  lesson: '',
  improvement: '',
  tags: [] as string[]
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
    stats.value = statsRes.data
    resultOptions.value = statsRes.data?.result_options || []
    // 预载策略名称映射，保证店铺展示与「常用策略」名称对齐
    getStrategyNameMap().then((m) => {
      strategyNames.value = m
    })
  } catch (e) {
    ElMessage.error('加载交易复盘数据失败')
  } finally {
    loading.value = false
  }
}

function openAddNote(row?: ReviewCycleItem) {
  editingId.value = null
  noteForm.code = row?.code || ''
  noteForm.result = ''
  noteForm.lesson = ''
  noteForm.improvement = ''
  noteForm.tags = []
  noteDialogVisible.value = true
}

function openEditNote(n: ReviewNoteItem) {
  editingId.value = n.id || null
  noteForm.code = n.code || ''
  noteForm.result = n.result || ''
  noteForm.lesson = n.lesson || ''
  noteForm.improvement = n.improvement || ''
  noteForm.tags = n.tags || []
  noteDialogVisible.value = true
}

async function saveNote() {
  saving.value = true
  try {
    const payload = {
      code: noteForm.code || null,
      result: noteForm.result || null,
      lesson: noteForm.lesson || null,
      improvement: noteForm.improvement || null,
      tags: noteForm.tags
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

onMounted(loadAll)

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

function getStrategyTagType(s: string) {
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
</script>

<style scoped>
.review-page {
  padding: 24px;
  max-width: 1280px;
  margin: 0 auto;
}
.stats-row {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
}
.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.stat-value {
  font-size: 24px;
  font-weight: 600;
  margin-top: 4px;
}
.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }
.notes-toolbar {
  margin-bottom: 12px;
  text-align: right;
}
.note-card {
  margin-bottom: 12px;
}
.note-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.note-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.note-subject {
  font-weight: 600;
}
.note-body {
  margin-top: 8px;
}
.note-field {
  font-size: 14px;
  line-height: 1.6;
}
.field-label {
  display: inline-block;
  width: 44px;
  color: var(--el-text-color-secondary);
}
.note-tags {
  margin-top: 8px;
  display: flex;
  gap: 6px;
}
.note-time {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.strategy-returns {
  .strategy-card {
    height: 100%;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    &:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
    }
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

  .strategy-card-body {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .return-hero {
    text-align: center;
    padding: 14px 10px;
    border-radius: 10px;
    background: linear-gradient(135deg, rgba(43, 108, 176, 0.08) 0%, rgba(43, 108, 176, 0.02) 100%);
    border: 1px solid var(--el-border-color-lighter);

    .return-hero-label {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      margin-bottom: 4px;
    }

    .return-hero-value {
      font-size: 32px;
      font-weight: 700;
      font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
      letter-spacing: -0.5px;

      &.up { color: var(--el-color-danger); }
      &.down { color: var(--el-color-success); }
    }
  }

  .return-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;

    .return-stat {
      display: flex;
      flex-direction: column;
      padding: 8px;
      background: var(--el-fill-color-lighter);
      border-radius: 6px;

      .rs-label {
        font-size: 11px;
        color: var(--el-text-color-secondary);
        margin-bottom: 2px;
      }

      .rs-value {
        font-size: 14px;
        font-weight: 600;
        font-family: 'Menlo', 'Monaco', monospace;

        &.up { color: var(--el-color-danger); }
        &.down { color: var(--el-color-success); }
      }
    }
  }

  .return-bar {
    .bar-track {
      height: 6px;
      background: var(--el-fill-color-lighter);
      border-radius: 3px;
      overflow: hidden;

      .bar-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.4s ease;

        &.up { background: var(--el-color-danger); }
        &.down { background: var(--el-color-success); }
      }
    }

    .bar-label {
      font-size: 11px;
      color: var(--el-text-color-secondary);
      margin-top: 4px;
    }
  }
}

@media (max-width: 768px) {
  .strategy-returns {
    .return-stats {
      grid-template-columns: repeat(2, 1fr);
    }

    .return-hero .return-hero-value {
      font-size: 26px;
    }
  }
}
</style>