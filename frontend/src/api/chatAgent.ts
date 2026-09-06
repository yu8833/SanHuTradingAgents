import { ApiClient } from './request'

// ===== Agent 策略问股（对话子系统） =====

export interface ChatSession {
  session_id: string
  title: string
  status: string
  active_strategy?: string | null
  message_count: number
  created_at: string
  updated_at: string
  budget?: { rounds: number; total_tokens: number; total_cost: number }
  messages?: Array<{ role: string; content: string; created_at?: string }>
}

export interface ChatBudgetView {
  rounds_used: number
  tokens_used: number
  cost_used: number
  model_name?: string
}

export interface StrategyMetaItem {
  id: string
  name: string
  description?: string
  tags?: string[]
  source?: string
  market_regimes?: string[]
  frontend?: { icon?: string; color?: string; order?: number }
  buy_desc?: string[]
  sell_desc?: string[]
}

// NDJSON 流式对话：{session_id, message} → delta/error/done/info
export async function chatStream(
  sessionId: string,
  message: string,
  onEvent: (ev: any) => void,
  signal?: AbortSignal
): Promise<void> {
  const authStore = (await import('@/stores/auth')).useAuthStore()
  const token = authStore.token || localStorage.getItem('auth-token') || ''
  const controller = new AbortController()
  const combinedSignal = signal || controller.signal
  try {
    const resp = await fetch('/api/chat-agent/turns', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ session_id: sessionId, message }),
      signal: combinedSignal,
    })
    if (!resp.ok) {
      const errText = await resp.text()
      throw new Error(`请求失败(${resp.status}): ${errText.slice(0, 200)}`)
    }
    const reader = resp.body?.getReader()
    if (!reader) throw new Error('无法读取流式响应')
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        const t = line.trim()
        if (!t) continue
        try {
          onEvent(JSON.parse(t))
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  } finally {
    controller.abort()
  }
}

export const chatAgentApi = {
  createSession: (title?: string, strategy?: string | null) =>
    ApiClient.post<ChatSession>('/api/chat-agent/sessions', { title: title || '新问股会话', strategy: strategy ?? null }),
  listSessions: () => ApiClient.get<ChatSession[]>('/api/chat-agent/sessions'),
  getSession: (sid: string) => ApiClient.get<ChatSession>(`/api/chat-agent/sessions/${sid}`),
  closeSession: (sid: string) => ApiClient.delete<{ session_id: string; status: string }>(`/api/chat-agent/sessions/${sid}`),
  budget: (sid: string) => ApiClient.get<ChatBudgetView>(`/api/chat-agent/budget/${sid}`),
  strategies: () => ApiClient.get<StrategyMetaItem[]>('/api/chat-agent/strategies'),
}