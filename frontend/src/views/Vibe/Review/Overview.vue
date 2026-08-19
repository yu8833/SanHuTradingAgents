<template>
  <div class="vibe-overview app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ today }} · 大盘看板</h2>
          <p class="page-hero-sub">大盘指数 / 全球市场一屏看全</p>
        </div>
      </div>
      <div class="page-hero-meta">
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
          <div class="kpi-label">涨停 / 跌停</div>
          <div class="kpi-value">
            <span class="up">{{ dashboard.limit.limit_up }}</span><span class="kpi-sep">/</span><span class="down">{{ dashboard.limit.limit_down }}</span>
          </div>
          <div class="kpi-sub">封板率 {{ dashboard.limit.seal_rate == null ? '—' : fmtAbsPct(dashboard.limit.seal_rate * 100, 0) }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">最高连板</div>
          <div class="kpi-value accent">{{ dashboard.limit.max_boards || 0 }}板</div>
          <div class="kpi-sub">梯队 {{ dashboard.limit.tiers.length }}</div>
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
          <div class="card-title">涨跌分布 / 广度</div>
          <div class="dist-bars">
            <div v-for="b in distDisplay" :key="b.label" class="dist-col">
              <div class="dist-count">{{ b.count || '' }}</div>
              <div
                class="dist-bar"
                :class="distBarClass(b.dir)"
                :style="{ height: distHeight(b.count) + '%' }"
                :title="`${b.label}: ${b.count}只`"
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

    <!-- 行业热度 -->
    <section v-if="dashboard && (dashboard.industry_rank.leading.length || dashboard.industry_rank.lagging.length)" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataLine /></el-icon> 行业热度</span>
        <span class="block-hint">领涨 / 领跌</span>
      </div>
      <div class="rank-grid">
        <div class="rank-col">
          <div class="rank-col-title up">领涨</div>
          <div v-for="(item, idx) in dashboard.industry_rank.leading" :key="'ld-' + item.name" class="rank-item">
            <span class="rank-no">{{ idx + 1 }}</span>
            <div class="rank-main">
              <div class="rank-name" :title="item.name">{{ item.name }}</div>
              <div class="rank-sub">{{ item.count }}只 · 净流入{{ item.net }}亿</div>
            </div>
            <span class="rank-pct up">{{ fmtPct(item.pct) }}</span>
          </div>
        </div>
        <div class="rank-col">
          <div class="rank-col-title down">领跌</div>
          <div v-for="(item, idx) in dashboard.industry_rank.lagging" :key="'lg-' + item.name" class="rank-item">
            <span class="rank-no">{{ idx + 1 }}</span>
            <div class="rank-main">
              <div class="rank-name" :title="item.name">{{ item.name }}</div>
              <div class="rank-sub">{{ item.count }}只 · 净流出{{ Math.abs(item.net) }}亿</div>
            </div>
            <span class="rank-pct down">{{ fmtPct(item.pct) }}</span>
          </div>
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
              <router-link :to="`/stocks/${r.code}`" class="list-name stock-name" :title="r.name">{{ r.name }}</router-link>
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

      <!-- ============ 全球市场 ============ -->
      <el-tab-pane label="全球市场" name="global">
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><DataLine /></el-icon> 全球指数</span>
          </div>
          <div class="grid grid-5">
            <el-card
              v-for="item in globalIndices"
              :key="item.key"
              shadow="never"
              class="idx-card"
            >
              <div class="idx-name">
                {{ item.name }}<span class="region">{{ item.region }}</span>
              </div>
              <div class="idx-price">{{ fmtPrice(item.price) }}</div>
              <div class="idx-change" :class="colorClass(item.change_pct)">
                {{ fmtPct(item.change_pct) }}
              </div>
            </el-card>
            <el-card v-if="!globalIndices.length && !loading" shadow="never" class="idx-card empty-card">
              <el-empty :image-size="48" description="暂无全球指数" />
            </el-card>
          </div>
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><DataLine /></el-icon> 美股</span>
          </div>
          <div class="grid grid-5">
            <el-card
              v-for="item in usStocks"
              :key="item.secid"
              shadow="never"
              class="idx-card"
            >
              <div class="idx-name">
                {{ item.name }}<span class="region">美股</span>
              </div>
              <div class="idx-price">{{ fmtPrice(item.price) }}</div>
              <div class="idx-change" :class="colorClass(item.change_pct)">
                {{ fmtPct(item.change_pct) }}
              </div>
            </el-card>
            <el-card v-if="!usStocks.length && !loading" shadow="never" class="idx-card empty-card">
              <el-empty :image-size="48" description="暂无美股数据" />
            </el-card>
          </div>
        </section>

        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><DataLine /></el-icon> 港股</span>
          </div>
          <div class="grid grid-5">
            <el-card
              v-for="item in hkStocks"
              :key="item.secid"
              shadow="never"
              class="idx-card"
            >
              <div class="idx-name">
                {{ item.name }}<span class="region">港股</span>
              </div>
              <div class="idx-price">{{ fmtPrice(item.price) }}</div>
              <div class="idx-change" :class="colorClass(item.change_pct)">
                {{ fmtPct(item.change_pct) }}
              </div>
            </el-card>
            <el-card v-if="!hkStocks.length && !loading" shadow="never" class="idx-card empty-card">
              <el-empty :image-size="48" description="暂无港股数据" />
            </el-card>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <!-- 免责声明 -->
    <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'ReviewOverview' })
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  DataLine,
  Refresh,
  Loading,
  Odometer,
} from '@element-plus/icons-vue'
import {
  vibeApi,
  type IndexQuote,
  type GlobalIndex,
  type GlobalStock,
  type MarketDashboard,
} from '@/api/vibe'
import { fmtPrice, fmtPct, fmtAbsPct, fmtAmount, fmtSigned, clsByVal } from '@/utils/format'

const loading = ref(false)
const activeTab = ref('ashare')
const indices = ref<IndexQuote[]>([])
const globalIndices = ref<GlobalIndex[]>([])
const globalStocks = ref<GlobalStock[]>([])
const dashboard = ref<MarketDashboard | null>(null)

// 全球著名股票按 美股 / 港股 分组
const usStocks = computed(() => globalStocks.value.filter(s => s.region === '美股'))
const hkStocks = computed(() => globalStocks.value.filter(s => s.region === '港股'))

const today = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

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

// 雷达极端值兜底：当所有维度均为 0 时，多边形会塌陷为圆心一个点，
// 视觉上无意义。此时视为"今日无有效情绪数据"，展示空态而非退化图形。
const radarHasData = computed(() =>
  (dashboard.value?.radar || []).some(r => Number(r.value) > 0)
)

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
      withTimeout(vibeApi.getGlobalIndices(), 15000),
      withTimeout(vibeApi.getGlobalStocks(), 15000),
      withTimeout(vibeApi.getDashboard(), 20000),
    ])

    // 逐个处理结果，失败不影响其他数据显示
    const [idxRes, gRes, gsRes, dashRes] = results
    if (idxRes.status === 'fulfilled') {
      indices.value = idxRes.value.data || []
    }
    if (gRes.status === 'fulfilled') {
      globalIndices.value = gRes.value.data || []
    }
    if (gsRes.status === 'fulfilled') {
      globalStocks.value = gsRes.value.data || []
    }
    if (dashRes.status === 'fulfilled') {
      dashboard.value = dashRes.value.data || null
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
  loadAll()
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

.grid {
  display: grid;
  gap: 12px;
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.grid-5 {
  grid-template-columns: repeat(5, 1fr);
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
  font-size: 11px;
  color: var(--el-text-color-placeholder);
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

.up { color: #f56c6c; }
.down { color: #67c23a; }
.flat { color: #909399; }

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 1200px) {
  .grid-5 { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 768px) {
  .grid-4, .grid-5 { grid-template-columns: repeat(2, 1fr); }
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
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 12px;
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

.dist-up { background: #f56c6c; }
.dist-flat { background: #c0c4cc; }
.dist-down { background: #67c23a; }

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

.breadth-up { background: #f56c6c; }
.breadth-flat { background: #c0c4cc; }
.breadth-down { background: #67c23a; }

.breadth-legend {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
}

.lg-up { color: #f56c6c; }
.lg-flat { color: #909399; }
.lg-down { color: #67c23a; }

/* 行业热度 */
.rank-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.rank-col {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}

.rank-col-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.rank-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.rank-item:last-child {
  border-bottom: none;
}

.rank-no {
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

.rank-main {
  flex: 1;
  min-width: 0;
}

.rank-name {
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rank-sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 1px;
}

.rank-pct {
  font-family: var(--app-font-mono);
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

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
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
  .list-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .dash-main, .rank-grid, .list-grid { grid-template-columns: 1fr; }
}
</style>
