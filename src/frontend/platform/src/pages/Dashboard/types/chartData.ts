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
export type QueryDataResponse = ChartDataResponse | MetricDataResponse



/**
 * 创建指标卡示例数据（无趋势）
 */
export const createSimpleMetricMockData = (): MetricDataResponse => ({
  value: 8523,
  title: '活跃用户',
  format: {
    decimalPlaces: 0,
    thousandSeparator: true
  }
})
