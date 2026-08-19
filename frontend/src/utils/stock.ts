/**
 * 股票相关工具函数
 */

/**
 * 生成股票详情页链接
 * 支持 sh./sz. 前缀和纯6位代码
 */
export function stockLink(code: string | number): string {
  if (!code && code !== 0) return '#'
  const codeStr = String(code).trim()
  const cleanCode = codeStr.replace(/^(sh|sz)\./i, '')
  return `/stocks/${cleanCode}`
}

/**
 * 统一排序比较函数（数值型）
 * 处理 null/undefined 空值，空值排在最后
 */
export function sortNumber(a: any, b: any): number {
  const aVal = (a ?? null)
  const bVal = (b ?? null)
  if (aVal == null && bVal == null) return 0
  if (aVal == null) return 1
  if (bVal == null) return -1
  return Number(aVal) - Number(bVal)
}

/**
 * 统一排序比较函数（字符串型）
 */
export function sortString(a: any, b: any): number {
  const aVal = (a ?? '').toString()
  const bVal = (b ?? '').toString()
  return aVal.localeCompare(bVal, 'zh-CN')
}

/**
 * 表格列：股票代码列（可点击跳转）
 */
export const stockCodeColumn = (label = '代码', width = 90) => ({
  label,
  prop: 'code',
  width,
  sortable: true,
  align: 'left' as const,
  template: (row: any) =>
    `<router-link to="${stockLink(row.code)}" class="stock-code">${row.code}</router-link>`
})

/**
 * 表格列：股票名称列（可点击跳转）
 */
export const stockNameColumn = (label = '名称', minWidth = 120) => ({
  label,
  prop: 'name',
  minWidth,
  sortable: true,
  align: 'left' as const,
  template: (row: any) =>
    `<router-link to="${stockLink(row.code)}" class="stock-name">${row.name}</router-link>`
})
