import { ApiClient } from './request'

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

export type GateLevel = 'green' | 'yellow' | 'red'
export type PoolStatus = 'watching' | 'near' | 'triggered' | 'expired'
export type ExitState = 'exit' | 'warn' | 'normal' | 'closed'

export interface EmotionPhase {
  label: string | null
  reason?: string
}

export interface GateData {
  gate: GateLevel
  label: string
  hint: string
  position_hint: string
  degraded: boolean
  degrade_note?: string
  portrait: string | null
  advice: Record<string, any>
  dims: Record<string, any>
  reasons: string[]
  metrics: Record<string, any>
  emotion_phase: EmotionPhase
  emotion: {
    zt?: number
    dt?: number
    zb?: number
    max_boards?: number
    seal_rate?: number | null
    lianban?: number | null
  }
  data_quality: string
  missing: string[]
  as_of_portrait: string | null
  as_of_emotion: string | null
}

export interface MainlineRow {
  name: string
  pct_3d: number
  net_3d: number
  streak: number
  pool_count: number
}

export interface PeriodRow {
  name: string
  pct: number
  net: number
  inflow?: number
  outflow?: number
  firms?: number
}

export interface MainlineData {
  mainlines: MainlineRow[]
  periods: Record<string, PeriodRow[]>
  as_of: string | null
  updated_at: string | null
  source: string
}

export interface PoolItem {
  code: string
  name: string
  industry: string
  status: PoolStatus
  close: number
  ma5: number
  trigger_price: number
  trigger_basis: string
  distance_to_trigger: number
  range_low: number
  sideways_days: number
  volatility_pctile: number
  converge_ratio: number
  avg_amount_20d: number
  avg_amount_5d: number
  current_price?: number
  first_seen_date?: string
  last_scan_date?: string
  last_price?: number
  triggered_at?: string
  trigger_vol_ratio?: number
  /** B2 突破确认时落库的指标（仅曾触发的标的才有） */
  b2_trigger_price?: number
  b2_volume_ratio?: number
  b2_ma55?: number
  b2_ma60?: number
  last_triggered_date?: string
}

export interface PoolData {
  items: PoolItem[]
  total: number
  scanned_at: string
  quote_as_of: string | null
  trading_session: boolean
  params: Record<string, any>
  params_version: string
  params_note: string
}

export interface SignalsData {
  triggered: PoolItem[]
  near: PoolItem[]
  watching_count: number
  last_check_at: string | null
  trading_session: boolean
  quote_as_of: string | null
  pool_since: string | null
  scan_note: string
}

export interface PositionItem {
  id: string
  code: string
  name: string
  industry: string
  buy_price: number
  buy_date: string
  sell_price?: number | null
  sell_date?: string | null
  status: 'open' | 'closed'
  current_price?: number | null
  state: ExitState
  reasons: string[]
  pnl_pct: number | null
  holding_days: number
  t1_locked: boolean
  stop_loss_line: number | null
  trailing_line: number | null
}

export interface PositionsData {
  items: PositionItem[]
  evaluated_at: string
  trade_date: string
  is_intraday: boolean
}

// ---------------------------------------------------------------------------
// 请求封装：统一拆包 {success, data, message}
// ---------------------------------------------------------------------------

async function getData<T>(url: string, params?: Record<string, any>, timeout = 30000): Promise<T> {
  const res = await ApiClient.get<T>(url, params, { timeout })
  const body = res as any
  if (body && body.success === false) {
    throw new Error(body.message || '请求失败')
  }
  return (body?.data ?? body) as T
}

export const cockpitApi = {
  /** 区块 01：环境闸门 */
  getGate: () => getData<GateData>('/api/cockpit/gate', undefined, 45000),

  /** 区块 02：主线方向 */
  getMainline: () => getData<MainlineData>('/api/cockpit/mainline', undefined, 45000),

  /** 区块 03：积累区观察池 */
  getPool: (params?: { status?: string; industry?: string }) =>
    getData<PoolData>('/api/cockpit/pool', params, 45000),

  /** 区块 04：突破触发信号 */
  getSignals: () => getData<SignalsData>('/api/cockpit/signals', undefined, 45000),

  /** 区块 05：纪律持仓 */
  getPositions: () => getData<PositionsData>('/api/cockpit/positions', undefined, 45000),

  /** 标记买入 */
  async createPosition(code: string, buyPrice: number, buyDate?: string): Promise<any> {
    const res: any = await ApiClient.post('/api/cockpit/positions', {
      code,
      buy_price: buyPrice,
      buy_date: buyDate
    })
    if (res?.success === false) throw new Error(res.message || '标记买入失败')
    return res?.data
  },

  /** 卖出/了结 */
  async closePosition(id: string, sellPrice: number): Promise<any> {
    const res: any = await ApiClient.post(`/api/cockpit/positions/${id}/close`, {
      sell_price: sellPrice
    })
    if (res?.success === false) throw new Error(res.message || '了结失败')
    return res?.data
  },

  /** 手动重扫观察池（全市场，可能耗时 1~3 分钟） */
  async rescanPool(): Promise<any> {
    const res: any = await ApiClient.post('/api/cockpit/pool/rescan', undefined, { timeout: 300000 })
    if (res?.success === false) throw new Error(res.message || '重扫失败')
    return res?.data
  }
}
