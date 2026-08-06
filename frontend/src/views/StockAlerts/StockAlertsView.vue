<template>
  <div class="stock-alerts-view">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Odometer /></el-icon>
        监控中心
      </h1>
      <p class="page-description">
        配置信号 / 价格涨跌 / 市场异动规则，行情自动评估并在命中后生成触发记录（非交易时间自动跳过评估）
      </p>
    </div>

    <MonitorCenter />
  </div>
</template>

<script setup lang="ts">
import { Odometer } from '@element-plus/icons-vue'
import MonitorCenter from '@/components/Dashboard/MonitorCenter.vue'

defineOptions({ name: 'StockAlertsView' })
</script>

<style lang="scss" scoped>
.stock-alerts-view { padding: 16px; }
.page-header { margin-bottom: 16px; }
.page-title {
  font-size: 24px; font-weight: 600; margin: 0 0 8px 0;
  display: flex; align-items: center; gap: 10px;
}
.page-description { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
</style>