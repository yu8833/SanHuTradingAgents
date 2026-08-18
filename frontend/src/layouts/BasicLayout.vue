<template>
  <div class="basic-layout" :class="{ 'sidebar-open on-mobile': isMobile && !appStore.sidebarCollapsed }">
    <!-- 侧边栏 -->
    <aside
      class="sidebar"
      :class="{ collapsed: appStore.sidebarCollapsed, 'is-mobile': isMobile }"
      :style="{ width: sidebarWidthPx }"
    >
      <div class="sidebar-header">
        <div class="logo">
          <img src="/logo.svg" alt="股票分析系统" />
          <span v-show="!appStore.sidebarCollapsed || isMobile" class="logo-text">
            股票分析系统
          </span>
        </div>
      </div>
      
      <nav class="sidebar-nav">
        <SidebarMenu />
      </nav>
      
      <div class="sidebar-footer">
        <UserProfile />
      </div>
    </aside>

    <!-- 点击蒙层：移动端展开时，点击空白处收起侧边栏 -->
    <div
      v-if="isMobile && !appStore.sidebarCollapsed"
      class="sidebar-overlay"
      @click="appStore.setSidebarCollapsed(true)"
    ></div>

    <!-- 主内容区 -->
    <div class="main-container" :style="{ marginLeft: mainMarginLeft }" @click="handleMainClick">
      <!-- 顶部导航栏 -->
      <header class="header">
        <div class="header-left">
          <el-button
            type="text"
            @click.stop="appStore.toggleSidebar()"
            class="sidebar-toggle"
          >
            <el-icon><Expand v-if="appStore.sidebarCollapsed" /><Fold v-else /></el-icon>
          </el-button>
          
          <Breadcrumb />
        </div>
        
        <div class="header-right">
          <HeaderActions />
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="main-content">
        <div class="content-wrapper">
          <router-view v-slot="{ Component, route }">
            <transition
              :name="route.meta.transition || 'fade'"
              mode="out-in"
              appear
            >
              <keep-alive :include="keepAliveComponents">
                <component :is="Component" :key="route.fullPath" />
              </keep-alive>
            </transition>
          </router-view>
        </div>
      </main>

      <!-- 页脚 -->
      <footer class="footer">
        <AppFooter />
      </footer>
    </div>

    <!-- 回到顶部 -->
    <el-backtop :right="40" :bottom="40" />
  </div>
</template>

<script setup lang="ts">
import { computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useWindowSize } from '@vueuse/core'
import { useAppStore } from '@/stores/app'
import SidebarMenu from '@/components/Layout/SidebarMenu.vue'
import UserProfile from '@/components/Layout/UserProfile.vue'
import Breadcrumb from '@/components/Layout/Breadcrumb.vue'
import HeaderActions from '@/components/Layout/HeaderActions.vue'
import AppFooter from '@/components/Layout/AppFooter.vue'
import { Expand, Fold } from '@element-plus/icons-vue'

const appStore = useAppStore()
const route = useRoute()
const { width } = useWindowSize()

// 需要缓存的组件（使用路由 name，与 router/index.ts 中的 name 一致）
// keep-alive 的 include 匹配的是组件 name，但 Vue SFC 未显式声明 name 时，
// 会回退到路由 matched 组件的 name。这里用路由 name 作为缓存标识。
// 缓存高频返回的列表/工作台页面，保留滚动位置与查询状态。
const keepAliveComponents = computed(() => [
  'DashboardHome',       // 仪表盘
  'StockScreeningCommon',// 常用策略
  'TaskCenterHome',      // 任务中心
  'FavoritesHome',       // 自选股
  'ReportsHome',         // 历史报告
  'ReviewOverview'       // 大盘看板
])

// 移动端判断
const isMobile = computed(() => width.value < 768)

// 计算实际侧边栏宽度（考虑移动端）
const sidebarWidthPx = computed(() => {
  if (isMobile.value && appStore.sidebarCollapsed) {
    return '0px'
  }
  return appStore.actualSidebarWidth + 'px'
})

// 计算主内容区左边距
const mainMarginLeft = computed(() => {
  if (isMobile.value) {
    return '0px'
  }
  return appStore.actualSidebarWidth + 'px'
})

// 点击主内容时，若移动端且侧边栏已展开，则收起
const handleMainClick = () => {
  if (isMobile.value && !appStore.sidebarCollapsed) {
    appStore.setSidebarCollapsed(true)
  }
}

// 移动端侧边栏打开时锁定 body 滚动
const syncBodyScroll = () => {
  if (isMobile.value && !appStore.sidebarCollapsed) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
}

watch([isMobile, () => appStore.sidebarCollapsed], () => {
  syncBodyScroll()
})

// 监听窗口大小变化：在小屏幕上自动折叠侧边栏
watch(width, (newWidth) => {
  if (newWidth < 768 && !appStore.sidebarCollapsed) {
    appStore.setSidebarCollapsed(true)
  }
  if (newWidth >= 768 && appStore.sidebarCollapsed) {
    // 恢复桌面端时，如果之前是默认展开的，可以保持展开
    // 这里保持 collapsed 状态，由用户手动展开
  }
})

// 路由变化时，移动端收起侧边栏
watch(() => route.fullPath, () => {
  if (isMobile.value) {
    appStore.setSidebarCollapsed(true)
  }
})

onMounted(() => {
  syncBodyScroll()
})

onUnmounted(() => {
  document.body.style.overflow = ''
})
</script>

<style lang="scss" scoped>
.basic-layout {
  min-height: 100vh;
  background-color: var(--el-bg-color-page);
}

.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 950;
}

.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  background-color: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  transition: width 0.3s ease, transform 0.3s ease;
  z-index: 1000;
  display: flex;
  flex-direction: column;

  &.collapsed:not(.is-mobile) {
    width: 64px !important;
  }

  .sidebar-header {
    height: 56px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    border-bottom: 1px solid var(--el-border-color-lighter);

    .logo {
      display: flex;
      align-items: center;
      gap: 10px;

      img {
        width: 28px;
        height: 28px;
      }

      .logo-text {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        white-space: nowrap;
      }
    }
  }

  .sidebar-nav {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }

  .sidebar-footer {
    border-top: 1px solid var(--el-border-color-lighter);
    padding: 6px;
  }
}

.main-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  transition: margin-left 0.3s ease;
}

.header {
  height: 60px;
  background-color: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 999;

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;

    .sidebar-toggle {
      padding: 8px;
      
      .el-icon {
        font-size: 18px;
      }
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }
}

.main-content {
  flex: 1;
  padding: 24px;
  min-height: calc(100vh - 60px - 60px);

  .content-wrapper {
    max-width: min(1680px, 96vw);
    margin: 0 auto;
  }
}

.footer {
  display: none;
}

// 响应式设计
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    box-shadow: none;
    
    &:not(.collapsed) {
      transform: translateX(0);
      box-shadow: 4px 0 24px rgba(0, 0, 0, 0.12);
    }
  }

  .main-container {
    margin-left: 0 !important;
    width: 100%;
  }

  .main-content {
    padding: 12px;
    padding-top: 12px;
  }

  .header {
    padding: 0 12px;
    gap: 8px;
    position: sticky;
    top: 0;

    .header-left {
      gap: 8px;
      flex: 1 1 auto;
      min-width: 0;
    }

    .header-right {
      gap: 6px;
      flex-shrink: 0;
    }

    .header-right :deep(.el-button) {
      padding: 6px;
    }

    .header-right .header-action-label,
    .breadcrumb,
    :deep(.el-breadcrumb) {
      .el-breadcrumb__separator {
        display: none;
      }
    }
  }
}

@media (max-width: 480px) {
  .header {
    height: 52px;
    .header-left .sidebar-toggle {
      padding: 6px;
    }
  }
}

// 路由过渡动画
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-left-enter-active,
.slide-left-leave-active {
  transition: all 0.3s ease;
}

.slide-left-enter-from {
  transform: translateX(30px);
  opacity: 0;
}

.slide-left-leave-to {
  transform: translateX(-30px);
  opacity: 0;
}
</style>
