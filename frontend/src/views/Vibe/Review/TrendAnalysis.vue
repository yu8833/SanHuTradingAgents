<template>
  <div class="trend-analysis-page app-page">
    <!-- 页头（与其他 Review 页面统一：最新交易日 + 标题 + 刷新）；
         三 Tab 内部不再各自渲染页头，避免重复 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataLine /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">{{ titleDate }} · 趋势分析</h2>
          <p class="page-hero-sub">行业 / 概念 / 个股多维趋势与资金研判</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span class="page-hero-tag">更新于 {{ updatedAt || '—' }}</span>
        <el-button type="primary" plain :icon="Refresh" :loading="refreshing" @click="refresh">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 三 Tab：行业全景 / 概念快照 / 个股趋势（懒加载，仅激活时挂载并缓存；Tab 样式与大盘看板一致） -->
    <el-tabs v-model="activeTab" class="trend-tabs">
      <el-tab-pane label="行业全景" name="industry">
        <KeepAlive>
          <IndustryPanorama v-if="activeTab === 'industry'" ref="industryRef" @data-updated="onTabUpdated('industry', $event)" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="概念快照" name="concept">
        <KeepAlive>
          <BoardQuadrant v-if="activeTab === 'concept'" ref="conceptRef" @data-updated="onTabUpdated('concept', $event)" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="个股趋势" name="stock">
        <KeepAlive>
          <StockQuadrant v-if="activeTab === 'stock'" ref="stockRef" @data-updated="onTabUpdated('stock', $event)" />
        </KeepAlive>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { DataLine, Refresh } from '@element-plus/icons-vue'
import IndustryPanorama from './IndustryPanorama.vue'
import StockQuadrant from './StockQuadrant.vue'
import BoardQuadrant from './BoardQuadrant.vue'
import { vibeApi } from '@/api/vibe'
import { formatBeijingDateTimeMinute } from '@/utils/datetime'

defineOptions({ name: 'TrendAnalysis' })

const activeTab = ref<'industry' | 'concept' | 'stock'>('industry')

// 页头日期：最新交易日（轻量接口预取，首屏即正确，不闪非交易日当天）
const titleDate = ref('')

// 页头「更新于」：当前激活 tab 的数据获取时刻（由子组件数据返回后上报），格式与其他页面统一（YYYY-MM-DD HH:MM）
const tabUpdatedAt = ref<Record<string, string>>({})
const onTabUpdated = (tab: string, time: string) => { if (time) tabUpdatedAt.value[tab] = time }
const updatedAt = computed(() => {
  const t = tabUpdatedAt.value[activeTab.value]
  return t ? formatBeijingDateTimeMinute(t) : ''
})

// 页头刷新：只刷新当前 Tab（调用子组件暴露的 refresh，失效该页自己的缓存；
// 其它 Tab 的 KeepAlive 实例与缓存保持不变，避免整页重建与重复请求）
const industryRef = ref<any>(null)
const conceptRef = ref<any>(null)
const stockRef = ref<any>(null)
const refreshing = ref(false)
const refresh = async () => {
  const instMap: Record<string, any> = {
    industry: industryRef.value,
    concept: conceptRef.value,
    stock: stockRef.value,
  }
  const inst = instMap[activeTab.value]
  if (!inst?.refresh) return
  refreshing.value = true
  try {
    await inst.refresh()
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) titleDate.value = d })
})
</script>

<style scoped lang="scss">
.trend-analysis-page {
  .trend-tabs {
    margin-bottom: 8px;
    :deep(.el-tabs__header) {
      margin-bottom: 16px;
    }
    :deep(.el-tab-pane) {
      min-height: 200px;
    }
  }
}
</style>
