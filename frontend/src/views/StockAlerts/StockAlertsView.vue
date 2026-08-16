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
            常用策略命中自动入自选 → 触发买入/卖出待确认指令交由你确认，建仓后持仓再触发卖出指令离场。点击「立即评估」即时生成待确认指令。
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