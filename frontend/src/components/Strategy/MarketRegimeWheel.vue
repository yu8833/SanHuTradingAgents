<template>
  <div class="regime-wheel">
    <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="wheel-svg" role="img" aria-label="大盘行情画像轮盘">
      <!-- 外圈浅环：给轮盘一个“仪表盘”边界，弱化扇区外缘的锯齿感 -->
      <circle :cx="C" :cy="C" :r="R_OUT + 5" class="wheel-outer-ring" />

      <g v-for="s in sectors" :key="s.id">
        <g
          class="wheel-sector"
          :class="{ current: s.id === current, dim: current && s.id !== current }"
          :style="{ transform: `translate(${s.dx}px, ${s.dy}px)` }"
          @click="emit('pick', s.id)"
        >
          <path :d="s.path" :fill="s.color" class="sector-shape" />
          <!-- 标签沿扇区中轴旋转，贴合弧线，不再水平溢出窄扇区 -->
          <text
            :x="s.labelX"
            :y="s.labelY"
            :transform="`rotate(${s.rot} ${s.labelX} ${s.labelY})`"
            class="sector-label"
            :class="{ strong: s.id === current }"
            text-anchor="middle"
            dominant-baseline="central"
          >{{ s.label }}</text>
        </g>
      </g>

      <!-- 中心：只放画像名，长说明移到图例 / tooltip，避免叠字 -->
      <circle :cx="C" :cy="C" :r="R_IN - 8" class="wheel-center" />
      <text :x="C" :y="C - 16" text-anchor="middle" class="center-label">当前画像</text>
      <text :x="C" :y="C + 8" text-anchor="middle" class="center-value">{{ currentLabel || current || '待检测' }}</text>
      <text v-if="shortDesc" :x="C" :y="C + 30" text-anchor="middle" class="center-hint">{{ shortDesc }}</text>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

defineOptions({ name: 'MarketRegimeWheel' })

export interface WheelGroup {
  id: string
  /** 展示名（可一个组承载多个画像，如「熊市恐慌 / 反弹」） */
  label?: string
  color: string
  count: number
}

const props = defineProps<{
  /** 画像组（顺序即轮盘顺时针顺序） */
  groups: WheelGroup[]
  /** 当前画像 id（高亮，其余变暗） */
  current?: string
  /** 圆心展示的画像名（可与分组 id 不同，如画像「熊市反弹」落在「熊市恐慌」组） */
  currentLabel?: string
  /** 当前画像的说明文案（仅截断后显示在圆心，完整版请走图例 / tooltip） */
  currentDesc?: string
}>()

const emit = defineEmits<{ (e: 'pick', id: string): void }>()

const SIZE = 340
const C = SIZE / 2
const R_OUT = 126
const R_IN = 82

const polar = (r: number, deg: number) => {
  const rad = ((deg - 90) * Math.PI) / 180
  return { x: C + r * Math.cos(rad), y: C + r * Math.sin(rad) }
}

const arcPath = (startDeg: number, endDeg: number) => {
  const o1 = polar(R_OUT, startDeg)
  const o2 = polar(R_OUT, endDeg)
  const i1 = polar(R_IN, startDeg)
  const i2 = polar(R_IN, endDeg)
  const large = endDeg - startDeg > 180 ? 1 : 0
  return [
    `M ${o1.x.toFixed(2)} ${o1.y.toFixed(2)}`,
    `A ${R_OUT} ${R_OUT} 0 ${large} 1 ${o2.x.toFixed(2)} ${o2.y.toFixed(2)}`,
    `L ${i2.x.toFixed(2)} ${i2.y.toFixed(2)}`,
    `A ${R_IN} ${R_IN} 0 ${large} 0 ${i1.x.toFixed(2)} ${i1.y.toFixed(2)}`,
    'Z',
  ].join(' ')
}

const sectors = computed(() => {
  const n = props.groups.length || 1
  const step = 360 / n
  const gap = n > 1 ? 1.4 : 0
  const midR = (R_OUT + R_IN) / 2

  return props.groups.map((g, i) => {
    const start = i * step + gap
    const end = (i + 1) * step - gap
    const mid = (start + end) / 2
    // 当前扇区沿中轴外推，形成「指针指向」的强调效果
    const push = g.id === props.current ? 6 : 0
    const rad = ((mid - 90) * Math.PI) / 180
    const dx = Math.cos(rad) * push
    const dy = Math.sin(rad) * push
    const label = polar(midR, mid)
    // 文字沿扇区中轴旋转；左半圆翻转 180°，避免倒立
    let rot = mid - 90
    if (rot > 90) rot -= 180
    else if (rot < -90) rot += 180
    return {
      id: g.id,
      // 「熊市恐慌 / 反弹」这种合并组在弧上写成单行，不再拆行（拆行旋转后会重叠）
      label: (g.label || g.id).replace(' / ', '·'),
      color: g.color,
      count: g.count,
      path: arcPath(start, end),
      dx,
      dy,
      labelX: label.x,
      labelY: label.y,
      rot,
    }
  })
})

// 圆心最多放 14 个字，超出截断；完整说明在图例 / 画像条里看
const shortDesc = computed(() => {
  const d = (props.currentDesc || '').trim()
  return d.length > 14 ? `${d.slice(0, 13)}…` : d
})
</script>

<style scoped>
.regime-wheel {
  display: flex;
  align-items: center;
  justify-content: center;
}
.wheel-svg {
  width: 100%;
  max-width: 340px;
  height: auto;
  overflow: visible;
}
.wheel-outer-ring {
  fill: none;
  stroke: var(--el-border-color-lighter, #ebeef5);
  stroke-width: 1;
}
.wheel-sector {
  cursor: pointer;
  transition: opacity 0.25s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.wheel-sector.dim { opacity: 0.45; }
.wheel-sector.dim:hover { opacity: 0.8; }
.sector-shape {
  stroke: var(--el-bg-color, #fff);
  stroke-width: 2;
  transition: filter 0.25s ease, stroke-width 0.2s ease;
}
.wheel-sector:hover .sector-shape { filter: brightness(1.06); }
.wheel-sector.current .sector-shape {
  stroke: #fff;
  stroke-width: 2.5;
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.3));
}
.sector-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  fill: #fff;
  pointer-events: none;
  user-select: none;
  /* SVG 文字描边：在浅色扇区（如震荡蓄势的绿）上也能读得清 */
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.3);
  stroke-width: 2.5px;
  stroke-linejoin: round;
}
.sector-label.strong { font-size: 12px; }
.wheel-center {
  fill: var(--el-bg-color, #fff);
  stroke: var(--el-border-color, #dcdfe6);
  stroke-width: 1;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.08));
}
.center-label {
  font-size: 10px;
  fill: var(--el-text-color-secondary, #909399);
  letter-spacing: 2px;
}
.center-value {
  font-size: 17px;
  font-weight: 700;
  fill: var(--el-text-color-primary, #303133);
}
.center-hint {
  font-size: 10px;
  fill: var(--el-text-color-secondary, #909399);
}
</style>
