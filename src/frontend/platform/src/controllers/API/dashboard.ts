// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils"
import { ComponentConfig, createDefaultDataConfig } from "@/pages/Dashboard/types/dataConfig"

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
    theme: 'light' | 'dark' | 'blue' | 'green' // 当前主题
    themes: {
        light: ThemeConfig
        dark: ThemeConfig
        blue: ThemeConfig
        green: ThemeConfig
    }
}

// 组件样式配置
export interface ComponentStyleConfig {
    backgroundColor?: string
    borderColor?: string
    textColor?: string
    chartColors?: string[] // echarts 配色
}

export interface Dashboard {
    id: string
    title: string
    description: string
    status: 'draft' | 'published',
    dashboard_type: 'custom',
    layout_config: LayoutConfig,
    style_config: StyleConfig,
    created_by: string
    created_at: string
    updated_at: string
    components: DashboardComponent[]
}

export interface DashboardComponent {
    id: string
    dashboard_id: string
    title: string
    type: 'chart' | 'query' | 'metric' // 图表组件、查询组件、指标组件
    dataset_code: string
    data_config: ComponentConfig // 图表/指标组件使用 DataConfig，查询组件使用 QueryConfig
    style_config: ComponentStyleConfig
    created_at: string
    updated_at: string
}

// Simulate API delay
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// 默认主题配置
const defaultStyleConfig: StyleConfig = {
    theme: 'light',
    themes: {
        light: {
            backgroundColor: '#ffffff',
            textColor: '#000000',
            borderColor: '#e5e7eb',
            chartColors: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']
        },
        dark: {
            backgroundColor: '#1f2937',
            textColor: '#f9fafb',
            borderColor: '#374151',
            chartColors: ['#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#f472b6']
        },
        blue: {
            backgroundColor: '#dbeafe',
            textColor: '#1e3a8a',
            borderColor: '#93c5fd',
            chartColors: ['#2563eb', '#0ea5e9', '#06b6d4', '#14b8a6', '#10b981', '#84cc16']
        },
        green: {
            backgroundColor: '#dcfce7',
            textColor: '#14532d',
            borderColor: '#86efac',
            chartColors: ['#10b981', '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1']
        }
    }
}

// Mock data
let mockDashboards: Dashboard[] = [
    {
        id: "1",
        title: "看板 1",
        description: "這是一個測試用的看板",
        status: 'draft',
        dashboard_type: 'custom',
        layout_config: {
            layouts: [
                { i: "chart-1", x: 0, y: 0, w: 3, h: 4, minW: 2, minH: 2 },
                { i: "chart-2", x: 5, y: 0, w: 3, h: 4, minW: 2, minH: 2 },
                { i: "metric-1", x: 0, y: 4, w: 3, h: 2, minW: 2, minH: 2 },
                { i: "metric-2", x: 3, y: 4, w: 3, h: 2, minW: 2, minH: 2 },
                { i: "chart-3", x: 6, y: 4, w: 6, h: 4, minW: 2, minH: 2 },
            ]
        },
        style_config: defaultStyleConfig,
        created_by: "admin",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        components: [
            {
                id: "chart-1",
                dashboard_id: "1",
                title: "销售趋势",
                type: 'chart',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('line'),
                style_config: {},
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
            {
                id: "chart-2",
                dashboard_id: "1",
                title: "产品分布",
                type: 'chart',
                dataset_code: "product_data",
                data_config: createDefaultDataConfig('bar'),
                style_config: {},
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
            {
                id: "metric-1",
                dashboard_id: "1",
                title: "总销售额",
                type: 'metric',
                dataset_code: "sales_metric",
                data_config: createDefaultDataConfig('metric'),
                style_config: {},
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
            {
                id: "metric-2",
                dashboard_id: "1",
                title: "活跃用户",
                type: 'metric',
                dataset_code: "user_metric",
                data_config: createDefaultDataConfig('metric'),
                style_config: {},
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
            {
                id: "chart-3",
                dashboard_id: "1",
                title: "地区分布",
                type: 'chart',
                dataset_code: "region_data",
                data_config: createDefaultDataConfig('pie'),
                style_config: {},
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
        ]
    },
    {
        id: "2",
        title: "看板 2",
        description: "這是一個測試用的看板",
        status: 'published',
        dashboard_type: 'custom',
        layout_config: { layouts: [] },
        style_config: defaultStyleConfig,
        created_by: "admin",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        components: []
    },
]

export async function getDashboards(): Promise<Dashboard[]> {
    await delay(500)
    return mockDashboards
}

export async function createDashboard(data: Partial<Dashboard>): Promise<Dashboard> {
    await delay(300)
    const newDashboard: Dashboard = {
        id: Date.now().toString(),
        title: data.title || "新看板",
        description: "",
        status: 'draft',
        dashboard_type: 'custom',
        layout_config: { layouts: [] },
        style_config: defaultStyleConfig,
        created_by: "admin",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        components: []
    }
    mockDashboards.push(newDashboard)
    return newDashboard
}

export async function updateDashboard(id: string, data: Partial<Dashboard>): Promise<Dashboard> {
    await delay(300)
    const index = mockDashboards.findIndex((d) => d.id === id)
    if (index === -1) throw new Error("Dashboard not found")

    mockDashboards[index] = {
        ...mockDashboards[index],
        ...data,
        updated_at: new Date().toISOString(),
    }
    return mockDashboards[index]
}

export async function deleteDashboard(id: string): Promise<void> {
    await delay(300)
    mockDashboards = mockDashboards.filter((d) => d.id !== id)
}

export async function duplicateDashboard(id: string): Promise<Dashboard> {
    await delay(300)
    const dashboard = mockDashboards.find((d) => d.id === id)
    if (!dashboard) throw new Error("Dashboard not found")

    const newDashboard: Dashboard = {
        ...dashboard,
        id: Date.now().toString(),
        title: `${dashboard.title} (副本)`,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
    }
    mockDashboards.push(newDashboard)
    return newDashboard
}

export async function getShareLink(id: string): Promise<string> {
    await delay(300)
    return `${window.location.origin}/share/${id}`
}

export async function publishDashboard(id: string, status: any): Promise<Dashboard> {
    await delay(300)
    return updateDashboard(id, { status })
}

export async function getDashboardDetail(id: string): Promise<Dashboard> {
    await delay(500)
    const dashboard = mockDashboards.find((d) => d.id === id)
    if (!dashboard) throw new Error("Dashboard not found")
    return dashboard
}

export async function copyComponentTo(dashboard: Dashboard, component: DashboardComponent, layoutItem: LayoutItem): Promise<{ component: DashboardComponent, layoutItem: LayoutItem }> {
    const newComponentId = `${component.type}-${generateUUID(8)}`
    const newComponent: DashboardComponent = {
        ...component,
        id: newComponentId,
        dashboard_id: dashboard.id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
    }
    // Calculate position at bottom left of target dashboard
    const maxY = dashboard.layout_config.layouts.length > 0
        ? Math.max(...dashboard.layout_config.layouts.map(l => l.y + l.h))
        : 0
    const newLayoutItem: LayoutItem = {
        ...layoutItem,
        i: newComponentId,
        x: 0,
        y: maxY
    }

    dashboard.components.push(newComponent)
    dashboard.layout_config.layouts.push(newLayoutItem)
    // todo  save api
    await delay(300)
    return { component: newComponent, layoutItem: newLayoutItem }
}

// Dataset related types and APIs

// 时间粒度
export interface TimeGranularity {
    name: string
    aggregation: Record<string, any>
}

// 维度配置
export interface DimensionConfig {
    name: string
    type: 'integer' | 'keyword' | 'date'
    field: string
    time_granularity?: TimeGranularity[]
    aggregation?: Record<string, any>
    aggregation_name: string
    bucket_path: string
}

// 指标配置
export interface MetricConfig {
    name: string
    filter?: Record<string, any>
    aggregation: Record<string, any>
    aggregation_name: string
    bucket_path?: string
}

// Schema 配置
export interface SchemaConfig {
    metrics: MetricConfig[]
    dimensions: DimensionConfig[]
}

// 数据集
export interface DashboardDataset {
    id: number
    dataset_name: string
    dataset_code: string
    es_index_name: string
    description: string
    is_commercial_only: boolean
    schema_config: SchemaConfig
}

// Mock datasets
const mockDatasets: DashboardDataset[] = [
    {
        id: 1,
        dataset_name: "条区原料费用",
        dataset_code: "raw_material_cost",
        es_index_name: "raw_material_cost_index",
        description: "原料费用数据集",
        is_commercial_only: false,
        schema_config: {
            dimensions: [
                {
                    name: "店铺",
                    type: "keyword",
                    field: "shop",
                    aggregation_name: "shop_agg",
                    bucket_path: "shop_agg"
                },
                {
                    name: "日期",
                    type: "date",
                    field: "date",
                    time_granularity: [
                        { name: "天", aggregation: { date_histogram: { field: "date", calendar_interval: "day" } } },
                        { name: "月", aggregation: { date_histogram: { field: "date", calendar_interval: "month" } } },
                        { name: "年", aggregation: { date_histogram: { field: "date", calendar_interval: "year" } } }
                    ],
                    aggregation_name: "date_agg",
                    bucket_path: "date_agg"
                },
                {
                    name: "用途",
                    type: "keyword",
                    field: "purpose",
                    aggregation_name: "purpose_agg",
                    bucket_path: "purpose_agg"
                }
            ],
            metrics: [
                {
                    name: "金额",
                    aggregation: { sum: { field: "amount" } },
                    aggregation_name: "amount_sum",
                    bucket_path: "amount_sum"
                },
                {
                    name: "记录数",
                    aggregation: { value_count: { field: "_id" } },
                    aggregation_name: "record_count",
                    bucket_path: "record_count"
                }
            ]
        }
    },
    {
        id: 2,
        dataset_name: "销售数据",
        dataset_code: "sales_data",
        es_index_name: "sales_data_index",
        description: "销售数据集",
        is_commercial_only: false,
        schema_config: {
            dimensions: [
                {
                    name: "区域",
                    type: "keyword",
                    field: "region",
                    aggregation_name: "region_agg",
                    bucket_path: "region_agg"
                },
                {
                    name: "产品类别",
                    type: "keyword",
                    field: "category",
                    aggregation_name: "category_agg",
                    bucket_path: "category_agg"
                }
            ],
            metrics: [
                {
                    name: "销售额",
                    aggregation: { sum: { field: "sales_amount" } },
                    aggregation_name: "sales_sum",
                    bucket_path: "sales_sum"
                },
                {
                    name: "订单数",
                    aggregation: { value_count: { field: "_id" } },
                    aggregation_name: "order_count",
                    bucket_path: "order_count"
                }
            ]
        }
    }
]

// 获取数据集列表（支持搜索和分页）
export async function getDatasets(params?: {
    search?: string
    limit?: number
    offset?: number
}): Promise<DashboardDataset[]> {
    await delay(300)

    let filteredDatasets = [...mockDatasets]

    // 搜索过滤
    if (params?.search) {
        const searchLower = params.search.toLowerCase()
        filteredDatasets = filteredDatasets.filter(d =>
            d.dataset_name.toLowerCase().includes(searchLower) ||
            d.dataset_code.toLowerCase().includes(searchLower) ||
            d.description.toLowerCase().includes(searchLower)
        )
    }

    // 分页
    const offset = params?.offset || 0
    const limit = params?.limit || 11
    filteredDatasets = filteredDatasets.slice(offset, offset + limit)

    return filteredDatasets
}

