"use client"

import { Button } from "@/components/bs-ui/button"
import { DatePicker } from "@/components/bs-ui/calendar/datePicker"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { Search } from "lucide-react"
import { useState } from "react"
import { AdvancedDatePicker, DatePickerValue } from "../AdvancedDatePicker"
import { DashboardComponent, QueryConfig } from "../../types/dataConfig"

interface QueryFilterProps {
    component: DashboardComponent  // Query the ID of the component, which is used to trigger the refresh of the associated chart
    isPreviewMode?: boolean
}

export function QueryFilter({ component, isPreviewMode = false }: QueryFilterProps) {
    const { refreshChartsByQuery } = useEditorDashboardStore()
    const [date, setDate] = useState<Date | undefined>(undefined)

    const handleDateChange = (newDate: Date) => {
        setDate(newDate)
    }

    const handleQuery = () => {
        console.log("查询日期:", date)
        // Refresh the associated chart based on the query component ID 
        refreshChartsByQuery(component.id, filter)
    }

    const { queryConditions } = component.data_config as QueryConfig
    const map = { 'year_month': 'month', 'year_month_day': 'day', 'year_month_day_hour': 'hour' }
    const [filter, setFilter] = useState<DatePickerValue | undefined>();

    return (
        <div className="w-full h-full p-4 flex flex-col gap-3 relative">
            {/* 日期选择区域 */}
            <div className="flex flex-col gap-2 pr-24">
                <label className="text-sm font-medium">选择日期</label>
                <AdvancedDatePicker
                    granularity={'hour'}
                    mode={'range'}
                    value={filter}
                    onChange={(val) => {
                        console.log("Day Range Change:", val);
                        setFilter(val);
                    }}
                />
            </div>

            {/* 查询按钮 - 固定在右下角 */}
            <div className="absolute bottom-5 right-4">
                <Button onClick={handleQuery} size="sm" className="gap-1">
                    <Search className="h-4 w-4" />
                    查询
                </Button>
            </div>
        </div>
    )
}
