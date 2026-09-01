import { ApiClient } from './request'

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

export interface WarRoomToday {
  current_period: 'pre_market' | 'intraday' | 'post_market' | 'weekly'
  today: string
  week_start: string
  pre_market: {
    macro_snapshot_ready: boolean
    plan_pending: number
    plan_total: number
  }
  intraday: {
    holding_count: number
    alert_count: number
  }
  post_market: {
    signal_pending: number
    signal_total: number
  }
  weekly: { done: boolean; todo: number }
  total_todo: number
}

export interface MacroSnapshot {
  date: string
  indices?: { key: string; name: string; region: string; price: number | null; change_pct: number | null }[]
  calendar?: { date: string; region: string; event: string; importance: string; forecast?: string; actual?: string }[]
  news_top?: { publish_time?: string; title: string; importance: string; summary?: string }[]
  rule?: { score: number; direction: string; confidence: number; signals: any[] }
  llm_interpretation?: {
    keywords?: string[]
    event_impact?: string
    style_tendency?: string
    risk_tips?: string
  } | null
  llm_available?: boolean
  created_at?: string
}

export interface SignalItem {
  id?: string
  signal_type: string
  code: string
  name?: string
  trigger_date: string
  snapshot?: Record<string, any>
  status: 'pending' | 'filled'
  filled?: { ret: number; outcome: 'win' | 'loss' | 'flat'; hit_stop?: boolean }
}

export interface PlanItem {
  id: string
  code: string
  name?: string
  direction: 'buy' | 'sell'
  trigger_price?: number | null
  stop_loss?: number | null
  sell_condition?: string | null
  status: 'pending' | 'executed' | 'cancelled'
  position?: Record<string, any> | null
}

export interface TodayTrade {
  code: string
  name: string
  side: 'buy' | 'sell'
  quantity: number
  price?: number | null
  amount?: number | null
  pnl?: number | null
  strategy?: string | null
  timestamp?: string
}

export interface TodayAlert {
  id?: string
  ts?: number
  rule_name?: string
  source?: string
  symbol?: string
  name?: string
  message?: string
  price?: number | null
  change_pct?: number | null
  signals?: string[]
  severity?: string
}

export interface WeeklyReview {
  week_start: string
  week_end: string
  quant?: {
    weekly_return: number | null
    trade_count: number
    win_rate: number | null
    win_count: number
    sell_count: number
    realized_pnl: number
    holding_count: number
    profitable_count: number
    all_red_rate: number | null
  }
  benchmark?: { available: boolean; ret_pct?: number | null; message?: string }
  excess_return?: number | null
  signal_stats?: { by_type?: any[]; total?: any; pending_count?: number }
  positions_snapshot?: any[]
}

// ---------------------------------------------------------------------------
// API 接口
// ---------------------------------------------------------------------------

export const warRoomApi = {
  // 今日聚合（引导条）
  async getToday() {
    const res = await ApiClient.get<WarRoomToday>('/api/war-room/today')
    return res.data
  },

  // 盘前：宏观快照
  async getMacroOverview(date?: string, refresh = false) {
    const res = await ApiClient.get<MacroSnapshot | null>('/api/macro/daily-overview', {
      date: date || undefined,
      refresh: refresh || undefined
    }, { timeout: 120000 })
    return res.data
  },

  // 盘前：手动刷新宏观快照（立即刷新，绕过 8:15 定时任务）
  async refreshMacro() {
    const res = await ApiClient.post<MacroSnapshot | null>('/api/macro/refresh', undefined, { timeout: 120000 })
    return res.data
  },

  // 盘中：今日触发预警列表（与今日聚合角标同口径）
  async getTodayAlerts() {
    const res = await ApiClient.get<{ total: number; items: TodayAlert[] }>('/api/war-room/today-alerts')
    return res.data
  },

  // 盘后：当日成交记录（交易复盘）
  async getTodayTrades() {
    const res = await ApiClient.get<{ total: number; items: TodayTrade[] }>('/api/war-room/today-trades')
    return res.data
  },

  // 当日计划
  async getPlans(date?: string, status?: string) {
    const res = await ApiClient.get<{ total: number; items: PlanItem[] }>('/api/plans', {
      date: date || undefined,
      status: status || undefined
    })
    return res.data
  },

  async createPlan(payload: Record<string, any>) {
    const res = await ApiClient.post<PlanItem>('/api/plans', payload)
    return res.data
  },

  async updatePlanStatus(planId: string, status: string, executedTradeId?: string) {
    const res = await ApiClient.patch<PlanItem>(`/api/plans/${planId}`, {
      status,
      executed_trade_id: executedTradeId
    })
    return res.data
  },

  // 信号跟踪
  async getSignals(status?: string, limit = 50) {
    const res = await ApiClient.get<{ total: number; items: SignalItem[] }>('/api/signal-tracking', {
      status: status || undefined,
      limit
    })
    return res.data
  },

  async getSignalStats() {
    const res = await ApiClient.get<any>('/api/signal-tracking/stats')
    return res.data
  },

  async triggerBackfill() {
    const res = await ApiClient.post<any>('/api/signal-tracking/backfill')
    return res.data
  },

  // 周度复盘
  async getWeeklyReview() {
    const res = await ApiClient.get<WeeklyReview | null>('/api/weekly-review/latest')
    return res.data
  },

  async generateWeeklyReview() {
    const res = await ApiClient.post<WeeklyReview | null>('/api/weekly-review/generate')
    return res.data
  }
}
