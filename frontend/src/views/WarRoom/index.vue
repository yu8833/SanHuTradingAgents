<template>
  <div class="war-room app-page">
    <!-- ═══ 顶栏：日期 + 实时状态 + 刷新 ═══ -->
    <div class="wr-top">
      <div class="wr-head">
        <h2 class="wr-title">今日作战</h2>
        <span class="wr-date">{{ todayText }}</span>
      </div>
      <div class="wr-actions">
        <el-button size="small" text :icon="Refresh" :loading="loading" @click="refreshCurrent">刷新</el-button>
        <el-button size="small" text @click="goScheduled">定时任务</el-button>
      </div>
    </div>

    <!-- ═══ 大盘方向条 ═══ -->
    <section class="macro-bar" :class="macroCls">
      <div class="macro-main">
        <em class="macro-pill">{{ statusLabel(basis?.status) }}</em>
        <span class="macro-conf">置信度 <b>{{ basis?.confidence ?? '—' }}%</b></span>
      </div>
      <div class="macro-advice">{{ macroAdvice }}</div>
      <div class="macro-gauge" title="刻度 = 状态区间 · 指针 = 当日基准得分">
        <div class="g-seg bear">偏空</div>
        <div class="g-seg neu">中性</div>
        <div class="g-seg bull">偏多</div>
        <div class="g-needle" :style="{ left: gaugePos + '%' }"></div>
      </div>
      <div class="macro-meta">
        <template v-if="macro">快照 {{ fmtClock(macro.created_at) }}</template>
        <template v-else-if="macroAutoGenerating">正在自动生成大盘快照…</template>
        <template v-else>大盘快照未生成</template>
      </div>
      <!-- 市场环境条：四维环境画像（趋势/波动/宽度/情绪）+ 建议激活策略，并入方向区与方向条并列 -->
      <div v-if="envDims.length" class="env-bar">
        <span class="env-label">市场环境</span>
        <span v-for="(d, i) in envDims" :key="i" class="env-dim">{{ d }}</span>
        <span class="flex"></span>
        <template v-if="zhStrategies.length">
          <span class="env-strat">建议激活</span>
          <span v-for="s in zhStrategies" :key="s" class="env-chip">{{ s }}</span>
        </template>
      </div>
      <!-- 打分依据 · 折叠（与方向条融为一体，展开逐条复核） -->
      <div v-if="signals.length" class="macro-facts" :class="{ open: signalOpen }" @click="signalOpen = !signalOpen">
        <span class="mf-label">打分依据</span>
        <span class="mf-sum">总分 <b>{{ basis?.score ?? '—' }}</b><em v-if="scoreBreakdown" class="mf-brk">（{{ scoreBreakdown }}）</em><i class="mf-th">偏多≥+2 · 偏空≤-2</i></span>
        <span class="flex"></span>
        <i class="mf-arrow" :class="{ open: signalOpen }"></i>
      </div>
      <div v-show="signalOpen" class="ms-list">
        <!-- 五类信号分舱：每舱 = 组头(贡献小计) + 组内信号行；单击组头可单独折叠该舱 -->
        <div v-for="g in signalGroups" :key="g.key" class="sg" :class="g.key">
          <div class="sg-head" @click="toggleSg(g)">
            <i class="sg-no">{{ g.no }}</i>
            <span class="sg-name">{{ g.name }}</span>
            <em class="sg-desc">{{ g.desc }}</em>
            <span class="flex"></span>
            <template v-if="g.key === 'event'">
              <span class="sg-count">{{ g.items.length }} 条</span>
              <el-button v-if="g.items.length > 5" size="small" text @click.stop="evLimit = evLimit >= g.items.length ? 5 : g.items.length">
                {{ evLimit >= g.items.length ? '展开全部' : '收起' }}
              </el-button>
            </template>
            <b class="sg-score" :class="groupScoreCls(g)">{{ fmtGroupScore(g) }}</b>
            <i class="mf-arrow" :class="{ open: sgOpenState(g) }"></i>
          </div>
          <div v-show="sgOpenState(g)" class="sg-body">
            <!-- ③ 重大事件舱：|影响度|≥50 强影响事件融合为事件卡 -->
            <div v-if="g.key === 'event'">
              <div class="ev-cards">
              <div v-for="(s, i) in g.items.slice(0, evLimit)" :key="i" class="ev-card" :class="evDir(s)">
                <div class="ev-side">
                  <em class="ev-dir" :class="evDir(s)">{{ evDirText(s) }}</em>
                  <b class="ev-score" :class="evScoreCls(s)">{{ evScoreText(s) }}</b>
                  <span class="ev-lv">{{ evLevel(s) }}影响</span>
                  <span class="ev-type chip-type" :class="evType(s)">{{ evTypeText(s) }}</span>
                  <span v-if="evProb(s)" class="ev-prob">影响概率 <b>{{ evProb(s) }}</b></span>
                </div>
                <div class="ev-main">
                  <div class="ev-meta">
                    <el-tag v-if="evDetail(s)?.category" size="small" class="cat-tag" effect="plain">{{ evDetail(s)?.category }}</el-tag>
                    <el-tag :type="importanceTag(evDetail(s)?.importance)" size="small" effect="plain">{{ evDetail(s)?.importance === 'high' ? '重大' : evDetail(s)?.importance === 'medium' ? '重要' : '一般' }}</el-tag>
                    <span v-if="evDetail(s)?.source" class="ev-src">{{ sourceShort(evDetail(s)?.source) }} · {{ newsTime(evDetail(s)?.publish_time) }}</span>
                  </div>
                  <p class="ev-title">
                    <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" class="ev-origin">{{ s.title }} →</a>
                    <span v-else>{{ s.title }}</span>
                  </p>
                  <p v-if="s.analysis || evDetail(s)?.analysis" class="ev-analysis">{{ s.analysis || evDetail(s)?.analysis }}</p>
                  <div v-if="(s.related_sectors?.length) || evDetail(s)?.related_sectors?.length" class="ev-sectors">
                    <span class="sec-label">相关板块</span>
                    <span v-for="(sec, si) in (s.related_sectors?.length ? s.related_sectors : evDetail(s)?.related_sectors)" :key="si" class="sec-chip">{{ sec }}</span>
                  </div>
                </div>
              </div>
              <p v-if="!g.items.length" class="ms-news-empty">今日暂无计入总分的强影响事件</p>
              </div>
            </div>
            <!-- ①②④⑤ 其他舱：指数/期货/情绪/技术面 紧凑行，分值徽章醒目 -->
            <template v-else>
              <div v-for="(s, i) in g.items" :key="i" class="ms-row" :class="['score-' + sigScoreCls(s), { hot: sigScore(s) !== 0 }]">
                <span class="ms-name">{{ s.name }}</span>
                <span class="ms-val">{{ fmtSigValue(s) }}</span>
                <b class="ms-score" :class="sigScoreCls(s)">{{ fmtSigScore(s) }}</b>
                <span class="ms-detail">{{ s.detail }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </section>

  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { warRoomApi } from '@/api/warRoom'
import { retailApi } from '@/api/retail'

defineOptions({ name: 'WarRoomHome' })

// ──────────────────────────── 数据状态 ────────────────────────────
const loading = ref(false)
const macroAutoGenerating = ref(false)
const macro = ref<any>(null)
const reference = ref<any>(null)
let macroAutoTimer: number | null = null

const todayText = computed(() => {
  const d = new Date()
  const wd = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 周${wd}`
})

const router = useRouter()
function goScheduled() { router.push('/tasks') }

// ──────────────────────────── 大盘方向 ────────────────────────────
const basis = computed(() => macro.value?.basis || null)
const gaugePos = computed(() => {
  const b = basis.value
  if (b?.low_confidence || b?.status === '数据不足' || b?.status === '中性(观望)') return 50
  const score = Number(b?.score ?? 0) || 0
  const norm = Math.max(-1, Math.min(1, score / 10))
  return Math.round(50 + norm * 46)
})
function statusLabel(s?: string): string {
  if (s) return s
  const d = macro.value?.rule?.direction
  if (!d) return '数据不足'
  if (d.includes('多')) return '偏多'
  if (d.includes('空')) return '偏空'
  return '中性(观望)'
}
const macroCls = computed(() => {
  const s = statusLabel(basis.value?.status)
  if (s.includes('空')) return 'bear'
  if (s.includes('多')) return 'bull'
  if (s === '中性(观望)') return 'neutral'
  return 'nodata'
})
const macroAdvice = computed(() => {
  const b = basis.value
  if (!b?.status || b.status === '数据不足') return '数据不足：今日方向不明，谨慎为主'
  if (b.low_confidence || b.status === '中性(观望)') return `置信度 ${b.confidence ?? 0}% 不足 → 观望为主；若操作，仓位减半`
  if (b.status.includes('多')) return '大盘偏多 → 可进取：按计划执行买入，严守止损纪律'
  if (b.status.includes('空')) return '大盘偏空 → 减仓避险为主：暂缓新开仓，执行卖出计划'
  return b.direction || '观望'
})

// ── 规则引擎明细（折叠区）：逐条信号 → 贡献分，可复核总分怎么来的 ──
const signals = computed(() => macro.value?.rule?.signals || [])
const signalOpen = ref(true)

// 五类信号分组（与规则引擎打分顺序一一对应）：
//   ① 外围指数（标普/纳指/恒指/日经/KOSPI）
//   ② 期货·风险（VIX + 富时A50/标普/纳指/道指期货）
//   ③ 重大事件（高重要性政策/数据事件，含「已落地/预期」概率分级）
//   ④ 市场情绪（昨日涨跌家数）
//   ⑤ A股技术面（上证20日线/中期趋势/两市量能）
const signalGroupDefs = [
  { key: 'overseas', no: '①', name: '外围指数', desc: '隔夜美股与亚太基准' },
  { key: 'futures', no: '②', name: '期货·风险', desc: 'VIX 与海外期货 / 富时A50' },
  { key: 'event', no: '③', name: '重大事件', desc: '已落地 / 预期 · 影响概率' },
  { key: 'breadth', no: '④', name: '市场情绪', desc: '昨日涨跌家数' },
  { key: 'a_share', no: '⑤', name: 'A股技术面', desc: '上证均线 · 两市量能' },
]
function sigGroupKey(s: any): string {
  const name = s?.name || ''
  if (name === '高重要性政策/数据事件') return 'event'
  if (name === '昨日大盘情绪') return 'breadth'
  if (name.includes('上证指数') || name.includes('两市量能')) return 'a_share'
  if (name.includes('期货') || name === 'VIX恐慌指数') return 'futures'
  return 'overseas'
}
const signalGroups = computed(() =>
  signalGroupDefs
    .map(def => ({ ...def, items: signals.value.filter((s: any) => sigGroupKey(s) === def.key) }))
    .filter(g => g.items.length)
)
// 组贡献小计：该组全部信号分数之和（组头徽章，一眼看到每类信号对总分的影响）
function groupScore(g: any): number {
  return g.items.reduce((a: number, s: any) => a + sigScore(s), 0)
}
function fmtGroupScore(g: any): string {
  const sc = groupScore(g)
  return sc > 0 ? `+${sc}` : String(sc)
}
function groupScoreCls(g: any): string {
  const sc = groupScore(g)
  return sc > 0 ? 'up' : sc < 0 ? 'down' : 'flat'
}
// 组内折叠（默认全展开；外层 signalOpen 控制整体明细区）
const sgOpen = ref<Record<string, boolean>>({})
function sgOpenState(g: any): boolean {
  return sgOpen.value[g.key] !== false
}
function toggleSg(g: any) {
  sgOpen.value = { ...sgOpen.value, [g.key]: !sgOpenState(g) }
}
function fmtSigValue(s: any): string {
  const v = s?.value
  if (v == null) return '—'
  if (typeof v === 'number') return String(Math.round(v * 100) / 100)
  return String(v)
}
// 分值徽章：数值 + 方向色（非零醒目，零弱化）
function sigScore(s: any): number {
  return Number(s?.score ?? 0) || 0
}
function fmtSigScore(s: any): string {
  const sc = sigScore(s)
  return sc > 0 ? `+${sc}` : String(sc)
}
function sigScoreCls(s: any): string {
  const sc = sigScore(s)
  return sc > 0 ? 'up' : sc < 0 ? 'down' : 'flat'
}
// 总分来源分解：按信号组聚合，如「①+2 · ②-1 · ③-4 · ⑤+2」，一眼看到 5 类信号各自贡献
const scoreBreakdown = computed(() =>
  signalGroups.value
    .map(g => {
      const sc = groupScore(g)
      return `${g.no}${sc > 0 ? '+' : ''}${sc}`
    })
    .join(' · ')
)
function fmtClock(iso?: string): string {
  if (!iso) return '—'
  let s = String(iso).trim()
  s = s.replace(/\.(\d{3})\d+/, '.$1')
  if (!/([Z]|[+-]\d{2}:?\d{2}( ?\(.+\))?)$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.toDateString() === new Date().toDateString()
    ? `今日 ${hm}`
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

// ──────────────────────────── 加载 ────────────────────────────
async function loadMacro() {
  loading.value = true
  try {
    const res: any = await warRoomApi.getMacroOverview()
    macro.value = res?.snapshot || null
    macroAutoGenerating.value = !!res?.auto_generating
    if (macroAutoGenerating.value) {
      stopMacroAuto()
      macroAutoTimer = window.setInterval(async () => {
        try {
          const r: any = await warRoomApi.getMacroOverview()
          if (r?.snapshot) {
            macro.value = r.snapshot
            macroAutoGenerating.value = false
            stopMacroAuto()
          }
        } catch { /* 轮询失败忽略，下轮重试 */ }
      }, 15000)
    }
  } catch (e) {
    macro.value = null
  }
  loading.value = false
}
function stopMacroAuto() { if (macroAutoTimer) { window.clearInterval(macroAutoTimer); macroAutoTimer = null } }

// 重大新闻（参考数据源：快讯多源聚合 + 影响度打分）
async function loadReference() {
  try {
    reference.value = await warRoomApi.getMacroReference()
  } catch (e) {
    console.warn('[WarRoom] loadReference', e)
    if (!reference.value) reference.value = null
  }
}

// 市场环境（retail 市场环境识别器：趋势/波动/宽度/情绪 四维 + 建议激活策略），并入方向区。
const REGIME_ZH: Record<string, string> = {
  bull: '牛市', bear: '熊市', range: '震荡市',
  high: '高波动', normal: '正常', low: '低波动',
  broad: '普涨', narrow: '分化',
  euphoric: '狂热', neutral: '中性', panic: '恐慌',
}
const STRATEGY_ZH: Record<string, string> = {
  turnaround: '困境反转',
  small_cap_value: '小盘价值',
  convertible_arbitrage: '转债博弈',
  extreme_reversal: '极端情绪反转',
  default: '默认',
}
const regime = ref<any>(null)
const envDims = computed(() => {
  const r = regime.value
  if (!r) return []
  return [r.trend, r.volatility, r.breadth, r.sentiment]
    .filter(Boolean)
    .map((k: string) => REGIME_ZH[k] || k)
})
const zhStrategies = computed(() =>
  (regime.value?.active_strategies || []).map((s: string) => STRATEGY_ZH[s] || s)
)
async function loadRegime() {
  try {
    regime.value = await retailApi.detectRegimeAuto()
  } catch (e) {
    console.warn('[WarRoom] loadRegime', e)
    regime.value = null
  }
}

// 重要事件（重大新闻）：剔除个股类、只留 |影响度| ≥ 50 的强影响事件
const newsList = computed(() => {
  const items = (reference.value?.news_top || []).filter((n: any) =>
    String(n.category) !== '个股' && Math.abs(Number(n.impact_score ?? 0) || 0) >= 50
  )
  return items.slice().sort((a: any, b: any) => {
    const ia = Math.abs(a.impact_score ?? 0)
    const ib = Math.abs(b.impact_score ?? 0)
    if (ia !== ib) return ib - ia
    const wa = a.importance === 'high' ? 0 : a.importance === 'medium' ? 1 : 2
    const wb = b.importance === 'high' ? 0 : b.importance === 'medium' ? 1 : 2
    return wa - wb
  })
})
// ③ 重大事件舱展示条数上限（>5 条时头部出现「展开全部」）
const evLimit = ref(5)
function evDir(s: any): string {
  return Number(s?.score ?? 0) > 0 ? 'bull' : 'bear'
}
function evDirText(s: any): string {
  return Number(s?.score ?? 0) > 0 ? '利多' : '利空'
}
function evLevel(s: any): string {
  const imp = Math.abs(Number(s?.impact_score ?? 0)) || 0
  if (imp >= 60) return '强'
  if (imp >= 30) return '中'
  return Number(s?.score ?? 0) !== 0 ? '强' : '弱'
}
// 事件对应的新闻详情（标题匹配 news_top），补充解读/板块/来源；匹配不到返回 null
function evDetail(s: any): any {
  if (!s?.title) return null
  const t = String(s.title).trim()
  return newsList.value.find((n: any) => String(n.title || '').trim() === t) || null
}
// 事件打分制：直接显示对总分的贡献（±3 重大 / ±2 重要），与规则引擎分档一致
function evScoreText(s: any): string {
  const c = Number(s?.score ?? 0)
  if (!c) return '—'
  return c > 0 ? `+${c}` : String(c)
}
function evScoreCls(s: any): string {
  const c = Number(s?.score ?? 0)
  if (!c) return 'is-na'
  return c > 0 ? 'up' : 'down'
}
function newsTime(t?: string): string {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function sourceShort(src?: string): string {
  if (!src) return ''
  const s = String(src)
  if (s.startsWith('资讯雷达')) return '资讯雷达'
  return s.length > 8 ? s.slice(0, 8) : s
}
function importanceTag(v?: string): 'danger' | 'warning' | 'info' {
  if (v === 'high' || v === '高') return 'danger'
  if (v === 'medium' || v === '中') return 'warning'
  return 'info'
}
// ── B 档：事件"概率×幅度"分级展示 ──
// 事件类型：fact=已落地（正式数据/政策/声明），expectation=预期/传闻（未落地）
function evType(s: any): string {
  return s?.event_type === 'expectation' ? 'expectation' : 'fact'
}
function evTypeText(s: any): string {
  return s?.event_type === 'expectation' ? '预期' : '已落地'
}
function evProb(s: any): string {
  const p = Number(s?.probability)
  if (!Number.isFinite(p) || p <= 0) return ''
  return `${Math.round(p * 100)}%`
}

async function refreshCurrent() {
  loading.value = true
  await Promise.allSettled([loadMacro(), loadReference(), loadRegime()])
  loading.value = false
}

onMounted(() => {
  refreshCurrent()
})
onActivated(() => {
  refreshCurrent()
})
onUnmounted(() => {
  stopMacroAuto()
})
</script>

<style lang="scss" scoped>
.war-room {
  font-variant-numeric: tabular-nums;

  .up { color: var(--app-up); }    // A股惯例：涨 = 红
  .down { color: var(--app-down); } // 跌 = 绿
  .flex { flex: 1; }
  .no-op { color: var(--el-text-color-placeholder); }

  // ═══ 顶栏 ═══
  .wr-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12px;

    .wr-head {
      display: flex;
      align-items: baseline;
      gap: 12px;
      .wr-title { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: 1px; color: var(--el-text-color-primary); }
      .wr-date { font-size: 13px; color: var(--el-text-color-secondary); }
    }
    .wr-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      .live {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--el-text-color-placeholder);
        .live-dot {
          width: 8px; height: 8px; border-radius: 50%;
          background: var(--el-text-color-placeholder);
        }
        &.on {
          color: var(--el-color-primary);
          .live-dot {
            background: var(--el-color-primary);
            animation: pulse 1.8s ease-in-out infinite;
          }
        }
      }
    }
  }

  // ═══ 大盘方向条 ═══
  .macro-bar {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    padding: 12px 18px;
    margin-bottom: 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-left: 4px solid var(--el-text-color-placeholder);
    border-radius: 12px;
    background: var(--el-bg-color);

    &.bull { border-left-color: var(--el-color-danger); }
    &.bear { border-left-color: var(--el-color-success); }
    &.neutral { border-left-color: var(--el-color-warning); }
    &.nodata { border-left-color: var(--el-text-color-placeholder); }

    .macro-main {
      display: flex;
      align-items: center;
      gap: 10px;
      .macro-pill {
        font-style: normal;
        font-size: 18px;
        font-weight: 800;
        color: var(--el-color-primary);
      }
      &.bull .macro-pill { color: var(--el-color-danger); }
      &.bear .macro-pill { color: var(--el-color-success); }
      &.neutral .macro-pill { color: var(--el-color-warning); }
      &.nodata .macro-pill { color: var(--el-text-color-secondary); }
      .macro-conf { font-size: 13px; color: var(--el-text-color-secondary); b { font-size: 15px; color: var(--el-text-color-primary); } }
    }
    .macro-advice { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
    .macro-gauge {
      position: relative;
      display: flex;
      width: 240px;
      height: 18px;
      margin-left: auto;
      border-radius: 99px;
      overflow: visible;
      .g-seg {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: #fff;
        // 用显式类而非 :first/:last-child —— gauge 内还有 g-needle，:last-child 会失效导致白字白底
        &.bear { border-radius: 99px 0 0 99px; background: var(--el-color-success); }
        &.neu { background: var(--el-color-info); }
        &.bull { border-radius: 0 99px 99px 0; background: var(--el-color-danger); }
      }
      .g-needle {
        position: absolute;
        top: -4px;
        width: 3px;
        height: 26px;
        background: var(--el-color-primary);
        border-radius: 2px;
        transform: translateX(-50%);
        transition: left .6s cubic-bezier(.2, .8, .2, 1);
        box-shadow: 0 0 4px rgba(0, 0, 0, .25);
        &:after {
          content: '';
          position: absolute;
          bottom: -3px; left: 50%;
          transform: translateX(-50%);
          border-left: 4px solid transparent;
          border-right: 4px solid transparent;
          border-top: 5px solid var(--el-color-primary);
        }
      }
    }
    .macro-meta { font-size: 12px; color: var(--el-text-color-placeholder); }

    // 市场环境条：四维环境画像 + 建议激活策略（并入方向区，与方向条并列）
    .env-bar {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      width: 100%;
      margin-top: 4px;
      padding: 5px 10px;
      border: 1px dashed var(--el-border-color-lighter);
      border-radius: 8px;
      background: var(--el-fill-color-lighter);

      .env-label { font-size: 12px; font-weight: 700; color: var(--el-text-color-primary); }
      .env-dim {
        font-size: 11px;
        line-height: 1.6;
        padding: 0 8px;
        border-radius: 20px;
        color: var(--el-text-color-regular);
        background: var(--el-bg-color-overlay);
        border: 1px solid var(--el-border-color-lighter);
      }
      .env-strat { font-size: 11px; color: var(--el-text-color-secondary); }
      .env-chip {
        font-size: 11px;
        line-height: 1.6;
        padding: 0 8px;
        border-radius: 4px;
        color: var(--el-color-primary);
        background: var(--el-color-primary-light-9);
        border: 1px solid var(--el-color-primary-light-5);
      }
    }

    // 打分依据 · 折叠（融合进方向条，非独立卡片）
    .macro-facts {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      margin-top: 4px;
      padding: 6px 10px;
      border: 1px dashed var(--el-border-color-lighter);
      border-radius: 8px;
      cursor: pointer;
      user-select: none;
      transition: background .2s, border-color .2s;
      &:hover { background: var(--el-fill-color-lighter); border-color: var(--el-border-color-hover); }

      .mf-label { font-size: 12px; font-weight: 700; color: var(--el-text-color-primary); }
      .mf-sum {
        font-size: 12px; color: var(--el-text-color-secondary);
        b { color: var(--el-color-primary); font-weight: 700; font-size: 14px; }
        .mf-brk { margin-left: 4px; font-style: normal; color: var(--el-text-color-placeholder); }
        .mf-th { margin: 0 4px 0 8px; font-style: normal; color: var(--el-text-color-placeholder); }
      }
      .mf-arrow {
        width: 0; height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid var(--el-text-color-secondary);
        transition: transform .2s;
        &.open { transform: rotate(180deg); }
      }
    }

    .ms-list {
      width: 100%;
      border-top: 1px dashed var(--el-border-color-lighter);
      margin-top: 6px;
      padding-top: 4px;
      animation: riseIn .25s cubic-bezier(.2, .8, .2, 1) both;

      // ── 五类信号分舱：组头（①~⑤ + 组贡献小计徽章） + 组内信号行 ──
      .sg {
        border-radius: 8px;
        &.event { margin-top: 8px; }

        .sg-head {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 5px 8px;
          cursor: pointer;
          user-select: none;
          border-radius: 6px;
          transition: background .2s;
          &:hover { background: var(--el-fill-color-lighter); }

          .sg-no {
            flex: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            font-style: normal;
            font-size: 12px;
            font-weight: 800;
            color: #fff;
            background: var(--el-text-color-secondary);
            border-radius: 6px;
          }
          &.overseas .sg-no { background: var(--el-color-primary); }
          &.futures .sg-no { background: var(--el-color-warning-dark-2, #b88200); }
          &.event .sg-no { background: var(--el-color-danger-dark-2); }
          &.breadth .sg-no { background: var(--el-color-info); }
          &.a_share .sg-no { background: var(--el-color-success-dark-2); }

          .sg-name { font-size: 13px; font-weight: 700; color: var(--el-text-color-primary); }
          .sg-desc { font-size: 11.5px; font-style: normal; color: var(--el-text-color-placeholder); }
          .sg-count { font-size: 12px; color: var(--el-text-color-placeholder); }

          // 组贡献小计徽章：非零方向色实底白字，零灰弱化 —— 一眼看到这类信号对总分的影响
          .sg-score {
            flex: none;
            min-width: 34px;
            text-align: center;
            font-size: 13px;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
            line-height: 1.8;
            border-radius: 6px;
            &.up { color: #fff; background: var(--el-color-danger-dark-2); }
            &.down { color: #fff; background: var(--el-color-success-dark-2); }
            &.flat { color: var(--el-text-color-placeholder); background: var(--el-fill-color-light); }
          }
          .mf-arrow {
            flex: none;
            width: 0; height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid var(--el-text-color-secondary);
            transition: transform .2s;
            &.open { transform: rotate(180deg); }
          }
        }

        .sg-body {
          padding: 2px 6px 4px 30px;
          animation: riseIn .2s ease both;
        }
      }

      .ms-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 5px 4px;
        font-size: 12.5px;
        border-bottom: 1px dashed var(--el-border-color-lighter);
        border-radius: 6px;
        &:last-child { border-bottom: none; }
        // 有实际贡献分（非零）的行：浅方向色底强调（用 element 官方 light-9，兼容性稳定）
        &.hot { padding: 5px 4px 5px 6px; background: var(--el-fill-color-light); }
        &.hot.score-up { background: var(--el-color-danger-light-9); }
        &.hot.score-down { background: var(--el-color-success-light-9); }

        .ms-name { width: 150px; flex: none; font-weight: 600; color: var(--el-text-color-primary); }
        .ms-val { width: 90px; flex: none; color: var(--el-text-color-regular); font-variant-numeric: tabular-nums; }
        // 分值徽章：非零方向色实底白字（高分对比，避免红字红底看不清），零灰弱化
        .ms-score {
          flex: none;
          width: 34px;
          text-align: center;
          font-size: 13px;
          font-weight: 800;
          font-variant-numeric: tabular-nums;
          line-height: 1.8;
          border-radius: 6px;
          &.up { color: #fff; background: var(--el-color-danger-dark-2); }
          &.down { color: #fff; background: var(--el-color-success-dark-2); }
          &.flat { color: var(--el-text-color-placeholder); background: var(--el-fill-color-light); }
        }
        .ms-detail { flex: 1; min-width: 0; color: var(--el-text-color-secondary); }

        // 事件原文链接：hover 变主题色 + 下划线，整条 detail 可点
        .ms-origin {
          color: inherit;
          text-decoration: none;
          &:hover { color: var(--el-color-primary); text-decoration: underline; }
        }
      }
  }
}

  // ═══ ③ 重大事件舱：事件卡（左评分柱 + 右内容，编辑部式） ═══
  .ms-news-empty { margin: 6px 0; font-size: 13px; color: var(--el-text-color-placeholder); }

  .ev-cards { display: grid; grid-template-columns: 1fr; gap: 10px; }
.ev-card {
  display: flex;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-left-width: 4px;
  border-left-style: solid;
  border-radius: 10px;
  background: var(--el-bg-color-page);
  transition: border-color .2s, transform .2s;
  animation: riseIn .35s cubic-bezier(.2, .8, .2, 1) both;

  &:hover { border-color: var(--el-border-color-hover); transform: translateY(-1px); }
  &.bull { border-left-color: var(--el-color-danger); }
  &.bear { border-left-color: var(--el-color-success); }
  &.neutral { border-left-color: var(--el-text-color-placeholder); }

  // 左评分柱
  .ev-side {
    width: 92px;
    flex: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding-top: 2px;

    .ev-dir {
      font-style: normal;
      font-size: 11px;
      font-weight: 700;
      line-height: 1.6;
      padding: 0 10px;
      border-radius: 99px;
      &.bull { color: #fff; background: var(--el-color-danger); }
      &.bear { color: #fff; background: var(--el-color-success); }
      &.neutral { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
      }
    .ev-score {
      // 打分制：显示对总分的贡献（±2/±1），白字深色底高分对比；未计入显示 —
      min-width: 36px;
      text-align: center;
      font-size: 20px;
      font-weight: 800;
      line-height: 1.4;
      border-radius: 6px;
      padding: 0 6px;
      font-variant-numeric: tabular-nums;
      &.up { color: #fff; background: var(--el-color-danger-dark-2); }
      &.down { color: #fff; background: var(--el-color-success-dark-2); }
      &.is-na { color: var(--el-text-color-placeholder); background: var(--el-fill-color-light); font-size: 14px; }
      }
    .ev-lv { font-size: 11px; color: var(--el-text-color-secondary); }
    // B 档：事件类型徽章（已落地=实底 / 预期=浅底描边）+ 影响概率
    .ev-type {
      font-size: 10px;
      font-weight: 600;
      line-height: 1.5;
      padding: 0 7px;
      border-radius: 99px;
      white-space: nowrap;
      &.fact { color: var(--el-color-primary-dark-2); background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-7); }
      &.expectation { color: var(--el-color-warning-dark-2, #b88200); background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-7); }
      }
    .ev-prob {
      font-size: 10px;
      color: var(--el-text-color-secondary);
      b { font-size: 12px; color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
      }
    }

  // 右内容
  .ev-main { flex: 1; min-width: 0; }
  .ev-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 6px;
    .cat-tag { color: var(--el-color-primary); border-color: var(--el-color-primary-light-7); }
    .ev-src { font-size: 12px; color: var(--el-text-color-placeholder); }
    }
  .ev-title {
    margin: 0 0 6px;
    font-size: 14.5px;
    font-weight: 700;
    line-height: 1.5;
    color: var(--el-text-color-primary);

    .ev-origin {
      color: inherit;
      text-decoration: none;
      &:hover { color: var(--el-color-primary); text-decoration: underline; }
      }
    }
  // 解读：方向色左边条 + 淡底（引用样式）
  .ev-analysis {
    margin: 0 0 7px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--el-text-color-regular);
    background: var(--el-fill-color-lighter);
    border-left: 3px solid var(--el-border-color);
    border-radius: 6px;
    padding: 6px 10px;
    }
  &.bull .ev-analysis { border-left-color: var(--el-color-danger-light-5); }
  &.bear .ev-analysis { border-left-color: var(--el-color-success-light-5); }

  .ev-sectors {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    .sec-label { font-size: 11px; color: var(--el-text-color-placeholder); }
    .sec-chip {
      font-size: 11px;
      padding: 1px 8px;
      border-radius: 99px;
      color: var(--el-color-primary);
      background: var(--el-color-primary-light-9);
      border: 1px solid var(--el-color-primary-light-7);
      }
    }
  }
}

@keyframes riseIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
}
</style>