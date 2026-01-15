// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils";
import { ChartType, Dashboard, DashboardComponent, LayoutItem, TimeRangeMode } from "@/pages/Dashboard/types/dataConfig";
import axios from "../request";

// Simulate API delay
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

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
    return await updateDashboard(targetId, targetDashboard)
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
    useId: boolean,
    component: DashboardComponent,
    dashboardId: string
    queryParams?: any
}): Promise<QueryDataResponse> {
    const resData = await axios.post(`/api/v1/telemetry/dashboard/component/query`, {
        dashboard_id: params.dashboardId,
        component_data: params.useId ? undefined : params.component,
        component_id: params.useId ? params.component.id : undefined,
        time_filters: params.queryParams.filter(p => p.queryComponentParams).map(({ queryComponentParams: p }) => ({
            type: p.type,
            mode: p.isDynamic ? TimeRangeMode.Dynamic : TimeRangeMode.Fixed,
            recentDays: p.shortcutKey ? Number(p.shortcutKey.replace('last_', '')) : undefined,
            startDate: p.startTime,
            endDate: p.endTime,
        }))
    });

    const metricsData = params.component.data_config.metrics.map(e => e.displayName)

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

    const chartType = params.component.type

    // 根据图表类型返回对应的 mock 数据
    switch (chartType) {
        case ChartType.Bar:
        case ChartType.StackedBar:
        case ChartType.GroupedBar:
        case ChartType.HorizontalBar:
        case ChartType.StackedHorizontalBar:
        case ChartType.GroupedHorizontalBar:
        case ChartType.Line:
        case ChartType.Area:
        case ChartType.StackedLine:
        case ChartType.StackedArea:
            return {
                dimensions: resData.dimensions,
                series: (hasDuidie ? duidieweidu : metricsData).map((name, index) => ({
                    name: name,
                    data: resData.value.map(el => el[index])
                }))
            }
        case ChartType.Pie:
        case ChartType.Donut:
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
        case ChartType.Metric:
            return {
                value: resData.value[0][0],
                title: metricsData[0],
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