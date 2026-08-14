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
  // ΔG 五因子（来自 dg_prosperity，百分数口径）
  or_yoy?: number | null   // 收入增速（营收YOY）
  g?: number | null        // 盈利增速
  d_or_yoy?: number | null
  d_roe?: number | null
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

  /** Tab2：某行业候选个股（top30，ΔG过滤+择时预览，仅保留三买三卖信号） */
  stocks: (industry: string, limit = 30) =>
    ApiClient.get<CandidateStockList>(
      '/api/candidate/stocks', { industry, limit }),

  /** Tab2 默认视图：未选行业时，前 top_n 行业每行业 top per_industry 只三买三卖信号个股 */
  stocksOverview: (topN = 10, perIndustry = 3, industries: string[] = []) =>
    ApiClient.get<CandidateStockList>(
      '/api/candidate/stocks-overview',
      { top_n: topN, per_industry: perIndustry, industries: industries.join(',') }),

  /** 批量加入自选 */
  async batchAddFavorites(items: Array<{ code: string; name: string }>) {
    const res = await ApiClient.post<{ added: number; failed: number; total: number }>(
      '/api/candidate/favorites/batch', { items })
    return res
  },

  /** 单只加入自选（复用 favorites api） */
  addFavorite(code: string, name: string) {
    return favoritesApi.add({ symbol: code, stock_name: name, market: 'A股' })
  },

  /** 行业筛选：行业 ETF 主力净流入资金流排名（资金为王，动量/量能仅展示） */
  industryScreening: (top_n = 10, refresh = false) =>
    ApiClient.get<IndustryScreeningSummary>('/api/candidate/industry-screening', { top_n, refresh })
}

export interface IndustryScreeningItem {
  industry: string
  etf_code: string
  etf_name: string
  close?: number | null
  pct_chg?: number | null
  fund_net_inflow?: number | null        // 元
  fund_net_inflow_pct?: number | null    // %
  super_large_inflow?: number | null
  large_inflow?: number | null
  medium_inflow?: number | null
  small_inflow?: number | null
  volume_ratio?: number | null
  turnover_rate?: number | null
  fund_flow_score: number
  composite_score: number
  sector_net_inflow?: number | null   // 亿元（同花顺行业资金流交叉核验）
  sector_pct_chg?: number | null
  sector_dg?: SectorDg | null         // 本地行业 ΔG 景气（best-effort 融合）
}

export interface IndustryScreeningSummary {
  success: boolean
  message?: string
  as_of: string
  updated_at: string
  industry_count: number
  top: IndustryScreeningItem[]
  rankings: IndustryScreeningItem[]
  industry_flows: Array<{ industry: string; net_inflow?: number | null; pct_chg?: number | null }>
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