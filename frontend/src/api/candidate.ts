import { ApiClient } from './request'
import { favoritesApi } from './favorites'

// ==================== 候选池 ====================

export interface SectorDg {
  industry?: string
  quadrant?: string
  quadrant_label?: string
  quadrant_color?: string
  avg_g?: number | null
  avg_dg?: number | null
  member_count?: number
  data_count?: number
  distribution?: Record<string, number>
  report_period?: string
  available?: boolean
}

export interface IndustryItem {
  industry: string
  sector_score: number
  member_count: number
  top_members: Array<{
    code: string
    name: string
    close?: number | null
    pct_chg?: number | null
    momentum_20d?: number | null
  }>
  sector_dg?: SectorDg
}

export interface IndustryMember {
  code: string
  name: string
  close?: number | null
  pct_chg?: number | null
  momentum_20d?: number | null
  total_mv?: number | null
  pe_ttm?: number | null
  revenue_yoy?: number | null
}

export interface CandidateStock {
  code: string
  name: string
  industry: string
  close?: number | null
  pct_chg?: number | null
  quality_score: number
  roe?: number | null
  revenue_yoy?: number | null
  net_profit_yoy?: number | null
  pe_ttm?: number | null
  pb?: number | null
  total_mv?: number | null
  momentum_20d?: number | null
  volume_ratio_5d?: number | null
  date: string
  // 择时预览
  dg_quadrant?: string
  dg_available?: boolean
  dg_g?: number | null
  dg_dg?: number | null
  signal_type?: string
  signal_label?: string
  signal_score?: number
  market_trend?: string
  // 辅助信号系统（教材第三章）
  aux_score?: number
  aux_warnings?: string[]
  auxiliary?: Record<string, {
    triggered?: boolean
    level?: 'confirm' | 'warn' | 'neutral'
    label?: string
    detail?: string
  }>
}

export const candidateApi = {
  /** Tab1：强势行业列表 */
  industries: (top_n = 20) =>
    ApiClient.get<{ as_of: string; industries: IndustryItem[] }>('/api/candidate/industries', { top_n }),

  /** Tab1：某行业成分股 */
  members: (industry: string) =>
    ApiClient.get<{ as_of: string; industry: string; sector_score: number | null; member_count: number; items: IndustryMember[] }>(
      '/api/candidate/members', { industry }),

  /** Tab2：某行业候选个股（top30，ΔG过滤+择时预览） */
  stocks: (industry: string, limit = 30) =>
    ApiClient.get<{ as_of: string; industry: string; total: number; items: CandidateStock[] }>(
      '/api/candidate/stocks', { industry, limit }),

  /** 批量加入自选 */
  async batchAddFavorites(items: Array<{ code: string; name: string }>) {
    const res = await ApiClient.post<{ added: number; failed: number; total: number }>(
      '/api/candidate/favorites/batch', { items })
    return res
  },

  /** 单只加入自选（复用 favorites api） */
  addFavorite(code: string, name: string) {
    return favoritesApi.add({ symbol: code, stock_name: name, market: 'A股' })
  }
}

export interface CandidateStockList {
  as_of: string
  industry: string
  sector_dg?: SectorDg
  total: number
  items: CandidateStock[]
}

export interface CandidateIndustries {
  as_of: string
  industries: IndustryItem[]
}