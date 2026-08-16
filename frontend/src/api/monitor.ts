import { ApiClient, type RequestConfig } from './request'

// ── 类型定义 ────────────────────────────────────────────

export interface MonitorCondition {
  field: string
  op: string            // truth | > >= < <= == !=
  value?: number | null
}

export interface MonitorRule {
  id: string
  name: string
  enabled: boolean
  type: string          // signal | price | market | aux | tbs
  scope: string         // symbols | watchlist | all | positions
  symbols: string[]
  user_id?: string
  conditions: MonitorCondition[]
  logic: string         // and | or
  cooldown_seconds: number
  severity: string      // info | warn | critical
  message: string
  tbs_dir?: string      // type=tbs 时：buy | sell | both
  tbs_signals?: string[] // type=tbs 时：限定监听的信号（B1/B2/B3/S1/S2/S3）
  builtin?: boolean     // 内置规则（三买三卖核心，不可删除）
  created_at?: string
}

export interface MonitorAlert {
  ts: number
  rule_id: string
  rule_name: string
  source: string
  rule_type: string
  symbol: string
  name: string
  message: string
  price: number
  change_pct: number
  signals: string[]
  severity: string
  conditions: MonitorCondition[]
  logic: string
}

export interface MonitorOptions {
  threshold_fields: { key: string; label: string }[]
  signal_fields: { key: string; label: string }[]
  operators: string[]
  types: { key: string; label: string }[]
  scopes: { key: string; label: string }[]
  logics: { key: string; label: string }[]
  severities: { key: string; label: string }[]
  tbs_dirs?: { key: string; label: string }[]
  tbs_signals?: { key: string; label: string }[]
  aux_fields?: { key: string; label: string }[]
}

export interface MonitorRulePayload {
  name: string
  enabled?: boolean
  type: string
  scope?: string
  symbols?: string[]
  user_id?: string
  conditions: MonitorCondition[]
  logic?: string
  cooldown_seconds?: number
  severity?: string
  message?: string
  tbs_dir?: string
  tbs_signals?: string[]
  strategy_id?: string
  tag?: string
}

export interface StrategyMonitorStatus {
  strategy_id: string
  rule_id: string
  name: string
  enabled: boolean
}

export interface TbsOrder {
  id: string
  rule_id: string
  rule_name: string
  symbol: string
  name: string
  signal_type: string
  signal_label: string
  direction: string       // buy | sell
  position_pct: number
  reference_price: number
  status: string          // pending | executed | cancelled | dismissed
  created_at: string
  executed_at?: string
  executed_qty?: number
  executed_price?: number
  reason?: string
}

// 生成规则 id（小写字母数字下划线，1-40字符）
export const genRuleId = (): string =>
  `rule_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

export const monitorApi = {
  // 字段/枚举选项
  async getOptions() {
    return ApiClient.get<MonitorOptions>('/api/monitor/options')
  },

  // 规则 CRUD
  async listRules() {
    return ApiClient.get<{ rules: MonitorRule[] }>('/api/monitor/rules')
  },
  async saveRule(rule: MonitorRulePayload) {
    return ApiClient.post<{ rule: MonitorRule }>('/api/monitor/rules', rule)
  },
  async deleteRule(ruleId: string) {
    return ApiClient.delete<{ rule_id: string }>(`/api/monitor/rules/${ruleId}`)
  },

  // 触发记录
  async listAlerts(params?: { days?: number; limit?: number; source?: string }, config?: RequestConfig) {
    return ApiClient.get<{ alerts: MonitorAlert[]; total: number }>('/api/monitor/alerts', params, config)
  },
  async clearAlerts() {
    return ApiClient.delete<{ cleared: number }>('/api/monitor/alerts')
  },
  async deleteAlert(alertId: string) {
    return ApiClient.delete<{ alert_id: string }>(`/api/monitor/alerts/${alertId}`)
  },

  // 手动触发评估
  async manualCheck() {
    return ApiClient.post<{ triggered: number }>('/api/monitor/check')
  },

  // 三买三卖待确认指令
  async listTbsOrders(params?: { status?: string; limit?: number }) {
    return ApiClient.get<{ orders: TbsOrder[] }>('/api/monitor/tbs/orders', params)
  },
  async executeTbsOrder(orderId: string, quantity?: number) {
    return ApiClient.post<{ order: Record<string, unknown> }>(
      `/api/monitor/tbs/orders/${orderId}/execute`,
      quantity ? { quantity } : undefined
    )
  },
  async cancelTbsOrder(orderId: string) {
    return ApiClient.post<{ order_id: string }>(`/api/monitor/tbs/orders/${orderId}/cancel`)
  },
  async dismissTbsOrder(orderId: string) {
    return ApiClient.post<{ order_id: string }>(`/api/monitor/tbs/orders/${orderId}/dismiss`)
  },

  // 常用策略监控（type=strategy）
  async strategyMonitorStatus() {
    return ApiClient.get<{ items: StrategyMonitorStatus[] }>('/api/monitor/strategies/status')
  },
  async toggleStrategyMonitor(strategyId: string, enabled: boolean, name?: string) {
    return ApiClient.post<{ rule: MonitorRule }>(`/api/monitor/strategies/${strategyId}/monitor`, { enabled, name })
  },
}