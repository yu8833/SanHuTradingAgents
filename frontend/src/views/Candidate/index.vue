<template>
  <div class="candidate-page app-page">
    <!-- 顶部横幅：三步主线 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">股票筛选</h2>
          <p class="page-hero-sub">① 选行业（与趋势分析同口径） → ② 看候选（三买三卖） → ③ 操作（自选 / AI 分析）</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span v-if="asOfText" class="page-hero-tag">
          <el-icon :size="14"><Calendar /></el-icon> {{ asOfText }}
        </span>
        <el-button :icon="Refresh" :loading="refreshingAll" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <!-- ① 行业定位：全部同花顺行业（与趋势分析-行业全景一致），搜索或点击选中 -->
    <section class="flow-block">
      <div class="flow-head">
        <span class="flow-step">①</span>
        <div class="flow-title">
          选择行业
          <span class="flow-sub">与「趋势分析-行业全景」同口径（{{ sectorTotal }} 个同花顺行业）{{ marketDate ? ' · ' + marketDate : '' }}</span>
        </div>
        <div class="flow-actions">
          <el-input
            v-model="sectorKw"
            size="small"
            clearable
            placeholder="搜索行业，如：化学制品 / 白酒 / 半导体"
            class="sector-search"
            @input="filterSectors"
            @clear="filterSectors"
          />
          <el-button size="small" :type="selectedSector ? 'default' : 'primary'" @click="clearSelectedSector">
            {{ selectedSector ? `当前：${selectedSector.name}` : '默认：全部行业三买 TOP' }}
          </el-button>
        </div>
      </div>

      <!-- 行业 chip 长廊 -->
      <div class="sector-chips" v-loading="sectorLoading">
        <button
          v-for="s in visibleSectors"
          :key="s.name"
          class="sector-chip"
          :class="[chipCls(s), { active: selectedSector?.name === s.name }]"
          @click="pickSector(s)"
        >
          <span class="sc-name">{{ s.name }}</span>
          <span class="sc-pct" :class="(Number(s.pct) || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(s.pct) }}</span>
        </button>
        <el-empty v-if="!sectorLoading && !visibleSectors.length" :image-size="48" description="未找到匹配行业" />
      </div>
    </section>

    <!-- ② 候选股：选中行业的候选（三买三卖） + 质量轴 -->
    <section ref="stockSection" class="flow-block">
      <div class="flow-head">
        <span class="flow-step">②</span>
        <div class="flow-title">
          候选个股
          <span class="flow-sub">{{ selectedSector ? `行业：${selectedSector.name}` : '全部行业各行业三买 TOP' }} · 三买三卖择时信号</span>
        </div>
        <div class="flow-actions signal-filter">
          <el-radio-group v-model="signalFilter" size="small">
            <el-radio-button value="buy">三买 {{ signalStats.buy }}</el-radio-button>
            <el-radio-button value="all">全部 {{ signalStats.all }}</el-radio-button>
            <el-radio-button value="B1">左侧 {{ signalStats.B1 }}</el-radio-button>
            <el-radio-button value="B2">突破 {{ signalStats.B2 }}</el-radio-button>
            <el-radio-button value="B3">回踩 {{ signalStats.B3 }}</el-radio-button>
            <el-radio-button value="S1">加速卖 {{ signalStats.S1 }}</el-radio-button>
            <el-radio-button value="S2">跌破卖 {{ signalStats.S2 }}</el-radio-button>
            <el-radio-button value="S3">清仓卖 {{ signalStats.S3 }}</el-radio-button>
          </el-radio-group>
          <el-button size="small" :icon="Refresh" :loading="stockLoading" @click="loadCandidates">计算候选</el-button>
        </div>
      </div>

      <!-- 动量 × ROE 质量轴 -->
      <div class="panel quality-panel">
        <div class="panel-title">动量 × ROE（质量轴 · 气泡大小=市值，颜色=当日涨跌）</div>
        <div v-if="scatterData.length > 1">
          <v-chart class="chart chart--scatter" :option="scatterOption" autoresize />
        </div>
        <el-empty v-else :image-size="48" description="暂无候选个股（可切换行业或稍后再看）" />
        <div class="panel-tip">右上角 = 高动量 + 高 ROE 的质量优等生；下方表格点击行可快速加入自选或 AI 分析</div>
      </div>

      <div class="stocks-hint">
        {{ stocksHint }} · {{ signalFilter === 'buy' ? '仅三买' : signalFilter === 'all' ? '三买三卖' : signalFilter }} · 显示 {{ filteredCandidates.length }} 只
        <span class="goto-trend">
          <router-link to="/vibe/review/trend-analysis">行业资金/象限详情 → 趋势分析</router-link>
        </span>
      </div>
      <div class="table-scroll">
        <el-table
          :data="filteredCandidates"
          v-loading="stockLoading"
          stripe
          :empty-text="emptyText"
          class="candidate-table app-table app-table--trades"
          @row-click="onRowClick"
        >
          <el-table-column prop="code" label="代码" width="90">
            <template #default="{ row }">
              <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code" @click.stop>{{ row.code }}</router-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="110">
            <template #default="{ row }">
              <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name" @click.stop>{{ row.name }}</router-link>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" width="92" align="right" sortable :sort-method="(a, b) => (a.pct_chg||0) - (b.pct_chg||0)">
            <template #default="{ row }">
              <span :class="(row.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtPctF(row.pct_chg) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="择时信号" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="signalTagType(row.signal_type)" size="small" effect="plain">{{ row.signal_label || row.signal_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="趋势象限" width="105">
            <template #default="{ row }">
              <span v-if="trendTagOf(row.code)" class="trend-tag" :class="trendTagOf(row.code)!.cls">
                <i class="tt-dot" />{{ trendTagOf(row.code)!.label }}
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="主力净流入(亿)" width="125" align="right" sortable :sort-method="(a, b) => (mainFlowOf(a.code)||0) - (mainFlowOf(b.code)||0)">
            <template #default="{ row }">
              <span v-if="mainFlowOf(row.code) != null" :class="(mainFlowOf(row.code) || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(mainFlowOf(row.code), 1) }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="20日动量" width="100" align="right" sortable :sort-method="(a, b) => (a.momentum_20d||0) - (b.momentum_20d||0)">
            <template #default="{ row }">
              <span :class="(row.momentum_20d || 0) >= 0 ? 'up' : 'down'">{{ fmtPctF(row.momentum_20d) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="5日涨跌" width="95" align="right" sortable :sort-method="(a, b) => (d5Of(a.code)||0) - (d5Of(b.code)||0)">
            <template #default="{ row }">
              <span v-if="d5Of(row.code) != null" :class="(d5Of(row.code) || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(d5Of(row.code), 1) }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="ROE" width="78" align="right" sortable :sort-method="(a, b) => (a.roe||0) - (b.roe||0)">
            <template #default="{ row }">{{ fmtNum(row.roe) }}%</template>
          </el-table-column>
          <el-table-column label="操作" width="165" fixed="right" align="center">
            <template #default="{ row }">
              <el-button size="small" type="success" plain @click.stop="addFavorite(row)">✓ 自选</el-button>
              <el-button size="small" type="primary" plain :loading="aiRow?.code === row.code && aiLoading" :icon="Cpu" @click.stop="doAiAnalyze(row)">AI 分析</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <!-- AI 分析结果弹窗（复用个股趋势的单股 AI 操作结论） -->
    <el-dialog v-model="aiDialog" :title="aiDialogTitle" width="640px" class="ai-dialog" :close-on-click-modal="false">
      <div v-if="aiLoading" class="ai-body ai-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在基于四维信号（趋势象限/择时/ΔG/预警）+ 个股趋势帧解读一致性…</span>
      </div>
      <el-alert v-else-if="aiError" :title="aiError" type="error" show-icon :closable="false" class="ai-body" />
      <el-empty v-else-if="aiResult && !aiResult.found" :description="aiResult.message || '未找到该股数据'" />
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

          <!-- 维度一致性（融合改造核心：四维共振/背离解读） -->
          <div v-if="aiResult.consistency" class="ai-block consistency-block">
            <div class="ai-block-title">
              维度一致性
              <span class="consistency-tag" :class="'cs-' + aiResult.consistency">{{ aiResult.consistency_label }}</span>
              <span class="consistency-engine">{{ aiResult.engine === 'llm' ? 'LLM 解读' : '规则判定' }}</span>
            </div>
            <p v-if="aiResult.consistency_summary" class="ai-summary cs-summary">{{ aiResult.consistency_summary }}</p>
            <div v-if="aiResult.dimensions?.length" class="cs-grid">
              <div
                v-for="(d, i) in aiResult.dimensions"
                :key="i"
                class="cs-cell"
                :class="d.support > 0 ? 'cs-up' : (d.support < 0 ? 'cs-down' : 'cs-flat')"
              >
                <div class="cs-head">
                  <span class="cs-name">{{ d.name }}</span>
                  <span class="cs-flag">{{ d.support > 0 ? '偏多' : (d.support < 0 ? '偏空' : '中性') }}</span>
                </div>
                <div class="cs-value">{{ d.value || '—' }}</div>
                <div class="cs-view">{{ d.view }}</div>
              </div>
            </div>
            <div v-if="aiResult.conflicts?.length" class="cs-conflicts">
              <div v-for="(c, i) in aiResult.conflicts" :key="'cf' + i" class="cs-conflict">{{ c }}</div>
            </div>
          </div>

          <p class="ai-summary">{{ aiResult.summary }}</p>
          <div v-if="aiResult.reasons?.length" class="ai-block">
            <div class="ai-block-title">判断要点</div>
            <ul class="ai-list"><li v-for="(r, i) in aiResult.reasons" :key="'r' + i">{{ r }}</li></ul>
          </div>
          <div v-if="aiResult.risks?.length" class="ai-block">
            <div class="ai-block-title">风险提示</div>
            <ul class="ai-list ai-risk"><li v-for="(r, i) in aiResult.risks" :key="'k' + i">{{ r }}</li></ul>
          </div>
          <div class="ai-block">
            <div class="ai-block-title">今日数据（个股趋势帧 · {{ aiResult.as_of }}）</div>
            <div class="ai-table">
              <div v-for="cell in aiTodayCells" :key="cell.label" class="ai-cell">
                <span class="ai-cell-label">{{ cell.label }}</span>
                <b :class="cell.cls">{{ cell.text }}</b>
              </div>
            </div>
          </div>
          <div v-if="aiResult.data?.recent_trend?.length" class="ai-block">
            <div class="ai-block-title">近期走势（最近 {{ aiResult.data.recent_trend.length }} 个交易日）</div>
            <div class="ai-trend">
              <span v-for="t in aiResult.data.recent_trend" :key="t.date" class="ai-trend-item" :class="(t.pct ?? 0) >= 0 ? 'up' : 'down'">
                {{ t.date.slice(5) }} {{ fmtPct(t.pct) }}
              </span>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Aim, Calendar, Cpu, Loading } from '@element-plus/icons-vue'
import { candidateApi, type CandidateStock } from '@/api/candidate'
import { vibeApi, SQ } from '@/api/vibe'
import {
  fmtNum,
  fmtPct,
  fmtPctFromFraction,
  fmtSigned as fmtSign,
} from '@/utils/format'
/** 候选股/动量等"小数"口径（0.0123 → +1.23%）；趋势帧/行业口径用 fmtPct（百分数） */
const fmtPctF = fmtPctFromFraction
import { use as echartsUse } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

defineOptions({ name: 'CandidateScreening' })

echartsUse([ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent, CanvasRenderer])

/* ================= ① 行业定位：同花顺行业（与趋势分析-行业全景同口径） ================= */
const sectorLoading = ref(false)
const sectors = ref<Array<{ name: string; pct: number | null; net: number | null }>>([])
const sectorKw = ref('')
const sectorTotal = computed(() => sectors.value.length)
const marketDate = ref('')
const filteredSectors = computed(() => {
  const kw = sectorKw.value.trim()
  if (!kw) return sectors.value
  return sectors.value.filter(s => s.name.includes(kw))
})
const visibleSectors = computed(() => (sectorKw.value.trim() ? filteredSectors.value : sectors.value))
const asOfText = computed(() => (marketDate.value ? `数据日 ${marketDate.value}` : ''))

/** 行业 chip 红涨绿跌（净额为负绿涨无所谓，按涨跌幅） */
function chipCls(s: { name: string; pct: number | null }) {
  return (Number(s.pct) || 0) >= 0 ? 'chip-up' : 'chip-down'
}
async function loadSectors() {
  sectorLoading.value = true
  try {
    const res = await vibeApi.getMarketOverview()
    const data = (res as any)?.data ?? null
    sectors.value = (data?.sectors || []).map((s: any) => ({
      name: String(s.name || ''),
      pct: Number(s.pct) ?? null,
      net: s.net != null ? Number(s.net) : null,
    }))
    marketDate.value = String(data?.updated || '').slice(0, 10)
  } catch (e) {
    console.warn('加载行业列表失败', e)
    sectors.value = []
  } finally {
    sectorLoading.value = false
  }
}
function filterSectors() {}

/* ================= ② 候选个股：三买三卖 ================= */
const selectedSector = ref<{ name: string } | null>(null)
const candidates = ref<CandidateStock[]>([])
const limit = 30
const stockSection = ref<HTMLElement | null>(null)
const signalFilter = ref<'all' | 'buy' | 'B1' | 'B2' | 'B3' | 'S1' | 'S2' | 'S3'>('buy')
const stockLoading = ref(false)
const refreshingAll = ref(false)

const stocksHint = computed(() =>
  selectedSector.value
    ? `行业 ${selectedSector.value.name} · top ${limit}`
    : '全市场各行业 · 每行业 top 5 · 全为三买信号'
)
const emptyText = computed(() =>
  selectedSector.value
    ? `行业「${selectedSector.value.name}」当前无三买信号（可切换行业，或切「全部」查看三买三卖）`
    : '市场当前无三买买入信号（可切换行业，或稍后再看）'
)

// 信号过滤：buy=仅三买（B1/B2/B3）/ all=全部 / 具体信号
const filteredCandidates = computed(() => {
  const f = signalFilter.value
  if (f === 'all') return candidates.value
  if (f === 'buy') return candidates.value.filter((r) => (r.signal_type || '').startsWith('B'))
  return candidates.value.filter((r) => r.signal_type === f)
})
const signalStats = computed(() => {
  const s: Record<string, number> = { all: candidates.value.length, buy: 0, B1: 0, B2: 0, B3: 0, S1: 0, S2: 0, S3: 0 }
  for (const r of candidates.value) {
    if (r.signal_type && s[r.signal_type] !== undefined) s[r.signal_type]++
    if (r.signal_type && r.signal_type.startsWith('B')) s.buy++
  }
  return s
})

/** 选中行业 → 加载候选 */
function pickSector(s: { name: string }) {
  selectedSector.value = s
  loadCandidates()
  nextTick(() => stockSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}
function clearSelectedSector() {
  selectedSector.value = null
  loadCandidates()
}

async function loadCandidates() {
  stockLoading.value = true
  try {
    if (selectedSector.value) {
      const res = await candidateApi.stocks(selectedSector.value.name, limit)
      candidates.value = res.data?.items || []
    } else {
      const res = await candidateApi.stocksOverview(10, 5)
      candidates.value = res.data?.items || []
    }
  } catch (e) {
    ElMessage.error('计算候选个股失败')
  } finally {
    stockLoading.value = false
  }
}

/* ================= 个股趋势帧 join（趋势列/象限标签/散点） ================= */
const trendByCode = ref<Record<string, number[]>>({})
function norm(c: string): string {
  return String(c).replace(/\D/g, '')
}
const mainFlowOf = (code: string) => {
  const v = trendByCode.value[norm(code)]
  return v ? v[SQ.MAIN] : null
}
const d5Of = (code: string) => {
  const v = trendByCode.value[norm(code)]
  return v ? v[SQ.D5] : null
}
function trendTagOf(code: string) {
  const v = trendByCode.value[norm(code)]
  if (!v) return null
  const p = v[SQ.P]
  const m = v[SQ.MAIN]
  if (p == null || m == null) return null
  if (m >= 0 && p >= 0) return { label: '强势共振', cls: 'tq-red' }
  if (m < 0 && p >= 0) return { label: '缩量上行', cls: 'tq-yellow' }
  if (m >= 0 && p < 0) return { label: '低位承接', cls: 'tq-blue' }
  return { label: '弱势杀跌', cls: 'tq-green' }
}

/** 候选股趋势帧（最新交易日）填充 trendByCode */
async function loadTrendSlim() {
  try {
    const res = await vibeApi.getStockQuadrantSlim()
    const data = (res as any)?.data ?? null
    const frame = data?.frame || {}
    const out: Record<string, number[]> = {}
    for (const [code, v] of Object.entries(frame)) out[norm(String(code))] = v as number[]
    trendByCode.value = out
  } catch (e) {
    console.warn('加载个股趋势帧失败', e)
  }
}

/* ================= 动量 × ROE 质量轴 ================= */
const scatterData = computed(() =>
  filteredCandidates.value
    .filter((r) => r.momentum_20d != null && r.roe != null)
    .map((r) => ({
      name: r.name || r.code,
      code: r.code,
      momentum: Number(r.momentum_20d),
      roe: Number(r.roe),
      mv: Number(r.total_mv || 0),
      pct: Number(r.pct_chg || 0),
    }))
)
const scatterOption = computed(() => {
  const pts = scatterData.value
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const d = p?.data
        if (!d) return ''
        const v = d.value || []
        return `${d.name}（${d.code}）<br/>动量：${fmtPctF(v[0])}<br/>ROE：${fmtNum(v[1])}%<br/>市值：${fmtNum(v[2])}亿<br/>涨跌幅：${fmtPctF(v[3])}`
      },
    },
    grid: { left: 56, right: 24, top: 24, bottom: 40 },
    xAxis: {
      type: 'value',
      name: '20日动量(%)',
      nameLocation: 'middle',
      nameGap: 24,
      axisLabel: { formatter: (v: number) => fmtPctF(v), fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } },
    },
    yAxis: { type: 'value', name: 'ROE(%)', axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    series: [{
      type: 'scatter',
      symbolSize: (d: any) => Math.max(8, Math.min(42, Math.sqrt(d[2] || 1) * 1.2)),
      itemStyle: { opacity: 0.75 },
      data: pts.map((p) => ({
        name: p.name,
        code: p.code,
        value: [p.momentum, p.roe, p.mv, p.pct],
        itemStyle: { color: p.pct >= 0 ? '#f56c6c' : '#67c23a' },
      })),
      markLine: { symbol: 'none', lineStyle: { type: 'dashed', color: '#909399' }, label: { show: false }, data: [{ xAxis: 0 }] },
    }],
  }
})

/* ================= AI 分析 ================= */
const aiDialog = ref(false)
const aiLoading = ref(false)
const aiError = ref('')
const aiResult = ref<any>(null)
const aiRow = ref<CandidateStock | null>(null)
const AI_ACTION_COLOR: Record<string, string> = {
  strong_buy: '#f56c6c', buy: '#e6a23c', hold: '#409eff', wait: '#909399', reduce: '#67c23a', avoid: '#13a8a8',
}
const aiActionColor = computed(() => AI_ACTION_COLOR[aiResult.value?.action as string] || '#909399')
const aiDialogTitle = computed(() => (aiResult.value ? `AI 分析 · ${aiResult.value.name}（${aiResult.value.code}）` : 'AI 分析'))
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
  { key: 'pct', label: '涨跌幅', unit: '%', sign: true },
  { key: 'amt', label: '成交额', unit: '亿' },
  { key: 'turn', label: '换手率', unit: '%' },
  { key: 'pe', label: '市盈率' },
  { key: 'mv', label: '总市值', unit: '亿' },
  { key: 'main', label: '主力净流入', unit: '亿', sign: true },
  { key: 'board', label: '连板', render: (v: any) => (v == null ? '—' : v === 0 ? '未涨停' : `${v} 板`) },
  { key: 'd5', label: '5日涨跌', unit: '%', sign: true },
]
const aiTodayCells = computed(() => {
  const today = aiResult.value?.data?.today ?? {}
  return AI_TODAY_DEF.map((d) => {
    const raw = today[d.key]
    let text: string
    let cls = ''
    if (d.render) {
      text = d.render(raw)
      cls = (raw != null && raw > 0) ? 'up' : (raw != null && raw < 0 ? 'down' : '')
    } else {
      text = fmtN(raw, d.unit || '', !!d.sign)
      cls = (raw != null && raw > 0) ? 'up' : (raw != null && raw < 0 ? 'down' : '')
    }
    return { label: d.label, text, cls }
  })
})
async function doAiAnalyze(row: CandidateStock) {
  aiRow.value = row
  aiError.value = ''
  aiResult.value = null
  aiDialog.value = true
  aiLoading.value = true
  try {
    const res = await vibeApi.getStockQuadrantAiConsistency({
      code: row.code,
      name: row.name,
      industry: row.industry || '',
      signal_type: row.signal_type || '',
      signal_label: row.signal_label || '',
      dg_quadrant: row.dg_quadrant || '',
      aux_warnings: row.aux_warnings || [],
    })
    aiResult.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('AI 分析请求失败', e)
    aiError.value = 'AI 分析请求失败，请稍后重试'
  } finally {
    aiLoading.value = false
  }
}

/* ================= 交互 ================= */
function signalTagType(s: string) {
  if (s.startsWith('B')) return 'danger'
  if (s.startsWith('S')) return 'success'
  return 'info'
}
function onRowClick(row: CandidateStock) {
  window.open(`/stocks/${row.code}`, '_blank', 'noopener')
}
async function addFavorite(row: CandidateStock) {
  try {
    await candidateApi.addFavorite(row.code, row.name)
    ElMessage.success(`已将 ${row.name} 加入自选`)
  } catch (e) {
    ElMessage.error('加入自选失败')
  }
}

async function refreshAll() {
  refreshingAll.value = true
  try {
    await Promise.allSettled([loadSectors(), loadCandidates(), loadTrendSlim()])
  } finally {
    refreshingAll.value = false
  }
}

// 首次进入：并行加载行业 + 默认候选
onMounted(async () => {
  await Promise.allSettled([loadSectors(), loadCandidates(), loadTrendSlim()])
  nextTick(() => stockSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
})
</script>

<style scoped lang="scss">
.candidate-page {
  /* 页面容器交给全局 .app-page */
}

/* —— 步骤条通用 —— */
.flow-block {
  margin-bottom: 20px;
  padding: 18px 20px;
  background: var(--el-bg-color);
  border-radius: var(--app-radius-lg, 12px);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow, none);
}
.flow-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.flow-step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: linear-gradient(120deg, #1e3a5f, #2b6cb0);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  flex-shrink: 0;
}
.flow-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.flow-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.flow-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-wrap: wrap;
}
.signal-filter .el-radio-button__inner {
  padding: 4px 10px;
  font-size: 12px;
}

/* —— ① 行业 chips —— */
.sector-search {
  width: 260px;
}
.sector-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0;
  min-height: 40px;
}
.sector-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-primary);
  cursor: pointer;
  transition: box-shadow .15s, transform .15s;

  &:hover {
    box-shadow: var(--app-shadow-light, 0 2px 8px rgba(30,58,95,.12));
    transform: translateY(-1px);
  }
  &.active {
    border-color: var(--el-color-primary);
    color: var(--el-color-primary);
    background: var(--el-color-primary-light-9, #ecf5ff);
    font-weight: 600;
  }
  .sc-name { font-size: 12.5px; font-weight: 500; }
  .sc-pct { font-size: 12px; font-weight: 600; }
  .sc-pct.up { color: #f56c6c; }
  .sc-pct.down { color: #67c23a; }
}

/* —— ② 候选 —— */
.panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  padding: 12px 14px;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.panel-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.chart--scatter { height: 300px; }
.stocks-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 12px 0 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.goto-trend a {
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 12px;
}
.candidate-table {
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--el-box-shadow-light);
  border: 1px solid var(--el-border-color-light);
}
.muted { color: var(--el-text-color-secondary); }
.stock-code, .stock-name { text-decoration: none; }
.stock-code { font-family: var(--app-font-mono); }

/* —— 个股趋势象限标签 —— */
.trend-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  .tt-dot { width: 8px; height: 8px; border-radius: 3px; display: inline-block; }
}
.tq-red { background: #fbe0e0; color: #c0392b; .tt-dot { background: #e57373; } }
.tq-yellow { background: #fdf3d1; color: #b7791f; .tt-dot { background: #ecc94b; } }
.tq-blue { background: #e3f0fd; color: #2b6cb0; .tt-dot { background: #63b3ed; } }
.tq-green { background: #e8f7e2; color: #2f855a; .tt-dot { background: #68d391; } }

.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.table-scroll::-webkit-scrollbar { height: 6px; }
.table-scroll::-webkit-scrollbar-thumb { background: var(--el-border-color); border-radius: 3px; }

/* —— AI 弹窗 —— */
.ai-dialog {
  .ai-body { padding: 4px 2px; }
  .ai-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 120px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
  .ai-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12px;
    .ai-head-tags { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .ai-score {
      flex: 1;
      .el-progress { margin-bottom: 4px; }
      .ai-score-txt { font-size: 12px; color: var(--el-text-color-secondary); }
    }
  }
  .ai-summary {
    margin: 0 0 12px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--el-fill-color-light);
    font-size: 13px;
    line-height: 1.7;
    color: var(--el-text-color-primary);
  }
  .ai-block {
    margin-top: 12px;
    .ai-block-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
    .ai-list {
      margin: 0;
      padding-left: 18px;
      font-size: 12.5px;
      line-height: 1.9;
      color: var(--el-text-color-regular);
      &.ai-risk { color: #d4380d; }
    }
  }
  .consistency-block {
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--el-fill-color-light);
    border: 1px solid var(--el-border-color-lighter);
    .ai-block-title { display: flex; align-items: center; gap: 8px; }
    .consistency-tag {
      padding: 1px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      &.cs-align { background: rgba(103, 194, 58, .14); color: #2f855a; border: 1px solid rgba(103, 194, 58, .35); }
      &.cs-partial { background: rgba(230, 162, 60, .14); color: #b7791f; border: 1px solid rgba(230, 162, 60, .35); }
      &.cs-diverg { background: rgba(245, 108, 108, .14); color: #c0392b; border: 1px solid rgba(245, 108, 108, .35); }
      &.cs-neutral { background: rgba(144, 147, 153, .14); color: #606266; border: 1px solid rgba(144, 147, 153, .35); }
    }
    .consistency-engine { margin-left: auto; font-size: 11px; font-weight: 400; color: var(--el-text-color-secondary); }
    .cs-summary { margin-top: 10px; margin-bottom: 10px; }
    .cs-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .cs-cell {
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border-left: 3px solid var(--el-border-color);
      .cs-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; .cs-name { font-size: 12px; font-weight: 600; color: var(--el-text-color-primary); } .cs-flag { font-size: 11px; font-weight: 600; } }
      .cs-value { font-size: 13.5px; font-weight: 700; margin-bottom: 3px; }
      .cs-view { font-size: 11.5px; line-height: 1.6; color: var(--el-text-color-secondary); }
      &.cs-up { border-left-color: #f56c6c; .cs-flag { color: #f56c6c; } .cs-value { color: #c0392b; } }
      &.cs-down { border-left-color: #67c23a; .cs-flag { color: #67c23a; } .cs-value { color: #2f855a; } }
      &.cs-flat { border-left-color: #909399; .cs-flag { color: #909399; } }
    }
    .cs-conflicts { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; .cs-conflict { font-size: 12.5px; line-height: 1.7; color: #b7791f; background: rgba(230, 162, 60, .10); border: 1px dashed rgba(230, 162, 60, .45); border-radius: 8px; padding: 6px 10px; &::first-letter { font-weight: 700; } } }
  }
  .ai-table {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    .ai-cell {
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border: 1px solid var(--el-border-color-lighter);
      display: flex;
      flex-direction: column;
      gap: 4px;
      .ai-cell-label { font-size: 11px; color: var(--el-text-color-secondary); }
      b { font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace; font-size: 14px; color: var(--el-text-color-primary); &.up { color: #f56c6c; } &.down { color: #67c23a; } }
    }
  }
  .ai-trend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    .ai-trend-item { font-size: 11.5px; padding: 3px 8px; border-radius: 6px; background: var(--el-fill-color-light); font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace; &.up { color: #f56c6c; } &.down { color: #67c23a; } }
  }
}

/* —— 响应式 —— */
@media (max-width: 1100px) {
  .flow-actions { margin-left: 0; }
}
@media (max-width: 768px) {
  .flow-block { padding: 14px; }
  .flow-head { gap: 8px; }
  .sector-search { width: 100%; }
  .signal-filter { width: 100%; gap: 6px; }
  .signal-filter .el-radio-button__inner { padding: 4px 8px; font-size: 11px; }
  .candidate-table { font-size: 13px; }
  .table-scroll { margin: 0 -14px; padding: 0 14px; }
}
</style>
