<template>
  <el-menu
    :default-active="activeMenu"
    :collapse="appStore.sidebarCollapsed"
    :unique-opened="true"
    router
    class="sidebar-menu"
  >
    <el-menu-item index="/dashboard">
      <el-icon><Odometer /></el-icon>
      <template #title>仪表</template>
    </el-menu-item>

    <el-menu-item index="/learning">
      <el-icon><Reading /></el-icon>
      <template #title>资料</template>
    </el-menu-item>

    <el-sub-menu index="/analysis">
      <template #title>
        <el-icon><TrendCharts /></el-icon>
        <span>分析</span>
      </template>
      <el-menu-item index="/analysis/single">单股分析</el-menu-item>
      <el-menu-item index="/analysis/batch">批量分析</el-menu-item>
      <el-menu-item index="/reports">分析报告</el-menu-item>
      <el-menu-item index="/analysis/notifications">通知中心</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/tasks">
      <el-icon><List /></el-icon>
      <template #title>任务</template>
    </el-menu-item>

    <el-sub-menu index="/screening">
      <template #title>
        <el-icon><Search /></el-icon>
        <span>选股</span>
      </template>
      <el-menu-item index="/screening/common">常用策略</el-menu-item>
      <el-menu-item index="/screening/limit-up-pullback">涨停回调</el-menu-item>
      <el-menu-item index="/screening/three-buys-three-sells">三买三卖</el-menu-item>
      <el-menu-item index="/screening/extreme-reversal">极端反转</el-menu-item>
      <el-menu-item index="/screening/turnaround">困境反转</el-menu-item>
      <el-menu-item index="/screening/small-cap-value">小盘价值</el-menu-item>
      <el-menu-item index="/screening/convertible-arbitrage">转债博弈</el-menu-item>
      <el-menu-item index="/screening/ma-crossover">均线交叉</el-menu-item>
      <el-menu-item index="/screening/macd-divergence">MACD背离</el-menu-item>
      <el-menu-item index="/screening/volume-price">量价配合</el-menu-item>
      <el-menu-item index="/screening/comparison">策略对比</el-menu-item>
      <el-menu-item index="/screening/retail-center">散户策略中心</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/favorites">
      <el-icon><Star /></el-icon>
      <template #title>自选</template>
    </el-menu-item>

    <el-sub-menu index="/vibe-review">
      <template #title>
        <el-icon><DataAnalysis /></el-icon>
        <span>市场</span>
      </template>
      <el-menu-item index="/vibe/review/overview">大盘看板</el-menu-item>
      <el-menu-item index="/vibe/review/fundflow">资金流向</el-menu-item>
      <el-menu-item index="/vibe/review/emotion">短线情绪</el-menu-item>
      <el-menu-item index="/vibe/intel/radar">资讯雷达</el-menu-item>
      <el-menu-item index="/vibe/notes">研究记录</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="/paper-root">
      <template #title>
        <el-icon><CreditCard /></el-icon>
        <span>交易</span>
      </template>
      <el-menu-item index="/paper">模拟交易</el-menu-item>
      <el-menu-item index="/portfolio">持仓追踪</el-menu-item>
      <el-menu-item index="/stock-alerts">个股预警</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="/settings-root">
      <template #title>
        <el-icon><Setting /></el-icon>
        <span>设置</span>
      </template>

      <!-- 个人设置 -->
      <el-sub-menu index="/settings-personal">
        <template #title>个人设置</template>
        <el-menu-item index="/settings">通用设置</el-menu-item>
        <el-menu-item index="/settings?tab=appearance">外观设置</el-menu-item>
        <el-menu-item index="/settings?tab=analysis">分析偏好</el-menu-item>
        <el-menu-item index="/settings?tab=notifications">通知设置</el-menu-item>
        <el-menu-item index="/settings?tab=security">安全设置</el-menu-item>
        <el-menu-item index="/settings/tags">标签管理</el-menu-item>
      </el-sub-menu>

      <!-- 系统配置 -->
      <el-sub-menu index="/settings-config">
        <template #title>系统配置</template>
        <el-menu-item index="/settings/config">配置管理</el-menu-item>
        <el-menu-item index="/settings/usage">使用统计</el-menu-item>
        <el-menu-item index="/settings/cache">缓存管理</el-menu-item>
      </el-sub-menu>

      <!-- 系统管理 -->
      <el-sub-menu index="/settings-admin">
        <template #title>系统管理</template>
        <el-menu-item index="/settings/users">用户管理</el-menu-item>
        <el-menu-item index="/settings/database">数据库管理</el-menu-item>
        <el-menu-item index="/settings/logs">操作日志</el-menu-item>
        <el-menu-item index="/settings/system-logs">系统日志</el-menu-item>
        <el-menu-item index="/settings/sync">多数据源同步</el-menu-item>
        <el-menu-item index="/settings/scheduler">定时任务</el-menu-item>
      </el-sub-menu>
    </el-sub-menu>

    <el-menu-item index="/about">
      <el-icon><InfoFilled /></el-icon>
      <template #title>关于</template>
    </el-menu-item>
  </el-menu>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import {
  Odometer,
  Reading,
  TrendCharts,
  Search,
  Star,
  List,
  Setting,
  InfoFilled,
  CreditCard,
  DataAnalysis,
  Wallet,
  Bell,
  ChatDotRound
} from '@element-plus/icons-vue'

const route = useRoute()
const appStore = useAppStore()

const activeMenu = computed(() => route.path)
</script>

<style lang="scss" scoped>
.sidebar-menu {
  border: none;
  height: 100%;

  // 调整菜单项高度
  :deep(.el-menu-item),
  :deep(.el-sub-menu__title) {
    height: 50px;
    line-height: 50px;
    font-size: 16px;
    font-weight: 500;
  }

  // 调整子菜单项
  :deep(.el-menu .el-menu-item) {
    font-size: 15px;
    height: 44px;
    line-height: 44px;
  }

  // 调整图标大小
  :deep(.el-icon) {
    font-size: 20px;
    margin-right: 10px;
  }

  // 调整子菜单的图标
  :deep(.el-sub-menu .el-icon) {
    font-size: 20px;
  }

  // 调整文字样式
  :deep(.el-menu-item span),
  :deep(.el-sub-menu__title span) {
    font-size: 16px;
    font-weight: 500;
    letter-spacing: 0.5px;
  }

  // 当前激活项样式
  :deep(.el-menu-item.is-active) {
    background-color: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
    font-weight: 600;
  }

  // 悬停效果
  :deep(.el-menu-item:hover),
  :deep(.el-sub-menu__title:hover) {
    background-color: var(--el-color-primary-light-9);
  }
}
</style>
