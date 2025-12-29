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



// ==================== 示例数据 ====================
/**
 * 创建柱状图示例数据
 */
export const createBarChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '销售额',
      data: [320, 432, 301, 434, 390, 530]
    }
  ]
})

/**
 * 创建堆叠柱状图示例数据
 */
export const createStackedBarChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '线上销售',
      data: [120, 132, 101, 134, 90, 230]
    },
    {
      name: '线下销售',
      data: [220, 182, 191, 234, 290, 330]
    }
  ]
})

/**
 * 创建分组柱状图示例数据
 */
export const createGroupedBarChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '产品A',
      data: [120, 132, 101, 134, 90, 230]
    },
    {
      name: '产品B',
      data: [220, 182, 191, 234, 290, 330]
    },
    {
      name: '产品C',
      data: [150, 232, 201, 154, 190, 330]
    }
  ]
})

/**
 * 创建折线图示例数据
 */
export const createLineChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '访问量',
      data: [820, 932, 901, 934, 1290, 1330]
    }
  ]
})

/**
 * 创建面积图示例数据
 */
export const createAreaChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '销售额',
      data: [820, 932, 901, 934, 1290, 1330]
    }
  ]
})

/**
 * 创建堆叠折线图示例数据
 */
export const createStackedLineChartMockData = (): ChartDataResponse => ({
  dimensions: ['1月', '2月', '3月', '4月', '5月', '6月'],
  series: [
    {
      name: '邮件营销',
      data: [120, 132, 101, 134, 90, 230]
    },
    {
      name: '联盟广告',
      data: [220, 182, 191, 234, 290, 330]
    },
    {
      name: '视频广告',
      data: [150, 232, 201, 154, 190, 330]
    }
  ]
})

/**
 * 创建饼图示例数据
 */
export const createPieChartMockData = (): ChartDataResponse => ({
  dimensions: [],
  series: [
    {
      name: '销售占比',
      data: [
        { name: '直接访问', value: 335 },
        { name: '邮件营销', value: 310 },
        { name: '联盟广告', value: 234 },
        { name: '视频广告', value: 135 },
        { name: '搜索引擎', value: 548 }
      ]
    }
  ]
})

/**
 * 创建环形图示例数据
 */
export const createDonutChartMockData = (): ChartDataResponse => ({
  dimensions: [],
  series: [
    {
      name: '访问来源',
      data: [
        { name: '直接访问', value: 335 },
        { name: '邮件营销', value: 310 },
        { name: '联盟广告', value: 234 },
        { name: '视频广告', value: 135 },
        { name: '搜索引擎', value: 548 }
      ]
    }
  ]
})

/**
 * 创建指标卡示例数据
 */
export const createMetricMockData = (): MetricDataResponse => ({
  value: 123456,
  title: '总销售额',
  unit: '元',
  trend: {
    value: 12.5,
    direction: 'up',
    label: '较上月'
  },
  format: {
    decimalPlaces: 2,
    thousandSeparator: true
  }
})

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
