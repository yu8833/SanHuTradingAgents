/**
 * 实时行情 SSE 订阅工具
 *
 * 后端 quotes_ingestion_service 每次入库完成后会通过 Redis publish 通知。
 * 前端通过 EventSource 订阅 /api/sse/quotes 接收信号，
 * 收到 quotes_update 事件后主动拉取最新行情。
 *
 * 与 30 秒轮询互补：
 * - SSE 信号到达后立即拉取（延迟约 0-2 秒）
 * - 30 秒轮询作为兜底，防止 SSE 断连
 */

const SSE_RECONNECT_DELAY = 5000 // 断连后 5 秒重连
const MAX_RECONNECT_ATTEMPTS = 10 // 最大重连次数

export interface QuotesUpdateSignal {
  type: string
  trade_date: string
  source: string
  count: number
  timestamp: number
}

/**
 * 订阅实时行情更新信号
 *
 * @param onUpdate 收到 quotes_update 事件时的回调
 * @returns 取消订阅函数（调用后关闭 SSE 连接）
 */
export function subscribeQuotesUpdate(onUpdate: (signal: QuotesUpdateSignal) => void): () => void {
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let isClosed = false

  const getToken = (): string | null => {
    return localStorage.getItem('auth-token')
  }

  const getBaseUrl = (): string => {
    return import.meta.env.VITE_API_BASE_URL || ''
  }

  const connect = () => {
    if (isClosed) return

    const token = getToken()
    if (!token) {
      console.warn('[QuotesSSE] 未找到 token，跳过 SSE 订阅（依赖轮询兜底）')
      return
    }

    const baseUrl = getBaseUrl()
    const url = `${baseUrl}/api/stream/quotes?token=${encodeURIComponent(token)}`

    try {
      eventSource = new EventSource(url)
    } catch (e) {
      console.warn('[QuotesSSE] EventSource 创建失败:', e)
      return
    }

    eventSource.addEventListener('connected', () => {
      console.log('[QuotesSSE] 已连接实时行情信号流')
      reconnectAttempts = 0
    })

    eventSource.addEventListener('quotes_update', (event: MessageEvent) => {
      try {
        const data: QuotesUpdateSignal = JSON.parse(event.data)
        onUpdate(data)
      } catch (e) {
        console.warn('[QuotesSSE] 解析 quotes_update 事件失败:', e)
      }
    })

    eventSource.addEventListener('heartbeat', () => {
      // 心跳仅用于保活，无需处理
    })

    eventSource.addEventListener('error', (event: Event) => {
      console.warn('[QuotesSSE] 连接错误，准备重连...', {
        readyState: eventSource?.readyState,
        attempt: reconnectAttempts + 1
      })

      if (eventSource) {
        eventSource.close()
        eventSource = null
      }

      if (isClosed) return

      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        reconnectTimer = setTimeout(() => {
          console.log(`[QuotesSSE] 第 ${reconnectAttempts} 次重连...`)
          connect()
        }, SSE_RECONNECT_DELAY)
      } else {
        console.warn('[QuotesSSE] 达到最大重连次数，停止重连（依赖轮询兜底）')
      }
    })
  }

  connect()

  // 返回取消订阅函数
  return () => {
    isClosed = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    console.log('[QuotesSSE] 已取消订阅')
  }
}
