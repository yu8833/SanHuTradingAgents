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
    // 待确认计划数（confirmed=false；缺省视为已确认，与 list_plans 序列化口径一致）
    plan_pending: number
    plan_total: number
    todo: number
  }
  intraday: {
    holding_count: number
    alert_count: number
    pending_orders: number
    // 已确认待执行的买入计划数（动作 = 盘中「去交易」）
    plan_confirmed_pending: number
    todo: number
  }
  post_market: {
    signal_pending: number
    signal_total: number
    todo: number
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
  basis?: {
    status: '偏多' | '偏空' | '中性(观望)' | '数据不足'
    direction: string
    confidence: number
    low_confidence: boolean
    confidence_threshold: number
    locked_at?: string
    score: number
  }
  llm_interpretation?: {
    keywords?: string[]
    event_impact?: string
    style_tendency?: string
    risk_tips?: string
  } | null
  llm_available?: boolean
  created_at?: string
}

export interface PlanSource { type: string; ref?: string; label?: string }

export interface PlanItem {
  id: string
  code: string
  name?: string
  direction: 'buy' | 'sell'
  trigger_price?: number | null
  stop_loss?: number | null
  sell_condition?: string | null
  status: 'pending' | 'executed' | 'cancelled'
  // 三态确认：False=待确认 / True=已确认（已确认才进入盘中执行提醒）
  confirmed?: boolean
  position?: Record<string, any> | null
  source?: PlanSource | null
}

export interface PlanCandidate {
  code: string
  name?: string
  direction: 'buy' | 'sell'
  trigger_price?: number | null
  stop_loss?: number | null
  sell_condition?: string | null
  position?: Record<string, any> | null
  source?: PlanSource | null
  signal_label?: string
  industry?: string
  quality_score?: number | null
}

export interface PlanAuditStep {
  step: string
  scanned: number
  rule: string
  kept: number
  dropped: number
  reasons: string[]
  meta?: Record<string, any>
}

export interface PlanIndustryForecast {
  industry: string
  forecast_score?: number
  confidence?: number
  factors?: Record<string, any>
}

export interface PlanGenerateResult {
  direction?: string
  basis?: MacroSnapshot['basis']
  industries?: PlanIndustryForecast[]
  candidates?: PlanCandidate[]
  candidates_count?: number
  // 当日卖出观测（持仓卖出评估：清仓/减仓/止损/止盈 → 人工确认写入当日计划）
  sell_candidates?: SellCandidate[]
  sell_count?: number
  // 快照按用户过滤后，被「当日计划去重」剔除的候选数量（>0 表示已自动生成但候选已全部确认/过滤）
  filtered_count?: number
  audit?: { steps: PlanAuditStep[]; total: number }
  generated_at?: string
}

export interface SellCandidate {
  code: string
  name?: string
  direction: 'sell'
  trigger_price?: number | null
  last_price?: number | null
  profit_loss_rate?: number | null
  stop_loss_price?: number | null
  take_profit_price?: number | null
  sell_pct?: number | null
  sell_condition?: string | null
  signal_label?: string
  reason?: string | null
  holding?: boolean
  source?: PlanSource | null
}

export interface BuyGuideItem {
  code: string
  name?: string
  direction: 'buy'
  trigger_price?: number | null
  last_price?: number | null
  distance_pct?: number | null
  triggered?: boolean
  signal_label?: string
  source?: PlanSource | null
  plan_id?: string | null
  advice?: string
}

export interface SellGuideItem {
  code: string
  name?: string
  quantity?: number
  avg_cost?: number | null
  last_price?: number | null
  profit_loss_rate?: number | null
  stop_loss_price?: number | null
  take_profit_price?: number | null
  advice?: string
  advice_label?: string
  sell_pct?: number
  trigger_price?: number | null
  reason?: string | null
  advice_text?: string
  holding?: boolean
}

export interface IntradayGuide {
  as_of?: string
  buys?: BuyGuideItem[]
  sells?: SellGuideItem[]
  buy_count?: number
  sell_count?: number
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

  // 盘中：买卖点实时指导（买入触达 + 持仓卖出建议）
  async getIntradayGuide() {
    const res = await ApiClient.get<IntradayGuide>('/api/war-room/intraday-guide', undefined, { timeout: 30000 })
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

  // 5.4 人工可改：改价/改止损/改卖出条件（触发价变更后自动重算仓位）
  async updatePlanDetail(planId: string, fields: Record<string, any>) {
    const res = await ApiClient.put<PlanItem>(`/api/plans/${planId}`, fields)
    return res.data
  },

  // 5.4 人工删除（仅允许删除未执行的计划）
  async deletePlan(planId: string) {
    const res = await ApiClient.delete<{ deleted: boolean }>(`/api/plans/${planId}`)
    return res.data
  },

  // 5.3 今日计划快照（盘前 8:15 预生成落库，打开即读、秒回）
  async getTodayPlan() {
    const res = await ApiClient.get<{
      generated: boolean
      date?: string
      result?: PlanGenerateResult | null
    }>('/api/war-room/daily-plan/today', undefined, { timeout: 15000 })
    return res.data
  },

  // 5.3 启动当日计划生成任务：立即返回 job_id，不再同步等待
  // 进度经 /api/war-room/daily-plan/stream/{job_id} SSE 实时接收四段审计；
  // 完成后经 /api/war-room/daily-plan/result/{job_id} 取回候选。
  async generateDailyPlan() {
    const res = await ApiClient.post<{ job_id?: string; status: string; progress?: number; stage?: string }>(
      '/api/war-room/daily-plan/generate', undefined, { timeout: 60000 }
    )
    return res.data
  },

  async getPlanJobStatus(jobId: string) {
    const res = await ApiClient.get<{ job_id?: string; status: string; progress?: number; stage?: string }>(
      `/api/war-room/daily-plan/status/${jobId}`
    )
    return res.data
  },

  async getPlanJobResult(jobId: string) {
    const res = await ApiClient.get<PlanGenerateResult | null>(
      `/api/war-room/daily-plan/result/${jobId}`, { timeout: 60000 }
    )
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
