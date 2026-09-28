<template>
  <div class="vibe-overview app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 大盘看板</h2>
          <p class="page-hero-sub">大盘指数 / 市场情绪 / 涨跌分布一屏看全</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">更新于 {{ updatedAt }}</span>
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
          刷新
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="overview-tabs">
      <!-- ============ A股市场 ============ -->
      <el-tab-pane label="A股市场" name="ashare">
    <!-- 大盘指数 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataLine /></el-icon> 大盘指数</span>
        <span v-if="loading" class="block-hint">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中
        </span>
      </div>
      <div class="grid grid-4">
        <el-card
          v-for="item in indices"
          :key="item.name"
          shadow="never"
          class="idx-card"
        >
          <div class="idx-name">{{ item.name }}</div>
          <div class="idx-price">{{ fmtPrice(item.price) }}</div>
          <div class="idx-change" :class="colorClass(item.change_pct)">
            <span class="pct">{{ fmtPct(item.change_pct) }}</span>
            <span class="amt">{{ fmtSigned(item.change_amt) }}</span>
          </div>
        </el-card>
        <el-card v-if="!indices.length && !loading" shadow="never" class="idx-card empty-card">
          <el-empty :image-size="48" description="暂无指数数据" />
        </el-card>
      </div>
    </section>

    <!-- 情绪评分 + KPI + 涨跌分布 + 雷达 -->
    <section v-if="dashboard" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Odometer /></el-icon> 市场情绪与涨跌分布</span>
        <span class="score-badge" :style="scoreStyle">{{ dashboard.emotion.label }} · {{ dashboard.emotion.score }}</span>
      </div>

      <!-- KPI 指标行 -->
      <div class="kpi-row">
        <div class="kpi-cell">
          <div class="kpi-label">个股涨 / 平 / 跌</div>
          <div class="kpi-value">
            <span class="up">{{ dashboard.breadth.up }}</span><span class="kpi-sep">/</span><span class="kpi-mid">{{ dashboard.breadth.flat }}</span><span class="kpi-sep">/</span><span class="down">{{ dashboard.breadth.down }}</span>
          </div>
          <div class="kpi-sub">上涨率 {{ dashboard.breadth.up_pct }}%</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">强势 / 弱势</div>
          <div class="kpi-value">
            <span class="up">{{ dashboard.breadth.strong_up }}</span><span class="kpi-sep">/</span><span class="down">{{ dashboard.breadth.strong_down }}</span>
          </div>
          <div class="kpi-sub">涨跌 ≥3%</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">成交额</div>
          <div class="kpi-value accent">{{ fmtAmount(dashboard.amount.total) }}</div>
          <div class="kpi-sub">均额 {{ fmtAmount(dashboard.amount.avg) }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">换手</div>
          <div class="kpi-value accent">{{ dashboard.activity.avg_turnover }}%</div>
          <div class="kpi-sub">高换手 {{ dashboard.activity.high_turnover }} · 占 {{ dashboard.activity.high_turnover_pct }}%</div>
        </div>
      </div>

      <!-- 雷达 + 涨跌分布 -->
      <div class="dash-main">
        <el-card shadow="never" class="dash-card">
          <div class="card-title">情绪雷达</div>
          <div v-if="dashboard.radar.length" class="radar-wrap">
            <svg viewBox="0 0 240 240" class="radar-svg">
              <defs>
                <radialGradient id="emRadarFill" cx="50%" cy="45%" r="70%">
                  <stop offset="0%" :stop-color="scoreHex + '57'" />
                  <stop offset="100%" :stop-color="scoreHex + '1f'" />
                </radialGradient>
              </defs>
              <polygon
                v-for="g in radarGrid"
                :key="g.level"
                :points="g.points"
                :fill="g.idx % 2 === 0 ? 'rgba(128,128,128,0.12)' : 'rgba(128,128,128,0.06)'"
                :stroke="g.level === 1 ? 'rgba(128,128,128,0.5)' : 'rgba(128,128,128,0.25)'"
                :stroke-width="g.level === 1 ? 1.2 : 0.8"
              />
              <line v-for="p in radarPoints" :key="p.key + '-l'" :x1="120" :y1="120" :x2="p.gx" :y2="p.gy" stroke="rgba(128,128,128,0.3)" />
              <polygon :points="radarPolygon" :fill="'url(#emRadarFill)'" :stroke="scoreHex" stroke-width="2" />
              <circle v-for="p in radarPoints" :key="p.key" :cx="p.x" :cy="p.y" r="2.8" :fill="scoreHex" />
              <text x="120" y="127" text-anchor="middle" class="radar-score">{{ dashboard.emotion.score }}</text>
              <text v-for="p in radarPoints" :key="p.key + '-t'" :x="p.lx" :y="p.ly + 4" text-anchor="middle" class="radar-label" :style="{ cursor: 'help' }">
                {{ p.label }}
                <title>{{ p.label }}：{{ p.value }}分{{ p.desc ? ' — ' + p.desc : '' }}</title>
              </text>
            </svg>
          </div>
          <div v-else class="radar-empty">{{ dashboard.radar.length ? '今日情绪数据为空' : '暂无雷达数据' }}</div>
        </el-card>

        <el-card shadow="never" class="dash-card">
          <div class="card-title">
            涨跌分布 / 广度
            <span class="dist-note">涨停/跌停按涨跌幅阈值判定，含接近未封死（东财口径）</span>
          </div>
          <div class="dist-bars">
            <div v-for="b in distDisplay" :key="b.label" class="dist-col">
              <div class="dist-count">{{ b.count || '' }}</div>
              <div
                class="dist-bar"
                :class="distBarClass(b.dir)"
                :style="{ height: distHeight(b.count) + '%' }"
                :title="distTip(b)"
              />
              <div class="dist-label">{{ b.label }}</div>
            </div>
          </div>
          <div class="breadth-bar">
            <div class="breadth-track">
              <div class="breadth-up" :style="{ width: breadthUpW + '%' }" />
              <div class="breadth-flat" :style="{ width: breadthFlatW + '%' }" />
              <div class="breadth-down" :style="{ width: breadthDownW + '%' }" />
            </div>
            <div class="breadth-legend">
              <span class="lg-up">涨 {{ dashboard.breadth.up }}</span>
              <span class="lg-flat">平 {{ dashboard.breadth.flat }}</span>
              <span class="lg-down">跌 {{ dashboard.breadth.down }}</span>
            </div>
          </div>
        </el-card>
      </div>
    </section>

    <!-- 短线情绪速览：一看连板温度，详情跳转短线情绪页 -->
    <section v-if="dashboard" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 短线情绪速览</span>
        <router-link to="/vibe/review/emotion" class="block-more">
          进入短线情绪 <el-icon><ArrowRight /></el-icon>
        </router-link>
      </div>
      <div class="kpi-row kpi-row--4">
        <div class="kpi-cell">
          <div class="kpi-label">涨停</div>
          <div class="kpi-value up">{{ dashboard.limit.limit_up }}</div>
          <div class="kpi-sub">封板率 {{ dashboard.limit.seal_rate == null ? '—' : fmtAbsPct(dashboard.limit.seal_rate * 100, 0) }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">跌停</div>
          <div class="kpi-value down">{{ dashboard.limit.limit_down }}</div>
          <div class="kpi-sub">短线跌停家数</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">最高连板</div>
          <div class="kpi-value accent">{{ dashboard.limit.max_boards || 0 }}板</div>
          <div class="kpi-sub">梯队 {{ dashboard.limit.tiers.length }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">连板（2板+）</div>
          <div class="kpi-value accent">{{ dashboard.limit.tiers.length }}层</div>
          <div class="kpi-sub">连板梯队</div>
        </div>
      </div>
    </section>

    <!-- 四大榜单 -->
    <section v-if="dashboard" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataAnalysis /></el-icon> 市场榜单</span>
        <span class="block-hint">涨幅 / 跌幅 / 成交额 / 换手</span>
      </div>
      <div class="list-grid">
        <div v-for="(col, key) in listCols" :key="key" class="list-card">
          <div class="list-head">
            <span class="list-title">{{ col.title }}</span>
            <span class="list-top">TOP {{ col.rows.length }}</span>
          </div>
          <div v-for="(r, idx) in col.rows" :key="key + '-' + r.code" class="list-item">
            <span class="list-no">{{ idx + 1 }}</span>
            <div class="list-main">
              <router-link target="_blank" rel="noopener" :to="`/stocks/${r.code}`" class="list-name stock-name" :title="r.name">{{ r.name }}</router-link>
              <div class="list-code">{{ r.code }}</div>
            </div>
            <div class="list-right">
              <div v-if="col.mode === 'amount'" class="list-amt">{{ fmtAmount(r.amount) }}</div>
              <div v-else-if="col.mode === 'active'" class="list-amt accent">{{ r.turnover_rate }}%</div>
              <div :class="clsByVal(r.pct_chg)">{{ fmtPct(r.pct_chg) }}</div>
              <div v-if="col.mode === 'gain' || col.mode === 'loss'" class="list-close">{{ fmtPrice(r.close) }}</div>
            </div>
          </div>
        </div>
      </div>
    </section>
      </el-tab-pane>

      <!-- 外围市场（分类快照：美股 / 港股 / 亚太 / VIX / 股指期货 / A50 / 商品 + 美股港股个股） -->
      <el-tab-pane label="外围市场" name="overseas">
        <template v-if="overseas">
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Position /></el-icon> 外围市场快照</span>
              <div class="block-actions">
                <span class="block-hint">美股 · 港股 · 亚太 · VIX · 期货 · A50 · 商品</span>
                <el-button size="small" :icon="Refresh" :loading="overseasRefreshing || foreignLoading" @click="refreshOverseas">刷新</el-button>
              </div>
            </div>

            <!-- ① 分类快照 -->
            <div class="ovs-grid">
              <div v-for="g in overseasGroups" :key="g.key" class="ovs-group">
                <div class="ovs-group-head">
                  <el-icon :size="13"><component :is="g.icon" /></el-icon>
                  <span class="ovs-group-name">{{ g.label }}</span>
                  <span v-if="g.hint" class="ovs-group-hint">{{ g.hint }}</span>
                </div>
                <div class="ovs-rows">
                  <div v-for="idx in g.items" :key="idx.key" class="ovs-row">
                    <span class="ovs-name" :title="idx.name">{{ idx.name }}</span>
                    <span class="ovs-price">{{ idx.price != null ? idx.price.toFixed(2) : '—' }}</span>
                    <span class="ovs-pct" :class="clsByVal(idx.change_pct, 'flat')">{{ fmtPct(idx.change_pct) }}</span>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-if="!overseasGroups.length" :image-size="48" description="暂无外围数据" />

            <!-- ② 美股 / 港股个股行情 -->
            <div class="sub-block ovs-stocks-block">
              <div class="sub-title"><el-icon><DataLine /></el-icon> 美股 / 港股个股行情</div>
              <div class="ovs-stocks">
                <div class="ovs-stock-col">
                  <div class="ovs-stock-title">美股</div>
                  <div v-for="s in foreignUsStocks" :key="s.secid" class="ovs-row">
                    <span class="ovs-name" :title="s.name">{{ s.name }}</span>
                    <span class="ovs-price">{{ s.price != null ? s.price.toFixed(2) : '—' }}</span>
                    <span class="ovs-pct" :class="clsByVal(s.change_pct, 'flat')">{{ fmtPct(s.change_pct) }}</span>
                  </div>
                  <div v-if="!foreignUsStocks.length" class="ovs-empty">暂无美股数据</div>
                </div>
                <div class="ovs-stock-col">
                  <div class="ovs-stock-title">港股</div>
                  <div v-for="s in foreignHkStocks" :key="s.secid" class="ovs-row">
                    <span class="ovs-name" :title="s.name">{{ s.name }}</span>
                    <span class="ovs-price">{{ s.price != null ? s.price.toFixed(2) : '—' }}</span>
                    <span class="ovs-pct" :class="clsByVal(s.change_pct, 'flat')">{{ fmtPct(s.change_pct) }}</span>
                  </div>
                  <div v-if="!foreignHkStocks.length" class="ovs-empty">暂无港股数据</div>
                </div>
              </div>
            </div>
          </section>
        </template>
        <el-empty v-else-if="!overseasLoading" :image-size="48" description="外围市场数据暂不可用，可点「刷新」或刷新页面重试" />
      </el-tab-pane>
    </el-tabs>

    <!-- 免责声明 -->
    <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'ReviewOverview' })
import { ref, computed, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  DataLine,
  Refresh,
  Loading,
  Odometer,
  Position,
  Coin,
  TrendCharts,
  Warning,
  Goods,
  ArrowRight,
} from '@element-plus/icons-vue'
import { vibeApi, type IndexQuote, type MarketDashboard } from '@/api/vibe'
import { warRoomApi } from '@/api/warRoom'
import { fmtPrice, fmtPct, fmtAbsPct, fmtAmount, fmtSigned, clsByVal } from '@/utils/format'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'

const loading = ref(false)
const activeTab = ref('ashare')
const indices = ref<IndexQuote[]>([])
const dashboard = ref<MarketDashboard | null>(null)

const today = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

// 标题日期：优先后端数据返回的交易日；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => dashboard.value?.trade_date || tradeDate.value || '')

// 页头「更新于」：数据获取时刻（看板构建时刻）
const updatedAt = computed(() => dashboard.value?.updated ? formatBeijingDateTimeMinute(dashboard.value.updated) : '')

// ── 外围市场 tab（分类快照：美股/港股/亚太/VIX/股指期货/A50/商品 + 个股行情）──
const overseasLoading = ref(false)
const overseasRefreshing = ref(false)
const foreignLoading = ref(false)
const overseas = ref<Record<string, any> | null>(null)
const foreignStocks = ref<any[]>([])
const foreignUsStocks = computed(() => foreignStocks.value.filter(s => s.region === '美股'))
const foreignHkStocks = computed(() => foreignStocks.value.filter(s => s.region === '港股'))

// 外围快照分类定义（key 对应 macro_indices 返回项的 key）
const OVERSEAS_GROUP_DEFS: { key: string; label: string; icon: any; hint?: string; keys: string[] }[] = [
  { key: 'us', label: '美股指数', icon: TrendCharts, keys: ['dji', 'spx', 'ndx'] },
  { key: 'hk', label: '港股', icon: Coin, keys: ['hsi', 'hstech'] },
  { key: 'ap', label: '亚太', icon: DataLine, keys: ['n225', 'kospi'] },
  { key: 'vix', label: 'VIX 恐慌指数', icon: Warning, hint: '↑ 避险情绪升温', keys: ['vix'] },
  { key: 'fut', label: '美股股指期货', icon: Odometer, keys: ['spxfut', 'ndxfut', 'djifut'] },
  { key: 'a50', label: '富时A50 期货', icon: Position, keys: ['a50fut'] },
  { key: 'com', label: '大宗商品', icon: Goods, keys: ['gold', 'wti', 'copper'] },
]

/** 按分类把 indices 分组；空组自动隐藏 */
const overseasGroups = computed(() => {
  const list: any[] = (overseas.value?.indices) || []
  return OVERSEAS_GROUP_DEFS
    .map(g => ({ ...g, items: g.keys.map(k => list.find(i => i.key === k)).filter(Boolean) }))
    .filter(g => g.items.length)
})

const loadOverseas = async () => {
  overseasLoading.value = true
  try {
    overseas.value = await warRoomApi.getMacroReference()
  } catch (e) {
    console.warn('[Overview] 加载外围指数失败', e)
  } finally {
    overseasLoading.value = false
  }
}
const loadGlobalStocks = async () => {
  foreignLoading.value = true
  try {
    const res: any = await vibeApi.getGlobalStocks()
    foreignStocks.value = res?.data || []
  } catch (e) {
    console.warn('[Overview] 加载美股/港股失败', e)
  } finally {
    foreignLoading.value = false
  }
}
const refreshOverseas = async () => {
  overseasRefreshing.value = true
  try {
    await Promise.all([
      warRoomApi.getMacroReference(true).then(d => { overseas.value = d }),
      loadGlobalStocks(),
    ])
    ElMessage.success('外围市场已刷新')
  } catch (e) {
    console.warn('[Overview] 刷新外围市场失败', e)
    ElMessage.error('外围市场刷新失败，请稍后重试')
  } finally {
    overseasRefreshing.value = false
  }
}

const colorClass = (v: number | null | undefined) => {
  if (v == null) return 'flat'
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

// ---- 看板辅助函数 ----
const scoreColor = (v: number) => {
  if (v >= 70) return '#F04438'
  if (v >= 55) return '#FB923C'
  if (v >= 45) return '#F59E0B'
  if (v >= 30) return '#84CC16'
  return '#12B76A'
}
const scoreHex = computed(() => scoreColor(dashboard.value?.emotion.score ?? 50))
const scoreStyle = computed(() => {
  const c = scoreHex.value
  return { color: c, borderColor: c + '40', background: c + '14' }
})

// 雷达图几何
const RADAR_CX = 120
const RADAR_CY = 120
const RADAR_MAX_R = 78

// 各维度说明（悬停提示）
const RADAR_DESC: Record<string, string> = {
  index: '主要指数当日平均涨跌幅所反映的大盘整体强度',
  profit: '赚钱效应：上涨家数占比、涨跌幅均值/中位数与强势股占比综合',
  money: '量能：全市场平均换手率与高换手个股占比，反映资金活跃度',
  speculation: '投机：涨停家数、封板率、最高连板与2板以上家数综合',
  resilience: '抗跌：下跌家数占比与大跌家数占比越低，抗跌分越高',
  mainline: '主线：领涨行业平均涨幅与覆盖度，反映资金主攻方向',
}

const radarPoints = computed(() => {
  const dims = dashboard.value?.radar || []
  return dims.map((r, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / dims.length
    const radius = (RADAR_MAX_R * Math.max(0, Math.min(100, r.value))) / 100
    return {
      key: r.key,
      label: r.label,
      value: r.value,
      desc: RADAR_DESC[r.key] || '',
      x: RADAR_CX + Math.cos(angle) * radius,
      y: RADAR_CY + Math.sin(angle) * radius,
      lx: RADAR_CX + Math.cos(angle) * (RADAR_MAX_R + 27),
      ly: RADAR_CY + Math.sin(angle) * (RADAR_MAX_R + 27),
      gx: RADAR_CX + Math.cos(angle) * RADAR_MAX_R,
      gy: RADAR_CY + Math.sin(angle) * RADAR_MAX_R,
    }
  })
})
const radarPolygon = computed(() =>
  radarPoints.value.map(p => `${p.x},${p.y}`).join(' ')
)
const radarGrid = computed(() => {
  const n = dashboard.value?.radar?.length || 0
  return [1, 0.66, 0.33].map((level, idx) => ({
    level,
    idx,
    points: Array.from({ length: n }, (_, i) => {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n
      return `${RADAR_CX + Math.cos(angle) * RADAR_MAX_R * level},${RADAR_CY + Math.sin(angle) * RADAR_MAX_R * level}`
    }).join(' '),
  }))
})

// 涨跌分布
const distMax = computed(() =>
  Math.max(...(dashboard.value?.distribution.map(d => d.count) || [0]), 1)
)
const distHeight = (count: number) =>
  Math.max(4, (count / distMax.value) * 86)

// 反转后端分布（跌→涨）为 涨→平→跌，使红色(涨)在左、绿色(跌)在右，与广度条一致
const distDisplay = computed(() => {
  const dist = dashboard.value?.distribution || []
  return dist.slice().reverse()
})
const distBarClass = (dir: -1 | 0 | 1 | undefined) => {
  if (dir === 0) return 'dist-flat'
  if (dir === 1) return 'dist-up'
  return 'dist-down'
}

// 涨跌分布 tooltip：涨停/跌停按涨跌幅阈值判定（跌幅≤-限制价+容差即计入），
// 与东财/乐谷「真实封板」口径不同，含接近跌停未封死个股
const distTip = (b: { label: string; count: number }) => {
  const note = (b.label === '涨停' || b.label === '跌停')
    ? '（按涨跌幅阈值判定：达到板块涨跌幅限制，含接近未封死）'
    : ''
  return `${b.label}: ${b.count}只${note}`
}

const breadthUpW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return (b.up / b.total) * 100
})
const breadthFlatW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return Math.max(0, 100 - (b.up / b.total) * 100 - (b.down / b.total) * 100)
})
const breadthDownW = computed(() => {
  const b = dashboard.value?.breadth
  if (!b || !b.total) return 0
  return (b.down / b.total) * 100
})

// 四大榜单
const listCols = computed(() => {
  const d = dashboard.value
  if (!d) return []
  return [
    { title: '涨幅榜', mode: 'gain', rows: d.top_gainers },
    { title: '跌幅榜', mode: 'loss', rows: d.top_losers },
    { title: '成交额榜', mode: 'amount', rows: d.turnover_leaders },
    { title: '活跃换手', mode: 'active', rows: d.active_leaders },
  ]
})

// 带超时的请求包装
const withTimeout = <T>(promise: Promise<T>, timeoutMs: number = 15000): Promise<T> => {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      setTimeout(() => {
        reject(new Error(`请求超时 (${timeoutMs}ms)`))
      }, timeoutMs)
    })
  ])
}

const loadAll = async () => {
  loading.value = true
  try {
    const results = await Promise.allSettled([
      withTimeout(vibeApi.getIndices(), 15000),
      withTimeout(vibeApi.getDashboard(), 60000),
      withTimeout(loadOverseas(), 20000),
      // 外围美股/港股行情：后端已加 news 级缓存与预热，命中秒回；冷构建/外部源不可达可近 30s，超时放宽避免误杀
      withTimeout(loadGlobalStocks(), 30000),
    ])

    // 逐个处理结果，失败不影响其他数据显示
    const [idxRes, dashRes] = results
    if (idxRes.status === 'fulfilled') {
      indices.value = (idxRes.value as any).data || []
    }
    if (dashRes.status === 'fulfilled') {
      dashboard.value = (dashRes.value as any).data || null
    }

    // 统计失败数量，给出提示
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length > 0) {
      const msg = failed.map(r => (r as PromiseRejectedResult).reason.message).join(', ')
      ElMessage.warning(`${failed.length} 个接口加载超时，显示已有数据：${msg}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) tradeDate.value = d })
  loadAll()
})

// keep-alive 缓存恢复时刷新（大盘/外围/日历数据会随时间变化）
let overviewInited = false
onActivated(() => {
  if (overviewInited) loadAll()
  overviewInited = true
})
</script>

<style scoped>
.vibe-overview {
  padding: 4px;
}

.overview-tabs {
  margin-bottom: 8px;
}

.overview-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.block {
  margin-bottom: 24px;
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.block-title .el-icon {
  color: var(--el-color-primary);
}

.block-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.block-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.block-more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}

.block-more:hover {
  opacity: 0.8;
}

.sub-block {
  margin-bottom: 18px;
}

.sub-block:last-child {
  margin-bottom: 0;
}

.sub-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}

.sub-title .el-icon {
  color: var(--el-color-primary);
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.idx-card {
  border-radius: 8px;
}

.idx-card :deep(.el-card__body) {
  padding: 16px;
}

.idx-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
  gap: 6px;
}

.idx-name .region {
  margin-left: 4px;
  padding: 0 6px;
  font-size: 11px;
  line-height: 16px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  border-radius: 4px;
  vertical-align: 1px;
}

.idx-price {
  font-family: var(--app-font-mono);
  font-size: 26px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 8px 0 4px;
  letter-spacing: -0.5px;
}

.idx-change {
  font-family: var(--app-font-mono);
  font-size: 14px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.idx-change .amt {
  font-size: 12px;
  opacity: 0.8;
}

.empty-card :deep(.el-empty) {
  padding: 12px 0;
  margin: 0;
}

/* ── 外围市场：分类快照 ── */
.ovs-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.ovs-group {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 12px 14px;
  min-width: 0;
}
.ovs-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: var(--el-color-primary);
}
.ovs-group-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.ovs-group-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-color-warning);
  white-space: nowrap;
}
.ovs-rows {
  display: flex;
  flex-direction: column;
}
.ovs-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.ovs-row:last-child {
  border-bottom: none;
}
.ovs-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ovs-price {
  font-family: var(--app-font-mono);
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.ovs-pct {
  min-width: 62px;
  text-align: center;
  font-size: 12.5px;
  font-weight: 600;
  font-family: var(--app-font-mono);
  padding: 2px 8px;
  border-radius: 6px;
}
.ovs-pct.up { background: rgba(244, 60, 60, .1); }
.ovs-pct.down { background: rgba(38, 179, 117, .12); }
.ovs-pct.flat { color: var(--el-text-color-secondary); background: var(--el-fill-color); }

/* 美股 / 港股个股行情 */
.ovs-stocks {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.ovs-stock-col {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 12px 14px;
  min-width: 0;
}
.ovs-stock-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 6px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.ovs-empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 8px 0;
}

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 1200px) {
  .ovs-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .ovs-grid { grid-template-columns: 1fr; }
  .ovs-stocks { grid-template-columns: 1fr; }
}

/* ===== 市场看板（借鉴 tickflow Dashboard）===== */
.score-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 10px;
  border: 1px solid;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.kpi-row--4 {
  margin-bottom: 0;
}

.kpi-cell {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}

.kpi-label {
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-bottom: 6px;
}

.kpi-value {
  font-family: var(--app-font-mono);
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.kpi-value .kpi-sep {
  color: var(--el-text-color-placeholder);
  margin: 0 3px;
  font-weight: 400;
}

.kpi-value.accent {
  color: var(--el-color-primary);
}

.kpi-sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.dash-main {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.dash-card {
  border-radius: 8px;
}

.dash-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}

/* 雷达图 */
.radar-wrap {
  display: flex;
  justify-content: center;
  padding: 4px 0;
}

.radar-svg {
  width: 260px;
  height: 260px;
}

.radar-score {
  font-family: var(--app-font-mono);
  font-size: 26px;
  font-weight: 700;
  fill: var(--el-text-color-primary);
}

.radar-label {
  font-size: 11px;
  fill: var(--el-text-color-regular);
}

.radar-empty {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}

/* 涨跌分布 */
.dist-bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 152px;
  padding: 0 2px;
}

.dist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}

.dist-count {
  font-size: 10px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.dist-bar {
  width: 100%;
  max-width: 24px;
  border-radius: 3px 3px 0 0;
  min-height: 4px;
}

.dist-up { background: var(--app-up); }
.dist-flat { background: var(--app-flat); }
.dist-down { background: var(--app-down); }

/* 分布图口径说明（标题旁小字，常显） */
.dist-note {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}

.dist-label {
  font-size: 9px;
  line-height: 1.15;
  text-align: center;
  word-break: break-word;
  color: var(--el-text-color-placeholder);
  margin-top: 5px;
  white-space: normal;
}

.breadth-bar {
  margin-top: 14px;
}

.breadth-track {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-fill-color-light);
}

.breadth-up { background: var(--app-up); }
.breadth-flat { background: var(--app-flat); }
.breadth-down { background: var(--app-down); }

.breadth-legend {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
}

.lg-up { color: var(--app-up); }
.lg-flat { color: var(--app-flat); }
.lg-down { color: var(--app-down); }

/* 四大榜单 */
.list-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.list-card {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}

.list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.list-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.list-top {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.list-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.list-item:last-child {
  border-bottom: none;
}

.list-no {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.list-main {
  flex: 1;
  min-width: 0;
}

.list-name {
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-code {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.list-right {
  text-align: right;
  flex-shrink: 0;
}

.list-amt {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.list-amt.accent {
  color: var(--el-color-primary);
}

.list-close {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

@media (max-width: 1200px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .list-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .dash-main, .list-grid { grid-template-columns: 1fr; }
}
</style>
