// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils";
import { ChartType, createDefaultDataConfig, Dashboard, DashboardComponent, LayoutItem, StyleConfig } from "@/pages/Dashboard/types/dataConfig";
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

export async function updateDashboard2(id: string, data: Partial<Dashboard>): Promise<Dashboard> {
    const payload = cloneDeep(data);
    // delete time
    delete payload.create_time;
    delete payload.update_time;
    payload.components.forEach(component => {
        delete component.create_time;
        delete component.update_time;
    })
    return await axios.put(`/api/v1/telemetry/dashboard/${id}`, payload)
}

export async function updateDashboard(id: string, data: Partial<Dashboard>): Promise<Dashboard> {
    // return await axios.put(`/api/v1/telemetry/dashboard/${id}`, {
    //     "title": "22224333",
    //     "description": "test2-2",
    //     "layout_config": {},
    //     "style_config": {},
    //     "id": 1,
    //     "components": []
    // })
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

export async function copyComponentTo(component: DashboardComponent, targetId: string, layout: LayoutItem): Promise<any> {
    const targetDashboard = await getDashboard(targetId)
    console.log('targetDashboard :>> ', targetDashboard, layout);
    const copyComponentId = generateUUID(6)
    targetDashboard.components.push({
        ...component,
        id: copyComponentId
    })

    // // Calculate position at bottom left of target dashboard
    const maxY = targetDashboard.layout_config.layouts.length > 0
        ? Math.max(...targetDashboard.layout_config.layouts.map(l => l.y + l.h))
        : 0
    const newLayoutItem: LayoutItem = {
        ...layout,
        i: copyComponentId,
        x: 0,
        y: maxY
    }

    targetDashboard.layout_config.layouts.push(newLayoutItem)
    return await updateDashboard2(targetId, targetDashboard)
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

// 获取数据集列表
export async function getDatasets(): Promise<DashboardDataset[]> {
    return await axios.get(`/api/v1/telemetry/dashboard/dataset/list`);
}

// 查询图表数据
import {
    QueryDataResponse
} from '@/pages/Dashboard/types/chartData';
import { cloneDeep } from "lodash-es";

export async function queryChartData(params: {
    chartType: ChartType
    dashboardId: string
    componentId?: string
    componentData?: DashboardComponent
    queryParams?: any
}): Promise<QueryDataResponse> {
    const resData = await axios.post(`/api/v1/telemetry/dashboard/component/query`, {
        dashboard_id: params.dashboardId,
        component_data: params.componentData,
        component_id: params.componentId,
        time_filters: params.queryParams
    });


    // console.log('dataConfig :>> ', params.dataConfig);
    // mock
    // 双指标
    const zhibiaoData = params.componentData.data_config.metrics.map(e => e.displayName)

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

// 获取字段枚举列表
export async function getFieldEnums({ dataset_code, field, page, pageSize = 20 }: {
    dataset_code: string
    field: string
    page: number
    pageSize?: number
}): Promise<any> {
    return await axios.get(`/api/v1/telemetry/dashboard/dataset/field/enums`, {
        params: {
            index_name: dataset_code,
            field,
            page,
            size: pageSize
        }
    });
}