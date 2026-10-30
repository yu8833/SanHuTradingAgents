<template>
  <div class="vibe-emotion app-page">
    <!-- 页面标题 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 短线情绪</h2>
          <p class="page-hero-sub">打板质量 / 情绪周期 / 强弱结构 · 客观公开榜单</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">更新于 {{ updatedAt }}</span>
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="refresh">
          刷新
        </el-button>
      </div>
    </div>

    <div class="emotion-content" v-loading="loading" element-loading-background="rgba(255,255,255,0.85)">

    <template v-if="emotion">
      <!-- 1. 情绪概览 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><DataLine /></el-icon> 情绪概览
          </span>
          <span class="block-hint">数据日 {{ emotion.date }} · 数字下方为较上一交易日变化</span>
        </div>
        <div class="grid grid-6">
          <el-card
            v-for="k in kpis"
            :key="k.key"
            shadow="never"
            class="count-card clickable"
            @click="openKpiDetail(k.key)"
          >
            <div class="cnt-label" :title="k.tip">{{ k.label }}</div>
            <div class="cnt-num" :class="k.tone">{{ k.value }}</div>
            <div class="cnt-sub">
              <span>{{ k.unit }}</span>
              <span v-if="k.delta != null" class="cnt-delta" :class="clsByVal(k.delta, '')">
                {{ fmtSigned(k.delta, 0) }}
              </span>
            </div>
          </el-card>
        </div>
        <div class="fund-strip">
          <div class="fund-item" title="涨停池内个股当日成交额合计">
            <span class="fund-label">涨停池成交额</span>
            <b>{{ fmtYi(amountStats.zt) }}</b><i>亿</i>
          </div>
          <div class="fund-item" title="炸板池内个股当日成交额合计，反映封板失败的资金消耗">
            <span class="fund-label">炸板池成交额</span>
            <b>{{ fmtYi(amountStats.zb) }}</b><i>亿</i>
          </div>
          <div class="fund-item" title="封板资金占比 = 涨停池成交额 ÷（涨停池 + 炸板池），越高说明打板资金越集中在最终封住的个股上">
            <span class="fund-label">封板资金占比</span>
            <b>{{ amountStats.sealShare == null ? '-' : amountStats.sealShare.toFixed(1) }}</b><i>%</i>
          </div>
          <div class="fund-item" title="连板股（2板+）平均单只成交额">
            <span class="fund-label">连板股均成交额</span>
            <b>{{ fmtYi(amountStats.lbAvg) }}</b><i>亿</i>
          </div>
        </div>
      </section>

      <!-- 2. 打板情绪比率 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><MagicStick /></el-icon> 打板情绪比率
          </span>
          <span class="block-hint">数据日 {{ emotion.date }} · 灰色数字为近 5 个交易日均值</span>
        </div>
        <div class="grid grid-3">
          <el-card shadow="never" class="ratio-card clickable" @click="openRatioDetail('seal')">
            <div class="rt-label" title="封板率 = 涨停 ÷（涨停 + 炸板），越高说明封板越坚决">封板率</div>
            <div class="rt-frac">
              <b class="frac-num up">{{ emotion.zt_count }}</b>
              <span class="frac-sep">/</span>
              <b class="frac-den">{{ attemptsCount }}</b>
              <span class="frac-eq">=</span>
              <b class="frac-result up">{{ fmtRate(emotion.seal_rate) }}</b>
            </div>
            <div class="rt-bar">
              <div class="bar-fill up" :style="{ width: rateWidth(emotion.seal_rate) }"></div>
            </div>
            <div class="rt-avg">近5日均值 {{ fmtPctFromFraction(ratioAvg.seal, 1) }}</div>
          </el-card>
          <el-card shadow="never" class="ratio-card clickable" @click="openRatioDetail('break')">
            <div class="rt-label" title="炸板率 = 炸板 ÷（涨停 + 炸板），越高说明封板承接越弱">炸板率</div>
            <div class="rt-frac">
              <b class="frac-num down">{{ emotion.zb_count }}</b>
              <span class="frac-sep">/</span>
              <b class="frac-den">{{ attemptsCount }}</b>
              <span class="frac-eq">=</span>
              <b class="frac-result down">{{ fmtRate(emotion.break_rate) }}</b>
            </div>
            <div class="rt-bar">
              <div class="bar-fill down" :style="{ width: rateWidth(emotion.break_rate) }"></div>
            </div>
            <div class="rt-avg">近5日均值 {{ fmtPctFromFraction(ratioAvg.break, 1) }}</div>
          </el-card>
          <el-card shadow="never" class="ratio-card clickable" @click="openRatioDetail('promo')">
            <div class="rt-label" title="晋级率 = 今日连板家数 ÷ 昨日涨停家数，反映打板资金接力意愿">晋级率</div>
            <div class="rt-frac">
              <b class="frac-num">{{ emotion.lianban_count }}</b>
              <span class="frac-sep">/</span>
              <b class="frac-den">{{ emotion.yzt_count }}</b>
              <span class="frac-eq">=</span>
              <b class="frac-result neutral">{{ fmtRate(emotion.promotion_rate) }}</b>
            </div>
            <div class="rt-bar">
              <div class="bar-fill neutral" :style="{ width: rateWidth(emotion.promotion_rate) }"></div>
            </div>
            <div class="rt-avg">今日连板 {{ emotion.lianban_count }} 家 ÷ 昨涨停 {{ emotion.yzt_count }} 家</div>
          </el-card>
        </div>
      </section>

      <!-- 3. 情绪周期：家数走势 + 打板质量 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><TrendCharts /></el-icon> 情绪周期 · 近 {{ history?.series?.length || 0 }} 个交易日
          </span>
          <span v-if="historyRange" class="block-hint">{{ historyRange }}</span>
          <span v-if="phase" class="phase-tag" :class="`phase-${phase.tone}`">{{ phase.label }}</span>
        </div>
        <div class="grid grid-2">
          <el-card shadow="never" class="chart-card" v-loading="historyLoading">
            <div class="chart-cap">家数走势 <span>涨停 / 炸板 / 跌停（柱）· 最高连板（右轴）</span></div>
            <VChart v-if="countChartOption" :option="countChartOption" autoresize class="chart-240" />
            <div v-else class="empty">历史情绪数据暂不可用（数据源未返回），稍后刷新重试</div>
          </el-card>
          <el-card shadow="never" class="chart-card" v-loading="historyLoading">
            <div class="chart-cap">打板质量 <span>封板率 / 炸板率（%）· 连板家数（右轴）</span></div>
            <VChart v-if="qualityChartOption" :option="qualityChartOption" autoresize class="chart-240" />
            <div v-else class="empty">历史情绪数据暂不可用</div>
          </el-card>
        </div>
        <p v-if="phase" class="phase-desc">{{ phase.desc }}</p>
      </section>

      <!-- 4. 今日 vs 近 10 日均值（同一维度双柱对比，避免百分比解读歧义） -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><DataAnalysis /></el-icon> 今日 vs 近 10 日均值
          </span>
          <span class="block-hint">红色为今日实际值，灰色为近 10 个交易日均值（不含今日）</span>
        </div>
        <el-card shadow="never" class="chart-card">
          <div v-if="compareRows.length" class="cmp-list">
            <div v-for="r in compareRows" :key="r.label" class="cmp-row">
              <div class="cmp-label">
                <span>{{ r.label }}</span>
                <i v-if="r.reverse">低者为好</i>
              </div>
              <div class="cmp-bars">
                <div class="cmp-line">
                  <span class="cmp-tag today">今日</span>
                  <div class="cmp-track"><div class="cmp-fill today" :style="{ width: r.todayW }"></div></div>
                  <b class="cmp-val">{{ r.todayText }}</b>
                </div>
                <div class="cmp-line">
                  <span class="cmp-tag avg">均值</span>
                  <div class="cmp-track"><div class="cmp-fill avg" :style="{ width: r.avgW }"></div></div>
                  <b class="cmp-val">{{ r.avgText }}</b>
                </div>
              </div>
              <span class="cmp-delta" :title="`今日较近10日均值变化 ${r.deltaText}`">{{ r.deltaText }}</span>
            </div>
          </div>
          <div v-else class="empty">历史均值数据不足，无法对比</div>
        </el-card>
      </section>

      <!-- 6. 打板生态：晋级阶梯 / 行业分布 / 连板股成交额 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Histogram /></el-icon> 打板生态
          </span>
          <span class="block-hint">数据日 {{ emotion.date }} · 晋级留存 / 行业集中度 / 连板股资金分布</span>
        </div>
        <div class="grid grid-2">
          <el-card shadow="never" class="chart-card">
            <div class="chart-cap">晋级阶梯 <span>点击长条查看明细 · 留存率 = 该档家数 ÷ 昨日涨停家数</span></div>
            <VChart
              v-if="stageOption"
              :option="stageOption"
              autoresize
              class="chart-220"
              @click="onStageClick"
            />
            <div v-else class="empty">昨日涨停池暂无数据，无法计算晋级留存</div>
            <EmotionDetailTable
              v-if="stageDetail"
              :title="stageDetail.title"
              :rows="stageDetail.rows"
              :metric="{ key: 'boards', label: '连板', suffix: '板' }"
              @close="stageSel = null"
            />
          </el-card>
          <el-card shadow="never" class="chart-card">
            <div class="chart-cap">
              行业分布
              <el-radio-group v-model="indPool" size="small" class="pool-switch">
                <el-radio-button value="zt">涨停</el-radio-button>
                <el-radio-button value="zb">炸板</el-radio-button>
                <el-radio-button value="dt">跌停</el-radio-button>
              </el-radio-group>
              <span>点击长条跳转同花顺行业板块 · 前三行业占比 {{ cr3 }}%</span>
            </div>
            <VChart
              v-if="industryOption"
              :option="industryOption"
              autoresize
              class="chart-220"
              @click="onIndustryClick"
            />
            <div v-else class="empty">该池暂无个股</div>
          </el-card>
        </div>
        <el-card shadow="never" class="chart-card chart-card--wide">
          <div class="chart-cap">
            连板股成交额 <span>颜色越深连板越高 · 共 {{ emotion.lianban_stocks.length }} 只 · 点击长条查看个股详情</span>
          </div>
          <VChart
            v-if="lianbanAmountOption"
            :option="lianbanAmountOption"
            autoresize
            :style="{ height: lianbanChartHeight }"
            @click="onLianbanClick"
          />
          <div v-else class="empty">暂无连板股</div>
        </el-card>
      </section>

      <!-- 7. 风险结构：炸板强度 / 跌停天数 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Warning /></el-icon> 风险结构
          </span>
          <span class="block-hint">炸板次数越多、连续跌停天数越长，说明分歧与补跌压力越大</span>
        </div>
        <div class="grid grid-2">
          <el-card shadow="never" class="chart-card">
            <div class="chart-cap">炸板强度 <span>点击长条查看明细 · 炸板池 {{ emotion.pools?.zb?.length || 0 }} 只</span></div>
            <VChart v-if="breakDistOption" :option="breakDistOption" autoresize class="chart-200" @click="onBreakClick" />
            <div v-else class="empty">今日无炸板个股</div>
            <EmotionDetailTable
              v-if="breakDetail"
              :title="breakDetail.title"
              :rows="breakDetail.rows"
              :metric="{ key: 'break_times', label: '炸板', suffix: '次' }"
              @close="zbSel = null"
            />
          </el-card>
          <el-card shadow="never" class="chart-card">
            <div class="chart-cap">跌停天数 <span>点击长条查看明细 · 跌停池 {{ emotion.pools?.dt?.length || 0 }} 只</span></div>
            <VChart v-if="dtDistOption" :option="dtDistOption" autoresize class="chart-200" @click="onDtClick" />
            <div v-else class="empty">今日无跌停个股</div>
            <EmotionDetailTable
              v-if="dtDetail"
              :title="dtDetail.title"
              :rows="dtDetail.rows"
              :metric="{ key: 'days', label: '连续跌停', suffix: '天' }"
              @close="dtSel = null"
            />
          </el-card>
        </div>
      </section>

      <!-- 8. 明细榜单（默认收起，避免表格堆叠） -->
      <section v-if="emotion.pools" class="block">
        <el-collapse v-model="detailOpen" class="detail-collapse">
          <el-collapse-item name="lianban">
            <template #title>
              <span class="collapse-title">连板股明细（{{ emotion.lianban_stocks.length }} 只）</span>
            </template>
            <el-table :data="emotion.lianban_stocks" stripe size="default" class="app-table app-table--ranking">
              <el-table-column label="名称 / 代码" min-width="170">
                <template #default="{ row }">
                  <div class="stock-cell">
                    <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                    <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="连板数" width="90" align="right" sortable>
                <template #default="{ row }">
                  <el-tag type="danger" effect="plain">{{ row.boards }}板</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="现价" width="100" align="right" sortable>
                <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
              </el-table-column>
              <el-table-column label="涨停%" width="100" align="right" sortable>
                <template #default="{ row }">
                  <span class="up">{{ fmtPct(row.pct) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="成交额(亿)" width="120" align="right" sortable>
                <template #default="{ row }">{{ fmtYi(row.amount) }}</template>
              </el-table-column>
              <el-table-column label="流通市值(亿)" width="130" align="right" sortable>
                <template #default="{ row }">{{ fmtYi(row.float_cap) }}</template>
              </el-table-column>
              <el-table-column label="概念" min-width="120" prop="industry" />
            </el-table>
          </el-collapse-item>

          <el-collapse-item name="pools">
            <template #title>
              <span class="collapse-title">三池清单（涨停 {{ emotion.pools.zt.length }} / 炸板 {{ emotion.pools.zb.length }} / 跌停 {{ emotion.pools.dt.length }}）</span>
            </template>
            <el-tabs v-model="poolTab" class="pool-tabs">
              <el-tab-pane :label="`涨停池 ${emotion.pools.zt.length}`" name="zt" />
              <el-tab-pane :label="`炸板池 ${emotion.pools.zb.length}`" name="zb" />
              <el-tab-pane :label="`跌停池 ${emotion.pools.dt.length}`" name="dt" />
            </el-tabs>
            <el-table :data="poolRows" stripe size="default" class="app-table app-table--ranking">
              <el-table-column label="名称 / 代码" min-width="170">
                <template #default="{ row }">
                  <div class="stock-cell">
                    <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                    <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="现价" width="100" align="right" sortable prop="price">
                <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
              </el-table-column>
              <el-table-column label="涨跌幅" width="100" align="right" sortable prop="pct">
                <template #default="{ row }">
                  <span :class="clsByVal(row.pct, '')">{{ fmtPct(row.pct) }}</span>
                </template>
              </el-table-column>
              <el-table-column v-if="poolTab === 'zt'" label="连板" width="90" align="right" sortable prop="boards">
                <template #default="{ row }">
                  <el-tag type="danger" effect="plain" size="small">{{ row.boards }}板</el-tag>
                </template>
              </el-table-column>
              <el-table-column v-if="poolTab === 'zb'" label="炸板次数" width="100" align="right" sortable prop="break_times">
                <template #default="{ row }">{{ row.break_times }} 次</template>
              </el-table-column>
              <el-table-column v-if="poolTab === 'dt'" label="连续跌停" width="100" align="right" sortable prop="days">
                <template #default="{ row }">{{ row.days }} 天</template>
              </el-table-column>
              <el-table-column label="成交额(亿)" width="120" align="right" sortable prop="amount">
                <template #default="{ row }">{{ fmtYi(row.amount) }}</template>
              </el-table-column>
              <el-table-column label="行业" min-width="120" prop="industry" />
            </el-table>
            <div v-if="!poolRows.length" class="empty">该池暂无个股</div>
          </el-collapse-item>
        </el-collapse>
      </section>

      <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>

      <!-- 明细弹窗：情绪概览 / 打板情绪比率共用 -->
      <el-dialog
        v-model="detailDialog"
        :title="detailTitle"
        width="760px"
        top="8vh"
        class="emotion-detail-dialog"
        append-to-body
        destroy-on-close
      >
        <div v-if="detailPayload" class="dialog-body">
          <p v-if="detailPayload.note" class="dialog-note">{{ detailPayload.note }}</p>
          <EmotionDetailTable
            :title="detailPayload.title"
            :rows="detailPayload.rows"
            :metric="detailPayload.metric"
            hide-head
            @close="detailDialog = false"
          />
        </div>
      </el-dialog>
    </template>

    <el-empty v-else-if="!loading" description="暂无短线情绪数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  DataLine,
  DataAnalysis,
  Refresh,
  MagicStick,
  Histogram,
  Warning,
} from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import EmotionDetailTable from './EmotionDetailTable.vue'
import {
  vibeApi,
  type ShortTermEmotion,
  type EmotionPoolRow,
  type EmotionHistory,
  type EmotionHistoryPoint,
} from '@/api/vibe'
import { fmtPrice, fmtYi, fmtPctFromFraction, fmtPct, fmtSigned, clsByVal } from '@/utils/format'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'

defineOptions({ name: 'ReviewEmotion' })

echartsUse([
  CanvasRenderer,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
])

// 标题日期：优先情绪数据日期（最新交易日）；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => emotion.value?.date || tradeDate.value || '')

// 页头「更新于」：数据获取时刻（涨停池构建时刻）
const updatedAt = computed(() => emotion.value?.updated ? formatBeijingDateTimeMinute(emotion.value.updated) : '')

const loading = ref(false)
const emotion = ref<ShortTermEmotion | null>(null)

// ── 近 10 交易日情绪序列（独立接口，不阻塞主情绪；数据源不可用时明确空态） ──
const history = ref<EmotionHistory | null>(null)
const historyLoading = ref(false)

const histSeries = computed<EmotionHistoryPoint[]>(() => history.value?.series || [])

// 上一交易日 / 均值样本（排除今日数据点，避免自己和自己比）
const prevPoint = computed<EmotionHistoryPoint | null>(() => {
  const e = emotion.value
  const before = histSeries.value.filter(p => !e || p.date < e.date)
  return before.length ? before[before.length - 1] : null
})
const avgPoints = computed(() => {
  const d = emotion.value?.date
  return histSeries.value.filter(p => !d || p.date !== d)
})
const recent5 = computed(() => avgPoints.value.slice(-5))

// 区块级数据时间：曲线区间起点 → 终点（与上方当日快照分开标注）
const historyRange = computed(() => {
  const series = histSeries.value
  if (!series.length) return ''
  const first = series[0].date
  const last = series[series.length - 1].date
  return first === last ? `数据日 ${last}` : `区间 ${first} → ${last}`
})

const axisLabel = { color: '#a0aec0', fontSize: 10 }
const splitLine = { lineStyle: { color: '#f0f4f8' } }
const TIP = {
  backgroundColor: '#fff',
  borderColor: 'rgba(45,55,72,.08)',
  borderWidth: 1,
  textStyle: { color: '#2d3748', fontSize: 12 },
  extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
}
const LEGEND = {
  top: 0,
  right: 0,
  itemWidth: 10,
  itemHeight: 10,
  textStyle: { color: '#718096', fontSize: 11 },
}

// ── 概览 KPI（含环比） ──
const kpis = computed(() => {
  const e = emotion.value
  if (!e) return []
  const p = prevPoint.value
  const d = (cur: number, prevVal?: number) => (p && prevVal != null ? cur - (prevVal as number) : null)
  return [
    { key: 'zt', label: '涨停', tip: '收盘涨停家数（东财涨停池口径）', value: e.zt_count, unit: '家', tone: 'up', delta: d(e.zt_count, p?.zt) },
    { key: 'dt', label: '跌停', tip: '收盘跌停家数（东财跌停池口径）', value: e.dt_count, unit: '家', tone: 'down', delta: d(e.dt_count, p?.dt) },
    { key: 'zb', label: '炸板', tip: '盘中触及涨停但收盘未封住的个股家数', value: e.zb_count, unit: '家', tone: 'neutral', delta: d(e.zb_count, p?.zb) },
    { key: 'lianban', label: '连板（2板+）', tip: '连续 2 个及以上交易日涨停的家数', value: e.lianban_count, unit: '家', tone: '', delta: d(e.lianban_count, p?.lianban) },
    { key: 'max', label: '最高连板', tip: '当日连板高度最高的个股连板数', value: e.max_boards, unit: '板', tone: '', delta: d(e.max_boards, p?.max_boards) },
    { key: 'yzt', label: '昨涨停', tip: '昨日涨停家数，用作今日晋级率的分母', value: e.yzt_count, unit: '家', tone: '', delta: null },
  ]
})

// ── 明细弹窗（情绪概览 / 打板情绪比率共用） ──
interface DetailMetric { key: string; label: string; suffix: string }
interface DetailPayload { title: string; note?: string; rows: any[]; metric: DetailMetric | null }

const METRIC_BOARDS: DetailMetric = { key: 'boards', label: '连板', suffix: '板' }
const METRIC_BREAK: DetailMetric = { key: 'break_times', label: '炸板', suffix: '次' }
const METRIC_DT: DetailMetric = { key: 'days', label: '连续跌停', suffix: '天' }

const detailDialog = ref(false)
const detailPayload = ref<DetailPayload | null>(null)
const detailTitle = computed(() =>
  detailPayload.value ? `${detailPayload.value.title} · ${detailPayload.value.rows.length} 只` : '明细',
)
const showDetail = (payload: DetailPayload) => {
  detailPayload.value = payload
  detailDialog.value = true
}

// 情绪概览卡片 → 对应池明细
const openKpiDetail = (key: string) => {
  const e = emotion.value
  if (!e) return
  const pools = e.pools
  if (key === 'zt') {
    showDetail({ title: '涨停池', rows: pools?.zt || [], metric: METRIC_BOARDS })
  } else if (key === 'dt') {
    showDetail({ title: '跌停池', rows: pools?.dt || [], metric: METRIC_DT })
  } else if (key === 'zb') {
    showDetail({ title: '炸板池', rows: pools?.zb || [], metric: METRIC_BREAK })
  } else if (key === 'lianban') {
    showDetail({ title: '连板股（2 板+）', rows: e.lianban_stocks || [], metric: METRIC_BOARDS })
  } else if (key === 'max') {
    const rows = (pools?.zt || []).filter(r => (Number(r.boards) || 1) === Number(e.max_boards))
    showDetail({ title: `最高连板 · ${e.max_boards} 板`, rows, metric: METRIC_BOARDS })
  } else if (key === 'yzt') {
    showDetail({
      title: '昨日涨停（今日表现）',
      note: '涨跌幅为这些个股今日的表现，用于对照晋级情况',
      rows: pools?.yzt || [],
      metric: METRIC_BOARDS,
    })
  }
}

// 打板情绪比率 → 分子个股明细（分/分母同源口径）
const attemptsCount = computed(() => (emotion.value?.zt_count || 0) + (emotion.value?.zb_count || 0))
const fmtRate = (v: number | null | undefined) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)

const openRatioDetail = (key: 'seal' | 'break' | 'promo') => {
  const e = emotion.value
  if (!e) return
  if (key === 'seal') {
    showDetail({
      title: '封板率 · 涨停池（分子）',
      note: `封板率 = 涨停 ${e.zt_count} ÷（涨停 ${e.zt_count} + 炸板 ${e.zb_count}）= ${fmtRate(e.seal_rate)}`,
      rows: e.pools?.zt || [],
      metric: METRIC_BOARDS,
    })
  } else if (key === 'break') {
    showDetail({
      title: '炸板率 · 炸板池（分子）',
      note: `炸板率 = 炸板 ${e.zb_count} ÷（涨停 ${e.zt_count} + 炸板 ${e.zb_count}）= ${fmtRate(e.break_rate)}`,
      rows: e.pools?.zb || [],
      metric: METRIC_BREAK,
    })
  } else {
    showDetail({
      title: '晋级率 · 今日连板（分子）',
      note: `晋级率 = 今日连板 ${e.lianban_count} ÷ 昨日涨停 ${e.yzt_count} = ${fmtRate(e.promotion_rate)}`,
      rows: e.lianban_stocks || [],
      metric: METRIC_BOARDS,
    })
  }
}

// ── 资金维度 ──
const amountStats = computed(() => {
  const pools = emotion.value?.pools
  const sum = (rows?: EmotionPoolRow[]) => (rows || []).reduce((a, r) => a + (Number(r.amount) || 0), 0)
  const ztAmt = sum(pools?.zt)
  const zbAmt = sum(pools?.zb)
  const lb = emotion.value?.lianban_stocks || []
  const lbAmt = lb.reduce((a, r) => a + (Number(r.amount) || 0), 0)
  const total = ztAmt + zbAmt
  return {
    zt: ztAmt,
    zb: zbAmt,
    sealShare: total ? (ztAmt / total) * 100 : null,
    lbAvg: lb.length ? lbAmt / lb.length : 0,
  }
})

// ── 比率均值 ──
const ratioAvg = computed(() => {
  const seals = recent5.value.map(p => p.seal_rate).filter((v): v is number => v != null)
  const breaks = recent5.value
    .map(p => (p.zt + p.zb ? p.zb / (p.zt + p.zb) : null))
    .filter((v): v is number => v != null)
  const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null)
  return { seal: avg(seals), break: avg(breaks) }
})

// ── 情绪周期图 1：家数走势（柱）+ 最高连板（线） ──
const countChartOption = computed<EChartsOption | null>(() => {
  const s = histSeries.value
  if (s.length < 2) return null
  const maxBoard = Math.max(1, ...s.map(p => p.max_boards || 0))
  return {
    animationDuration: 500,
    grid: { left: 40, right: 42, top: 32, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TIP },
    legend: { ...LEGEND, data: ['涨停', '炸板', '跌停', '最高连板'] },
    xAxis: {
      type: 'category',
      data: s.map(p => p.date.slice(5)),
      axisLabel,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: [
      { type: 'value', name: '家数', nameTextStyle: { ...axisLabel }, axisLabel, splitLine },
      {
        type: 'value',
        name: '板',
        min: 0,
        max: maxBoard + 1,
        nameTextStyle: { ...axisLabel },
        axisLabel,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '涨停', type: 'bar', barMaxWidth: 14, barGap: '15%',
        data: s.map(p => p.zt),
        itemStyle: { color: '#f56c6c', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '炸板', type: 'bar', barMaxWidth: 14,
        data: s.map(p => p.zb),
        itemStyle: { color: '#e6a23c', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '跌停', type: 'bar', barMaxWidth: 14,
        data: s.map(p => p.dt),
        itemStyle: { color: '#67c23a', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '最高连板', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 5,
        data: s.map(p => p.max_boards),
        itemStyle: { color: '#7c3aed' },
        lineStyle: { width: 2 },
      },
    ],
  }
})

// ── 情绪周期图 2：封板率 / 炸板率（%）+ 连板家数（右轴） ──
const qualityChartOption = computed<EChartsOption | null>(() => {
  const s = histSeries.value
  if (s.length < 2) return null
  const seal = s.map(p => (p.seal_rate == null ? null : +(p.seal_rate * 100).toFixed(1)))
  const brk = s.map(p => {
    const a = p.zt + p.zb
    return a ? +((p.zb / a) * 100).toFixed(1) : null
  })
  const maxLianban = Math.max(1, ...s.map(p => p.lianban || 0))
  return {
    animationDuration: 500,
    grid: { left: 40, right: 42, top: 32, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TIP },
    legend: { ...LEGEND, data: ['封板率', '炸板率', '连板家数'] },
    xAxis: {
      type: 'category',
      data: s.map(p => p.date.slice(5)),
      axisLabel,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: [
      {
        type: 'value', name: '%', min: 0, max: 100,
        nameTextStyle: { ...axisLabel }, axisLabel: { ...axisLabel, formatter: '{value}%' }, splitLine,
      },
      {
        type: 'value', name: '家', min: 0, max: maxLianban + 2,
        nameTextStyle: { ...axisLabel }, axisLabel, splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '连板家数', type: 'bar', yAxisIndex: 1, barMaxWidth: 14,
        data: s.map(p => p.lianban),
        itemStyle: { color: '#a5b4fc', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '封板率', type: 'line', smooth: true, symbolSize: 4,
        data: seal,
        itemStyle: { color: '#e11d48' },
        lineStyle: { width: 2.2 },
      },
      {
        name: '炸板率', type: 'line', smooth: true, symbolSize: 4,
        data: brk,
        itemStyle: { color: '#e6a23c' },
        lineStyle: { width: 1.6, type: 'dashed' },
      },
    ],
  }
})

// ── 今日 vs 近 10 日均值（双条对比，直接展示同量纲数值） ──
interface CompareRow {
  label: string
  today: number
  avg: number
  unit: string
  reverse?: boolean
  todayW: string
  avgW: string
  todayText: string
  avgText: string
  deltaText: string
  deltaTone: string
}
const compareRows = computed<CompareRow[]>(() => {
  const e = emotion.value
  const avg = avgPoints.value
  if (!e || !avg.length) return []
  const avgOf = (fn: (p: EmotionHistoryPoint) => number | null | undefined) => {
    const vals = avg.map(fn).filter((v): v is number => v != null)
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  }
  const defs: Array<{ label: string; today: number | null; avg: number | null; unit: string; reverse?: boolean }> = [
    { label: '涨停家数', today: e.zt_count, avg: avgOf(p => p.zt), unit: '家' },
    { label: '连板家数', today: e.lianban_count, avg: avgOf(p => p.lianban), unit: '家' },
    { label: '最高连板', today: e.max_boards, avg: avgOf(p => p.max_boards), unit: '板' },
    { label: '封板率', today: e.seal_rate == null ? null : e.seal_rate * 100, avg: avgOf(p => (p.seal_rate == null ? null : p.seal_rate * 100)), unit: '%' },
    { label: '炸板家数', today: e.zb_count, avg: avgOf(p => p.zb), unit: '家', reverse: true },
    { label: '跌停家数', today: e.dt_count, avg: avgOf(p => p.dt), unit: '家', reverse: true },
  ]
  const valid = defs.filter(d => d.today != null && d.avg != null)
  if (!valid.length) return []
  // 同一图表内所有条共用一个最大刻度，保证今日与均值可直接目测比较
  const scale = Math.max(1, ...valid.flatMap(d => [d.today as number, d.avg as number]))
  const toW = (v: number) => `${Math.max(1.5, (v / scale) * 100).toFixed(1)}%`
  return valid.map(d => {
    const today = d.today as number
    const avgVal = d.avg as number
    const diff = today - avgVal
    const pct = avgVal ? (diff / avgVal) * 100 : 0
    const better = d.reverse ? diff < 0 : diff > 0
    return {
      label: d.label,
      today,
      avg: avgVal,
      unit: d.unit,
      reverse: d.reverse,
      todayW: toW(today),
      avgW: toW(avgVal),
      todayText: `${today.toFixed(unitDigit(d.unit))}${d.unit}`,
      avgText: `${avgVal.toFixed(unitDigit(d.unit))}${d.unit}`,
      deltaText: `${diff > 0 ? '+' : ''}${diff.toFixed(unitDigit(d.unit))}${d.unit}（${pct > 0 ? '+' : ''}${pct.toFixed(0)}%）`,
      deltaTone: Math.abs(pct) < 5 ? 'flat' : better ? 'up' : 'down',
    }
  })
})
const unitDigit = (unit: string) => (unit === '板' ? 0 : unit === '%' ? 1 : 0)

// ── 晋级阶梯（昨日涨停 → 今日连板 → 3板+ → 5板+） ──
interface StageDef { name: string; value: number; pct: number; color: string; min: number }
const stageList = computed<StageDef[]>(() => {
  const e = emotion.value
  if (!e || !e.yzt_count) return []
  const ladder = e.ladder || []
  const above = (min: number) => ladder.filter(l => l.boards >= min).reduce((a, l) => a + l.count, 0)
  const pct = (v: number) => +((v / e.yzt_count) * 100).toFixed(1)
  return [
    { name: '昨日涨停', value: e.yzt_count, pct: 100, color: '#cbd5e0', min: 1 },
    { name: '今日连板 2板+', value: e.lianban_count, pct: pct(e.lianban_count), color: '#f87171', min: 2 },
    { name: '3板+', value: above(3), pct: pct(above(3)), color: '#ef4444', min: 3 },
    { name: '5板+', value: above(5), pct: pct(above(5)), color: '#b91c1c', min: 5 },
  ]
})
const stageOption = computed<EChartsOption | null>(() => {
  const e = emotion.value
  const stages = stageList.value
  if (!e || !stages.length) return null
  return {
    animationDuration: 500,
    grid: { left: 92, right: 96, top: 12, bottom: 22 },
    tooltip: {
      trigger: 'item',
      ...TIP,
      formatter: (p: any) => {
        const s = stages[p.dataIndex]
        return `${s.name}<br/>${s.value} 家 · 占昨日涨停 ${s.pct}%<br/><span style="color:#a0aec0">点击长条查看明细</span>`
      },
    },
    xAxis: { type: 'value', max: Math.max(1, e.yzt_count), axisLabel, splitLine },
    yAxis: {
      type: 'category',
      inverse: true,
      data: stages.map(s => s.name),
      axisLabel: { color: '#4a5568', fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 22,
      cursor: 'pointer',
      data: stages.map(s => ({ value: s.value, itemStyle: { color: s.color, borderRadius: [0, 4, 4, 0] } })),
      label: {
        show: true,
        position: 'right',
        fontSize: 10,
        color: '#718096',
        formatter: (p: any) => {
          const s = stages[p.dataIndex]
          return `${s.value}家 · ${s.pct}%`
        },
      },
    }],
  }
})

const stageSel = ref<number | null>(null)
const onStageClick = (p: any) => {
  const idx = Number(p?.dataIndex)
  if (Number.isNaN(idx)) return
  stageSel.value = stageSel.value === idx ? null : idx
}
const stageDetail = computed(() => {
  const idx = stageSel.value
  const stages = stageList.value
  const e = emotion.value
  if (idx == null || !stages[idx] || !e) return null
  const stage = stages[idx]
  const isYzt = stage.name === '昨日涨停'
  const rows = isYzt
    ? (e.pools?.yzt || [])
    : (e.lianban_stocks || []).filter(r => (r.boards || 0) >= stage.min)
  // 昨涨停池的涨跌幅为今日表现，标题注明避免误读
  return { title: isYzt ? '昨日涨停（今日表现）' : stage.name, rows }
})

// ── 行业分布（涨停 / 炸板 / 跌停 可切换） ──
const indPool = ref<'zt' | 'zb' | 'dt'>('zt')
const industryRows = computed(() => {
  const rows = emotion.value?.pools?.[indPool.value] || []
  const cnt = new Map<string, number>()
  rows.forEach(r => {
    const k = (r.industry || '').trim() || '未分类'
    cnt.set(k, (cnt.get(k) || 0) + 1)
  })
  return [...cnt.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
})
const cr3 = computed(() => {
  const rows = industryRows.value
  const total = rows.reduce((a, r) => a + r.count, 0)
  const top3 = rows.slice(0, 3).reduce((a, r) => a + r.count, 0)
  return total ? Math.round((top3 / total) * 100) : 0
})
const industryOption = computed<EChartsOption | null>(() => {
  const top = industryRows.value.slice(0, 10)
  if (!top.length) return null
  const max = Math.max(1, ...top.map(r => r.count))
  const colorMap = { zt: '#f87171', zb: '#e6a23c', dt: '#67c23a' } as const
  return {
    animationDuration: 500,
    grid: { left: 96, right: 40, top: 10, bottom: 22 },
    tooltip: {
      trigger: 'item',
      ...TIP,
      formatter: (p: any) => {
        const r = top[p.dataIndex]
        const total = industryRows.value.reduce((a, x) => a + x.count, 0)
        return `${r.name}<br/>${r.count} 家 · 占该池 ${((r.count / total) * 100).toFixed(1)}%<br/><span style="color:#a0aec0">点击长条跳转同花顺行业板块</span>`
      },
    },
    xAxis: { type: 'value', max: max, minInterval: 1, axisLabel, splitLine },
    yAxis: {
      type: 'category',
      inverse: true,
      data: top.map(r => r.name),
      axisLabel: { color: '#4a5568', fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 16,
      cursor: 'pointer',
      data: top.map(r => ({ value: r.count, itemStyle: { color: colorMap[indPool.value], borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: 'right', fontSize: 10, color: '#718096', formatter: '{c}家' },
    }],
  }
})

// ── 行业名 → 同花顺行业板块（881xxx）映射 · 点击长条直接跳转 ──
// 东财池内行业名常被截断（如「农产品加」「汽车零部」）或与同花顺叫法略有差异，
// 先按别名归一，再用同花顺全名做前缀兜底匹配。
const THS_INDUSTRY_ALIAS: Record<string, string> = {
  休闲食品: '食品加工制造',
  一般零售: '零售',
  饮料乳品: '饮料制造',
  家电零部: '白色家电',
  照明设备: '光学光电子',
  航运港口: '港口航运',
  装修建材: '建筑材料',
  专业工程: '建筑装饰',
  出版: '文化传媒',
  文娱用品: '文化传媒',
  广告营销: '文化传媒',
  工程咨询: '建筑装饰',
  装修装饰: '建筑装饰',
  航空装备: '军工装备',
  航天装备: '军工装备',
  铁路公路: '公路铁路运输',
  焦炭: '煤炭开采加工',
  林业: '种植业与林业',
  旅游及景: '旅游及酒店',
}
const sectorThsMap = ref<Map<string, string>>(new Map())
let sectorMapTask: Promise<void> | null = null
const ensureSectorThsMap = () => {
  if (!sectorMapTask) {
    sectorMapTask = vibeApi.getMarketOverview()
      .then((res) => {
        const sectors = (res as any)?.data?.sectors || []
        sectorThsMap.value = new Map(
          sectors
            .filter((s: any) => s?.name && s?.ths_code)
            .map((s: any) => [String(s.name).trim(), String(s.ths_code)]),
        )
      })
      .catch(() => {
        sectorMapTask = null
      })
  }
  return sectorMapTask
}
const normalizeIndustryName = (s: string) => s.replace(/Ⅱ|II/g, '').trim()
const resolveThsIndustryCode = (name: string): string => {
  const target = THS_INDUSTRY_ALIAS[normalizeIndustryName(name)] || normalizeIndustryName(name)
  const map = sectorThsMap.value
  if (!target || !map.size) return ''
  const exact = map.get(target)
  if (exact) return exact
  const candidates = [...map.keys()]
    .filter(k => {
      const n = normalizeIndustryName(k)
      return n.startsWith(target) || target.startsWith(n)
    })
    .sort((a, b) => a.length - b.length)
  return candidates.length ? (map.get(candidates[0]) as string) : ''
}
const onIndustryClick = async (p: any) => {
  if (p?.componentType !== 'series') return
  const idx = Number(p?.dataIndex)
  const name = industryRows.value.slice(0, 10)[idx]?.name
  if (!name) return
  if (!sectorThsMap.value.size) await ensureSectorThsMap()
  const code = resolveThsIndustryCode(name)
  if (!code) {
    ElMessage.info(`未找到「${name}」对应的同花顺行业板块`)
    return
  }
  window.open(`https://q.10jqka.com.cn/thshy/detail/code/${code}/`, '_blank', 'noopener')
}

// ── 连板股成交额（替代表格） ──
const boardColor = (b: number) =>
  b >= 5 ? '#b91c1c' : b === 4 ? '#dc2626' : b === 3 ? '#ef4444' : '#f87171'
const lianbanSorted = computed(() =>
  [...(emotion.value?.lianban_stocks || [])].sort((a, b) => (b.amount || 0) - (a.amount || 0))
)
const lianbanChartHeight = computed(() => {
  const n = lianbanSorted.value.length
  return `${Math.max(150, n * 34 + 30)}px`
})
const lianbanAmountOption = computed<EChartsOption | null>(() => {
  const rows = lianbanSorted.value
  if (!rows.length) return null
  return {
    animationDuration: 500,
    grid: { left: 116, right: 62, top: 10, bottom: 20 },
    tooltip: {
      trigger: 'item',
      ...TIP,
      formatter: (p: any) => {
        const r = rows[p.dataIndex]
        return `<b>${r.name}</b> ${r.code}<br/>连板 ${r.boards}板 · ${r.industry || '未分类'}<br/>成交额 ${fmtYi(r.amount)} 亿<br/>流通市值 ${fmtYi(r.float_cap)} 亿<br/><span style="color:#a0aec0">点击长条查看个股详情</span>`
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: { ...axisLabel, formatter: '{value}亿' },
      splitLine,
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map(r => `${r.name} ${r.boards}板`),
      axisLabel: { color: '#4a5568', fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 18,
      cursor: 'pointer',
      data: rows.map(r => ({
        value: +(((r.amount || 0) / 1e8).toFixed(2)),
        itemStyle: { color: boardColor(r.boards), borderRadius: [0, 4, 4, 0] },
      })),
      label: {
        show: true,
        position: 'right',
        fontSize: 10,
        color: '#718096',
        formatter: (p: any) => `${p.value}亿`,
      },
    }],
  }
})

// 连板股成交额长条 → 个股详情
const onLianbanClick = (p: any) => {
  if (p?.componentType !== 'series') return
  const idx = Number(p?.dataIndex)
  const code = lianbanSorted.value[idx]?.code
  if (code) window.open(`/stocks/${code}`, '_blank', 'noopener')
}

// ── 风险结构：炸板次数 / 跌停天数（点击柱体展开该档明细） ──
interface RiskBucket { label: string; min: number; max: number | null; count: number }
const breakBuckets = computed<RiskBucket[]>(() => {
  const buckets: RiskBucket[] = [
    { label: '1次', min: 1, max: 1, count: 0 },
    { label: '2次', min: 2, max: 2, count: 0 },
    { label: '3次', min: 3, max: 3, count: 0 },
    { label: '4次+', min: 4, max: null, count: 0 },
  ]
  ;(emotion.value?.pools?.zb || []).forEach(r => {
    const n = Math.max(1, Number(r.break_times) || 1)
    buckets[Math.min(3, n - 1)].count += 1
  })
  return buckets
})
const breakDistOption = computed<EChartsOption | null>(() => {
  const buckets = breakBuckets.value
  if (!buckets.some(b => b.count)) return null
  return {
    animationDuration: 500,
    grid: { left: 40, right: 16, top: 16, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      ...TIP,
      valueFormatter: (v: any) => `${v} 家`,
    },
    xAxis: {
      type: 'category',
      data: buckets.map(b => b.label),
      axisLabel,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: { type: 'value', name: '家', nameTextStyle: { ...axisLabel }, axisLabel, splitLine },
    series: [{
      type: 'bar',
      barMaxWidth: 40,
      cursor: 'pointer',
      data: buckets.map(b => b.count),
      itemStyle: { color: '#e6a23c', borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', fontSize: 10, color: '#718096' },
    }],
  }
})
const dtBuckets = computed<RiskBucket[]>(() => {
  const buckets: RiskBucket[] = [
    { label: '1天', min: 1, max: 1, count: 0 },
    { label: '2天', min: 2, max: 2, count: 0 },
    { label: '3天+', min: 3, max: null, count: 0 },
  ]
  ;(emotion.value?.pools?.dt || []).forEach(r => {
    const n = Math.max(1, Number(r.days) || 1)
    buckets[Math.min(2, n - 1)].count += 1
  })
  return buckets
})
const dtDistOption = computed<EChartsOption | null>(() => {
  const buckets = dtBuckets.value
  if (!buckets.some(b => b.count)) return null
  return {
    animationDuration: 500,
    grid: { left: 40, right: 16, top: 16, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TIP, valueFormatter: (v: any) => `${v} 家` },
    xAxis: {
      type: 'category',
      data: buckets.map(b => b.label),
      axisLabel,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: { type: 'value', name: '家', minInterval: 1, nameTextStyle: { ...axisLabel }, axisLabel, splitLine },
    series: [{
      type: 'bar',
      barMaxWidth: 48,
      cursor: 'pointer',
      data: buckets.map(b => b.count),
      itemStyle: { color: '#67c23a', borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', fontSize: 10, color: '#718096' },
    }],
  }
})

const zbSel = ref<number | null>(null)
const dtSel = ref<number | null>(null)
const pickBucket = (
  p: any,
  buckets: RiskBucket[],
  current: number | null,
): number | null => {
  const idx = Number(p?.dataIndex)
  if (Number.isNaN(idx) || !buckets[idx]) return current
  return current === idx ? null : idx
}
const onBreakClick = (p: any) => { zbSel.value = pickBucket(p, breakBuckets.value, zbSel.value) }
const onDtClick = (p: any) => { dtSel.value = pickBucket(p, dtBuckets.value, dtSel.value) }

const inBucket = (v: number, b: RiskBucket) => v >= b.min && (b.max == null || v <= b.max)

const breakDetail = computed(() => {
  const idx = zbSel.value
  const b = idx == null ? null : breakBuckets.value[idx]
  if (!b) return null
  const rows = (emotion.value?.pools?.zb || []).filter(r => inBucket(Math.max(1, Number(r.break_times) || 1), b))
  return { title: `炸板 ${b.label}`, rows }
})
const dtDetail = computed(() => {
  const idx = dtSel.value
  const b = idx == null ? null : dtBuckets.value[idx]
  if (!b) return null
  const rows = (emotion.value?.pools?.dt || []).filter(r => inBucket(Math.max(1, Number(r.days) || 1), b))
  return { title: `连续跌停 ${b.label}`, rows }
})

// 情绪周期阶段（基于涨停/跌停家数、炸板率、连板高度与环比变化）
type PhaseTone = 'hot' | 'mid' | 'cold'
interface PhaseInfo { label: string; tone: PhaseTone; desc: string }

const phase = computed<PhaseInfo | null>(() => {
  const e = emotion.value
  if (!e) return null
  const prev = prevPoint.value
  const zt = Number(e.zt_count) || 0
  const zb = Number(e.zb_count) || 0
  const dt = Number(e.dt_count) || 0
  const attempts = zt + zb
  const breakRate = attempts ? zb / attempts : 0
  const delta = prev ? zt - prev.zt : 0
  if (zt < 30 && dt >= zt) {
    return { label: '冰点期', tone: 'cold', desc: '涨停家数少、跌停压制，赚钱效应偏弱，等待修复信号' }
  }
  if (prev && zt < prev.zt * 0.7 && (breakRate >= 0.3 || dt >= 10)) {
    return { label: '退潮期', tone: 'cold', desc: '涨停家数明显回落、炸板与跌停增多，注意高位股补跌风险' }
  }
  if (breakRate >= 0.35 || (prev && zt < prev.zt * 0.85)) {
    return { label: '分歧期', tone: 'mid', desc: '炸板率偏高、涨停家数环比回落，资金开始分歧，宜降低预期' }
  }
  if (zt >= 100 || Number(e.max_boards) >= 6) {
    return { label: '高潮期', tone: 'hot', desc: '涨停家数与连板高度双高，赚钱效应最强，警惕次日退潮' }
  }
  if (zt >= 60 && (Number(e.seal_rate) || 0) >= 0.65) {
    return { label: '发酵期', tone: 'hot', desc: '涨停家数扩张、封板率较高，情绪仍在向上发酵' }
  }
  if (delta > 0 || zt >= 40) {
    return { label: '修复期', tone: 'mid', desc: '涨停家数回暖，情绪自低位修复，关注主线持续性' }
  }
  return { label: '启动期', tone: 'mid', desc: '情绪温和、主线未明，适合轻仓试错' }
})

// ── 三池明细（折叠区） ──
const detailOpen = ref<string[]>([])
const poolTab = ref<'zt' | 'zb' | 'dt'>('zt')
const poolRows = computed<EmotionPoolRow[]>(() => {
  const pools = emotion.value?.pools
  return pools ? (pools[poolTab.value] || []) : []
})

const rateWidth = (v: number | null | undefined) =>
  v == null ? '0%' : Math.min(100, Math.max(0, v * 100)).toFixed(1) + '%'

const load = async (refresh = false) => {
  loading.value = true
  try {
    const res = await vibeApi.getEmotion(refresh)
    emotion.value = (res as any).data || null
    // 数据刷新后收起所有图表明细，避免指向已变化的档位
    stageSel.value = null
    zbSel.value = null
    dtSel.value = null
    detailDialog.value = false
    if (!emotion.value) {
      ElMessage.warning('暂无短线情绪数据')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

const loadHistory = async (refresh = false) => {
  historyLoading.value = true
  try {
    const res = await vibeApi.getEmotionHistory(10, refresh)
    history.value = (res as any)?.data || null
  } catch (e) {
    console.warn('情绪历史加载失败', e)
    history.value = null
  } finally {
    historyLoading.value = false
  }
}

// 页头刷新：两个接口并行刷新（含历史序列）
const refresh = async () => {
  await Promise.all([load(true), loadHistory(true)])
}
defineExpose({ refresh })

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) tradeDate.value = d })
  load()
  loadHistory()
  ensureSectorThsMap()
})

// keep-alive 恢复：缓存 TTL 内不产生请求，仅刷新数据快照
let emotionInited = false
onActivated(() => {
  if (emotionInited) {
    load()
    loadHistory()
  }
  emotionInited = true
})
</script>

<style scoped>
.vibe-emotion {
  padding: 4px;
  min-height: 200px;
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
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.grid-6 {
  grid-template-columns: repeat(6, 1fr);
}

.count-card {
  border-radius: 8px;
  text-align: center;
}

.clickable {
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.clickable:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 4px 14px rgba(45, 55, 72, 0.1);
}

.count-card :deep(.el-card__body) {
  padding: 18px 16px;
}

.cnt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.cnt-num {
  font-family: var(--app-font-mono);
  font-size: 32px;
  font-weight: 700;
  margin: 6px 0 2px;
  color: var(--el-text-color-primary);
}

.cnt-sub {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.cnt-delta {
  font-family: var(--app-font-mono);
  font-weight: 600;
}

.cnt-delta.up { color: var(--app-up); }
.cnt-delta.down { color: var(--app-down); }

.fund-strip {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.fund-item {
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.fund-label {
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}

.fund-item b {
  font-family: var(--app-font-mono);
  font-size: 19px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.fund-item i {
  font-style: normal;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.ratio-card {
  border-radius: 8px;
}

.ratio-card :deep(.el-card__body) {
  padding: 18px 20px;
}

.rt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.rt-num {
  font-family: var(--app-font-mono);
  font-size: 28px;
  font-weight: 700;
  margin: 6px 0 12px;
  color: var(--el-text-color-primary);
}

/* 分子 / 分母 = 结果 */
.rt-frac {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 8px 0 12px;
  font-family: var(--app-font-mono);
  white-space: nowrap;
}

.frac-num,
.frac-den {
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.frac-sep,
.frac-eq {
  font-size: 18px;
  color: var(--el-text-color-placeholder);
}

.frac-result {
  font-size: 26px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.frac-num.up,
.frac-result.up {
  color: var(--app-up);
}

.frac-num.down,
.frac-result.down {
  color: var(--app-down);
}

.rt-bar {
  height: 6px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  overflow: hidden;
}

.rt-avg {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.ladder-card {
  border-radius: 8px;
}

/* 图表卡片 */
.chart-card {
  border-radius: 8px;
}

.chart-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.chart-card--wide {
  margin-top: 12px;
}

.chart-cap {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.chart-cap > span {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.pool-switch {
  margin-left: auto;
}

.chart-200 { width: 100%; height: 200px; }
.chart-220 { width: 100%; height: 220px; }
.chart-240 { width: 100%; height: 240px; }

.phase-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  border: 1px solid transparent;
}

.phase-hot {
  color: #c0392b;
  background: #fdecea;
  border-color: #f5b7b1;
}

.phase-cold {
  color: #1e8449;
  background: #eafaf1;
  border-color: #a9dfbf;
}

.phase-mid {
  color: #a16207;
  background: #fef9e7;
  border-color: #f7dc6f;
}

.phase-desc {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

/* 今日 vs 近 10 日均值：双条对比 */
.cmp-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cmp-row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) 118px;
  align-items: center;
  gap: 12px;
}

.cmp-label {
  font-size: 12.5px;
  color: var(--el-text-color-regular);
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.cmp-label i {
  font-style: normal;
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}

.cmp-bars {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cmp-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cmp-tag {
  width: 30px;
  flex: none;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.cmp-track {
  flex: 1;
  height: 12px;
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
  overflow: hidden;
}

.cmp-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.cmp-fill.today { background: var(--app-up); }
.cmp-fill.avg { background: var(--el-border-color-darker); }

.cmp-val {
  width: 54px;
  flex: none;
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--el-text-color-primary);
  text-align: right;
}

.cmp-delta {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  text-align: right;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.cmp-delta.up { color: var(--app-up); }
.cmp-delta.down { color: var(--app-down); }
.cmp-delta.flat { color: var(--el-text-color-secondary); }

/* 明细折叠区 */
.detail-collapse {
  border-top: none;
}

.collapse-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

/* 三池清单 Tab */
.pool-tabs {
  margin-top: -6px;
}

.pool-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.pool-tabs :deep(.el-tabs__item) {
  height: 34px;
  font-size: 13px;
}

.empty {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 16px 0;
  font-size: 13px;
}

.dialog-body {
  padding-bottom: 4px;
}

.dialog-note {
  margin: 0 0 10px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.bar-fill.up { background: var(--app-up); }
.bar-fill.down { background: var(--app-down); }
.bar-fill.neutral { background: var(--app-flat); }

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 992px) {
  .grid-2 { grid-template-columns: 1fr; }
  .grid-3 { grid-template-columns: 1fr; }
  .fund-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 768px) {
  .vibe-emotion {
    padding: 2px;
  }
  .grid-6 {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
  .grid-3 {
    gap: 8px;
  }
  .count-card :deep(.el-card__body) {
    padding: 12px 8px;
  }
  .cnt-label {
    font-size: 12px;
    line-height: 1.2;
  }
  .cnt-num {
    font-size: 26px;
    margin: 4px 0 2px;
    line-height: 1;
    word-break: break-all;
  }
  .rt-num {
    font-size: 22px;
    margin: 4px 0 8px;
  }
  .frac-num,
  .frac-den {
    font-size: 18px;
  }
  .frac-result {
    font-size: 22px;
  }
  .frac-sep,
  .frac-eq {
    font-size: 15px;
  }
  .block-head {
    flex-wrap: wrap;
    gap: 4px;
  }
}

@media (max-width: 480px) {
  .grid-6 {
    grid-template-columns: repeat(2, 1fr);
  }
  .fund-strip {
    grid-template-columns: 1fr;
  }
}
</style>
