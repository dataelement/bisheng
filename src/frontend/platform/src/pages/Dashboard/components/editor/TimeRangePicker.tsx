// TimeRangePicker.tsx
"use client"

import { Button } from "@/components/bs-ui/button"
import { Calendar } from "@/components/bs-ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { CalendarIcon } from "lucide-react"
import { format } from "date-fns"
import { zhCN } from "date-fns/locale"
import { useState, useEffect } from "react"
import { cn } from "@/util/utils"

interface TimeRangePickerProps {
  startDate?: string
  endDate?: string
  onChange?: (range: { startDate?: string; endDate?: string }) => void
  className?: string
}

export function TimeRangePicker({ 
  startDate, 
  endDate, 
  onChange,
  className 
}: TimeRangePickerProps) {
  const [dateRange, setDateRange] = useState<{ from?: Date; to?: Date }>({
    from: startDate ? new Date(startDate) : undefined,
    to: endDate ? new Date(endDate) : undefined
  })
  const [tempRange, setTempRange] = useState<{ from?: Date; to?: Date }>({
    from: startDate ? new Date(startDate) : undefined,
    to: endDate ? new Date(endDate) : undefined
  })
  const [open, setOpen] = useState(false)

  // 当外部传入的日期变化时更新内部状态
  useEffect(() => {
    setDateRange({
      from: startDate ? new Date(startDate) : undefined,
      to: endDate ? new Date(endDate) : undefined
    })
    setTempRange({
      from: startDate ? new Date(startDate) : undefined,
      to: endDate ? new Date(endDate) : undefined
    })
  }, [startDate, endDate])

  // 处理日期选择（只更新临时状态）
  const handleSelect = (range: { from?: Date; to?: Date } | undefined) => {
    if (!range) return
    
    setTempRange({
      from: range.from,
      to: range.to
    })
  }

  // 清除选择
  const handleClear = () => {
    setDateRange({})
    setTempRange({})
    onChange?.({ startDate: '', endDate: '' })
    setOpen(false)
  }

  // 确定选择
  const handleConfirm = () => {
    if (tempRange.from && tempRange.to) {
      setDateRange(tempRange)
      onChange?.({
        startDate: format(tempRange.from, 'yyyy-MM-dd'),
        endDate: format(tempRange.to, 'yyyy-MM-dd')
      })
      setOpen(false)
    }
  }

  // 取消选择
  const handleCancel = () => {
    setTempRange(dateRange) // 恢复之前的选中状态
    setOpen(false)
  }

  // 格式化显示文本
  const getDisplayText = () => {
    if (dateRange.from && dateRange.to) {
      return `${format(dateRange.from, 'yyyy-MM-dd')} 至 ${format(dateRange.to, 'yyyy-MM-dd')}`
    } else if (dateRange.from) {
      return `${format(dateRange.from, 'yyyy-MM-dd')} 至 ?`
    }
    return "选择时间范围"
  }

  return (
    <div className={cn("w-full", className)}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            className={cn(
              "w-full h-9 justify-start text-left font-normal hover:bg-accent hover:text-accent-foreground",
              !dateRange.from && "text-muted-foreground"
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4" />
            {getDisplayText()}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <div className="p-3">
            <Calendar
              mode="range"
              selected={tempRange}
              onSelect={handleSelect}
              defaultMonth={tempRange.from || dateRange.from}
              numberOfMonths={1}
              locale={zhCN}
              className="rounded-md border"
            />
          </div>
          <div className="flex items-center justify-between p-3 border-t">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              disabled={!tempRange.from && !tempRange.to}
            >
              清除
            </Button>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
              >
                取消
              </Button>
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={!tempRange.from || !tempRange.to}
              >
                确定
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}