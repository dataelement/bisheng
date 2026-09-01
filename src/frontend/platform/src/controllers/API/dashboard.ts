// Mock API functions for dashboard operations

import { generateUUID } from "@/components/bs-ui/utils";
import { resolvePivotColumnLabels } from "@/pages/Dashboard/components/charts/pivotColumnAliases";
import { ChartType, Dashboard, DashboardComponent, LayoutItem, TimeRangeMode, TimeRangeType } from "@/pages/Dashboard/types/dataConfig";
import {
    mergePersonDedupValues,
    resolveGroupDimensionIndex,
    resolvePersonDedupIndices,
} from "@/pages/Dashboard/utils/groupCrossTabRows";
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
    field: string
    field_type: 'string' | 'number' | 'date'
    time_granularitys?: string[]
}

// 指标配置
export interface MetricConfig {
    field: string
    field_type: 'string' | 'number' | 'date'
    name: string
    filter?: Record<string, any>
    aggregations?: Record<string, any>[]
    formula?: 'add' | 'subtract' | 'multiply' | 'divide'
    calculation?: 'share_of_total'
    default_number_format?: {
        type: 'number' | 'percent' | 'duration' | 'storage'
        decimalPlaces: number
        unit?: string
        suffix?: string
        thousandSeparator: boolean
    }
    index?: number
    sum_field?: string
    sum_type?: string
    is_virtual?: boolean
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
    // F058 AC-07: datasets sharing a non-null dataset_group render as one grouped entry
    // in the dataset picker (e.g. 用户规模统计/活跃用户规模统计/全员每日参与度 -> "用户数据统计").
    // "用户反馈统计" is already excluded server-side (is_visible=false), no frontend filter needed.
    dataset_group?: string | null
}

// 获取数据集列表
export async function getDatasets(): Promise<DashboardDataset[]> {
    return await axios.get(`/api/v1/telemetry/dashboard/dataset/list`);
}

// 查询图表数据
import {
    QueryDataResponse
} from '@/pages/Dashboard/types/chartData';
import { sumMetricValues } from '@/pages/Dashboard/components/charts/metricCardValue';
import { cloneDeep } from "lodash-es";

function transformStackedData(resData: any) {
    const { value, dimensions: rawDimensions } = resData;
    const groups: string[] = [];
    const seriesKeys: string[] = [];
    const dataMap: Record<string, Record<string, number>> = {};

    rawDimensions.forEach((dim: string[], index: number) => {
        const seriesName = dim[dim.length - 1];
        const groupName = dim.slice(0, -1).join('\n');
        const val = value[index][0];

        if (!groups.includes(groupName)) groups.push(groupName);
        if (!seriesKeys.includes(seriesName)) seriesKeys.push(seriesName);

        if (!dataMap[groupName]) dataMap[groupName] = {};
        dataMap[groupName][seriesName] = val;
    });

    const series = seriesKeys.map(name => ({
        name,
        data: groups.map(group => dataMap[group][name] ?? null)
    }));

    return { dimensions: groups, series };
}

function transformNormalData(resData: any, component: DashboardComponent) {
    const dimensions = resData.dimensions.map((name: string[]) => name.join('\n'));
    const metrics = component.data_config.metrics || [];
    const series = metrics.map((m, idx) => ({
        name: (m.displayName || m.fieldName || '').length > 24
            ? (m.displayName || m.fieldName).slice(0, 24) + '...'
            : (m.displayName || m.fieldName || ''),
        data: resData.value.map((val: any[]) => val[idx])
    }));

    return { dimensions, series };
}

const MAX_PIVOT_ROWS = 500;
const MAX_PIVOT_COLUMNS = 100;

export function transformPivotData(
    resData: any,
    component: DashboardComponent,
    dimensionFilters: { fieldId: string, values: unknown[] }[] = [],
) {
    const config = component.data_config;
    const rowDimensionCount = config.dimensions?.length || 0;
    const stackDimensions = config.stackDimensions?.length
        ? config.stackDimensions.slice(0, 2)
        : config.stackDimension
            ? [config.stackDimension]
            : [];
    const columnDimensionCount = stackDimensions.length;
    const columnPaths: string[][] = [];
    const columnIndex = new Map<string, number>();
    const rows = new Map<string, { key: string[], values: Map<string, number> }>();
    let truncated = false;

    resData.dimensions.forEach((dimensionValues: unknown[], index: number) => {
        const rowValues = dimensionValues
            .slice(0, rowDimensionCount)
            .map(value => String(value ?? '未分类'));
        const columnPath = dimensionValues
            .slice(rowDimensionCount, rowDimensionCount + columnDimensionCount)
            .map(value => String(value ?? '未分类'));
        const normalizedColumnPath = columnPath.length > 0 ? columnPath : ['未分类'];
        const rowKey = JSON.stringify(rowValues);
        const columnKey = JSON.stringify(normalizedColumnPath);

        if (!columnIndex.has(columnKey)) {
            if (columnPaths.length >= MAX_PIVOT_COLUMNS) {
                truncated = true;
                return;
            }
            columnIndex.set(columnKey, columnPaths.length);
            columnPaths.push(normalizedColumnPath);
        }
        if (!rows.has(rowKey)) {
            if (rows.size >= MAX_PIVOT_ROWS) {
                truncated = true;
                return;
            }
            rows.set(rowKey, { key: rowValues, values: new Map() });
        }
        const metricValue = Number(resData.value[index]?.[0] ?? 0);
        const row = rows.get(rowKey)!;
        row.values.set(columnKey, (row.values.get(columnKey) ?? 0) + metricValue);
    });

    const columnKeys = columnPaths.map(path => JSON.stringify(path));
    const columnTotals = columnPaths.map(() => 0);
    const pivotRows = Array.from(rows.values()).map(row => {
        const values = columnKeys.map((columnKey, index) => {
            const value = row.values.get(columnKey) ?? 0;
            columnTotals[index] += value;
            return value;
        });
        return {
            key: row.key,
            values,
            total: values.reduce((sum, value) => sum + value, 0),
        };
    });

    // F058 AC-11: when both a person-name field (e.g. uploader_user_name) and its
    // paired department field are configured as row dimensions, merge them into one
    // "name(dept)" cell instead of two columns, to disambiguate same-named people.
    const rawRowFieldIds = (config.dimensions || []).map(dimension => dimension.fieldId);
    const personDedup = resolvePersonDedupIndices(rawRowFieldIds);
    const mergedRowFieldIds = personDedup
        ? rawRowFieldIds.filter((_id, index) => index !== personDedup.deptIndex)
        : rawRowFieldIds;
    const mergedRowHeaders = (config.dimensions || [])
        .filter((_dimension, index) => !personDedup || index !== personDedup.deptIndex)
        .map(dimension => dimension.displayName || dimension.fieldName || dimension.fieldId);
    if (personDedup) {
        pivotRows.forEach(row => {
            row.key = mergePersonDedupValues(row.key, personDedup.personIndex, personDedup.deptIndex);
        });
    }
    // Index of the merged "name(dept)" column in the FINAL (post-removal) key/header
    // arrays — shifts left by one if the removed department column came before it.
    const personDedupIndex = personDedup
        ? personDedup.personIndex - (personDedup.deptIndex < personDedup.personIndex ? 1 : 0)
        : null;

    const displayColumnPaths = columnPaths.map(path => path.map((value, index) => {
        const dimension = stackDimensions[index];
        return resolvePivotColumnLabels({
            columns: [value],
            stackDimension: dimension,
            aliasConfig: config.pivotColumnAliases,
        })[0];
    }));
    const columnHeaders = stackDimensions.map(
        dimension => dimension.displayName || dimension.fieldName || dimension.fieldId
    );

    // F058 AC-12/AC-13: group rows by the finest actively-filtered org-hierarchy row
    // dimension (see spec.md AD-02 — this is a pure client-side transform over the
    // already-flat rows above; the backend response/aggregation contract is unchanged).
    // Computed on the post-merge field list so indices line up with the returned rows.
    const groupDimensionIndex = resolveGroupDimensionIndex(mergedRowFieldIds, dimensionFilters);

    return {
        rowHeaders: mergedRowHeaders,
        columnHeader: columnHeaders[0] || '',
        columnHeaders,
        metricName: config.metrics?.[0]?.displayName
            || config.metrics?.[0]?.fieldName
            || '',
        columns: displayColumnPaths.map(path => path[path.length - 1]),
        originalColumns: columnPaths.map(path => path[path.length - 1]),
        columnPaths: displayColumnPaths,
        originalColumnPaths: columnPaths,
        rows: pivotRows,
        columnTotals,
        grandTotal: columnTotals.reduce((sum, value) => sum + value, 0),
        truncated,
        groupDimensionIndex,
        rowFieldIds: mergedRowFieldIds,
        personDedupIndex,
    };
}

export async function queryChartData(params: {
    useId: boolean,
    component: DashboardComponent,
    dashboardId: string
    queryParams?: any
}): Promise<QueryDataResponse> {
    const { component, useId, dashboardId, queryParams = [] } = params;

    const dimensionFilters = queryParams.flatMap(
        param => param.dimensionFilters || []
    );

    const resData = await axios.post(`/api/v1/telemetry/dashboard/component/query`, {
        dashboard_id: dashboardId,
        component_data: useId ? undefined : component,
        component_id: useId ? component.id : undefined,
        time_filters: queryParams
            .filter(p => p.queryComponentParams || (p.queryConditions && p.queryConditions.hasDefaultValue)) // all
            .map(({ queryComponentParams: p, queryConditions: q }) => {
                if (p) {
                    return {
                        type: p.shortcutKey ? TimeRangeType.RECENT_DAYS : TimeRangeType.CUSTOM,
                        mode: p.isDynamic ? TimeRangeMode.Dynamic : TimeRangeMode.Fixed,
                        recentDays: p.shortcutKey ? Number(p.shortcutKey.replace('last_', '')) : undefined,
                        startDate: p.startTime,
                        endDate: p.endTime,
                    }
                } else if (q) {
                    return q.defaultValue
                }
            }),
        dimension_filters: dimensionFilters,
    });

    if (!resData?.value?.length) return null

    if (component.type === ChartType.PivotTable) {
        return transformPivotData(resData, component, dimensionFilters);
    }

    const isStacked = !!component.data_config.stackDimension?.fieldId;
    const { dimensions, series } = isStacked
        ? transformStackedData(resData)
        : transformNormalData(resData, component);

    // console.log('query params :>> ', dimensions, series);

    const chartType = params.component.type

    // 根据图表类型返回对应的 数据
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
                dimensions,// xAxis.data
                series // legend && series(chart line) 
            }
        case ChartType.Pie:
        case ChartType.Donut:
            return {
                dimensions: [],
                series: [
                    {
                        name: '',
                        data: dimensions.map((name, index) => ({
                            name: name,
                            value: resData.value[index][0]
                        }))
                    }
                ]
            }
        case ChartType.Metric:
            return {
                value: sumMetricValues(resData.value[0]),
                title: series[0]?.name || '',
                unit: '',
                trend: { value: 0, direction: 'up', label: '' },
                format: { decimalPlaces: 2, thousandSeparator: true }
            };
    }
}

// F058 AC-09: export the detail rows for one clicked chart category as an Excel file.
export async function exportComponentDetail(params: {
    dashboardId: string
    componentId: string
    dimensionField: string
    dimensionValue: string | number
    timeFilters?: any[]
    dimensionFilters?: { fieldId: string, values: unknown[] }[]
}): Promise<{ file_url: string }> {
    return await axios.post(
        `/api/v1/telemetry/dashboard/component/${params.componentId}/export`,
        {
            dashboard_id: params.dashboardId,
            dimension_field: params.dimensionField,
            dimension_value: params.dimensionValue,
            time_filters: params.timeFilters || [],
            dimension_filters: params.dimensionFilters || [],
        },
    );
}

// F058 AC-10: export the whole chart as a multi-sheet Excel file.
export async function exportComponentAll(params: {
    dashboardId: string
    componentId: string
    timeFilters?: any[]
    dimensionFilters?: { fieldId: string, values: unknown[] }[]
}): Promise<{ file_url: string }> {
    return await axios.post(
        `/api/v1/telemetry/dashboard/component/${params.componentId}/export-all`,
        {
            dashboard_id: params.dashboardId,
            time_filters: params.timeFilters || [],
            dimension_filters: params.dimensionFilters || [],
        },
    );
}

// 获取字段枚举列表
export async function getFieldEnums({ dataset_code, field, labelField, exactValues, page, pageSize = 20, keyword = "" }: {
    dataset_code: string
    field: string
    labelField?: string
    exactValues?: string[]
    page: number
    pageSize?: number
    keyword?: string
}): Promise<any> {
    return await axios.get(`/api/v1/telemetry/dashboard/dataset/field/enums`, {
        params: {
            index_name: dataset_code,
            field,
            label_field: labelField,
            exact_values: exactValues?.join(','),
            page,
            size: pageSize,
            keyword
        }
    });
}
