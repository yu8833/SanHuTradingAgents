<template>
  <div class="trend-analysis-page">
    <!-- 三 Tab：行业趋势 / 概念趋势 / 个股趋势（懒加载，仅激活时挂载并缓存） -->
    <el-tabs v-model="activeTab" type="border-card" class="trend-tabs">
      <el-tab-pane label="行业趋势" name="industry">
        <KeepAlive>
          <IndustryPanorama v-if="activeTab === 'industry'" key="industry" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="概念趋势" name="concept">
        <KeepAlive>
          <BoardQuadrant v-if="activeTab === 'concept'" key="concept" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="个股趋势" name="stock">
        <KeepAlive>
          <StockQuadrant v-if="activeTab === 'stock'" key="stock" />
        </KeepAlive>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import IndustryPanorama from './IndustryPanorama.vue'
import StockQuadrant from './StockQuadrant.vue'
import BoardQuadrant from './BoardQuadrant.vue'

defineOptions({ name: 'TrendAnalysis' })

const activeTab = ref<'industry' | 'concept' | 'stock'>('industry')
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
