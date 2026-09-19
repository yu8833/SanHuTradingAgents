<template>
  <div class="vibe-synthesis app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ today }} · 综合研判</h2>
          <p class="page-hero-sub">汇聚大盘 / 情绪 / 概念 / 资讯四维数据，AI 综合研判市场方向</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
          AI 重新研判
        </el-button>
      </div>
    </div>

    <!-- 加载中骨架 -->
    <div v-if="loading" class="syn-loading">
      <el-skeleton :rows="6" animated />
      <div class="syn-loading-tip">
        <el-icon class="is-loading"><Loading /></el-icon>
        AI 综合研判中（约需 10~60 秒），正在聚合四页市场数据…
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
          <div class="syn-conf-wrap" v-if="verdict.confidence != null">
            <div class="syn-conf-ring" :style="confRingStyle">
              <span class="syn-conf-num">{{ verdict.confidence }}</span>
              <span class="syn-conf-unit">%</span>
            </div>
            <span class="syn-conf-label">信心度</span>
          </div>
          <div class="syn-tags">
            <el-tag v-if="syn?.llm_available" size="small" type="danger" effect="dark">AI 研判</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">规则兜底</el-tag>
            <span class="syn-asof">更新于 {{ syn?.as_of ? fmtClock(syn.as_of) : '—' }}</span>
          </div>
        </div>

        <!-- 总研判结论 -->
        <div class="syn-hero-concl">
          <div class="syn-concl-text">{{ verdict.conclusion }}</div>
        </div>

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

        <!-- ③ 操作要点：主攻 / 回避 / 持仓分析 / 仓位纪律 -->
        <div class="syn-panel" v-if="hasOperationPoints">
          <div class="syn-panel-title bull"><el-icon><Opportunity /></el-icon> 操作要点</div>
          <div class="syn-op-grid">
            <div class="syn-op-card" v-if="verdict.operation_points.main_direction">
              <div class="syn-op-card-label main">主攻方向</div>
              <div class="syn-op-card-text">{{ verdict.operation_points.main_direction }}</div>
            </div>
            <div class="syn-op-card" v-if="verdict.operation_points.avoid_direction">
              <div class="syn-op-card-label avoid">回避方向</div>
              <div class="syn-op-card-text">{{ verdict.operation_points.avoid_direction }}</div>
            </div>
            <div class="syn-op-card" v-if="verdict.operation_points.position_analysis.length">
              <div class="syn-op-card-label pos">现有持仓买卖分析</div>
              <ul class="syn-panel-list">
                <li v-for="(p, i) in verdict.operation_points.position_analysis" :key="'pa' + i">◆ {{ p }}</li>
              </ul>
            </div>
            <div class="syn-op-card" v-if="verdict.operation_points.position_discipline">
              <div class="syn-op-card-label disc">仓位纪律</div>
              <div class="syn-op-card-text">{{ verdict.operation_points.position_discipline }}</div>
            </div>
          </div>
        </div>

        <!-- ④ 今日观察：外围传导 + 观察信号 -->
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

        <!-- ⑤ 操作策略 -->
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
} from '@/api/vibe'
import {
  Refresh, Loading, Aim, Opportunity, WarnTriangleFilled, View, Guide,
  DataLine, InfoFilled, StarFilled,
} from '@element-plus/icons-vue'

defineOptions({ name: 'VibeSynthesis' })

const loading = ref(false)
const syn = ref<MarketSynthesis | null>(null)

const today = computed(() => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
})

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
      position_analysis: Array.isArray(op.position_analysis) ? op.position_analysis : [],
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
  return !!(op.main_direction || op.avoid_direction || op.position_discipline || op.position_analysis.length)
})

/** 结论横幅信心度环：--pct 与 --ring-color 由方向色驱动 */
const confRingStyle = computed(() => {
  const v = verdict.value
  const c = v?.confidence
  const color = v?.dirClass === 'bull' ? '#f56c6c' : v?.dirClass === 'bear' ? '#67c23a' : '#2b6cb0'
  return { '--pct': `${c != null ? c : 0}%`, '--ring-color': color }
})

function fmtClock(s: string | null | undefined): string {
  if (!s) return '—'
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    const p = (n: number) => String(n).padStart(2, '0')
    return `${p(d.getHours())}:${p(d.getMinutes())}`
  } catch {
    return s
  }
}

const loadAll = async () => {
  loading.value = true
  try {
    const res: any = await vibeApi.getSynthesis()
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

onMounted(loadAll)

// keep-alive 恢复时刷新（AI 研判随刷新重算）
let inited = false
onActivated(() => {
  if (inited) loadAll()
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
.syn-asof {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
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

/* 操作要点卡片 */
.syn-op-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.syn-op-card {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
}
.syn-op-card-label {
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 5px;
}
.syn-op-card-label.main { color: var(--app-up); }
.syn-op-card-label.avoid { color: var(--app-down); }
.syn-op-card-label.pos { color: #2b6cb0; }
.syn-op-card-label.disc { color: var(--el-color-warning); }
.syn-op-card-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
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
}
</style>
