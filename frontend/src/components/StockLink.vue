<template>
  <span class="stock-link-wrap" :class="{ column }">
    <router-link
      v-if="name"
      :to="`/stocks/${code}`"
      class="s-name"
      :title="name"
    >{{ name }}</router-link>
    <router-link
      :to="`/stocks/${code}`"
      class="s-code"
    >{{ code }}</router-link>
  </span>
</template>

<script setup lang="ts">
defineOptions({ name: 'StockLink' })

defineProps<{
  /** 股票代码（跳转详情页） */
  code: string
  /** 股票名称（可选；不传则只显示代码） */
  name?: string
  /** 名称与代码是否上下排列（默认横排：名称 代码） */
  column?: boolean
}>()
</script>

<style scoped>
.stock-link-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  vertical-align: middle;
  &.column {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    line-height: 1.3;
  }
}
</style>