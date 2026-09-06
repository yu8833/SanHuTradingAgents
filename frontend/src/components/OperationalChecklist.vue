<template>
  <el-collapse v-if="hasData" class="operational-checklist">
    <el-collapse-item title="📋 操作检查清单" name="checklist">
      <!-- 决策行：操作方向 + 置信度 -->
      <div v-if="cl['操作方向'] || cl['评分']" class="oc-decision-line">
        <el-tag v-if="actionTag" :type="actionTag.type" effect="dark" size="large">
          {{ actionTag.text }}
        </el-tag>
        <span class="oc-stock" v-if="cl['结论文本']">{{ cl['结论文本'].slice(0, 40) }}</span>
        <span v-if="cl['评分']" class="oc-conf">
          <b>{{ cl['评分'] }}</b><i>分 · 置信度</i>
        </span>
      </div>

      <!-- 点位/仓位网格 -->
      <el-descriptions v-if="pointCells.length" :column="4" border class="oc-grid" size="small">
        <el-descriptions-item v-for="c in pointCells" :key="c.label" :label="c.label">
          <span :class="{ 'oc-danger': c.danger }">{{ c.value }}</span>
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
            <div v-for="(it, i) in b.items" :key="i" class="oc-line">{{ it }}</div>
          </template>
          <template v-else>
            <div class="oc-line">{{ b.items }}</div>
          </template>
        </el-alert>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  checklist?: Record<string, any> | null
}>()

const cl = computed(() => (props.checklist && typeof props.checklist === 'object' ? props.checklist : {}))

const hasData = computed(() => Object.keys(cl.value).length > 0)

const actionTag = computed(() => {
  const a = cl.value['操作方向']
  if (!a) return null
  const s = String(a)
  if (/买入|增持/.test(s)) return { text: s.length > 4 ? '买入' : s, type: 'success' as const }
  if (/卖出|减持/.test(s)) return { text: s.length > 4 ? '卖出' : s, type: 'danger' as const }
  return { text: s, type: 'info' as const }
})

const pointCells = computed(() => {
  const cells: Array<{ label: string; value: string; danger?: boolean }> = []
  const push = (label: string, key: string, danger = false) => {
    const v = cl.value[key]
    if (v != null && String(v).trim()) cells.push({ label, value: String(v), danger })
  }
  push('入场', '入场')
  push('目标1', '目标1')
  push('目标2', '目标2')
  push('止损', '止损', true)
  push('风险/回报比', '风险回报比')
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
</script>

<style scoped>
.operational-checklist {
  margin-bottom: 16px;
}
.oc-decision-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.oc-stock {
  font-size: 14px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.oc-conf {
  margin-left: auto;
  text-align: right;
}
.oc-conf b {
  font-size: 18px;
  color: var(--el-color-primary);
  font-family: var(--el-font-mono, monospace);
}
.oc-conf i {
  font-style: normal;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: 4px;
}
.oc-grid {
  margin-bottom: 12px;
}
.oc-danger {
  color: var(--el-color-danger);
  font-weight: 600;
}
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
  line-height: 1.7;
}
.oc-line + .oc-line {
  margin-top: 2px;
}
</style>