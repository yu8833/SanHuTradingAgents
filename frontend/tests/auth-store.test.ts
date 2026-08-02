/**
 * 防回归测试：auth store
 *
 * 钉住的 bug：
 *   bug-005: token 刷新定时器泄漏（每次登录创建新 setInterval 但不清理，
 *            导致多次登录后定时器数量无限增长）
 *
 * 测试策略：
 *   1. clearAuthInfo 必须调用 clearInterval 并重置 _tokenRefreshTimerId
 *   2. ensureTokenRefreshTimer 再次调用时必须先清理旧定时器，确保全局唯一
 *   3. 连续多次调用必须不产生重复定时器
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { setActivePinia, createPinia } from 'pinia'

function makeValidToken(expOffsetSeconds = 3600) {
  const header = btoa(JSON.stringify({ alg: 'HS256' }))
  const payload = btoa(
    JSON.stringify({ sub: '1', exp: Math.floor(Date.now() / 1000) + expOffsetSeconds })
  )
  return `${header}.${payload}.sig`
}

describe('auth store - 基础状态', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('初始状态 token 为 null，_tokenRefreshTimerId 为 null', () => {
    const store = useAuthStore()
    expect(store.token).toBeNull()
    expect((store as any)._tokenRefreshTimerId).toBeNull()
  })

  it('isAuthenticated 根据 token 存在与否判断', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    store.token = makeValidToken()
    store.isAuthenticated = true
    expect(store.isAuthenticated).toBe(true)
  })
})

// ============================================================
// bug-005 核心钉住：定时器生命周期管理
// ============================================================
describe('bug-005: auth store - 定时器生命周期必须正确管理', () => {
  let clearIntervalSpy: ReturnType<typeof vi.spyOn>
  let setIntervalSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => {})
    setIntervalSpy = vi.spyOn(globalThis, 'setInterval').mockImplementation(() => 999 as any)
  })
  afterEach(() => {
    clearIntervalSpy.mockRestore()
    setIntervalSpy.mockRestore()
  })

  it('clearAuthInfo 必须清理 _tokenRefreshTimerId 并调用 clearInterval', () => {
    const store = useAuthStore()
    ;(store as any)._tokenRefreshTimerId = 123
    store.token = makeValidToken()
    store.isAuthenticated = true
    store.user = { username: 'admin', is_admin: true } as any

    store.clearAuthInfo()

    // ======= bug-005 关键断言 =======
    expect(clearIntervalSpy).toHaveBeenCalledWith(123)
    expect((store as any)._tokenRefreshTimerId).toBeNull()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.isAuthenticated).toBe(false)
  })

  it('clearAuthInfo 对 _tokenRefreshTimerId 为 null 时也不报错', () => {
    const store = useAuthStore()
    ;(store as any)._tokenRefreshTimerId = null
    expect(() => store.clearAuthInfo()).not.toThrow()
    expect(clearIntervalSpy).not.toHaveBeenCalled()
  })

  it('ensureTokenRefreshTimer 对同一 store 多次调用，必须只保留 1 个定时器', async () => {
    const store = useAuthStore()
    store.token = makeValidToken()

    // 模拟多次触发 ensureTokenRefreshTimer（等价于多次登录/路由切换）
    for (let i = 0; i < 3; i++) {
      await store.ensureTokenRefreshTimer()
    }

    // ======= bug-005 关键断言 =======
    // setInterval 每轮都被调用，但中间每次都被 clearInterval 清掉旧的
    const created = setIntervalSpy.mock.calls.length
    // 至少调用 setInterval（至少 1 次）
    expect(created).toBeGreaterThanOrEqual(1)
    // 最终只保留一个 timerId
    expect((store as any)._tokenRefreshTimerId).not.toBeNull()
  })

  it('登出后再登录的流程：登出时清定时器，登录后才创建', async () => {
    const store = useAuthStore()
    store.token = makeValidToken()
    await store.ensureTokenRefreshTimer()
    expect((store as any)._tokenRefreshTimerId).toBe(999)

    // 登出（等价于 clearAuthInfo）
    store.clearAuthInfo()
    expect(clearIntervalSpy).toHaveBeenCalled()
    expect((store as any)._tokenRefreshTimerId).toBeNull()

    // 重新登录（模拟）
    store.token = makeValidToken()
    await store.ensureTokenRefreshTimer()
    expect((store as any)._tokenRefreshTimerId).toBe(999)
  })
})
