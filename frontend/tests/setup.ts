/**
 * Vitest 全局 setup
 * 集中 mock 所有运行时注入的全局 API（Vue Router、Pinia、Element Plus、localStorage 等）
 */
import { vi, beforeEach, beforeAll } from 'vitest'
import { config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'

// ---- Mock Element Plus ElMessage / ElNotification ----
const ElMessageMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}
const ElNotificationMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}

vi.mock('element-plus', () => ({
  ElMessage: ElMessageMock,
  ElNotification: ElNotificationMock,
}))

// ---- 初始化 Pinia 实例（所有测试共享） ----
beforeEach(() => {
  const pinia = createPinia()
  setActivePinia(pinia)

  // 清空 localStorage
  window.localStorage.clear()

  // 清空 ElMessage mock
  ElMessageMock.success.mockReset()
  ElMessageMock.error.mockReset()
  ElMessageMock.warning.mockReset()
  ElMessageMock.info.mockReset()
  ElNotificationMock.success.mockReset()
  ElNotificationMock.error.mockReset()

  // 重置所有定时器
  vi.useFakeTimers()
})

beforeAll(() => {
  // 全局 Vue Test Utils 插件：Pinia + Vue Router
  const pinia = createPinia()
  const router = createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div/>' } },
      { path: '/', name: 'home', component: { template: '<div/>' } },
    ],
  })
  config.global.plugins.push(pinia)
  config.global.plugins.push(router)
})
