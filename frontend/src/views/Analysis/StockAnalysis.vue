<template>
  <div class="stock-analysis app-page">
    <!-- 页面头部 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Document /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">股票分析</h2>
          <p class="page-hero-sub">
            AI 驱动的智能股票分析，多维度评估投资价值与风险
          </p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-tag v-if="stockCount > 0" class="page-hero-tag" effect="plain">
          {{ stockCount }} 只股票
        </el-tag>
      </div>
    </div>

    <!-- 工作台：左（分析配置）与右（模型配置）等高对齐 -->
    <div class="workbench">
      <!-- 左侧：股票代码 + 分析配置 + 开始分析 融合为一张操作卡片 -->
      <el-card shadow="hover" class="analyze-card">
        <!-- ① 股票代码 -->
        <div class="panel-section code-section">
          <div class="section-head">
            <span class="section-label">股票代码</span>
            <span class="section-count" :class="{ warn: stockCount > 10 }">
              <strong>{{ stockCount }}</strong> 只
            </span>
          </div>
          <el-input
            v-model="stockInput"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 9 }"
            placeholder="每行输入一只，最多 10 只"
            :disabled="submitting"
            @input="onInputChange"
          />
          <div class="code-tips">
            <span>兼容格式：000001 · 600519.SH · AAPL · 0700.HK</span>
            <span v-if="stockCount > 10" class="warn">上限 10 只</span>
          </div>
        </div>

        <!-- ② 分析配置（深度 + 因子 一体化） -->
        <div class="config-panel">
          <div class="config-row">
            <span class="config-label">分析深度</span>
            <el-radio-group v-model="analysisMode" class="mode-group">
              <el-radio-button label="quick">速览</el-radio-button>
              <el-radio-button label="deep">深度</el-radio-button>
            </el-radio-group>
          </div>
          <div class="config-row">
            <span class="config-label">分析因子</span>
            <div class="factor-group">
              <el-checkbox v-model="includeSentiment" border class="factor-checkbox">
                <span>情绪</span>
              </el-checkbox>
              <el-checkbox v-model="includeRisk" border class="factor-checkbox">
                <span>风险</span>
              </el-checkbox>
            </div>
          </div>
          <p class="config-hint">
            {{ analysisMode === 'quick'
              ? '速览：快速输出核心结论，耗时更短'
              : '深度：完整多智能体论证链，结论更充分' }}
          </p>
        </div>

        <!-- ③ 开始分析：全宽主操作，锚定卡片底部 -->
        <div class="submit-bar">
          <el-button
            class="submit-btn"
            type="primary"
            :loading="submitting"
            :disabled="stockCount === 0"
            @click="submitAnalysis"
          >
            <el-icon v-if="!submitting"><CaretRight /></el-icon>
            {{ submitting
              ? '分析中...'
              : (mode === 'batch' ? `开始批量分析 · ${stockCount} 只` : '开始分析') }}
          </el-button>
          <span v-if="stockCount === 0" class="submit-hint">请先输入股票代码</span>
        </div>
      </el-card>

      <!-- 右侧：模型配置 -->
      <el-card shadow="hover" class="model-card">
        <template #header>
          <div class="card-header">
            <h3>模型配置</h3>
            <el-tag type="warning" size="small" effect="plain">高级</el-tag>
          </div>
        </template>
        <ModelConfig
          v-model:quick-analysis-model="modelSettings.quickAnalysisModel"
          v-model:deep-analysis-model="modelSettings.deepAnalysisModel"
          :available-models="availableModels"
        />
      </el-card>
    </div>

    <!-- 进度区域 -->
    <el-card v-if="progressVisible" shadow="hover" class="progress-card">
      <template #header>
        <div class="card-header progress-header">
          <h3>
            <el-icon v-if="batchProgress.status !== 'completed'" class="running-icon"><Loading /></el-icon>
            <el-icon v-else class="done-icon"><CircleCheck /></el-icon>
            {{ batchProgress.status === 'completed' ? '分析完成' : '分析中...' }}
          </h3>
          <div class="progress-stats">
            <el-tag type="success" size="small">{{ batchProgress.completed_tasks }} 完成</el-tag>
            <el-tag type="warning" size="small">{{ batchProgress.running_tasks }} 运行中</el-tag>
            <el-tag type="danger" size="small">{{ batchProgress.failed_tasks }} 失败</el-tag>
          </div>
        </div>
      </template>

      <!-- 总进度条 -->
      <el-progress
        :percentage="batchProgress.progress"
        :status="batchProgress.status === 'completed' ? 'success' : undefined"
        :stroke-width="18"
        :text-inside="true"
      />

      <!-- 子任务 -->
      <div v-if="batchProgress.tasks.length > 0" class="subtask-grid">
        <div
          v-for="task in batchProgress.tasks"
          :key="task.task_id || task.symbol"
          class="subtask-item"
          :class="'subtask-' + task.status"
        >
          <div class="subtask-head">
            <span class="subtask-symbol">{{ task.symbol }}</span>
            <el-tag :type="subtaskTagType(task.status)" size="small" effect="plain">
              {{ subtaskLabel(task.status) }}
            </el-tag>
          </div>
          <el-progress
            :percentage="task.progress"
            :stroke-width="8"
            :show-text="false"
          />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { analysisApi, type BatchProgress } from '@/api/analysis'
import { configApi } from '@/api/config'
import ModelConfig from '@/components/ModelConfig.vue'
import { Document, CaretRight, Loading, CircleCheck } from '@element-plus/icons-vue'

const route = useRoute()
const authStore = useAuthStore()

// ── State ──────────────────────────────────────────────
const stockInput = ref('')
const stockCodes = ref<string[]>([])
const submitting = ref(false)
const analysisMode = ref<'deep' | 'quick'>('deep')
const includeSentiment = ref(true)
const includeRisk = ref(true)
const availableModels = ref<any[]>([])
const modelSettings = ref({
  quickAnalysisModel: 'qwen-plus',
  deepAnalysisModel: 'qwen-max'
})

const progressVisible = ref(false)
const batchProgress = reactive<BatchProgress>({
  batch_id: '',
  status: 'pending',
  total_tasks: 0,
  completed_tasks: 0,
  failed_tasks: 0,
  cancelled_tasks: 0,
  running_tasks: 0,
  progress: 0,
  tasks: []
})

let sseController: AbortController | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let singlePollTimer: ReturnType<typeof setInterval> | null = null

// ── Computed ───────────────────────────────────────────
const stockCount = computed(() => stockCodes.value.length)
const mode = computed(() => stockCount.value > 1 ? 'batch' : 'single')

const onInputChange = () => {
  const lines = stockInput.value
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.length > 0)
    .filter((v, i, a) => a.indexOf(v) === i)
  stockCodes.value = lines
}

const getAuthToken = (): string | null => {
  return authStore.token || localStorage.getItem('auth-token')
}
const getBaseUrl = (): string => {
  return import.meta.env.VITE_API_BASE_URL || ''
}

const subtaskTagType = (status: string): 'success' | 'danger' | 'warning' | 'info' => {
  const map: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
    completed: 'success', failed: 'danger', cancelled: 'info',
    running: 'warning', processing: 'warning', queued: 'info', pending: 'info'
  }
  return map[status] || 'info'
}
const subtaskLabel = (status: string): string => {
  const map: Record<string, string> = {
    pending: '待命', processing: '运行', running: '运行', queued: '排队',
    completed: '完成', failed: '失败', cancelled: '中止'
  }
  return map[status] || status
}

// ── SSE ────────────────────────────────────────────────
const subscribeBatchProgress = (batchId: string) => {
  const token = getAuthToken()
  if (!token) return
  const baseUrl = getBaseUrl()
  const controller = new AbortController()
  sseController = controller

  const connect = async () => {
    try {
      const resp = await fetch(`${baseUrl}/api/analysis/batches/${batchId}/events`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal
      })
      if (!resp.ok || !resp.body) throw new Error(`SSE HTTP ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let event = 'message'
      let dataLines: string[] = []

      const dispatch = () => {
        const raw = dataLines.join('\n')
        dataLines = []
        if (event === 'progress' && raw) {
          try { Object.assign(batchProgress, JSON.parse(raw) as BatchProgress) } catch { /* ignore */ }
        } else if (event === 'done') {
          cleanup()
        }
        event = 'message'
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const t = line.replace(/\r$/, '')
          if (t === '') { dispatch(); continue }
          if (t.startsWith('event:')) { event = t.slice(6).trim(); continue }
          if (t.startsWith('data:')) { dataLines.push(t.slice(5).replace(/^ /, '')); continue }
        }
      }
    } catch (e: any) {
      if (e.name === 'AbortError') return
      console.warn('[StockAnalysis] SSE 中断，切轮询兜底', e)
    }
  }
  connect()
}

// ── 轮询兜底 ───────────────────────────────────────────
const startPolling = (batchId: string) => {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res = await analysisApi.getBatchProgress(batchId)
      if (res?.success && res.data) {
        Object.assign(batchProgress, res.data)
        if (['completed', 'failed', 'partial_success', 'cancelled'].includes(res.data.status)) stopPolling()
      }
    } catch { /* ignore */ }
  }, 3000)
}
const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
const cleanup = () => {
  if (sseController) { sseController.abort(); sseController = null }
  stopPolling()
  if (singlePollTimer) { clearInterval(singlePollTimer); singlePollTimer = null }
}

// ── 提交 ───────────────────────────────────────────────
const buildParams = () => ({
  mode: analysisMode.value,
  include_sentiment: includeSentiment.value,
  include_risk: includeRisk.value,
  quick_analysis_model: modelSettings.value.quickAnalysisModel,
  deep_analysis_model: modelSettings.value.deepAnalysisModel
})

const submitAnalysis = async () => {
  if (stockCount.value === 0) return
  if (mode.value === 'batch' && stockCount.value > 10) {
    ElMessage.warning('单次批量分析最多支持 10 只股票')
    return
  }

  submitting.value = true
  progressVisible.value = true
  Object.assign(batchProgress, {
    status: 'pending', progress: 0, completed_tasks: 0, failed_tasks: 0, running_tasks: 0, tasks: []
  })

  try {
    if (mode.value === 'single') {
      const symbol = stockCodes.value[0]
      const res = await analysisApi.startSingleAnalysis({ symbol, parameters: buildParams() })
      if (!res?.success) throw new Error(res?.message || '提交失败')
      const taskId = res.data?.task_id
      if (!taskId) throw new Error('未返回 task_id')

      batchProgress.batch_id = ''
      batchProgress.total_tasks = 1
      batchProgress.tasks = [{ task_id: taskId, symbol, status: 'processing', progress: 0 }]

      singlePollTimer = setInterval(async () => {
        try {
          const s = await analysisApi.getTaskStatus(taskId)
          if (s?.success && s.data) {
            const d = s.data
            const task = batchProgress.tasks[0]
            if (task) { task.status = d.status; task.progress = d.progress || 0 }
            batchProgress.progress = d.progress || 0
            batchProgress.completed_tasks = d.status === 'completed' ? 1 : 0
            batchProgress.failed_tasks = d.status === 'failed' ? 1 : 0
            batchProgress.running_tasks = ['pending', 'processing', 'running', 'queued'].includes(d.status) ? 1 : 0
            batchProgress.status = d.status === 'completed' ? 'completed' : (d.status === 'failed' ? 'failed' : 'processing')
            if (['completed', 'failed', 'cancelled'].includes(d.status)) {
              if (singlePollTimer) { clearInterval(singlePollTimer); singlePollTimer = null }
            }
          }
        } catch { /* ignore */ }
      }, 2000)
    } else {
      const res = await analysisApi.startBatchAnalysis({
        title: `批量分析 ${new Date().toLocaleString('zh-CN')}`,
        symbols: [...stockCodes.value],
        parameters: buildParams()
      })
      if (!res?.success) throw new Error(res?.message || '提交失败')
      const batchId = res.data?.batch_id
      if (!batchId) throw new Error('未返回 batch_id')

      batchProgress.batch_id = batchId
      batchProgress.total_tasks = res.data?.total_tasks || stockCount.value
      batchProgress.tasks = stockCodes.value.map(s => ({ task_id: '', symbol: s, status: 'pending', progress: 0 }))

      subscribeBatchProgress(batchId)
      startPolling(batchId)
    }
  } catch (e: any) {
    ElMessage.error(e.message || '分析提交失败')
    progressVisible.value = false
  } finally {
    submitting.value = false
  }
}

// ── 初始化 ─────────────────────────────────────────────
onMounted(async () => {
  try {
    const defaults = await configApi.getDefaultModels()
    if (defaults) {
      modelSettings.value.quickAnalysisModel = defaults.quick_analysis_model
      modelSettings.value.deepAnalysisModel = defaults.deep_analysis_model
    }
    const llmConfigs = await configApi.getLLMConfigs()
    if (Array.isArray(llmConfigs)) {
      availableModels.value = llmConfigs
        .filter((c: any) => c.enabled)
        .sort((a: any, b: any) => {
          const ta = a.created_at ? new Date(a.created_at).getTime() : 0
          const tb = b.created_at ? new Date(b.created_at).getTime() : 0
          return tb - ta
        })
    }
  } catch { /* 用默认值 */ }

  const q = route.query as any
  if (q?.stocks) {
    const parts = String(q.stocks).split(',').map((s: string) => s.trim()).filter(Boolean)
    stockCodes.value = parts
    stockInput.value = parts.join('\n')
  }
})

onUnmounted(cleanup)
</script>

<style lang="scss" scoped>
.stock-analysis {
  // ── 工作台：左右两张卡片等高对齐 ──
  .workbench {
    display: flex;
    align-items: stretch;
    gap: 24px;
  }

  // ── 左侧统一卡片（股票代码 + 分析配置 + 开始分析 融合）──
  .analyze-card {
    flex: 2 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background:
      radial-gradient(1200px 220px at 50% -60px, rgba(43, 108, 176, .06), transparent 70%),
      var(--el-bg-color);

    :deep(.el-card__body) {
      display: flex;
      flex-direction: column;
      flex: 1;
    }

    // ── ① 股票代码 ──
    .code-section {
      .section-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;

        .section-label {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          position: relative;
          padding-left: 10px;

          &::before {
            content: '';
            position: absolute;
            left: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 3px;
            height: 14px;
            border-radius: 2px;
            background: var(--el-color-primary);
          }
        }

        .section-count {
          font-size: 12px;
          color: var(--el-text-color-secondary);

          strong {
            font-size: 15px;
            color: var(--el-color-primary);
            font-variant-numeric: tabular-nums;
          }
          &.warn strong { color: var(--el-color-warning); }
        }
      }

      :deep(.el-textarea__inner) {
        border-radius: 10px;
        font-family: var(--app-font-mono);
        font-size: 13.5px;
        letter-spacing: .3px;
        line-height: 1.7;
        padding: 12px 14px;
      }

      .code-tips {
        margin-top: 8px;
        font-size: 12px;
        color: var(--el-text-color-placeholder);
        display: flex;
        gap: 10px;

        .warn { color: var(--el-color-warning); font-weight: 600; }
      }
    }

    // ── ② 分析配置（深度 + 因子 一体化面板）──
    .config-panel {
      margin-top: 20px;
      padding: 16px 18px;
      border-radius: var(--app-radius);
      border: 1px solid var(--el-border-color-lighter);
      background: var(--el-fill-color-lighter);

      .config-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 16px;

        &:last-of-type { margin-bottom: 0; }

        .config-label {
          flex-shrink: 0;
          font-size: 13px;
          font-weight: 500;
          color: var(--el-text-color-secondary);
        }
      }

      // 分析深度：等宽分段
      .mode-group {
        flex: 1;
        display: flex;

        .el-radio-button { flex: 1; }
        .el-radio-button__inner {
          width: 100%;
          padding: 10px 16px;
          display: inline-flex;
          justify-content: center;
          align-items: center;
          font-weight: 600;
        }
      }

      // 分析因子：等宽复选
      .factor-group {
        flex: 1;
        display: flex;
        gap: 12px;
      }

      .factor-checkbox {
        flex: 1;
        margin: 0;
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;

        span { font-size: 13.5px; font-weight: 500; }
      }

      .config-hint {
        margin: 12px 0 0;
        font-size: 12px;
        color: var(--el-text-color-placeholder);
      }
    }

    // ── ③ 开始分析：全宽主操作，锚定卡片底部 ──
    .submit-bar {
      margin-top: auto;
      padding-top: 18px;
      border-top: 1px solid var(--el-border-color-lighter);
      display: flex;
      align-items: center;
      gap: 14px;

      .submit-btn {
        flex: 1;
        height: 46px;
        font-size: 15px;
        font-weight: 600;
        letter-spacing: 1px;
        border-radius: 10px;
        background: linear-gradient(120deg, #2b6cb0, #2c5282);
        border: none;
        box-shadow: 0 6px 16px rgba(44, 82, 130, .28);
        transition: transform .15s ease, box-shadow .2s ease, filter .15s ease;
        overflow: hidden;

        &:hover:not(.is-disabled) {
          transform: translateY(-1px);
          box-shadow: 0 10px 22px rgba(44, 82, 130, .34);
          filter: brightness(1.05);
        }
        &:active:not(.is-disabled) {
          transform: translateY(0);
          box-shadow: none;
        }

        .el-icon { margin-right: 4px; }
      }

      .submit-hint {
        flex-shrink: 0;
        font-size: 13px;
        color: var(--el-text-color-placeholder);
      }
    }
  }

  // ── 右侧：模型配置 ──
  .model-card {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
    }
  }

  // ── 响应式：窄屏两张卡片上下堆叠 ──
  @media (max-width: 992px) {
    .workbench {
      flex-direction: column;
    }
    .analyze-card,
    .model-card {
      flex: none;
      width: 100%;
    }
  }

  // ── 进度卡片 ──
  .progress-card {
    margin-top: 8px;

    .progress-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      h3 {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0;
      }
    }

    .running-icon {
      color: var(--el-color-primary);
      animation: spin 1.5s linear infinite;
    }
    .done-icon {
      color: var(--el-color-success);
    }

    .progress-stats {
      display: flex;
      gap: 6px;
    }

    .subtask-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }

    .subtask-item {
      padding: 12px;
      border: 1px solid var(--el-border-color-light);
      border-radius: var(--app-radius);
      background: var(--el-fill-color-light);

      &.subtask-completed {
        border-color: var(--el-color-success);
        background: var(--el-color-success-light-9);
      }
      &.subtask-failed {
        border-color: var(--el-color-danger);
        background: var(--el-color-danger-light-9);
      }
      &.subtask-processing,
      &.subtask-running,
      &.subtask-queued {
        border-color: var(--el-color-warning);
        background: var(--el-color-warning-light-9);
      }

      .subtask-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }

      .subtask-symbol {
        font-size: 14px;
        font-weight: 700;
        font-family: var(--app-font-mono);
        color: var(--el-text-color-primary);
      }
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>