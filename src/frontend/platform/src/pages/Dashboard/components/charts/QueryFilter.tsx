"use client"

import { Button } from "@/components/bs-ui/button"
import { DatePicker } from "@/components/bs-ui/calendar/datePicker"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { Search } from "lucide-react"
import { useState } from "react"

interface QueryFilterProps {
    isPreviewMode?: boolean
}

export function QueryFilter({ isPreviewMode = false }: QueryFilterProps) {
    const { triggerQuery } = useEditorDashboardStore()
    const [date, setDate] = useState<Date | undefined>(undefined)

    const handleDateChange = (newDate: Date) => {
        setDate(newDate)
    }

    const handleQuery = () => {
        console.log("查询日期:", date)
        triggerQuery()
    }

    return (
        <div className="w-full h-full p-4 flex flex-col gap-3 relative">
            {/* 日期选择区域 */}
            <div className="flex flex-col gap-2">
                <label className="text-sm font-medium">选择日期</label>
                <DatePicker
                    value={date}
                    onChange={handleDateChange}
                    placeholder="选择日期"
                />
            </div>

            {/* 查询按钮 - 固定在右下角 */}
            <div className="absolute bottom-4 right-4">
                <Button onClick={handleQuery} size="sm" className="gap-1">
                    <Search className="h-4 w-4" />
                    查询
                </Button>
            </div>
        </div>
    )
}
