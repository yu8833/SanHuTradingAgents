<template>
  <div class="single-analysis">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Document /></el-icon>
            单股分析
          </h1>
          <p class="page-description">
            AI驱动的智能股票分析，多维度评估投资价值与风险
          </p>
        </div>
      </div>
    </div>

    <!-- 主要分析表单 -->
    <div class="analysis-container">
      <el-row :gutter="24" class="form-row">
        <!-- 左侧：基础配置 -->
        <el-col :span="18" class="form-col">
          <el-card class="main-form-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>分析配置</h3>
                <el-tag type="info" size="small">必填信息</el-tag>
              </div>
            </template>

            <el-form :model="analysisForm" label-width="100px" class="analysis-form">
              <!-- 股票信息 -->
              <div class="form-section">
                <h4 class="section-title">📊 股票信息</h4>
                <el-row :gutter="16">
                  <el-col :span="12">
                    <el-form-item label="股票代码" required>
                      <el-input
                        v-model="analysisForm.stockCode"
                        placeholder="如：000001、AAPL、700、1810"
                        clearable
                        size="large"
                        class="stock-input"
                        :class="{ 'is-error': stockCodeError }"
                        @blur="validateStockCodeInput"
                        @input="onStockCodeInput"
                      >
                        <template #prefix>
                          <el-icon><TrendCharts /></el-icon>
                        </template>
                      </el-input>
                      <div v-if="stockCodeError" class="error-message">
                        <el-icon><WarningFilled /></el-icon>
                        {{ stockCodeError }}
                      </div>
                      <div v-else-if="stockCodeHelp" class="help-message">
                        <el-icon><InfoFilled /></el-icon>
                        {{ stockCodeHelp }}
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="市场类型">
                      <el-select
                        v-model="analysisForm.market"
                        placeholder="选择市场"
                        size="large"
                        style="width: 100%"
                        @change="onMarketChange"
                      >
                        <el-option label="🇨🇳 A股市场" value="A股">
                          <span>🇨🇳 A股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（6位数字）</span>
                        </el-option>
                        <el-option label="🇺🇸 美股市场" value="美股">
                          <span>🇺🇸 美股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5个字母）</span>
                        </el-option>
                        <el-option label="🇭🇰 港股市场" value="港股">
                          <span>🇭🇰 港股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5位数字）</span>
                        </el-option>
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-form-item label="分析日期">
                  <el-date-picker
                    v-model="analysisForm.analysisDate"
                    type="date"
                    placeholder="选择分析基准日期"
                    size="large"
                    style="width: 100%"
                    :disabled-date="disabledDate"
                  />
                </el-form-item>
              </div>

              <!-- 操作按钮 -->
              <div class="form-section">
                <div class="action-buttons" style="display: flex; justify-content: center; align-items: center; width: 100%; text-align: center;">
                  <el-button
                    v-if="analysisStatus === 'idle'"
                    type="primary"
                    size="large"
                    @click="submitAnalysis"
                    :loading="submitting"
                    :disabled="!analysisForm.stockCode.trim()"
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><TrendCharts /></el-icon>
                    开始智能分析
                  </el-button>

                  <el-button
                    v-else-if="analysisStatus === 'running'"
                    type="warning"
                    size="large"
                    disabled
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><Loading /></el-icon>
                    分析进行中...
                  </el-button>

                  <div v-else-if="analysisStatus === 'completed'" style="display: flex; gap: 12px;">
                    <el-button
                      type="success"
                      size="large"
                      @click="goToReportDetail"
                      class="submit-btn"
                      style="width: 180px; height: 56px; font-size: 16px; font-weight: 700; border-radius: 16px;"
                    >
                      <el-icon><Document /></el-icon>
                      查看完整报告
                    </el-button>

                    <el-button
                      type="primary"
                      size="large"
                      @click="restartAnalysis"
                      class="submit-btn"
                      style="width: 180px; height: 56px; font-size: 16px; font-weight: 700; border-radius: 16px;"
                    >
                      <el-icon><Refresh /></el-icon>
                      重新分析
                    </el-button>
                  </div>

                  <el-button
                    v-else-if="analysisStatus === 'failed'"
                    type="danger"
                    size="large"
                    @click="restartAnalysis"
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><Refresh /></el-icon>
                    重新分析
                  </el-button>
                </div>
              </div>

              <!-- 分析进度显示 -->
              <div v-if="analysisStatus === 'running'" class="progress-section">
                <el-card class="progress-card" shadow="hover">
                  <template #header>
                    <div class="progress-header">
                      <h4>
                        <el-icon class="rotating-icon">
                          <Loading />
                        </el-icon>
                        分析进行中...
                      </h4>
                      <!-- 任务ID已隐藏 -->
                      <!-- <el-tag type="warning">{{ currentTaskId }}</el-tag> -->
                    </div>
                  </template>

                  <div class="progress-content">
                    <!-- 总体进度信息 -->
                    <div class="overall-progress-info">
                      <div class="progress-stats">
                        <!-- 当前步骤已隐藏 -->
                        <!--
                        <div class="stat-item">
                          <div class="stat-label">当前步骤</div>
                          <div class="stat-value">{{ progressInfo.currentStep || '初始化中...' }}</div>
                        </div>
                        -->
                        <!-- 整体进度已隐藏 -->
                        <!--
                        <div class="stat-item">
                          <div class="stat-label">整体进度</div>
                          <div class="stat-value">{{ progressInfo.progress.toFixed(1) }}%</div>
                        </div>
                        -->
                        <div class="stat-item">
                          <div class="stat-label">已用时间</div>
                          <div class="stat-value">{{ formatTime(progressInfo.elapsedTime) }}</div>
                        </div>
                        <div class="stat-item">
                          <div class="stat-label">预计剩余</div>
                          <div class="stat-value">{{ formatTime(progressInfo.remainingTime) }}</div>
                        </div>
                        <div class="stat-item">
                          <div class="stat-label">预计总时长</div>
                          <div class="stat-value">{{ formatTime(progressInfo.totalTime) }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- 进度条 -->
                    <div class="progress-bar-section">
                      <el-progress
                        :percentage="Math.round(progressInfo.progress)"
                        :stroke-width="12"
                        :show-text="true"
                        :status="getProgressStatus()"
                        class="main-progress-bar"
                      />
                    </div>

                    <!-- 当前任务详情 -->
                    <div class="current-task-info">
                      <div class="task-title">
                        <el-icon class="task-icon">
                          <Loading />
                        </el-icon>
                        {{ progressInfo.currentStep || '正在初始化分析引擎...' }}
                      </div>
                      <div
                        class="task-description"
                        style="white-space: pre-wrap; line-height: 1.6;"
                      >
                        {{ progressInfo.currentStepDescription || progressInfo.message || 'AI正在根据您的要求重点分析相关内容' }}
                      </div>
                    </div>

                    <!-- 分析步骤显示 - 已隐藏 -->
                    <!--
                    <div v-if="analysisSteps.length > 0" class="analysis-steps">
                      <h5 class="steps-title">📋 分析步骤</h5>
                      <div class="steps-container">
                        <div
                          v-for="(step, index) in analysisSteps"
                          :key="index"
                          class="step-item"
                          :class="{
                            'step-completed': step.status === 'completed',
                            'step-current': step.status === 'current',
                            'step-pending': step.status === 'pending'
                          }"
                        >
                          <div class="step-icon">
                            <el-icon v-if="step.status === 'completed'" class="completed-icon">
                              <Check />
                            </el-icon>
                            <el-icon v-else-if="step.status === 'current'" class="current-icon rotating-icon">
                              <Loading />
                            </el-icon>
                            <el-icon v-else class="pending-icon">
                              <Clock />
                            </el-icon>
                          </div>
                          <div class="step-content">
                            <div class="step-title">{{ step.title }}</div>
                            <div class="step-description">{{ step.description }}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                    -->
                  </div>
                </el-card>
              </div>
            </el-form>
          </el-card>
        </el-col>

        <!-- 右侧：高级配置 -->
        <el-col :span="6" class="form-col">
          <el-card class="config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>高级配置</h3>
                <el-tag type="warning" size="small">可选设置</el-tag>
              </div>
            </template>

            <div class="config-content">
              <!-- AI模型配置 -->
              <div class="config-section">
                <h4 class="config-title">🤖 AI模型配置</h4>
                <div class="model-config">
                  <div class="model-item">
                    <div class="model-label">
                      <span>快速分析模型</span>
                      <el-tooltip content="用于市场分析、新闻分析、基本面分析等" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="modelSettings.quickAnalysisModel" size="small" style="width: 100%" filterable>
                      <el-option
                        v-for="model in availableModels"
                        :key="`quick-${model.provider}/${model.model_name}`"
                        :label="model.model_display_name || model.model_name"
                        :value="model.model_name"
                      >
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                          <span style="flex: 1;">{{ model.model_display_name || model.model_name }}</span>
                          <div style="display: flex; align-items: center; gap: 4px;">
                            <!-- 能力等级徽章 -->
                            <el-tag
                              v-if="model.capability_level"
                              :type="getCapabilityTagType(model.capability_level)"
                              size="small"
                              effect="plain"
                            >
                              {{ getCapabilityText(model.capability_level) }}
                            </el-tag>
                            <!-- 角色标签 -->
                            <el-tag
                              v-if="isQuickAnalysisRole(model.suitable_roles)"
                              type="success"
                              size="small"
                              effect="plain"
                            >
                              ⚡快速
                            </el-tag>
                            <span style="font-size: 12px; color: #909399;">{{ model.provider }}</span>
                          </div>
                        </div>
                      </el-option>
                    </el-select>
                  </div>

                  <div class="model-item">
                    <div class="model-label">
                      <span>深度决策模型</span>
                      <el-tooltip content="用于研究管理者综合决策、风险管理者最终评估" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <DeepModelSelector v-model="modelSettings.deepAnalysisModel" :available-models="availableModels" type="deep" size="small" width="100%" />
                  </div>
                </div>
              </div>

              <!-- 分析选项 -->
              <div class="config-section">
                <h4 class="config-title">⚙️ 分析选项</h4>
                <div class="option-list">
                  <div class="option-item">
                    <div class="option-info">
                      <span class="option-name">情绪分析</span>
                      <span class="option-desc">分析市场情绪和投资者心理</span>
                    </div>
                    <el-switch v-model="analysisForm.includeSentiment" />
                  </div>

                  <div class="option-item">
                    <div class="option-info">
                      <span class="option-name">风险评估</span>
                      <span class="option-desc">包含详细的风险因素分析</span>
                    </div>
                    <el-switch v-model="analysisForm.includeRisk" />
                  </div>

                  <div class="option-item">
                    <div class="option-info">
                      <span class="option-name">语言偏好</span>
                    </div>
                    <el-select v-model="analysisForm.language" size="small" style="width: 100px">
                      <el-option label="中文" value="zh-CN" />
                      <el-option label="English" value="en-US" />
                    </el-select>
                  </div>
                </div>
              </div>

            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 功能介绍 -->
    <div class="intro-section">
      <el-card class="intro-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <h3>✨ 功能介绍</h3>
          </div>
        </template>
        <div class="intro-content">
          <div class="intro-item">
            <div class="intro-icon">📊</div>
            <div class="intro-text">
              <h4>多维度评分</h4>
              <p>从技术面、基本面、情绪面、消息面、资金面、政策面等多个维度对股票进行综合评估，每项评分0-100分</p>
            </div>
          </div>
          <div class="intro-item">
            <div class="intro-icon">👥</div>
            <div class="intro-text">
              <h4>7位AI分析师团队</h4>
              <p>技术分析师、市场情绪分析师、新闻分析师、基本面分析师、政策分析师、游资追踪师、解禁追踪师并行研究</p>
            </div>
          </div>
          <div class="intro-item">
            <div class="intro-icon">⚔️</div>
            <div class="intro-text">
              <h4>多空辩论 · 三方风控 · 决策建议</h4>
              <p>看涨/看跌研究员进行辩论，研究经理综合裁决；激进/中性/保守三个风控视角；最终给出可操作的投资建议</p>
            </div>
          </div>
          <div class="intro-item">
            <div class="intro-icon">📈</div>
            <div class="intro-text">
              <h4>置信度评估</h4>
              <p>基于报告数据丰富度、评级一致性、分析师覆盖度等因素，综合计算分析结果的置信度评分</p>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, ElInputNumber } from 'element-plus'
import {
  Document,
  TrendCharts,
  InfoFilled,
  Check,
  Loading,
  Refresh,
  Download,
  CreditCard,
  WarningFilled,
  Cpu,
  QuestionFilled,
  ArrowDown,
} from '@element-plus/icons-vue'
import { analysisApi, type SingleAnalysisRequest } from '@/api/analysis'
import { paperApi } from '@/api/paper'
import { stocksApi } from '@/api/stocks'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { configApi } from '@/api/config'
import DeepModelSelector from '@/components/DeepModelSelector.vue'
import { convertAnalystNamesToIds } from '@/constants/analysts'
import { marked } from 'marked'
import { validateStockCode, getStockCodeFormatHelp } from '@/utils/stockValidator'
import { normalizeMarketForAnalysis, getMarketByStockCode } from '@/utils/market'

// 配置marked选项
marked.setOptions({
  breaks: true,        // 支持换行符转换为<br>
  gfm: true           // 启用GitHub风格的Markdown
})

// 市场类型定义
type MarketType = 'A股' | '美股' | '港股'

// 表单类型定义
interface AnalysisForm {
  stockCode: string
  symbol: string
  market: MarketType
  analysisDate: Date
  selectedAnalysts: string[]
  includeSentiment: boolean
  includeRisk: boolean
  language: 'zh-CN' | 'en-US'
}

// 使用store
const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const submitting = ref(false)

// 分析进度和结果相关状态
const currentTaskId = ref('')
const analysisStatus = ref('idle') // 'idle', 'running', 'completed', 'failed'
const showResults = ref(false)
const analysisResults = ref<any>(null)
const activeReportTab = ref('') // 当前激活的报告标签页
const progressInfo = ref({
  progress: 0,
  currentStep: '',
  currentStepDescription: '',  // 当前步骤描述
  message: '',
  elapsedTime: 0,      // 已用时间（秒）
  remainingTime: 0,    // 预计剩余时间（秒）
  totalTime: 0         // 预计总时长（秒）
})
const pollingTimer = ref<any>(null)

// 分析步骤定义（动态生成）
const analysisSteps = ref<any[]>([])

// 从后端步骤数据生成前端步骤
const generateStepsFromBackend = (backendSteps: any[]) => {
  if (!backendSteps || !Array.isArray(backendSteps)) {
    return []
  }

  return backendSteps.map((step: any, index: number) => ({
    key: `step_${index}`,
    title: step.name || `步骤 ${index + 1}`,
    description: step.description || '处理中...',
    status: 'pending'
  }))
}

// 模型设置
const modelSettings = ref({
  quickAnalysisModel: 'qwen-turbo',
  deepAnalysisModel: 'qwen-max'
})

// 可用的模型列表（从配置中获取）
const availableModels = ref<any[]>([])

// 🆕 模型推荐提示
const modelRecommendation = ref<{
  title: string
  message: string
  type: 'success' | 'warning' | 'info' | 'error'
  quickModel?: string
  deepModel?: string
} | null>(null)

// 分析表单
const analysisForm = reactive<AnalysisForm>({
  stockCode: '',
  symbol: '',
  market: 'A股',
  analysisDate: new Date(),
  // 默认启用全部 7 位分析师
  selectedAnalysts: [
    '技术分析师',
    '市场情绪分析师',
    '新闻分析师',
    '基本面分析师',
    '政策分析师',
    '游资追踪师',
    '解禁追踪师'
  ],
  includeSentiment: true,
  includeRisk: true,
  language: 'zh-CN'
})

// 股票代码验证相关
const stockCodeError = ref<string>('')
const stockCodeHelp = ref<string>('')

// 禁用日期
const disabledDate = (time: Date) => {
  return time.getTime() > Date.now()
}

// 股票代码输入时的处理
const onStockCodeInput = () => {
  // 清除错误信息
  stockCodeError.value = ''
  // 显示格式提示
  stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
}

// 市场类型变更时的处理
const onMarketChange = () => {
  // 重新验证股票代码
  if (analysisForm.stockCode.trim()) {
    validateStockCodeInput()
  } else {
    // 显示新市场的格式提示
    stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
  }
}

// 验证股票代码输入
const validateStockCodeInput = () => {
  const code = analysisForm.stockCode.trim()

  if (!code) {
    stockCodeError.value = ''
    stockCodeHelp.value = ''
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(code, analysisForm.market)

  if (!validation.valid) {
    stockCodeError.value = validation.message || '股票代码格式不正确'
    stockCodeHelp.value = ''
  } else {
    stockCodeError.value = ''
    stockCodeHelp.value = `✓ ${validation.market}代码格式正确`

    // 自动更新市场类型（如果识别出的市场与当前选择不同）
    if (validation.market && validation.market !== analysisForm.market) {
      analysisForm.market = validation.market
      ElMessage.success(`已自动识别为${validation.market}`)
    }

    // 标准化代码
    if (validation.normalizedCode) {
      analysisForm.stockCode = validation.normalizedCode
    }
  }

  // 获取股票信息
  fetchStockInfo()
}

// 获取股票信息
const fetchStockInfo = () => {
  // TODO: 实现股票信息获取
}

// 切换分析师
// 已废弃：分析师默认全部启用，前端不提供勾选界面
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const toggleAnalyst = (_analystName: string) => {
  // no-op
}

// 提交分析
const submitAnalysis = async () => {
  const stockCode = analysisForm.stockCode.trim()
  if (!stockCode) {
    ElMessage.warning('请输入股票代码')
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(stockCode, analysisForm.market)
  if (!validation.valid) {
    ElMessage.error(validation.message || '股票代码格式不正确')
    stockCodeError.value = validation.message || '股票代码格式不正确'
    return
  }

  // 使用标准化后的代码
  analysisForm.symbol = validation.normalizedCode || stockCode.toUpperCase()

  // 默认启用全部 7 位分析师，无需选择校验

  submitting.value = true

  try {
    // 确保 analysisDate 是 Date 对象
    const analysisDate = analysisForm.analysisDate instanceof Date
      ? analysisForm.analysisDate
      : new Date(analysisForm.analysisDate)

    const request: SingleAnalysisRequest = {
      symbol: analysisForm.symbol,
      stock_code: analysisForm.symbol,
      parameters: {
        market_type: analysisForm.market,
        analysis_date: analysisDate.toISOString().split('T')[0],
        selected_analysts: convertAnalystNamesToIds(analysisForm.selectedAnalysts),
        include_sentiment: analysisForm.includeSentiment,
        include_risk: analysisForm.includeRisk,
        language: analysisForm.language,
        quick_analysis_model: modelSettings.value.quickAnalysisModel,
        deep_analysis_model: modelSettings.value.deepAnalysisModel
      }
    }

    const response = await analysisApi.startSingleAnalysis(request)

    console.log('🔍 分析响应数据:', response)
    console.log('🔍 响应数据结构:', response.data)
    console.log('🔍 任务ID:', response.data?.task_id)

    ElMessage.success('分析任务已提交，正在处理中...')

    // 响应拦截器已返回 response.data，所以直接访问 response.data.task_id
    currentTaskId.value = response.data.task_id

    if (!currentTaskId.value) {
      console.error('❌ 任务ID为空:', response)
      ElMessage.error('任务ID获取失败，请重试')
      return
    }

    console.log('✅ 任务ID设置成功:', currentTaskId.value)

    // 保存任务状态到缓存
    saveTaskToCache(currentTaskId.value, {
      parameters: { ...analysisForm },
      submitTime: new Date().toISOString()
    })

    analysisStatus.value = 'running'
    showResults.value = false
    progressInfo.value = {
      progress: 0,
      currentStep: '正在初始化分析...',
      currentStepDescription: '分析任务已提交，正在启动分析流程',
      message: '分析任务已提交，正在启动分析流程',
      elapsedTime: 0,
      remainingTime: 0,
      totalTime: 0
    }

    // 初始化空的步骤列表，等待后端数据
    analysisSteps.value = []

    // 开始轮询任务状态
    startPollingTaskStatus()

    // 立即查询一次状态（不等待第一次轮询）
    setTimeout(async () => {
      try {
        const response = await analysisApi.getTaskStatus(currentTaskId.value)
        const status = response.data // 响应拦截器已返回 response.data
        console.log('🔄 立即查询状态:', status)
        console.log('🔄 当前 analysisStatus:', analysisStatus.value)
        if (status.status === 'running') {
          analysisStatus.value = 'running'
          console.log('✅ 设置 analysisStatus 为 running')
          updateProgressInfo(status)
        }
      } catch (error) {
        console.error('立即查询状态失败:', error)
      }
    }, 1000) // 1秒后查询

  } catch (error: any) {
    ElMessage.error(error.message || '提交分析失败')
  } finally {
    submitting.value = false
  }
}

// 轮询任务状态
const startPollingTaskStatus = () => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
  }

  // 检查任务ID是否有效
  if (!currentTaskId.value) {
    console.error('❌ 任务ID为空，无法开始轮询')
    return
  }

  console.log('🔄 开始轮询任务状态:', currentTaskId.value)

  pollingTimer.value = setInterval(async () => {
    try {
      if (!currentTaskId.value) {
        console.error('❌ 轮询中任务ID为空')
        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
        }
        return
      }

      console.log('🔄 开始查询任务状态:', currentTaskId.value)
      const response = await analysisApi.getTaskStatus(currentTaskId.value)
      const status = response.data // 响应拦截器已返回 response.data

      console.log('🔍 任务状态响应:', response)
      console.log('🔍 任务状态数据:', status)
      console.log('🔍 当前状态:', status.status, '进度:', status.progress)

      if (status.status === 'completed') {
        // 分析完成，调用专门的结果API获取完整数据
        console.log('🎉 分析完成，正在获取完整结果...')

        try {
          const resultResponse = await fetch(`/api/analysis/tasks/${currentTaskId.value}/result`, {
            headers: {
              'Authorization': `Bearer ${authStore.token}`,
              'Content-Type': 'application/json'
            }
          })

          if (resultResponse.ok) {
            const resultData = await resultResponse.json()
            if (resultData.success) {
              analysisResults.value = resultData.data
              console.log('✅ 获取完整分析结果成功:', resultData.data)

              // 添加调试信息
              console.log('🔍 完整结果数据结构:', {
                hasDecision: !!resultData.data?.decision,
                hasState: !!resultData.data?.state,
                hasReports: !!resultData.data?.reports,
                hasSummary: !!resultData.data?.summary,
                hasRecommendation: !!resultData.data?.recommendation,
                keys: Object.keys(resultData.data || {})
              })
            } else {
              console.error('❌ 获取分析结果失败:', resultData.message)
              analysisResults.value = status.result_data // 回退到状态中的数据
            }
          } else {
            console.error('❌ 结果API调用失败:', resultResponse.status)
            analysisResults.value = status.result_data // 回退到状态中的数据
          }
        } catch (error) {
          console.error('❌ 获取分析结果异常:', error)
          analysisResults.value = status.result_data // 回退到状态中的数据
        }

        analysisStatus.value = 'completed'
        showResults.value = true
        progressInfo.value.progress = 100
        progressInfo.value.currentStep = '分析完成'
        progressInfo.value.message = '分析已完成！'

        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
          pollingTimer.value = null
        }

        // 任务完成后保持缓存，以便刷新后能看到结果
        // clearTaskCache() // 不清除，让用户能在30分钟内刷新查看结果

        ElMessage.success('分析完成！')

      } else if (status.status === 'failed') {
        // 分析失败
        analysisStatus.value = 'failed'
        progressInfo.value.currentStep = '分析失败'

        // 格式化错误消息（保留换行符）
        const errorMessage = status.error_message || '分析过程中发生错误'
        progressInfo.value.message = errorMessage

        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
          pollingTimer.value = null
        }

        // 任务失败时清除缓存
        clearTaskCache()

        // 显示友好的错误提示（使用 dangerouslyUseHTMLString 支持换行）
        ElMessage({
          type: 'error',
          message: errorMessage.replace(/\n/g, '<br>'),
          dangerouslyUseHTMLString: true,
          duration: 10000, // 显示10秒，让用户有时间阅读
          showClose: true
        })

      } else if (status.status === 'running') {
        // 分析进行中，更新进度
        console.log('🔄 轮询中设置 analysisStatus 为 running')
        analysisStatus.value = 'running'
        updateProgressInfo(status)
      }

    } catch (error) {
      console.error('获取任务状态失败:', error)
      // 继续轮询，不中断
    }
  }, 5000) // 每5秒轮询一次
}

// 更新进度信息
const updateProgressInfo = (status: any) => {
  console.log('🔄 更新进度信息:', status)
  console.log('🔄 当前进度信息:', progressInfo.value)

  // 使用后端返回的实际进度数据
  if (status.progress !== undefined) {
    console.log('📊 更新进度:', status.progress)
    progressInfo.value.progress = status.progress
  }

  if (status.current_step_name) {
    console.log('📋 更新步骤:', status.current_step_name)
    progressInfo.value.currentStep = status.current_step_name
  }

  if (status.current_step_description) {
    console.log('📝 更新步骤描述:', status.current_step_description)
    progressInfo.value.currentStepDescription = status.current_step_description
  }

  if (status.message) {
    console.log('💬 更新消息:', status.message)
    progressInfo.value.message = status.message
  }

  // 接收后端返回的时间数据
  if (status.elapsed_time !== undefined) {
    progressInfo.value.elapsedTime = status.elapsed_time
  }

  if (status.remaining_time !== undefined) {
    progressInfo.value.remainingTime = status.remaining_time
  }

  if (status.estimated_total_time !== undefined) {
    progressInfo.value.totalTime = status.estimated_total_time
  }

  // 如果后端提供了步骤数据，更新步骤列表
  if (status.steps && Array.isArray(status.steps)) {
    if (analysisSteps.value.length === 0) {
      // 首次生成步骤列表
      analysisSteps.value = generateStepsFromBackend(status.steps)
      console.log('📋 从后端生成步骤列表:', analysisSteps.value.length, '个步骤')
    }
  }

  console.log('🔄 更新后进度信息:', progressInfo.value)

  // 更新分析步骤状态
  updateAnalysisSteps(status)

  // 前端不进行估算，只展示后端返回的数据
  progressInfo.value.message = status.message || '分析正在进行中...'
}

// 重新开始分析
const goToReportDetail = () => {
  const reportId = analysisResults.value?.id || currentTaskId.value
  if (reportId) {
    router.push(`/reports/view/${reportId}`)
  }
}

const restartAnalysis = () => {
  // 清除任务缓存
  clearTaskCache()

  analysisStatus.value = 'idle'
  showResults.value = false
  analysisResults.value = null
  currentTaskId.value = ''
  progressInfo.value = {
    progress: 0,
    currentStep: '',
    currentStepDescription: '',
    message: '',
    elapsedTime: 0,
    remainingTime: 0,
    totalTime: 0
  }

  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}


// 获取操作标签类型
const getActionTagType = (action: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  const actionTypes: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    '买入': 'success',
    '持有': 'warning',
    '卖出': 'danger',
    '观望': 'info'
  }
  return actionTypes[action] || 'info'
}

// 获取分析报告
const getAnalysisReports = (data: any) => {
  console.log('📊 getAnalysisReports 输入数据:', data)
  const reports: Array<{title: string, content: any}> = []

  // 优先从 reports 字段获取数据（新的API格式）
  let reportsData = data
  if (data && data.reports && typeof data.reports === 'object') {
    reportsData = data.reports
    console.log('📊 使用 data.reports:', reportsData)
  } else if (data && data.state && typeof data.state === 'object') {
    reportsData = data.state
    console.log('📊 使用 data.state:', reportsData)
  } else {
    console.log('📊 没有找到有效的报告数据')
    return reports
  }

  // 定义报告映射（按照完整的分析流程顺序）
  const reportMappings = [
    // 分析师团队 (7个)
    { key: 'market_report', title: '📈 市场技术分析', category: '分析师团队' },
    { key: 'sentiment_report', title: '💭 市场情绪分析', category: '分析师团队' },
    { key: 'news_report', title: '📰 新闻事件分析', category: '分析师团队' },
    { key: 'fundamentals_report', title: '💰 基本面分析', category: '分析师团队' },
    { key: 'policy_report', title: '🏛️ 政策分析', category: '分析师团队' },
    { key: 'hot_money_report', title: '💹 游资追踪分析', category: '分析师团队' },
    { key: 'lockup_report', title: '🔒 限售解禁分析', category: '分析师团队' },

    // 研究团队 (3个)
    { key: 'bull_researcher', title: '🐂 看涨研究员', category: '研究团队' },
    { key: 'bear_researcher', title: '🐻 看跌研究员', category: '研究团队' },
    { key: 'research_team_decision', title: '👔 研究经理决策', category: '研究团队' },

    // 交易团队 (1个)
    { key: 'trader_investment_plan', title: '💼 交易员投资计划', category: '交易团队' },

    // 风险管理团队 (5个)
    { key: 'risky_analyst', title: '🔥 激进风险分析', category: '风险管理团队' },
    { key: 'safe_analyst', title: '🛡️ 保守风险分析', category: '风险管理团队' },
    { key: 'neutral_analyst', title: '⚖️ 中性风险分析', category: '风险管理团队' },
    { key: 'risk_control_decision', title: '📋 风控约束决策', category: '风险管理团队' },
    { key: 'risk_management_decision', title: '👔 风险经理决策', category: '风险管理团队' },

    // 最终决策 (1个)
    { key: 'final_trade_decision', title: '🎯 决策建议', category: '最终决策' },

    // 数据质量
    { key: 'data_quality_summary', title: '📊 数据质量评估', category: '数据质量' },
    { key: 'quality_gate', title: '🚦 数据质量门控', category: '数据质量' },

    // 兼容旧格式
    { key: 'investment_plan', title: '📋 投资建议', category: '其他' },
    { key: 'investment_debate_state', title: '🔬 研究团队决策（旧）', category: '其他' },
    { key: 'risk_debate_state', title: '⚖️ 风险管理团队（旧）', category: '其他' }
  ]

  // 遍历所有可能的报告
  reportMappings.forEach(mapping => {
    const content = reportsData[mapping.key]
    if (content) {
      console.log(`📊 找到报告: ${mapping.key} -> ${mapping.title}`)
      reports.push({
        title: mapping.title,
        content: content
      })
    }
  })

  console.log(`📊 总共找到 ${reports.length} 个报告`)

  // 设置第一个报告为默认激活标签页
  if (reports.length > 0 && !activeReportTab.value) {
    activeReportTab.value = '0'
  }

  return reports
}

// 获取报告图标
const getReportIcon = (title: string) => {
  const iconMap: Record<string, string> = {
    '📈 市场技术分析': '📈',
    '💰 基本面分析': '💰',
    '📰 新闻事件分析': '📰',
    '💭 市场情绪分析': '💭',
    '📋 投资建议': '📋',
    '🔬 研究团队决策': '🔬',
    '💼 交易团队计划': '💼',
    '⚖️ 风险管理团队': '⚖️',
    '🎯 决策建议': '🎯'
  }
  return iconMap[title] || '📊'
}

// 获取报告名称（去掉图标）
const getReportName = (title: string) => {
  return title.replace(/^[^\s]+\s/, '')
}

// 获取报告描述
const getReportDescription = (title: string) => {
  const descMap: Record<string, string> = {
    '📈 市场技术分析': '技术指标、价格趋势、支撑阻力位分析',
    '💰 基本面分析': '财务数据、估值水平、盈利能力分析',
    '📰 新闻事件分析': '相关新闻事件、市场动态影响分析',
    '💭 市场情绪分析': '投资者情绪、社交媒体情绪指标',
    '📋 投资建议': '具体投资策略、仓位管理建议',
    '🔬 研究团队决策': '多头/空头研究员辩论分析，研究经理综合决策',
    '💼 交易团队计划': '专业交易员制定的具体交易执行计划',
    '⚖️ 风险管理团队': '激进/保守/中性分析师风险评估，投资组合经理最终决策',
    '🎯 决策建议': '综合所有团队分析后的最终投资决策'
  }
  return descMap[title] || '详细分析报告'
}

// 格式化报告内容
const formatReportContent = (content: any) => {
  console.log('🎨 [DEBUG] formatReportContent 被调用:', {
    content: content,
    type: typeof content,
    length: typeof content === 'string' ? content.length : 'N/A'
  })

  // 确保content是字符串类型
  if (!content) {
    console.log('⚠️ [DEBUG] content为空，返回空字符串')
    return ''
  }

  // 如果content不是字符串，转换为字符串
  let stringContent = ''
  if (typeof content === 'string') {
    stringContent = content
    console.log('✅ [DEBUG] content是字符串，长度:', stringContent.length)
  } else if (typeof content === 'object') {
    // 如果是对象，尝试提取有用信息
    if (content.judge_decision) {
      stringContent = content.judge_decision
      console.log('📝 [DEBUG] 从对象中提取judge_decision')
    } else {
      stringContent = JSON.stringify(content, null, 2)
      console.log('📝 [DEBUG] 将对象转换为JSON字符串')
    }
  } else {
    stringContent = String(content)
    console.log('📝 [DEBUG] 将内容转换为字符串')
  }

  try {
    // 使用marked库将Markdown转换为HTML
    const htmlContent = marked.parse(stringContent) as string

    console.log('🎨 [DEBUG] Marked转换完成，HTML长度:', htmlContent.length)
    console.log('🎨 [DEBUG] HTML前200字符:', htmlContent.substring(0, 200))

    return htmlContent
  } catch (error) {
    console.error('❌ [ERROR] Marked转换失败:', error)
    // 如果marked转换失败，回退到简单的文本显示
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${stringContent}</pre>`
  }
}

// 下载报告
const downloadReport = async (format: string = 'markdown') => {
  try {
    if (!analysisResults.value && !currentTaskId.value) {
      ElMessage.error('报告尚未生成，无法下载')
      return
    }

    // 显示加载提示
    const loadingMsg = ElMessage({
      message: `正在生成${getFormatName(format)}格式报告...`,
      type: 'info',
      duration: 0
    })

    const reportId = (analysisResults.value?.id as any) || currentTaskId.value
    const res = await fetch(`/api/reports/${reportId}/download?format=${format}`, {
      headers: {
        'Authorization': `Bearer ${authStore.token}`
      }
    })

    loadingMsg.close()

    if (!res.ok) {
      const errorText = await res.text()
      throw new Error(errorText || `HTTP ${res.status}`)
    }

    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const code =
      analysisResults.value?.stock_code ||
      analysisResults.value?.stock_symbol ||
      analysisResults.value?.symbol ||
      'stock'
    const dateStr = analysisResults.value?.analysis_date || new Date().toISOString().slice(0, 10)

    // 根据格式设置文件扩展名
    const ext = getFileExtension(format)
    a.download = `${String(code)}_分析报告_${String(dateStr).slice(0, 10)}.${ext}`

    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    ElMessage.success(`${getFormatName(format)}报告下载成功`)
  } catch (err: any) {
    console.error('下载报告出错:', err)

    // 显示详细错误信息
    if (err.message && err.message.includes('pandoc')) {
      ElMessage.error({
        message: 'PDF/Word 导出需要安装 pandoc 工具',
        duration: 5000
      })
    } else {
      ElMessage.error(`下载报告失败: ${err.message || '未知错误'}`)
    }
  }
}

// 辅助函数：获取格式名称
const getFormatName = (format: string): string => {
  const names: Record<string, string> = {
    'markdown': 'Markdown',
    'docx': 'Word',
    'pdf': 'PDF',
    'json': 'JSON'
  }
  return names[format] || format
}

// 辅助函数：获取文件扩展名
const getFileExtension = (format: string): string => {
  const extensions: Record<string, string> = {
    'markdown': 'md',
    'docx': 'docx',
    'pdf': 'pdf',
    'json': 'json'
  }
  return extensions[format] || 'txt'
}

// 解析投资建议
const parseRecommendation = () => {
  if (!analysisResults.value) return null

  // 从多个可能的字段中提取投资建议
  const rec = analysisResults.value.recommendation ||
              analysisResults.value.summary ||
              analysisResults.value.decision?.action || ''

  const traderPlan = analysisResults.value.reports?.trader_investment_plan || ''
  const allReports = Object.values(analysisResults.value.reports || {}).join(' ')

  // 解析操作类型
  let action: 'buy' | 'sell' | null = null
  const recStr = String(rec).toLowerCase()
  const allText = (recStr + ' ' + String(traderPlan).toLowerCase() + ' ' + allReports.toLowerCase())

  if (allText.includes('买入') || allText.includes('buy') || allText.includes('增持')) {
    action = 'buy'
  } else if (allText.includes('卖出') || allText.includes('sell') || allText.includes('减持')) {
    action = 'sell'
  }

  if (!action) return null

  // 解析目标价格
  let targetPrice: number | null = null
  const priceMatch = allText.match(/目标价[格]?[：:]\s*([0-9.]+)/) ||
                     allText.match(/价格[：:]\s*([0-9.]+)/)
  if (priceMatch) {
    targetPrice = parseFloat(priceMatch[1])
  }

  // 解析置信度
  const confidence = analysisResults.value.decision?.confidence ||
                    analysisResults.value.confidence_score ||
                    0

  // 解析风险等级
  const riskLevel = analysisResults.value.risk_level ||
                   analysisResults.value.decision?.risk_level ||
                   '中等'

  return {
    action,
    targetPrice,
    confidence: typeof confidence === 'number' ? confidence : 0,
    riskLevel: String(riskLevel)
  }
}

// 一键模拟下单（应用到交易）
const goSimOrder = async () => {
  try {
    if (!analysisResults.value) {
      ElMessage.warning('暂无可用的分析结果')
      return
    }

    // 获取股票代码（兼容新旧字段）
    const code = analysisResults.value.symbol ||
                 analysisResults.value.stock_symbol ||
                 analysisResults.value.stock_code ||
                 analysisForm.symbol ||
                 analysisForm.stockCode
    if (!code) {
      ElMessage.warning('未识别到股票代码')
      return
    }

    // 解析投资建议
    const recommendation = parseRecommendation()
    if (!recommendation) {
      ElMessage.warning('无法解析投资建议，请检查分析结果')
      return
    }

    // 获取账户信息
    const accountRes = await paperApi.getAccount()
    if (!accountRes.success || !accountRes.data) {
      ElMessage.error('获取账户信息失败')
      return
    }

    const account = accountRes.data.account
    const positions = accountRes.data.positions

    // 查找当前持仓
    const currentPosition = positions.find(p => p.code === code)

    // 获取当前实时价格
    let currentPrice = 10 // 默认价格
    try {
      const quoteRes = await stocksApi.getQuote(code)
      if (quoteRes.success && quoteRes.data && quoteRes.data.price) {
        currentPrice = quoteRes.data.price
      }
    } catch (error) {
      console.warn('获取实时价格失败，使用默认价格')
    }

    // 计算建议交易数量
    let suggestedQuantity = 0
    let maxQuantity = 0

    if (recommendation.action === 'buy') {
      // 买入：根据可用资金和当前价格计算
      const availableCash = account.cash
      maxQuantity = Math.floor(Number(availableCash) / Number(currentPrice) / 100) * 100 // 100股为单位
      const suggested = Math.floor(maxQuantity * 0.2) // 建议使用20%资金
      suggestedQuantity = Math.floor(suggested / 100) * 100 // 向下取整到100的倍数
      suggestedQuantity = Math.max(100, suggestedQuantity) // 至少100股
    } else {
      // 卖出：根据当前持仓计算
      if (!currentPosition || currentPosition.quantity === 0) {
        ElMessage.warning('当前没有持仓，无法卖出')
        return
      }
      maxQuantity = currentPosition.quantity
      suggestedQuantity = Math.floor(maxQuantity / 100) * 100 // 向下取整到100的倍数
      suggestedQuantity = Math.max(100, suggestedQuantity) // 至少100股
    }

    // 用户可修改的价格和数量（使用reactive）
    const tradeForm = reactive({
      price: currentPrice,
      quantity: suggestedQuantity
    })

    // 显示可编辑的确认对话框
    const actionText = recommendation.action === 'buy' ? '买入' : '卖出'
    const actionColor = recommendation.action === 'buy' ? '#67C23A' : '#F56C6C'

    // 创建一个响应式的消息组件
    const MessageComponent = {
      setup() {
        // 计算预计金额
        const estimatedAmount = computed(() => {
          return (tradeForm.price * tradeForm.quantity).toFixed(2)
        })

        return () => h('div', { style: 'line-height: 2;' }, [
          h('p', [
            h('strong', '股票代码：'),
            h('span', code)
          ]),
          h('p', [
            h('strong', '操作类型：'),
            h('span', { style: `color: ${actionColor}; font-weight: bold;` }, actionText)
          ]),
          h('p', [
            h('strong', '当前价格：'),
            h('span', `${currentPrice.toFixed(2)}元`)
          ]),
          h('div', { style: 'margin: 16px 0;' }, [
            h('p', { style: 'margin-bottom: 8px;' }, [
              h('strong', '交易价格：'),
              h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(可修改)')
            ]),
            h(ElInputNumber, {
              modelValue: tradeForm.price,
              'onUpdate:modelValue': (val: number | undefined) => { tradeForm.price = val ?? 0 },
              min: 0.01,
              max: 9999,
              precision: 2,
              step: 0.01,
              style: 'width: 200px;',
              controls: true
            })
          ]),
          h('div', { style: 'margin: 16px 0;' }, [
            h('p', { style: 'margin-bottom: 8px;' }, [
              h('strong', '交易数量：'),
              h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(可修改，100股为单位)')
            ]),
            h(ElInputNumber, {
              modelValue: tradeForm.quantity,
              'onUpdate:modelValue': (val: number | undefined) => { tradeForm.quantity = val ?? 0 },
              min: 100,
              max: maxQuantity,
              step: 100,
              style: 'width: 200px;',
              controls: true
            })
          ]),
          h('p', [
            h('strong', '预计金额：'),
            h('span', { style: 'color: #409EFF; font-weight: bold;' }, `${estimatedAmount.value}元`)
          ]),
          h('p', [
            h('strong', '置信度：'),
            h('span', `${(recommendation.confidence * 100).toFixed(1)}%`)
          ]),
          h('p', [
            h('strong', '风险等级：'),
            h('span', recommendation.riskLevel)
          ]),
          recommendation.action === 'buy' ? h('p', { style: 'color: #909399; font-size: 12px; margin-top: 12px;' },
            `可用资金：${typeof account.cash === 'number' ? account.cash.toFixed(2) : account.cash}元，最大可买：${maxQuantity}股`
          ) : null,
          recommendation.action === 'sell' ? h('p', { style: 'color: #909399; font-size: 12px; margin-top: 12px;' },
            `当前持仓：${maxQuantity}股`
          ) : null
        ])
      }
    }

    await ElMessageBox({
      title: '确认交易',
      message: h(MessageComponent),
      confirmButtonText: '确认下单',
      cancelButtonText: '取消',
      type: 'warning',
      beforeClose: (action, _instance, done) => {
        if (action === 'confirm') {
          // 验证输入
          if (tradeForm.quantity < 100 || tradeForm.quantity % 100 !== 0) {
            ElMessage.error('交易数量必须是100的整数倍')
            return
          }
          if (tradeForm.quantity > maxQuantity) {
            ElMessage.error(`交易数量不能超过${maxQuantity}股`)
            return
          }
          if (tradeForm.price <= 0) {
            ElMessage.error('交易价格必须大于0')
            return
          }

          // 检查资金是否充足
          if (recommendation.action === 'buy') {
            const totalAmount = tradeForm.price * tradeForm.quantity
            if (totalAmount > Number(account.cash)) {
              ElMessage.error('可用资金不足')
              return
            }
          }
        }
        done()
      }
    })

    // 执行交易
    const analysisId = analysisResults.value.id || currentTaskId.value
    const orderRes = await paperApi.placeOrder({
      code: code,
      side: recommendation.action,
      quantity: tradeForm.quantity,
      analysis_id: analysisId ? String(analysisId) : undefined
    })

    if (orderRes.success) {
      ElMessage.success(`${actionText}订单已提交成功！`)
      // 可选：跳转到模拟交易页面
      setTimeout(() => {
        router.push({ name: 'PaperTradingHome' })
      }, 1500)
    } else {
      ElMessage.error(orderRes.message || '下单失败')
    }

  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('一键模拟下单失败:', error)
      ElMessage.error(error.message || '操作失败')
    }
  }
}

// 组件销毁时清理定时器
onUnmounted(() => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
})

// 页面可见性变化时的处理
const handleVisibilityChange = () => {
  if (document.hidden) {
    console.log('📱 页面隐藏，暂停轮询')
  } else {
    console.log('📱 页面显示，恢复轮询')
    // 页面重新可见时，立即查询一次状态
    if (currentTaskId.value && analysisStatus.value === 'running') {
      setTimeout(async () => {
        try {
          const response = await analysisApi.getTaskStatus(currentTaskId.value)
          const status = response.data // 响应拦截器已返回 response.data
          console.log('🔄 页面恢复查询状态:', status)
          if (status.status === 'running') {
            analysisStatus.value = 'running'
            updateProgressInfo(status)
          }
        } catch (error) {
          console.error('页面恢复查询状态失败:', error)
        }
      }, 500)
    }
  }
}

// 监听页面可见性变化
document.addEventListener('visibilitychange', handleVisibilityChange)

// 获取进度条状态
const getProgressStatus = () => {
  if (analysisStatus.value === 'completed') {
    return 'success'
  } else if (analysisStatus.value === 'failed') {
    return 'exception'
  } else if (analysisStatus.value === 'running') {
    return '' // 默认状态，显示蓝色进度条
  }
  return ''
}

// 简单的时间格式化方法（只用于显示后端返回的时间）
const formatTime = (seconds: number) => {
  if (!seconds || seconds <= 0) {
    return '计算中...'
  }

  if (seconds < 60) {
    return `${Math.floor(seconds)}秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.floor(seconds % 60)
    return remainingSeconds > 0 ? `${minutes}分${remainingSeconds}秒` : `${minutes}分钟`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}小时${minutes}分钟`
  }
}

// 更新分析步骤状态
const updateAnalysisSteps = (status: any) => {
  console.log('📋 步骤更新输入:', status)

  if (analysisSteps.value.length === 0) {
    console.log('📋 没有步骤定义，跳过更新')
    return
  }

  // 优先使用后端提供的详细步骤信息
  let currentStepIndex = 0

  if (status.current_step !== undefined) {
    // 后端提供了精确的步骤索引
    currentStepIndex = status.current_step
    console.log('📋 使用后端步骤索引:', currentStepIndex)
  } else {
    // 兜底方案：使用进度百分比估算
    const progress = status.progress_percentage || status.progress || 0
    if (progress > 0) {
      const progressRatio = progress / 100
      currentStepIndex = Math.floor(progressRatio * (analysisSteps.value.length - 1))
      if (progress > 0 && currentStepIndex === 0) {
        currentStepIndex = 1
      }
    }
    console.log('📋 使用进度估算步骤索引:', currentStepIndex, '进度:', progress)
  }

  // 确保索引在有效范围内
  currentStepIndex = Math.max(0, Math.min(currentStepIndex, analysisSteps.value.length - 1))

  console.log('📋 最终步骤索引:', currentStepIndex, '/', analysisSteps.value.length)

  // 更新所有步骤状态
  analysisSteps.value.forEach((step, index) => {
    if (index < currentStepIndex) {
      step.status = 'completed'
    } else if (index === currentStepIndex) {
      step.status = 'current'
    } else {
      step.status = 'pending'
    }
  })

  const statusSummary = analysisSteps.value.map((s, i) => `${i}:${s.status}`).join(', ')
  console.log('📋 步骤状态更新完成:', statusSummary)
}

// 初始化模型设置
const initializeModelSettings = async () => {
  try {
    const sortModelsByNewest = (configs: any[]) => {
      const getTimestamp = (config: any) => {
        const timeValue = config.created_at || config.updated_at
        const timestamp = timeValue ? new Date(timeValue).getTime() : 0
        return Number.isNaN(timestamp) ? 0 : timestamp
      }

      return [...configs].sort((a, b) => getTimestamp(b) - getTimestamp(a))
    }

    // 获取默认模型
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.quickAnalysisModel = defaultModels.quick_analysis_model
    modelSettings.value.deepAnalysisModel = defaultModels.deep_analysis_model

    // 获取所有可用的模型列表
    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = sortModelsByNewest(
      llmConfigs.filter((config: any) => config.enabled)
    )

    console.log('✅ 加载模型配置成功:', {
      quick: modelSettings.value.quickAnalysisModel,
      deep: modelSettings.value.deepAnalysisModel,
      available: availableModels.value.length
    })
    console.log('🔍 可用模型详细信息:', availableModels.value.map(m => ({
      model_name: m.model_name,
      model_display_name: m.model_display_name,
      provider: m.provider
    })))
  } catch (error) {
    console.error('加载默认模型配置失败:', error)
    modelSettings.value.quickAnalysisModel = 'qwen-turbo'
    modelSettings.value.deepAnalysisModel = 'qwen-max'
  }
}

// 任务状态缓存管理
const TASK_CACHE_KEY = 'trading_analysis_task'
const TASK_CACHE_DURATION = 30 * 60 * 1000 // 30分钟

// 保存任务状态到缓存
const saveTaskToCache = (taskId: string, taskData: any) => {
  const cacheData = {
    taskId,
    taskData,
    timestamp: Date.now()
  }
  localStorage.setItem(TASK_CACHE_KEY, JSON.stringify(cacheData))
  console.log('💾 任务状态已缓存:', taskId)
}

// 从缓存获取任务状态
const getTaskFromCache = () => {
  try {
    const cached = localStorage.getItem(TASK_CACHE_KEY)
    if (!cached) return null

    const cacheData = JSON.parse(cached)
    const now = Date.now()

    // 检查是否过期（30分钟）
    if (now - cacheData.timestamp > TASK_CACHE_DURATION) {
      localStorage.removeItem(TASK_CACHE_KEY)
      console.log('🗑️ 缓存已过期，已清理')
      return null
    }

    console.log('📦 从缓存恢复任务:', cacheData.taskId)
    return cacheData
  } catch (error) {
    console.error('❌ 读取缓存失败:', error)
    localStorage.removeItem(TASK_CACHE_KEY)
    return null
  }
}

// 清除任务缓存
const clearTaskCache = () => {
  localStorage.removeItem(TASK_CACHE_KEY)
  console.log('🗑️ 任务缓存已清除')
}

// 恢复任务状态
const restoreTaskFromCache = async () => {
  const cached = getTaskFromCache()
  if (!cached) return false

  try {
    console.log('🔄 尝试恢复任务状态:', cached.taskId)

    // 查询任务当前状态
    const response = await analysisApi.getTaskStatus(cached.taskId)
    const status = response.data // 响应拦截器已返回 response.data

    console.log('📊 恢复的任务状态:', status)

    if (status.status === 'completed') {
      // 任务已完成，显示结果
      currentTaskId.value = cached.taskId
      analysisStatus.value = 'completed'
      showResults.value = true
      analysisResults.value = status.result_data
      progressInfo.value.progress = 100
      progressInfo.value.currentStep = '分析完成'
      progressInfo.value.message = '分析已完成'

      // 恢复分析参数
      if (cached.taskData.parameters) {
        Object.assign(analysisForm, cached.taskData.parameters)
      }

      console.log('✅ 任务已完成，显示结果')
      return true

    } else if (status.status === 'running') {
      // 任务仍在运行，恢复进度显示
      currentTaskId.value = cached.taskId
      analysisStatus.value = 'running'
      showResults.value = false
      updateProgressInfo(status)

      // 恢复分析参数
      if (cached.taskData.parameters) {
        Object.assign(analysisForm, cached.taskData.parameters)
      }

      // 启动轮询
      startPollingTaskStatus()

      console.log('🔄 任务仍在运行，恢复进度显示')
      return true

    } else if (status.status === 'failed') {
      // 任务失败
      analysisStatus.value = 'failed'
      progressInfo.value.currentStep = '分析失败'
      progressInfo.value.message = status.error_message || '分析过程中发生错误'

      // 清除缓存
      clearTaskCache()

      console.log('❌ 任务失败')
      return true

    } else {
      // 其他状态，清除缓存
      clearTaskCache()
      console.log('🤔 未知任务状态，清除缓存')
      return false
    }

  } catch (error) {
    console.error('❌ 恢复任务状态失败:', error)
    // 如果查询失败，可能是任务不存在了，清除缓存
    clearTaskCache()
    return false
  }
}

// 🆕 模型能力相关辅助函数

/**
 * 获取能力等级文本
 */
const getCapabilityText = (level: number): string => {
  const texts: Record<number, string> = {
    1: '⚡基础',
    2: '📊标准',
    3: '🎯高级',
    4: '🔥专业',
    5: '👑旗舰'
  }
  return texts[level] || '📊标准'
}

/**
 * 获取能力等级标签类型
 */
const getCapabilityTagType = (level: number): 'success' | 'info' | 'warning' | 'danger' => {
  if (level >= 4) return 'danger'
  if (level >= 3) return 'warning'
  if (level >= 2) return 'success'
  return 'info'
}

/**
 * 判断是否适合快速分析
 */
const isQuickAnalysisRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('quick_analysis') || roles.includes('both')
}

/**
 * 显示模型配置说明
 */
const checkModelSuitability = async () => {
  try {
    modelRecommendation.value = {
      title: '💡 模型配置',
      message: `当前模型配置：\n• 快速模型：${modelSettings.value.quickAnalysisModel || '未设置'}\n• 深度模型：${modelSettings.value.deepAnalysisModel || '未设置'}`,
      type: 'info'
    }
  } catch (error) {
    console.error('检查模型配置失败:', error)
  }
}

// 应用推荐的模型配置
const applyRecommendedModels = () => {
  if (modelRecommendation.value?.quickModel && modelRecommendation.value?.deepModel) {
    modelSettings.value.quickAnalysisModel = modelRecommendation.value.quickModel
    modelSettings.value.deepAnalysisModel = modelRecommendation.value.deepModel

    // 清除推荐提示
    modelRecommendation.value = null

    ElMessage.success('已应用推荐的模型配置')
  }
}

// 监听模型选择变化
watch([() => modelSettings.value.quickAnalysisModel, () => modelSettings.value.deepAnalysisModel], () => {
  checkModelSuitability()
})

// 页面初始化
onMounted(async () => {
  initializeModelSettings()

  // 🆕 从用户偏好加载默认设置
  const authStore = useAuthStore()
  const appStore = useAppStore()

  // 优先从 authStore.user.preferences 读取，其次从 appStore.preferences 读取
  const userPrefs = authStore.user?.preferences
  if (userPrefs) {
    // 加载默认市场
    if (userPrefs.default_market) {
      analysisForm.market = userPrefs.default_market as MarketType
    }

    // 加载默认分析师
    if (userPrefs.default_analysts && userPrefs.default_analysts.length > 0) {
      analysisForm.selectedAnalysts = [...userPrefs.default_analysts]
    }

    console.log('✅ 已加载用户偏好设置:', {
      market: analysisForm.market,
      analysts: analysisForm.selectedAnalysts
    })
  } else {
    // 降级到 appStore.preferences
    if (appStore.preferences.defaultMarket) {
      analysisForm.market = appStore.preferences.defaultMarket as MarketType
    }
    console.log('✅ 已加载应用偏好设置（降级）')
  }

  // 接收一次路由参数（从筛选页带入）- 路由参数优先级最高
  const q = route.query as any
  const hasNewStock = !!q?.stock
  if (hasNewStock) {
    analysisForm.stockCode = String(q.stock)
    // 🔥 关键修复：如果有新的股票代码，清除旧任务缓存
    clearTaskCache()
    console.log('🔄 检测到新股票代码，已清除旧任务缓存:', q.stock)

    // 🆕 自动识别市场类型（如果URL中没有明确指定market参数）
    if (!q?.market) {
      const detectedMarket = getMarketByStockCode(analysisForm.stockCode)
      analysisForm.market = detectedMarket as MarketType
      console.log('🔍 自动识别市场类型:', analysisForm.stockCode, '->', detectedMarket)
    }
  }
  if (q?.market) analysisForm.market = normalizeMarketForAnalysis(q.market) as MarketType

  // 尝试恢复任务状态（仅当没有新股票代码时）
  if (!hasNewStock) {
    await restoreTaskFromCache()
  }

  // 🆕 初始检查模型适用性
  await checkModelSuitability()
})
</script>

<style lang="scss" scoped>
.single-analysis {
  min-height: 100vh;
  background: var(--el-bg-color-page);
  padding: 24px;

  .page-header {
    margin-bottom: 32px;

    .header-content {
      background: var(--el-bg-color);
      padding: 32px;
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    .title-section {
      .page-title {
        display: flex;
        align-items: center;
        font-size: 32px;
        font-weight: 700;
        color: var(--el-text-color-primary);
        margin: 0 0 8px 0;

        .title-icon {
          margin-right: 12px;
          color: #3b82f6;
        }
      }

      .page-description {
        font-size: 16px;
        color: var(--el-text-color-secondary);
        margin: 0;
      }
    }
  }

  // 功能介绍区域
  .intro-section {
    margin-top: 40px;
    margin-bottom: 24px;

    .intro-card {
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    .intro-content {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
      padding: 8px 0;

      @media (max-width: 1024px) {
        grid-template-columns: 1fr;
      }
    }

    .intro-item {
      display: flex;
      gap: 16px;
      padding: 16px;
      background: var(--el-fill-color-light);
      border-radius: 12px;
      transition: all 0.3s ease;

      &:hover {
        background: var(--el-fill-color);
        transform: translateY(-2px);
      }

      .intro-icon {
        font-size: 32px;
        flex-shrink: 0;
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--el-bg-color);
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
      }

      .intro-text {
        flex: 1;

        h4 {
          margin: 0 0 6px 0;
          font-size: 16px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }

        p {
          margin: 0;
          font-size: 14px;
          color: var(--el-text-color-secondary);
          line-height: 1.6;
        }
      }
    }
  }

  // 分析流程介绍面板（美化版）
  .pipeline-intro {
    margin-top: 32px;
    margin-bottom: 32px;
    display: flex;
    flex-direction: column;
    gap: 24px;

    .pipeline-section {
      background: var(--el-bg-color);
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);

      .section-header {
        margin-bottom: 20px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--el-border-color);

        h3 {
          margin: 0 0 8px 0;
          font-size: 18px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }

        .section-subtitle {
          margin: 0;
          font-size: 14px;
          color: var(--el-text-color-secondary);
        }
      }

      // 分析师团队样式
      .analyst-teams {
        display: flex;
        flex-direction: column;
        gap: 16px;

        .team-group {
          .team-label {
            font-size: 13px;
            font-weight: 600;
            color: var(--el-text-color-secondary);
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
          }

          .team-cards {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
          }
        }

        .analyst-chip {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 16px;
          border-radius: 10px;
          background: var(--el-fill-color-light);
          border: 1px solid var(--el-border-color);
          transition: all 0.2s ease;

          &:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
          }

          .chip-icon {
            font-size: 18px;
          }

          .chip-name {
            font-size: 14px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }

          .chip-desc {
            font-size: 12px;
            color: var(--el-text-color-secondary);
          }

          // 短线博弈配色
          &--market {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border-color: #fbbf24;
            .chip-icon { font-size: 20px; }
            .chip-name { color: #92400e; }
            .chip-desc { color: #b45309; }
          }
          &--social {
            background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
            border-color: #60a5fa;
            .chip-name { color: #1e40af; }
            .chip-desc { color: #2563eb; }
          }
          &--fund {
            background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
            border-color: #34d399;
            .chip-name { color: #065f46; }
            .chip-desc { color: #059669; }
          }
          &--unlock {
            background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%);
            border-color: #f472b6;
            .chip-name { color: #9d174d; }
            .chip-desc { color: #be185d; }
          }
          // 长线价值配色
          &--fundamental {
            background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
            border-color: #818cf8;
            .chip-name { color: #3730a3; }
            .chip-desc { color: #4f46e5; }
          }
          &--news {
            background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
            border-color: #a78bfa;
            .chip-name { color: #6b21a8; }
            .chip-desc { color: #9333ea; }
          }
          &--policy {
            background: linear-gradient(135deg, #ccfbf1 0%, #99f6e4 100%);
            border-color: #2dd4bf;
            .chip-name { color: #115e59; }
            .chip-desc { color: #0d9488; }
          }
        }
      }

      // 暗色模式适配
      @media (prefers-color-scheme: dark) {
        .analyst-chip {
          &--market {
            background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
            border-color: #d97706;
            .chip-name { color: #fef3c7; }
            .chip-desc { color: #fde68a; }
          }
          &--social {
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            border-color: #3b82f6;
            .chip-name { color: #dbeafe; }
            .chip-desc { color: #bfdbfe; }
          }
          &--fund {
            background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
            border-color: #10b981;
            .chip-name { color: #d1fae5; }
            .chip-desc { color: #a7f3d0; }
          }
          &--unlock {
            background: linear-gradient(135deg, #831843 0%, #9d174d 100%);
            border-color: #ec4899;
            .chip-name { color: #fce7f3; }
            .chip-desc { color: #fbcfe8; }
          }
          &--fundamental {
            background: linear-gradient(135deg, #312e81 0%, #3730a3 100%);
            border-color: #6366f1;
            .chip-name { color: #e0e7ff; }
            .chip-desc { color: #c7d2fe; }
          }
          &--news {
            background: linear-gradient(135deg, #581c87 0%, #6b21a8 100%);
            border-color: #a855f7;
            .chip-name { color: #f3e8ff; }
            .chip-desc { color: #e9d5ff; }
          }
          &--policy {
            background: linear-gradient(135deg, #134e4a 0%, #115e59 100%);
            border-color: #14b8a6;
            .chip-name { color: #ccfbf1; }
            .chip-desc { color: #99f6e4; }
          }
        }
      }

      // 辩论流程样式
      .section--debate {
        background: var(--el-bg-color);
      }

      .debate-timeline {
        display: flex;
        flex-direction: column;
        gap: 16px;

        .timeline-phase {
          background: var(--el-bg-color);
          border-radius: 12px;
          padding: 16px;
          border: 1px solid var(--el-border-color);

          .phase-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--el-text-color-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
          }

          .phase-flow {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
          }

          &.phase--trade {
            background: linear-gradient(135deg, #fef3c7 0%, #fff7ed 100%);
            border-color: #fbbf24;
          }
        }

        .debate-node {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 12px 16px;
          border-radius: 10px;
          min-width: 100px;
          text-align: center;

          .node-icon {
            font-size: 24px;
            margin-bottom: 6px;
          }

          .node-name {
            font-size: 13px;
            font-weight: 600;
            color: var(--el-text-color-primary);
            margin-bottom: 4px;
          }

          .node-desc {
            font-size: 11px;
            color: var(--el-text-color-secondary);
            line-height: 1.4;
          }

          // 节点配色
          &.node--bull {
            background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
            border: 1px solid #34d399;
            .node-name { color: #065f46; }
            .node-desc { color: #059669; }
          }
          &.node--bear {
            background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
            border: 1px solid #f87171;
            .node-name { color: #991b1b; }
            .node-desc { color: #dc2626; }
          }
          &.node--debate {
            background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
            border: 1px solid #a78bfa;
            .node-name { color: #5b21b6; }
            .node-desc { color: #7c3aed; }
          }
          &.node--manager {
            background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
            border: 1px solid #60a5fa;
            .node-name { color: #1e40af; }
            .node-desc { color: #2563eb; }
          }
        }

        .timeline-arrow {
          font-size: 16px;
          color: #94a3b8;
          font-weight: 700;

          &--vs {
            color: #ef4444;
          }
        }

        .trade-node {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;

          .node-icon { font-size: 24px; }
          .node-name {
            font-size: 14px;
            font-weight: 600;
            color: #92400e;
          }
          .node-desc {
            font-size: 12px;
            color: #a16207;
          }
        }

        .risk-perspectives {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
          margin-bottom: 12px;

          .risk-card {
            padding: 12px;
            border-radius: 10px;
            text-align: center;

            .risk-icon {
              font-size: 20px;
              display: block;
              margin-bottom: 6px;
            }

            .risk-name {
              font-size: 13px;
              font-weight: 600;
              display: block;
              margin-bottom: 4px;
            }

            .risk-desc {
              font-size: 11px;
              opacity: 0.8;
            }

            &.risk-card--aggressive {
              background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
              color: #991b1b;
            }
            &.risk-card--neutral {
              background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
              color: #92400e;
            }
            &.risk-card--conservative {
              background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
              color: #3730a3;
            }
          }
        }

        .risk-manager {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%);
          border-radius: 10px;
          border: 1px solid #f472b6;

          .node-icon { font-size: 20px; }
          .node-name {
            font-size: 13px;
            font-weight: 600;
            color: #9d174d;
          }
          .node-desc {
            font-size: 12px;
            color: #be185d;
          }
        }

        // 暗色模式适配
        @media (prefers-color-scheme: dark) {
          .debate-node {
            &.node--bull {
              background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
              border-color: #10b981;
              .node-name { color: #d1fae5; }
              .node-desc { color: #a7f3d0; }
            }
            &.node--bear {
              background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
              border-color: #ef4444;
              .node-name { color: #fee2e2; }
              .node-desc { color: #fecaca; }
            }
            &.node--debate {
              background: linear-gradient(135deg, #4c1d95 0%, #5b21b6 100%);
              border-color: #8b5cf6;
              .node-name { color: #ede9fe; }
              .node-desc { color: #ddd6fe; }
            }
            &.node--manager {
              background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
              border-color: #3b82f6;
              .node-name { color: #dbeafe; }
              .node-desc { color: #bfdbfe; }
            }
          }

          .timeline-arrow {
            color: #64748b;
            &--vs { color: #f87171; }
          }

          .trade-node {
            .node-name { color: #fef3c7; }
            .node-desc { color: #fde68a; }
          }

          .risk-perspectives .risk-card {
            &.risk-card--aggressive {
              background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
              color: #fee2e2;
            }
            &.risk-card--neutral {
              background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
              color: #fef3c7;
            }
            &.risk-card--conservative {
              background: linear-gradient(135deg, #312e81 0%, #3730a3 100%);
              color: #e0e7ff;
            }
          }

          .risk-manager {
            background: linear-gradient(135deg, #831843 0%, #9d174d 100%);
            border-color: #ec4899;
            .node-name { color: #fce7f3; }
            .node-desc { color: #fbcfe8; }
          }
        }
      }

      // 最终决策样式
      .final-decision {
        background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
        border-radius: 12px;
        padding: 20px;
        text-align: center;

        .decision-label {
          font-size: 14px;
          font-weight: 600;
          color: #fbbf24;
          margin-bottom: 12px;
        }

        .decision-options {
          display: flex;
          justify-content: center;
          gap: 16px;
          margin-bottom: 12px;
        }

        .decision-chip {
          padding: 8px 24px;
          border-radius: 8px;
          font-size: 16px;
          font-weight: 700;
          letter-spacing: 1px;

          &.decision-chip--buy {
            background: #10b981;
            color: white;
          }
          &.decision-chip--hold {
            background: #f59e0b;
            color: #1a202c;
          }
          &.decision-chip--sell {
            background: #ef4444;
            color: white;
          }
        }

        .decision-desc {
          margin: 0;
          font-size: 13px;
          color: #cbd5e1;
        }
      }
    }
  }

  .analysis-container {
    // 让左右两侧卡片高度一致
    .form-row {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
    }

    .form-col {
      display: flex;
      flex-direction: column;

      .el-card {
        flex: 1;
      }
    }

    .main-form-card, .config-card {
      border-radius: 16px;
      border: none;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

      :deep(.el-card__header) {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 16px 16px 0 0;
        padding: 20px 24px;

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;

          h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
          }
        }
      }

      :deep(.el-card__body) {
        padding: 24px;
      }
    }

    .analysis-form {
      .form-section {
        margin-bottom: 32px;
        width: 100%;
        display: flex;
        flex-direction: column;

        .section-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin: 0 0 16px 0;
          padding-bottom: 8px;
          border-bottom: 2px solid var(--el-border-color);
        }
      }

      .stock-input {
        :deep(.el-input__inner) {
          font-weight: 600;
          text-transform: uppercase;
        }

        &.is-error {
          :deep(.el-input__inner) {
            border-color: #f56c6c;
          }
        }
      }

      .error-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #f56c6c;

        .el-icon {
          font-size: 14px;
        }
      }

      .help-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #67c23a;

        .el-icon {
          font-size: 14px;
        }
      }
    }

    .config-card {
      .config-content {
        .config-section {
          margin-bottom: 24px;

          .config-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--el-text-color-primary);
            margin: 0 0 12px 0;
            display: flex;
            align-items: center;
            gap: 8px;
          }

          .model-config {
            .model-item {
              margin-bottom: 16px;

              .model-label {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
                font-size: 13px;
                color: var(--el-text-color-regular);

                .help-icon {
                  color: var(--el-text-color-secondary);
                  cursor: help;
                }
              }
            }
          }

          .option-list {
            .option-item {
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 12px 0;
              border-bottom: 1px solid var(--el-border-color-lighter);

              &:last-child {
                border-bottom: none;
              }

              .option-info {
                .option-name {
                  font-size: 14px;
                  font-weight: 500;
                  color: var(--el-text-color-regular);
                  display: block;
                  margin-bottom: 2px;
                }

                .option-desc {
                  font-size: 12px;
                  color: var(--el-text-color-secondary);
                }
              }
            }
          }

          .custom-input {
            :deep(.el-textarea__inner) {
              border-radius: 8px;
              border: 1px solid #d1d5db;

              &:focus {
                border-color: #3b82f6;
                box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
              }
            }
          }

          .input-help {
            font-size: 12px;
            color: #6b7280;
            margin-top: 8px;
          }

          .action-buttons {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            margin-top: 24px !important;
            width: 100% !important;
            text-align: center !important;

            .submit-btn.el-button {
              width: 280px !important;
              height: 56px !important;
              font-size: 18px !important;
              font-weight: 700 !important;
              background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
              border: none !important;
              border-radius: 16px !important;
              transition: all 0.3s ease !important;
              box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
              min-width: 280px !important;
              max-width: 280px !important;

              &:hover {
                transform: translateY(-3px) !important;
                box-shadow: 0 12px 30px rgba(59, 130, 246, 0.4) !important;
                background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
              }

              &:disabled {
                opacity: 0.6 !important;
                transform: none !important;
                box-shadow: 0 4px 15px rgba(59, 130, 246, 0.1) !important;
              }

              .el-icon {
                margin-right: 8px !important;
                font-size: 20px !important;
              }

              span {
                font-size: 18px !important;
                font-weight: 700 !important;
              }
            }
          }
        }
      }
    }

    .action-section {
      margin-top: 24px;
      display: flex;
      gap: 16px;

      .submit-btn {
        flex: 1;
        height: 48px;
        font-size: 16px;
        font-weight: 600;
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        border: none;
        border-radius: 12px;
        transition: all 0.3s ease;

        &:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px rgba(59, 130, 246, 0.3);
        }

        &:disabled {
          opacity: 0.6;
          transform: none;
          box-shadow: none;
        }
      }

      .reset-btn {
        height: 48px;
        font-size: 16px;
        border-radius: 12px;
        border: 2px solid #e5e7eb;
        color: #6b7280;
        transition: all 0.3s ease;

        &:hover {
          border-color: #d1d5db;
          color: #374151;
          transform: translateY(-1px);
        }
      }
    }
  }
}

// 分析步骤样式
.step-item {
  display: flex;
  align-items: flex-start;
  padding: 12px 0;
  border-left: 3px solid #e5e7eb;
  margin-left: 15px;
  position: relative;
  transition: all 0.3s ease;

  &.step-completed {
    border-left-color: #10b981;

    .step-icon {
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: white;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
    }

    .step-title {
      color: #10b981;
      font-weight: 600;
    }

    .step-description {
      color: #059669;
    }
  }

  &.step-current {
    border-left-color: #3b82f6;
    background: linear-gradient(90deg, rgba(59, 130, 246, 0.05) 0%, transparent 100%);

    .step-icon {
      background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
      color: white;
      box-shadow: 0 2px 12px rgba(59, 130, 246, 0.4);
    }

    .step-title {
      color: #3b82f6;
      font-weight: 700;
    }

    .step-description {
      color: #1d4ed8;
      font-weight: 500;
    }
  }

  &.step-pending {
    .step-icon {
      background: #f3f4f6;
      color: #9ca3af;
      border: 2px solid #e5e7eb;
    }

    .step-title {
      color: #6b7280;
    }

    .step-description {
      color: #9ca3af;
    }
  }
}

.step-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: -16px;
  margin-right: 16px;
  font-size: 14px;
  flex-shrink: 0;
  z-index: 1;
  transition: all 0.3s ease;
}

.completed-icon {
  color: white;
}

.current-icon {
  color: white;
}

.pending-icon {
  color: #9ca3af;
}

.step-content {
  flex: 1;
  min-width: 0;
  padding-right: 16px;
}

.step-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
  line-height: 1.4;
}

.step-description {
  font-size: 12px;
  line-height: 1.4;
  opacity: 0.9;
}

/* 脉冲动画 */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.05);
  }
}

/* 为当前步骤图标添加脉冲效果 */
.step-current .step-icon {
  animation: pulse 2s ease-in-out infinite;
}
</style>

<style>
/* 全局样式确保按钮样式生效 */
.action-buttons {
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  text-align: center !important;
}

.large-analysis-btn.el-button {
  width: 280px !important;
  height: 56px !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
  border: none !important;
  border-radius: 16px !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
  min-width: 280px !important;
  max-width: 280px !important;
}

.large-analysis-btn.el-button:hover {
  transform: translateY(-3px) !important;
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.4) !important;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
}

.large-analysis-btn.el-button:disabled {
  opacity: 0.6 !important;
  transform: none !important;
  box-shadow: 0 4px 15px rgba(59, 130, 246, 0.1) !important;
}

.large-analysis-btn.el-button .el-icon {
  margin-right: 8px !important;
  font-size: 20px !important;
}

.large-analysis-btn.el-button span {
  font-size: 18px !important;
  font-weight: 700 !important;
}

/* 进度显示样式 */
.progress-section {
  margin-top: 24px;
}

.progress-card .progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-card .progress-header h4 {
  margin: 0;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 旋转动画 */
.rotating-icon {
  animation: rotate 2s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 总体进度信息 */
.overall-progress-info {
  margin-bottom: 24px;
}

.progress-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-item {
  text-align: center;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

/* 进度条区域 */
.progress-bar-section {
  margin-bottom: 24px;
}

.main-progress-bar {
  :deep(.el-progress-bar__outer) {
    background-color: var(--el-fill-color);
    border-radius: 8px;
  }

  :deep(.el-progress-bar__inner) {
    background: linear-gradient(90deg, #3b82f6 0%, #1d4ed8 100%);
    border-radius: 8px;
    transition: width 0.6s ease;
  }

  :deep(.el-progress__text) {
    font-weight: 600;
    color: var(--el-text-color-primary);
  }
}

/* 当前任务信息 */
.current-task-info {
  background: var(--el-fill-color-light);
  border: 1px solid #3b82f6;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 24px;
}

.task-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-color-primary);
  margin-bottom: 8px;
}

.task-icon {
  color: #3b82f6;
}

.task-description {
  font-size: 14px;
  color: var(--el-color-primary);
  line-height: 1.5;
}

/* 分析步骤 */
.analysis-steps {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
}

.steps-title {
  margin: 0 0 16px 0;
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 600;
}

.steps-container {
  max-height: 300px;
  overflow-y: auto;
}

/* 结果显示样式 */
.results-section {
  margin-top: 24px;
}

.results-card .results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.results-card .results-header h3 {
  margin: 0;
  color: var(--el-text-color-primary);
}

.results-card .result-meta {
  display: flex;
  gap: 8px;
}

/* 风险提示样式 */
.risk-disclaimer {
  margin-bottom: 24px;
  animation: fadeInDown 0.5s ease-out;
}

.risk-disclaimer :deep(.el-alert) {
  background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
  border: 2px solid #ffc107;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
}

.risk-disclaimer :deep(.el-alert__icon) {
  font-size: 24px;
  color: #ff6b00;
}

.disclaimer-content {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  line-height: 1.6;
}

.disclaimer-icon {
  font-size: 24px;
  color: #ff6b00;
  flex-shrink: 0;
  animation: pulse 2s ease-in-out infinite;
}

.disclaimer-text {
  color: #856404;
  flex: 1;
}

.disclaimer-text strong {
  color: #d63031;
  font-size: 16px;
  font-weight: 700;
}

@keyframes pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
  }
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.decision-section {
  margin-bottom: 32px;
}

.decision-section h4 {
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
}

.decision-card {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
}

.decision-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.decision-action {
  display: flex;
  align-items: center;
  gap: 12px;
}

.decision-action .label {
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.decision-metrics {
  display: flex;
  gap: 24px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.metric-item .label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.metric-item .value {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.decision-reasoning h5 {
  margin: 0 0 8px 0;
  color: var(--el-text-color-regular);
  font-size: 14px;
}

.decision-reasoning p {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.reports-section {
  margin-bottom: 32px;
}

.reports-section h4 {
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
}

.report-content {
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

.report-content h1,
.report-content h2,
.report-content h3 {
  color: var(--el-text-color-primary);
  margin: 16px 0 8px 0;
}

.report-content strong {
  color: var(--el-text-color-primary);
}

.result-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  padding-top: 24px;
  border-top: 1px solid var(--el-border-color);
}

/* 分析报告标签页样式 */
.analysis-tabs-container {
  margin-top: 16px;
}

.analysis-tabs {
  /* 标签页头部样式 */
  :deep(.el-tabs__header) {
    margin: 0 0 20px 0;
    background: var(--el-fill-color-light);
    padding: 12px;
    border-radius: 15px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    border: 1px solid var(--el-border-color);
  }

  /* 标签页导航 */
  :deep(.el-tabs__nav-wrap) {
    &::after {
      display: none; /* 隐藏默认的底部边框 */
    }
  }

  /* 单个标签页样式 */
  :deep(.el-tabs__item) {
    height: 55px !important;
    line-height: 55px !important;
    padding: 0 20px !important;
    margin-right: 8px !important;
    background: var(--el-bg-color) !important;
    border: 2px solid var(--el-border-color) !important;
    border-radius: 12px !important;
    color: var(--el-text-color-regular) !important;
    font-weight: 600 !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
    position: relative !important;
    overflow: hidden !important;
    border-bottom: 2px solid var(--el-border-color) !important; /* 确保底部边框存在 */

    &:hover {
      background: var(--el-fill-color-light) !important;
      border-color: #2196f3 !important;
      transform: translateY(-2px) scale(1.02) !important;
      box-shadow: 0 4px 15px rgba(33,150,243,0.3) !important;
      color: #1976d2 !important;
    }

    &.is-active {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
      color: white !important;
      border-color: #667eea !important;
      box-shadow: 0 6px 20px rgba(102,126,234,0.4) !important;
      transform: translateY(-3px) scale(1.05) !important;

      &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(135deg, rgba(255,255,255,0.2) 0%, rgba(255,255,255,0.1) 100%);
        border-radius: 10px;
        pointer-events: none;
      }
    }
  }

  /* 标签页内容区域 */
  :deep(.el-tabs__content) {
    padding: 0;
  }

  :deep(.el-tab-pane) {
    padding: 25px;
    background: var(--el-bg-color);
    border-radius: 15px;
    border: 1px solid var(--el-border-color);
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    margin-top: 10px;
  }
}

/* 报告头部样式 */
.report-header {
  margin-bottom: 25px;
  padding: 20px;
  background: var(--el-fill-color-light);
  border-radius: 15px;
  border-left: 5px solid #667eea;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);

  .report-title {
    display: flex;
    align-items: center;
    margin-bottom: 8px;

    .report-icon {
      font-size: 24px;
      margin-right: 12px;
    }

    .report-name {
      font-size: 20px;
      font-weight: 700;
      color: var(--el-text-color-primary);
    }
  }

  .report-description {
    color: var(--el-text-color-secondary);
    font-size: 16px;
    line-height: 1.5;
    margin-left: 36px; /* 对齐图标后的文字 */
  }
}

/* 报告内容包装器 */
.report-content-wrapper {
  background: var(--el-bg-color);
  padding: 25px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

/* 报告内容样式增强 */
.report-content {
  line-height: 1.7;
  color: var(--el-text-color-regular);
  font-size: 16px;

  /* 标题样式 */
  h1, h2, h3, h4, h5, h6 {
    color: var(--el-text-color-primary) !important;
    margin: 20px 0 12px 0 !important;
    font-weight: 600 !important;
  }

  h1 { font-size: 24px !important; }
  h2 { font-size: 20px !important; }
  h3 { font-size: 18px !important; }
  h4 { font-size: 16px !important; }

  /* 段落样式 */
  p {
    margin: 12px 0 !important;
    line-height: 1.7 !important;
  }

  /* 强调文本 */
  strong, b {
    color: var(--el-text-color-primary) !important;
    font-weight: 600 !important;
  }

  /* 斜体文本 */
  em, i {
    color: var(--el-text-color-secondary) !important;
    font-style: italic !important;
  }

  /* 列表样式 */
  ul, ol {
    margin: 12px 0 !important;
    padding-left: 24px !important;

    li {
      margin: 6px 0 !important;
      line-height: 1.6 !important;
    }
  }

  /* 代码样式 */
  code {
    background: var(--el-fill-color-light) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace !important;
    font-size: 14px !important;
    color: #e11d48 !important;
  }

  /* 引用样式 */
  blockquote {
    border-left: 4px solid #3b82f6 !important;
    padding-left: 16px !important;
    margin: 16px 0 !important;
    background: var(--el-fill-color-light) !important;
    padding: 12px 16px !important;
    border-radius: 0 8px 8px 0 !important;
    font-style: italic !important;
    color: var(--el-text-color-regular) !important;
  }
}

/* 风险提示样式 */
.risk-disclaimer {
  margin-top: 24px;
  border-radius: 8px;

  :deep(.el-alert__content) {
    width: 100%;
  }

  :deep(.el-alert__title) {
    font-size: 14px;
    line-height: 1.6;
    color: #e6a23c;
  }
}
</style>
