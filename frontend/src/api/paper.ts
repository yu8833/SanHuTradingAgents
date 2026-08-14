import { ApiClient } from './request'

export interface CurrencyAmount {
  CNY: number
  HKD: number
  USD: number
}

export interface PaperAccountSummary {
  cash: CurrencyAmount | number  // 支持新旧格式
  realized_pnl: CurrencyAmount | number  // 支持新旧格式
  positions_value: CurrencyAmount
  equity: CurrencyAmount | number  // 支持新旧格式
  updated_at?: string
}

export interface PaperPositionItem {
  code: string
  quantity: number
  avg_cost: number
  last_price?: number | null
  market_value?: number
  unrealized_pnl?: number | null
}

export interface PaperOrderItem {
  user_id?: string
  code: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  status: 'filled' | 'rejected' | string
  created_at: string
  filled_at?: string
}

export interface GetAccountResponse {
  account: PaperAccountSummary
  positions: PaperPositionItem[]
}

export interface HoldingHealth {
  total: number
  red: number
  green: number
  all_red_rate: number
  holdings: Array<{
    code: string
    name?: string
    pnl: number | null
    pnl_pct: number | null
    status: 'red' | 'green' | 'unknown'
    market_value: number
  }>
}

export interface RiskControlStatus {
  current_equity: number
  weekly_peak: number
  monthly_peak: number
  weekly_dd_pct: number
  monthly_dd_pct: number
  level: number
  max_position_pct: number
  level_label: string
  level_action: string
  account_paused: boolean
  account_paused_reason?: string
  consecutive_stop_loss_limit?: number
  holding_health?: HoldingHealth
}

export interface PlaceOrderPayload {
  code: string
  side: 'buy' | 'sell'
  quantity: number
  analysis_id?: string
  // 散户策略元数据（买入时写入 paper_positions）
  strategy?: string
  stop_loss_price?: number | null
  take_profit_price?: number | null
  thesis?: string
  stock_name?: string
}

export const paperApi = {
  async getAccount() {
    return ApiClient.get<GetAccountResponse>('/api/paper/account')
  },
  async getRisk() {
    return ApiClient.get<{ risk: RiskControlStatus }>('/api/paper/risk')
  },
  async placeOrder(data: PlaceOrderPayload) {
    return ApiClient.post<{ order: PaperOrderItem }>('/api/paper/order', data, { showLoading: true })
  },
  async getPositions() {
    return ApiClient.get<{ items: PaperPositionItem[] }>('/api/paper/positions')
  },
  async getOrders(limit = 50) {
    return ApiClient.get<{ items: PaperOrderItem[] }>(`/api/paper/orders`, { limit })
  },
  async resetAccount() {
    // 后端要求 confirm=true
    return ApiClient.post<{ message: string; cash: number }>(`/api/paper/reset?confirm=true`)
  }
}

// ==================== 交易复盘 ====================

export interface ReviewCycleItem {
  code: string
  name: string
  strategy: string
  buy_price: number
  sell_price: number
  quantity: number
  pnl: number
  pnl_pct: number
  buy_time: string
  sell_time: string
}

export interface ReviewNoteItem {
  id?: string
  trade_id?: string | null
  code?: string | null
  name?: string | null
  strategy?: string | null
  result?: string | null
  lesson?: string | null
  improvement?: string | null
  tags?: string[]
  created_at?: string
  updated_at?: string
}

export interface ReviewStats {
  total_cycles: number
  win_count: number
  loss_count: number
  win_rate: number
  profit_loss_ratio: number
  total_pnl: number
  attribution: Record<string, number>
  result_options: string[]
}

export const reviewApi = {
  async getTrades() {
    return ApiClient.get<{ items: ReviewCycleItem[]; total: number }>('/api/paper/review/trades')
  },
  async getNotes() {
    return ApiClient.get<{ items: ReviewNoteItem[] }>('/api/paper/review/notes')
  },
  async createNote(data: Partial<ReviewNoteItem>) {
    return ApiClient.post<{ id: string }>('/api/paper/review/notes', data)
  },
  async updateNote(id: string, data: Partial<ReviewNoteItem>) {
    return ApiClient.put<{ message: string }>(`/api/paper/review/notes/${id}`, data)
  },
  async deleteNote(id: string) {
    return ApiClient.delete<{ message: string }>(`/api/paper/review/notes/${id}`)
  },
  async getStats() {
    return ApiClient.get<ReviewStats>('/api/paper/review/stats')
  }
}
