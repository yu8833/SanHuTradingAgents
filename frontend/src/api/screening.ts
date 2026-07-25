import { ApiClient } from './request'

export interface ScreeningOrderBy { field: string; direction: 'asc' | 'desc' }
export interface ScreeningRunReq {
  market?: 'CN'
  date?: string | null
  adj?: 'qfq' | 'hfq' | 'none'
  conditions: any
  order_by?: ScreeningOrderBy[]
  limit?: number
  offset?: number
}

export interface ScreeningRunItem {
  code: string
  close?: number
  pct_chg?: number
  amount?: number
  ma20?: number
  rsi14?: number
  kdj_k?: number
  kdj_d?: number
  kdj_j?: number
  dif?: number
  dea?: number
  macd_hist?: number
}

export interface ScreeningRunResp { total: number; items: ScreeningRunItem[] }

// 筛选字段配置
export interface FieldInfo {
  name: string
  display_name: string
  field_type: string
  data_type: string
  description: string
  supported_operators: string[]
}

export interface FieldConfigResponse {
  fields: Record<string, FieldInfo>
  categories: Record<string, string[]>
}

// 行业列表响应
export interface IndustryOption {
  value: string
  label: string
  count: number
}

export interface IndustriesResponse {
  industries: IndustryOption[]
  total: number
}

export interface LimitUpPullbackScanReq {
  min_score?: number
  top_n?: number
  hold_days?: number
  initial_capital?: number
  limit?: number
}

export interface LimitUpPullbackBacktestReq extends LimitUpPullbackScanReq {
  start_date?: string
  end_date?: string
}

export interface LimitUpPullbackItem {
  code: string
  name: string
  close: number
  pct_chg: number
  limit_up_date: string
  days_since_limit_up: number
  limit_up_close: number
  pullback_depth: number
  volume_shrink_ratio: number
  ground_volume_ratio: number
  lower_shadow_pct: number
  signal_type: string
  score: number
  score_details: string[]
  upside_space: number
  ma5?: number
  ma10?: number
  ma20?: number
  small_body_ratio: number
  ground_day_offset: number
  industry: string
  shadow_to_body_ratio?: number
  space_position_ok?: boolean
  is_20day_ground?: boolean
  fake_breakout?: boolean
  days_since_ground_day?: number
  rebound_from_ground?: number
  // 各阶段日期
  pullback_start_date?: string
  pullback_end_date?: string
  bottom_watch_start_date?: string
  left_buy_date?: string
  right_buy_date?: string
  ground_day_date?: string
}

export interface LimitUpPullbackScanResp {
  total: number
  items: LimitUpPullbackItem[]
  took_ms?: number
  scanned_count?: number
  params?: Record<string, any>
}

export interface BacktestTrade {
  code: string
  name: string
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  return_pct: number
  score: number
  signal_type: string
  sell_reason: string
  // 各阶段日期
  limit_up_date?: string
  pullback_start_date?: string
  pullback_end_date?: string
  bottom_watch_start_date?: string
  left_buy_date?: string
  right_buy_date?: string
  ground_day_date?: string
  // 卖点日期
  stop_loss_date?: string
  time_stop_date?: string
  high_stop_date?: string
  ma5_stop_date?: string
}

export interface LimitUpPullbackBacktestResp {
  total_trades: number
  win_rate: number
  avg_return: number
  avg_win: number
  avg_loss: number
  profit_loss_ratio: number
  max_drawdown: number
  sharpe_ratio: number
  calmar_ratio: number
  annualized_return: number
  max_consecutive_losses: number
  total_fees_est: number
  total_return: number
  final_capital: number
  initial_capital: number
  backtest_days: number
  signal_stats: Record<string, { count: number; win_rate: number; avg_return: number }>
  sell_reason_stats: Record<string, { count: number; win_rate: number; avg_return: number }>
  daily_results: Array<{
    date: string
    total_value: number
    position_count: number
    position_pct: number
    cash: number
    position_value: number
    return_pct: number
    drawdown: number
    market_rise_ratio: number
  }>
  top_trades: BacktestTrade[]
  worst_trades: BacktestTrade[]
  params?: Record<string, any>
  took_ms?: number
}

// ===== 三买三卖策略 =====

export interface ThreeBuysThreeSellsScanReq {
  min_score?: number
  top_n?: number
  hold_days?: number
  initial_capital?: number
  max_position_pct?: number
  limit?: number
}

export interface ThreeBuysThreeSellsItem {
  code: string
  name: string
  industry: string
  market_cap: number
  close: number
  pct_chg: number
  bias60: number
  ma60: number
  ma60_direction: string
  ma60_slope: number
  stock_type: string
  stock_type_label: string
  signals: Array<{
    type: string
    type_label: string
    trigger_price: number
    position_pct?: number
  }>
  primary_signal_type: string
  primary_signal_label: string
  bottom_pickup: boolean
  macd_divergence: string
  volume_price_divergence: boolean
  score: number
  score_details: string[]
  s1_threshold: number
  stop_price: number
  volume_ratio: number
  atr14: number
  dif: number
  dea: number
  macd_hist: number
  dg_quadrant: string
  dg_available: boolean
  dg_g?: number
  dg_dg?: number
  market_trend: string
  trigger_date: string
}

export interface ThreeBuysThreeSellsScanResp {
  total: number
  items: ThreeBuysThreeSellsItem[]
  took_ms?: number
  scanned_count?: number
  params?: Record<string, any>
  market_trend?: string
}

export interface ThreeBuysThreeSellsBacktestReq extends ThreeBuysThreeSellsScanReq {
  start_date?: string
  end_date?: string
}

export interface ThreeBuysThreeSellsTrade {
  code: string
  name: string
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  return_pct: number
  score: number
  signal_type: string
  sell_reason: string
  profit: number
}

export interface ThreeBuysThreeSellsBacktestResp {
  total_trades: number
  win_rate: number
  avg_return: number
  avg_win: number
  avg_loss: number
  profit_loss_ratio: number
  max_drawdown: number
  sharpe_ratio: number
  calmar_ratio: number
  annualized_return: number
  max_consecutive_losses: number
  total_fees_est: number
  total_return: number
  final_capital: number
  initial_capital: number
  backtest_days: number
  signal_stats: Record<string, { count: number; win_rate: number; avg_return: number }>
  sell_reason_stats: Record<string, { count: number; win_rate: number; avg_return: number }>
  daily_results: Array<{
    date: string
    total_value: number
    position_count: number
    position_pct: number
    cash: number
    position_value: number
    return_pct: number
    drawdown: number
  }>
  top_trades: ThreeBuysThreeSellsTrade[]
  worst_trades: ThreeBuysThreeSellsTrade[]
  params?: Record<string, any>
  took_ms?: number
}

// ===== 散户策略通用类型（极端反转 / 困境反转 / 小盘价值 / 转债下修博弈） =====

export interface RetailScanReq {
  min_score?: number       // 最低评分
  limit?: number           // 返回数量
  top_n?: number           // 回测每次选股数
  hold_days?: number       // 持有天数
  initial_capital?: number // 初始资金
  // 转债下修博弈专用参数
  max_bond_price?: number          // 转债价格上限
  max_stock_vs_conversion?: number // 正股/转股价最大比值
  min_issue_size?: number          // 最小发行规模（亿元）
  [key: string]: any
}

export interface RetailBacktestReq extends RetailScanReq {
  start_date?: string
  end_date?: string
}

export interface RetailScanItem {
  code: string
  name: string
  industry?: string
  close: number
  pct_chg?: number
  score: number
  signal_type?: string
  score_details?: Record<string, any>
  [key: string]: any // 各策略会有额外字段
}

export interface RetailScanResp {
  total: number
  items: RetailScanItem[]
  took_ms?: number
  params?: any
}

export interface RetailBacktestResp {
  total_trades: number
  win_rate: number
  avg_return: number
  avg_win: number
  avg_loss: number
  profit_loss_ratio: number
  max_drawdown: number
  sharpe_ratio: number
  calmar_ratio: number
  annualized_return: number
  max_consecutive_losses: number
  total_fees_est: number
  total_return: number
  final_capital: number
  initial_capital: number
  backtest_days: number
  sell_reason_stats?: Record<string, { count: number; win_rate: number; avg_return: number }>
  daily_results?: any[]
  top_trades?: any[]
  worst_trades?: any[]
  params?: any
  took_ms?: number
}

export const screeningApi = {
  run: (payload: ScreeningRunReq, options?: { timeout?: number }) =>
    ApiClient.post<ScreeningRunResp>('/api/screening/run', payload, { timeout: options?.timeout ?? 120000 }),
  getFields: () => ApiClient.get<FieldConfigResponse>('/api/screening/fields'),
  getIndustries: () => ApiClient.get<IndustriesResponse>('/api/screening/industries'),
  scanLimitUpPullback: (payload: LimitUpPullbackScanReq, options?: { timeout?: number }) =>
    ApiClient.post<LimitUpPullbackScanResp>('/api/screening/limit-up-pullback/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestLimitUpPullback: (payload: LimitUpPullbackBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<LimitUpPullbackBacktestResp>('/api/screening/limit-up-pullback/backtest', payload, { timeout: options?.timeout ?? 300000 }),
  scanThreeBuysThreeSells: (payload: ThreeBuysThreeSellsScanReq, options?: { timeout?: number }) =>
    ApiClient.post<ThreeBuysThreeSellsScanResp>('/api/screening/three-buys-three-sells/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestThreeBuysThreeSells: (payload: ThreeBuysThreeSellsBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<ThreeBuysThreeSellsBacktestResp>('/api/screening/three-buys-three-sells/backtest', payload, { timeout: options?.timeout ?? 600000 }),

  // ===== 散户策略：极端反转 / 困境反转 / 小盘价值 / 转债下修博弈 =====
  scanExtremeReversal: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/extreme-reversal/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestExtremeReversal: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/extreme-reversal/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  scanTurnaround: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/turnaround/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestTurnaround: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/turnaround/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  scanSmallCapValue: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/small-cap-value/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestSmallCapValue: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/small-cap-value/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  scanConvertibleArbitrage: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/convertible-arbitrage/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestConvertibleArbitrage: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/convertible-arbitrage/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  // ===== 均线交叉策略 =====
  scanMaCrossover: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/ma-crossover/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestMaCrossover: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/ma-crossover/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  // ===== MACD背离策略 =====
  scanMacdDivergence: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/macd-divergence/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestMacdDivergence: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/macd-divergence/backtest', payload, { timeout: options?.timeout ?? 300000 }),

  // ===== 量价配合策略 =====
  scanVolumePrice: (payload: RetailScanReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailScanResp>('/api/screening/volume-price/scan', payload, { timeout: options?.timeout ?? 180000 }),
  backtestVolumePrice: (payload: RetailBacktestReq, options?: { timeout?: number }) =>
    ApiClient.post<RetailBacktestResp>('/api/screening/volume-price/backtest', payload, { timeout: options?.timeout ?? 300000 })
}

