<script setup lang="ts">
defineOptions({ name: 'CockpitGateCard' })
import { computed } from 'vue'
import type { GateData } from '@/api/cockpit'

const props = defineProps<{ data: GateData | null; loading?: boolean }>()

const level = computed(() => props.data?.gate || 'yellow')

const actionText = computed(() => {
  const g = props.data
  if (!g) return ''
  if (g.gate === 'red') return '今天不买。只观察观察池，等环境转好或个股独立走强'
  if (g.gate === 'green') return '可以进攻。按下方「突破触发信号」执行，触发一只买一只'
  return '轻仓试错。只做临近触发且已确认量能的标的，不加仓、不扩散'
})

const phaseLabel = computed(() => props.data?.emotion_phase?.label || '—')
const phaseColor = computed(() => {
  const p = phaseLabel.value
  if (p === '冰点期') return '#64748b'
  if (p === '退潮期') return '#ef4444'
  if (p === '分歧期') return '#f59e0b'
  if (p === '修复期') return '#38bdf8'
  if (p === '启动期') return '#22c55e'
  if (p === '发酵期') return '#16a34a'
  if (p === '高潮期') return '#dc2626'
  return '#94a3b8'
})

const emotionChips = computed(() => {
  const e = props.data?.emotion
  if (!e) return []
  return [
    { k: '涨停', v: e.zt ?? '—' },
    { k: '跌停', v: e.dt ?? '—' },
    { k: '炸板率', v: e.zb != null && e.zt != null && e.zt + e.zb > 0 ? `${Math.round((e.zb / (e.zt + e.zb)) * 100)}%` : '—' },
    { k: '最高板', v: e.max_boards ?? '—' }
  ]
})
</script>

<template>
  <div class="cg-card" :class="`cg-card--${level}`">
    <div v-if="loading && !data" class="cg-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <template v-else-if="data">
      <div class="cg-main">
        <div class="cg-light">
          <span class="cg-light-dot" />
          <span class="cg-light-text">{{ data.label }}</span>
        </div>

        <div class="cg-body">
          <div class="cg-row1">
            <div class="cg-tags">
              <span class="cg-tag">
                大盘画像
                <b>{{ data.portrait || '数据缺失' }}</b>
              </span>
              <span class="cg-tag">
                情绪阶段
                <b :style="{ color: phaseColor }">{{ phaseLabel }}</b>
              </span>
            </div>
            <span v-if="data.degraded" class="cg-degrade" :title="data.degrade_note">
              数据降级
            </span>
          </div>

          <div class="cg-action">
            <span class="cg-action-label">今日行动</span>
            <span class="cg-action-text">{{ actionText }}</span>
          </div>

          <div class="cg-hint">{{ data.hint }}</div>

          <div class="cg-foot">
            <div class="cg-pos">
              <span class="cg-pos-label">建议仓位</span>
              <span class="cg-pos-value">{{ data.position_hint }}</span>
            </div>
            <div class="cg-chips">
              <span v-for="c in emotionChips" :key="c.k" class="cg-chip">
                {{ c.k }} <b>{{ c.v }}</b>
              </span>
            </div>
          </div>

          <div class="cg-times">
            <span>画像 {{ data.as_of_portrait || '—' }}</span>
            <span>情绪 {{ data.as_of_emotion || '—' }}</span>
          </div>
        </div>
      </div>
    </template>

    <el-empty v-else description="环境闸门数据不可用" :image-size="60" />
  </div>
</template>

<style scoped>
.cg-card {
  border-radius: 14px;
  padding: 18px 20px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  transition: box-shadow 0.2s;
}
.cg-card--green {
  background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 60%);
  border-color: #86efac;
}
.cg-card--yellow {
  background: linear-gradient(135deg, #fffbeb 0%, #ffffff 60%);
  border-color: #fcd34d;
}
.cg-card--red {
  background: linear-gradient(135deg, #fef2f2 0%, #ffffff 60%);
  border-color: #fca5a5;
}
.cg-main {
  display: flex;
  gap: 20px;
  align-items: stretch;
}
.cg-light {
  flex: 0 0 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 12px;
  padding: 10px;
}
.cg-card--green .cg-light { background: rgba(34, 197, 94, 0.12); }
.cg-card--yellow .cg-light { background: rgba(245, 158, 11, 0.12); }
.cg-card--red .cg-light { background: rgba(239, 68, 68, 0.12); }
.cg-light-dot {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  box-shadow: 0 0 0 8px rgba(0, 0, 0, 0.04);
}
.cg-card--green .cg-light-dot { background: #22c55e; box-shadow: 0 0 0 8px rgba(34, 197, 94, 0.16); }
.cg-card--yellow .cg-light-dot { background: #f59e0b; box-shadow: 0 0 0 8px rgba(245, 158, 11, 0.16); }
.cg-card--red .cg-light-dot { background: #ef4444; box-shadow: 0 0 0 8px rgba(239, 68, 68, 0.16); }
.cg-light-text {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
}
.cg-card--green .cg-light-text { color: #15803d; }
.cg-card--yellow .cg-light-text { color: #b45309; }
.cg-card--red .cg-light-text { color: #b91c1c; }

.cg-body { flex: 1; min-width: 0; }
.cg-row1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.cg-tags { display: flex; flex-wrap: wrap; gap: 10px; }
.cg-tag {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 3px 9px;
}
.cg-tag b { color: var(--el-text-color-primary); margin-left: 4px; font-weight: 600; }
.cg-degrade {
  font-size: 12px;
  color: #b45309;
  border: 1px dashed #fcd34d;
  border-radius: 6px;
  padding: 2px 8px;
  cursor: help;
}
.cg-action {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px dashed var(--el-border-color);
  margin-bottom: 10px;
}
.cg-action-label {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.cg-action-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.5;
}
.cg-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}
.cg-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.cg-pos { display: flex; align-items: baseline; gap: 8px; }
.cg-pos-label { font-size: 12px; color: var(--el-text-color-secondary); }
.cg-pos-value { font-size: 16px; font-weight: 700; color: var(--el-text-color-primary); }
.cg-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cg-chip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border-radius: 20px;
  padding: 2px 10px;
}
.cg-chip b { color: var(--el-text-color-primary); margin-left: 2px; }
.cg-times {
  display: flex;
  gap: 14px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
@media (max-width: 768px) {
  .cg-main { flex-direction: column; }
  .cg-light { flex: none; flex-direction: row; }
}
</style>
