import { ApiClient } from './request'

// 持仓项
export interface PositionItem {
  id: string
  user_id?: string
  symbol: string
  code?: string
  stock_name: string
  quantity: number
  cost_price: number
  avg_cost?: number
  position_ratio: number
  buy_date: string
  notes?: string | null
  strategy?: string
  stop_loss_price?: number | null
  take_profit_price?: number | null
  thesis?: string | null
  status?: string
  exit_price?: number | null
  exit_date?: string | null
  exit_reason?: string | null
  created_at?: string
  updated_at?: string
  // 汇总时附加
  current_price?: number | null
  market_value?: number
  profit_loss?: number
  profit_loss_rate?: number
  cost?: number
}

// 持仓汇总
export interface PositionSummary {
  total_positions: number
  total_cost: number
  total_market_value?: number
  total_quantity: number
  total_profit_loss?: number
  profit_loss_rate?: number
  positions: PositionItem[]
}

// 策略表现
export interface StrategyPerformance {
  strategy: string
  total_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  profit_loss_ratio: number
  avg_return: number
}

// 添加持仓请求
export interface AddPositionPayload {
  symbol: string
  stock_name: string
  quantity: number
  cost_price: number
  position_ratio: number
  buy_date: string
  notes?: string
  strategy?: string
  stop_loss_price?: number | null
  take_profit_price?: number | null
  thesis?: string
}

// 更新持仓请求
export interface UpdatePositionPayload {
  quantity?: number
  cost_price?: number
  position_ratio?: number
  notes?: string
  stop_loss_price?: number | null
  take_profit_price?: number | null
  thesis?: string
}

// 平仓请求
export interface ClosePositionPayload {
  exit_price: number
  exit_date?: string
  exit_reason?: string
}

// 已平仓交易记录（用于交易复盘）
export interface ClosedTrade {
  id: string
  code: string
  stock_name: string
  market?: string
  currency?: string
  quantity: number
  avg_cost: number
  strategy?: string
  buy_date?: string
  thesis?: string | null
  stop_loss_price?: number | null
  take_profit_price?: number | null
  status: string
  exit_price?: number | null
  exit_date?: string | null
  exit_reason?: string | null
  realized_pnl?: number | null
  created_at?: string
  updated_at?: string
}

export const portfolioApi = {
  // 获取持仓列表
  async getPositions() {
    return ApiClient.get<PositionItem[]>('/api/portfolio/positions')
  },

  // 添加持仓
  async addPosition(data: AddPositionPayload) {
    return ApiClient.post<PositionItem>('/api/portfolio/positions', data)
  },

  // 更新持仓（设置止损/止盈等）
  async updatePosition(positionId: string, data: UpdatePositionPayload) {
    return ApiClient.put<PositionItem>(`/api/portfolio/positions/${positionId}`, data)
  },

  // 删除持仓
  async deletePosition(positionId: string) {
    return ApiClient.delete<{ position_id: string }>(`/api/portfolio/positions/${positionId}`)
  },

  // 持仓汇总
  async getSummary() {
    return ApiClient.get<PositionSummary>('/api/portfolio/summary')
  },

  // 批量导入
  async importPositions(positions: AddPositionPayload[]) {
    return ApiClient.post<{ total: number; success_count: number }>('/api/portfolio/positions/import', { positions })
  },

  // CSV导入实盘交易记录
  async importCsv(file: File, strategy: string = 'default') {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('strategy', strategy)
    return ApiClient.post<{ total: number; success_count: number; skipped: number; strategy: string }>(
      '/api/portfolio/positions/import-csv',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
  },

  // 平仓
  async closePosition(positionId: string, data: ClosePositionPayload) {
    return ApiClient.post<PositionItem>(`/api/portfolio/${positionId}/close`, data)
  },

  // 获取未平仓持仓
  async getOpenPositions() {
    return ApiClient.get<PositionItem[]>('/api/portfolio/open/list')
  },

  // 按策略获取持仓
  async getPositionsByStrategy(strategy: string) {
    return ApiClient.get<PositionItem[]>(`/api/portfolio/strategy/${strategy}/positions`)
  },

  // 策略表现统计
  async getStrategyPerformance(strategy?: string) {
    const url = strategy ? `/api/portfolio/strategy/performance?strategy=${strategy}` : '/api/portfolio/strategy/performance'
    return ApiClient.get<StrategyPerformance>(url)
  },

  // 获取已平仓交易记录（用于交易复盘）
  async getClosedTrades() {
    const res = await ApiClient.get<{ items: ClosedTrade[] }>('/api/paper/positions?status=closed')
    return res?.items || []
  },
}
