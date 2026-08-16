/**
 * 待确认指令实时推送 SSE 订阅工具
 *
 * 后端监控引擎生成新的股票买卖待确认指令时，通过 Redis publish 到
 * `monitor_orders:{user_id}` 频道，前端订阅 `/api/stream/monitor-orders` 接收。
 * 收到 `order` 事件后，立即弹出确认页供用户确认执行或忽略。
 *
 * 与「立即评估」弹窗互补：
 * - SSE 信号实时到达后立即弹窗（延迟约 0-2 秒）
 * - 立即评估/手动刷新作为兜底，防止 SSE 断连期间漏掉指令
 *
 * 注意：这是「主动弹窗」链路，"立即评估"的展示链路不受影响。
 */

const SSE_RECONNECT_BASE_DELAY = 1000 // 首次重连 1 秒
const SSE_RECONNECT_MAX_DELAY = 5000  // 最大重连间隔 5 秒
const MAX_RECONNECT_ATTEMPTS = 10     // 最大重连次数

// 重连延迟：指数退避 + 随机抖动，避免多客户端同时重连
const getReconnectDelay = (attempt: number): number => {
  const exp = Math.min(SSE_RECONNECT_BASE_DELAY * Math.pow(2, attempt - 1), SSE_RECONNECT_MAX_DELAY)
  return exp + Math.random() * 300
}

export interface PendingOrderEvent {
  type: string
  user_id: string
  order: Record<string, unknown>
}

/**
 * 订阅待确认指令实时推送信号
 *
 * @param onOrder 收到新待确认指令（order 事件）时的回调
 * @returns 取消订阅函数（调用后关闭 SSE 连接）
 */
export function subscribeMonitorOrders(onOrder: (event: PendingOrderEvent) => void): () => void {
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let isClosed = false

  const getToken = (): string | null => localStorage.getItem('auth-token')
  const getBaseUrl = (): string => import.meta.env.VITE_API_BASE_URL || ''

  const connect = () => {
    if (isClosed) return

    const token = getToken()
    if (!token) {
      console.warn('[MonitorOrdersSSE] 未找到 token，跳过 SSE 订阅')
      return
    }

    const baseUrl = getBaseUrl()
    const url = `${baseUrl}/api/stream/monitor-orders?token=${encodeURIComponent(token)}`

    try {
      eventSource = new EventSource(url)
    } catch (e) {
      console.warn('[MonitorOrdersSSE] EventSource 创建失败:', e)
      return
    }

    eventSource.addEventListener('connected', () => {
      console.log('[MonitorOrdersSSE] 已连接待确认指令信号流')
      reconnectAttempts = 0
    })

    eventSource.addEventListener('order', (event: MessageEvent) => {
      try {
        const data: PendingOrderEvent = JSON.parse(event.data)
        onOrder(data)
      } catch (e) {
        console.warn('[MonitorOrdersSSE] 解析 order 事件失败:', e)
      }
    })

    eventSource.addEventListener('heartbeat', () => {
      // 心跳仅用于保活，无需处理
    })

    eventSource.addEventListener('error', () => {
      console.warn('[MonitorOrdersSSE] 连接错误，准备重连...')
      if (eventSource) {
        eventSource.close()
        eventSource = null
      }
      if (isClosed) return
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        const delay = getReconnectDelay(reconnectAttempts)
        reconnectTimer = setTimeout(() => {
          connect()
        }, delay)
      } else {
        console.warn('[MonitorOrdersSSE] 达到最大重连次数，停止重连')
      }
    })
  }

  connect()

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
    console.log('[MonitorOrdersSSE] 已取消订阅')
  }
}