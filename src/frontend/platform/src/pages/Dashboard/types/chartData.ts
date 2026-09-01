/**
 * 图表数据类型定义
 */

// ==================== 图表数据（柱状图、折线图、饼图等）====================
export interface ChartDataResponse {
  // 维度数据（X轴数据，用于柱状图、折线图等）
  dimensions: string[] // 如：['2024-01', '2024-02', '2024-03'] 或 ['北京', '上海', '广州']

  // 系列数据（纯数据，不包含配置）
  series: ChartSeries[]
}

export interface ChartSeries {
  name: string // 系列名称，如 '销售额'、'订单数'
  data: number[] | PieDataItem[] // 数据数组，饼图使用 PieDataItem
}

export interface PivotTableRow {
  key: string[]
  values: number[]
  total: number
}

export interface PivotTableDataResponse {
  rowHeaders: string[]
  columnHeader: string
  columnHeaders?: string[]
  metricName: string
  columns: string[]
  originalColumns?: string[]
  columnPaths?: string[][]
  originalColumnPaths?: string[][]
  rows: PivotTableRow[]
  columnTotals: number[]
  grandTotal: number
  truncated?: boolean
  // F058 AC-12/AC-13: row-dimension index to group by (rowSpan-merge in the UI), or
  // null when no org-hierarchy row dimension has an active filter value (flat rendering).
  groupDimensionIndex?: number | null
  // F058 AC-09: raw field ids parallel to rowHeaders/row.key, needed to call the
  // drill-down export API (which takes a field id, not the localized display label).
  // Note: after AC-11's person/department merge, this array is shorter than the
  // pre-merge dimension count — it stays index-aligned with the (merged) row.key/rowHeaders.
  rowFieldIds?: string[]
  // F058 AC-09/AC-11: row-key index whose displayed value is an AC-11 merged
  // "name(dept)" string, not a raw filterable value — click-to-export must skip this
  // column (there's no single raw value left to filter on after the merge).
  personDedupIndex?: number | null
}

// 饼图数据项
export interface PieDataItem {
  name: string // 名称
  value: number // 数值
}

// ==================== 指标卡数据 ====================
export interface MetricDataResponse {
  value: number // 主要指标值
  title: string // 指标标题
  unit?: string // 单位

  // 趋势数据（可选）
  trend?: {
    value: number // 对比值（如环比增长 5%）
    direction: 'up' | 'down' | 'flat' // 趋势方向：上升/下降/持平
    label: string // 趋势标签，如 '较上月'、'同比'
  }

  // 格式化配置（可选）
  format?: {
    decimalPlaces?: number // 小数位数
    thousandSeparator?: boolean // 是否显示千分位
  }
}

// ==================== 查询请求参数 ====================
export interface QueryChartRequest {
  componentId: string // 组件ID
  dataConfig: any // 组件的 data_config
  queryParams?: QueryParams // 查询组件传递的参数（可选）
}

// 查询参数（来自查询组件）
export interface QueryParams {
  timeFilter?: {
    startDate?: string
    endDate?: string
    granularity?: string
  }
  filters?: Record<string, any>
}

// ==================== 统一的查询响应 ====================
export type QueryDataResponse = ChartDataResponse | MetricDataResponse | PivotTableDataResponse
