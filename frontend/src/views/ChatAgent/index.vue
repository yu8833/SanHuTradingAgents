<template>
  <div class="chat-agent">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><ChatDotRound /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">Agent 策略问股</h2>
          <p class="page-hero-sub">
            多轮对话问股 · 内置 15+ 策略模板路由 · 可选数据工具 · 预算护栏
          </p>
        </div>
      </div>
    </div>

    <div class="chat-layout" v-loading="sessionsLoading">
      <!-- 左侧：会话列表 + 策略选择 -->
      <div class="chat-side">
        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="side-head">
              <span class="panel-title">会话</span>
              <el-button size="small" type="primary" :icon="Plus" @click="newSession">新建</el-button>
            </div>
          </template>
          <div class="session-list">
            <div
              v-for="s in sessions" :key="s.session_id"
              class="session-item" :class="{ active: s.session_id === currentSessionId }"
              @click="openSession(s.session_id)"
            >
              <div class="session-title">{{ s.title }}</div>
              <div class="session-meta">
                <span>{{ s.message_count }} 条</span>
                <span v-if="s.status !== 'active'" class="session-closed">{{ s.status }}</span>
              </div>
            </div>
            <el-empty v-if="!sessions.length && !sessionsLoading" description="暂无会话" :image-size="60" />
          </div>
        </el-card>

        <el-card shadow="never" class="side-card strategy-card">
          <template #header>
            <span class="panel-title">策略模板</span>
          </template>
          <el-select
            v-model="activeStrategy" clearable placeholder="选择策略（可选）" style="width:100%"
            @change="switchStrategy"
          >
            <el-option-group label="量化策略">
              <el-option
                v-for="s in quantStrategies" :key="s.id" :value="s.id"
                :label="`${(s.frontend && s.frontend.icon) || '📊'} ${s.name}`"
              />
            </el-option-group>
            <el-option-group label="对话/辅助信号策略">
              <el-option
                v-for="s in chatStrategies" :key="s.id" :value="s.id"
                :label="`${(s.frontend && s.frontend.icon) || '📊'} ${s.name}`"
              />
            </el-option-group>
          </el-select>
          <p v-if="activeStrategyDesc" class="strategy-desc">{{ activeStrategyDesc }}</p>
        </el-card>

        <!-- 预算进度 -->
        <el-card v-if="budgetView" shadow="never" class="side-card">
          <template #header><span class="panel-title">会话预算</span></template>
          <div class="budget-body">
            <div class="budget-row"><span>已用轮次</span><b>{{ budgetView.rounds_used }}</b></div>
            <div class="budget-row"><span>累计 Tokens</span><b>{{ budgetView.tokens_used }}</b></div>
            <div class="budget-row"><span>累计费用</span><b>¥{{ budgetView.cost_used }}</b></div>
            <div class="budget-row"><span>模型</span><b class="budget-model">{{ budgetView.model_name || '—' }}</b></div>
          </div>
        </el-card>
      </div>

      <!-- 右侧：对话区 -->
      <el-card shadow="never" class="chat-main">
        <div ref="msgBox" class="chat-msgs">
          <div v-if="!messages.length" class="chat-welcome">
            <el-icon :size="44"><ChatDotRound /></el-icon>
            <h3>开始一次问股</h3>
            <p>输入股票代码或问题，例如：<br />「用缠论看 600519」·「底部放量分析 000858」·「今天关注什么热点」</p>
            <div class="welcome-hints">
              <el-tag v-for="h in exampleHints" :key="h" size="small" effect="plain" class="welcome-hint" @click="sendNew(h)">{{ h }}</el-tag>
            </div>
          </div>

          <template v-for="(m, i) in messages" :key="i">
            <div class="msg-row" :class="m.role">
              <div class="msg-bubble" :class="m.role">
                <div class="msg-text" v-html="md(m.content)"></div>
                <div v-if="m.toolNote" class="msg-toolnote">⚙️ {{ m.toolNote }}</div>
              </div>
            </div>
          </template>

          <div v-if="streaming" class="msg-row user">
            <div class="msg-bubble user">{{ pendingText }}</div>
          </div>
          <div v-if="streamingText" class="msg-row assistant">
            <div class="msg-bubble assistant">
              <span v-html="md(streamingText)"></span><span class="cursor">▍</span>
            </div>
          </div>
          <div v-if="streamInfo" class="stream-info"><el-icon class="is-loading"><Loading /></el-icon> {{ streamInfo }}</div>
        </div>

        <div class="chat-input-bar">
          <el-input
            v-model="input" type="textarea" :rows="2" resize="none" placeholder="输入股票代码或问题…（Enter 发送，Shift+Enter 换行）"
            :disabled="streaming || !currentSessionId" @keydown.enter.exact.prevent="send"
          />
          <el-button type="primary" :icon="streaming ? undefined : Promotion" :loading="streaming" :disabled="!currentSessionId || !input.trim()" @click="send">
            {{ streaming ? '思考中' : (currentSessionId ? '发送' : '请先新建会话') }}
          </el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Plus, Promotion, Loading } from '@element-plus/icons-vue'
import { chatAgentApi, chatStream, type ChatSession, type StrategyMetaItem } from '@/api/chatAgent'

defineOptions({ name: 'ChatAgentHome' })

const sessionsLoading = ref(false)
const sessions = ref<ChatSession[]>([])
const currentSessionId = ref('')
const messages = ref<Array<{ role: string; content: string; toolNote?: string }>>([])
const input = ref('')
const streaming = ref(false)
const pendingText = ref('')
const streamingText = ref('')
const streamInfo = ref('')
const budgetView = ref<any>(null)

const strategies = ref<StrategyMetaItem[]>([])
const activeStrategy = ref<string | null>(null)

const msgBox = ref<HTMLElement>()

const quantStrategies = computed(() => strategies.value.filter(s => s.source !== 'template' && s.source !== 'retail'))
const chatStrategies = computed(() => strategies.value.filter(s => s.source === 'template' || s.source === 'retail'))
const activeStrategyDesc = computed(() => {
  const s = strategies.value.find(x => x.id === activeStrategy.value)
  return s?.description || ''
})

const exampleHints = ['用缠论看 600519', '底部放量分析 000858', '今天有什么热点', '情绪周期看什么股票']

const scrollBottom = async () => {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

/** 简单 markdown 渲染（安全子集：标题/粗体/换行/代码块） */
function md(text: string): string {
  let s = String(text || '')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
  s = s.replace(/(^|\n)#{1,4}\s+(.*)/g, '$1<h4>$2</h4>')
  s = s.replace(/\n/g, '<br />')
  return s
}

const loadBudget = async () => {
  if (!currentSessionId.value) { budgetView.value = null; return }
  try {
    budgetView.value = await chatAgentApi.budget(currentSessionId.value)
  } catch { budgetView.value = null }
}

const loadStrategies = async () => {
  try {
    const data = await chatAgentApi.strategies()
    strategies.value = (Array.isArray(data) ? data : (data as any)?.data || [])
  } catch (e: any) {
    console.error('加载策略列表失败', e)
  }
}

const listSessions = async () => {
  sessionsLoading.value = true
  try {
    const data = await chatAgentApi.listSessions()
    sessions.value = (Array.isArray(data) ? data : (data as any)?.data || []).sort((a: any, b: any) => (b.updated_at || '').localeCompare(a.updated_at || ''))
  } finally {
    sessionsLoading.value = false
  }
}

const newSession = async () => {
  try {
    const s = await chatAgentApi.createSession()
    const created = (s as any)?.data || s
    sessions.value.unshift(created)
    await openSession((created as any).session_id)
  } catch (e: any) {
    ElMessage.error('新建会话失败：' + (e?.message || e))
  }
}

const openSession = async (sid: string) => {
  currentSessionId.value = sid
  messages.value = []
  try {
    const data = await chatAgentApi.getSession(sid)
    const s = (data as any)?.data || data
    messages.value = (s.messages || []).map((m: any) => ({ role: m.role, content: m.content }))
    if (s.active_strategy) activeStrategy.value = s.active_strategy
    else activeStrategy.value = null
    scrollBottom()
  } catch (e: any) {
    ElMessage.error('加载会话失败：' + (e?.message || e))
  }
  loadBudget()
}

const switchStrategy = async (val: string | null) => {
  activeStrategy.value = val
  if (!currentSessionId.value) return
  try {
    const s = await chatAgentApi.getSession(currentSessionId.value)
    void s
  } catch { /* 忽略 */ }
  if (val) ElMessage.info(`已选择策略：${val}（可新建会话后用该策略提问）`)
}

const sendNew = (text: string) => {
  input.value = text
  send()
}

const send = async () => {
  const text = input.value.trim()
  if (!text || streaming.value || !currentSessionId.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  streaming.value = true
  streamingText.value = ''
  pendingText.value = text
  streamInfo.value = ''
  scrollBottom()
  try {
    await chatStream(
      currentSessionId.value,
      text,
      (ev: any) => {
        if (ev.type === 'delta') {
          streamingText.value += ev.text || ''
          scrollBottom()
        } else if (ev.type === 'info') {
          streamInfo.value = ev.text || ''
        } else if (ev.type === 'error') {
          streamInfo.value = ''
          ElMessage.error(ev.message || '对话失败')
          if (ev.code === 'budget_exceeded') {
            // 会话预算触顶：会话被标记为 budget_exceeded，提示用户新建会话
            ElMessage.warning('会话预算已达上限，请新建会话继续')
          }
        }
      }
    )
  } catch (e: any) {
    ElMessage.error('请求失败：' + (e?.message || e))
  } finally {
    streaming.value = false
    if (streamingText.value.trim()) {
      messages.value.push({ role: 'assistant', content: streamingText.value })
    }
    streamingText.value = ''
    pendingText.value = ''
    streamInfo.value = ''
    loadBudget()
    listSessions()
    scrollBottom()
  }
}

onMounted(async () => {
  await loadStrategies()
  await listSessions()
  if (sessions.value.length) await openSession(sessions.value[0].session_id)
})
</script>

<style scoped>
.chat-agent { padding: 24px; display: flex; flex-direction: column; gap: 16px; }
.chat-layout { display: flex; gap: 16px; height: calc(100vh - 220px); min-height: 420px; }
.chat-side { width: 300px; flex-shrink: 0; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; }
.side-card { flex-shrink: 0; }
.side-head { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-weight: 600; font-size: 15px; }
.session-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; border: 1px solid #e4e7ed; margin-bottom: 8px; transition: all .2s; }
.session-item:hover { border-color: #409EFF; }
.session-item.active { border-color: #409EFF; background: #ecf5ff; }
.session-title { font-size: 13px; font-weight: 600; color: #303133; }
.session-meta { font-size: 12px; color: #909399; margin-top: 4px; }
.session-closed { color: #E6A23C; margin-left: 8px; }
.strategy-desc { font-size: 12px; color: #909399; margin-top: 8px; line-height: 1.6; }
.budget-body { display: flex; flex-direction: column; gap: 8px; }
.budget-row { display: flex; justify-content: space-between; font-size: 13px; }
.budget-row b { color: #303133; }
.budget-model { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.chat-main { flex: 1; display: flex; flex-direction: column; }
.chat-msgs { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.chat-welcome { margin: auto; text-align: center; color: #909399; }
.chat-welcome h3 { color: #303133; margin: 12px 0 8px; }
.chat-welcome p { font-size: 13px; line-height: 1.8; }
.welcome-hints { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.welcome-hint { cursor: pointer; }
.msg-row { display: flex; }
.msg-row.user { justify-content: flex-end; }
.msg-row.assistant { justify-content: flex-start; }
.msg-bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.7; word-break: break-word; }
.msg-bubble.user { background: #409EFF; color: #fff; border-top-right-radius: 2px; }
.msg-bubble.assistant { background: #f4f4f5; color: #303133; border-top-left-radius: 2px; }
.msg-toolnote { font-size: 12px; color: #909399; margin-top: 6px; }
.cursor { color: #409EFF; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0; } }
.stream-info { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #909399; }
.chat-input-bar { display: flex; gap: 12px; padding: 12px; border-top: 1px solid #f0f0f0; align-items: flex-end; }
.chat-input-bar .el-input { flex: 1; }
</style>