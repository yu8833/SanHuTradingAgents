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
        <el-button type="primary" plain :icon="Refresh" @click="refresh">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 三 Tab：行业全景 / 概念趋势 / 个股趋势（懒加载，仅激活时挂载并缓存） -->
    <el-tabs v-model="activeTab" type="border-card" class="trend-tabs">
      <el-tab-pane label="行业全景" name="industry">
        <KeepAlive>
          <IndustryPanorama v-if="activeTab === 'industry'" :key="`industry-${refreshKey}`" @data-updated="onTabUpdated('industry', $event)" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="概念趋势" name="concept">
        <KeepAlive>
          <BoardQuadrant v-if="activeTab === 'concept'" :key="`concept-${refreshKey}`" @data-updated="onTabUpdated('concept', $event)" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="个股趋势" name="stock">
        <KeepAlive>
          <StockQuadrant v-if="activeTab === 'stock'" :key="`stock-${refreshKey}`" @data-updated="onTabUpdated('stock', $event)" />
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

// 页头刷新：key 变化强制重建当前 tab（保持 KeepAlive 缓存语义，仅重建激活组件）
const refreshKey = ref(0)
const refresh = () => { refreshKey.value++ }

onMounted(() => {
  vibeApi.getLatestTradeDate().then((d) => { if (d) titleDate.value = d })
})
</script>

<style scoped lang="scss">
.trend-analysis-page {
  .trend-tabs {
    :deep(.el-tabs__content) {
      padding: 4px;
    }
    :deep(.el-tab-pane) {
      min-height: 200px;
    }
  }
}
</style>
