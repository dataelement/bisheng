import { generateUUID } from "@/components/bs-ui/utils"

// React-Grid-Layout 布局项
export interface LayoutItem {
  i: string // 组件ID
  x: number // 横向位置 (0-11)
  y: number // 纵向位置
  w: number // 宽度 (1-12)
  h: number // 高度
  minW?: number // 最小宽度
  minH?: number // 最小高度
  maxW?: number // 最大宽度
  maxH?: number // 最大高度
  static?: boolean // 是否静态（不可拖拽）
}

// 看板布局配置
export interface LayoutConfig {
  layouts: LayoutItem[] // 布局数组
}

// 主题配置
export interface ThemeConfig {
  backgroundColor: string
  textColor: string
  borderColor: string
  chartColors: string[] // echarts 配色
}

// 看板样式配置
export interface StyleConfig {
  theme: 'light' | 'dark'// 当前主题
}

// 组件样式配置
export interface ComponentStyleConfig {
  themeColor: string        // 主体颜色
  bgColor: string           // 背景颜色
  
  // 图表主标题
  title?: string           // 标题内容
  titleFontSize: number     // 主标题字体大小
  titleBold: boolean        // 主标题加粗
  titleItalic: boolean      // 主标题斜体
  titleUnderline: boolean   // 主标题下划线
  titleAlign: "left" | "center" | "right" // 主标题对齐方式
  
  // X轴标题 - 新增
  xAxisTitle?: string         // X轴标题文字
  xAxisFontSize?: number      // X轴标题字体大小
  xAxisBold?: boolean         // X轴标题加粗
  xAxisItalic?: boolean       // X轴标题斜体
  xAxisUnderline?: boolean    // X轴标题下划线
  xAxisAlign?: "left" | "center" | "right" // X轴标题对齐方式
  
  // Y轴标题 - 新增
  yAxisTitle?: string         // Y轴标题文字
  yAxisFontSize?: number      // Y轴标题字体大小
  yAxisBold?: boolean         // Y轴标题加粗
  yAxisItalic?: boolean       // Y轴标题斜体
  yAxisUnderline?: boolean    // Y轴标题下划线
  yAxisAlign?: "left" | "center" | "right" // Y轴标题对齐方式
  
  // 图例
  legendPosition: "top" | "bottom" | "left" | "right" // 图例位置
  legendFontSize: number    // 图例字体大小
  legendBold: boolean       // 图例加粗
  legendItalic: boolean     // 图例斜体
  legendUnderline: boolean  // 图例下划线
  legendAlign: "left" | "center" | "right" // 图例对齐
  
  // 图表选项
  showLegend: boolean       // 是否显示图例
  showAxis: boolean         // 是否显示坐标轴
  showDataLabel: boolean    // 是否显示数据标签
  showGrid: boolean         // 是否显示网格线
  
   // 指标卡特有字段
  metricFontSize?: number
  metricBold?: boolean
  metricItalic?: boolean
  metricUnderline?: boolean
  metricAlign?: "left" | "center" | "right"
  
  showSubtitle?: boolean
  subtitle?: string
  subtitleFontSize?: number
  subtitleBold?: boolean
  subtitleItalic?: boolean
  subtitleUnderline?: boolean
  subtitleAlign?: "left" | "center" | "right"
}
export interface Dashboard {
  id: string
  title: string
  description: string
  status: 'draft' | 'published',
  dashboard_type: 'custom',
  layout_config: LayoutConfig,
  style_config: StyleConfig,
  create_time: string
  update_time: string
  is_default: boolean
  user_name: string
  write: boolean
  components: DashboardComponent[]
}

export interface DashboardComponent {
  id: string //
  dashboard_id: string
  title: string
  type: ChartType
  dataset_code: string
  data_config: ComponentConfig // 图表/指标组件使用 DataConfig，查询组件使用 QueryConfig
  style_config: ComponentStyleConfig
  create_time: string
  update_time: string
}

/**
 * Dashboard 组件数据配置类型定义
 */
// 图表类型
export enum ChartType {
  /** 基础柱状图 */
  Bar = 'bar',
  /** 堆叠柱状图 */
  StackedBar = 'stacked-bar',
  /** 分组柱状图 */
  GroupedBar = 'grouped-bar',
  /** 基础条形图 */
  HorizontalBar = 'horizontal-bar',
  /** 堆叠条形图 */
  StackedHorizontalBar = 'stacked-horizontal-bar',
  /** 分组条形图 */
  GroupedHorizontalBar = 'grouped-horizontal-bar',
  /** 基础折线图 */
  Line = 'line',
  /** 面积图 */
  Area = 'area',
  /** 堆叠面积图 */
  StackedArea = 'stacked-area',
  /** 堆叠折线图 */
  StackedLine = 'stacked-line',
  /** 饼状图 */
  Pie = 'pie',
  /** 环状图 */
  Donut = 'donut',
  /** 指标卡 */
  Metric = 'metric',
  /** 查询组件 */
  Query = 'query'
}

// 维度配置
export interface DimensionField {
  fieldId: string               // 字段ID（来自数据集）
  fieldName: string             // 字段名称
  fieldCode: string             // 字段编码
  displayName?: string          // 展示名称（不填则使用 fieldName）
  sort: null | 'asc' | 'desc' // 排序方式
  timeGranularity: string | null // 时间子维度（仅时间字段有效）
}

//  指标配置 
export interface MetricField {
  fieldId: string               // 字段ID（来自数据集）
  fieldName: string             // 字段名称
  fieldCode: string             // 字段编码
  displayName?: string          // 展示名称
  aggregation?: string // 汇总方式（虚拟指标无此属性）
  isVirtual: boolean            // 是否为虚拟指标
  sort: null | 'asc' | 'desc' // 排序方式
  numberFormat: {               // 数值格式
    type: 'number' | 'percent' | 'duration' | 'storage'    // 数值 百分比 时长 存储大小      
    decimalPlaces: number         // 小数位数
    unit?: string                 // 数量单位（如 K、M、B）
    suffix?: string               // 单位后缀（如 元、个、次）
    thousandSeparator: boolean    // 是否显示千分位符
  }
}

export interface FilterCondition {
  id: string                           // 筛选条件唯一ID
  fieldId: string                      // 字段ID
  fieldName: string                    // 字段名称
  filterType: string                   // 筛选类型
  operator?: string                    // 操作符
  value?: string | number | string[]   // 值
}

// 时间筛选 
export const enum TimeRangeType {
  ALL = 'all', // 全部时间
  RECENT_DAYS = 'recent_days', // 最近n天
  CUSTOM = 'custom' // 自定义时间范围
}

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
  },
  isConfigured: boolean // 配置完成
}

// 查询组件配置
export interface QueryConfig {
  linkedComponentIds: string[]    // 关联的图表组件ID列表（查询时会更新这些组件）
  queryConditions: {
    id: string                      // 条件唯一ID
    displayType: 'range' | 'single'        // 展示类型：时间范围 或 单个时间
    timeGranularity: 'year_month' | 'year_month_day' | 'year_month_day_hour'// 时间粒度
    hasDefaultValue: boolean        // 是否设置默认值
    defaultValue?: TimeFilter // 默认值配置
  }// 查询条件列表
}

// 组件配置联合类型
export type ComponentConfig = DataConfig | QueryConfig
export const createDefaultDataConfig = (type: ChartType): ComponentConfig => (
  type === 'query'
    ? {
      linkedComponentIds: [], queryConditions: {
        id: generateUUID(4),
        displayType: 'range',
        timeGranularity: 'year_month_day',
        hasDefaultValue: false,
        defaultValue: {
          type: TimeRangeType.ALL
        }
      }
    }
    : {
      dimensions: [],
      metrics: [],
      fieldOrder: [],
      filters: [],
      resultLimit: { limitType: 'all' },
      isConfigured: false
    })