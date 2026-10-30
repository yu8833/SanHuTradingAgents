<template>
  <div class="emotion-detail">
    <div v-if="!hideHead" class="detail-head">
      <span class="detail-title">{{ title }} · {{ rows.length }} 只</span>
      <span class="detail-close" @click="$emit('close')">收起</span>
    </div>
    <el-table
      v-if="rows.length"
      :data="rows"
      size="small"
      stripe
      max-height="260"
      class="app-table app-table--ranking"
    >
      <el-table-column label="名称 / 代码" min-width="120">
        <template #default="{ row }">
          <div class="stock-cell">
            <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
            <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="metric" :label="metric.label" width="86" align="right">
        <template #default="{ row }">{{ row[metric.key] }}{{ metric.suffix }}</template>
      </el-table-column>
      <el-table-column label="涨跌幅" width="86" align="right">
        <template #default="{ row }">
          <span :class="clsByVal(row.pct, '')">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="成交额(亿)" width="96" align="right">
        <template #default="{ row }">{{ fmtYi(row.amount) }}</template>
      </el-table-column>
      <el-table-column label="行业" min-width="96" prop="industry" />
    </el-table>
    <div v-else class="detail-empty">该档暂无个股</div>
  </div>
</template>

<script setup lang="ts">
import { fmtYi, fmtPct, clsByVal } from '@/utils/format'

defineOptions({ name: 'EmotionDetailTable' })

interface DetailRow {
  code: string
  name: string
  pct?: number | null
  amount?: number | null
  industry?: string
  [key: string]: any
}

withDefaults(defineProps<{
  title: string
  rows: DetailRow[]
  metric?: { key: string; label: string; suffix: string } | null
  /** 弹窗场景可隐藏内置标题栏（标题由弹窗头展示） */
  hideHead?: boolean
}>(), {
  metric: null,
  hideHead: false,
})

defineEmits<{ (e: 'close'): void }>()
</script>

<style scoped>
.emotion-detail {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.detail-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.detail-close {
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
}

.detail-close:hover {
  text-decoration: underline;
}

.detail-empty {
  padding: 10px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--el-text-color-placeholder);
}
</style>
