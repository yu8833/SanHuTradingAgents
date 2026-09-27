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
          <p class="page-hero-sub">大盘指数 / 市场情绪 / 涨跌分布一屏看全</p>
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

    <!-- 行业搜索 + AI 分析（名称查找，跨 热力图/象限/资金榜/领涨股/多周期 同步高亮） -->
    <section v-if="heatmapReady" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Search /></el-icon> 查找行业（名称）</span>
        <span v-if="matchNames.length" class="block-hint">命中 {{ matchNames.length }} 个行业，多图同步高亮</span>
      </div>
      <div class="search-row">
        <el-input
          v-model="sectorSearchKw"
          size="small"
          clearable
          placeholder="如：银行 或 半导体"
          class="search-input"
          @keyup.enter="doSectorSearch"
          @clear="clearSectorMatch"
        />
        <el-button size="small" type="primary" plain :icon="Search" :disabled="!sectorSearchKw.trim()" @click="doSectorSearch">
          查 找
        </el-button>
        <el-button
          size="small"
          type="warning"
          plain
          :icon="Cpu"
          :loading="aiLoading"
          :disabled="!sectorSearchKw.trim()"
          @click="doIndustryAiAnalyze"
        >
          AI 分析
        </el-button>
        <el-button v-if="matchNames.length" size="small" @click="clearSectorMatch">清除高亮</el-button>
      </div>
    </section>

    <!-- 大盘热力图：行业板块全景（左净流入 / 右净流出，中轴零线） -->
    <section v-if="heatmapReady" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataAnalysis /></el-icon> 大盘热力图 · 行业板块全景</span>
        <span class="block-hint">方块大小 = 资金量 · 左净流入 / 右净流出 · 红涨绿跌 · 点击跳转同花顺板块</span>
      </div>
      <div class="heatmap-wrap">
        <VChart :option="heatmapOption" autoresize class="heatmap-chart" @click="onHeatmapClick" />
        <div class="zero-axis"><span>0</span></div>
      </div>
    </section>

    <!-- 行业象限：涨跌 × 主力资金（与热力图同源 · 同花顺行业资金流） -->
    <section v-if="heatmapReady" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 行业象限 · 涨跌 × 主力资金</span>
        <span class="block-hint">X=涨跌幅(%) · Y=主力净流入(亿) · 圆点大小=资金量 · 红涨绿跌 · 点击跳转同花顺板块</span>
      </div>
      <div class="sector-quadrant">
        <VChart :option="sectorQuadrantOption" autoresize class="sector-quadrant-chart" @click="onSectorClick" />
        <div class="quadrant-tip">
          <span v-for="(t, i) in SECTOR_QUADRANT_TIPS" :key="i" class="qt-item">
            <i class="qt-dot" :class="SECTOR_QUADRANT_DOTS[i]" />{{ t }}
          </span>
        </div>
      </div>
    </section>

    <!-- 行业资金 · 多周期（3/5/10/20 日阶段涨跌幅 + 区间净额） -->
    <section v-if="periodMatrixReady" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><TrendCharts /></el-icon> 行业资金 · 多周期</span>
        <span class="block-hint">资金轮动矩阵 · 每格颜色 = 区间主力净流入（红流入/绿流出，颜色越深额越大）· 按 20 日净额排序 · 点击跳转同花顺板块 · 更新于 {{ periodFlows?.as_of || '—' }}</span>
      </div>
      <div class="period-matrix">
        <VChart :option="periodMatrixOption" autoresize class="period-matrix-chart" @click="onMatrixClick" />
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
                <span class="block-hint">美股 · 港股 · 亚太 · VIX · 期货 · A50 · 商品 · 更新于 {{ fmtClock(overseas.generated_at) }}</span>
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

    <!-- 行业 AI 分析结果弹窗 -->
    <el-dialog v-model="aiDialog" :title="aiDialogTitle" width="640px" class="ai-dialog" :close-on-click-modal="false">
      <div v-if="aiLoading" class="ai-body ai-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在基于该行业（同花顺行业资金流 + 多周期）生成操作结论…</span>
      </div>
      <el-alert v-else-if="aiError" :title="aiError" type="error" show-icon :closable="false" class="ai-body" />
      <el-empty v-else-if="aiResult && !aiResult.found" :description="aiResult.message || '未找到该行业数据'" />
      <template v-else-if="aiResult">
        <div class="ai-body">
          <div class="ai-head">
            <div class="ai-head-tags">
              <el-tag :color="aiActionColor" effect="dark" size="large">{{ aiResult.action_label }}</el-tag>
              <el-tag :type="aiResult.engine === 'llm' ? 'primary' : 'info'" size="small" effect="plain">
                {{ aiResult.engine === 'llm' ? 'LLM 深度分析' : '规则引擎兜底' }}
              </el-tag>
            </div>
            <div class="ai-score">
              <el-progress :percentage="aiScorePct" :color="aiActionColor" :stroke-width="10" />
              <span class="ai-score-txt">综合评分 {{ aiResult.score }} 分</span>
            </div>
          </div>
          <p class="ai-summary">{{ aiResult.summary }}</p>
          <div v-if="aiResult.reasons?.length" class="ai-block">
            <div class="ai-block-title">判断要点</div>
            <ul class="ai-list">
              <li v-for="(r, i) in aiResult.reasons" :key="'r' + i">{{ r }}</li>
            </ul>
          </div>
          <div v-if="aiResult.risks?.length" class="ai-block">
            <div class="ai-block-title">风险提示</div>
            <ul class="ai-list ai-risk">
              <li v-for="(r, i) in aiResult.risks" :key="'k' + i">{{ r }}</li>
            </ul>
          </div>
          <div class="ai-block">
            <div class="ai-block-title">今日行情（同花顺行业资金流 · {{ aiResult.as_of }}）</div>
            <div class="ai-table">
              <div v-for="cell in aiTodayCells" :key="cell.label" class="ai-cell">
                <span class="ai-cell-label">{{ cell.label }}</span>
                <b :class="cell.cls">{{ cell.text }}</b>
              </div>
            </div>
          </div>
          <div v-if="aiPeriodCells.length" class="ai-block">
            <div class="ai-block-title">多周期资金（3/5/10/20 日净额 · 阶段涨跌幅）</div>
            <div class="ai-table">
              <div v-for="cell in aiPeriodCells" :key="cell.label" class="ai-cell">
                <span class="ai-cell-label">{{ cell.label }}</span>
                <b :class="cell.cls">{{ cell.text }}</b>
              </div>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>

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
  Search,
  Cpu,
} from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { TreemapChart, ScatterChart, HeatmapChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import {
  vibeApi,
  type IndexQuote,
  type MarketDashboard,
  type IndustryPeriodFlows,
} from '@/api/vibe'
import { warRoomApi } from '@/api/warRoom'
import { fmtPrice, fmtPct, fmtAbsPct, fmtAmount, fmtSigned, fmtAbs, clsByVal } from '@/utils/format'

echartsUse([CanvasRenderer, TreemapChart, ScatterChart, HeatmapChart, TooltipComponent, GridComponent, MarkAreaComponent, MarkLineComponent])

const loading = ref(false)
const activeTab = ref('ashare')
const indices = ref<IndexQuote[]>([])
const dashboard = ref<MarketDashboard | null>(null)
// 行业板块热力图数据（/market/overview → sectors）
const sectorMap = ref<any[]>([])
const heatmapReady = computed(() => sectorMap.value.length > 0)

const today = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

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

// 快照生成时间格式化：今日显示「今日 HH:MM」，否则「M/D HH:MM」
function fmtClock(iso?: string): string {
  if (!iso) return '—'
  let s = String(iso).trim()
  // 统一截断多余小数秒到 3 位（后端微秒 .898000，部分浏览器解析 >3 位微秒失败）
  s = s.replace(/\.(\d{3})\d+/, '.$1')
  // 时区判定：Z / ±HH:MM（可带括号注释，如 "+08:00 (CST)"）都视为带时区；
  // 无时区的 naive ISO（如旧缓存）一律按 UTC 补 Z，避免按本地时区解析导致时间倒退
  if (!/([Z]|[+-]\d{2}:?\d{2}( ?\(.+\))?)$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.toDateString() === new Date().toDateString()
    ? `今日 ${hm}`
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
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

// ── 大盘热力图：行业板块 treemap（面积=公司家数，颜色=涨跌幅 红涨绿跌）──
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
/** 涨跌幅 → 颜色：0% 中性灰，+5% 红，-5% 绿（A股配色） */
function heatColor(pct: number | null | undefined): string {
  const t = clamp01(Math.abs(pct || 0) / 5)
  const gray: [number, number, number] = [226, 232, 240]
  const red: [number, number, number] = [244, 99, 88]
  const green: [number, number, number] = [103, 178, 70]
  const mix = (c1: number[], c2: number[], k: number) => {
    const [r, g, b] = c1.map((v, i) => Math.round(v + (c2[i] - v) * k))
    return `rgb(${r},${g},${b})`
  }
  return (pct || 0) >= 0 ? mix(gray, red, t) : mix(gray, green, t)
}

// treemap 数据项：面积=资金量（流入用净额、流出用绝对值），颜色=涨跌幅
const inflowSectors = computed(() => sectorMap.value.filter(s => (Number(s.net) || 0) >= 0))
const outflowSectors = computed(() => sectorMap.value.filter(s => (Number(s.net) || 0) < 0))

const mkTreemapData = (list: any[], abs = false) => {
  const hasMatch = matchSet.value.size > 0
  return list.map(s => {
    const net = Number(s.net) || 0
    const matched = matchSet.value.has(String(s.name || ''))
    return {
      name: s.name,
      // 面积=净流入/净流出资金量（绝对净额），下限兜底避免方块过小
      value: Math.max(abs ? Math.abs(net) : net, 1e6),
      pct: s.pct,
      net,
      firms: s.firms,
      ths_code: s.ths_code,
      index: s.index,
      lead: s.lead,
      lead_pct: s.lead_pct,
      lead_price: s.lead_price,
      itemStyle: {
        color: heatColor(s.pct),
        // 搜索命中：宝蓝高亮边框；未命中（有命中集时）淡化
        ...(matched
          ? { borderColor: '#1d4ed8', borderWidth: 2.5, shadowBlur: 10, shadowColor: 'rgba(37,99,235,.55)' }
          : hasMatch ? { opacity: 0.35 } : {}),
      },
    }
  })
}

const heatmapOption = computed<EChartsOption>(() => {
  return {
    animationDuration: 600,
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (p: any) => {
        const d = p?.data ?? {}
        const pct = Number(d.pct) || 0
        const cls = pct >= 0 ? '#f56c6c' : '#67c23a'
        const netYi = Number(d.net ?? 0) / 1e8
        return `<b>${d.name || ''}</b><br/>`
          + `涨跌 <b style="color:${cls};font-family:monospace">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</b><br/>`
          + `净额 <b style="font-family:monospace">${fmtSigned(netYi)}亿</b><br/>`
          + (d.index != null ? `行业指数 <b style="font-family:monospace">${d.index}</b><br/>` : '')
          + (d.lead ? `领涨股 <b style="font-family:monospace">${d.lead}</b> <span style="color:#a0aec0">${(d.lead_pct ?? 0) >= 0 ? '+' : ''}${Number(d.lead_pct ?? 0).toFixed(2)}% · ${Number(d.lead_price ?? 0).toFixed(2)}元</span><br/>` : '')
          + `公司家数 <b style="font-family:monospace">${d.firms ?? '—'}</b>`
      },
    },
    graphic: [
      { type: 'text', left: 14, top: 2, style: { text: '← 净流入', fill: '#f56c6c', fontSize: 12, fontWeight: 600 } },
      { type: 'text', right: 14, top: 2, style: { text: '净流出 →', fill: '#67c23a', fontSize: 12, fontWeight: 600 } },
    ],
    series: [{
      // 左半：净流入行业（左侧，越靠左资金流入越大）
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      left: 0,
      top: 22,
      width: '49%',
      bottom: 0,
      itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 },
      label: {
        show: true,
        color: '#1f2937',
        fontSize: 11,
        formatter: (p: any) => {
          const d = p?.data ?? {}
          const pct = Number(d.pct) || 0
          return `${d.name || ''}\n${pct >= 0 ? '+' : ''}${(pct || 0).toFixed(2)}%`
        },
      },
      upperLabel: { show: false },
      data: mkTreemapData(inflowSectors.value, false),
    }, {
      // 右半：净流出行业（右侧）
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      left: '51%',
      top: 22,
      width: '49%',
      bottom: 0,
      itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 },
      label: {
        show: true,
        color: '#1f2937',
        fontSize: 11,
        formatter: (p: any) => {
          const d = p?.data ?? {}
          const pct = Number(d.pct) || 0
          return `${d.name || ''}\n${pct >= 0 ? '+' : ''}${(pct || 0).toFixed(2)}%`
        },
      },
      upperLabel: { show: false },
      data: mkTreemapData(outflowSectors.value, true),
    }],
  }
})

// 点击行业块 → 跳转同花顺行业板块详情页
function onHeatmapClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.ths_code
  if (!code) return
  window.open(`https://q.10jqka.com.cn/thshy/detail/code/${code}/`, '_blank', 'noopener')
}

// ── 行业象限（复用热力图 sectors = 同花顺 stock_fund_flow_industry 即时）──
const MONO = "'SFMono-Regular', ui-monospace, Menlo, monospace"

interface SectorPoint {
  name: string
  pct: number
  netYi: number
  inflowYi: number
  outflowYi: number
  firms: number
  ths_code: string
  /** 行业指数点位 */
  index: number | null
  /** 领涨股名称 */
  lead: string
  /** 领涨股涨跌幅 % */
  lead_pct: number | null
  /** 领涨股当前价 元 */
  lead_price: number | null
}

/** 同花顺行业资金流（net 单位元）→ 象限/榜单数据点（亿） */
const sectorPoints = computed<SectorPoint[]>(() =>
  sectorMap.value
    .map(s => ({
      name: String(s.name || ''),
      pct: Number(s.pct) || 0,
      netYi: (Number(s.net) || 0) / 1e8,
      inflowYi: (Number(s.inflow) || 0) / 1e8,
      outflowYi: (Number(s.outflow) || 0) / 1e8,
      firms: Number(s.firms) || 0,
      ths_code: String(s.ths_code || ''),
      index: s.index != null && Number.isFinite(Number(s.index)) ? Number(s.index) : null,
      lead: String(s.lead || ''),
      lead_pct: s.lead_pct != null && Number.isFinite(Number(s.lead_pct)) ? Number(s.lead_pct) : null,
      lead_price: s.lead_price != null && Number.isFinite(Number(s.lead_price)) ? Number(s.lead_price) : null,
    }))
    .filter(p => p.name && !Number.isNaN(p.pct) && !Number.isNaN(p.netYi)),
)

const sectorByName = computed(() => new Map(sectorPoints.value.map(p => [p.name, p])))

// 象限语义（右上/左上/右下/左下，对应四角红/黄/蓝/绿）
const SECTOR_QUADRANT_TIPS = [
  '流入+上涨 · 强势共振',
  '下跌+流入 · 低位承接',
  '上涨+流出 · 缩量上行',
  '下跌+流出 · 弱势杀跌',
]
const SECTOR_QUADRANT_DOTS = ['qt-red', 'qt-yellow', 'qt-blue', 'qt-green']

// 圆点大小 = 主力资金量（亿元，对数归一 6~18）
const sectorNetAbsMax = computed(() =>
  Math.max(...sectorPoints.value.map(p => Math.abs(p.netYi)), 1),
)
const sectorSizeOf = (netYi: number): number => {
  if (!(Math.abs(netYi) > 0)) return 6
  const base = Math.log10(Math.abs(netYi) + 1)
  const hi = Math.max(Math.log10(sectorNetAbsMax.value + 1), 1e-6)
  return Math.round(6 + 12 * Math.min(1, base / hi))
}

const mkSectorData = (list: SectorPoint[]) => {
  const hasMatch = matchSet.value.size > 0
  return list.map(p => {
    const matched = matchSet.value.has(p.name)
    const baseSize = sectorSizeOf(p.netYi)
    return {
      name: p.name,
      ths_code: p.ths_code,
      value: [p.pct, p.netYi],
      pct: p.pct,
      netYi: p.netYi,
      inflowYi: p.inflowYi,
      outflowYi: p.outflowYi,
      firms: p.firms,
      index: p.index,
      lead: p.lead,
      lead_pct: p.lead_pct,
      lead_price: p.lead_price,
      symbolSize: matched ? baseSize + 6 : baseSize,
      itemStyle: matched
        ? { color: '#1d4ed8', borderColor: '#2563eb', borderWidth: 1.5, shadowBlur: 12, shadowColor: 'rgba(37,99,235,.8)' }
        : hasMatch ? { opacity: 0.25 } : undefined,
    }
  })
}

const sectorQuadrantOption = computed<EChartsOption>(() => {
  // 四象限角标（白底文字芯片，颜色对齐底部图例：红/黄/蓝/绿）
  const corners = [
    { pos: 'insideTopRight' as const, color: '#dc2626', border: '#f87171' },
    { pos: 'insideTopLeft' as const, color: '#b45309', border: '#fbbf24' },
    { pos: 'insideBottomRight' as const, color: '#1d4ed8', border: '#60a5fa' },
    { pos: 'insideBottomLeft' as const, color: '#15803d', border: '#4ade80' },
  ]
  const cornerLabel = (i: number) => ({
    show: true,
    position: corners[i].pos,
    distance: 5,
    color: corners[i].color,
    fontSize: 12,
    fontWeight: 'bold' as const,
    backgroundColor: 'rgba(255,255,255,.94)',
    borderColor: corners[i].border,
    borderWidth: 1,
    borderRadius: 6,
    padding: [3, 8],
    shadowBlur: 5,
    shadowColor: 'rgba(30,41,59,.18)',
    shadowOffsetY: 1,
  })
  const mkAreaData = () => [
    [{ name: '强势共振', coord: [0, 0], itemStyle: { color: 'rgba(255,235,238,.5)' }, label: cornerLabel(0) }, { coord: ['max', 'max'] }],
    [{ name: '低位承接', coord: ['min', 0], itemStyle: { color: 'rgba(255,250,225,.5)' }, label: cornerLabel(1) }, { coord: [0, 'max'] }],
    [{ name: '缩量上行', coord: [0, 'min'], itemStyle: { color: 'rgba(235,245,255,.5)' }, label: cornerLabel(2) }, { coord: ['max', 0] }],
    [{ name: '弱势杀跌', coord: ['min', 'min'], itemStyle: { color: 'rgba(240,249,240,.5)' }, label: cornerLabel(3) }, { coord: [0, 0] }],
  ]
  const up = sectorPoints.value.filter(p => p.pct >= 0).map(p => mkSectorData([p])[0])
  const down = sectorPoints.value.filter(p => p.pct < 0).map(p => mkSectorData([p])[0])
  return {
    animationDuration: 600,
    grid: { left: 64, right: 28, top: 30, bottom: 44 },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (p: any) => {
        const d = p?.data ?? {}
        const x = Number(d.pct ?? 0)
        const y = Number(d.netYi ?? 0)
        const xCls = x >= 0 ? '#f56c6c' : '#67c23a'
        const yCls = y >= 0 ? '#f56c6c' : '#67c23a'
        return `<b>${d.name || ''}</b><br/>`
          + `<span style="color:#a0aec0">涨跌幅</span> <b style="color:${xCls};font-family:${MONO}">${x >= 0 ? '+' : ''}${x.toFixed(2)}%</b><br/>`
          + `<span style="color:#a0aec0">主力净流入</span> <b style="color:${yCls};font-family:${MONO}">${y >= 0 ? '+' : ''}${y.toFixed(2)}亿</b><br/>`
          + `<span style="color:#a0aec0">流入/流出</span> <b style="font-family:${MONO}">${fmtAbs(d.inflowYi ?? 0)} / ${fmtAbs(d.outflowYi ?? 0)} 亿</b><br/>`
          + (d.index != null ? `<span style="color:#a0aec0">行业指数</span> <b style="font-family:${MONO}">${d.index}</b><br/>` : '')
          + (d.lead ? `<span style="color:#a0aec0">领涨股</span> <b style="font-family:${MONO}">${d.lead}</b> <span style="color:#a0aec0">${(d.lead_pct ?? 0) >= 0 ? '+' : ''}${Number(d.lead_pct ?? 0).toFixed(2)}% · ${Number(d.lead_price ?? 0).toFixed(2)}元</span><br/>` : '')
          + `<span style="color:#a0aec0">公司家数</span> <b style="font-family:${MONO}">${d.firms ?? '—'}</b>`
      },
    },
    xAxis: {
      name: '涨跌幅（%）',
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10, formatter: (v: number) => `${v}%` },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      name: '主力净流入（亿）',
      nameLocation: 'middle',
      nameGap: 36,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        name: '上涨',
        type: 'scatter',
        itemStyle: { color: 'rgba(245,108,108,.6)' },
        emphasis: { scale: 2.2, itemStyle: { borderColor: '#2d3748', borderWidth: 1 } },
        data: up,
      },
      {
        name: '下跌',
        type: 'scatter',
        itemStyle: { color: 'rgba(103,194,58,.6)' },
        emphasis: { scale: 2.2, itemStyle: { borderColor: '#2d3748', borderWidth: 1 } },
        data: down,
      },
      {
        // 顶层标记系列：承载零轴分隔线与四象限角标（数据恒空，ECharts 合并时角标不重排）
        type: 'scatter',
        z: 5,
        symbolSize: 0,
        data: [],
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: 'rgba(100,116,139,.9)', type: 'dashed', width: 1.4 },
          label: { show: false },
          data: [{ xAxis: 0 }, { yAxis: 0 }],
        },
        markArea: {
          silent: true,
          data: mkAreaData(),
        },
      },
    ],
  }
})

// 点击象限散点 → 跳转同花顺板块
function onSectorClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.ths_code
  if (code) window.open(`https://q.10jqka.com.cn/thshy/detail/code/${code}/`, '_blank', 'noopener')
}

// ── 行业搜索：按名称查找，跨 热力图/象限/多周期矩阵 静态同步高亮 ──
const sectorSearchKw = ref('')
const matchNames = ref<string[]>([])
const matchSet = computed(() => new Set(matchNames.value))

async function doSectorSearch() {
  const kw = sectorSearchKw.value.trim()
  if (!kw) {
    clearSectorMatch()
    return
  }
  const hits = sectorPoints.value.filter(p => p.name.includes(kw)).map(p => p.name)
  if (!hits.length) {
    clearSectorMatch()
    ElMessage.warning(`未找到名称包含「${kw}」的行业`)
    return
  }
  if (hits.length > 200) hits.length = 200
  matchNames.value = hits
}

function clearSectorMatch() {
  matchNames.value = []
}

// ── 行业资金 · 多周期卡（3/5/10/20 日资金轮动矩阵热力图） ──
const PERIOD_LABELS: Record<string, string> = { '3': '3日', '5': '5日', '10': '10日', '20': '20日' }
const PERIOD_KEYS = ['3', '5', '10', '20']
const periodFlows = ref<IndustryPeriodFlows | null>(null)
const periodMatrixReady = computed(() => !!(periodFlows.value?.periods?.['20']?.length))

/** 各周期净额绝对值上限（颜色归一基线，取 4 周期全行业最大绝对值） */
const periodNetAbsMax = computed(() => {
  const periods = periodFlows.value?.periods ?? {}
  let hi = 1
  for (const rows of Object.values(periods)) {
    for (const r of rows) hi = Math.max(hi, Math.abs(Number(r.net) || 0))
  }
  return hi
})

/** 资金轮动矩阵 option：X=周期，Y=行业（按 20 日净额降序），颜色=区间净额 */
const periodMatrixOption = computed<EChartsOption | null>(() => {
  const periods = periodFlows.value?.periods
  if (!periods?.['20']?.length) return null
  // 按 20 日净额降序排行业（自上而下 = 中长期资金最强 → 最弱）
  const names = (periods['20'] as IndustryPeriodRow[])
    .slice()
    .sort((a, b) => (Number(b.net) || 0) - (Number(a.net) || 0))
    .map(r => r.name)
  const hi = Math.max(1, periodNetAbsMax.value)
  const hasMatch = matchSet.value.size > 0
  const data: any[] = []
  names.forEach((name, yIdx) => {
    const matched = matchSet.value.has(name)
    PERIOD_KEYS.forEach((k, xIdx) => {
      const row = (periods[k] ?? []).find(r => r.name === name)
      const net = Number(row?.net || 0)
      data.push({
        name,
        yIdx,
        value: [xIdx, yIdx, net],
        netYi: net / 1e8,
        pct: row?.pct ?? null,
        ths_code: sectorByName.value.get(name)?.ths_code ?? '',
        matched,
        itemStyle: {
          // 红涨绿跌随净额绝对值加深（同即时热力图配色风格）
          color: net >= 0
            ? `rgba(244,99,88,${0.12 + 0.66 * Math.min(1, Math.abs(net) / hi)})`
            : `rgba(103,178,70,${0.12 + 0.66 * Math.min(1, Math.abs(net) / hi)})`,
          ...(matched
            ? { borderColor: '#1d4ed8', borderWidth: 1.5 }
            : hasMatch ? { opacity: 0.3 } : {}),
        },
      })
    })
  })
  return {
    animationDuration: 600,
    grid: { left: 74, right: 20, top: 14, bottom: 30 },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (p: any) => {
        const d = p?.data ?? {}
        const netYi = Number(d.netYi ?? 0)
        const netCls = netYi >= 0 ? '#f56c6c' : '#67c23a'
        const pctCls = (d.pct ?? 0) >= 0 ? '#f56c6c' : '#67c23a'
        return `<b>${d.name || ''}</b> <span style="color:#a0aec0;font-size:11px">${PERIOD_LABELS[PERIOD_KEYS[d.value?.[0]] as string] || ''}</span><br/>`
          + `<span style="color:#a0aec0">区间净流入</span> <b style="color:${netCls};font-family:${MONO}">${netYi >= 0 ? '+' : ''}${netYi.toFixed(2)}亿</b><br/>`
          + `<span style="color:#a0aec0">阶段涨跌幅</span> <b style="color:${pctCls};font-family:${MONO}">${fmtPct(d.pct ?? 0)}</b>`
      },
    },
    xAxis: {
      type: 'category',
      data: PERIOD_KEYS.map(k => PERIOD_LABELS[k]),
      axisLabel: { color: '#a0aec0', fontSize: 11 },
      splitLine: { show: false },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true, // 第一名在顶部
      axisLabel: { color: '#4a5568', fontSize: 10 },
      splitLine: { show: false },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    dataZoom: [
      // 行数多（90 行业），保留滚轮/拖拽缩放，便于放大看局部
      { type: 'inside', yAxisIndex: 0 },
      { type: 'slider', yAxisIndex: 0, right: 2, width: 14, showDetail: false },
    ],
    series: [{
      type: 'heatmap',
      data,
      progressive: 400,
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(37,99,235,.5)', borderColor: '#2563eb', borderWidth: 1 },
      },
    }],
  }
})

// 点击矩阵格子 → 跳转同花顺板块
function onMatrixClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.ths_code
  if (code) window.open(`https://q.10jqka.com.cn/thshy/detail/code/${code}/`, '_blank', 'noopener')
}

// ── 行业 AI 分析（LLM 优先，规则兜底；结果弹窗参考个股趋势） ──
const aiDialog = ref(false)
const aiLoading = ref(false)
const aiError = ref('')
const aiResult = ref<any>(null)

// 操作建议 → 展示色（买入红/关注橙/持有蓝/观望灰/减仓绿/回避青）
const AI_ACTION_COLOR: Record<string, string> = {
  strong_buy: '#f56c6c',
  buy: '#e6a23c',
  hold: '#409eff',
  wait: '#909399',
  reduce: '#67c23a',
  avoid: '#13a8a8',
}
const aiActionColor = computed(() => AI_ACTION_COLOR[aiResult.value?.action as string] || '#909399')
const aiDialogTitle = computed(() => {
  const r = aiResult.value
  return r ? `AI 分析 · ${r.name} 行业` : 'AI 分析'
})
// 评分 -100~100 → 0~100 进度展示
const aiScorePct = computed(() => {
  const s = Number(aiResult.value?.score ?? 0)
  return Math.max(0, Math.min(100, Math.round((s + 100) / 2)))
})

function fmtN(v: any, unit = '', sign = false): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const s = sign && n > 0 ? '+' : ''
  const num = Number.isInteger(n) ? String(n) : n.toFixed(2)
  return `${s}${num}${unit}`
}

const AI_TODAY_DEF = [
  { key: 'pct', label: '今日涨跌', unit: '%', sign: true },
  { key: 'net_yi', label: '主力净流入', unit: '亿', sign: true },
  { key: 'inflow_yi', label: '流入', unit: '亿' },
  { key: 'outflow_yi', label: '流出', unit: '亿' },
  { key: 'index', label: '行业指数' },
  { key: 'lead', label: '领涨股', render: (v: any) => (v ? String(v) : '—') },
  { key: 'lead_pct', label: '领涨股涨幅', unit: '%', sign: true },
  { key: 'lead_price', label: '领涨股现价', unit: '元' },
]
const aiTodayCells = computed(() => {
  const today = aiResult.value?.data?.today ?? {}
  return AI_TODAY_DEF.map(d => {
    const raw = today[d.key]
    let text: string
    let cls = ''
    if (d.render) {
      text = d.render(raw)
      cls = (raw != null && (Number(raw) || 0) > 0) ? 'up' : (raw != null && (Number(raw) || 0) < 0 ? 'down' : '')
    } else {
      text = fmtN(raw, d.unit || '', !!d.sign)
      cls = (raw != null && (Number(raw) || 0) > 0) ? 'up' : (raw != null && (Number(raw) || 0) < 0 ? 'down' : '')
    }
    return { label: d.label, text, cls }
  })
})
const AI_PERIOD_KEYS = ['3', '5', '10', '20']
const aiPeriodCells = computed(() => {
  const pf = aiResult.value?.data?.period_flows ?? {}
  return AI_PERIOD_KEYS.map(k => {
    const p = pf[k]
    const netYi = p?.net_yi
    const pct = p?.pct
    const text = p != null
      ? `${fmtN(netYi, '亿', (Number(netYi) || 0) > 0)} · ${fmtN(pct, '%', (Number(pct) || 0) > 0)}`
      : '—'
    const cls = (netYi != null && Number(netYi) > 0) ? 'up' : (netYi != null && Number(netYi) < 0 ? 'down' : '')
    return { label: `${k}日`, text, cls }
  })
})

async function doIndustryAiAnalyze() {
  const kw = sectorSearchKw.value.trim()
  if (!kw) return
  const hits = sectorPoints.value.filter(p => p.name.includes(kw)).map(p => p.name)
  if (!hits.length) {
    ElMessage.warning(`未找到与「${kw}」匹配的行业`)
    return
  }
  if (hits.length > 1) {
    ElMessage.warning(`「${kw}」匹配到 ${hits.length} 个行业，请输入完整行业名后再分析`)
    return
  }
  const name = hits[0]
  aiError.value = ''
  aiResult.value = null
  aiDialog.value = true
  aiLoading.value = true
  try {
    const res = await vibeApi.getIndustryAiAnalysis(name)
    aiResult.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('行业 AI 分析请求失败', e)
    aiError.value = '行业 AI 分析请求失败，请稍后重试'
  } finally {
    aiLoading.value = false
  }
}

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
      withTimeout(vibeApi.getMarketOverview(), 20000),
      withTimeout(vibeApi.getIndustryPeriodFlows(), 20000),
      withTimeout(loadOverseas(), 20000),
      // 外围美股/港股行情：后端已加 news 级缓存与预热，命中秒回；冷构建/外部源不可达可近 30s，超时放宽避免误杀
      withTimeout(loadGlobalStocks(), 30000),
    ])

    // 逐个处理结果，失败不影响其他数据显示
    const [idxRes, dashRes, ovRes, periodRes] = results
    if (idxRes.status === 'fulfilled') {
      indices.value = (idxRes.value as any).data || []
    }
    if (dashRes.status === 'fulfilled') {
      dashboard.value = (dashRes.value as any).data || null
    }
    if (ovRes.status === 'fulfilled') {
      sectorMap.value = (ovRes.value as any).data?.sectors || []
    }
    if (periodRes.status === 'fulfilled') {
      periodFlows.value = (periodRes.value as any).data || null
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

.heatmap-wrap {
  position: relative;
}

.heatmap-chart {
  width: 100%;
  height: 480px;
}

/* 行业象限（与热力图同源同花顺行业资金流） */
.sector-quadrant-chart {
  width: 100%;
  height: 420px;
}

.quadrant-tip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.qt-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.qt-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.qt-dot.qt-red { background: #f56c6c; }
.qt-dot.qt-yellow { background: #fbbf24; }
.qt-dot.qt-blue { background: #60a5fa; }
.qt-dot.qt-green { background: #4ade80; }

/* 行业搜索条（名称查找 · AI 分析） */
.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-input {
  width: 260px;
}

/* 行业资金 · 多周期卡（资金轮动矩阵热力图） */
.period-matrix-chart {
  width: 100%;
  height: 720px;
}

/* 中轴零线：净流入（左）/ 净流出（右）分界 */
.zero-axis {
  position: absolute;
  top: 6px;
  bottom: 6px;
  left: 50%;
  border-left: 1px dashed var(--el-border-color-dark, #cbd5e0);

  span {
    position: absolute;
    top: 4px;
    left: 7px;
    font-size: 11px;
    line-height: 1;
    color: var(--el-text-color-secondary);
    background: var(--el-bg-color);
    padding: 2px 4px;
    border-radius: 4px;
  }
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

.idx-pct {
  font-size: 14px;
  font-weight: 600;
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

.dist-up { background: var(--app-up); }
.dist-flat { background: var(--app-flat); }
.dist-down { background: var(--app-down); }

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
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
  .list-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .dash-main, .list-grid { grid-template-columns: 1fr; }
  .search-input { width: 100%; }
}
</style>

<!-- AI 分析弹窗：el-dialog teleport 到 body，样式必须为全局（非 scoped） -->
<style>
.ai-dialog .ai-body {
  padding: 4px 2px;
}
.ai-dialog .ai-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 120px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.ai-dialog .ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.ai-dialog .ai-head-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.ai-dialog .ai-score {
  flex: 1;
}
.ai-dialog .ai-score .el-progress {
  margin-bottom: 4px;
}
.ai-dialog .ai-score-txt {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ai-dialog .ai-summary {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}
.ai-dialog .ai-block {
  margin-top: 12px;
}
.ai-dialog .ai-block-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.ai-dialog .ai-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.ai-dialog .ai-list.ai-risk {
  color: #d4380d;
}
.ai-dialog .ai-table {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.ai-dialog .ai-cell {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ai-dialog .ai-cell-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.ai-dialog .ai-cell b {
  font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.ai-dialog .ai-cell b.up { color: #f56c6c; }
.ai-dialog .ai-cell b.down { color: #67c23a; }
@media (max-width: 640px) {
  .ai-dialog .ai-table { grid-template-columns: repeat(2, 1fr); }
}
</style>
