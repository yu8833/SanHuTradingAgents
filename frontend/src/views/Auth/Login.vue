<template>
  <div class="login-page">
    <!-- 背景装饰：光晕 + 网格 + K线剪影 -->
    <div class="bg-glow bg-glow-1"></div>
    <div class="bg-glow bg-glow-2"></div>
    <div class="bg-grid"></div>
    <svg class="bg-candles" viewBox="0 0 480 360" fill="none" aria-hidden="true">
      <g class="candle-cluster" opacity="0.22">
        <path d="M30 30V150" stroke="#f87171" stroke-width="2" />
        <rect x="23" y="66" width="14" height="72" fill="#f87171" />
        <path d="M80 50V130" stroke="#4ade80" stroke-width="2" />
        <rect x="73" y="58" width="14" height="40" fill="#4ade80" />
        <path d="M130 20V120" stroke="#f87171" stroke-width="2" />
        <rect x="123" y="52" width="14" height="48" fill="#f87171" />
        <path d="M180 40V150" stroke="#4ade80" stroke-width="2" />
        <rect x="173" y="74" width="14" height="58" fill="#4ade80" />
        <path d="M230 10V110" stroke="#f87171" stroke-width="2" />
        <rect x="223" y="34" width="14" height="62" fill="#f87171" />
        <path d="M280 60V170" stroke="#4ade80" stroke-width="2" />
        <rect x="273" y="78" width="14" height="44" fill="#4ade80" />
        <path d="M330 30V130" stroke="#f87171" stroke-width="2" />
        <rect x="323" y="60" width="14" height="54" fill="#f87171" />
        <path d="M380 20V140" stroke="#4ade80" stroke-width="2" />
        <rect x="373" y="42" width="14" height="66" fill="#4ade80" />
        <path d="M430 50V160" stroke="#f87171" stroke-width="2" />
        <rect x="423" y="76" width="14" height="52" fill="#f87171" />
      </g>
      <g class="candle-cluster" opacity="0.14" transform="translate(60 150)">
        <path d="M40 20V120" stroke="#93c5fd" stroke-width="2" />
        <rect x="33" y="50" width="14" height="40" fill="#93c5fd" />
        <path d="M100 40V140" stroke="#93c5fd" stroke-width="2" />
        <rect x="93" y="70" width="14" height="34" fill="#93c5fd" />
        <path d="M160 10V110" stroke="#93c5fd" stroke-width="2" />
        <rect x="153" y="38" width="14" height="44" fill="#93c5fd" />
        <path d="M220 30V130" stroke="#93c5fd" stroke-width="2" />
        <rect x="213" y="60" width="14" height="40" fill="#93c5fd" />
        <path d="M280 20V120" stroke="#93c5fd" stroke-width="2" />
        <rect x="273" y="48" width="14" height="42" fill="#93c5fd" />
      </g>
      <path class="candle-trend" d="M20 60L70 50L120 72L170 40L220 58L270 30L320 46L370 24L420 42L460 20"
        stroke="#93c5fd" stroke-width="2" stroke-linecap="round" opacity="0.3" />
    </svg>

    <div class="login-container">
      <div class="login-header">
        <img src="/logo.svg" alt="股票分析系统" class="logo" />
        <h1 class="title">股票分析系统</h1>
        <p class="subtitle">多智能体股票分析学习平台</p>
      </div>

      <el-card class="login-card" shadow="never">
        <el-form
          :model="loginForm"
          :rules="loginRules"
          ref="loginFormRef"
          label-position="top"
          size="large"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="loginForm.username"
              placeholder="请输入用户名"
              prefix-icon="User"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item>
            <div class="form-options">
              <el-checkbox v-model="loginForm.rememberMe">
                记住我
              </el-checkbox>
            </div>
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              style="width: 100%"
              :loading="loginLoading"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form-item>

          <el-form-item>
            <div class="login-tip">
              <el-text size="small">
                还没有账号？
                <el-link type="primary" :underline="false" @click="$router.push('/register')">
                  立即注册
                </el-link>
              </el-text>
            </div>
          </el-form-item>
        </el-form>
      </el-card>

      <div class="login-footer">
        <p>&copy; 2026 股票分析系统. All rights reserved.</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loginFormRef = ref()
const loginLoading = ref(false)

const loginForm = reactive({
  username: '',
  password: '',
  rememberMe: false
})

const loginRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  // 防止重复提交
  if (loginLoading.value) {
    console.log('⏭️ 登录请求进行中，跳过重复点击')
    return
  }

  try {
    await loginFormRef.value.validate()

    loginLoading.value = true
    console.log('🔐 开始登录流程...')

    // 调用真实的登录API
    const success = await authStore.login({
      username: loginForm.username,
      password: loginForm.password
    })

    if (success) {
      console.log('✅ 登录成功')
      ElMessage.success('登录成功')

      // 跳转到重定向路径或仪表板
      const redirectPath = authStore.getAndClearRedirectPath()
      console.log('🔄 重定向到:', redirectPath)
      router.push(redirectPath)
    } else {
      ElMessage.error('用户名或密码错误')
    }

  } catch (error) {
    const err = error as Error
    console.error('登录失败:', err)
    // 只有在不是表单验证错误时才显示错误消息
    if (err.message && !err.message.includes('validate')) {
      ElMessage.error('登录失败，请重试')
    }
  } finally {
    loginLoading.value = false
  }
}


</script>

<style lang="scss" scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(76, 132, 200, 0.35), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(12, 74, 110, 0.5), transparent 60%),
    linear-gradient(160deg, #16324f 0%, #1e3a5f 45%, #2c5282 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.bg-glow {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  filter: blur(60px);

  &-1 {
    width: 420px; height: 420px;
    top: -120px; right: -80px;
    background: rgba(43, 108, 176, 0.35);
    animation: float-glow 12s ease-in-out infinite;
  }

  &-2 {
    width: 380px; height: 380px;
    bottom: -140px; left: -100px;
    background: rgba(12, 74, 110, 0.4);
    animation: float-glow 16s ease-in-out infinite reverse;
  }
}

.bg-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at center, rgba(0, 0, 0, 0.9), transparent 78%);
}

.bg-candles {
  position: absolute;
  right: -30px; bottom: -20px;
  width: 480px; height: 360px;
  pointer-events: none;

  .candle-trend {
    stroke-dasharray: 1200;
    stroke-dashoffset: 1200;
    animation: draw-trend 3.2s 0.6s ease-out forwards;
  }
}

.login-container {
  position: relative;
  width: 100%;
  max-width: 400px;
  z-index: 1;
}

.login-header {
  text-align: center;
  margin-bottom: 28px;
  color: white;
  animation: fade-up 0.55s ease-out both;

  .logo {
    width: 64px;
    height: 64px;
    margin-bottom: 14px;
    filter: drop-shadow(0 4px 14px rgba(0, 0, 0, 0.25));
  }

  .title {
    font-size: 30px;
    font-weight: 700;
    margin: 0 0 8px 0;
    letter-spacing: 1px;
    background: linear-gradient(180deg, #ffffff, #c7d8ec);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .subtitle {
    font-size: 15px;
    opacity: 0.85;
    margin: 0;
    letter-spacing: 0.5px;
  }
}

.login-card {
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 14px;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.28);
  animation: fade-up 0.55s 0.1s ease-out both;

  :deep(.el-card__body) {
    padding: 26px 24px 14px;
  }

  :deep(.el-form-item__label) {
    color: rgba(255, 255, 255, 0.9);
  }

  :deep(.el-input__wrapper) {
    background: rgba(255, 255, 255, 0.94);
    box-shadow: none;
    border: 1px solid transparent;
    transition: border-color 0.2s, box-shadow 0.2s;

    &:hover {
      border-color: rgba(255, 255, 255, 0.5);
    }
  }

  :deep(.el-input__wrapper.is-focus) {
    border-color: #7aa5d8;
    box-shadow: 0 0 0 1px rgba(122, 165, 216, 0.4);
  }

  :deep(.el-checkbox__label) {
    color: rgba(255, 255, 255, 0.9);
  }

  :deep(.el-button--primary) {
    height: 44px;
    font-weight: 600;
    letter-spacing: 2px;
    background: linear-gradient(135deg, #4d84c8, #2b6cb0);
    border: none;
    transition: transform 0.15s ease, box-shadow 0.2s ease;

    &:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 20px rgba(43, 108, 176, 0.45);
    }

    &:active {
      transform: translateY(0);
    }
  }

  .form-options {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
  }

  .login-tip {
    text-align: center;
    width: 100%;
    color: rgba(255, 255, 255, 0.82);

    :deep(.el-link) {
      font-weight: 500;
    }
  }
}

.login-footer {
  text-align: center;
  margin-top: 26px;
  color: white;
  opacity: 0.8;
  animation: fade-up 0.55s 0.2s ease-out both;

  p {
    margin: 0;
    font-size: 13px;
  }
}

@keyframes fade-up {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: none; }
}

@keyframes float-glow {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(22px); }
}

@keyframes draw-trend {
  to { stroke-dashoffset: 0; }
}

@media (max-width: 768px) {
  .bg-candles { display: none; }
  .login-card :deep(.el-card__body) { padding: 22px 18px 10px; }
}
</style>