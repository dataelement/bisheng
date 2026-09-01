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
        <div className="group w-full h-full p-4 py-0 flex flex-col gap-3 relative">
            {/* date zone */}
            {/* <div className="flex flex-col gap-2 pr-24">
                <label className={cn("text-sm font-medium", "dark:text-gray-400")}>{t('selectDate')}</label>
            </div> */}

            {/* query btn */}
            <div className="w-full flex flex-1 items-center select-none">
                <div className="no-drag w-full flex flex-wrap items-center gap-2">
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
                    {dimensionFields.map(field => (
                        <MultiSelect
                            key={field.id}
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
                            triggerClassName="no-drag h-9 min-w-32 bg-background"
                            contentClassName="min-w-56"
                        />
                    ))}
                    <Button onClick={handleQuery} className=" gap-1">
                        <Search className="h-4 w-4" />
                        {t('query')}
                    </Button>
                </div>
            </div>

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
