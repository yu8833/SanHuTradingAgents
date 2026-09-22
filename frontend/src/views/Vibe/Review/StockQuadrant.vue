<template>
  <div class="stock-quadrant-page">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ today }} · 个股趋势</h2>
          <p class="page-hero-sub">全市场个股六维四象限 · 30 日时间轴一屏看全</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 概念宽度 KPI（随时间轴当前帧联动） -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Odometer /></el-icon> 市场宽度 · {{ currentDate }}</span>
        <span v-if="data?.as_of" class="block-hint">数据更新于 {{ data.as_of }} · 共 {{ dates.length }} 个交易日</span>
      </div>
      <div class="kpi-row">
        <div class="kpi-cell">
          <div class="kpi-label">个股总数</div>
          <div class="kpi-value accent">{{ currentTotal ?? '—' }}</div>
          <div class="kpi-sub">全市场 A 股（有成交额）</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">上涨 / 下跌</div>
          <div class="kpi-value">
            <span class="up">{{ kpiUp ?? '—' }}</span><span class="kpi-sep">/</span><span class="down">{{ kpiDown ?? '—' }}</span>
          </div>
          <div class="kpi-sub">当前帧涨跌家数</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">平均涨幅</div>
          <div class="kpi-value accent" :class="clsByVal(kpiAvg, '')">{{ fmtPct(kpiAvg) }}</div>
          <div class="kpi-sub">当前帧全市场均值</div>
        </div>
      </div>
    </section>

    <!-- 时间轴 + 搜索 -->
    <section class="block control-panel">
      <div class="control-main">
        <div class="control-timeline">
          <div class="timeline-title">
            <span class="block-title"><el-icon><Clock /></el-icon> 时间轴 · 最近 30 交易日</span>
            <span class="tl-date">{{ currentDate }}</span>
          </div>
          <div class="timeline-row">
            <el-button
              circle
              size="small"
              :type="playing ? 'warning' : 'primary'"
              :icon="playing ? VideoPause : VideoPlay"
              :disabled="dates.length < 2"
              @click="togglePlay"
            />
            <el-slider
              v-model="currentIndex"
              :min="0"
              :max="Math.max(0, dates.length - 1)"
              :show-tooltip="true"
              :format-tooltip="(v: number) => dates[v] || ''"
              class="tl-slider"
              :disabled="!dates.length"
              @change="onSeek"
            />
            <el-select v-model="playSpeed" size="small" class="tl-speed" :disabled="dates.length < 2">
              <el-option :value="3000" label="1x" />
              <el-option :value="1500" label="2x" />
              <el-option :value="750" label="4x" />
            </el-select>
          </div>
        </div>
        <div class="control-search">
          <div class="search-head">
            <span class="block-title"><el-icon><Search /></el-icon> 查找股票（代码 / 名称）</span>
            <span v-if="matchNames.length" class="block-hint">命中 {{ matchNames.length }} 只，六图同步高亮</span>
          </div>
          <div class="search-row">
            <el-input
              v-model="searchKw"
              size="small"
              clearable
              placeholder="如：600519 或 贵州茅台"
              class="search-input"
              @keyup.enter="doSearch"
              @clear="clearMatch"
            />
            <el-button size="small" type="primary" plain :icon="Search" :disabled="!searchKw.trim()" @click="doSearch">
              查 找
            </el-button>
            <el-button
              size="small"
              type="warning"
              plain
              :icon="Cpu"
              :loading="aiLoading"
              :disabled="!searchKw.trim()"
              @click="doAiAnalyze"
            >
              AI 分析
            </el-button>
            <el-button v-if="matchNames.length" size="small" @click="clearMatch">清除高亮</el-button>
          </div>
        </div>
      </div>
      <div class="panel-hint">
        拖动时间轴 6 图同步切换 · 默认停在当前交易日 · 点击圆点跳转个股详情 · 滚轮缩放
        <span v-if="!mainAvailable" class="warn-hint">当前帧主力资金数据暂不可用（外部行情域受限），资金类图表以历史帧为准</span>
      </div>
    </section>

    <!-- 六图四象限 -->
    <div v-if="mapReady" class="chart-grid">
      <section v-for="card in CARDS" :key="card.id" class="block chart-card">
        <div class="block-head">
          <span class="block-title"><el-icon><TrendCharts /></el-icon> {{ card.title }}</span>
          <span class="block-hint">{{ card.subtitle }}</span>
        </div>
        <div class="concept-chart">
          <VChart
            v-if="chartPointCount[card.id] > 0"
            :ref="(el: any) => setChartRef(card.id, el)"
            :option="chartOptions[card.id]"
            autoresize
            class="concept-chart-inner map-chart"
            @click="onChartClick"
          />
          <el-empty v-else :image-size="48" :description="isFrameLoading ? '历史帧加载中…' : (card.emptyHint || '暂无数据')" />
        </div>
        <div class="quadrant-tip">
          <span v-for="(t, i) in card.tips" :key="i" class="qt-item">
            <i class="qt-dot" :class="QT_DOT[i]" />{{ t }}
          </span>
        </div>
      </section>
    </div>
    <el-empty v-else :image-size="64" :description="loading ? '数据聚合中… 首次加载约需 10-40 秒，请稍候' : '暂无数据，请刷新重试'" />

    <!-- AI 分析结果弹窗 -->
    <el-dialog v-model="aiDialog" :title="aiDialogTitle" width="640px" class="ai-dialog" :close-on-click-modal="false">
      <div v-if="aiLoading" class="ai-body ai-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在基于该股在个股趋势中的数据生成操作结论…</span>
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
              <span
                v-for="t in aiResult.data.recent_trend"
                :key="t.date"
                class="ai-trend-item"
                :class="(t.pct ?? 0) >= 0 ? 'up' : 'down'"
              >{{ t.date.slice(5) }} {{ fmtPct(t.pct) }}</span>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, DataAnalysis, TrendCharts, Odometer, Clock, VideoPlay, VideoPause, Cpu, Loading } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { vibeApi, SQ } from '@/api/vibe'
import type { StockQuadrantSlim } from '@/api/vibe'
import { makeQuadrantOption, computeMatchPoints, type QuadrantCfg } from '@/utils/quadrant'
import { fmtPct, clsByVal } from '@/utils/format'

defineOptions({ name: 'StockQuadrant' })

echartsUse([CanvasRenderer, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent])

const QT_DOT = ['qt-red', 'qt-yellow', 'qt-blue', 'qt-green'] as const

const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
const loading = ref(false)
// 轻量首屏：dates + meta + 最新一帧（约 150KB gzip）；历史帧按需加载
const data = ref<StockQuadrantSlim | null>(null)
// 按需帧缓存：date → 帧（首屏仅最新帧，拖动/播放时从 /day 接口补齐）
const frameCache = ref<Record<string, Record<string, number[]>>>({})
const loadingFrames = ref<Set<string>>(new Set())

// ── 六图配置：xKey/yKey 对齐帧 8 元组（utils/quadrant 里的 SQ 索引） ──
const CARDS: (QuadrantCfg & { subtitle: string })[] = [
  {
    id: 'money_pct', title: '涨跌 × 主力资金', subtitle: '强弱共振定位',
    xKey: SQ.MAIN, yKey: SQ.P, xName: '主力净流入', xUnit: '亿', yName: '涨跌幅', yUnit: '%',
    quadrants: ['强势共振', '缩量上行', '低位承接', '弱势杀跌'],
    tips: ['流入+上涨 · 强势共振', '流出+上涨 · 缩量上行', '流入+下跌 · 低位承接', '流出+下跌 · 弱势杀跌'],
    emptyHint: '该帧主力资金暂不可用（外部行情域受限），请拖动时间轴到历史交易日查看',
  },
  {
    id: 'pct_turn', title: '涨跌 × 换手率', subtitle: '量价关系',
    xKey: SQ.P, yKey: SQ.TURN, xName: '涨跌幅', xUnit: '%', yName: '换手率', yUnit: '%',
    quadrants: ['放量上攻', '放量下跌', '缩量回调', '缩量阴跌'],
    tips: ['高换手+上涨 · 抢筹', '高换手+下跌 · 出货', '低换手+上涨 · 惜售/临板', '低换手+下跌 · 阴跌'],
  },
  {
    id: 'pct_d5', title: '当日 × 5日涨跌', subtitle: '趋势确认',
    xKey: SQ.P, yKey: SQ.D5, xName: '当日涨跌幅', xUnit: '%', yName: '5日涨跌幅', yUnit: '%',
    quadrants: ['顺势加速', '高位回调', '超跌反弹', '破位加速'],
    tips: ['双强 · 顺势加速', '5日强+今日回调 · 见顶预警', '5日弱+今日反弹 · 诱多', '双弱 · 破位加速'],
  },
  {
    id: 'pct_pe', title: '涨跌 × 市盈率', subtitle: '估值动量（对数轴）',
    xKey: SQ.P, yKey: SQ.PE, xName: '涨跌幅', xUnit: '%', yName: '市盈率', logY: true,
    quadrants: ['低估上攻', '高估上攻', '高估杀跌', '低估杀跌'],
    tips: ['低PE+上涨 · 机会区', '高PE+上涨 · 雷达泡', '高PE+下跌 · 戴维斯双杀', '低PE+下跌 · 价值陷阱'],
  },
  {
    id: 'pct_mv', title: '涨跌 × 总市值', subtitle: '大小盘风格（对数轴）',
    xKey: SQ.P, yKey: SQ.MV, xName: '涨跌幅', xUnit: '%', yName: '总市值', yUnit: '亿', logY: true,
    quadrants: ['权重搭台', '题材活跃', '权重杀跌', '题材退潮'],
    tips: ['大市值+上涨 · 权重搭台', '小市值+上涨 · 题材活跃', '大市值+下跌 · 权重杀跌', '小市值+下跌 · 题材退潮'],
  },
  {
    id: 'board_money', title: '连板 × 主力资金', subtitle: '情绪周期（涨停梯队）',
    xKey: SQ.MAIN, yKey: SQ.BOARD, xName: '主力净流入', xUnit: '亿', yName: '连板高度',
    filter: (v) => (v[SQ.BOARD] || 0) >= 1,
    quadrants: ['情绪加速', '分歧退潮', '首板启动', '炸板风险'],
    tips: ['高标+流入 · 情绪加速', '高标+流出 · 分歧退潮', '首板+流入 · 启动', '首板+流出 · 炸板风险'],
    emptyHint: '该帧主力资金暂不可用（外部行情域受限），请拖动时间轴到历史交易日查看',
  },
]

// ── 时间轴 ──
const currentIndex = ref(0)
const playing = ref(false)
// 播放节拍（ms/帧）：1x=3s / 2x=1.5s / 4x=0.75s（调慢3倍，给每帧渲染留足时间）
const playSpeed = ref(3000)
let playTimer: ReturnType<typeof setInterval> | null = null

const dates = computed(() => data.value?.dates || [])
const currentDate = computed(() => dates.value[currentIndex.value] || '')
const currentFrame = computed(() => {
  const d = currentDate.value
  return d ? (frameCache.value[d] || {}) : {}
})
const isFrameLoading = computed(() => loadingFrames.value.has(currentDate.value))

// 按需加载单日帧（去重并发；每帧约 60KB gzip）
async function ensureFrame(date: string) {
  if (!date || frameCache.value[date] || loadingFrames.value.has(date)) return
  loadingFrames.value.add(date)
  try {
    const res = await vibeApi.getStockQuadrantDay(date)
    const frame = (res as any)?.data?.frame ?? {}
    if (frame && typeof frame === 'object') {
      frameCache.value = { ...frameCache.value, [date]: frame }
    }
  } catch (e) {
    console.warn(`个股趋势帧加载失败 ${date}`, e)
  } finally {
    loadingFrames.value.delete(date)
  }
}

// 并发预取多个日期帧（分片，避免同时令过多请求，服务端/网络友好）
const PREFETCH_CONCURRENCY = 4
async function prefetchDates(batch: string[]) {
  const miss = batch.filter((d) => d && !frameCache.value[d] && !loadingFrames.value.has(d))
  for (let i = 0; i < miss.length; i += PREFETCH_CONCURRENCY) {
    await Promise.allSettled(miss.slice(i, i + PREFETCH_CONCURRENCY).map(ensureFrame))
  }
}

// 一次性补齐全部缺失帧（首次加载后 + 播放开始前调用，确保播放时无空白）
async function prefetchAll() {
  if (!dates.value.length) return
  await prefetchDates(dates.value.slice())
}

// 时间轴移动 → 确保当前帧 + 预取相邻帧（播放时衔接更顺）
watch(currentIndex, (i) => {
  const d = dates.value[i]
  if (d) ensureFrame(d)
  if (i + 1 < dates.value.length) ensureFrame(dates.value[i + 1])
  if (i - 1 >= 0) ensureFrame(dates.value[i - 1])
})

function onSeek() {
  playing.value = false
}
function togglePlay() {
  if (playing.value) {
    playing.value = false
    return
  }
  if (currentIndex.value >= dates.value.length - 1) currentIndex.value = dates.value.length - 1
  // 播放前补齐全部缺失帧（不阻塞，后台预取；播放时每帧数据已就绪无空白）
  prefetchAll()
  playing.value = true
}
watch(playing, (on) => {
  stopPlayTimer()
  if (on) {
    playTimer = setInterval(() => {
      if (currentIndex.value >= dates.value.length - 1) {
        playing.value = false
        return
      }
      currentIndex.value += 1
    }, playSpeed.value)
  }
})
watch(playSpeed, () => {
  if (playing.value) {
    stopPlayTimer()
    playTimer = setInterval(() => {
      if (currentIndex.value >= dates.value.length - 1) {
        playing.value = false
        return
      }
      currentIndex.value += 1
    }, playSpeed.value)
  }
})
function stopPlayTimer() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

// ── KPI（随当前帧） ──
const currentTotal = computed(() => (currentFrame.value ? Object.keys(currentFrame.value).length : null))
const kpiUp = computed(() => {
  const f = currentFrame.value
  if (!f) return null
  return Object.values(f).filter((v) => (v[SQ.P] || 0) > 0).length
})
const kpiDown = computed(() => {
  const f = currentFrame.value
  if (!f) return null
  return Object.values(f).filter((v) => (v[SQ.P] || 0) < 0).length
})
const kpiAvg = computed(() => {
  const f = currentFrame.value
  if (!f) return null
  const arr = Object.values(f).map((v) => v[SQ.P]).filter((x) => x != null)
  if (!arr.length) return null
  return arr.reduce((a, b) => a + b, 0) / arr.length
})

// ── 六图 option（当前帧） ──
const mainAvailable = computed(() => {
  const f = currentFrame.value
  if (!f) return false
  let cnt = 0
  const values = Object.values(f)
  for (const v of values) {
    if (v[SQ.MAIN] != null) cnt++
  }
  return values.length > 0 && cnt / values.length > 0.05
})
const mapReady = computed(() => (data.value?.dates?.length ?? 0) > 0)

const chartOptions = computed<Record<string, EChartsOption>>(() => {
  const meta = data.value?.meta || {}
  const frame = currentFrame.value
  const out: Record<string, EChartsOption> = {}
  if (!frame || !Object.keys(frame).length) return out
  for (const card of CARDS) {
    out[card.id] = makeQuadrantOption(meta, frame, card, matchSet.value)
  }
  return out
})

// 各图当前帧有效点数（用于空数据时显示提示而非空轴网格）
const chartPointCount = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const card of CARDS) {
    const opt: any = chartOptions.value[card.id]
    const s0 = opt?.series?.[0]?.data?.length ?? 0
    const s1 = opt?.series?.[1]?.data?.length ?? 0
    out[card.id] = (s0 as number) + (s1 as number)
  }
  return out
})

// ── 多图实例与跨图闪烁 ──
const charts: Record<string, any> = {}
function setChartRef(id: string, el: any) {
  charts[id] = el?.getInstance?.() ?? null
}

const searchKw = ref('')
const matchNames = ref<string[]>([])
const matchSet = computed(() => new Set(matchNames.value))
let blinkTimer: ReturnType<typeof setInterval> | null = null
let blinkOn = false

const matchPoints = computed(() => {
  if (!matchSet.value.size) return []
  const frame = currentFrame.value
  if (!frame) return []
  const pts: { chartId: string; seriesIndex: number; dataIndex: number }[] = []
  for (const card of CARDS) {
    for (const p of computeMatchPoints(frame, card, matchSet.value)) {
      pts.push({ chartId: card.id, seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
    }
  }
  return pts
})

function applyBlink() {
  blinkOn = !blinkOn
  dispatchMatch(blinkOn ? 'highlight' : 'downplay')
}
function startBlink() {
  stopBlink()
  blinkOn = true
  applyBlink()
  blinkTimer = setInterval(applyBlink, 550)
}
function stopBlink() {
  if (blinkTimer) {
    clearInterval(blinkTimer)
    blinkTimer = null
  }
}
function clearMatch() {
  stopBlink()
  downplayAll()
  matchNames.value = []
}
function downplayAll() {
  dispatchMatch('downplay')
}
// 对所有命中点统一派发 highlight/downplay（命中点已在各图顶层系列，seriesIndex/dataIndex 由 computeMatchPoints 对齐）
function dispatchMatch(type: 'highlight' | 'downplay') {
  for (const p of matchPoints.value) {
    const target = charts[p.chartId]
    if (!target) continue
    target.dispatchAction({ type, seriesIndex: p.seriesIndex, dataIndex: p.dataIndex })
  }
}
function doSearch() {
  const kw = searchKw.value.trim()
  if (!kw) {
    clearMatch()
    return
  }
  const meta = data.value?.meta || {}
  const isNum = /^\d+$/.test(kw) && kw.length >= 2
  const hits: string[] = []
  if (isNum) {
    // 数字输入 → 代码前缀匹配（覆盖沪深京全部 6 位代码）
    for (const code of Object.keys(meta)) {
      if (code.startsWith(kw)) hits.push(code)
    }
  } else {
    // 中文/其它 → 名称包含匹配
    for (const [code, m] of Object.entries(meta)) {
      if (m.name.includes(kw)) hits.push(code)
    }
  }
  if (!hits.length) {
    clearMatch()
    ElMessage.warning(`未找到与「${kw}」匹配的股票`)
    return
  }
  if (hits.length > 200) hits.length = 200
  stopBlink()
  matchNames.value = hits
  // 命中但当前帧无成交数据（停牌/尚未开盘/当日帧缺失）→ 提示；
  // matchNames 已记录，blink 保持运行，拖动时间轴到含该股的交易日时自动高亮
  if (!hits.some((c) => c in currentFrame.value)) {
    ElMessage.warning(`命中「${kw}」在当前交易日帧无成交数据（可能停牌/尚未开盘），可拖动时间轴到其他交易日查看高亮`)
  }
  startBlink()
}

// ── AI 分析：基于个股趋势帧数据的操作结论 ──
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
  return r ? `AI 分析 · ${r.name}（${r.code}）` : 'AI 分析'
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

async function doAiAnalyze() {
  const kw = searchKw.value.trim()
  if (!kw) return
  const meta = data.value?.meta || {}
  const isNum = /^\d+$/.test(kw) && kw.length >= 2
  const hits: string[] = isNum
    ? Object.keys(meta).filter((c) => c.startsWith(kw))
    : (Object.entries(meta) as [string, { name: string }][])
        .filter(([, m]) => m.name.includes(kw))
        .map(([c]) => c)
  if (!hits.length) {
    ElMessage.warning(`未找到与「${kw}」匹配的股票`)
    return
  }
  if (hits.length > 1) {
    ElMessage.warning(`「${kw}」匹配到 ${hits.length} 只股票，请输入完整代码或名称后再分析`)
    return
  }
  const code = hits[0]
  aiError.value = ''
  aiResult.value = null
  aiDialog.value = true
  aiLoading.value = true
  try {
    const res = await vibeApi.getStockQuadrantAiAnalysis(code)
    aiResult.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('AI 分析请求失败', e)
    aiError.value = 'AI 分析请求失败，请稍后重试'
  } finally {
    aiLoading.value = false
  }
}

// ── 点击跳转个股详情 / 数据加载 ──
function onChartClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.code ?? e?.data?.name
  if (!code) return
  window.open(`/stocks/${code}`, '_blank', 'noopener')
}

async function loadAll() {
  loading.value = true
  try {
    // 首屏走轻量接口（约 150KB gzip，秒开）；历史帧拖动/播放时按需加载
    const res = await vibeApi.getStockQuadrantSlim()
    const slim = (res as any)?.data ?? null
    data.value = slim
    const datesArr = slim?.dates || []
    const latest = datesArr[datesArr.length - 1] || ''
    frameCache.value = latest && slim?.frame ? { [latest]: slim.frame } : {}
    currentIndex.value = Math.max(0, datesArr.length - 1)
    // 静默补齐全部历史帧：首次进入即后台预取（分片并发），播放/拖动时全缓存命中零空白
    prefetchAll()
  } catch (e) {
    console.error('加载个股趋势失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAll()
})
onBeforeUnmount(() => {
  stopPlayTimer()
  stopBlink()
  downplayAll()
})
</script>

<style scoped lang="scss">
.stock-quadrant-page {
  .block {
    margin-bottom: 16px;
    padding: 16px;
    background: var(--el-bg-color);
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);

    .block-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;

      .block-title {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 15px;
        font-weight: 600;
      }

      .block-hint {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .kpi-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    .kpi-cell {
      padding: 12px 16px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border: 1px solid var(--el-border-color-lighter);

      .kpi-label {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }

      .kpi-value {
        margin: 6px 0;
        font-size: 22px;
        font-weight: 600;

        .kpi-sep {
          margin: 0 6px;
          color: var(--el-text-color-placeholder);
          font-weight: 400;
        }
      }

      .kpi-sub {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .control-panel {
    .control-main {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;

      .timeline-title,
      .search-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;

        .tl-date {
          font-size: 13px;
          font-weight: 600;
          color: var(--el-color-primary);
        }
      }

      .timeline-row {
        display: flex;
        align-items: center;
        gap: 12px;

        .tl-slider {
          flex: 1;
        }
        .tl-speed {
          width: 76px;
        }
        .search-input {
          width: 220px;
        }
      }

      .search-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }
    }

    .panel-hint {
      margin-top: 12px;
      font-size: 12px;
      color: var(--el-text-color-secondary);

      .warn-hint {
        margin-left: 10px;
        color: var(--el-color-warning);
      }
    }
  }

  .chart-grid {
    display: grid;
    // 宽屏两列/三列排布，配合时间轴一屏看全；窄屏由 media 查询折叠为单列
    grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
    gap: 16px;

    .chart-card {
      margin-bottom: 0;

      .concept-chart {
        .concept-chart-inner {
          width: 100%;
        }
        .map-chart {
          height: 440px;
        }
      }
    }
  }

  .quadrant-tip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 18px;
    padding: 10px 12px;
    margin-top: 10px;
    border-radius: 8px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-lighter);

    .qt-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
      white-space: nowrap;
    }

    .qt-dot {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      display: inline-block;
    }
    .qt-red { background: #fbe0e0; }
    .qt-yellow { background: #fdf3d1; }
    .qt-blue { background: #e3f0fd; }
    .qt-green { background: #e8f7e2; }
  }

  .accent {
    color: var(--el-color-warning);
  }
}

// AI 分析弹窗
.ai-dialog {
  .ai-body {
    padding: 4px 2px;
  }
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
    .ai-head-tags {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .ai-score {
      flex: 1;
      .el-progress {
        margin-bottom: 4px;
      }
      .ai-score-txt {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
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
    .ai-block-title {
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 6px;
    }
    .ai-list {
      margin: 0;
      padding-left: 18px;
      font-size: 12.5px;
      line-height: 1.9;
      color: var(--el-text-color-regular);
      &.ai-risk {
        color: #d4380d;
      }
    }
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
      .ai-cell-label {
        font-size: 11px;
        color: var(--el-text-color-secondary);
      }
      b {
        font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
        font-size: 14px;
        color: var(--el-text-color-primary);
        &.up { color: #f56c6c; }
        &.down { color: #67c23a; }
      }
    }
  }
  .ai-trend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    .ai-trend-item {
      font-size: 11.5px;
      padding: 3px 8px;
      border-radius: 6px;
      background: var(--el-fill-color-light);
      font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
      &.up { color: #f56c6c; }
      &.down { color: #67c23a; }
    }
  }
}

@media (max-width: 1100px) {
  .control-main {
    grid-template-columns: 1fr !important;
  }
  .chart-grid {
    grid-template-columns: 1fr !important;
  }
}
</style>