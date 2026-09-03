"use client"

import { MultiSelect, Option } from "@/components/bs-ui/multiSelect.tsx"
import { Button } from "@/components/bs-ui/button"
import { getFieldEnums } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { cn } from "@/utils"
import { GripHorizontalIcon, Search } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { DashboardComponent, QueryConfig, TimeRangeMode, TimeRangeType } from "../../types/dataConfig"
import { AdvancedDatePicker, DatePickerValue } from "../AdvancedDatePicker"
import { useTranslation } from "react-i18next"

interface QueryFilterProps {
    component: DashboardComponent  // Query the ID of the component, which is used to trigger the refresh of the associated chart
    isPreviewMode?: boolean
    isDark?: boolean
}

export function QueryFilter({ isDark, component, isPreviewMode = false }: QueryFilterProps) {
    const { t } = useTranslation("dashboard")

    const { refreshChartsByQuery, setQueryComponentParams } = useEditorDashboardStore()
    const [date, setDate] = useState<Date | undefined>(undefined)

    const { queryConditions, dimensionFields = [] } = component.data_config as QueryConfig

    // 客户反馈(2026-09-01): 查询组件除了时间，还要支持知识库大类/知识分类/组织架构/业务域。
    // 每个字段各自的枚举值来自它所属的数据集（配置时已记录在 field.datasetCode 上），跟
    // DimensionFilter.tsx 的加载逻辑一致，只是这里可能跨多个不同的数据集。
    const [dimensionValues, setDimensionValues] = useState<Record<string, string[]>>({})
    const [dimensionOptions, setDimensionOptions] = useState<Record<string, Option[]>>({})
    const [dimensionLoading, setDimensionLoading] = useState<Record<string, boolean>>({})
    const dimensionRequestVersions = useRef<Record<string, number>>({})

    const loadDimensionOptions = useCallback(async (fieldId: string, datasetCode: string | undefined, keyword = "") => {
        if (!datasetCode || !fieldId) return
        const requestVersion = (dimensionRequestVersions.current[fieldId] || 0) + 1
        dimensionRequestVersions.current[fieldId] = requestVersion
        setDimensionLoading(current => ({ ...current, [fieldId]: true }))
        try {
            const response = await getFieldEnums({
                dataset_code: datasetCode,
                field: fieldId,
                page: 1,
                pageSize: 50,
                keyword,
            })
            const nextOptions = (response.options || response.enums || []).map((option: any) => ({
                label: String(option?.label ?? option),
                value: String(option?.value ?? option),
            }))
            if (dimensionRequestVersions.current[fieldId] === requestVersion) {
                setDimensionOptions(current => ({ ...current, [fieldId]: nextOptions }))
            }
        } finally {
            if (dimensionRequestVersions.current[fieldId] === requestVersion) {
                setDimensionLoading(current => ({ ...current, [fieldId]: false }))
            }
        }
    }, [])

    useEffect(() => {
        setDimensionValues(Object.fromEntries(
            dimensionFields.map(field => [field.fieldId, field.defaultValues || []])
        ))
        dimensionFields.forEach(field => {
            void loadDimensionOptions(field.fieldId, field.datasetCode)
        })
        // Only re-run when the configured field list itself changes (not on every keystroke).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [component.id, dimensionFields.map(f => f.fieldId).join(",")])

    const handleQuery = () => {
        // Refresh the associated chart based on the query component ID
        refreshChartsByQuery(component, filter, dimensionValues)
    }

    const map = { 'year_month': 'month', 'year_month_day': 'day', 'year_month_day_hour': 'hour' }

    const [filter, setFilter] = useState<DatePickerValue | undefined>();
    useEffect(() => {
        console.log('filter :>> ', filter);
    }, [filter])

    useEffect(() => {
        // set default filter
        const { type, mode, recentDays, startDate, endDate } = queryConditions.defaultValue

        if (queryConditions.defaultValue) {
            if (type === TimeRangeType.ALL) {
                setQueryComponentParams(component.id, undefined)
                return setFilter(undefined)
            }
            const datePickerVal = {
                isDynamic: mode === TimeRangeMode.Dynamic,
                shortcutKey: recentDays ? `last_${recentDays}` : undefined,
                startTime: startDate,
                endTime: endDate
            }
            setFilter(datePickerVal)
            setQueryComponentParams(component.id, datePickerVal)
        }
    }, [queryConditions.defaultValue])

    return (
        <div
            className={cn(
                "group flex size-full items-center gap-3 overflow-x-auto p-4 py-0 relative select-none",
                isDark ? "text-slate-100" : "text-slate-900"
            )}
        >
            {/* Layout mirrors DimensionFilter.tsx: each condition gets its own labeled
                column, kept in one row (overflow-x-auto instead of wrapping) so this looks
                like the same widget family instead of a plain stacked form. */}
            <div className="no-drag min-w-52 flex-1 space-y-1 [&_button]:h-9 [&_button]:w-full">
                <label className="block truncate text-xs font-medium text-muted-foreground">
                    {t('selectDate')}
                </label>
                <AdvancedDatePicker
                    granularity={map[queryConditions.timeGranularity]}
                    mode={queryConditions.displayType}
                    isDark={isDark}
                    value={filter}
                    placeholder={t('selectTime')}
                    onChange={(val) => {
                        setFilter(val);
                        setQueryComponentParams(component.id, val)
                    }}
                />
            </div>
            {dimensionFields.map(field => (
                <div key={field.id} className="no-drag min-w-52 flex-1 space-y-1">
                    <label
                        className="block truncate text-xs font-medium text-muted-foreground"
                        title={field.displayName}
                    >
                        {field.displayName}
                    </label>
                    <MultiSelect
                        options={dimensionOptions[field.fieldId] || []}
                        value={dimensionValues[field.fieldId] || []}
                        onValueChange={values => {
                            setDimensionValues(current => ({ ...current, [field.fieldId]: values }))
                        }}
                        onSearch={keyword => {
                            void loadDimensionOptions(field.fieldId, field.datasetCode, keyword)
                        }}
                        loading={dimensionLoading[field.fieldId]}
                        multiple
                        searchable
                        clearable
                        maxDisplayed={1}
                        placeholder={`全部${field.displayName}`}
                        searchPlaceholder={`搜索${field.displayName}`}
                        emptyMessage="暂无可选项"
                        triggerClassName="no-drag h-9 bg-background"
                        contentClassName="min-w-64"
                    />
                </div>
            ))}
            <Button onClick={handleQuery} className="no-drag h-9 shrink-0 gap-1">
                <Search className="h-4 w-4" />
                {t('query')}
            </Button>

            {!isPreviewMode && <GripHorizontalIcon
                className={cn(
                    "absolute -top-1 left-1/2 -translate-x-1/2 text-gray-400 transition-opacity",
                    "opacity-0",
                    "group-hover:opacity-100",
                    "group-has-[.no-drag:hover]:opacity-0"
                )}
                size={16}
            />}
        </div>
    )
}
