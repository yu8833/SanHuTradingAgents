import { ApiClient } from './request'

export type AlertType = 'price_above' | 'price_below' | 'pct_up' | 'pct_down'

export interface AlertRule {
  id: string
  user_id: string
  code: string
  stock_name: string
  alert_type: AlertType
  threshold: number
  note?: string | null
  enabled: boolean
  triggered: boolean
  triggered_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface CreateAlertPayload {
  code: string
  stock_name?: string
  alert_type: AlertType
  threshold: number
  note?: string
}

export interface UpdateAlertPayload {
  threshold?: number
  note?: string
  enabled?: boolean
  triggered?: boolean
}

export const stockAlertApi = {
  async getAlerts(code?: string) {
    const url = code ? `/api/stock/alerts?code=${code}` : '/api/stock/alerts'
    return ApiClient.get<AlertRule[]>(url)
  },

  async createAlert(data: CreateAlertPayload) {
    return ApiClient.post<AlertRule>('/api/stock/alerts', data)
  },

  async updateAlert(alertId: string, data: UpdateAlertPayload) {
    return ApiClient.put<AlertRule>(`/api/stock/alerts/${alertId}`, data)
  },

  async deleteAlert(alertId: string) {
    return ApiClient.delete<{ alert_id: string }>(`/api/stock/alerts/${alertId}`)
  },
}
