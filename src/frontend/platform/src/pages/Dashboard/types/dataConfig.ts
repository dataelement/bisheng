/**
 * Dashboard 组件数据配置类型定义
 */

// 图表类型
export type ChartType =
  | 'bar'                      // 基础柱状图
  | 'stacked-bar'              // 堆叠柱状图
  | 'grouped-bar'              // 分组柱状图
  | 'horizontal-bar'           // 基础条形图
  | 'stacked-horizontal-bar'   // 堆叠条形图
  | 'grouped-horizontal-bar'   // 分组条形图
  | 'line'                     // 基础折线图
  | 'area'                     // 面积图
  | 'stacked-line'             // 堆叠折线图
  | 'pie'                      // 饼状图
  | 'donut'                    // 环状图
  | 'metric'                   // 指标卡


// 维度配置
export interface DimensionField {
  fieldId: string               // 字段ID（来自数据集）
  fieldName: string             // 字段名称
  fieldCode: string             // 字段编码
  displayName?: string          // 展示名称（不填则使用 fieldName）
  sort: 'none' | 'asc' | 'desc' // 排序方式
}

//  指标配置 
export interface MetricField {
  fieldId: string               // 字段ID（来自数据集）
  fieldName: string             // 字段名称
  fieldCode: string             // 字段编码
  displayName?: string          // 展示名称
  aggregation?: string // 汇总方式（虚拟指标无此属性）
  isVirtual: boolean            // 是否为虚拟指标
  sort: 'none' | 'asc' | 'desc' // 排序方式
  numberFormat: {               // 数值格式
    type: 'number' | 'percent' | 'duration' | 'storage'    // 数值 百分比 时长 存储大小      
    decimalPlaces: number         // 小数位数
    unit?: string                 // 数量单位（如 K、M、B）
    suffix?: string               // 单位后缀（如 元、个、次）
    thousandSeparator: boolean    // 是否显示千分位符
  }
}


export interface FilterCondition {
  id: string                    // 筛选条件唯一ID
  fieldId: string               // 字段ID
  fieldName: string             // 字段名称
  filterType: string            // 筛选类型
  // 文本筛选
  textOperator?: string         // 文本操作符
  textValue?: string            // 文本值
  // 枚举筛选
  enumValues?: string[]         // 多选值数组
  // 数字筛选
  numberOperator?: string       // 数字操作符
  numberValue?: number          // 数字值
}

// 时间筛选 
export type TimeRangeType =
  | 'all'          // 全部时间
  | 'recent_days'  // 最近n天
  | 'custom'       // 自定义时间范围

export type TimeRangeMode =
  | 'fixed'    // 固定时间范围
  | 'dynamic'  // 动态时间范围（相对当前时间）

export interface TimeFilter {
  type: TimeRangeType           // 时间范围类型
  mode?: TimeRangeMode          // 时间范围模式（type 为 recent_days 时有效）
  recentDays?: number           // 最近n天（如 7, 30, 70, 90）
  startDate?: number            // 自定义开始日期
  endDate?: number              // 自定义结束日期
}

// 数据配置（图表组件和指标组件使用）
export interface DataConfig {
  chartType: ChartType          // 图表类型
  dimensions: DimensionField[]  // 维度字段列表（对应 echarts xAxis）
  stackDimension?: DimensionField // 堆叠维度字段（某些图表类型才有，如堆叠柱状图）
  metrics: MetricField[]        // 指标字段列表（对应 echarts yAxis）
  fieldOrder: {
    fieldId: string               // 字段ID
    fieldType: 'dimension' | 'stack_dimension' | 'metric'   // 字段类型 维度字段|堆叠维度字段|指标字段
  }[]   // 所有字段的排序顺序（数组顺序即为排序）
  filters: FilterCondition[]      // 条件筛选列表
  timeFilter?: TimeFilter         // 时间筛选（可选）
  resultLimit: {                  // 结果展示配置
    limitType: 'all' | 'limited'  // 限制类型
    limit?: number                // 具体条数（limitType 为 limited 时有效）
  }
}

// 查询组件配置 
export interface QueryConfig {
  linkedComponentIds: string[]    // 关联的图表组件ID列表（查询时会更新这些组件）
  queryConditions: {
    id: string                      // 条件唯一ID
    fieldId: string                 // 字段ID
    fieldName: string               // 字段名称
    displayType: 'time_range' | 'single_time'        // 展示类型：时间范围 或 单个时间
    timeGranularity: 'year_month' | 'year_month_day' | 'year_month_day_hour'// 时间粒度
    hasDefaultValue: boolean        // 是否设置默认值
    defaultValue?: TimeFilter // 默认值配置
  }[] // 查询条件列表
}

// 组件配置联合类型
export type ComponentConfig = DataConfig | QueryConfig




export const createDefaultDataConfig = (chartType: ChartType = 'bar'): DataConfig => ({
  chartType,
  dimensions: [],
  metrics: [],
  fieldOrder: [],
  filters: [],
  resultDisplay: { limitType: 'all' }
})
