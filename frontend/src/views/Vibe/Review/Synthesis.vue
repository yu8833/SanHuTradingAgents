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
          <p class="page-hero-sub">汇聚大盘 / 情绪 / 概念 / 资讯四维数据，AI 综合研判市场方向（个股买卖清单已移至模拟交易页）</p>
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
      <!-- ├─ ① 研判结论横幅 -->
      <section v-if="verdict" class="sect sect-in vs-1">
        <div class="verdict-banner" :class="'vdir-' + verdict.dirClass">
          <div class="vb-main">
            <div class="vb-direction">
              <span class="vb-dir-text">{{ verdict.direction }}</span>
              <span class="vb-dir-zh">{{ verdict.directionZh }}方向</span>
            </div>
            <div class="vb-conf">
              <div class="vb-conf-ring" :style="confRingStyle">
                <span class="vb-conf-num">{{ verdict.confidence != null ? verdict.confidence : '—' }}</span>
                <span class="vb-conf-unit">%</span>
              </div>
              <span class="vb-conf-label">信心度</span>
            </div>
            <div class="vb-body">
              <div class="vb-meta">
                <el-tag v-if="syn?.llm_available" size="small" type="danger" effect="light">AI 研判</el-tag>
                <el-tag v-else size="small" type="warning" effect="light">规则兜底</el-tag>
                <span class="vb-asof">更新于 {{ syn?.as_of ? fmtClock(syn.as_of) : '—' }}</span>
              </div>
              <div class="vb-conclusion">{{ verdict.conclusion }}</div>
              <div v-if="verdict.strategy" class="vb-strategy">
                <el-icon><Opportunity /></el-icon>
                <span>{{ verdict.strategy }}</span>
              </div>
            </div>
          </div>

          <div v-if="verdict.risk_tips && verdict.risk_tips.length" class="vb-risk">
            <span class="vb-risk-title"><el-icon><WarnTriangleFilled /></el-icon> 风险提示</span>
            <ul class="vb-risk-list">
              <li v-for="(tip, i) in verdict.risk_tips" :key="i">{{ tip }}</li>
            </ul>
          </div>
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
import { Refresh, Loading, Aim, Opportunity, WarnTriangleFilled } from '@element-plus/icons-vue'

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
  return {
    direction: dir,
    directionZh: dirClass === 'bull' ? '偏多' : dirClass === 'bear' ? '偏空' : '中性',
    dirClass,
    confidence: conf,
    conclusion: v.conclusion || '',
    strategy: v.strategy || '',
    risk_tips: Array.isArray(v.risk_tips) ? v.risk_tips : [],
  }
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

/* ── 区块（错峰浮现） ── */
.sect {
  margin-bottom: 28px;
}
.sect-in {
  animation: sectIn .5s ease both;
}
.vs-1 { animation-delay: .04s; }
@keyframes sectIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}

/* ── ① 研判结论横幅 ── */
.verdict-banner {
  border-radius: var(--app-radius-lg);
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  overflow: hidden;
  box-shadow: var(--app-shadow);
}
.vb-main {
  display: flex;
  gap: 24px;
  padding: 20px 22px;
  position: relative;
}
.vb-main::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}
.vdir-bull .vb-main::before { background: var(--app-up); }
.vdir-bear .vb-main::before { background: var(--app-down); }
.vdir-neutral .vb-main::before { background: var(--el-color-primary); }
.vb-direction {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 100px;
}
.vb-dir-text {
  font-size: 30px;
  font-weight: 800;
  letter-spacing: 2px;
  line-height: 1.1;
}
.vdir-bull .vb-dir-text { color: var(--app-up); }
.vdir-bear .vb-dir-text { color: var(--app-down); }
.vdir-neutral .vb-dir-text { color: var(--el-color-primary); }
.vb-dir-zh { font-size: 12px; color: var(--el-text-color-placeholder); }
.vb-conf {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding-right: 22px;
  border-right: 1px dashed var(--el-border-color-lighter);
}
.vb-conf-ring {
  --pct: 0%;
  --ring-color: #2b6cb0;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: conic-gradient(var(--ring-color) var(--pct), var(--el-fill-color-extra-light) 0);
  display: grid;
  place-items: center;
  position: relative;
}
.vb-conf-ring::before {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  background: #fff;
}
.vb-conf-num {
  position: relative;
  z-index: 1;
  font-family: var(--app-font-mono);
  font-size: 20px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1;
}
.vb-conf-unit {
  position: relative;
  z-index: 1;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
  margin-top: 1px;
}
.vb-conf-label { font-size: 11px; color: var(--el-text-color-placeholder); }
.vb-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}
.vb-meta { display: flex; align-items: center; gap: 8px; }
.vb-asof {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-mono);
}
.vb-conclusion {
  font-size: 14px;
  line-height: 1.75;
  color: var(--el-text-color-primary);
}
.vb-strategy {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 8px 12px;
  align-self: flex-start;
  max-width: 100%;
}
.vb-strategy .el-icon {
  color: var(--el-color-warning);
  margin-top: 2px;
  flex-shrink: 0;
}
.vb-risk {
  margin: 0 22px 18px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(230, 162, 60, .08);
  border: 1px solid rgba(230, 162, 60, .22);
}
.vb-risk-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #b7791f;
  margin-bottom: 4px;
}
.vb-risk-list { margin: 0; padding-left: 18px; }
.vb-risk-list li {
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
  /* ── 结论横幅 · 手机适配 ── */
  .vb-main { flex-direction: column; gap: 14px; padding: 16px; }
  .vb-direction {
    flex-direction: row;
    gap: 10px;
    min-width: 0;
    justify-content: flex-start;
  }
  .vb-dir-text { font-size: 26px; }
  .vb-conf {
    flex-direction: row;
    gap: 10px;
    padding-right: 0;
    padding-bottom: 12px;
    border-right: none;
    border-bottom: 1px dashed var(--el-border-color-lighter);
    justify-content: flex-start;
  }
  .vb-conf-ring { width: 56px; height: 56px; }
  .vb-conf-ring::before { inset: 5px; }
  .vb-risk { margin: 0 16px 14px; }
}
</style>
