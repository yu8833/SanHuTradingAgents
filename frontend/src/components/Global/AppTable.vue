<template>
  <div class="app-table-wrapper">
    <div v-if="toolbar || showToolbar" class="app-table-toolbar">
      <div class="toolbar-left">
        <slot name="toolbar-left">
          <span v-if="count !== null" class="toolbar-count">
            共 <strong>{{ count }}</strong> {{ countLabel }}
          </span>
        </slot>
      </div>
      <div class="toolbar-actions">
        <slot name="toolbar-right">
          <el-button v-if="showRefresh" size="small" :loading="loading" @click="$emit('refresh')">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
          <el-button v-if="showAdd" size="small" type="primary" @click="$emit('add')">
            <el-icon><Plus /></el-icon>
            {{ addText }}
          </el-button>
        </slot>
      </div>
      <slot name="toolbar" />
    </div>

    <el-table
      :data="innerData"
      v-loading="loading"
      :size="size"
      stripe
      :border="false"
      :max-height="maxHeight"
      :row-key="rowKey"
      :default-sort="defaultSort"
      :empty-text="emptyText"
      :class="tableClass"
      class="app-table"
      show-summary
      :summary-method="summaryMethod"
      @sort-change="(sort: any) => $emit('sort-change', sort)"
      @row-click="(row: any) => $emit('row-click', row)"
    >
      <slot />
      <template #empty>
        <slot name="empty">
          <el-empty :description="emptyText" />
        </slot>
      </template>
    </el-table>

    <div v-if="pagination && showPagination" class="app-table-pagination">
      <el-pagination
        v-model:current-page="pagination.current"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="pageSizes"
        :layout="paginationLayout"
        background
        @current-change="(page: number) => $emit('page-change', page)"
        @size-change="(size: number) => $emit('size-change', size)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Refresh, Plus } from '@element-plus/icons-vue'

interface PaginationConfig {
  current: number
  pageSize: number
  total: number
}

interface Props {
  data: any[]
  loading?: boolean
  variant?: 'default' | 'compact' | 'metrics' | 'trades' | 'ranking'
  size?: 'small' | 'default' | 'large'
  maxHeight?: number | string
  rowKey?: string | ((row: any) => string | number)
  defaultSort?: { prop: string; order: 'ascending' | 'descending' }
  emptyText?: string
  count?: number | null
  countLabel?: string
  showToolbar?: boolean
  showRefresh?: boolean
  showAdd?: boolean
  addText?: string
  pagination?: PaginationConfig | null
  showPagination?: boolean
  pageSizes?: number[]
  paginationLayout?: string
  summaryMethod?: ({ columns, data }: { columns: any[]; data: any[] }) => (string | number)[]
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  variant: 'default',
  size: 'default',
  maxHeight: undefined,
  rowKey: undefined,
  defaultSort: undefined,
  emptyText: '暂无数据',
  count: null,
  countLabel: '条记录',
  showToolbar: false,
  showRefresh: false,
  showAdd: false,
  addText: '新增',
  pagination: null,
  showPagination: true,
  pageSizes: () => [10, 20, 50, 100],
  paginationLayout: 'total, prev, pager, next, jumper',
  summaryMethod: undefined,
})

defineEmits<{
  (e: 'refresh'): void
  (e: 'add'): void
  (e: 'sort-change', sort: any): void
  (e: 'row-click', row: any): void
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
}>()

const innerData = computed(() => props.data)

const tableClass = computed(() => {
  return props.variant !== 'default' ? `app-table--${props.variant}` : ''
})
</script>

<style lang="scss" scoped>
.app-table-wrapper {
  background: var(--el-bg-color);
  border: 1px solid var(--app-table-border, var(--el-border-color-light));
  border-radius: var(--app-radius);
  box-shadow: var(--app-shadow);
  overflow: hidden;

  .app-table {
    border: none;
    box-shadow: none;
    border-radius: 0;
  }

  .app-table-pagination {
    padding: 12px 18px;
    border-top: 1px solid var(--el-border-color-lighter);
    display: flex;
    justify-content: flex-end;
    background: var(--el-bg-color);
  }
}
</style>
