import type { EChartsOption } from 'echarts'

const MONO = "'SFMono-Regular', ui-monospace, Menlo, monospace"

/** 每图配置：xKey/yKey 为帧 8 元组的字段索引（SQ 常量）或 'pct' 等价索引。 */
export interface QuadrantCfg {
  id: string
  title: string
  xKey: number
  yKey: number
  xName: string
  yName: string
  /** 象限标签（右上/左上/右下/左下） */
  quadrants: [string, string, string, string]
  /** 下方图例色条文字（与 quadrants 同序） */
  tips: [string, string, string, string]
  /** 仅保留符合条件的股票（图6：连板梯队） */
  filter?: (v: number[]) => boolean
  /** 该图空数据时的提示文案 */
  emptyHint?: string
  /** Y 轴为 log（图4 PE / 图5 市值）时置 true，禁用 y=0 标线 */
  logY?: boolean
  /** X 轴单位（亿元/百分号）用于轴名与 tooltip */
  xUnit?: string
  yUnit?: string
  /** 高亮项数值 label 显示的字段索引（默认 x）与格式化 */
  labelKey?: number
}

interface Point {
  code: string
  name: string
  industry: string
  v: number[]
  x: number
  y: number
  isMatch: boolean
}

/** 宝蓝高亮样式（对齐概念地图搜索定位交互） */
const HILIGHT_STYLE = {
  color: '#2563eb',
  borderColor: '#fff',
  borderWidth: 2.5,
  shadowBlur: 18,
  shadowColor: 'rgba(37,99,235,.95)',
}

/** 数据项是否参与绘制（makeQuadrantOption 与 computeMatchPoints 共用，保证两处索引严格一致） */
function passFilter(cfg: QuadrantCfg, v: number[]): boolean {
  if (!Array.isArray(v)) return false
  if (cfg.filter && !cfg.filter(v)) return false
  const x = v[cfg.xKey]
  const y = v[cfg.yKey]
  if (x == null || y == null || Number.isNaN(x) || Number.isNaN(y)) return false
  if (cfg.logY && !(y > 0)) return false
  return !Number.isNaN(v[1])
}

/**
 * 计算搜索命中股票在某图中的 seriesIndex/dataIndex（与 makeQuadrantOption 遍历顺序一致）。
 * 命中点独立于顶层命中系列（seriesIndex=3），dataIndex 即其在匹配列表中的序号。
 */
export function computeMatchPoints(
  frame: Record<string, number[]>,
  cfg: QuadrantCfg,
  matchSet: Set<string>,
): { seriesIndex: number; dataIndex: number }[] {
  const out: { seriesIndex: number; dataIndex: number }[] = []
  let k = 0
  for (const [code, v] of Object.entries(frame)) {
    if (!matchSet.has(code)) continue
    if (!passFilter(cfg, v)) continue
    out.push({ seriesIndex: 3, dataIndex: k++ })
  }
  return out
}

/** 圆点大小 = 成交额（元 -> 对数归一，1%/99% 分位截断，防少数权重股独大） */
function symbolSizeOf(amt: number, minA: number, maxA: number): number {
  if (!(amt > 0)) return 5
  if (!(maxA > minA)) return 8
  const l = Math.log(amt)
  const lo = Math.log(Math.max(minA, 1e-6))
  const hi = Math.log(Math.max(maxA, lo + 1))
  // 上限收敛到 18 而非 22，缓解全市场四五千只个股在中心区的大点遮挡
  return 6 + 12 * Math.sqrt(Math.max(0, Math.min(1, (l - lo) / (hi - lo))))
}

/** 收集正成交额并取 1%/99% 分位（符号大小归一化的量纲基线） */
function amountQuantiles(amtList: number[]): [number, number] {
  const pos = amtList.filter((a) => a > 0).sort((a, b) => a - b)
  if (!pos.length) return [0, 0]
  const q1 = pos[Math.max(0, Math.floor(pos.length * 0.01))]
  const q99 = pos[Math.min(pos.length - 1, Math.ceil(pos.length * 0.99))]
  return [q1, q99]
}

function fmt(v: number | null | undefined, unit = '', sign = false): string {
  if (v == null || Number.isNaN(v)) return '—'
  const s = sign && v > 0 ? '+' : ''
  const num = Number.isInteger(v) ? String(v) : v.toFixed(2)
  return `${s}${num}${unit}`
}

/**
 * 个股四象限散点图 option 工厂（视觉对齐「概念地图 · 涨跌 × 资金」）。
 *
 * @param meta     code → {name, industry}
 * @param frame    code → 8 元组（[pct, amt, ...]）
 * @param cfg      图表配置（轴索引 / 象限语义）
 * @param matchSet 搜索命中 code 集合 → 宝蓝高亮放大闪烁
 */
export function makeQuadrantOption(
  meta: Record<string, { name: string; industry: string }>,
  frame: Record<string, number[]>,
  cfg: QuadrantCfg,
  matchSet: Set<string>,
): EChartsOption {
  const pts: Point[] = []
  const amtList: number[] = []

  for (const [code, v] of Object.entries(frame)) {
    if (!passFilter(cfg, v)) continue
    const x = v[cfg.xKey]
    const y = v[cfg.yKey]
    amtList.push(v[1] || 0)
    pts.push({
      code,
      name: meta[code]?.name || '',
      industry: meta[code]?.industry || '',
      v,
      x,
      y,
      isMatch: matchSet.has(code),
    })
  }

  const [minA, maxA] = amountQuantiles(amtList)
  const sizeOf = (a: number) => symbolSizeOf(a, minA, maxA)

  const up = pts.filter((p) => !p.isMatch && (p.v[0] || 0) >= 0) // 红：上涨股（不含命中）
  const down = pts.filter((p) => !p.isMatch && (p.v[0] || 0) < 0) // 绿：下跌股（不含命中）
  const matched = pts.filter((p) => p.isMatch) // 命中股独立成系列，置顶层绘制

  const mkData = (arr: Point[]) => arr.map((p) => ({
    name: p.code,
    code: p.code,
    value: [p.x, p.y],
    amt: p.v[1] || 0,
    turn: p.v[2],
    pct: p.v[0],
    board: p.v[6],
    d5: p.v[7],
    industry: p.industry,
    adjusted: false,
    symbolSize: sizeOf(p.v[1] || 0),
  }))

  // 命中股数据：宝蓝高亮 + 放大 + 涨幅标签（置于顶层系列，永不被散点遮挡）
  const mkMatchedData = (arr: Point[]): any[] => arr.map((p) => ({
    name: p.code,
    code: p.code,
    value: [p.x, p.y],
    amt: p.v[1] || 0,
    turn: p.v[2],
    pct: p.v[0],
    board: p.v[6],
    d5: p.v[7],
    industry: p.industry,
    adjusted: true,
    symbolSize: 22,
    itemStyle: HILIGHT_STYLE,
    label: {
      show: true,
      position: 'right' as const,
      distance: 6,
      color: '#1d4ed8',
      fontSize: 13,
      fontWeight: 700 as const,
      formatter: fmt(p.v[0], '%', true),
    },
    emphasis: { scale: 2.6 },
  }))

  const xUnit = cfg.xUnit ?? ''
  const yUnit = cfg.yUnit ?? ''
  const xu = (n: string) => (xUnit ? `${n}（${xUnit}）` : n)
  const yu = (n: string) => (yUnit ? `${n}（${yUnit}）` : n)
  const isZeroAxis = !cfg.logY

  // 四象限角标：高对比白底文字芯片，置于绘图区四角（颜色对齐底部图例条：红/黄/蓝/绿）
  const Q_CORNER: { pos: 'insideTopRight' | 'insideTopLeft' | 'insideBottomRight' | 'insideBottomLeft'; color: string; border: string }[] = [
    { pos: 'insideTopRight', color: '#dc2626', border: '#f87171' },
    { pos: 'insideTopLeft', color: '#b45309', border: '#fbbf24' },
    { pos: 'insideBottomRight', color: '#1d4ed8', border: '#60a5fa' },
    { pos: 'insideBottomLeft', color: '#15803d', border: '#4ade80' },
  ]
  const cornerLabel = (i: number) => ({
    show: true,
    position: Q_CORNER[i].pos,
    distance: 5,
    color: Q_CORNER[i].color,
    fontSize: 12,
    fontWeight: 'bold' as const,
    backgroundColor: 'rgba(255,255,255,.94)',
    borderColor: Q_CORNER[i].border,
    borderWidth: 1,
    borderRadius: 6,
    padding: [3, 8],
    shadowBlur: 5,
    shadowColor: 'rgba(30,41,59,.18)',
    shadowOffsetY: 1,
  })

  // 四象限背景区域（含角标），由顶层透明系列承载 → 角标绘制在全部散点之上
  const quadrantAreas = (): any => ({
    silent: true,
    data: isZeroAxis
      ? // 四象限淡色打底：清晰可辨但不过度抢镜（与散点、角标保持主次）
        [
          [
            { name: cfg.quadrants[0], coord: [0, 0], itemStyle: { color: 'rgba(255,235,238,.5)' }, label: cornerLabel(0) },
            { coord: ['max', 'max'] },
          ],
          [
            { name: cfg.quadrants[1], coord: ['min', 0], itemStyle: { color: 'rgba(255,250,225,.5)' }, label: cornerLabel(1) },
            { coord: [0, 'max'] },
          ],
          [
            { name: cfg.quadrants[2], coord: [0, 'min'], itemStyle: { color: 'rgba(235,245,255,.5)' }, label: cornerLabel(2) },
            { coord: ['max', 0] },
          ],
          [
            { name: cfg.quadrants[3], coord: ['min', 'min'], itemStyle: { color: 'rgba(240,249,240,.5)' }, label: cornerLabel(3) },
            { coord: [0, 0] },
          ],
        ]
      // 对数轴图（PE/市值）：用全绘图区透明区域承载四角角标（itemStyle 显式 opacity:0，
      // 避免 markArea 默认的蓝紫填充 rgba(210,219,238,…) 四层叠加把整个绘图区染紫）
      : [
          [{ name: cfg.quadrants[0], coord: ['min', 'min'], itemStyle: { opacity: 0 }, label: cornerLabel(0) }, { coord: ['max', 'max'] }],
          [{ name: cfg.quadrants[1], coord: ['min', 'min'], itemStyle: { opacity: 0 }, label: cornerLabel(1) }, { coord: ['max', 'max'] }],
          [{ name: cfg.quadrants[2], coord: ['min', 'min'], itemStyle: { opacity: 0 }, label: cornerLabel(2) }, { coord: ['max', 'max'] }],
          [{ name: cfg.quadrants[3], coord: ['min', 'min'], itemStyle: { opacity: 0 }, label: cornerLabel(3) }, { coord: ['max', 'max'] }],
        ],
  })

  return {
    animationDuration: 600,
    grid: { left: 56, right: 28, top: 52, bottom: 52 },
    legend: {
      top: 8,
      left: 10,
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { color: '#4a5568', fontSize: 12 },
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: 'rgba(45, 55, 72, .08)',
      borderWidth: 1,
      textStyle: { color: '#2d3748', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(45,55,72,.12); border-radius: 8px;',
      formatter: (p: any) => {
        const d = p?.data ?? {}
        const px = Number(d.value?.[0])
        const py = Number(d.value?.[1])
        const xCls = px >= 0 ? '#f56c6c' : '#67c23a'
        const yCls = py >= 0 ? '#f56c6c' : '#67c23a'
        const rows: string[] = []
        rows.push(`<b>${d.name || ''}</b> <span style="color:#a0aec0;font-size:11px">${d.industry || ''}</span>`)
        rows.push(`<span style="color:#a0aec0">${cfg.xName}</span> <b style="color:${xCls};font-family:${MONO}">${fmt(px, xUnit, true)}</b>`)
        rows.push(`<span style="color:#a0aec0">${cfg.yName}</span> <b style="color:${yCls};font-family:${MONO}">${fmt(py, yUnit, !cfg.logY)}</b>`)
        rows.push(`<span style="color:#a0aec0">涨跌</span> <b style="font-family:${MONO}">${fmt(d.pct, '%', true)}</b>`)
        rows.push(`<span style="color:#a0aec0">成交额</span> <b style="font-family:${MONO}">${fmt(d.amt, '亿')}</b>`)
        rows.push(`<span style="color:#a0aec0">换手</span> <b style="font-family:${MONO}">${fmt(d.turn, '%')}</b>`)
        if (d.board != null) rows.push(`<span style="color:#a0aec0">连板</span> <b style="font-family:${MONO}">${d.board} 板</b>`)
        if (d.d5 != null) rows.push(`<span style="color:#a0aec0">5日涨跌</span> <b style="font-family:${MONO}">${fmt(d.d5, '%', true)}</b>`)
        return rows.join('<br/>')
      },
    },
    dataZoom: [
      // 滚轮/拖拽缩放平移（x、y 双轴联动）
      { type: 'inside', xAxisIndex: 0, yAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseWheel: true, moveOnMouseMove: true },
      // 底部横向滑动条：放大后左右滑动
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 14,
        bottom: 6,
        showDetail: true,
        borderColor: 'rgba(148,163,184,.35)',
        backgroundColor: 'rgba(148,163,184,.12)',
        fillerColor: 'rgba(37,99,235,.16)',
        handleStyle: { color: '#2563eb', borderColor: '#2563eb' },
        textStyle: { color: '#94a3b8', fontSize: 10 },
      },
      // 右侧纵向滑动条：放大后上下滑动
      {
        type: 'slider',
        yAxisIndex: 0,
        width: 14,
        right: 6,
        showDetail: true,
        borderColor: 'rgba(148,163,184,.35)',
        backgroundColor: 'rgba(148,163,184,.12)',
        fillerColor: 'rgba(37,99,235,.16)',
        handleStyle: { color: '#2563eb', borderColor: '#2563eb' },
        textStyle: { color: '#94a3b8', fontSize: 10 },
      },
    ],
    xAxis: {
      name: xu(cfg.xName),
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      name: yu(cfg.yName),
      nameLocation: 'middle',
      nameGap: 36,
      nameTextStyle: { color: '#a0aec0', fontSize: 11 },
      type: cfg.logY ? 'log' : 'value',
      axisLabel: { color: '#a0aec0', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f0f4f8' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      name: '上涨',
      type: 'scatter',
      // 半透明度降低以求中心密集区红绿重叠时仍可辨底色
      itemStyle: { color: 'rgba(245,108,108,.55)' },
      emphasis: {
        scale: 2.6,
        itemStyle: { borderColor: '#2d3748', borderWidth: 1, shadowBlur: 28, shadowColor: 'rgba(37,99,235,.9)' },
      },
      data: mkData(up),
    }, {
      name: '下跌',
      type: 'scatter',
      itemStyle: { color: 'rgba(103,194,58,.55)' },
      emphasis: {
        scale: 2.6,
        itemStyle: { borderColor: '#2d3748', borderWidth: 1, shadowBlur: 28, shadowColor: 'rgba(37,99,235,.9)' },
      },
      data: mkData(down),
    }, {
      // 顶层标记系列：承载零轴分隔线与四角角标。数据恒为空、与搜索无关，
      // 保证搜索高亮前后该系列选项完全一致，ECharts 合并时角标位置永不重排/跳动
      type: 'scatter',
      z: 5,
      symbolSize: 0,
      data: [],
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: 'rgba(100,116,139,.9)', type: 'dashed', width: 1.4 },
        label: { show: false },
        data: isZeroAxis ? [{ xAxis: 0 }, { yAxis: 0 }] : [{ xAxis: 0 }],
      },
      markArea: {
        silent: true,
        data: quadrantAreas().data,
      },
    }, {
      // 顶层命中系列：仅承载搜索命中高点（z 最高 → 不被任何散点遮挡），不附带任何标记
      type: 'scatter',
      z: 5,
      symbolSize: 0,
      data: mkMatchedData(matched),
    }],
  }
}