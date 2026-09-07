<template>
  <div v-if="hasData" class="operational-checklist">
    <div class="oc-header">📋 操作检查清单</div>

    <!-- 结论文本（富文本渲染；仅保留有实质内容的结论摘要） -->
    <div v-if="cl['结论文本'] && String(cl['结论文本']).trim().length > 10" class="oc-summary" v-html="toHtml(cl['结论文本'])"></div>

    <!-- 点位/仓位网格 -->
    <el-descriptions v-if="pointCells.length" :column="4" border class="oc-grid" size="small">
      <el-descriptions-item v-for="c in pointCells" :key="c.label" :label="c.label">
        <span :class="['oc-cell', 'oc-cell--' + c.kind]">{{ c.value }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <!-- 触发/风险/监控列表 -->
    <div v-if="listBlocks.length" class="oc-blocks">
      <el-alert
        v-for="b in listBlocks"
        :key="b.label"
        :title="b.label"
        :type="b.type"
        :closable="false"
        show-icon
        class="oc-alert"
      >
        <template v-if="Array.isArray(b.items)">
          <div v-for="(it, i) in b.items" :key="i" class="oc-line" v-html="toHtml(it)"></div>
        </template>
        <template v-else>
          <div class="oc-line" v-html="toHtml(b.items)"></div>
        </template>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  checklist?: Record<string, any> | null
}>()

const cl = computed(() => (props.checklist && typeof props.checklist === 'object' ? props.checklist : {}))

const hasData = computed(() => Object.keys(cl.value).length > 0)

/** 点位格：kind 控制颜色 —— 买点/目标=红(看涨)，止损=绿(风险)，其余中性 */
const pointCells = computed(() => {
  const cells: Array<{ label: string; value: string; kind: 'up' | 'down' | 'flat' | 'warn' }> = []
  const push = (label: string, key: string, kind: 'up' | 'down' | 'flat' | 'warn' = 'flat', required = false) => {
    const v = cl.value[key]
    // required：关键点位格始终占位，缺失显示 "—" 保持网格完整；非 required 缺失时隐藏
    if (v == null || !String(v).trim()) {
      if (required) cells.push({ label, value: '—', kind: 'flat' })
      return
    }
    cells.push({ label, value: String(v), kind })
  }
  push('入场', '入场', 'up', true)
  push('目标1', '目标1', 'up', true)
  push('目标2', '目标2', 'up', true)
  push('止损', '止损', 'down', true)
  push('风险/回报比', '风险回报比', 'warn', true)
  push('建议仓位', '建议仓位')
  push('持有周期', '持有周期')
  return cells
})

const listBlocks = computed(() => {
  const blocks: Array<{ label: string; type: 'info' | 'warning' | 'error'; items: any }> = []
  if (cl.value['入场策略']) blocks.push({ label: '入场策略', type: 'info', items: cl.value['入场策略'] })
  if (cl.value['关键触发']) blocks.push({ label: '关键触发条件', type: 'info', items: cl.value['关键触发'] })
  if (cl.value['风险警报']) blocks.push({ label: '风险警报', type: 'warning', items: cl.value['风险警报'] })
  if (cl.value['监控点']) blocks.push({ label: '重点监控点', type: 'warning', items: cl.value['监控点'] })
  if (cl.value['催化因素']) blocks.push({ label: '催化因素', type: 'success', items: cl.value['催化因素'] })
  return blocks
})

/** 转义 + 轻量 markdown → 安全 HTML（不含原始标记） */
const toHtml = (text: string): string => {
  const lines = String(text ?? '').split(/\r?\n/)
  return lines.map(block => {
    let s = block
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    const trimmed = s.trim()
    // 标题 #/##/### → 深色加粗块
    const h = trimmed.match(/^#{1,4}\s+(.+)$/)
    if (h) return `<div class="oc-md-h">${inline(h[1])}</div>`
    // 数字编号行 "1. xx" / "1、xx" → 编号列表项
    const num = trimmed.match(/^(\d+[.、])\s*(.+)$/)
    if (num) return `<div class="oc-md-item"><span class="oc-md-num">${num[1]}</span><span class="oc-md-body">${inline(num[2])}</span></div>`
    // 无序列表 "- xx" / "· xx"
    const li = trimmed.match(/^[-·•*]\s+(.+)$/)
    if (li) return `<div class="oc-md-item"><span class="oc-md-dot">•</span><span class="oc-md-body">${inline(li[1])}</span></div>`
    // 普通段落（段内替换标点断行）
    return `<div class="oc-md-para">${inline(s)}</div>`
  }).join('')
}

/** 行内转义后的 markdown：**加粗** → 强调色；`code` → 等宽块；标题标记#/## 清除 */
const inline = (s: string): string => {
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b class="oc-md-b">$1</b>')
  s = s.replace(/`([^`]+)`/g, '<code> $1 </code>')
  // 清除残余的 markdown 标题标记（#、##、###）与单个 *
  s = s.replace(/#{1,6}\s*/g, '').replace(/\*+/g, '').replace(/^>\s?/gm, '')
  // 顿号/分号后轻断行，避免超长段落挤在一起
  s = s.replace(/(；|;\s*)/g, '$1<span class="oc-br"></span>')
  return s.trim()
}
</script>

<style scoped>
.operational-checklist {
  margin-bottom: 16px;
  /* 与「📈 决策建议」卡片风格对齐：渐变浅底 + 顶部彩条 + 同款圆角 */
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 28px 32px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04);
  position: relative;
  overflow: hidden;
}

.operational-checklist::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #2b6cb0, #8b5cf6, #ec4899, #f97316, #22c55e);
}

.oc-header {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 20px;
  letter-spacing: 0.5px;
}

html.dark .operational-checklist {
  background: linear-gradient(135deg, #1e293b 0%, #1c1917 100%);
  border-color: #334155;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3), 0 1px 3px rgba(0, 0, 0, 0.2);
}
html.dark .oc-header {
  color: #f8fafc;
}
html.dark .oc-md-para,
html.dark .oc-md-body,
html.dark .oc-line {
  color: #cbd5e1;
}
html.dark .oc-md-h {
  color: #f1f5f9;
}
html.dark .oc-md-b {
  color: #60a5fa;
}

/* ── 结论文本 ── */
.oc-summary {
  background: #f7f9fc;
  border-left: 3px solid #1f6feb;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #3a4250;
  line-height: 1.8;
}
.oc-summary :deep(.oc-md-h) {
  font-weight: 700;
  color: #1f2329;
}
.oc-summary :deep(.oc-md-b) {
  color: #c53030;
  font-weight: 700;
}
.oc-summary :deep(.oc-br) {
  display: block;
  height: 4px;
}

/* ── 点位网格 ── */
.oc-grid {
  margin-bottom: 12px;
}
.oc-cell {
  font-weight: 700;
  font-size: 14px;
}
.oc-cell--up   { color: #c53030; }
.oc-cell--down { color: #0f7a4b; }
.oc-cell--warn { color: #d46b08; }
.oc-cell--flat { color: #1f2329; }

/* ── 段落列表 ── */
.oc-blocks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.oc-alert {
  width: 100%;
}
.oc-line {
  font-size: 13px;
  line-height: 1.85;
  color: #3b4354;
}
.oc-line + .oc-line {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e8eaef;
}
.oc-md-h {
  font-weight: 700;
  color: #1f2329;
  font-size: 14px;
  margin: 4px 0 2px;
}
.oc-md-b {
  color: #1f6feb;
  font-weight: 700;
}
.oc-md-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 2px 0;
}
.oc-md-num {
  flex-shrink: 0;
  font-weight: 700;
  color: #d46b08;
  min-width: 22px;
}
.oc-md-dot {
  flex-shrink: 0;
  color: #1f6feb;
  font-weight: 700;
}
.oc-md-body {
  flex: 1;
}
.oc-md-para {
  padding: 2px 0;
}
.oc-br {
  display: block;
  height: 4px;
}
:deep(code) {
  font-family: var(--el-font-mono, monospace);
  font-size: 12px;
  background: #eef1f6;
  color: #3b4354;
  padding: 1px 5px;
  border-radius: 4px;
}
</style>