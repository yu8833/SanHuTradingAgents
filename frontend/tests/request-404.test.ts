/**
 * 防回归测试：全局响应拦截器 404 分支
 *
 * 钉住的 bug（实测 001232 嘉立创）：
 *   个股详情页并行请求之一「三买三卖 buy-sell-check」对次新股/历史不足
 *   返回业务性 404 `{"detail":"001232 历史数据不足"}`。旧拦截器 404 分支
 *   无视 config.skipErrorHandler、也无视后端 detail，一律弹「请求的资源不存在」，
 *   让用户误以为是系统故障 / 资源丢失。
 *
 * 修复：
 *   1) 404 分支尊重 skipErrorHandler（业务性 404 留给调用方空态承接，不弹全局窗）
 *   2) 非跳过时透出后端 detail（如「无效的股票代码」「历史数据不足」），
 *      仅当无可读文案（FastAPI 路由级默认 Not Found）才回退通用提示。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { ElMessage } from 'element-plus'
import { request } from '@/api/request'

// 自定义 adapter：直接以 AxiosError 形态 reject（axios 默认 adapter 内的 settle
// 校验状态码失败即 reject；自定义 adapter 需自建该行为才能走到响应错误拦截器）
function mock404Response(data: Record<string, unknown>) {
  request.defaults.adapter = async (config: any) => {
    const error: any = new Error('Request failed with status code 404')
    error.code = 'ERR_BAD_REQUEST'
    error.config = config
    error.response = { status: 404, statusText: 'Not Found', data, headers: {}, config }
    throw error
  }
}

function resetAdapter() {
  request.defaults.adapter = undefined as any
}

describe('request 拦截器 · 404 分支', () => {
  afterEach(() => {
    resetAdapter()
    // 越过消息 3s 去重窗口（setup.ts 启用了 fake timers，否则连续用例同文案互斥）
    vi.advanceTimersByTime(4000)
    vi.clearAllMocks()
  })

  it('skipErrorHandler=true 时业务性 404 不弹全局错误（详情页空态承接）', async () => {
    mock404Response({ detail: '001232 历史数据不足' })
    await expect(
      request.get('/api/stocks/001232/buy-sell-check', { skipErrorHandler: true })
    ).rejects.toBeTruthy()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('非跳过时透出后端 detail（无效代码等）', async () => {
    mock404Response({ detail: '无效的股票代码: 001232' })
    await expect(request.get('/api/stocks/001232/quote')).rejects.toBeTruthy()
    expect(ElMessage.error).toHaveBeenCalledWith('无效的股票代码: 001232')
  })

  it('detail 缺失时回退通用提示', async () => {
    mock404Response({})
    await expect(request.get('/api/stocks/001232/unknown-route')).rejects.toBeTruthy()
    expect(ElMessage.error).toHaveBeenCalledWith('请求的资源不存在（可能已下线或代码有误）')
  })

  it('FastAPI 路由级默认 Not Found 回退通用提示（不把英文透给用户）', async () => {
    mock404Response({ detail: 'Not Found' })
    await expect(request.get('/api/stocks/001232/sync/status')).rejects.toBeTruthy()
    expect(ElMessage.error).toHaveBeenCalledWith('请求的资源不存在（可能已下线或代码有误）')
  })
})