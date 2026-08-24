/**
 * 日期时间工具函数
 * 统一处理时间转换和显示
 *
 * 处理逻辑（后端时间契约）：
 * 1. 如果时间字符串包含时区信息（+08:00 或 Z），按真实瞬时解析
 * 2. 🔥 如果时间字符串没有时区信息，按 UTC 解释（与后端约定 naive=UTC 一致），
 *    并打 warning —— 正常路径下后端保证所有 datetime 出参都带 +08:00，不会走到这里
 * 3. 最终统一按中国时区（Asia/Shanghai，即 +08:00）渲染
 */

/**
 * 私有：把输入统一解析为 JS Date 瞬时，并规整 naive 语义。
 * - number：秒/毫秒时间戳
 * - 带偏移的字符串：按偏移解析
 * - 无偏移字符串：打警告，按 UTC 解释（后端契约 naive=UTC）
 * 解析失败返回 null。
 */
function parseToInstant(dateStr: string | number | null | undefined): Date | null {
  if (dateStr == null || dateStr === '') return null

  let timeStr: string

  if (typeof dateStr === 'number') {
    // 秒级时间戳（小于 10000000000）转换为毫秒
    const timestamp = dateStr < 10000000000 ? dateStr * 1000 : dateStr
    timeStr = new Date(timestamp).toISOString()
  } else {
    timeStr = String(dateStr).trim()
    // 无偏移的完整 datetime（如 2026-08-20T12:34:56 或带毫秒）→ 按 UTC 解释，不打 +08:00
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(timeStr)) {
      console.warn('[时间契约] 检测到无时区时间字符串，按 UTC 解释（后端约定 naive=UTC）:', timeStr)
      timeStr += 'Z'
    }
  }

  const date = new Date(timeStr)
  return isNaN(date.getTime()) ? null : date
}

/**
 * 格式化时间字符串，自动处理时区转换
 * @param dateStr - 时间字符串或时间戳
 * @param options - 格式化选项
 * @returns 格式化后的时间字符串
 */
export function formatDateTime(
  dateStr: string | number | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  const date = parseToInstant(dateStr)
  if (!date) return dateStr == null || dateStr === '' ? '-' : String(dateStr)

  // 默认格式化选项
  const defaultOptions: Intl.DateTimeFormatOptions = {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }

  // 合并用户提供的选项
  const finalOptions = { ...defaultOptions, ...options }

  // 格式化为中国本地时间（UTC+8）
  return date.toLocaleString('zh-CN', finalOptions)
}

/**
 * 格式化时间并添加相对时间描述
 * @param dateStr - 时间字符串或时间戳
 * @returns 格式化后的时间字符串 + 相对时间
 */
export function formatDateTimeWithRelative(dateStr: string | number | null | undefined): string {
  const date = parseToInstant(dateStr)
  if (!date) return dateStr == null || dateStr === '' ? '-' : String(dateStr)

  // 获取当前时间
  const now = new Date()

  // 计算时间差
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  const hours = Math.floor(diff / (1000 * 60 * 60))
  const minutes = Math.floor(diff / (1000 * 60))

  // 格式化为中国本地时间
  const formatted = date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })

  // 添加相对时间
  let relative = ''
  if (days > 0) {
    relative = `（${days}天前）`
  } else if (hours > 0) {
    relative = `（${hours}小时前）`
  } else if (minutes > 0) {
    relative = `（${minutes}分钟前）`
  } else {
    relative = '（刚刚）'
  }

  return formatted + ' ' + relative
}

/**
 * 仅格式化日期部分（不含时间）
 * @param dateStr - 时间字符串或时间戳
 * @returns 格式化后的日期字符串
 */
export function formatDate(dateStr: string | number | null | undefined): string {
  return formatDateTime(dateStr, {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  })
}

/**
 * 把时间字符串/时间戳转为瞬时毫秒时间戳（供新鲜度/差值计算），
 * 复用统一 naive 语义（naive 按 UTC 解释）。解析失败返回 null。
 * @param dateStr - 时间字符串或时间戳
 * @returns 毫秒时间戳，或 null
 */
export function toTimestamp(dateStr: string | number | null | undefined): number | null {
  const date = parseToInstant(dateStr)
  return date ? date.getTime() : null
}

/**
 * 仅格式化时间部分（不含日期）
 * @param dateStr - 时间字符串或时间戳
 * @returns 格式化后的时间字符串
 */
export function formatTime(dateStr: string | number | null | undefined): string {
  return formatDateTime(dateStr, {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

/**
 * 格式化相对时间（距离现在多久）
 * @param dateStr - 时间字符串或时间戳
 * @returns 相对时间描述
 */
export function formatRelativeTime(dateStr: string | number | null | undefined): string {
  const targetDate = parseToInstant(dateStr)
  if (!targetDate) return dateStr == null || dateStr === '' ? '-' : String(dateStr)

  try {
    // 获取当前时间
    const now = new Date()

    // 计算时间差（毫秒）
    const diff = targetDate.getTime() - now.getTime()
    const absDiff = Math.abs(diff)

    // 转换为各种时间单位
    const seconds = Math.floor(absDiff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    // 判断是过去还是将来
    const isPast = diff < 0

    // 格式化相对时间
    if (days > 0) {
      return isPast ? `${days}天前` : `${days}天后`
    } else if (hours > 0) {
      return isPast ? `${hours}小时前` : `${hours}小时后`
    } else if (minutes > 0) {
      return isPast ? `${minutes}分钟前` : `${minutes}分钟后`
    } else if (seconds > 10) {
      return isPast ? `${seconds}秒前` : `${seconds}秒后`
    } else {
      return isPast ? '刚刚' : '即将执行'
    }
  } catch (e) {
    console.error('相对时间格式化错误:', e, dateStr)
    return String(dateStr)
  }
}

/**
 * 取指定时区（默认北京时间）下的日期字符串 YYYY-MM-DD。
 * 用于业务"交易日/买入日"这类只关心日期、且必须按北京时间取墙钟日期的场景，
 * 避免用 `toISOString().slice(0, 10)`（UTC 日期，北京凌晨会串前一天）产生偏差。
 * 解析失败返回空字符串 ''。
 */
export function toDateStr(
  dateStr: string | number | null | undefined,
  timeZone: string = 'Asia/Shanghai'
): string {
  const date = parseToInstant(dateStr)
  if (!date) return ''

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date)

  const m: Record<string, string> = {}
  for (const p of parts) if (p.type !== 'literal') m[p.type] = p.value
  return `${m.year}-${m.month}-${m.day}`
}

/**
 * 今天（北京时间）的日期字符串 YYYY-MM-DD。
 * 替代 `new Date().toISOString().slice(0, 10)`（UTC 日期）。
 */
export function todayDateInBeijing(): string {
  return toDateStr(new Date(), 'Asia/Shanghai')
}

// 给定时区在指定 UTC 时刻的偏移（墙钟 epoch - UTC epoch），毫秒。
function _tzOffset(utcMs: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(new Date(utcMs))

  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0)
  const wallClockMs = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
  return wallClockMs - utcMs
}

/**
 * 指定时区（默认北京时间）"今天 00:00"对应的绝对 epoch 毫秒。
 * 基于纯 UTC 运算，不依赖浏览器本地时区，用于"今日触发/今日 X"这类按北京交易日的统计边界。
 */
export function todayStartEpoch(timeZone: string = 'Asia/Shanghai'): number {
  const dateStr = toDateStr(new Date(), timeZone) // YYYY-MM-DD in target tz
  const [y, mo, d] = dateStr.split('-').map(Number)
  const utcBase = Date.UTC(y, mo - 1, d)
  return utcBase - _tzOffset(utcBase, timeZone)
}
