/**
 * 策略 ↔ 行情适配元数据
 *
 * 用于「常用策略」/backtest 策略卡片：为每个策略标注「适合 / 慎用」的行情，
 * 并结合后端大盘行情上下文(趋势 bull/sideways/bear + 波动 high/low) 实时给出
 * 三态提醒：适合(green) / 中性(yellow) / 慎用(red)。
 *
 * signals: key=大盘趋势 -> level(1 适合 / 0 中性 / -1 慎用)
 * volSensitive: 高波动时对正向命中下调一级（如趋势、低波动、价值类）。
 */

export type Trend = 'bull' | 'sideways' | 'bear'
export type Volatility = 'high' | 'low'
export type FitLevel = 1 | 0 | -1

export interface MarketContext {
  trend: Trend | 'unknown'
  volatility: Volatility | 'unknown'
  as_of?: string | null
  trend_label?: string
  volatility_label?: string
  up_ratio?: number
  pct_chg?: number
  detail?: string
}

export interface MarketFitMeta {
  /** 适合行情的简要文案（卡片展示） */
  suits: string
  /** 慎用行情的简要文案（卡片展示） */
  avoids: string
  /** 按大盘趋势的适配档位 */
  signals: Record<Exclude<Trend, 'unknown'>, FitLevel>
  /** 高波动时是否对正向命中降级 */
  volSensitive?: boolean
}

export const STRATEGY_MARKET_FIT: Record<string, MarketFitMeta> = {
  ma_golden_cross: {
    suits: '多头趋势（均线走好）',
    avoids: '单边下跌、均线空头',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: false,
  },
  macd_golden: {
    suits: '趋势延续（零轴上方）',
    avoids: '单边下跌、高波动急跌',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: true,
  },
  n_day_high_breakout: {
    suits: '增量牛市、趋势行情',
    avoids: '振荡市（易假突破）、熊市',
    signals: { bull: 1, sideways: 0, bear: -1 },
    volSensitive: true,
  },
  n_day_low_reversal: {
    suits: '超跌企稳、底部反转',
    avoids: '单边下跌（接飞刀）',
    signals: { bull: 0, sideways: 1, bear: 1 },
    volSensitive: true,
  },
  oversold_bounce: {
    suits: '超卖反弹、行情企稳',
    avoids: '强势单边行情（缺超卖）',
    signals: { bull: 0, sideways: 1, bear: 1 },
    volSensitive: true,
  },
  trend_breakout: {
    suits: '增量牛市、趋势行情',
    avoids: '振荡市（假突破）、熊市',
    signals: { bull: 1, sideways: 0, bear: -1 },
    volSensitive: true,
  },
  boll_breakout: {
    suits: '低波动后放量突破',
    avoids: '高波动急跌、缩量阴跌',
    signals: { bull: 1, sideways: 0, bear: -1 },
    volSensitive: true,
  },
  volume_price_surge: {
    suits: '上涨放量、情绪活跃',
    avoids: '缩量熊市、无量阴跌',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: false,
  },
  pullback_ma20_bounce: {
    suits: '健康多头趋势的回踩',
    avoids: '熊市破位续跌',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: true,
  },
  strong_open: {
    suits: '情绪高涨、赚钱效应好',
    avoids: '弱势低迷、易诱多',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: false,
  },
  low_volatility_leader: {
    suits: '慢牛、结构牛',
    avoids: '题材妖股炒作、高波动',
    signals: { bull: 1, sideways: 1, bear: -1 },
    volSensitive: true,
  },
  low_pe_high_div_leader: {
    suits: '熊市避险、存量抱团',
    avoids: '极致成长风偏（跑输）',
    signals: { bull: -1, sideways: 1, bear: 1 },
    volSensitive: true,
  },
  turnaround: {
    suits: '底部企稳、修复初期',
    avoids: '逻辑未验证、单边未止跌',
    signals: { bull: 0, sideways: 1, bear: 1 },
    volSensitive: true,
  },
  small_cap_value: {
    suits: '存量博弈、流动性回暖',
    avoids: '大资金大盘风格主导',
    signals: { bull: 0, sideways: 1, bear: -1 },
    volSensitive: true,
  },
}

const FIT_LABEL: Record<FitLevel, string> = { 1: '适合', 0: '中性', '-1': '慎用' }

export interface FitResult {
  level: FitLevel
  label: string
  meta: MarketFitMeta
}

/**
 * 依据大盘上下文计算某策略当前的适配三态。
 * 规则：先按趋势取基准档位；若该策略 volSensitive 且大盘高波动，
 * 对正向命中(适合)降级为中性（避免在剧烈行情下鼓励激进）。
 */
export function marketFitLevel(id: string, ctx: MarketContext): FitResult {
  const safe: MarketContext = ctx || {}
  const meta = STRATEGY_MARKET_FIT[id]
  if (!meta) return { level: 0, label: FIT_LABEL[0], meta: null as unknown as MarketFitMeta }
  const trend = safe.trend === 'bull' || safe.trend === 'sideways' || safe.trend === 'bear'
    ? safe.trend : 'sideways'
  let level = meta.signals?.[trend] ?? 0
  if (meta.volSensitive && safe.volatility === 'high' && level > 0) level = 0
  return { level, label: FIT_LABEL[level], meta }
}