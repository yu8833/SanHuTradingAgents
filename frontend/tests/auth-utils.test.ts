/**
 * 防回归测试：auth 工具函数
 *
 * 钉住的 bug：
 *   bug-005: setupTokenRefreshTimer 不返回 timerId 导致定时器泄漏
 *   bug-007: vibe.ts 使用 localStorage.getItem('token') 而非 'auth-token'
 *
 * 覆盖的函数：
 *   - isTokenValid
 *   - parseToken
 *   - getTokenRemainingTime
 *   - setupTokenRefreshTimer / clearTokenRefreshTimer
 *   - isAuthError
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import {
  isTokenValid,
  parseToken,
  getTokenRemainingTime,
  setupTokenRefreshTimer,
  clearTokenRefreshTimer,
  isAuthError,
} from '@/utils/auth'
import { useAuthStore } from '@/stores/auth'
import { setActivePinia, createPinia } from 'pinia'

describe('isAuthError - 认证错误识别', () => {
  it('识别 401 状态码', () => {
    expect(isAuthError({ response: { status: 401 } })).toBe(true)
  })
  it('识别业务错误码 40101/40102/40103', () => {
    expect(isAuthError({ code: 40101 })).toBe(true)
    expect(isAuthError({ response: { data: { code: 40102 } } })).toBe(true)
  })
  it('识别包含"token"/"未授权"/"登录已过期"的错误消息', () => {
    expect(isAuthError({ message: 'Token 已失效' })).toBe(true)
    expect(isAuthError({ message: '未授权的请求' })).toBe(true)
  })
  it('非认证错误返回 false', () => {
    expect(isAuthError({ response: { status: 500 } })).toBe(false)
    expect(isAuthError({ message: '网络超时' })).toBe(false)
    expect(isAuthError(null)).toBe(false)
    expect(isAuthError(undefined)).toBe(false)
  })
})

describe('isTokenValid - Token 有效性校验', () => {
  it('null / 空字符串返回 false', () => {
    expect(isTokenValid(null)).toBe(false)
    expect(isTokenValid('')).toBe(false)
  })
  it('mock-token 视为无效', () => {
    expect(isTokenValid('mock-token')).toBe(false)
    expect(isTokenValid('mock-abc')).toBe(false)
  })
  it('非 JWT 格式（不是 3 段）返回 false', () => {
    expect(isTokenValid('abc.def')).toBe(false)
    expect(isTokenValid('only.one')).toBe(false)
  })
  it('有效的 JWT token 返回 true', () => {
    // 手工构造一个 payload.exp 为未来的 token
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const payload = btoa(
      JSON.stringify({ sub: '1', exp: Math.floor(Date.now() / 1000) + 3600 })
    )
    const sig = 'fake-signature'
    expect(isTokenValid(`${header}.${payload}.${sig}`)).toBe(true)
  })
  it('过期的 JWT token 返回 false', () => {
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const payload = btoa(
      JSON.stringify({ sub: '1', exp: Math.floor(Date.now() / 1000) - 100 })
    )
    expect(isTokenValid(`${header}.${payload}.sig`)).toBe(false)
  })
  it('payload 无法 base64 解码时返回 false', () => {
    expect(isTokenValid('a.!!!.c')).toBe(false)
  })
})

describe('parseToken - 解析 Token payload', () => {
  it('正确解析有效 token', () => {
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const payload = JSON.stringify({ sub: '123', username: 'admin' })
    const tok = `${header}.${btoa(payload)}.sig`
    const p = parseToken(tok)
    expect(p).toEqual(expect.objectContaining({ sub: '123', username: 'admin' }))
  })
  it('非 3 段 token 返回 null', () => {
    expect(parseToken('a.b')).toBeNull()
  })
  it('无法解码时返回 null', () => {
    expect(parseToken('a.@#$.c')).toBeNull()
  })
})

describe('getTokenRemainingTime - 剩余时间计算', () => {
  it('无效 token 返回 0', () => {
    expect(getTokenRemainingTime('bad.token')).toBe(0)
  })
  it('无 exp 字段返回 0', () => {
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const payload = btoa(JSON.stringify({ sub: '1' }))
    expect(getTokenRemainingTime(`${header}.${payload}.sig`)).toBe(0)
  })
  it('未过期时返回正数', () => {
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const exp = Math.floor(Date.now() / 1000) + 1800
    const payload = btoa(JSON.stringify({ exp }))
    const remaining = getTokenRemainingTime(`${header}.${payload}.sig`)
    expect(remaining).toBeGreaterThan(0)
    expect(remaining).toBeLessThanOrEqual(1800)
  })
  it('过期后返回 0', () => {
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const exp = Math.floor(Date.now() / 1000) - 10
    const payload = btoa(JSON.stringify({ exp }))
    expect(getTokenRemainingTime(`${header}.${payload}.sig`)).toBe(0)
  })
})

// ============================================================
// bug-005 钉住：setupTokenRefreshTimer 必须返回 timerId，
//              clearTokenRefreshTimer 能正确清理
// ============================================================
describe('bug-005: Token 刷新定时器生命周期', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const store = useAuthStore()
    // 写入一个假 token，让 setupTokenRefreshTimer 走启动分支
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const payload = btoa(JSON.stringify({ sub: '1', exp: Math.floor(Date.now() / 1000) + 3600 }))
    store.token = `${header}.${payload}.sig`
  })

  it('setupTokenRefreshTimer 返回的 timerId 是有效值，不是 null/undefined', () => {
    const timerId = setupTokenRefreshTimer()
    // ======= bug-005 关键断言：必须是有效值（number 或 Timeout 对象），不是 null/undefined =======
    expect(timerId).not.toBeNull()
    expect(timerId).not.toBeUndefined()
    // 浏览器返回 number，Node/happy-dom 可能返回 object(Timeout)，都算合法
    const ok = typeof timerId === 'number' || typeof timerId === 'object'
    expect(ok).toBe(true)
    // 清理
    clearTokenRefreshTimer(timerId)
  })

  it('setupTokenRefreshTimer 内部调用了 setInterval', () => {
    const spySetInterval = vi.spyOn(globalThis, 'setInterval')
    const id = setupTokenRefreshTimer()
    expect(spySetInterval).toHaveBeenCalled()
    clearTokenRefreshTimer(id)
    spySetInterval.mockRestore()
  })

  it('无 token 时 setupTokenRefreshTimer 返回 null（不启动定时器）', () => {
    const store = useAuthStore()
    store.token = null
    const id = setupTokenRefreshTimer()
    expect(id).toBeNull()
  })

  it('clearTokenRefreshTimer 会调用 clearInterval 清理定时器', () => {
    const spyClear = vi.spyOn(globalThis, 'clearInterval')
    const fakeId = 42 as any
    clearTokenRefreshTimer(fakeId)
    expect(spyClear).toHaveBeenCalledWith(42)
    spyClear.mockRestore()
  })

  it('clearTokenRefreshTimer 对 null/undefined 不调用 clearInterval（防越界）', () => {
    const spyClear = vi.spyOn(globalThis, 'clearInterval')
    clearTokenRefreshTimer(null)
    clearTokenRefreshTimer(undefined)
    expect(spyClear).not.toHaveBeenCalled()
    spyClear.mockRestore()
  })
})

// ============================================================
// bug-007 钉住：任何从 localStorage 取 token 的地方都必须使用
//              key 'auth-token'，不能使用 'token'
//
// 策略：直接读 TS 源文件做静态断言，保证源码级约束永不复发
// ============================================================
const AUTH_STORE_SRC = fs.readFileSync(
  path.resolve(__dirname, '../src/stores/auth.ts'),
  'utf-8'
)
const VIBE_SRC = fs.readFileSync(
  path.resolve(__dirname, '../src/api/vibe.ts'),
  'utf-8'
)

describe('bug-007: localStorage token key 一致性校验（源码静态断言）', () => {
  it('auth store 写 localStorage 时使用正确 key "auth-token"，且不能出现错误 key "token" 单独写入', () => {
    // ======= bug-007 关键断言：必须存在正确 key =======
    expect(AUTH_STORE_SRC).toContain(`localStorage.setItem('auth-token'`)
    // ======= bug-007 关键断言：绝对不能出现错误 key =======
    expect(AUTH_STORE_SRC).not.toContain(`localStorage.setItem('token',`)
    expect(AUTH_STORE_SRC).not.toContain(`localStorage.setItem("token",`)
    // 读路径也不能错
    expect(AUTH_STORE_SRC).not.toContain(`localStorage.getItem('token')`)
    expect(AUTH_STORE_SRC).not.toContain(`localStorage.getItem("token")`)
  })

  it('vibe.ts 中必须使用 "auth-token" 作为 localStorage token key，不能用错误的 "token"', () => {
    // ======= bug-007 关键断言 =======
    expect(VIBE_SRC).not.toContain(`getItem('token')`)
    expect(VIBE_SRC).not.toContain(`getItem("token")`)
    expect(VIBE_SRC).not.toContain(`setItem('token',`)
    expect(VIBE_SRC).not.toContain(`setItem("token",`)
    // 正确模式：至少存在 auth-token 的使用
    expect(VIBE_SRC).toContain('auth-token')
  })
})
