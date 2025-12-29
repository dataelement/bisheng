// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils"
import { createDefaultDataConfig, Dashboard, DashboardComponent, LayoutItem, StyleConfig } from "@/pages/Dashboard/types/dataConfig"

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
        title: "图表展示看板",
        description: "展示所有图表类型",
        status: 'draft',
        dashboard_type: 'custom',
        layout_config: {
            layouts: [
                // 第一行：查询组件
                { i: "query-filter", x: 0, y: 0, w: 6, h: 6, minW: 4, minH: 4 },

                // 第二行：柱状图
                { i: "bar-basic", x: 0, y: 6, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "bar-stacked", x: 8, y: 6, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "bar-grouped", x: 16, y: 6, w: 8, h: 8, minW: 4, minH: 4 },

                // 第三行：条形图
                { i: "horizontal-bar-basic", x: 0, y: 14, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "horizontal-bar-stacked", x: 8, y: 14, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "horizontal-bar-grouped", x: 16, y: 14, w: 8, h: 8, minW: 4, minH: 4 },

                // 第四行：折线图
                { i: "line-basic", x: 0, y: 22, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "area-chart", x: 8, y: 22, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "line-stacked", x: 16, y: 22, w: 8, h: 8, minW: 4, minH: 4 },

                // 第五行：饼图、环形图、指标卡
                { i: "pie-chart", x: 0, y: 30, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "donut-chart", x: 8, y: 30, w: 8, h: 8, minW: 4, minH: 4 },
                { i: "metric-card", x: 16, y: 30, w: 6, h: 6, minW: 4, minH: 4 },
            ]
        },
        style_config: defaultStyleConfig,
        created_by: "admin",
        created_at: Date.now(),
        updated_at: Date.now(),
        components: [
            // 查询组件
            {
                id: "query-filter",
                dashboard_id: "1",
                title: "时间查询",
                type: 'query',
                dataset_code: "",
                data_config: {},
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },

            // 柱状图系列
            {
                id: "bar-basic",
                dashboard_id: "1",
                title: "基础柱状图",
                type: 'bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "bar-stacked",
                dashboard_id: "1",
                title: "堆叠柱状图",
                type: 'stacked-bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('stacked-bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "bar-grouped",
                dashboard_id: "1",
                title: "分组柱状图",
                type: 'grouped-bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('grouped-bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },

            // 条形图系列
            {
                id: "horizontal-bar-basic",
                dashboard_id: "1",
                title: "基础条形图",
                type: 'horizontal-bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('horizontal-bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "horizontal-bar-stacked",
                dashboard_id: "1",
                title: "堆叠条形图",
                type: 'stacked-horizontal-bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('stacked-horizontal-bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "horizontal-bar-grouped",
                dashboard_id: "1",
                title: "分组条形图",
                type: 'grouped-horizontal-bar',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('grouped-horizontal-bar'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },

            // 折线图系列
            {
                id: "line-basic",
                dashboard_id: "1",
                title: "基础折线图",
                type: 'line',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('line'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "area-chart",
                dashboard_id: "1",
                title: "面积图",
                type: 'area',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('area'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "line-stacked",
                dashboard_id: "1",
                title: "堆叠折线图",
                type: 'stacked-line',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('stacked-line'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },

            // 饼图和环形图
            {
                id: "pie-chart",
                dashboard_id: "1",
                title: "饼图",
                type: 'pie',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('pie'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },
            {
                id: "donut-chart",
                dashboard_id: "1",
                title: "环形图",
                type: 'donut',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('donut'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
            },

            // 指标卡
            {
                id: "metric-card",
                dashboard_id: "1",
                title: "总销售额",
                type: 'metric',
                dataset_code: "sales_data",
                data_config: createDefaultDataConfig('metric'),
                style_config: {},
                created_at: Date.now(),
                updated_at: Date.now(),
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
        created_at: Date.now(),
        updated_at: Date.now(),
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
        created_at: Date.now(),
        updated_at: Date.now(),
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
        updated_at: Date.now(),
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
        created_at: Date.now(),
        updated_at: Date.now()
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
        created_at: Date.now(),
        updated_at: Date.now()
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

// 查询图表数据
import {
    QueryDataResponse,
    ChartDataResponse,
    MetricDataResponse,
    createBarChartMockData,
    createStackedBarChartMockData,
    createGroupedBarChartMockData,
    createLineChartMockData,
    createAreaChartMockData,
    createStackedLineChartMockData,
    createPieChartMockData,
    createDonutChartMockData,
    createMetricMockData
} from '@/pages/Dashboard/types/chartData'

export async function queryChartData(params: {
    componentId: string
    chartType: string
    dataConfig: any
    queryParams?: any
}): Promise<QueryDataResponse> {
    await delay(500)

    const { chartType } = params

    // 根据图表类型返回对应的 mock 数据
    switch (chartType) {
        case 'bar':
            return createBarChartMockData()
        case 'stacked-bar':
            return createStackedBarChartMockData()
        case 'grouped-bar':
            return createGroupedBarChartMockData()
        case 'horizontal-bar':
            return createBarChartMockData() // 条形图使用相同数据，只是方向不同
        case 'stacked-horizontal-bar':
            return createStackedBarChartMockData()
        case 'grouped-horizontal-bar':
            return createGroupedBarChartMockData()
        case 'line':
            return createLineChartMockData()
        case 'area':
            return createAreaChartMockData()
        case 'stacked-line':
            return createStackedLineChartMockData()
        case 'pie':
            return createPieChartMockData()
        case 'donut':
            return createDonutChartMockData()
        case 'metric':
            return createMetricMockData()
        default:
            return createBarChartMockData()
    }
}

