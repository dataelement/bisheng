// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils";
import { createDefaultDataConfig, Dashboard, DashboardComponent, LayoutItem, StyleConfig } from "@/pages/Dashboard/types/dataConfig";
import axios from "../request";

// Simulate API delay
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// 默认主题配置
const defaultStyleConfig: StyleConfig = {
    theme: 'light'
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
                { i: "query-filter", x: 0, y: 0, w: 8, h: 3, minW: 6, minH: 3 },

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
                { i: "metric-card", x: 16, y: 30, w: 3, h: 3, minW: 3, minH: 3 },
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
    // has administrative privileges or can view published dashboards
    return await axios.get(`/api/v1/telemetry/dashboard`).then(res =>
        res.data.filter(dashboard => (dashboard.write || dashboard.status === 'published')));
}

export async function getDashboard(id: string, fromShare: boolean = false): Promise<Dashboard> {
    const query = fromShare ? `?from_share=true` : ''
    return await axios.get(`/api/v1/telemetry/dashboard/${id}${query}`);
}

export async function createDashboard(title: string): Promise<Dashboard> {
    return await axios.post(`/api/v1/telemetry/dashboard`, {
        title,
        description: "",
        layout_config: { layouts: [] },
        style_config: { theme: 'light' }
    })
}

export async function updateDashboardTitle(id: string, title: string): Promise<Dashboard> {
    return await axios.post(`/api/v1/telemetry/dashboard/${id}/title`, {
        title
    })
}

export async function setDefaultDashboard(id: string): Promise<Dashboard> {
    return await axios.post(`/api/v1/telemetry/dashboard/${id}/default`, {
        dashboard_id: id
    })
}

export async function copyDashboard({ id, title }: { id: string, title: string }): Promise<Dashboard> {
    return await axios.post(`/api/v1/telemetry/dashboard/${id}/copy`, {
        new_title: title
    })
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
    return await axios.delete(`/api/v1/telemetry/dashboard/${id}`)
}


export async function getShareLink(id: string): Promise<string> {
    await delay(300)
    return `${window.location.origin}/share/${id}`
}

export async function publishDashboard(id: string, status: any): Promise<Dashboard> {
    return await axios.post(`/api/v1/telemetry/dashboard/${id}/status`, {
        status
    })
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

// 获取数据集列表
export async function getDatasets(): Promise<DashboardDataset[]> {
    return await axios.get(`/api/v1/telemetry/dashboard/dataset/list`);
}

// 查询图表数据
import {
    QueryDataResponse
} from '@/pages/Dashboard/types/chartData';

export async function queryChartData(params: {
    componentId: string
    chartType: string
    dataConfig: any
    queryParams?: any
}): Promise<QueryDataResponse> {
    await delay(500)

    // console.log('dataConfig :>> ', params.dataConfig);
    // mock
    // 双指标
    const zhibiaoData = ['销售额', '订单数'] // 使用display名

    const resData = {
        value: [[1, 2, 3, 4, 5], [2, 2, 3, 4, 5], [9, 6, 7, 8, 9]],
        dimensions: [["朝阳店", "2025-10-01", "奶茶"], ["望京店", "2025-10-01", "咖啡"], ["朝阳店", "2025-10-02", "奶茶"]]
    }
    const hasDuidie = false
    let duidieweidu = [] // 表字段去重值
    const nameSet = new Set()
    resData.dimensions = resData.dimensions.map((name) => {
        hasDuidie && nameSet.add(name.pop())
        return name.join('\n')
    })

    if (hasDuidie) {
        duidieweidu = Array.from(nameSet)
    }

    console.log('query params :>> ', params);

    const { chartType } = params

    // 根据图表类型返回对应的 mock 数据
    switch (chartType) {
        case 'bar':
        case 'stacked-bar':
        case 'grouped-bar':
        case 'horizontal-bar':
        case 'stacked-horizontal-bar':
        case 'grouped-horizontal-bar':
        case 'line':
        case 'area':
        case 'stacked-line':
            return {
                dimensions: resData.dimensions,
                series: (hasDuidie ? duidieweidu : zhibiaoData).map((name, index) => ({
                    name: name,
                    data: resData.value.map(el => el[index])
                }))
            }
        case 'pie':
        case 'donut':
            return {
                dimensions: [],
                series: [
                    {
                        name: '',
                        data: resData.dimensions.map((name, index) => ({
                            name: name,
                            value: resData.value[index][0]
                        }))
                    }
                ]
            }
        case 'metric':
            return {
                value: resData.value[0][0],
                title: zhibiaoData[0],
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
            }
    }
}

