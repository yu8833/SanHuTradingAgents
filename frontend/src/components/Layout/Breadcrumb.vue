<template>
  <el-breadcrumb separator="/" class="breadcrumb">
    <el-breadcrumb-item
      v-for="item in breadcrumbList"
      :key="item.path"
      :to="item.path"
    >
      {{ item.title }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const breadcrumbList = computed(() => {
  const matched = route.matched.filter(item => item.meta && item.meta.title)

  if (matched.length === 0) {
    return []
  }

  // 只取最后一个（最深层）路由记录
  const last = matched[matched.length - 1]
  const meta = last.meta

  if (meta.parentTitle) {
    // 有父级标题，展示 "父标题/当前标题"
    return [
      { path: '', title: meta.parentTitle as string },
      { path: last.path, title: meta.title as string }
    ]
  } else {
    // 没有父级标题，只展示当前标题
    return [{ path: last.path, title: meta.title as string }]
  }
})
</script>

<style lang="scss" scoped>
.breadcrumb {
  font-size: 14px;
}
</style>
