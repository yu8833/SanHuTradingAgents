import { ApiClient } from './request'

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
  type: string          // signal | price | market
  scope: string         // symbols | all
  symbols: string[]
  conditions: MonitorCondition[]
  logic: string         // and | or
  cooldown_seconds: number
  severity: string      // info | warn | critical
  message: string
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
}

export interface MonitorRulePayload {
  name: string
  enabled?: boolean
  type: string
  scope?: string
  symbols?: string[]
  conditions: MonitorCondition[]
  logic?: string
  cooldown_seconds?: number
  severity?: string
  message?: string
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
  async listAlerts(params?: { days?: number; limit?: number; source?: string }) {
    return ApiClient.get<{ alerts: MonitorAlert[]; total: number }>('/api/monitor/alerts', params)
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
}