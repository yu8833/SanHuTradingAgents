import { ApiClient } from './request'

// ---------------------------------------------------------------------------
// API 缓存（保证数据及时的前提下减少重复请求）
// ---------------------------------------------------------------------------

interface CacheEntry {
  data: any
  expire: number
}

const apiCache = new Map<string, CacheEntry>()
const MAX_CACHE_SIZE = 100

function getCacheKey(url: string, params?: Record<string, any>): string {
  if (!params) return url
  const sortedParams = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&')
  return `${url}?${sortedParams}`
}

async function cachedGet<T>(
  url: string,
  params?: Record<string, any>,
  ttl: number = 60000,
  config?: Record<string, any>
): Promise<T> {
  const key = getCacheKey(url, params)
  const hit = apiCache.get(key)
  
  if (hit && hit.expire > Date.now()) {
    return hit.data as T
  }
  
  const result = params
    ? await ApiClient.get<T>(url, params, config)
    : await ApiClient.get<T>(url, undefined, config)
  
  apiCache.set(key, { data: result, expire: Date.now() + ttl })
  
  if (apiCache.size > MAX_CACHE_SIZE) {
    const oldestKey = Array.from(apiCache.keys()).sort(
      (a, b) => apiCache.get(a)!.expire - apiCache.get(b)!.expire
    )[0]
    apiCache.delete(oldestKey)
  }
  
  return result
}

function clearCache(pattern?: string) {
  if (!pattern) {
    apiCache.clear()
    return
  }
  for (const key of apiCache.keys()) {
    if (key.includes(pattern)) {
      apiCache.delete(key)
    }
  }
}

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

export interface IndexQuote {
  name: string
  price: number
  change_pct: number
  change_amt: number
}

export interface GlobalIndex {
  key: string
  name: string
  region: string
  price: number | null
  change_pct: number | null
}

export interface GlobalStock {
  query: string
  name: string
  region: string
  price: number | null
  change_pct: number | null
}

export interface MarketSentiment {
  up: number
  down: number
  flat: number
  zt: number
  zt_real: number
  dt: number
  dt_real: number
  active: string
  breadth: string
  speculation: string
  date: string
}

export interface SectorFlow {
  name: string
  pct: number
  net: number
  inflow: number
  outflow: number
  firms: number
}

export interface MarketOverview {
  sentiment: MarketSentiment
  sectors: SectorFlow[]
  updated: string
}

// ---------------------------------------------------------------------------
// 市场看板（借鉴 tickflow Dashboard）
// ---------------------------------------------------------------------------

export interface RadarDim {
  key: string
  label: string
  value: number
}

export interface MarketRankItem {
  name: string
  pct: number
  count: number
  net: number
}

export interface MarketTopRow {
  code: string
  name: string
  close: number
  pct_chg: number
  amount: number
  turnover_rate: number
}

export interface DashboardLimit {
  limit_up: number
  limit_down: number
  seal_rate: number | null
  max_boards: number
  tiers: { boards: number; count: number; plus?: boolean }[]
}

export interface MarketDashboard {
  as_of: string
  indices: IndexQuote[]
  breadth: {
    total: number
    up: number
    down: number
    flat: number
    up_pct: number
    down_pct: number
    avg_pct: number
    median_pct: number
    strong_up: number
    strong_down: number
  }
  amount: { total: number; avg: number }
  distribution: { label: string; count: number; pct: number; dir: -1 | 0 | 1 }[]
  limit: DashboardLimit
  activity: { avg_turnover: number; high_turnover: number; high_turnover_pct: number }
  radar: RadarDim[]
  emotion: { score: number; label: string }
  top_gainers: MarketTopRow[]
  top_losers: MarketTopRow[]
  turnover_leaders: MarketTopRow[]
  active_leaders: MarketTopRow[]
  industry_rank: { leading: MarketRankItem[]; lagging: MarketRankItem[] }
  updated: string
}

export interface LianbanStock {
  code: string
  name: string
  boards: number
  price: number
  pct: number
  amount: number | null
  float_cap: number | null
  industry: string
}

export interface ShortTermEmotion {
  date: string
  zt_count: number
  dt_count: number
  zt_real: number
  dt_real: number
  zb_count: number
  max_boards: number
  lianban_count: number
  ladder: { boards: number; count: number; plus: boolean }[]
  lianban_stocks: LianbanStock[]
  seal_rate: number | null
  break_rate: number | null
  promotion_rate: number | null
  yzt_count: number
}

export interface TurnoverStock {
  code: string
  name: string
  price: number | null
  pct: number | null
  amount: number
  mcap: number
  industry: string
}

export interface TurnoverTop {
  stocks: TurnoverStock[]
  updated: string
}

export interface ConceptItem {
  code: string
  name: string
  pct_chg: number
  lead_code: string
  lead_name: string
  money_flow: number
  turnover: number
}

export interface ConceptAnalysis {
  total: number
  as_of: string
  breadth: { up: number; down: number; avg_pct: number }
  concepts: ConceptItem[]
  gainers: ConceptItem[]
  losers: ConceptItem[]
  money_leaders: ConceptItem[]
}

export interface ConceptRotationRow {
  code: string
  name: string
  pct_chg: number
  returns: Record<string, number | null>
}

export interface ConceptRotation {
  windows: number[]
  as_of: string
  rows: ConceptRotationRow[]
}

export interface StockQuote {
  code: string
  name: string
  price: number | null
  change_pct: number | null
  change_amt: number | null
  pe_ttm: number | null
  pb: number | null
  mcap_yi: number | null
  float_mcap_yi: number | null
  amount_wan: number | null
  turnover_pct: number | null
}

export interface RadarItem {
  title: string
  url: string
  time: string
  source: string
  summary?: string
  zh?: string
  ts?: number
}

export interface Industry {
  key: string
  name: string
  accent: string
  total: number
  items: RadarItem[]
}

export interface RadarData {
  generated_at: string | null
  recent_days: number
  industries: Industry[]
  stats: {
    industries: number
    total_sources: number
    failed_sources?: number
  }
}

export type BottleneckLevel = 'high' | 'mid' | 'low'

export interface SectorLink {
  name: string
  role: string
  focus: string
  bottleneck: BottleneckLevel
}

export interface SectorLayer {
  name: string
  desc: string
  nodes: SectorLink[]
}

export interface BottleneckDimension {
  dimension: string
  items: string[]
}

export interface SectorNode {
  key: string
  label: string
  tagline: string
  hot: boolean
  verified: boolean
  nodes: string[]
  // 扩展字段（仅 verified=true 的板块使用）
  summary?: string
  layers?: SectorLayer[]
  bottlenecks?: BottleneckDimension[]
}

export interface SectorsData {
  sectors: SectorNode[]
}

export interface Note {
  id: string
  kind: string
  title: string
  content: string
  ts: number
}

export interface Announcement {
  date: string
  title: string
  type: string
  url: string
}

export interface NewsItem {
  title: string
  url: string
  publish_time: string
  source: string
  content?: string
  symbol?: string
  stock_codes?: string[]
}

// ---------------------------------------------------------------------------
// 本地存储（研究记录）
// ---------------------------------------------------------------------------

const NOTES_KEY = 'vibe_research_notes'
const MAX_NOTES = 200

const WATCHLIST_KEY = 'vibe_watchlist'
const MAX_WATCHLIST = 20

// ---------------------------------------------------------------------------
// API 接口
// ---------------------------------------------------------------------------

export const vibeApi = {
  // 复盘模块
  async getIndices() {
    return cachedGet<IndexQuote[]>('/api/vibe/indices', undefined, 30000)
  },

  async getGlobalIndices() {
    return cachedGet<GlobalIndex[]>('/api/vibe/global-indices', undefined, 600000)
  },

  async getGlobalStocks() {
    return cachedGet<GlobalStock[]>('/api/vibe/global-stocks', undefined, 600000)
  },

  async getMarketOverview() {
    return cachedGet<MarketOverview>('/api/vibe/market/overview', undefined, 180000, { timeout: 15000 })
  },

  async getDashboard() {
    return cachedGet<MarketDashboard>('/api/vibe/market/dashboard', undefined, 180000, { timeout: 15000 })
  },

  async getEmotion() {
    return cachedGet<ShortTermEmotion>('/api/vibe/market/emotion', undefined, 180000, { timeout: 15000 })
  },

  async getTurnoverTop() {
    return cachedGet<TurnoverTop>('/api/vibe/market/turnover-top', undefined, 180000, { timeout: 15000 })
  },

  async getConceptAnalysis() {
    return cachedGet<ConceptAnalysis>('/api/vibe/market/concept-analysis', undefined, 180000, { timeout: 20000 })
  },

  async getConceptRotation(topN: number = 40) {
    return cachedGet<ConceptRotation>('/api/vibe/market/concept-rotation', { top_n: topN }, 3600000, { timeout: 120000 })
  },

  // 资讯模块
  async getRadar() {
    return cachedGet<RadarData>('/api/vibe/radar', undefined, 3600000)
  },

  async refreshRadar() {
    clearCache('/api/vibe/radar')
    return ApiClient.post<RadarData>('/api/vibe/radar/refresh')
  },

  async getAnnouncements(code: string, limit = 15) {
    return ApiClient.get<Announcement[]>(`/api/vibe/announcements?code=${code}&limit=${limit}`)
  },

  async getNews(code: string, limit = 20) {
    return ApiClient.get<NewsItem[]>(`/api/vibe/news?code=${code}&limit=${limit}`)
  },

  async getNewsBatch(codes: string[], limit = 10) {
    if (codes.length === 0) return { success: true, data: [] as (NewsItem & { stock_codes: string[] })[], message: '' }
    const key = getCacheKey('/api/vibe/news/batch', { codes: codes.join(','), limit })
    const cached = apiCache.get(key)
    let since = ''
    if (cached && cached.data?.data?.length > 0) {
      const items = cached.data.data as (NewsItem & { stock_codes: string[] })[]
      since = items[0]?.publish_time || ''
    }
    const result = since
      ? await ApiClient.get<(NewsItem & { stock_codes: string[] })[]>(
          `/api/vibe/news/batch?codes=${codes.join(',')}&limit=${limit}&since=${encodeURIComponent(since)}`
        )
      : await ApiClient.get<(NewsItem & { stock_codes: string[] })[]>(
          `/api/vibe/news/batch?codes=${codes.join(',')}&limit=${limit}`
        )
    if (cached && result.data && result.data.length > 0) {
      const existing = cached.data.data as (NewsItem & { stock_codes: string[] })[]
      const merged = [...result.data, ...existing]
      const seen = new Map<string, NewsItem & { stock_codes: string[] }>()
      for (const item of merged) {
        const title = item.title
        if (!seen.has(title)) {
          seen.set(title, item)
        }
      }
      const deduped = Array.from(seen.values())
      deduped.sort((a, b) => (b.publish_time || '').localeCompare(a.publish_time || ''))
      cached.data.data = deduped
      cached.expire = Date.now() + 300000
      return cached.data
    }
    apiCache.set(key, { data: result, expire: Date.now() + 300000 })
    return result
  },

  async getAnnouncementsBatch(codes: string[], limit = 10) {
    if (codes.length === 0) return { success: true, data: [] as (Announcement & { stock_code: string })[], message: '' }
    return cachedGet<(Announcement & { stock_code: string })[]>(
      '/api/vibe/announcements/batch',
      { codes: codes.join(','), limit },
      300000
    )
  },

  // 板块模块
  async getSectors() {
    return cachedGet<SectorsData>('/api/vibe/sectors', undefined, 3600000)
  },

  // 批量行情
  async getQuotes(codes: string[]) {
    if (codes.length === 0) return { success: true, data: [] as StockQuote[], message: '' }
    return cachedGet<StockQuote[]>(
      '/api/vibe/quotes',
      { codes: codes.join(',') },
      30000
    )
  },

  // AI 对话（流式 NDJSON）
  async chatStream(
    messages: { role: string; content: string }[],
    context: string,
    onDelta: (text: string) => void,
    onError?: (msg: string) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const authStore = (await import('@/stores/auth')).useAuthStore()
    const token = authStore.token || localStorage.getItem('auth-token') || ''
    const controller = new AbortController()
    const combinedSignal = signal || controller.signal

    try {
      console.log('[chatStream] sending request, token exists:', !!token)
      const resp = await fetch('/api/vibe/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ messages, context }),
        signal: combinedSignal,
      })

      console.log('[chatStream] response status:', resp.status, resp.ok)
      if (!resp.ok) {
        const errText = await resp.text()
        console.error('[chatStream] error response:', errText.substring(0, 200))
        throw new Error(`请求失败: ${resp.status}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) {
        console.error('[chatStream] resp.body is null, cannot read stream')
        throw new Error('无法读取流式响应')
      }
      const decoder = new TextDecoder()
      let buf = ''
      let deltaCount = 0

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const ev = JSON.parse(trimmed)
            if (ev.type === 'delta') {
              onDelta(ev.text)
              deltaCount++
            }
            else if (ev.type === 'error' && onError) onError(ev.message)
            else if (ev.type === 'done') console.log('[chatStream] stream done event')
          } catch {
            // ignore parse errors
          }
        }
      }
      console.log('[chatStream] reading complete, total deltas:', deltaCount)
    } catch (e: any) {
      console.error('[chatStream] caught error:', e?.message || e)
      throw e
    } finally {
      controller.abort()
    }
  },

  // 研究记录（后端 MongoDB 存储，跨设备同步）
  async loadNotes(): Promise<Note[]> {
    try {
      const list = await ApiClient.get<Note[]>('/api/vibe/notes')
      return Array.isArray(list) ? list : []
    } catch (e) {
      console.error('[loadNotes] 加载失败，回退到本地缓存:', e)
      try {
        const data = localStorage.getItem(NOTES_KEY)
        return data ? JSON.parse(data) : []
      } catch {
        return []
      }
    }
  },

  async saveNote(
    kind: string,
    title: string,
    content: string,
    meta?: { related_code?: string; related_strategy?: string; related_trade_id?: string }
  ): Promise<Note | null> {
    try {
      const note = await ApiClient.post<Note>('/api/vibe/notes', {
        kind, title, content,
        related_code: meta?.related_code,
        related_strategy: meta?.related_strategy,
        related_trade_id: meta?.related_trade_id,
      })
      return note || null
    } catch (e) {
      console.error('[saveNote] 后端保存失败，回退到本地缓存:', e)
      // 回退到 localStorage
      const notes = this.loadNotesSync()
      const newNote: Note = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        kind, title, content, ts: Date.now(),
      }
      const next = [newNote, ...notes].slice(0, MAX_NOTES)
      localStorage.setItem(NOTES_KEY, JSON.stringify(next))
      return newNote
    }
  },

  async deleteNote(id: string): Promise<boolean> {
    try {
      await ApiClient.delete<{ success: boolean }>(`/api/vibe/notes/${id}`)
      return true
    } catch (e) {
      console.error('[deleteNote] 后端删除失败，回退到本地缓存:', e)
      const notes = this.loadNotesSync().filter(n => n.id !== id)
      localStorage.setItem(NOTES_KEY, JSON.stringify(notes))
      return true
    }
  },

  async clearNotes(): Promise<boolean> {
    try {
      await ApiClient.delete<{ success: boolean }>('/api/vibe/notes')
      return true
    } catch (e) {
      console.error('[clearNotes] 后端清空失败，回退到本地缓存:', e)
      localStorage.removeItem(NOTES_KEY)
      return true
    }
  },

  // 同步本地加载（仅作后端不可用时的回退）
  loadNotesSync(): Note[] {
    try {
      const data = localStorage.getItem(NOTES_KEY)
      return data ? JSON.parse(data) : []
    } catch {
      return []
    }
  },

  // 关注股票（localStorage）
  loadWatchlist(): string[] {
    try {
      const data = localStorage.getItem(WATCHLIST_KEY)
      return data ? JSON.parse(data) : []
    } catch {
      return []
    }
  },

  addWatchlist(code: string): string[] {
    const list = this.loadWatchlist()
    const c = code.trim()
    if (!c || list.includes(c)) return list
    const next = [c, ...list].slice(0, MAX_WATCHLIST)
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next))
    return next
  },

  removeWatchlist(code: string): string[] {
    const list = this.loadWatchlist().filter(c => c !== code)
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list))
    return list
  },
}
