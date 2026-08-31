import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { ElMessage } from 'element-plus'
import NProgress from 'nprogress'
import 'nprogress/nprogress.css'

// 配置NProgress
NProgress.configure({
  showSpinner: false,
  minimum: 0.2,
  easing: 'ease',
  speed: 500
})

// 路由配置
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  // 兼容文档链接：将 /paper/<name>.md 重定向到学习中心文章路由
  {
    path: '/paper/:name.md',
    name: 'PaperMdRedirect',
    redirect: (to) => `/learning/article/${to.params.name as string}`,
    meta: { title: '文档跳转', hideInMenu: true, requiresAuth: false }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '速览',
      icon: 'Dashboard',
      requiresAuth: true,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'DashboardHome',
        component: () => import('@/views/Dashboard/index.vue'),
        meta: {
          title: '速览',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/analysis',
    name: 'Analysis',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/analysis',
    meta: {
      title: '分析',
      icon: 'TrendCharts',
      requiresAuth: true
    },
    children: [
      {
        path: '',
        name: 'StockAnalysis',
        component: () => import('@/views/Analysis/StockAnalysis.vue'),
        meta: {
          title: '股票分析',
          parentTitle: '分析',
          requiresAuth: true
        }
      },
      {
        path: 'single',
        name: 'SingleAnalysis',
        redirect: '/analysis',
        meta: {
          title: '单股分析',
          parentTitle: '分析',
          requiresAuth: true,
          hideInMenu: true
        }
      },
      {
        path: 'batch',
        name: 'BatchAnalysis',
        redirect: '/analysis',
        meta: {
          title: '批量分析',
          parentTitle: '分析',
          requiresAuth: true,
          hideInMenu: true
        }
      },
      ]
  },
  {
    path: '/screening',
    name: 'StockScreening',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/screening/common',
    meta: {
      title: '策略',
      icon: 'Search',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: 'common',
        name: 'StockScreeningCommon',
        component: () => import('@/views/Screening/StrategyScreener.vue'),
        meta: {
          title: '常用策略',
          parentTitle: '策略',
          requiresAuth: true
        }
      },
      {
        path: 'backtest',
        name: 'StrategyBacktest',
        component: () => import('@/views/Screening/StrategyBacktest.vue'),
        meta: {
          title: '策略回测',
          parentTitle: '策略',
          requiresAuth: true
        }
      },
      {
        path: 'convertible-arbitrage',
        name: 'ConvertibleArbitrage',
        component: () => import('@/views/Screening/ConvertibleArbitrage.vue'),
        meta: {
          title: '转债博弈',
          parentTitle: '策略',
          requiresAuth: true
        }
      },
      {
        path: 'macd-divergence',
        name: 'MacdDivergence',
        component: () => import('@/views/Screening/MacdDivergence.vue'),
        meta: {
          title: 'MACD背离',
          parentTitle: '策略',
          requiresAuth: true,
          hidden: true // 高级变体，折叠保留
        }
      },
      {
        path: 'extreme-reversal',
        name: 'ExtremeReversal',
        component: () => import('@/views/Screening/ExtremeReversal.vue'),
        meta: {
          title: '极端反转',
          parentTitle: '策略',
          requiresAuth: true,
          hidden: true // 高级变体，折叠保留
        }
      }
    ]
  },
  {
    path: '/candidate',
    name: 'Candidate',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '候选',
      icon: 'Aim',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'CandidateHome',
        component: () => import('@/views/Candidate/index.vue'),
        meta: {
          title: '候选池',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '自选',
      icon: 'Star',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'FavoritesHome',
        component: () => import('@/views/Favorites/index.vue'),
        meta: {
          title: '自选',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/vibe',
    name: 'VibeResearch',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/vibe/review/overview',
    meta: {
      title: '市场',
      icon: 'DataAnalysis',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: 'review/overview',
        name: 'ReviewOverview',
        component: () => import('@/views/Vibe/Review/Overview.vue'),
        meta: {
          title: '大盘看板',
          parentTitle: '市场',
          requiresAuth: true
        }
      },
      {
        path: 'review/emotion',
        name: 'ReviewEmotion',
        component: () => import('@/views/Vibe/Review/Emotion.vue'),
        meta: {
          title: '短线情绪',
          parentTitle: '市场',
          requiresAuth: true
        }
      },
      {
        path: 'review/concept',
        name: 'ReviewConcept',
        component: () => import('@/views/Vibe/Review/ConceptAnalysis.vue'),
        meta: {
          title: '概念分析',
          parentTitle: '市场',
          requiresAuth: true
        }
      },
      {
        path: 'intel/radar',
        name: 'IntelRadar',
        component: () => import('@/views/Vibe/Intel/Radar.vue'),
        meta: {
          title: '资讯',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/learning',
    name: 'Learning',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '资料',
      icon: 'Reading',
      requiresAuth: false,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'LearningHome',
        component: () => import('@/views/Learning/index.vue'),
        meta: {
          title: '资料',
          requiresAuth: false
        }
      },
      {
        path: ':category',
        name: 'LearningCategory',
        component: () => import('@/views/Learning/Category.vue'),
        meta: {
          title: '分类详情',
          parentTitle: '资料',
          requiresAuth: false
        }
      },
      {
        path: 'article/:id',
        name: 'LearningArticle',
        component: () => import('@/views/Learning/Article.vue'),
        meta: {
          title: '文章详情',
          parentTitle: '资料',
          requiresAuth: false
        }
      }
    ]
  },
  {
    path: '/stocks',
    name: 'Stocks',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '股票详情',
      icon: 'TrendCharts',
      requiresAuth: true,
      hideInMenu: true,
      transition: 'fade'
    },
    children: [
      {
        path: ':code',
        name: 'StockDetail',
        component: () => import('@/views/Stocks/Detail.vue'),
        meta: {
          title: '股票详情',
          requiresAuth: true,
          hideInMenu: true,
          transition: 'fade'
        }
      }
    ]
  },


  {
    path: '/tasks',
    name: 'TaskCenter',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '任务',
      icon: 'List',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'TaskCenterHome',
        component: () => import('@/views/Tasks/TaskCenter.vue'),
        meta: { title: '任务', requiresAuth: true }
      }
    ]
  },
  { path: '/queue', redirect: '/tasks' },
  { path: '/analysis/history', redirect: '/tasks?tab=completed' },
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '历史报告',
      icon: 'Document',
      requiresAuth: true,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'ReportsHome',
        component: () => import('@/views/Reports/index.vue'),
        meta: {
          title: '历史报告',
          parentTitle: '分析',
          requiresAuth: true
        }
      },
      {
        path: 'view/:id',
        name: 'ReportDetail',
        component: () => import('@/views/Reports/ReportDetail.vue'),
        meta: {
          title: '报告详情',
          parentTitle: '分析',
          requiresAuth: true
        }
      },
      {
        path: 'token',
        name: 'TokenStatistics',
        component: () => import('@/views/Reports/TokenStatistics.vue'),
        meta: {
          title: 'Token统计',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '设置',
      icon: 'Setting',
      requiresAuth: true,
      transition: 'slide-left'
    },
    children: [
      {
        path: '',
        name: 'SettingsHome',
        component: () => import('@/views/Settings/index.vue'),
        meta: {
          title: '通用设置',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'config',
        name: 'ConfigManagement',
        component: () => import('@/views/Settings/ConfigManagement.vue'),
        meta: {
          title: '配置管理',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'database',
        name: 'DatabaseManagement',
        component: () => import('@/views/System/DatabaseManagement.vue'),
        meta: {
          title: '数据库管理',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'logs',
        name: 'OperationLogs',
        component: () => import('@/views/System/OperationLogs.vue'),
        meta: {
          title: '操作日志',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'system-logs',
        name: 'LogManagement',
        component: () => import('@/views/System/LogManagement.vue'),
        meta: {
          title: '系统日志',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'sync',
        name: 'MultiSourceSync',
        component: () => import('@/views/System/MultiSourceSync.vue'),
        meta: {
          title: '多数据源同步',
          parentTitle: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'users',
        name: 'UserManagement',
        component: () => import('@/views/System/UserManagement.vue'),
        meta: {
          title: '用户管理',
          parentTitle: '设置',
          requiresAuth: true,
          requiresAdmin: true
        }
      },
      {
        path: 'tags',
        name: 'TagManagement',
        component: () => import('@/views/Settings/TagManagement.vue'),
        meta: {
          title: '标签管理',
          parentTitle: '设置',
          requiresAuth: true
        }
      }
    ]
  },

  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Auth/Login.vue'),
    meta: {
      title: '登录',
      hideInMenu: true,
      transition: 'fade'
    }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Auth/Register.vue'),
    meta: {
      title: '注册',
      hideInMenu: true,
      transition: 'fade'
    }
  },

  {
    path: '/about',
    name: 'About',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '关于',
      icon: 'InfoFilled',
      requiresAuth: false,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'AboutHome',
        component: () => import('@/views/About/index.vue'),
        meta: {
          title: '关于',
          requiresAuth: false,
          transition: 'fade'
        }
      }
    ]
  },
  {
    path: '/paper',
    name: 'PaperTrading',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '交易',
      icon: 'CreditCard',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'PaperTradingHome',
        component: () => import('@/views/PaperTrading/index.vue'),
        meta: {
          title: '交易',
          requiresAuth: true
        }
      },
      {
        path: '/portfolio',
        name: 'PortfolioView',
        component: () => import('@/views/Portfolio/PortfolioView.vue'),
        meta: {
          title: '持仓追踪',
          requiresAuth: true
        }
      },
      {
        path: '/stock-alerts',
        name: 'StockAlertsView',
        component: () => import('@/views/StockAlerts/StockAlertsView.vue'),
        meta: {
          title: '监控中心',
          requiresAuth: true
        }
      },
      {
        path: 'review',
        name: 'PaperReview',
        component: () => import('@/views/PaperTrading/Review.vue'),
        meta: {
          title: '交易复盘',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/Error/404.vue'),
    meta: {
      title: '页面不存在',
      hideInMenu: true,
      requiresAuth: false  // 未登录用户输错URL也应看到404，而非跳转登录
    }
  }
]

// 创建路由实例
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    } else {
      return { top: 0 }
    }
  }
})

// 全局前置守卫
router.beforeEach(async (to, _from, next) => {
  // 开始进度条
  NProgress.start()

  const authStore = useAuthStore()
  const appStore = useAppStore()

  // 设置页面标题
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - 股票分析系统`
  }

  console.log('🚦 路由守卫检查:', {
    path: to.fullPath,
    name: to.name,
    requiresAuth: to.meta.requiresAuth,
    isAuthenticated: authStore.isAuthenticated,
    hasToken: !!authStore.token
  })

  // 检查是否需要认证
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    console.log('🔒 需要认证但用户未登录:', {
      path: to.fullPath,
      requiresAuth: to.meta.requiresAuth,
      isAuthenticated: authStore.isAuthenticated,
      token: authStore.token ? '存在' : '不存在'
    })
    // 保存原始路径，登录后跳转
    authStore.setRedirectPath(to.fullPath)
    next('/login')
    return
  }

  // 检查是否需要管理员权限
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    console.log('🚫 需要管理员权限但用户不是管理员:', {
      path: to.fullPath,
      username: authStore.user?.username,
      is_admin: authStore.user?.is_admin
    })
    ElMessage.error('权限不足，需要管理员权限')
    next('/dashboard')
    return
  }



  // 如果已登录且访问登录页，重定向到仪表板
  if (authStore.isAuthenticated && to.name === 'Login') {
    next('/dashboard')
    return
  }

  // 更新当前路由信息
  appStore.setCurrentRoute(to)

  next()
})

// 全局后置守卫
router.afterEach((_to, _from) => {
  // 结束进度条
  NProgress.done()

  // 页面切换后的处理
  nextTick(() => {
    // 可以在这里添加页面分析、埋点等逻辑
  })
})

// 路由错误处理
router.onError((error) => {
  console.error('路由错误:', error)
  NProgress.done()
  ElMessage.error('页面加载失败，请重试')
})

export default router

// 导出路由配置供其他地方使用
export { routes }
