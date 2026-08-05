<template>
  <div class="network-status" v-if="showStatus">
    <el-alert
      v-if="!appStore.isOnline"
      title="网络连接已断开"
      type="warning"
      :closable="false"
      show-icon
    >
      <template #default>
        <span>请检查您的网络连接</span>
      </template>
    </el-alert>
    
    <el-alert
      v-else-if="shouldShowApiError"
      title="后端服务连接失败"
      type="error"
      :closable="false"
      show-icon
    >
      <template #default>
        <span>无法连接到后端服务，请检查服务是否正常运行</span>
        <el-button 
          type="primary" 
          size="small" 
          @click="retryConnection"
          :loading="retrying"
          style="margin-left: 10px;"
        >
          重试连接
        </el-button>
      </template>
    </el-alert>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const retrying = ref(false)

// 只在有网络问题时显示状态
const showStatus = computed(() => {
  return !appStore.isOnline || shouldShowApiError.value
})

// 后端连接失败提示：需连续失败≥2次才展示，避免瞬时抖动/网络抖动误报
const shouldShowApiError = computed(() => {
  return appStore.apiChecked && !appStore.apiConnected && appStore.apiFailureStreak >= 2
})

// 重试连接
const retryConnection = async () => {
  retrying.value = true
  try {
    await appStore.checkApiConnection()
    if (appStore.apiConnected) {
      console.log('✅ API连接恢复')
    }
  } catch (error) {
    console.error('❌ 重试连接失败:', error)
  } finally {
    retrying.value = false
  }
}

// 定期检查API连接状态
let checkInterval: number | null = null

onMounted(() => {
  // 每10秒检查一次API连接状态（加快重试频率）
  checkInterval = window.setInterval(() => {
    // 🔥 改进：无论网络状态如何，只要后端未连接就尝试重连
    if (!appStore.apiConnected) {
      console.log('🔄 尝试重连后端服务...')
      appStore.checkApiConnection()
    }
  }, 10000)

  // 🔥 额外：在组件挂载时立即尝试一次连接检查
  setTimeout(() => {
    if (!appStore.apiConnected) {
      console.log('🔄 组件挂载时尝试重连...')
      appStore.checkApiConnection()
    }
  }, 1000)
})

onUnmounted(() => {
  if (checkInterval) {
    clearInterval(checkInterval)
  }
})
</script>

<style scoped>
.network-status {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  max-width: 400px;
}

.network-status :deep(.el-alert) {
  margin-bottom: 10px;
}

.network-status :deep(.el-alert__content) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
