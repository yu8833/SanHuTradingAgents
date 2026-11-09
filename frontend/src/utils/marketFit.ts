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
  /** 统一操作建议文案（后端下发，与大盘看板保持一致） */
  advice?: string
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

// ─────────────────────────────────────────────────────────────
// 行情画像分组：把「常用策略」按大盘画像分组展示（减少策略卡片数量）
// ─────────────────────────────────────────────────────────────

export type RegimeGroupId =
  | '牛市强趋势'
  | '牛市普涨'
  | '震荡蓄势'
  | '震荡分化'
  | '熊市阴跌'
  | '熊市恐慌'
  | '高波动市'
  | '全面适用'

export interface RegimeGroupMeta {
  id: RegimeGroupId
  /** 展示名（未设置时用 id）。「熊市恐慌」组同时承载「熊市反弹」画像 */
  label?: string
  /** 该组收益来源（一句话） */
  earn: string
  /** 失效条件（一句话） */
  lose: string
  /** 判定条件，阈值与后端 market_state 一致 */
  condition: string
  /** 轮盘/分组主色 */
  color: string
}

/** 轮盘顺序 = 一轮行情的自然流转（牛 → 顶 → 熊 → 底） */
export const REGIME_GROUPS: RegimeGroupMeta[] = [
  {
    id: '牛市普涨',
    earn: '全面上涨，弹性优先',
    lose: '次日高开低走、缩量滞涨',
    condition: '近5日涨家占比 ≥55% 且分散普涨',
    color: '#e5484d',
  },
  {
    id: '牛市强趋势',
    earn: '主线趋势延续，3~10 日惯性',
    lose: '放量假突破、跌破 MA20',
    condition: '近5日涨家占比 ≥55% + 成交集中于主线',
    color: '#f3731f',
  },
  {
    id: '震荡分化',
    earn: '结构性行情，精选个股',
    lose: '风格反转、个股逻辑证伪',
    condition: '趋势中性 + 涨跌分化（宽度 <18pp 摆动）',
    color: '#e0a800',
  },
  {
    id: '震荡蓄势',
    earn: '区间下沿低吸的波段收益',
    lose: '区间被向下击穿、假突破',
    condition: '趋势中性 + 低波动（振幅 <2.5%）+ 缩量',
    color: '#4f9d69',
  },
  {
    id: '熊市阴跌',
    earn: '股息 + 估值修复的防御收益',
    lose: '盈利/分红恶化',
    condition: '涨家占比 ≤45% + 窄幅 + 分化',
    color: '#3b7dd8',
  },
  {
    id: '熊市恐慌',
    label: '熊市恐慌 / 反弹',
    earn: '恐慌错杀 / 熊市反弹初期的 1~3 日收益',
    lose: '下跌中继放量、反弹次日即破',
    condition: '中期跌破年线 + 短期宽度转强（熊市反弹），或高波动 + 情绪恐慌',
    color: '#1f5f9e',
  },
  {
    id: '高波动市',
    earn: '情绪脉冲，快进快出',
    lose: '单边趋势中逆势承接',
    condition: '任意趋势 + 20日振幅 ≥2.5% 或宽度摆动 ≥18pp',
    color: '#8b5cf6',
  },
  {
    id: '全面适用',
    earn: '与大盘方向无关（债底保护等）',
    lose: '个券信用风险',
    condition: '不依赖大盘状态',
    color: '#8d99ae',
  },
]

export const REGIME_GROUP_ORDER: RegimeGroupId[] = REGIME_GROUPS.map((g) => g.id)

/** 组内优先级：primary=首选（建议开启），secondary=备选（信号不与首选重叠），其余归「同族其他」 */
export const STRATEGY_ROLE: Record<string, 'primary' | 'secondary'> = {
  trend_breakout: 'primary',
  pullback_ma20_bounce: 'secondary',
  n_day_high_breakout: 'primary',
  n_day_low_reversal: 'primary',
  boll_breakout: 'secondary',
  small_cap_value: 'primary',
  turnaround: 'secondary',
  low_pe_high_div_leader: 'primary',
  bottom_volume: 'primary',
  // 超跌反弹：熊市反弹画像（中期在年线下方 + 短期宽度转强）的直接对应策略
  oversold_bounce: 'primary',
  convertible_arbitrage: 'primary',
  low_volatility_leader: 'secondary',
}

/**
 * 策略归属的唯一画像组（保证一个策略只在页面出现一次）。
 * 默认取 market_regimes 中排序最靠前的一组，个别策略用 overrides 指定更合适的归属。
 */
const HOME_OVERRIDE: Record<string, RegimeGroupId> = {
  n_day_high_breakout: '牛市普涨',
  macd_golden: '牛市强趋势',
  one_yang_three_yin: '震荡蓄势',
  small_cap_value: '震荡分化',
  turnaround: '熊市阴跌',
  bottom_volume: '熊市恐慌',
  volume_price_surge: '高波动市',
  strong_open: '高波动市',
  low_volatility_leader: '全面适用',
  convertible_arbitrage: '全面适用',
  oversold_bounce: '熊市恐慌',
  extreme_reversal: '熊市恐慌',
  emotion_cycle: '高波动市',
  event_driven: '高波动市',
  chan_theory: '高波动市',
  wave_theory: '高波动市',
  expectation_repricing: '震荡分化',
}

export function homeRegimeOf(id: string, regimes?: string[]): RegimeGroupId {
  const home = HOME_OVERRIDE[id]
  if (home) return home
  const hit = REGIME_GROUP_ORDER.find((g) => (regimes || []).includes(g))
  return hit ?? '全面适用'
}

/** 四维检测结果 → 画像（唯一实现，矩阵面板与画像分组共用，避免两处规则漂移）
 *  规则与后端 market_state._derive_portrait 保持一致；「熊市反弹」需要短期宽度信息，
 *  四维里没有，故手动调维度时只能得到「熊市恐慌」。
 *  后端返回的权威画像请用 portraitToGroup() 直接取组。 */
export interface PortraitDims {
  trend?: string
  vol?: string
  breadth?: string
  sentiment?: string
}

export function portraitOf(d: PortraitDims): RegimeGroupId {
  if (!d) return '震荡蓄势'
  if (d.trend === '牛市') {
    return d.breadth === '普涨' ? '牛市普涨' : '牛市强趋势'
  }
  if (d.trend === '熊市') {
    return d.vol === '高波动' || d.sentiment === '恐慌' ? '熊市恐慌' : '熊市阴跌'
  }
  if (d.vol === '高波动') return '高波动市'
  if (d.vol === '低波动' || d.breadth === '普涨') return '震荡蓄势'
  return '震荡分化'
}

/** 后端权威画像 → 页面分组（一个策略组可承载多个画像，如「熊市恐慌 / 反弹」）。 */
export function portraitToGroup(portrait?: string | null): RegimeGroupId {
  if (!portrait) return '震荡蓄势'
  if (portrait === '熊市反弹') return '熊市恐慌'
  return (REGIME_GROUP_ORDER as string[]).includes(portrait)
    ? (portrait as RegimeGroupId)
    : '震荡蓄势'
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