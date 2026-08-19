import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  Aim, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Back,
  Bell, Bottom, Brush, Calendar, Check, CircleCheck,
  CircleCheckFilled, CircleClose, CircleCloseFilled, Clock, Close, Coin,
  Collection, Connection, Cpu, CreditCard, Crop, DArrowRight,
  DataAnalysis, DataBoard, DataLine, Delete, Document, Download,
  EditPen, Expand, Files, Fold, FullScreen, Grid,
  Histogram, HomeFilled, House, InfoFilled, Key, Lightning,
  Link, List, Loading, Lock, MagicStick, Message,
  Minus, Money, Monitor, Moon, Odometer, OfficeBuilding,
  Operation, Opportunity, Plus, PriceTag, Promotion, QuestionFilled,
  Rank, Reading, Refresh, RefreshRight, Remove, Right,
  Search, Select, Sell, Setting, ShoppingCart, Sort,
  Star, SuccessFilled, Sunny, SwitchButton, Timer, Tools,
  TrendCharts, Upload, User, UserFilled, View, Wallet,
  Warning, WarningFilled,
} from '@element-plus/icons-vue'
// 按需引入：模板组件由 unplugin-vue-components 自动注入样式，
// 此处仅显式补上「命令式 API」所需的浮层样式（ElMessage/ElMessageBox 等在 JS 中手动调用，
// 无法被模板按需扫描覆盖），从而可以移除全量 element-plus/dist/index.css，大幅减小包体。
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/es/components/loading/style/css'
import 'element-plus/es/components/popper/style/css'
import 'element-plus/es/components/overlay/style/css'

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

// 注册 Element Plus 图标（仅注册模板中实际用到的 86 个，避免全量 293 个进包）
// 白名单由 scripts/extract-icons.mjs 扫描 src 模板自动生成
const icons = {
  Aim, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Back,
  Bell, Bottom, Brush, Calendar, Check, CircleCheck,
  CircleCheckFilled, CircleClose, CircleCloseFilled, Clock, Close, Coin,
  Collection, Connection, Cpu, CreditCard, Crop, DArrowRight,
  DataAnalysis, DataBoard, DataLine, Delete, Document, Download,
  EditPen, Expand, Files, Fold, FullScreen, Grid,
  Histogram, HomeFilled, House, InfoFilled, Key, Lightning,
  Link, List, Loading, Lock, MagicStick, Message,
  Minus, Money, Monitor, Moon, Odometer, OfficeBuilding,
  Operation, Opportunity, Plus, PriceTag, Promotion, QuestionFilled,
  Rank, Reading, Refresh, RefreshRight, Remove, Right,
  Search, Select, Sell, Setting, ShoppingCart, Sort,
  Star, SuccessFilled, Sunny, SwitchButton, Timer, Tools,
  TrendCharts, Upload, User, UserFilled, View, Wallet,
  Warning, WarningFilled,
}
for (const [key, component] of Object.entries(icons)) {
  app.component(key, component)
}

// 使用插件
const pinia = createPinia()
app.use(pinia)
app.use(router)
// 设置全局中文 locale（Element Plus）
dayjs.locale('zh-cn')

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
