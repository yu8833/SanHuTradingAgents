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

    <!-- 两个面板 -->
    <el-tabs v-model="activeTab" class="review-tabs">
      <!-- 交易记录面板 -->
      <el-tab-pane label="交易记录" name="trades">
        <el-table :data="cycles" v-loading="loading" stripe empty-text="暂无已平仓交易">
          <el-table-column prop="code" label="代码" width="100" />
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column prop="strategy" label="策略" width="120">
            <template #default="{ row }">
              <el-tag size="small" v-if="row.strategy">{{ row.strategy }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="buy_price" label="建仓价" width="100" align="right" />
          <el-table-column prop="sell_price" label="平仓价" width="100" align="right" />
          <el-table-column prop="quantity" label="数量" width="90" align="right" />
          <el-table-column prop="pnl" label="盈亏" width="110" align="right">
            <template #default="{ row }">
              <span :class="row.pnl >= 0 ? 'up' : 'down'">{{ row.pnl >= 0 ? '+' : '' }}{{ row.pnl }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="pnl_pct" label="盈亏率" width="100" align="right">
            <template #default="{ row }">
              <span :class="row.pnl >= 0 ? 'up' : 'down'">{{ row.pnl_pct }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="sell_time" label="平仓时间" width="170">
            <template #default="{ row }">{{ formatTime(row.sell_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openAddNote(row)">记录复盘</el-button>
            </template>
          </el-table-column>
        </el-table>
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
              <el-tag size="small" v-if="n.strategy">{{ n.strategy }}</el-tag>
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reviewApi, type ReviewCycleItem, type ReviewNoteItem, type ReviewStats } from '@/api/paper'

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
</style>