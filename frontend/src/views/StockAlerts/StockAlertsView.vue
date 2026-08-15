<template>
  <div class="stock-alerts-view">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Odometer /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">监控中心</h2>
          <p class="page-hero-sub">
            配置信号 / 价格涨跌 / 市场异动规则，行情自动评估并在命中后生成触发记录（非交易时间自动跳过评估）
          </p>
        </div>
      </div>
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
.stock-alerts-view { padding: 24px; }
</style>