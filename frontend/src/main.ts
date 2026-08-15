import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import zhCn from 'element-plus/es/locale/lang/zh-cn'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

import App from './App.vue'
import router from './router'
import { setupGlobalComponents } from './components'
import { useAuthStore } from './stores/auth'
import { useAppStore } from './stores/app'
import './styles/index.scss'
import './styles/dark-theme.scss'

// 创建应用实例
const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 使用插件
const pinia = createPinia()
app.use(pinia)
app.use(router)
// 设置全局中文 locale（Element Plus）
dayjs.locale('zh-cn')
app.use(ElementPlus, {
  size: 'default',
  zIndex: 3000,
  locale: zhCn,
  // 配置消息提示
  message: {
    max: 3, // 最多同时显示3个消息
    grouping: true, // 启用消息分组，相同内容的消息不会重复显示
    duration: 3000, // 默认显示时长3秒
  },
})

// 注册全局组件
setupGlobalComponents(app)

// 全局错误处理
app.config.errorHandler = (err, _vm, info) => {
  console.error('全局错误:', err, info)

  // 检查是否是认证错误
  if (err && typeof err === 'object') {
    const error = err as any
    // 检查错误消息或状态码
    if (
      error.message?.includes('认证失败') ||
      error.message?.includes('登录已过期') ||
      error.message?.includes('Token') ||
      error.response?.status === 401 ||
      error.code === 401
    ) {
      console.log('🔒 全局错误处理：检测到认证错误，跳转登录页')
      const authStore = useAuthStore()
      authStore.clearAuthInfo()
      router.push('/login')
    }
  }

  // 这里可以集成错误监控服务
}

// 全局警告处理
app.config.warnHandler = (msg, _vm, trace) => {
  console.warn('全局警告:', msg, trace)
}

// 初始化认证状态（非阻塞：先挂载 UI，再异步检查后端状态）
const initApp = async () => {
  try {
    const authStore = useAuthStore()
    const appStore = useAppStore()

    // 应用主题（同步操作，速度快）
    appStore.applyTheme()
    console.log('🎨 主题已应用:', appStore.theme)

    // 设置网络状态监听
    window.addEventListener('online', () => {
      console.log('🌐 网络已连接')
      appStore.setOnlineStatus(true)
      appStore.checkApiConnection()
    })

    window.addEventListener('offline', () => {
      console.log('📱 网络已断开')
      appStore.setOnlineStatus(false)
      appStore.setApiConnected(false)
    })

    // 异步检查 API 连接（不阻塞挂载，NetworkStatus 组件会处理断连状态）
    appStore.checkApiConnection().then(apiConnected => {
      if (apiConnected) {
        console.log('✅ API连接正常，检查认证状态...')
        authStore.checkAuthStatus().then(() => {
          if (authStore.isAuthenticated) {
            authStore.ensureTokenRefreshTimer()
          }
        }).catch(err => {
          console.warn('⚠️ 认证检查失败，应用将继续运行:', err)
        })
      } else {
        console.log('⚠️ API连接失败，跳过认证检查')
      }
    }).catch(err => {
      console.warn('⚠️ API连接检查失败，应用将继续运行:', err)
    })
  } catch (error) {
    console.warn('⚠️ 应用初始化失败，但应用将继续启动:', error)
  }
}

// 先挂载应用让用户看到 UI，再异步初始化后端状态
app.mount('#app')
console.log('🚀 应用已挂载')
initApp()

// 开发环境下的调试信息
if (import.meta.env.DEV) {
  console.log('🚀 股票分析系统 v1.0.0-preview 前端应用已启动')
  console.log('📊 当前环境:', import.meta.env.MODE)
  console.log('🔗 API地址:', import.meta.env.VITE_API_BASE_URL || '/api')
}
