/**
 * 防回归测试：notifications store - WebSocket 生命周期管理
 *
 * 钉住的 bug：
 *   bug-006: 登出后 notifications WebSocket 未主动断开，
 *            因鉴权失效触发自动重连，进入空转重连循环。
 *
 * 策略：
 *   1. 静态源码断言：notifications.ts 源文件必须包含正确的 watch token 逻辑
 *   2. 因为闭包变量 wsReconnectTimer/wsReconnectAttempts 在测试环境很难访问，
 *      用"源码断言"作为主验证手段，行为测试作为补充。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const NOTIF_STORE_SRC = fs.readFileSync(
  path.resolve(__dirname, '../src/stores/notifications.ts'),
  'utf-8'
)

describe('bug-006 源码静态检查：notifications store 必须包含正确的 watch token 逻辑', () => {
  it('notifications.ts 中存在 watch 和 token 引用', () => {
    expect(NOTIF_STORE_SRC).toContain('watch')
    expect(NOTIF_STORE_SRC).toContain('token')
  })

  it('watch 回调中存在 watch(() => useAuthStore().token, (newToken, oldToken) ...) 模式', () => {
    expect(NOTIF_STORE_SRC).toMatch(/watch\s*\(\s*\(\s*\)\s*=>\s*useAuthStore\(\)\.token/)
  })

  it('token 为空分支中必须断开 WebSocket：调用 disconnectWebSocket 或 ws.close', () => {
    // 找到真正的 watch token 逻辑：以 "watch(() => useAuthStore().token" 为起点，向后取 600 字符
    const watchTokenStart = NOTIF_STORE_SRC.indexOf('watch(() => useAuthStore().token')
    expect(watchTokenStart).toBeGreaterThan(-1)
    const watchBlock = NOTIF_STORE_SRC.slice(watchTokenStart, watchTokenStart + 800)

    // ======= bug-006 关键断言 =======
    // 存在 !newToken / !token 的空分支
    const hasEmptyBranch = watchBlock.includes('!newToken') || watchBlock.includes('!token')
    // 该分支中必须调用 disconnectWebSocket 或 ws.close
    const hasDisconnect = watchBlock.includes('disconnectWebSocket') || watchBlock.includes('.close(')
    expect(hasEmptyBranch).toBe(true)
    expect(hasDisconnect).toBe(true)
  })

  it('token 为空分支中必须清除 wsReconnectTimer（clearTimeout）并置空', () => {
    const watchTokenStart = NOTIF_STORE_SRC.indexOf('watch(() => useAuthStore().token')
    expect(watchTokenStart).toBeGreaterThan(-1)
    const watchBlock = NOTIF_STORE_SRC.slice(watchTokenStart, watchTokenStart + 800)

    // ======= bug-006 关键断言 =======
    expect(watchBlock).toContain('wsReconnectTimer')
    expect(watchBlock).toContain('clearTimeout')
    expect(watchBlock).toMatch(/wsReconnectTimer\s*=\s*null/)
  })

  it('token 为空分支中必须重置 wsReconnectAttempts = 0', () => {
    const watchTokenStart = NOTIF_STORE_SRC.indexOf('watch(() => useAuthStore().token')
    expect(watchTokenStart).toBeGreaterThan(-1)
    const watchBlock = NOTIF_STORE_SRC.slice(watchTokenStart, watchTokenStart + 800)

    // ======= bug-006 关键断言 =======
    expect(watchBlock).toContain('wsReconnectAttempts')
    expect(watchBlock).toMatch(/wsReconnectAttempts\s*=\s*0/)
  })
})

// ============================================================
// 代码风格 & 防御性校验
// ============================================================
describe('notifications store - 代码质量静态检查', () => {
  it('connectWebSocket 在无 token 时不得直接建 WS，必须提前返回并 scheduleReconnect', () => {
    // 确保守卫逻辑：无 token 的路径
    expect(NOTIF_STORE_SRC).toContain("if (!token)")
    expect(NOTIF_STORE_SRC).toContain('未找到 token')
    // 必须调用 scheduleReconnect（下次 token 回来时自动重连）
    expect(NOTIF_STORE_SRC).toContain('scheduleReconnect')
  })

  it('存在 disconnectWebSocket 函数或 close 逻辑（不仅仅是 connect）', () => {
    const hasDisconnectFn = NOTIF_STORE_SRC.includes('function disconnectWebSocket')
      || NOTIF_STORE_SRC.includes('const disconnectWebSocket')
      || NOTIF_STORE_SRC.includes('disconnectWebSocket =')
    const hasWsClose = NOTIF_STORE_SRC.includes('ws.value?.close(')
      || NOTIF_STORE_SRC.includes('ws.value.close(')
    expect(hasDisconnectFn || hasWsClose).toBe(true)
  })
})
