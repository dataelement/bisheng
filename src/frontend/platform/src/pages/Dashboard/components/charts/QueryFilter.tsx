"use client"

import { Button } from "@/components/bs-ui/button"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { cn } from "@/utils"
import { GripHorizontalIcon, Search } from "lucide-react"
import { useEffect, useState } from "react"
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

    const handleDateChange = (newDate: Date) => {
        setDate(newDate)
    }

    const handleQuery = () => {
        console.log("查询日期:", date)
        // Refresh the associated chart based on the query component ID 
        refreshChartsByQuery(component, filter)
    }

    const { queryConditions } = component.data_config as QueryConfig
    const map = { 'year_month': 'month', 'year_month_day': 'day', 'year_month_day_hour': 'hour' }

    const [filter, setFilter] = useState<DatePickerValue | undefined>();
    useEffect(() => {
        console.log('filter :>> ', filter);
    }, [filter])
    useEffect(() => {
        // set default filter
        const { type, mode, recentDays, startDate, endDate } = queryConditions.defaultValue
        if (filter) return // not need reset
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
                <div className="no-drag w-full flex gap-4 ">
                    <AdvancedDatePicker
                        granularity={map[queryConditions.timeGranularity]}
                        mode={queryConditions.displayType}
                        isDark={isDark}
                        value={filter}
                        placeholder={t('selectTime')}
                        onChange={(val) => {
                            console.log("Day Range Change:", val);
                            setFilter(val);
                            setQueryComponentParams(component.id, val)
                        }}
                    />
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
