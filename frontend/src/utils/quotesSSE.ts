/**
 * 实时行情 SSE 订阅工具
 *
 * 后端 quotes_ingestion_service 每次入库完成后会通过 Redis publish 通知。
 * 前端通过 fetch-based SSE 订阅 /api/sse/quotes 接收信号，
 * 收到 quotes_update 事件后主动拉取最新行情（信号若带值则原地 patch）。
 *
 * 与 30 秒轮询互补：
 * - SSE 信号到达后立即拉取（延迟约 0-2 秒）
 * - 30 秒轮询作为兜底，防止 SSE 断连
 *
 * P3-7：改用 fetch + ReadableStream 解析 SSE，通过 Authorization header 携带 token，
 *       不再把 token 拼进 URL（避免进入浏览器历史与网关 access log）。
 *       后端 get_current_user_for_sse 优先读取 Authorization header，原生支持。
 */

const SSE_RECONNECT_BASE_DELAY = 1000 // 首次重连 1 秒
const SSE_RECONNECT_MAX_DELAY = 5000  // 最大重连间隔 5 秒
const MAX_RECONNECT_ATTEMPTS = 10 // 最大重连次数

// 重连延迟：指数退避，前几次快速重连以应对瞬时网络抖动，
// 之后逐步拉长间隔，避免频繁无效请求；加入随机抖动防止多客户端同时重连。
const getReconnectDelay = (attempt: number): number => {
  const exp = Math.min(SSE_RECONNECT_BASE_DELAY * Math.pow(2, attempt - 1), SSE_RECONNECT_MAX_DELAY)
  return exp + Math.random() * 300
}

export interface QuotesUpdateSignal {
  type: string
  trade_date: string
  source: string
  count: number
  timestamp: number
  /** P3-6：可选携带本批已落库的 {code: {close, pct_chg}}，前端可原地 patch 避免陈旧读取 */
  quotes?: Record<string, { close: number; pct_chg: number | null }>
}

/**
 * 订阅实时行情更新信号
 *
 * @param onUpdate 收到 quotes_update 事件时的回调
 * @param onStatus 连接状态回调（P5-12：`connected` 恢复正常，`degraded` 进入降级轮询态），
 *                 形如 "行情实时中断，已切换定时刷新"
 * @returns 取消订阅函数（调用后关闭 SSE 连接）
 */
export function subscribeQuotesUpdate(
  onUpdate: (signal: QuotesUpdateSignal) => void,
  onStatus?: (status: 'connected' | 'degraded') => void
): () => void {
  let controller: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let isClosed = false
  let connecting = false // 防重入：同一时刻只允许一个连接在途

  const getToken = (): string | null => {
    return localStorage.getItem('auth-token')
  }

  const getBaseUrl = (): string => {
    return import.meta.env.VITE_API_BASE_URL || ''
  }

  const scheduleReconnect = (): void => {
    if (isClosed) return
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      reconnectAttempts++
      const delay = getReconnectDelay(reconnectAttempts)
      reconnectTimer = setTimeout(() => {
        console.log(`[QuotesSSE] 第 ${reconnectAttempts} 次重连...`)
        connecting = false
        connect()
      }, delay)
    } else {
      console.warn('[QuotesSSE] 达到最大重连次数，停止重连（依赖轮询兜底）')
      // P5-12：通知调用方进入降级轮询态，UI 可对用户展示"行情实时中断"提示
      onStatus?.('degraded')
    }
  }

  const connect = async (): Promise<void> => {
    if (isClosed || connecting) return

    const token = getToken()
    if (!token) {
      console.warn('[QuotesSSE] 未找到 token，跳过 SSE 订阅（依赖轮询兜底）')
      onStatus?.('degraded')
      return
    }

    const baseUrl = getBaseUrl()
    const controllerId = new AbortController()
    controller = controllerId
    connecting = true

    try {
      const resp = await fetch(`${baseUrl}/api/stream/quotes`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controllerId.signal,
      })
      if (!resp.ok || !resp.body) {
        throw new Error(`SSE HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let event = 'message'
      let dataBuffer: string[] = []

      const dispatchEvent = (): void => {
        const raw = dataBuffer.join('\n')
        dataBuffer = []
        if (event === 'connected') {
          console.log('[QuotesSSE] 已连接实时行情信号流')
          reconnectAttempts = 0
          // P5-12：连接恢复，通知调用方退出降级态
          onStatus?.('connected')
        } else if (event === 'quotes_update' && raw) {
          try {
            onUpdate(JSON.parse(raw) as QuotesUpdateSignal)
          } catch (e) {
            console.warn('[QuotesSSE] 解析 quotes_update 事件失败:', e)
          }
        }
        // heartbeat / 其它事件：无需处理
        event = 'message'
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 按行处理，保留最后一行（可能不完整）留到下一块
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.replace(/\r$/, '')
          if (trimmed === '') {
            // 空行 = 事件结束
            dispatchEvent()
          } else if (trimmed.startsWith(':')) {
            // 注释或 retry 指令，忽略
            continue
          } else if (trimmed.startsWith('event:')) {
            event = trimmed.slice(6).trim()
          } else if (trimmed.startsWith('data:')) {
            dataBuffer.push(trimmed.slice(5).replace(/^ /, ''))
          }
          // id/retry 字段：忽略
        }
      }
      // 流正常结束（服务端关闭）→ 按断连处理
      connecting = false
      if (!isClosed) {
        console.warn('[QuotesSSE] 连接被服务端关闭，准备重连...')
        scheduleReconnect()
      }
    } catch (e) {
      connecting = false
      if (isClosed || controllerId.signal.aborted) return
      console.warn('[QuotesSSE] 连接错误，准备重连...', {
        attempt: reconnectAttempts + 1,
        error: e
      })
      scheduleReconnect()
    }
  }

  connect()

  // 返回取消订阅函数
  return () => {
    isClosed = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (controller) {
      controller.abort()
      controller = null
    }
    console.log('[QuotesSSE] 已取消订阅')
  }
}