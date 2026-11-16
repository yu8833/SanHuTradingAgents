import { ApiClient } from './request'

export interface ReasonItem {
  kind: string
  text: string
}

export interface TodayGate {
  gate: 'green' | 'yellow' | 'red' | null
  label: string | null
  hint: string | null
  position_hint: string | null
  portrait: string | null
  emotion_phase: { label?: string | null; tone?: string; desc?: string } | null
  degraded?: boolean
}

export interface TodayBuyItem {
  code: string
  name: string
  industry: string
  signal_label: string
  trigger_date: string | null
  score?: number
  bias60?: number | null
  current_price: number | null
  price_source: 'live' | 'close' | 'signal' | 'none'
  trigger_price: number | null
  stop_loss_price: number | null
  take_profit_price: number | null
  position_pct: number
  suggest_qty: number
  suggest_amount: number
  risk_amount?: number
  held: boolean
  blocked: boolean
  block_reason: string
  action: string
  summary: string
  reasons: ReasonItem[]
}

export interface TodayWatchItem {
  code: string
  name: string
  industry: string
  status: string
  stale?: boolean
  current_price: number
  trigger_price: number
  distance_to_trigger: number
  to_trigger_pct: number
  action: string
  summary: string
  reasons: ReasonItem[]
}

export interface TodaySellItem {
  code: string
  name: string
  source: 'paper' | 'cockpit'
  position_id: string | null
  state: 'exit' | 'warn' | 'normal'
  quantity: number | null
  avg_cost: number | null
  current_price: number | null
  pnl_pct: number | null
  advice: string
  advice_label: string
  sell_pct: number
  reference_price: number | null
  stop_loss_price: number | null
  reasons: ReasonItem[]
  summary: string
}

export interface TodayEnvLayer {
  value: string
  tone: 'up' | 'down' | 'flat' | 'warn'
  desc: string
  points: string[]
}

export interface TodayEnvAction {
  side: '买' | '盯' | '卖'
  tone: string
  title: string
  text: string
}

export interface TodayEnvironment {
  gate: 'green' | 'yellow' | 'red'
  verdict: string
  headline: string
  portrait: TodayEnvLayer
  phase: TodayEnvLayer
  position: TodayEnvLayer
  actions: TodayEnvAction[]
  footnote: string
  degraded: boolean
  degrade_note: string
}

export interface TodayDirection {
  status: 'ok' | 'unavailable'
  usable: boolean
  attack_industries: string[]
  avoid_industries: string[]
  as_of: string | null
  direction: string | null
  conclusion: string
  note: string
}

export interface TodayMeta {
  rule_version: string
  snapshot_hash: string
  as_of: string
  trade_date: string
  rule_engine: string
  data_quality: string[]
}

export interface TodayActions {
  as_of: string
  trade_date: string
  session: { is_intraday: boolean; quote_as_of: string | null; price_source?: string }
  gate: TodayGate
  mainlines: Array<{ name: string; streak: number; net_3d: number; pct_3d: number }>
  environment: TodayEnvironment
  account: { cash_cny: number; equity: number }
  direction: TodayDirection
  buy: {
    count: number
    actionable_count: number
    items: TodayBuyItem[]
    filtered: { avoid: number; not_attack: number }
  }
  watch: { count: number; near_count: number; items: TodayWatchItem[] }
  sell: {
    count: number
    exit_count: number
    warn_count: number
    hold_count: number
    items: TodaySellItem[]
  }
  meta: TodayMeta
}

async function getData<T>(url: string, params?: Record<string, any>, timeout = 60000): Promise<T> {
  const res = await ApiClient.get<T>(url, params, { timeout })
  const body = res as any
  if (body && body.success === false) {
    throw new Error(body.message || '请求失败')
  }
  return (body?.data ?? body) as T
}

export const todayApi = {
  getActions: () => getData<TodayActions>('/api/today/actions')
}
