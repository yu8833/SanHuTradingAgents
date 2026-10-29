<template>
  <div class="vibe-overview app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataAnalysis /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }}<em v-if="weekday" class="title-weekday">（{{ weekday }}）</em> · 大盘看板</h2>
          <p class="page-hero-sub">大盘指数 / 市场情绪 / 涨跌分布一屏看全</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="market-state" :class="marketState.cls">{{ marketState.label }}</span>
        <span class="page-hero-tag">数据 {{ dataAsOf || '—' }} · 更新 {{ updatedAt || '—' }}</span>
        <router-link to="/vibe/synthesis" class="hero-link">看今日结论 →</router-link>
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="refreshOverview">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 一句话结论：先给判断，下面各块都是这句话的依据 -->
    <section v-if="dashboard" class="verdict">
      <span class="verdict-tag" :style="scoreStyle">{{ dashboard.emotion.label }} · {{ dashboard.emotion.score }} 分</span>
      <p class="verdict-text">{{ verdictText }}</p>
      <span class="verdict-meta">
        <em v-if="metrics" :class="{ 'is-live': metrics.is_live }">{{ metrics.status_label || (metrics.is_live ? '盘中' : '已收盘') }}</em>
        <span v-if="dataAsOf">数据 {{ dataAsOf }}</span>
      </span>
    </section>

    <!-- 开盘情景：盘前唯一的前瞻信息（隔夜外盘 → 开盘缺口）+ 昨日情绪结构，08:30 后自动展开 -->
    <section v-if="preOpen && preOpen.bands.length" class="preopen-block">
      <div class="preopen-head">
        <span class="preopen-kicker">开盘情景</span>
        <span class="preopen-verdict" :class="`tone-${preOpen.gap.tone}`">
          {{ preOpen.gap.label }}
          <em v-if="preOpen.gap.pct != null">{{ signedPct(preOpen.gap.pct) }}</em>
        </span>
        <span v-if="preOpen.gap.basis_name" class="preopen-basis">
          {{ preOpen.gap.basis_name }} · {{ preOpen.gap.basis_name.includes('A50') ? '夜盘' : '期货' }}
          <span v-if="preOpen.gap.degraded" class="preopen-tag">降级口径</span>
        </span>
        <span class="preopen-actions">
          <span class="data-time">抓取 {{ shortTime(preOpen.as_of) }}</span>
          <span class="preopen-toggle" @click="preOpenOpen = !preOpenOpen">{{ preOpenOpen ? '收起' : '展开' }}</span>
        </span>
      </div>

      <div v-show="preOpenOpen" class="preopen-body">
        <!-- 五档刻度：区间宽度按幅度成比例，指针标出当前实际位置 -->
        <div class="scenario-scale">
          <span
            v-if="scenarioPointerPct != null"
            class="scenario-ptr"
            :class="`tone-${preOpen.gap.tone}`"
            :style="{ left: scenarioPointerPct + '%' }"
          />
          <div class="scenario-track">
            <div
              v-for="b in preOpen.bands"
              :key="b.key"
              class="scenario-seg"
              :class="b.key === preOpen.gap.band ? `active tone-${b.tone}` : ''"
            >
              <span class="seg-label">{{ b.label }}</span>
              <span class="seg-range">{{ bandRange(b) }}</span>
            </div>
          </div>
        </div>

        <div class="preopen-meta">
          <div class="meta-row">
            <span class="meta-label">隔夜外盘</span>
            <div class="meta-items">
              <span
                v-for="it in preOpen.overseas"
                :key="it.key"
                class="meta-item"
                :class="{ 'meta-item--key': it.key === 'a50fut' }"
              >
                <b>{{ it.name }}</b>
                <i :class="colorClass(it.change_pct)">{{ signedPct(it.change_pct) }}</i>
              </span>
            </div>
          </div>
          <div v-if="preOpen.structure" class="meta-row">
            <span class="meta-label">昨日结构</span>
            <div class="meta-items">
              <span class="meta-item">
                <b>涨停</b><i>{{ preOpen.structure.zt }}</i>
                <em :class="deltaClass(preOpen.structure.zt_delta)">{{ deltaText(preOpen.structure.zt_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>最高连板</b><i>{{ preOpen.structure.max_boards }}</i>
                <em :class="deltaClass(preOpen.structure.max_boards_delta)">{{ deltaText(preOpen.structure.max_boards_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>连板</b><i>{{ preOpen.structure.lianban }}</i>
                <em :class="deltaClass(preOpen.structure.lianban_delta)">{{ deltaText(preOpen.structure.lianban_delta) }}</em>
              </span>
              <span class="meta-item">
                <b>封板率</b>
                <i>{{ preOpen.structure.seal_rate == null ? '—' : fmtAbsPct(preOpen.structure.seal_rate * 100, 0) }}</i>
                <em :class="deltaClass(preOpen.structure.seal_delta_pt)">{{ deltaText(preOpen.structure.seal_delta_pt, 'pt') }}</em>
              </span>
              <span class="meta-date">{{ preOpen.structure.date }}</span>
            </div>
          </div>
        </div>

        <div class="preopen-note">{{ preOpen.note }}</div>
      </div>
    </section>
    <section v-else-if="preOpenLoading" class="preopen-block preopen-block--loading">
      <span class="preopen-kicker">开盘情景</span>
      <span class="block-hint"><el-icon class="is-loading"><Loading /></el-icon> 正在计算隔夜外盘与昨日结构</span>
    </section>

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

    <!-- 今日涨跌分布：横截面回答「涨多还是跌多、极端多少」 -->
    <section v-if="dashboard" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Histogram /></el-icon> 今日涨跌分布</span>
        <span class="block-hint">{{ limitNote }}</span>
      </div>

      <!-- 雷达 + 涨跌分布 -->
      <div class="dash-main">
        <el-card shadow="never" class="dash-card">
          <div class="card-title">
            情绪雷达
            <span class="dist-note">虚线 = 50 分中性基准</span>
          </div>
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
              <!-- 50 分基准环：低于虚线说明该维度不及中性水平 -->
              <polygon :points="radarMidPolygon" fill="none" stroke="rgba(128,128,128,0.45)" stroke-width="1" stroke-dasharray="3 3" />
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
          <p class="cap">六个维度越靠外越强；缩在虚线（50 分）以内的维度，就是当天明显的短板。</p>
        </el-card>

        <el-card shadow="never" class="dash-card">
          <div class="card-title">
            涨跌家数分布
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
          <div class="dist-foot">
            <span>涨跌 ≥3%：<b class="up">{{ dashboard.breadth.strong_up }}</b> 家强势 / <b class="down">{{ dashboard.breadth.strong_down }}</b> 家弱势</span>
            <span>平均 {{ fmtPct(dashboard.breadth.avg_pct) }} · 中位 {{ fmtPct(dashboard.breadth.median_pct) }}</span>
          </div>
          <p class="cap">右端（涨停/大涨）越长，赚钱效应越强；两端同时变长、中间变短 = 涨跌分化加剧，多数个股其实在原地。</p>
        </el-card>
      </div>
    </section>

    <!-- 市场温度与资金结构：把今天的读数放进近一年分位/趋势，回答「今天算热还是冷、钱去了哪」 -->
    <section v-if="metrics" class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataAnalysis /></el-icon> 市场温度与资金结构</span>
        <span class="block-hint">
          分位基于近一年交易日 · {{ metrics.status_label || '已收盘' }}{{ metrics.is_live ? '（数据仍在跳动）' : '（当日数据已定）' }}
          <em v-if="metrics.as_of" class="data-time">数据 {{ metrics.as_of }} · 更新 {{ shortTime(metrics.updated) }}</em>
        </span>
      </div>

      <div v-if="metrics.alerts.length" class="alert-row">
        <span v-for="a in metrics.alerts" :key="a.title" class="alert-chip" :class="`is-${a.level}`">
          <b>{{ a.title }}</b><span>{{ a.detail }}</span>
        </span>
      </div>
      <div v-else-if="metrics.ready" class="alert-row alert-row--calm">
        <span class="alert-chip is-ok">无异常信号 · 温度与广度均在正常区间</span>
      </div>

      <!-- 温度分位：每项一条分位条，中位刻度固定在 50% -->
      <div class="temp-headline">
        今日读数 · 近一年分位
        <span class="dist-note">条越长越接近近一年极值；竖线 = 中位数（50% 分位）</span>
      </div>
      <div class="temp-grid">
        <div v-for="t in metrics.temperature" :key="t.key" class="temp-item" :title="t.desc">
          <div class="temp-head">
            <span class="temp-label">{{ t.label }}</span>
            <span class="temp-value">{{ t.value }}<em>{{ t.unit }}</em></span>
          </div>
          <div class="temp-track">
            <i v-if="t.rank != null" class="temp-fill" :class="rankTone(t)" :style="{ width: t.rank + '%' }" />
            <i class="temp-median" title="近一年中位数 = 50% 分位" />
          </div>
          <div class="temp-foot">
            <span v-if="t.rank != null">
              近一年 <b :class="rankTone(t)">{{ t.rank }}%</b> 分位
              <em v-if="!t.higher_is_hot" class="temp-rev">越高越冷</em>
            </span>
            <span v-else class="temp-pending">历史基线构建中…</span>
            <span v-if="t.median != null" class="temp-med">中位 {{ t.median }}{{ t.unit }}</span>
          </div>
        </div>
      </div>

      <!-- 市场宽度：60 日趋势，回答「涨跌是在扩散还是收敛」 -->
      <el-card shadow="never" class="dash-card width-card">
        <div class="card-title card-title--flex">
          市场宽度趋势
          <span class="dist-note">近 {{ breadthSeries.length }} 个交易日</span>
          <div v-if="bwChart" class="bw-readout">
            <span class="ro ro--up">今日上涨率 <b>{{ bwChart.today.up_pct }}%</b></span>
            <span v-if="bwChart.today.ma20_above != null" class="ro ro--ma">
              站上 20 日线 <b>{{ bwChart.today.ma20_above }}%</b>
            </span>
            <span class="ro ro--med">一年中位 {{ bwChart.today.median }}%</span>
          </div>
        </div>
        <div v-if="bwChart" class="bw-plot">
          <div class="bw-yaxis">
            <span v-for="t in bwChart.yTicks" :key="t.v" :style="{ bottom: t.v + '%' }">{{ t.v }}%</span>
          </div>
          <div class="bw-canvas">
            <div
              v-for="t in bwChart.yTicks"
              :key="'g' + t.v"
              class="bw-gline"
              :class="{ 'is-mid': t.v === 50 }"
              :style="{ bottom: t.v + '%' }"
            />
            <svg class="bw-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <linearGradient :id="'bwFill'" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--el-color-primary)" stop-opacity="0.28" />
                  <stop offset="100%" stop-color="var(--el-color-primary)" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <polygon :points="bwChart.area" :fill="'url(#bwFill)'" />
              <polyline :points="bwChart.upLine" class="bw-up" vector-effect="non-scaling-stroke" />
              <polyline
                v-for="(seg, i) in bwChart.maSegs"
                :key="'ma' + i"
                :points="seg"
                class="bw-ma"
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <!-- 今日竖线：标示曲线末端对应的交易日 -->
            <div class="bw-today" />
            <div
              v-for="d in bwChart.dots"
              :key="d.k"
              class="bw-pt"
              :style="{ left: d.xp + '%', bottom: d.yp + '%' }"
            >
              <span class="bw-tip">{{ d.tip }}</span>
            </div>
            <div
              v-for="l in bwChart.xTicks"
              :key="l.k"
              class="bw-xaxis"
              :style="{ left: l.xp + '%', transform: l.align }"
            >{{ l.text }}</div>
          </div>
        </div>
        <div v-else class="rank-empty">暂无足够交易日数据</div>
        <div class="bw-legend">
          <span class="bw-key"><i class="k-up" />上涨个股占比</span>
          <span class="bw-key"><i class="k-ma" />站上 20 日线占比</span>
          <span class="bw-key"><i class="k-mid" />50% 多空分界</span>
        </div>
        <p class="cap">
          上涨率高于 50% = 赚钱效应扩散到多数个股；连续多日低于 30% 说明下跌在扩散，指数再涨也可能只是少数权重在拉。
          站上 20 日线的比例代表中期趋势还在的个股有多少。
        </p>
      </el-card>

      <div class="mini-grid">
        <!-- 市值风格：全市场按流通市值三等分，比较各组平均涨跌幅 -->
        <el-card v-if="metrics.style" shadow="never" class="dash-card">
          <div class="card-title">
            市值风格：钱偏大还是偏小
            <span class="dist-note">全市场按流通市值三等分 · 组内平均涨跌幅</span>
          </div>
          <div v-if="styleVerdict" class="style-verdict" :class="`tone-${styleVerdict.tone}`">
            <b>{{ styleVerdict.label }}</b>
            <span>{{ styleVerdict.detail }}</span>
          </div>
          <div class="style-bars">
            <div v-for="b in metrics.style.buckets" :key="b.key" class="style-row">
              <span class="style-name">{{ b.label }}</span>
              <span class="style-count">{{ b.count }} 家</span>
              <div class="style-track">
                <i class="style-axis" />
                <i class="style-fill" :class="b.pct >= 0 ? 'is-up' : 'is-down'" :style="styleBar(b.pct)" />
              </div>
              <span class="style-val" :class="b.pct >= 0 ? 'up' : 'down'">{{ fmtPct(b.pct) }}</span>
            </div>
          </div>
          <p class="cap">
            三组是把同一批股票按流通市值从大到小排成三段（各约三分之一），比较各组今天平均涨跌幅。
            谁跌得少／涨得多，就说明资金更愿意待在那一边；横线是 0%，条在中线左侧为跌。
          </p>
        </el-card>

        <!-- 成交额集中度：头部吸金占比 + HHI -->
        <el-card v-if="metrics.concentration" shadow="never" class="dash-card">
          <div class="card-title">
            成交额集中度
            <span class="dist-note">HHI 越高，资金越集中在少数个股</span>
          </div>
          <div class="conc-bar">
            <div class="conc-seg conc-top" :style="{ width: concTopW + '%' }" :title="`前10名合计 ${metrics.concentration.top10_share}%`" />
            <div class="conc-seg conc-rest" />
          </div>
          <div class="conc-legend">
            <span class="lg-up">前10名 {{ metrics.concentration.top10_share }}%</span>
            <span class="lg-rest">其余 {{ (100 - metrics.concentration.top10_share).toFixed(1) }}%</span>
          </div>
          <div class="snap-row snap-row--tight">
            <div class="snap-item">
              <div class="snap-label">第一大占比</div>
              <div class="snap-value">{{ metrics.concentration.top1_share }}%</div>
            </div>
            <div class="snap-item">
              <div class="snap-label">HHI</div>
              <div class="snap-value">{{ metrics.concentration.hhi }}</div>
            </div>
          </div>
          <p class="cap">前 10 名占全市场成交额的比重越高，说明资金越集中、抱团少数标的，其余个股越缺流动性。</p>
        </el-card>
      </div>
    </section>

    <!-- 今日事件：只回答「几点有事、是否影响方向」，分析在综合研判 -->
    <section v-if="eventsData" class="block block--tail">
      <div class="block-head">
        <span class="block-title"><el-icon><Calendar /></el-icon> 今日事件</span>
        <span class="block-hint">{{ eventSummary }}</span>
        <span v-if="eventsData.updated" class="data-time">抓取 {{ shortTime(eventsData.updated) }}</span>
      </div>

      <div v-if="events.length" class="event-axis">
        <div class="event-track">
          <i
            v-for="t in eventTicks"
            :key="t.label"
            class="event-tick"
            :class="{ 'event-tick--open': t.open }"
            :style="{ left: t.pct + '%' }"
          >
            <span class="event-tick-label">{{ t.label }}</span>
          </i>
          <button
            v-for="e in events"
            :key="e.id"
            class="event-dot"
            :class="[`status-${e.status}`, `impact-${e.impact}`]"
            :style="{ left: eventPct(e.time) + '%' }"
            :title="`${e.time} ${e.title}（${statusLabel(e)}）`"
            @click="gotoEvents"
          />
        </div>
        <div class="event-list">
          <span
            v-for="e in visibleEvents"
            :key="e.id"
            class="event-chip"
            :class="`status-${e.status}`"
            @click="gotoEvents"
          >
            <b>{{ e.time }}</b>{{ shortTitle(e.title) }}
            <em>{{ statusLabel(e) }}</em>
          </span>
          <span v-if="events.length > visibleEvents.length" class="event-more">
            +{{ events.length - visibleEvents.length }} 件
          </span>
        </div>
      </div>

      <div v-else-if="!eventsData.source_ok" class="event-empty">
        经济日历暂不可用，仅显示手工日程（当前无）
      </div>
      <div v-else class="event-empty">今日无重大宏观事件，按原计划执行</div>
    </section>

    <!-- 免责声明 -->
    <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'ReviewOverview' })
import { ref, computed, onMounted, onActivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  DataLine,
  Refresh,
  Loading,
  Histogram,
  Calendar,
} from '@element-plus/icons-vue'
import {
  vibeApi,
  type IndexQuote,
  type MarketDashboard,
  type MarketEvent,
  type MarketEvents,
  type MarketMetrics,
  type MarketTemperatureItem,
  type PreOpen,
  type PreOpenBand,
} from '@/api/vibe'
import { fmtPrice, fmtPct, fmtAbsPct, fmtSigned } from '@/utils/format'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'

const loading = ref(false)
const indices = ref<IndexQuote[]>([])
const dashboard = ref<MarketDashboard | null>(null)
const metrics = ref<MarketMetrics | null>(null)
const router = useRouter()

const shortTime = (v?: string | null) =>
  v ? formatBeijingDateTimeMinute(String(v)) : ''

// ── 开盘情景：隔夜外盘定档开盘缺口 + 上一交易日情绪结构（盘前唯一的前瞻信息） ──
const preOpen = ref<PreOpen | null>(null)
const preOpenLoading = ref(false)
const preOpenOpen = ref(isPreOpenWindow())

function isPreOpenWindow(): boolean {
  // 北京时间 08:30–09:25 自动展开；其余时段默认收起，避免干扰盘中/收盘复盘
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date())
  const val = (t: string) => Number(parts.find(p => p.type === t)?.value || 0)
  const hm = val('hour') * 60 + val('minute')
  return hm >= 8 * 60 + 30 && hm <= 9 * 60 + 25
}

async function loadPreOpen(refresh = false) {
  preOpenLoading.value = true
  try {
    const res = await vibeApi.getPreOpen(refresh)
    preOpen.value = (res as any).data || null
  } catch (e: any) {
    // 盘前块是增强信息，失败不打断看板主数据
    console.warn('[Overview] 开盘情景加载失败:', e?.message || e)
  } finally {
    preOpenLoading.value = false
  }
}

const signedPct = (v?: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const deltaText = (v?: number | null, unit = '') =>
  v == null || v === 0 ? '' : `${v > 0 ? '+' : ''}${v}${unit}`
const deltaClass = (v?: number | null) => (v == null || v === 0 ? 'flat' : v > 0 ? 'up' : 'down')
const bandRange = (b: PreOpenBand) => {
  if (b.lo == null) return `≤ ${b.hi}%`
  if (b.hi == null) return `≥ ${b.lo}%`
  return `${b.lo} ~ ${b.hi}%`
}

// 指针位置：把 -1.5%~+1.5% 线性映射到 0~100%，与刻度区间的成比例宽度对齐
const scenarioPointerPct = computed(() => {
  const pct = preOpen.value?.gap.pct
  if (pct == null) return null
  const raw = ((Math.max(-1.5, Math.min(1.5, pct)) + 1.5) / 3) * 100
  return Math.min(97, Math.max(3, raw))
})

// 标题日期：优先后端数据返回的交易日；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => dashboard.value?.trade_date || tradeDate.value || '')

// 页头「更新于」：展示看板数据的生成时刻
const updatedAt = computed(() =>
  dashboard.value?.updated ? formatBeijingDateTimeMinute(dashboard.value.updated) : ''
)

// 数据时点：与「抓取时刻」分开，避免把周末刷新当成数据新鲜
const dataAsOf = computed(() => {
  const a = dashboard.value?.as_of
  if (!a) return ''
  const s = String(a)
  return s.length >= 16 ? s.slice(5, 16) : s
})

// 标题星期：让用户一眼确认是不是交易日当天
const weekday = computed(() => {
  const d = titleDate.value
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return ''
  const dt = new Date(`${d}T00:00:00+08:00`)
  return `周${'日一二三四五六'[dt.getDay()]}`
})

// 盘中 / 休市：同一份数据在收盘后看到，语义完全不同
function beijingClock() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date())
  const val = (t: string) => parts.find(p => p.type === t)?.value || ''
  return { wd: val('weekday'), hm: Number(val('hour')) * 60 + Number(val('minute')) }
}
const marketState = computed(() => {
  const { wd, hm } = beijingClock()
  const weekdayOk = wd !== 'Sat' && wd !== 'Sun'
  const trading = (hm >= 570 && hm <= 690) || (hm >= 780 && hm <= 900)
  return weekdayOk && trading
    ? { label: '盘中', cls: 'is-open' }
    : { label: '休市', cls: 'is-closed' }
})

// ── 今日事件：看板只展示时间与状态，影响分析在综合研判页 ──
const eventsData = ref<MarketEvents | null>(null)
const events = computed<MarketEvent[]>(() => eventsData.value?.events || [])
const visibleEvents = computed(() => events.value.slice(0, 3))
const eventSummary = computed(() => {
  const list = events.value
  if (!list.length) return '今日无重大宏观事件'
  const dir = list.filter(e => e.impact === 'direction')
  const vol = list.filter(e => e.impact === 'volatility')
  if (dir.length) return `今日 ${list.length} 件 · ${dir.length} 件可能改变方向`
  if (vol.length) return `今日 ${list.length} 件 · 均不改方向，注意 ${vol[0].time} 前后波动`
  return `今日 ${list.length} 件 · 均不改变判断`
})
const shortTitle = (t: string) => (t.length > 14 ? `${t.slice(0, 14)}…` : t)
const statusLabel = (e: MarketEvent) =>
  e.status === 'pending' ? '待公布' : e.status === 'expired' ? '已过时' : '已公布'
const eventPct = (t: string) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t)
  if (!m) return 50
  const mins = Number(m[1]) * 60 + Number(m[2])
  return Math.min(99, Math.max(1, (mins / 1440) * 100))
}
const eventTicks = [
  { label: '00:00', pct: 0 },
  { label: '09:30 开盘', pct: (570 / 1440) * 100, open: true },
  { label: '12:00', pct: 50 },
  { label: '15:00', pct: (900 / 1440) * 100 },
  { label: '24:00', pct: 99 },
]
const gotoEvents = () => router.push('/vibe/synthesis#events')

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

// 一句话结论：先给判断，再让下面各块去支撑它
const verdictText = computed(() => {
  const d = dashboard.value
  if (!d) return ''
  const up = d.breadth.up_pct
  const breadthWord =
    up >= 60 ? '个股普涨' : up >= 45 ? '涨跌家数接近' : up >= 30 ? '个股偏跌' : '个股普跌'
  const zt = d.limit?.limit_up ?? 0
  const dt = d.limit?.limit_down ?? 0
  const amount = metrics.value?.temperature?.find((t) => t.key === 'amount')
  let posWord = ''
  if (amount?.rank != null) {
    posWord = amount.rank >= 75
      ? `，成交额处近一年 ${amount.rank}% 高位`
      : amount.rank <= 25
        ? `，成交额处近一年 ${amount.rank}% 低位`
        : `，成交额处近一年 ${amount.rank}% 分位`
  }
  return `${breadthWord}：上涨 ${up}%，涨停 ${zt} 家 / 跌停 ${dt} 家${posWord}。`
})

// 涨跌分布两端口径：与短线情绪页同源时不额外解释，仅降级时提示
const limitNote = computed(() =>
  dashboard.value?.limit?.source === 'threshold'
    ? '封板池暂不可用 · 涨停/跌停按涨跌幅阈值近似'
    : '涨停/跌停取封板池，与「短线情绪」页一致'
)

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
// 50 分中性基准环：与数据多边形同一套角度，便于直接比较「是否达标」
const radarMidPolygon = computed(() => {
  const n = dashboard.value?.radar?.length || 0
  if (!n) return ''
  return Array.from({ length: n }, (_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n
    const r = RADAR_MAX_R * 0.5
    return `${RADAR_CX + Math.cos(angle) * r},${RADAR_CY + Math.sin(angle) * r}`
  }).join(' ')
})
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
  count <= 0 ? 0 : Math.max(4, (count / distMax.value) * 86)

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

// 涨跌分布 tooltip：标注两端口径来源（封板池 / 阈值近似）
const distTip = (b: { label: string; count: number }) => {
  const note = (b.label === '涨停' || b.label === '跌停')
    ? (dashboard.value?.limit?.source === 'threshold'
      ? '（按涨跌幅阈值近似，含接近未封死）'
      : '（封板池口径，与短线情绪页一致）')
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

// ── 市场温度与结构：分位 / 宽度曲线 / 风格 / 集中度 ──
const breadthSeries = computed(() => metrics.value?.breadth?.series || [])

// 分位配色：热度指标高分为热（红），低分为冷（绿），中间中性
const rankTone = (t: MarketTemperatureItem) => {
  if (t.rank == null) return 'is-muted'
  // 反向指标（跌停家数）：分位越高说明越冷，配色需翻转，避免「高跌停=红色热」的误读
  const hot = t.higher_is_hot ? t.rank : 100 - t.rank
  return hot >= 75 ? 'is-hot' : hot <= 25 ? 'is-cold' : 'is-neutral'
}

// 宽度曲线：上涨率（实线+渐变面积）与站上20日线占比（虚线）同为 0-100%，共用一根纵轴。
// SVG 用 0-100 归一坐标（preserveAspectRatio="none"）保证任意宽度都能铺满；
// 文字/圆点改为 HTML 定位，避免非等比缩放下文字被横向拉扁。
const bwChart = computed(() => {
  const pts = breadthSeries.value
  if (pts.length < 3) return null
  const n = pts.length
  const xp = (i: number) => (i / (n - 1)) * 100
  // SVG 的 y 轴向下为正，故取 100 - 值；HTML 定位用 bottom = 值
  const yp = (v: number) => 100 - Math.max(0, Math.min(100, v))

  const upLine = pts.map((p, i) => `${xp(i).toFixed(2)},${yp(p.up_pct).toFixed(2)}`).join(' ')
  const area = `0,100 ${upLine} 100,100`

  // 虚线遇缺失值断开，避免把缺口连成一条假趋势
  const maSegs: string[] = []
  let cur: string[] = []
  pts.forEach((p, i) => {
    if (p.ma20_above == null) {
      if (cur.length) { maSegs.push(cur.join(' ')); cur = [] }
    } else {
      cur.push(`${xp(i).toFixed(2)},${yp(p.ma20_above).toFixed(2)}`)
    }
  })
  if (cur.length) maSegs.push(cur.join(' '))

  const dots = pts
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % 6 === 0 || i === n - 1)
    .map(({ p, i }) => ({
      k: `${p.date}-${i}`,
      xp: xp(i),
      yp: Math.max(0, Math.min(100, p.up_pct)),
      ma: p.ma20_above != null,
      tip: `${p.date} · 上涨率 ${p.up_pct}%${p.ma20_above == null ? '' : ` · 站上20日线 ${p.ma20_above}%`}`,
    }))

  const xTicks = [0, Math.floor(n / 2), n - 1].map((i, idx) => ({
    k: `x-${i}`,
    xp: xp(i),
    text: String(pts[i].date || '').slice(5),
    align: idx === 0 ? 'translateX(0)' : idx === 2 ? 'translateX(-100%)' : 'translateX(-50%)',
  }))

  // 一年中位上涨率：作为「常态水位」参照，让今天的 13.9% 一眼看出偏离多少
  const sorted = pts.map(p => p.up_pct).sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]

  return {
    upLine,
    area,
    maSegs,
    dots,
    xTicks,
    yTicks: [0, 25, 50, 75, 100].map(v => ({ v })),
    today: { ...pts[n - 1], median: Math.round(median * 10) / 10 },
  }
})

// 市值风格结论：先说「钱偏大还是偏小」，再看三根条验证
const styleVerdict = computed(() => {
  const s = metrics.value?.style
  if (!s?.buckets?.length) return null
  const spread = s.spread
  const allDown = s.buckets.every(b => b.pct < 0)
  const allUp = s.buckets.every(b => b.pct > 0)
  const big = spread >= 0
  const label = big ? '资金相对偏大盘' : '资金相对偏小盘'
  let detail = big
    ? '大盘组表现最好，权重更抗跌、更受资金照顾'
    : '小盘组表现最好，题材更活跃、弹性更大'
  if (allDown) {
    detail = big
      ? `三组都在跌，但越小盘跌得越多（差 ${Math.abs(spread).toFixed(2)} 个百分点），抛压集中在小盘`
      : `三组都在跌，但越小盘跌得越少（差 ${Math.abs(spread).toFixed(2)} 个百分点），小盘相对抗跌`
  } else if (allUp) {
    detail = big
      ? `三组都在涨，大盘涨得更多（多 ${Math.abs(spread).toFixed(2)} 个百分点），资金抱团权重`
      : `三组都在涨，小盘涨得更多（多 ${Math.abs(spread).toFixed(2)} 个百分点），资金更愿意做题材`
  }
  return { label, detail, tone: big ? 'defense' : 'offense' }
})

const concTopW = computed(() => Math.min(100, Math.max(0, metrics.value?.concentration?.top10_share || 0)))

const styleMax = computed(() =>
  Math.max(1, ...(metrics.value?.style?.buckets || []).map(b => Math.abs(b.pct)))
)
// 风格条以中线为 0 轴，条长按组内最大绝对涨跌幅归一（涨向右 / 跌向左）
const styleBar = (pct: number) => {
  const w = Math.max(4, Math.round((Math.abs(pct) / styleMax.value) * 50))
  return pct >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }
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

const loadAshare = async (refresh = false) => {
  loading.value = true
  // 开盘情景独立加载：不阻塞指数/看板，失败也不计入页头告警
  loadPreOpen(refresh)
  try {
    const results = await Promise.allSettled([
      withTimeout(vibeApi.getIndices(), 15000),
      withTimeout(vibeApi.getDashboard(refresh), 60000),
      withTimeout(vibeApi.getMarketEvents(refresh), 25000),
      withTimeout(vibeApi.getMarketMetrics(refresh), 20000),
    ])

    // 逐个处理结果，失败不影响其他数据显示
    const [idxRes, dashRes, evtRes, metRes] = results
    if (idxRes.status === 'fulfilled') {
      indices.value = (idxRes.value as any).data || []
    }
    if (dashRes.status === 'fulfilled') {
      dashboard.value = (dashRes.value as any).data || null
    }
    if (evtRes.status === 'fulfilled') {
      eventsData.value = (evtRes.value as any).data || null
    }
    if (metRes.status === 'fulfilled') {
      metrics.value = (metRes.value as any).data || null
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
  loadAshare()
  startAutoRefresh()
})

// 页头刷新：绕过前端缓存，确保拿到最新
const refreshOverview = () => loadAshare(true)

// 盘中每 60 秒静默刷新一次：只刷数据，不触发 AI 研判；页面隐藏时暂停
let autoTimer: number | undefined
function startAutoRefresh() {
  stopAutoRefresh()
  autoTimer = window.setInterval(() => {
    if (document.hidden) return
    if (marketState.value.cls !== 'is-open') return
    loadAshare(true)
  }, 60000)
}
function stopAutoRefresh() {
  if (autoTimer) {
    window.clearInterval(autoTimer)
    autoTimer = undefined
  }
}
onUnmounted(stopAutoRefresh)

// keep-alive 恢复时刷新一次
let overviewInited = false
onActivated(() => {
  if (overviewInited) loadAshare(true)
  overviewInited = true
  startAutoRefresh()
})
</script>

<style scoped>
.vibe-overview {
  padding: 4px;
}

.block {
  margin-bottom: 24px;
}

/* 页尾汇总块：与上方内容拉开层次 */
.block--tail {
  margin-top: 8px;
  padding-top: 18px;
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 区块级数据时间：标注该块数据自身的生成时刻，避免与页头「更新于」混淆 */
.data-time {
  font-size: 11.5px;
  font-style: normal;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
  margin-left: 8px;
}

/* 页头：星期、盘中/休市、数据时点。三者组合用于回答「这份数据是不是今天的」 */
.title-weekday {
  font-style: normal;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}
.market-state {
  padding: 1px 7px;
  border-radius: 9px;
  font-size: 11.5px;
  line-height: 18px;
  border: 1px solid transparent;
}
.market-state.is-open {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}
.market-state.is-closed {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-lighter);
}
.hero-link {
  font-size: 12.5px;
  color: var(--el-color-primary);
  text-decoration: none;
  margin-right: 4px;
}
.hero-link:hover {
  text-decoration: underline;
}

/* ── 一句话结论：先给判断 ── */
.verdict {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin-bottom: 18px;
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 3px solid var(--el-color-primary);
}

.verdict-tag {
  flex: 0 0 auto;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12.5px;
  font-weight: 600;
}

.verdict-text {
  flex: 1 1 320px;
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-primary);
}

.verdict-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

.verdict-meta em {
  font-style: normal;
  padding: 1px 7px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.verdict-meta em.is-live {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

@media (max-width: 768px) {
  .verdict-text { flex-basis: 100%; order: 3; }
  .verdict-meta { margin-left: auto; }
}

/* 每张图一句话：这图在说什么、怎么用 */
.cap {
  margin: 10px 0 0;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

/* ── 市场温度与结构 ── */
.alert-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.alert-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  border: 1px solid transparent;
}

.alert-chip b {
  font-weight: 600;
}

.alert-chip.is-danger {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}

.alert-chip.is-warning {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  border-color: var(--el-color-warning-light-7);
}

.alert-chip.is-info {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}

.alert-chip.is-ok {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}

.alert-row--calm {
  margin-bottom: 10px;
}

/* 温度分位卡：一条分位条 + 中位刻度（50%） */
.temp-headline {
  margin: 2px 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.temp-headline .dist-note {
  display: inline;
  margin: 0 0 0 10px;
  font-weight: 400;
}

.temp-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}

.temp-item {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}

.temp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.temp-label {
  font-size: 12.5px;
  color: var(--el-text-color-regular);
}

.temp-value {
  font-family: var(--app-font-mono);
  font-size: 18px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.temp-value em {
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 2px;
}

.temp-track {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
  margin: 10px 0 6px;
}

.temp-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.temp-fill.is-hot { background: var(--app-up); }
.temp-fill.is-cold { background: var(--app-down); }
.temp-fill.is-neutral { background: var(--el-color-primary); }
.temp-fill.is-muted { background: var(--el-border-color); }

.temp-median {
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--el-text-color-placeholder);
  opacity: 0.7;
}

.temp-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.temp-foot b.is-hot { color: var(--app-up); }
.temp-foot b.is-cold { color: var(--app-down); }
.temp-foot b.is-neutral { color: var(--el-color-primary); }
.temp-foot b.is-muted { color: var(--el-text-color-placeholder); }

.temp-med {
  color: var(--el-text-color-placeholder);
}

/* 反向指标标注（跌停家数：分位越高越冷） */
.temp-rev {
  font-style: normal;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-light);
}

.temp-pending {
  color: var(--el-text-color-placeholder);
}

/* 宽度曲线（整行） */
.width-card {
  margin-bottom: 12px;
}

/* 宽度趋势图：SVG 只画线面，刻度/圆点/标签用 HTML 定位，任意宽度都不变形 */
.bw-readout {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-left: auto;
}

.ro {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 400;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.ro b {
  font-family: var(--app-font-mono);
  font-weight: 600;
}

.ro--up b { color: var(--el-color-primary); }
.ro--ma b { color: var(--el-text-color-primary); }
.ro--med { color: var(--el-text-color-placeholder); }

.bw-plot {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}

.bw-yaxis {
  position: relative;
  flex: 0 0 32px;
  height: 176px;
}

.bw-yaxis span {
  position: absolute;
  right: 0;
  transform: translateY(50%);
  font-size: 9.5px;
  line-height: 1;
  color: var(--el-text-color-placeholder);
}

.bw-canvas {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 176px;
  margin-bottom: 16px;
}

.bw-gline {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--el-border-color-lighter);
}

.bw-gline.is-mid {
  background: var(--el-border-color);
  background-image: linear-gradient(90deg, var(--el-border-color) 50%, transparent 50%);
  background-size: 8px 1px;
}

.bw-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.bw-up {
  stroke: var(--el-color-primary);
  stroke-width: 2;
  stroke-linejoin: round;
  fill: none;
}

.bw-ma {
  stroke: var(--el-text-color-secondary);
  stroke-width: 1.4;
  stroke-dasharray: 4 3;
  fill: none;
  opacity: 0.9;
}

/* 今日竖线，标出曲线末端 */
.bw-today {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 0;
  border-left: 1px dashed var(--el-color-primary-light-5);
}

.bw-pt {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  transform: translate(-50%, 50%);
  box-shadow: 0 0 0 1.5px var(--el-bg-color);
  z-index: 2;
}

.bw-tip {
  position: absolute;
  left: 50%;
  bottom: 11px;
  transform: translateX(-50%);
  padding: 3px 7px;
  border-radius: 5px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--el-box-shadow-light);
  font-size: 11px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.12s;
  z-index: 4;
}

.bw-pt:hover .bw-tip {
  opacity: 1;
}

.bw-xaxis {
  position: absolute;
  bottom: -16px;
  font-size: 10px;
  line-height: 1;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}

.bw-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.bw-key {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.bw-key i {
  display: inline-block;
  width: 14px;
  height: 2px;
  border-radius: 1px;
  background: var(--el-color-primary);
}

.bw-key i.k-ma {
  height: 0;
  border-top: 1.5px dashed var(--el-text-color-secondary);
  background: none;
}

.bw-key i.k-mid {
  height: 0;
  border-top: 1px dashed var(--el-border-color);
  background: none;
  width: 10px;
}

/* 结构快照 */
.snap-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.snap-row--tight {
  grid-template-columns: repeat(2, 1fr);
  margin-top: 12px;
}

.snap-item {
  min-width: 0;
}

.snap-label {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.snap-value {
  font-family: var(--app-font-mono);
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.4;
}

/* 风格轮动 + 成交额集中度 */
.mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: stretch;
}

.style-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 4px 0 10px;
}

.style-row {
  display: grid;
  grid-template-columns: 34px 48px 1fr 66px;
  align-items: center;
  gap: 8px;
}

.style-name {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.style-count {
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}

/* 市值风格结论条：先给「钱偏哪边」，条形图只作佐证 */
.style-verdict {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin: 2px 0 12px;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}

.style-verdict b {
  font-size: 12.5px;
  white-space: nowrap;
}

.style-verdict span {
  color: var(--el-text-color-regular);
}

.style-verdict.tone-defense {
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-info);
}

.style-verdict.tone-offense {
  background: var(--el-color-danger-light-9);
  border-left: 3px solid var(--el-color-danger);
}

.style-track {
  position: relative;
  height: 10px;
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
}

.style-axis {
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--el-border-color);
}

.style-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 3px;
}

.style-fill.is-up {
  background: linear-gradient(90deg, #f8a5a0 0%, #f56c6c 100%);
  border-radius: 0 3px 3px 0;
}

.style-fill.is-down {
  background: linear-gradient(90deg, #67c23a 0%, #95d475 100%);
  border-radius: 3px 0 0 3px;
}

.style-val {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  text-align: right;
}

/* 集中度条 */
.conc-bar {
  display: flex;
  height: 10px;
  border-radius: 3px;
  overflow: hidden;
  margin: 6px 0 6px;
  background: var(--el-fill-color-lighter);
}

.conc-seg {
  height: 100%;
}

.conc-top {
  background: var(--el-color-primary);
  opacity: 0.85;
}

.conc-rest {
  flex: 1;
  background: var(--el-fill-color-dark);
}

.conc-legend {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

.conc-legend .lg-up { color: var(--el-color-primary); }
.conc-legend .lg-rest { color: var(--el-text-color-placeholder); }

.rank-empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 8px 0;
}

/* ── 今日事件：一条时间轴回答「几点有事」，不在此处放影响判断 ── */
.event-axis {
  padding: 6px 4px 0;
}
.event-track {
  position: relative;
  height: 26px;
  margin: 0 10px;
  border-top: 1px solid var(--el-border-color);
}
.event-tick {
  position: absolute;
  top: -1px;
  width: 1px;
  height: 6px;
  background: var(--el-border-color);
}
.event-tick--open {
  height: 10px;
  background: var(--el-color-primary-light-5);
}
.event-tick-label {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}
.event-dot {
  position: absolute;
  top: 0;
  width: 8px;
  height: 8px;
  margin: -4px 0 0 -4px;
  padding: 0;
  border-radius: 50%;
  border: 1.5px solid var(--el-border-color-darker);
  background: var(--el-fill-color-blank);
  cursor: pointer;
  transition: transform 0.15s ease;
}
.event-dot:hover {
  transform: scale(1.35);
}
.event-dot.status-released,
.event-dot.status-expired {
  background: var(--el-border-color-darker);
}
.event-dot.status-expired {
  opacity: 0.4;
}
.event-dot.impact-volatility {
  border-color: var(--el-color-warning);
}
.event-dot.impact-direction {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
}
.event-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 30px;
}
.event-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  color: var(--el-text-color-regular);
  cursor: pointer;
}
.event-chip:hover {
  background: var(--el-fill-color);
}
.event-chip b {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.event-chip em {
  font-style: normal;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.event-chip.status-pending em {
  color: var(--el-color-warning);
}
.event-more {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.event-empty {
  padding: 6px 4px;
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}

/* ── 开盘情景：结论先行，刻度+明细两层，弱化装饰只保留方向色 ── */
.preopen-block {
  margin-bottom: 20px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-blank);
}

.preopen-block--loading {
  display: flex;
  align-items: center;
  gap: 10px;
}

.preopen-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.preopen-kicker {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--el-text-color-placeholder);
}

.preopen-verdict {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.preopen-verdict em {
  font-style: normal;
  font-family: var(--app-font-mono);
  font-size: 15px;
  font-weight: 600;
  margin-left: 6px;
}

.preopen-basis {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.preopen-tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.preopen-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.preopen-actions .data-time { margin-left: 0; }

.preopen-toggle {
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  user-select: none;
}

.preopen-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}

.tone-up { color: var(--app-up); }
.tone-down { color: var(--app-down); }
.tone-flat { color: var(--el-text-color-primary); }

/* 五档刻度：区间宽度与幅度成比例（-1.5% ~ +1.5%，每 0.1% = 1 份） */
.scenario-scale {
  position: relative;
  padding-top: 10px;
}

.scenario-track {
  display: grid;
  grid-template-columns: 5fr 7fr 6fr 7fr 5fr;
  gap: 2px;
}

.scenario-seg {
  padding: 7px 4px 6px;
  text-align: center;
  border: 1px solid transparent;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.scenario-seg .seg-label {
  display: block;
  font-size: 12px;
  line-height: 1.3;
}

.scenario-seg .seg-range {
  display: block;
  margin-top: 2px;
  font-family: var(--app-font-mono);
  font-size: 10px;
  opacity: 0.65;
  white-space: nowrap;
}

.scenario-seg.active {
  font-weight: 600;
}

.scenario-seg.active.tone-up {
  background: rgba(245, 108, 108, 0.1);
  border-color: var(--app-up);
  color: var(--app-up);
}

.scenario-seg.active.tone-down {
  background: rgba(103, 194, 58, 0.1);
  border-color: var(--app-down);
  color: var(--app-down);
}

.scenario-seg.active.tone-flat {
  background: var(--el-fill-color);
  border-color: var(--el-border-color);
  color: var(--el-text-color-primary);
}

.scenario-ptr {
  position: absolute;
  top: 0;
  width: 0;
  height: 0;
  transform: translateX(-50%);
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 7px solid currentColor;
}

.preopen-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.meta-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.meta-label {
  flex: 0 0 58px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.meta-items {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 20px;
}

.meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
}

.meta-item b {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.meta-item i {
  font-style: normal;
  font-family: var(--app-font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.meta-item em {
  font-style: normal;
  font-size: 11px;
}

.meta-item--key b {
  color: var(--el-text-color-regular);
}

.meta-item--key i {
  font-size: 15px;
}

.meta-date {
  margin-left: auto;
  font-family: var(--app-font-mono);
  font-size: 10.5px;
  color: var(--el-text-color-placeholder);
}

.meta-item em.up,
.meta-item i.up { color: var(--app-up); }
.meta-item em.down,
.meta-item i.down { color: var(--app-down); }
.meta-item em.flat { color: var(--el-text-color-placeholder); }

.preopen-note {
  font-size: 11px;
  line-height: 1.5;
  color: var(--el-text-color-placeholder);
}

@media (max-width: 900px) {
  .preopen-verdict { font-size: 18px; }
  .scenario-seg .seg-label { font-size: 11px; }
  .scenario-seg .seg-range { display: none; }
  .meta-label { flex-basis: 100%; }
  .meta-row { flex-direction: column; gap: 4px; }
  .meta-date { margin-left: 0; }
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

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 768px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
}

/* ===== 市场看板（借鉴 tickflow Dashboard）===== */
.kpi-sep {
  color: var(--el-text-color-placeholder);
  margin: 0 3px;
  font-weight: 400;
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

/* 标题行内并排放尾部读数（宽度趋势卡片用） */
.card-title--flex {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
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

/* 分布图脚注：强弱股与平均涨跌（替代原 KPI 行） */
.dist-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.dist-foot b {
  font-family: var(--app-font-mono);
  font-weight: 600;
}

.dist-foot b.up { color: var(--app-up); }
.dist-foot b.down { color: var(--app-down); }

@media (max-width: 1200px) {
  .temp-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 900px) {
  .mini-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .dash-main { grid-template-columns: 1fr; }
  .temp-grid { grid-template-columns: repeat(2, 1fr); }
  .bw-canvas { height: 140px; }
  .bw-yaxis { height: 140px; }
  .snap-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
}
</style>
