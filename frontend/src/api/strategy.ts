import { ApiClient } from './request'

// ===== 策略筛选 =====
export interface StrategyParam {
  id: string
  label: string
  type: string
  default: any
  min?: number
  max?: number
  step?: number
}

export interface StrategyMeta {
  id: string
  name: string
  description: string
  tags: string[]
  params: StrategyParam[]
  scoring: Record<string, number>
  entry_signals: string[]
  exit_signals: string[]
  source: string
  asset_types: string[]
}

export interface StrategyRunItem {
  symbol: string
  code: string
  name: string
  close?: number
  change_pct?: number
  open?: number
  high?: number
  low?: number
  volume?: number
  amount?: number
  vol_ratio?: number
  score: number
  date: string
}

export interface StrategyRunResult {
  as_of: string
  strategy_id: string
  strategy_name: string
  total: number
  items: StrategyRunItem[]
  elapsed_ms: number
  message?: string
}

export interface StrategyRunAllItem {
  id: string
  name: string
  description: string
  tags: string[]
  count: number
  top: StrategyRunItem[]
  error?: string
}

export interface StrategyRunAllResult {
  as_of: string
  strategies: StrategyRunAllItem[]
  elapsed_ms: number
  computed_at?: string
  cached?: boolean
}

// ===== 回测 =====
export interface BacktestConfig {
  strategy_id: string
  start: string
  end: string
  symbols?: string[]
  params?: Record<string, any>
  entry_fill: string
  exit_fill: string
  fees_pct: number
  slippage_bps: number
  max_positions: number
  max_exposure_pct: number
  initial_capital: number
  position_sizing: string
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  max_hold_days?: number | null
  holding_days: number
}

export interface BacktestStats {
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe: number
  win_rate: number
  profit_factor: number | null
  n_trades: number
  n_days: number
  avg_win: number
  avg_loss: number
  best: number
  worst: number
}

export interface BacktestTrade {
  symbol: string
  name: string
  entry_date: string
  exit_date: string
  entry_price: number
  exit_price: number
  shares: number
  entry_value: number
  exit_value: number
  pnl_amount: number
  pnl_pct: number
  duration: number
  exit_reason: string
  entry_score?: number
  position_pct?: number
}

export interface BacktestResult {
  run_id: string
  success: boolean
  config: BacktestConfig
  stats: BacktestStats
  equity_curve: Array<{ date: string; value: number; positions: number }>
  drawdown_curve: Array<{ date: string; value: number }>
  benchmark_curve: any[]
  trades: BacktestTrade[]
  per_symbol_stats: Array<{
    symbol: string
    name: string
    n_trades: number
    win_rate: number
    total_pnl: number
    avg_pnl: number
  }>
  strategy_info?: {
    id: string
    name: string
    description: string
    entry_signals: string[]
    exit_signals: string[]
  }
  elapsed_ms: number
  error?: string
}

export interface FactorBacktestResult {
  run_id: string
  success: boolean
  config: { factor_name: string; start: string; end: string; n_groups: number; rebalance: string }
  stats: {
    ic_mean: number
    ic_std: number
    ic_ir: number
    ic_positive_ratio: number
    n_days: number
  }
  ic_series: Array<{ date: string; value: number }>
  group_returns: Array<{ group: string; avg_return: number; cum_return: number; n_days: number }>
  long_short: { avg_return: number; cum_return: number }
  elapsed_ms: number
  error?: string
}

export interface OptimizeResult {
  run_id: string
  success: boolean
  config: { strategy_id: string; objective: string; param_grid: any; start: string; end: string }
  n_trials: number
  results: Array<{ params: Record<string, any>; objective: string; value: number; stats: BacktestStats }>
  elapsed_ms: number
  error?: string
}

export interface WalkForwardResult {
  run_id: string
  success: boolean
  config: {
    strategy_id: string
    start: string
    end: string
    train_days: number
    test_days: number
    param_grid: any
  }
  n_folds: number
  avg_test_return: number
  folds: Array<{
    train: { start: string; end: string }
    test: { start: string; end: string }
    best_params: any
    stats: BacktestStats
    success: boolean
    error?: string
  }>
  elapsed_ms: number
  error?: string
}

// 回测结果对比项（后端从 MongoDB 持久化返回的精简字段）
export interface CompareResultItem {
  strategy_id: string
  strategy_name: string
  config?: { start: string; end: string }
  stats: BacktestStats
  equity_curve: Array<{ date: string; value: number }>
  saved_at: number
}

// 因子候选列表（与后端 indicators 计算出的列对应）
export const FACTOR_OPTIONS = [
  { value: 'momentum_20d', label: '20日动量' },
  { value: 'momentum_5d', label: '5日动量' },
  { value: 'momentum_60d', label: '60日动量' },
  { value: 'vol_ratio_5d', label: '5日量比' },
  { value: 'rsi_14', label: 'RSI14' },
  { value: 'macd_hist', label: 'MACD柱' },
  { value: 'annual_vol_20d', label: '20日年化波动' },
  { value: 'change_pct', label: '涨跌幅' },
  { value: 'close', label: '收盘价' },
]

export const strategyApi = {
  list: () => ApiClient.get<StrategyMeta[]>('/api/strategy/list'),
  tradeDates: (limit?: number) => ApiClient.get<{ dates: string[] }>('/api/strategy/trade-dates', { limit: limit ?? 30 }),
  run: (payload: { strategy_id: string; as_of?: string | null; params?: any; limit?: number; pool?: string[] }, options?: { timeout?: number }) =>
    ApiClient.post<StrategyRunResult>('/api/strategy/run', payload, { timeout: options?.timeout ?? 300000 }),
  runAll: (payload: { as_of?: string | null; limit?: number; pool?: string[]; refresh?: boolean }, options?: { timeout?: number }) =>
    ApiClient.post<StrategyRunAllResult>('/api/strategy/run-all', payload, { timeout: options?.timeout ?? 300000 }),
  backtest: (payload: BacktestConfig, options?: { timeout?: number }) =>
    ApiClient.post<BacktestResult>('/api/strategy/backtest', payload, { timeout: options?.timeout ?? 600000 }),
  factorBacktest: (payload: any, options?: { timeout?: number }) =>
    ApiClient.post<FactorBacktestResult>('/api/strategy/factor/backtest', payload, { timeout: options?.timeout ?? 600000 }),
  optimize: (payload: any, options?: { timeout?: number }) =>
    ApiClient.post<OptimizeResult>('/api/strategy/optimize', payload, { timeout: options?.timeout ?? 600000 }),
  walkforward: (payload: any, options?: { timeout?: number }) =>
    ApiClient.post<WalkForwardResult>('/api/strategy/walkforward', payload, { timeout: options?.timeout ?? 600000 }),

  // ===== 异步回测任务（长时计算，支持进度轮询与结果恢复） =====
  startBacktest: (payload: BacktestConfig) =>
    ApiClient.post<{ task_id: string; status: string; kind: string }>('/api/strategy/backtest/start', payload),
  startFactorBacktest: (payload: any) =>
    ApiClient.post<{ task_id: string; status: string; kind: string }>('/api/strategy/factor/backtest/start', payload),
  startOptimize: (payload: any) =>
    ApiClient.post<{ task_id: string; status: string; kind: string }>('/api/strategy/optimize/start', payload),
  startWalkforward: (payload: any) =>
    ApiClient.post<{ task_id: string; status: string; kind: string }>('/api/strategy/walkforward/start', payload),
  getTask: (taskId: string) =>
    ApiClient.get<{
      task_id: string
      kind: string
      status: 'running' | 'success' | 'failure'
      progress: number
      message: string
      elapsed_ms: number
      result?: any
      error?: string
    }>(`/api/strategy/task/${taskId}`),

  // ===== 回测结果对比（持久化到 MongoDB） =====
  backtestResults: () => ApiClient.get<CompareResultItem[]>('/api/strategy/backtest/results'),
  importBacktestResult: (result: BacktestResult) =>
    ApiClient.post<{ saved: boolean }>('/api/strategy/backtest/results', result),
  deleteBacktestResult: (strategyId: string) =>
    ApiClient.delete<{ deleted: number }>(`/api/strategy/backtest/results/${encodeURIComponent(strategyId)}`),
}