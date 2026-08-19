/**
 * 统一金融数据格式化工具
 *
 * 目标：全站数值/单位/小数位/正负号/空值格式一致，避免各页面各自实现导致对不齐。
 *
 * 约定：
 * - 空值（null / undefined / NaN）统一显示为 "-"。
 * - 所有"百分比"输入一律为"百分数数值"（如 1.23 代表 1.23%）；
 *   仅函数名带 FromFraction 的接受"小数"（如 0.0123 代表 1.23%）。
 * - 金额/成交量/市值统一使用中文单位（元/万/亿/万亿），不使用 K/M 英文缩写。
 * - 正负号统一为 "+x"/"-x"，上涨/盈利为正、下跌/亏损为负。
 */

const EMPTY = '-'

function isInvalid(v: unknown): boolean {
  return v === null || v === undefined || Number.isNaN(Number(v))
}

function toNum(v: unknown): number {
  return Number(v)
}

/** 通用空值占位（用于对齐空值显示） */
export const EMPTY_VALUE = EMPTY

/** 数值 → 固定小数位；无效 → '-'。如 fmtNum(3.14159) => '3.14' */
export function fmtNum(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  return toNum(v).toFixed(digits)
}

/** 价格 → 固定小数位；无效 → '-'。如 fmtPrice(12.345) => '12.35' */
export function fmtPrice(v: unknown, digits = 2): string {
  return fmtNum(v, digits)
}

/** 百分数数值（如 1.23）→ '+1.23%' / '-1.23%'；无效 → '-' */
export function fmtPct(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

/** 小数（如 0.0123）→ '+1.23%' / '-1.23%'；无效 → '-' */
export function fmtPctFromFraction(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v) * 100
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

/** 带正负号的数值（百分数数值，不含%）：如 +1.23 / -1.23；无效 → '-' */
export function fmtSigned(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`
}

/** 数值绝对值 → 固定小数位（用于"涨跌分别着色、无需正负号"的展示）：如 fmtAbsPct(-1.23) => '1.23' */
export function fmtAbs(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  return Math.abs(toNum(v)).toFixed(digits)
}

/** 百分数数值的绝对值 → '1.23%'（不带正负号）；无效 → '-'。如 fmtAbsPct(-1.23) => '1.23%' */
export function fmtAbsPct(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  return `${Math.abs(toNum(v)).toFixed(digits)}%`
}

/** 涨跌着色类：正→'up'、负→'down'、零/空→emptyClass（默认 'flat'，可传 '' 表示不加类） */
export function clsByVal(v: unknown, emptyClass = 'flat'): string {
  if (isInvalid(v) || toNum(v) === 0) return emptyClass
  return toNum(v) > 0 ? 'up' : 'down'
}

/** 元 → 亿（固定单位，2 位小数）；无效 → '-'。如 fmtYi(150000000) => '1.50' */
export function fmtYi(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  return (toNum(v) / 1e8).toFixed(digits)
}

/** 元 → 亿带正负号：如 +1.50 / -1.50；无效 → '-' */
export function fmtYiSigned(v: unknown, digits = 2): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v) / 1e8
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`
}

/** 金额自动缩放（万亿/亿/万，含单位）：如 1.5亿；无效 → '-' */
export function fmtAmount(v: unknown): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}万亿`
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

/** 金额自动缩放 + 正负号（万亿/亿/万）：如 +1.5亿 / -1.5亿；无效 → '-' */
export function fmtAmountSigned(v: unknown): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  const abs = Math.abs(n)
  const sign = n >= 0 ? '+' : '-'
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}万亿`
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(2)}万`
  return `${sign}${abs.toFixed(2)}`
}

/** 成交量自动缩放（亿股/万股/股）：如 1.5亿股；无效 → '-' */
export function fmtVolume(v: unknown): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿股`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万股`
  return `${n.toFixed(0)}股`
}

/** 成交量自动缩放（亿/万，不含"股"后缀）：如 1.5亿 / 12.35万；无效 → '-' */
export function fmtVol(v: unknown): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}

/** 市值自动缩放（万亿/亿）：如 1.5万亿 / 123.45亿；无效 → '-' */
export function fmtMarketCap(v: unknown): string {
  if (isInvalid(v)) return EMPTY
  const n = toNum(v)
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}万亿`
  return `${(n / 1e8).toFixed(2)}亿`
}

/** 金额 → 千分位 + 货币符号：如 ¥1,234,567.89；无效 → '-' */
export function fmtMoney(v: unknown, currency = '¥', digits = 2): string {
  if (isInvalid(v)) return EMPTY
  return `${currency}${toNum(v).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })}`
}