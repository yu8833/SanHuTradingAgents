/**
 * 常用策略名称对齐工具。
 *
 * 页面（持仓追踪、交易复盘、监控指令等）保存的策略字段是策略 ID（如 macd_golden），
 * 展示时需映射为「常用策略」的名称（如 MACD金叉）。统一从这里取数：拉取一次
 * /api/strategy/list 构建 id→name 映射并缓存，避免各页面各自维护一份易失真的映射。
 */
import { strategyApi } from '@/api/strategy'

// 兜底映射（策略列表接口失败或尚未加载完成时，也能给出一致可读的名称，
// 名称与后端 BUILTIN_STRATEGIES 保持一致）
const FALLBACK_NAMES: Record<string, string> = {
  ma_golden_cross: 'MA金叉',
  macd_golden: 'MACD金叉',
  n_day_high_breakout: '创60日新高',
  n_day_low_reversal: 'N日低点反转',
  oversold_bounce: '超跌反弹',
  trend_breakout: '趋势突破',
  boll_breakout: '布林突破',
  volume_price_surge: '量价齐升',
  pullback_ma20_bounce: '回踩MA20反弹',
  strong_open: '强势高开',
  low_volatility_leader: '低波动龙头',
  low_pe_high_div_leader: '低估值高股息龙头',
  turnaround: '困境反转',
  small_cap_value: '小盘价值',
  tbs: 'MA金叉', // 旧数据兼容
  default: '默认',
}

let _idToName: Record<string, string> | null = null
let _loadPromise: Promise<Record<string, string>> | null = null

async function _loadMap(): Promise<Record<string, string>> {
  try {
    const res = await strategyApi.list()
    const data = (res as any)?.data ?? res
    const items = Array.isArray(data) ? data : (data?.items ?? [])
    const map: Record<string, string> = { ...FALLBACK_NAMES }
    for (const meta of items) {
      if (meta?.id && meta?.name) map[meta.id] = meta.name
    }
    return map
  } catch (e) {
    return { ...FALLBACK_NAMES }
  }
}

/** 获取 id→name 映射（惰性加载 + 缓存 + 并发去重）。 */
export function getStrategyNameMap(): Promise<Record<string, string>> {
  if (_idToName) return Promise.resolve(_idToName)
  if (!_loadPromise) {
    _loadPromise = _loadMap().then((m) => {
      _idToName = m
      return m
    })
  }
  return _loadPromise
}

/** 把策略 ID 转成常用策略名称；未知 ID 原样返回（兼容 future 策略）。 */
export async function strategyName(id: string | null | undefined): Promise<string> {
  if (!id) return '默认'
  const map = await getStrategyNameMap()
  return map[id] || FALLBACK_NAMES[id] || id
}

/** 同步版本：未加载完成时用兜底映射，避免模板渲染等待。 */
export function strategyNameSync(id: string | null | undefined): string {
  if (!id) return '默认'
  return FALLBACK_NAMES[id] || id
}