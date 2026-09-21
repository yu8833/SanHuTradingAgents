<template>
  <div class="trend-analysis-page">
    <!-- 三 Tab：个股趋势 / 概念趋势 / 行业趋势（懒加载，仅激活时挂载并缓存） -->
    <el-tabs v-model="activeTab" type="border-card" class="trend-tabs">
      <el-tab-pane label="个股趋势" name="stock">
        <KeepAlive>
          <StockQuadrant v-if="activeTab === 'stock'" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="概念趋势" name="concept">
        <KeepAlive>
          <BoardQuadrant v-if="activeTab === 'concept'" key="concept" scope="concept" />
        </KeepAlive>
      </el-tab-pane>
      <el-tab-pane label="行业趋势" name="industry">
        <KeepAlive>
          <BoardQuadrant v-if="activeTab === 'industry'" key="industry" scope="industry" />
        </KeepAlive>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StockQuadrant from './StockQuadrant.vue'
import BoardQuadrant from './BoardQuadrant.vue'

defineOptions({ name: 'TrendAnalysis' })

const activeTab = ref<'stock' | 'concept' | 'industry'>('stock')
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