import { ApiClient } from './request'

// ===== 散户策略中心 API =====

// ---- 仓位计算 ----
export interface HoldingItem {
  symbol: string
  industry?: string
  theme?: string
  market_value?: number
  position_ratio?: number
}

export interface PositionReq {
  account_size: number
  holdings?: HoldingItem[]
  symbol: string
  strategy?: string
  price: number
  win_rate?: number
  profit_loss_ratio?: number
  industry?: string
  theme?: string
  daily_volume_amount?: number | null
}

export interface PositionAdvice {
  symbol: string
  strategy: string
  suggested_shares: number
  suggested_amount: number
  target_position_ratio: number
  total_position_ratio_after: number
  blocked: boolean
  block_reasons: string[]
  warnings: string[]
}

// ---- 退出信号 ----
export interface ExitHoldingItem {
  symbol: string
  strategy?: string
  buy_price: number
  buy_date: string
  current_price: number
  current_ma?: number | null
  thesis_invalid?: boolean
  thesis_invalid_reason?: string
}

export interface ExitReq {
  holdings: ExitHoldingItem[]
}

export interface ExitSignal {
  symbol: string
  should_exit: boolean
  reason: string
  suggested_sell_ratio: number
  detail: string
  current_pnl_pct: number
  holding_days: number
}

export interface ExitResp {
  total: number
  signals: ExitSignal[]
  exits_count: number
}

// ---- 市场环境 ----
export interface RegimeReq {
  index_price: number
  index_ma250: number
  volatility_percentile: number
  breadth_ratio: number
  margin_balance_change_pct: number
  turnover_ratio: number
  turnover_ma20: number
}

export interface MarketRegime {
  trend: string
  volatility: string
  breadth: string
  sentiment: string
  active_strategies: string[]
  summary: string
}

// 自动检测返回（包含原始采集数据）
export interface RegimeRawData {
  index_price: number
  index_ma250: number
  volatility_percentile: number
  breadth_ratio: number
  margin_balance_change_pct: number
  turnover_ratio: number
  turnover_ma20: number
}

export interface MarketRegimeAuto extends MarketRegime {
  raw_data: RegimeRawData
  data_source: string
}

// ---- 策略列表 ----
export interface StrategyInfo {
  name: string
  edge: string
  hold_days: string
  win_condition: string
}

export interface RiskParams {
  max_single_position: number
  max_total_position: number
  max_single_loss: number
}

export interface StrategiesResp {
  strategies: Record<string, StrategyInfo>
  risk_params: Record<string, RiskParams>
}

// ---- 策略表现统计 ----
export interface StrategyPerformance {
  strategy: string
  total_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  profit_loss_ratio: number
  avg_return: number
}

export interface SuggestedParams {
  win_rate: number
  profit_loss_ratio: number
}

export interface StrategiesPerformanceResp {
  strategies: Record<string, StrategyPerformance>
  overall: StrategyPerformance
  suggested_params: Record<string, SuggestedParams>
}

export const retailApi = {
  // 仓位建议（后端返回原始dict，非ok()包装）
  calculatePosition: async (payload: PositionReq): Promise<PositionAdvice> => {
    const res = await ApiClient.post('/api/retail/position', payload)
    return res as any
  },

  // 退出信号检查
  checkExits: async (payload: ExitReq): Promise<ExitResp> => {
    const res = await ApiClient.post('/api/retail/exits', payload)
    return res as any
  },

  // 市场环境检测（手动传参）
  detectRegime: async (payload: RegimeReq): Promise<MarketRegime> => {
    const res = await ApiClient.post('/api/retail/regime', payload)
    return res as any
  },

  // 市场环境自动检测（无需传参，后端自动采集数据）
  detectRegimeAuto: async (): Promise<MarketRegimeAuto> => {
    const res = await ApiClient.get('/api/retail/regime/auto')
    return res as any
  },

  // 策略列表及风控参数
  getStrategies: async (): Promise<StrategiesResp> => {
    const res = await ApiClient.get('/api/retail/strategies')
    return res as any
  },

  // 策略表现统计（基于已平仓持仓的真实数据）
  getStrategiesPerformance: async (): Promise<StrategiesPerformanceResp> => {
    const res = await ApiClient.get('/api/retail/strategies/performance')
    return res as any
  },
}
