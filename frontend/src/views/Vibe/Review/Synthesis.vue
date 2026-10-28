<template>
  <div class="vibe-synthesis app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 综合研判</h2>
          <p class="page-hero-sub">汇聚大盘 / 情绪 / 趋势 / 资讯四维数据，AI 综合研判市场方向</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">数据 {{ dataAsOf || '—' }} · 研判 {{ updatedAt || '—' }}</span>
        <span v-if="syn && !syn.llm_available" class="syn-degraded">
          规则兜底
          <em @click="loadAll(true)">重试 AI 研判</em>
        </span>
        <span v-if="loading && syn" class="syn-refresh-hint">
          <el-icon class="is-loading"><Loading /></el-icon> 正在重新研判…
        </span>
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll(true)">
          AI 重新研判
        </el-button>
      </div>
    </div>

    <!-- 首次加载骨架（已有结论时保留旧内容，仅按钮显示刷新态） -->
    <div v-if="loading && !syn" class="syn-loading">
      <el-skeleton :rows="6" animated />
      <div class="syn-loading-tip">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在加载综合研判（命中缓存秒开，冷启动需 10~60 秒）…
      </div>
    </div>

    <!-- 数据渲染 -->
    <template v-else>
      <section v-if="verdict" class="syn-hero" :class="'syn-hero--' + verdict.dirClass">
        <div class="syn-hero-glow"></div>

        <!-- 顶部：方向 + 信心度 + 标签 -->
        <div class="syn-hero-top">
          <div class="syn-direc-wrap">
            <span class="syn-direc-zh">{{ verdict.directionZh }}方向</span>
            <span class="syn-direc-main">{{ verdict.direction }}</span>
          </div>
          <el-popover
            v-if="verdict.confidence != null"
            placement="bottom"
            :width="272"
            trigger="hover"
            :disabled="!events.length"
          >
            <template #reference>
              <div class="syn-conf-wrap">
                <div class="syn-conf-ring" :style="confRingStyle">
                  <span class="syn-conf-num">{{ verdict.confidence }}</span>
                  <span class="syn-conf-unit">%</span>
                </div>
                <span class="syn-conf-label">信心度<em v-if="events.length" class="conf-badge">含事件</em></span>
              </div>
            </template>
            <div class="conf-pop">
              <div class="conf-pop-title">信心度已计入以下事件（只修正，不覆盖趋势判断）</div>
              <div v-for="e in events" :key="e.id" class="conf-pop-row">
                <span>{{ e.time }} {{ shortTitle(e.title) }}</span>
                <em :class="`dir-${e.direction}`">{{ dirLabel(e.direction) }}</em>
              </div>
            </div>
          </el-popover>
          <div class="syn-tags">
            <el-tag v-if="syn?.llm_available" size="small" type="danger" effect="dark">AI 研判</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">规则兜底</el-tag>
          </div>
        </div>

        <!-- 总研判结论 -->
        <div class="syn-hero-concl">
          <div class="syn-concl-text">{{ verdict.conclusion }}</div>
        </div>

        <!-- 首屏决策卡：主攻 / 回避 / 仓位（回答「今天怎么办」，一眼可见） -->
        <div class="syn-decision" v-if="hasOperationPoints">
          <div class="syn-dec-card syn-dec-card--main" v-if="verdict.operation_points.main_direction">
            <div class="syn-dec-label">主攻</div>
            <div class="syn-dec-text">{{ verdict.operation_points.main_direction }}</div>
          </div>
          <div class="syn-dec-card syn-dec-card--avoid" v-if="verdict.operation_points.avoid_direction">
            <div class="syn-dec-label">回避</div>
            <div class="syn-dec-text">{{ verdict.operation_points.avoid_direction }}</div>
          </div>
          <div class="syn-dec-card syn-dec-card--pos" v-if="verdict.operation_points.position_discipline">
            <div class="syn-dec-label">仓位</div>
            <div class="syn-dec-text">{{ verdict.operation_points.position_discipline }}</div>
          </div>
        </div>

      </section>

      <!-- 今日事件影响：只在这里做深度分析（看板只给时间轴），可直接修正主攻/回避/仓位 -->
      <section v-if="eventsData" id="events" class="syn-events">
        <div class="syn-events-head">
          <span class="syn-events-title"><el-icon><Calendar /></el-icon> 今日事件影响</span>
          <span class="syn-events-hint">{{ eventHeadline }}</span>
          <span v-if="eventsData.updated" class="data-time">更新 {{ shortTime(eventsData.updated) }}</span>
        </div>

        <div v-if="events.length" class="ev-list">
          <el-card
            v-for="e in events"
            :key="e.id"
            shadow="never"
            class="ev-card"
            :class="[`impact-${e.impact}`, { 'is-expired': e.status === 'expired' }]"
          >
            <div class="ev-row ev-main">
              <span class="ev-time">{{ e.time }}</span>
              <span class="ev-title">{{ e.title }}</span>
              <span v-if="e.surprise_label" class="ev-surprise" :class="surpriseClass(e)">
                {{ e.surprise_label }}
              </span>
              <span class="ev-status" :class="`status-${e.status}`">{{ eventStatusLabel(e) }}</span>
              <span class="ev-toggle" @click="toggleEvent(e.id)">
                {{ expandedEvents.includes(e.id) ? '收起' : '展开' }}
              </span>
            </div>

            <div class="ev-row ev-impact">
              <span class="ev-label">影响</span>
              <span class="ev-impact-val" :class="`dir-${e.direction}`">{{ impactText(e) }}</span>
            </div>

            <div v-if="e.action" class="ev-row ev-action">
              <span class="ev-label">怎么做</span>
              <span>{{ e.action }}</span>
            </div>

            <div v-if="e.sectors && e.sectors.length" class="ev-row ev-sectors">
              <span class="ev-label">相关</span>
              <span v-for="s in e.sectors" :key="s" class="ev-tag">{{ s }}</span>
            </div>

            <div v-if="expandedEvents.includes(e.id)" class="ev-detail">
              <div v-if="e.transmission && e.transmission.length" class="ev-trans">
                <span v-for="(t, i) in e.transmission" :key="i" class="ev-trans-step">
                  {{ t }}<em v-if="i < e.transmission.length - 1">→</em>
                </span>
              </div>
              <div v-if="e.watch" class="ev-watch">观察点：{{ e.watch }}</div>
            </div>
          </el-card>
        </div>
        <div v-else-if="!eventsData.source_ok" class="ev-empty">
          经济日历暂不可用，事件影响暂缺；不影响上方研判结论
        </div>
        <div v-else class="ev-empty">今日无重大宏观事件，按原计划执行</div>
      </section>

      <div v-if="!verdict" class="syn-missing">
        <el-empty :image-size="72" description="本次未获取到研判结论（AI 与规则兜底均不可用），可点「AI 重新研判」重试" />
      </div>

      <!-- 买卖清单：盘中实时计算，与上方 AI 文字研判相互独立 -->
      <section v-if="syn" class="syn-guide">
        <div class="syn-guide-head">
          <span class="syn-guide-title"><el-icon><TrendCharts /></el-icon> 今日买卖清单</span>
          <span class="syn-guide-hint">盘中实时计算 · 与上方文字研判相互独立</span>
        </div>
        <div class="syn-guide-grid">
          <div class="syn-guide-col">
            <div class="syn-guide-col-head">
              <span class="buy">买入关注</span>
              <span class="syn-guide-count">{{ buyList.length }} 只</span>
            </div>
            <div v-for="b in buyList" :key="'b-' + b.code" class="syn-guide-item">
              <div class="syn-guide-row">
                <router-link target="_blank" rel="noopener" :to="`/stocks/${b.code}`" class="syn-guide-name">{{ b.name || b.code }}</router-link>
                <span class="syn-guide-code">{{ b.code }}</span>
                <el-tag size="small" :type="buyTagType(b)" effect="plain">{{ buyStateLabel(b) }}</el-tag>
              </div>
              <div class="syn-guide-metrics">
                <span>现价 <b class="mono">{{ fmtPrice(b.last_price) }}</b></span>
                <span>触发价 <b class="mono">{{ fmtPrice(b.trigger_price) }}</b></span>
                <span v-if="b.distance_pct != null" :class="{ 'is-near': isNear(b.distance_pct) }">
                  偏离 <b class="mono">{{ fmtPct(b.distance_pct) }}</b>
                </span>
              </div>
              <div class="syn-guide-advice">{{ b.advice || '等待实时价确认触发' }}</div>
            </div>
            <div v-if="!buyList.length" class="syn-guide-empty">暂无待触发的买入计划</div>
          </div>

          <div class="syn-guide-col">
            <div class="syn-guide-col-head">
              <span class="sell">持仓卖出</span>
              <span class="syn-guide-count">{{ sellList.length }} 只</span>
            </div>
            <div v-for="s in sellList" :key="'s-' + s.code" class="syn-guide-item">
              <div class="syn-guide-row">
                <router-link target="_blank" rel="noopener" :to="`/stocks/${s.code}`" class="syn-guide-name">{{ s.name || s.code }}</router-link>
                <span class="syn-guide-code">{{ s.code }}</span>
                <el-tag size="small" :type="sellTagType(s)" effect="plain">{{ s.advice_label || s.advice || '持有' }}</el-tag>
              </div>
              <div class="syn-guide-metrics">
                <span>现价 <b class="mono">{{ fmtPrice(s.last_price) }}</b></span>
                <span>持仓 <b class="mono">{{ s.quantity ?? '—' }}</b></span>
                <span v-if="s.profit_loss_rate != null" :class="clsByVal(s.profit_loss_rate)">
                  盈亏 <b class="mono">{{ fmtPct(s.profit_loss_rate) }}</b>
                </span>
              </div>
              <div class="syn-guide-advice">{{ s.advice_text || s.advice || '暂无卖出动作' }}</div>
            </div>
            <div v-if="!sellList.length" class="syn-guide-empty">暂无持仓卖出建议</div>
          </div>
        </div>
      </section>

      <!-- 推理过程：默认收起，首屏只留决策结论与事件影响 -->
      <section v-if="verdict" class="syn-reason-wrap">
        <el-collapse v-model="reasonOpen" class="syn-reason">
          <el-collapse-item name="reason">
            <template #title>
              <span class="syn-reason-title"><el-icon><Document /></el-icon> 展开推理过程</span>
              <span class="syn-reason-sub">{{ reasonSections }}</span>
            </template>

            <div class="syn-reason-body">
              <!-- ① 现状 -->
              <div class="syn-panel" v-if="verdict.status">
                <div class="syn-panel-title status"><el-icon><DataLine /></el-icon> 现状</div>
                <div class="syn-plain-text">{{ verdict.status }}</div>
              </div>

              <!-- ② 引起现状的原因 -->
              <div class="syn-panel" v-if="verdict.reasons.length">
                <div class="syn-panel-title reasons"><el-icon><InfoFilled /></el-icon> 引起现状的原因</div>
                <ul class="syn-panel-list">
                  <li v-for="(r, i) in verdict.reasons" :key="'r' + i">▸ {{ r }}</li>
                </ul>
              </div>

              <!-- ③ 今日观察：外围传导 + 观察信号 -->
              <div class="syn-panel" v-if="verdict.external_observation || verdict.watch.length">
                <div class="syn-panel-title watch"><el-icon><View /></el-icon> 今日观察</div>
                <div class="syn-ext" v-if="verdict.external_observation">
                  <div class="syn-ext-label">外围传导 · 美股 / 大宗商品 → A股情绪</div>
                  <div class="syn-ext-text">{{ verdict.external_observation }}</div>
                </div>
                <ul class="syn-panel-list" v-if="verdict.watch.length">
                  <li v-for="(w, i) in verdict.watch" :key="'w' + i">◎ {{ w }}</li>
                </ul>
              </div>

              <!-- ④ 操作策略 -->
              <div class="syn-panel" v-if="verdict.strategy">
                <div class="syn-panel-title strat"><el-icon><Guide /></el-icon> 操作策略</div>
                <div class="syn-strat-text">{{ verdict.strategy }}</div>
              </div>

              <!-- AI 自主补充（重大事件影响等） -->
              <div class="syn-panel" v-if="verdict.extra.length">
                <div class="syn-panel-title extra"><el-icon><StarFilled /></el-icon> 重点补充</div>
                <ul class="syn-panel-list">
                  <li v-for="(e, i) in verdict.extra" :key="'e' + i">★ {{ e }}</li>
                </ul>
              </div>

              <!-- 风险提示 -->
              <div class="syn-risk" v-if="verdict.risk_tips.length">
                <span class="syn-risk-title"><el-icon><WarnTriangleFilled /></el-icon> 风险提示</span>
                <ul class="syn-risk-list">
                  <li v-for="(tip, i) in verdict.risk_tips" :key="i">{{ tip }}</li>
                </ul>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </section>

      <div class="disclaimer">以上内容由 AI 依据公开市场数据综合研判，仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import {
  vibeApi,
  type MarketSynthesis,
  type SynthesisBuyItem,
  type SynthesisSellItem,
  type MarketEvent,
  type MarketEvents,
} from '@/api/vibe'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'
import { fmtPrice, fmtPct, clsByVal } from '@/utils/format'
import {
  Refresh, Loading, Aim, WarnTriangleFilled, View, Guide,
  DataLine, InfoFilled, StarFilled, TrendCharts, Document, Calendar,
} from '@element-plus/icons-vue'

defineOptions({ name: 'VibeSynthesis' })

const loading = ref(false)
const syn = ref<MarketSynthesis | null>(null)

// 标题日期：优先后端数据返回的交易日；数据未回前用轻量接口预取的最新交易日（首屏即正确，不闪非交易日当天）
const tradeDate = ref('')
const titleDate = computed(() => syn.value?.trade_date || tradeDate.value || '')

// 页头「研判于」：数据获取时刻（LLM 研判完成时刻）
const updatedAt = computed(() => syn.value?.as_of ? formatBeijingDateTimeMinute(syn.value.as_of) : '')

// 页头「数据」：行情快照的数据时刻（与研判生成时刻区分，避免误以为数据是实时的）
// 后端 as_of 是「北京时间墙钟字符串」，直接截取即可，勿再做时区换算（会被当成本地时间二次平移）
const dataAsOf = computed(() => {
  const dash = syn.value?.sources?.dashboard
  // 研判快照里 dashboard 是裁剪版（可能只有 updated，无 as_of）
  const raw = dash?.as_of || dash?.updated
  if (!raw) return ''
  const s = String(raw)
  // 已是北京时间墙钟字符串（YYYY-MM-DD HH:mm）直接截取；带偏移的走统一格式化
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) return s.slice(5, 16)
  return formatBeijingDateTimeMinute(s).slice(5, 16)
})

// ── 今日事件影响（与看板共用同一份事件数据，这里做深度分析与动作建议） ──
const eventsData = ref<MarketEvents | null>(null)
const events = computed<MarketEvent[]>(() => eventsData.value?.events || [])
const expandedEvents = ref<string[]>([])
const toggleEvent = (id: string) => {
  const i = expandedEvents.value.indexOf(id)
  if (i >= 0) expandedEvents.value.splice(i, 1)
  else expandedEvents.value.push(id)
}

const shortTime = (v?: string) => {
  if (!v) return ''
  const s = formatBeijingDateTimeMinute(v)
  return s ? s.slice(5, 16) : ''
}
const shortTitle = (t: string) => (t && t.length > 14 ? `${t.slice(0, 14)}…` : t || '')
const dirLabel = (d?: string) => (d === 'bull' ? '偏多' : d === 'bear' ? '偏空' : '中性')
const surpriseClass = (e: MarketEvent) => `sur-${e.direction || 'neutral'}`
const eventStatusLabel = (e: MarketEvent) =>
  e.status === 'pending' ? '待公布' : e.status === 'expired' ? '已过时' : '已公布'

/** 影响一行说清三件事：方向 / 力度 / 时效；噪音事件明确标注「不改判断」 */
const impactText = (e: MarketEvent) => {
  if (e.impact === 'none') return '无影响 · 不改判断'
  const parts = [dirLabel(e.direction)]
  if (e.strength) parts.push(e.strength)
  if (e.horizon) parts.push(e.horizon)
  return parts.join(' · ')
}

/** 区块标题：件数 + 其中真正会改变方向的件数（让用户知道要不要逐条读） */
const eventHeadline = computed(() => {
  const list = events.value
  if (!list.length) return ''
  const dir = list.filter(e => e.impact === 'direction').length
  const vol = list.filter(e => e.impact === 'volatility').length
  if (dir) return `共 ${list.length} 件 · ${dir} 件可能改变方向`
  if (vol) return `共 ${list.length} 件 · 仅影响 ${vol} 次盘中波动`
  return `共 ${list.length} 件 · 均不改变判断`
})

const loadEvents = async () => {
  try {
    const res: any = await vibeApi.getMarketEvents()
    eventsData.value = res?.data || res || null
  } catch (e) {
    console.error('[Synthesis] 事件加载失败', e)
  }
}

const verdict = computed(() => {
  const v = syn.value?.verdict
  if (!v) return null
  const dir = v.direction || '中性'
  let dirClass = 'neutral'
  if (dir.includes('多') && !dir.includes('中性')) dirClass = 'bull'
  else if (dir.includes('空')) dirClass = 'bear'
  const conf = v.confidence != null ? Math.max(0, Math.min(100, Number(v.confidence))) : null
  const op = v.operation_points || {}
  return {
    direction: dir,
    directionZh: dirClass === 'bull' ? '偏多' : dirClass === 'bear' ? '偏空' : '中性',
    dirClass,
    confidence: conf,
    conclusion: v.conclusion || '',
    status: v.status || '',
    reasons: Array.isArray(v.reasons) ? v.reasons : [],
    operation_points: {
      main_direction: op.main_direction || '',
      avoid_direction: op.avoid_direction || '',
      position_discipline: op.position_discipline || '',
    },
    external_observation: v.external_observation || '',
    strategy: v.strategy || '',
    watch: Array.isArray(v.watch) ? v.watch : [],
    risk_tips: Array.isArray(v.risk_tips) ? v.risk_tips : [],
    extra: Array.isArray(v.extra) ? v.extra : [],
  }
})

/** 操作要点是否有内容可展示 */
const hasOperationPoints = computed(() => {
  const op = verdict.value?.operation_points
  if (!op) return false
  return !!(op.main_direction || op.avoid_direction || op.position_discipline)
})

/** 推理过程默认收起；展开后保留用户选择（keep-alive 切回仍在展开态） */
const reasonOpen = ref<string[]>([])

/** 折叠标题右侧：提示里面有哪些小节，避免用户不知道展开能看到什么 */
const reasonSections = computed(() => {
  const v = verdict.value
  if (!v) return ''
  const names: string[] = []
  if (v.status) names.push('现状')
  if (v.reasons.length) names.push('原因')
  if (v.external_observation || v.watch.length) names.push('今日观察')
  if (v.strategy) names.push('操作策略')
  if (v.extra.length) names.push('重点补充')
  if (v.risk_tips.length) names.push('风险提示')
  return names.join(' · ')
})

/** 结论横幅信心度环：--pct 与 --ring-color 由方向色驱动 */
const confRingStyle = computed(() => {
  const v = verdict.value
  const c = v?.confidence
  const color = v?.dirClass === 'bull' ? '#f56c6c' : v?.dirClass === 'bear' ? '#67c23a' : '#2b6cb0'
  return { '--pct': `${c != null ? c : 0}%`, '--ring-color': color }
})

/** 买卖清单（盘中实时计算，与 AI 文字研判相互独立） */
const buyList = computed<SynthesisBuyItem[]>(() => syn.value?.buys || [])
const sellList = computed<SynthesisSellItem[]>(() => syn.value?.sells || [])

const isNear = (dist: number) => dist <= 2

const buyStateLabel = (b: SynthesisBuyItem) => {
  if (b.triggered) return '已触发'
  if (b.confirmed === false) return '待确认'
  if (b.distance_pct != null && b.distance_pct <= 2) return '接近触发'
  return '等待回落'
}
type TagType = 'danger' | 'warning' | 'info' | 'success'
const buyTagType = (b: SynthesisBuyItem): TagType => {
  if (b.triggered) return 'danger'
  if (b.confirmed === false) return 'info'
  return b.distance_pct != null && b.distance_pct <= 2 ? 'warning' : 'info'
}
const sellTagType = (s: SynthesisSellItem): TagType => {
  const text = `${s.advice_label || ''}${s.advice || ''}`
  if (/清仓|止损|离场/.test(text)) return 'danger'
  if (/减仓|止盈/.test(text)) return 'warning'
  return /持有/.test(text) ? 'success' : 'info'
}

const loadAll = async (refresh = false) => {
  loading.value = true
  try {
    // 默认走市场级缓存（秒开）；仅「AI 重新研判」按钮传 refresh=true 强制重算
    const res: any = await vibeApi.getSynthesis(refresh)
    if (res?.code === 401) {
      ElMessage.warning('登录已过期，请重新登录')
      return
    }
    syn.value = res || null
  } catch (e: any) {
    console.error('[Synthesis] 加载失败', e)
    ElMessage.error(e?.message || '综合研判加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function prefetchTradeDate() {
  vibeApi.getLatestTradeDate().then((d) => { if (d) tradeDate.value = d })
}

onMounted(() => {
  prefetchTradeDate()
  loadAll(false)
  // 事件独立加载：失败不影响研判结论
  loadEvents()
})

// keep-alive 恢复时读缓存（避免每次切回都重跑 LLM 并等待 10~60 秒）
let inited = false
onActivated(() => {
  if (inited) {
    loadAll(false)
    loadEvents()
  }
  inited = true
})
</script>

<style scoped>
.vibe-synthesis {
  padding: 4px;
}

.syn-loading {
  padding: 8px 0;
}
.syn-loading-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.syn-refresh-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 规则兜底标识：标明结论来源，并给出重新尝试 AI 的通路 */
.syn-degraded {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--el-color-warning);
  background: rgba(230, 162, 60, .12);
}
.syn-degraded em {
  font-style: normal;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

/* 信心度「含事件」角标 + 悬浮明细 */
.conf-badge {
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 6px;
  font-style: normal;
  font-size: 9px;
  background: rgba(43, 108, 176, .14);
  color: #2b6cb0;
}
.conf-pop-title {
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.conf-pop-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.conf-pop-row em { font-style: normal; font-weight: 600; white-space: nowrap; }
.dir-bull { color: var(--app-up); }
.dir-bear { color: var(--app-down); }
.dir-neutral { color: var(--el-text-color-secondary); }

/* ── 今日事件影响 ── */
.syn-events {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
}
.syn-events-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.syn-events-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.syn-events-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.syn-events-head .data-time { margin-left: auto; }

.ev-list { display: flex; flex-direction: column; gap: 8px; }
.ev-card {
  border-left: 3px solid var(--el-border-color);
  box-shadow: none;
}
.ev-card.impact-volatility {
  border-left-color: var(--el-color-warning);
  background: rgba(230, 162, 60, .04);
}
.ev-card.impact-direction {
  border-left-color: var(--el-color-primary);
  background: rgba(43, 108, 176, .04);
}
.ev-card.is-expired { opacity: .72; }
.ev-card :deep(.el-card__body) { padding: 10px 12px; }

.ev-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 13px;
}
.ev-row + .ev-row { margin-top: 6px; }
.ev-main { font-weight: 600; }
.ev-time {
  flex: none;
  font-family: var(--app-font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.ev-title {
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ev-surprise {
  flex: none;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--el-fill-color);
}
.ev-surprise.sur-bull { color: var(--app-up); background: rgba(245, 108, 108, .12); }
.ev-surprise.sur-bear { color: var(--app-down); background: rgba(103, 194, 58, .12); }
.ev-surprise.sur-neutral { color: var(--el-text-color-secondary); }
.ev-status {
  flex: none;
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.ev-status.status-pending { color: var(--el-color-warning); }
.ev-toggle {
  flex: none;
  font-size: 11.5px;
  color: var(--el-color-primary);
  cursor: pointer;
}
.ev-label {
  flex: none;
  width: 34px;
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.ev-impact-val { font-weight: 600; }
.ev-action {
  align-items: flex-start;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.ev-sectors { flex-wrap: wrap; }
.ev-tag {
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 11px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}
.ev-detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.ev-trans {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.ev-trans-step em {
  font-style: normal;
  margin-left: 4px;
  color: var(--el-text-color-placeholder);
}
.ev-watch { font-size: 12px; line-height: 1.6; color: #2b6cb0; }
.ev-empty {
  padding: 14px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--el-text-color-placeholder);
}

.syn-reason-wrap { margin-top: 14px; }

.syn-missing {
  padding: 8px 0;
}

/* ── ① 研判结论横幅 ── */
.syn-hero {
  position: relative;
  overflow: hidden;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
  padding: 20px 22px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.syn-hero-glow {
  position: absolute;
  top: -60px; right: -40px;
  width: 240px; height: 240px;
  border-radius: 50%;
  filter: blur(60px);
  opacity: .28;
  pointer-events: none;
}
.syn-hero--bull .syn-hero-glow { background: var(--app-up); }
.syn-hero--bear .syn-hero-glow { background: var(--app-down); }
.syn-hero--neutral .syn-hero-glow { background: var(--el-color-primary); }

.syn-hero-top {
  display: flex;
  align-items: center;
  gap: 20px;
  position: relative;
}
.syn-direc-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 92px;
}
.syn-direc-zh { font-size: 12px; color: var(--el-text-color-placeholder); }
.syn-direc-main {
  font-size: 32px;
  font-weight: 800;
  letter-spacing: 3px;
  line-height: 1.05;
}
.syn-hero--bull .syn-direc-main { color: var(--app-up); }
.syn-hero--bear .syn-direc-main { color: var(--app-down); }
.syn-hero--neutral .syn-direc-main { color: var(--el-color-primary); }

.syn-conf-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 0 18px;
  border-right: 1px dashed var(--el-border-color-lighter);
  border-left: 1px dashed var(--el-border-color-lighter);
}
.syn-conf-ring {
  --pct: 0%;
  --ring-color: #2b6cb0;
  width: 60px; height: 60px;
  border-radius: 50%;
  background: conic-gradient(var(--ring-color) var(--pct), var(--el-fill-color-extra-light) 0);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}
.syn-conf-ring::before {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  background: #fff;
}
.syn-conf-num {
  position: relative;
  z-index: 1;
  font-family: var(--app-font-mono);
  font-size: 17px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1;
}
.syn-conf-unit {
  position: relative;
  z-index: 1;
  font-size: 9px;
  color: var(--el-text-color-placeholder);
  margin-top: 1px;
}
.syn-conf-label { font-size: 11px; color: var(--el-text-color-placeholder); }

.syn-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}


.syn-hero-concl .syn-concl-text {
  font-size: 15px;
  line-height: 1.85;
  color: var(--el-text-color-primary);
}

/* ── AI 内容面板 ── */
.syn-panel {
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
}
.syn-panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 8px;
}
.syn-panel-title.bull { color: var(--app-up); }
.syn-panel-title.watch { color: var(--el-color-primary); }
.syn-panel-title.strat { color: var(--el-color-warning); }
.syn-panel-title.status { color: #2b6cb0; }
.syn-panel-title.reasons { color: var(--el-color-info); }
.syn-panel-title.extra { color: #805ad5; }
.syn-panel-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.syn-panel-list li {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.syn-plain-text {
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--el-text-color-regular);
}
.syn-strat-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

/* 首屏决策卡：主攻 / 回避 / 仓位 —— 直接回答「今天怎么办」 */
.syn-decision {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.syn-dec-card {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-left-width: 3px;
}
.syn-dec-card--main {
  border-left-color: var(--app-up);
  background: rgba(245, 108, 108, .05);
}
.syn-dec-card--avoid {
  border-left-color: var(--app-down);
  background: rgba(103, 194, 58, .05);
}
.syn-dec-card--pos {
  border-left-color: var(--el-color-warning);
  background: rgba(230, 162, 60, .06);
}
.syn-dec-label {
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .5px;
  margin-bottom: 4px;
}
.syn-dec-card--main .syn-dec-label { color: var(--app-up); }
.syn-dec-card--avoid .syn-dec-label { color: var(--app-down); }
.syn-dec-card--pos .syn-dec-label { color: var(--el-color-warning); }
.syn-dec-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

@media (max-width: 900px) {
  .syn-decision { grid-template-columns: 1fr; }
}

/* 推理过程折叠区：默认收起，不抢首屏 */
.syn-reason {
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: none;
}
.syn-reason :deep(.el-collapse-item__header) {
  height: auto;
  padding: 8px 2px;
  border-bottom: none;
  gap: 10px;
  line-height: 1.5;
}
.syn-reason :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}
.syn-reason-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.syn-reason-sub {
  margin-left: auto;
  padding-right: 8px;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.syn-reason-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 0 4px;
}

/* 今日观察 · 外围传导 */
.syn-ext {
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(43, 108, 176, .06);
  border: 1px solid rgba(43, 108, 176, .18);
}
.syn-ext-label {
  font-size: 12px;
  font-weight: 700;
  color: #2b6cb0;
  margin-bottom: 4px;
}
.syn-ext-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

/* 风险提示 */
.syn-risk {
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(230, 162, 60, .08);
  border: 1px solid rgba(230, 162, 60, .22);
}
.syn-risk-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #b7791f;
  margin-bottom: 4px;
}
.syn-risk-list { margin: 0; padding-left: 18px; }
.syn-risk-list li {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

/* ── 今日买卖清单 ── */
.syn-guide {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow);
}
.syn-guide-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.syn-guide-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.syn-guide-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.syn-guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.syn-guide-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.syn-guide-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 700;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.syn-guide-col-head .buy { color: var(--app-up); }
.syn-guide-col-head .sell { color: var(--app-down); }
.syn-guide-count {
  font-weight: 500;
  color: var(--el-text-color-placeholder);
}
.syn-guide-item {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.syn-guide-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.syn-guide-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.syn-guide-name:hover { color: var(--el-color-primary); }
.syn-guide-code {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}
.syn-guide-row :deep(.el-tag) { margin-left: auto; flex: none; }
.syn-guide-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.syn-guide-metrics .is-near { color: var(--el-color-warning); }
.syn-guide-metrics .up { color: var(--app-up); }
.syn-guide-metrics .down { color: var(--app-down); }
.syn-guide-metrics .mono {
  font-family: var(--app-font-mono);
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.syn-guide-metrics .up .mono { color: var(--app-up); }
.syn-guide-metrics .down .mono { color: var(--app-down); }
.syn-guide-advice {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.syn-guide-empty {
  padding: 14px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--el-text-color-placeholder);
}

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 768px) {
  .syn-hero { padding: 16px; }
  .syn-hero-top { flex-wrap: wrap; gap: 12px; }
  .syn-tags { margin-left: 0; }
  .syn-direc-main { font-size: 26px; }
  .syn-conf-wrap { padding: 0 12px; }
  .syn-guide-grid { grid-template-columns: 1fr; }
}
</style>
