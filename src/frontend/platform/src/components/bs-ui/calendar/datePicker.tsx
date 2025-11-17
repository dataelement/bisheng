"use client"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { formatDate } from "@/util/utils"
import { CalendarDays } from "lucide-react"
import { useMemo, useEffect, useState } from "react"
import { Button } from "../button"
import { Calendar } from "../calendar"
import { cname } from "../utils"

const parseDate = (value: string | Date | undefined): Date | null => {
  if (!value) return null
  if (value instanceof Date) return value
  const date = new Date(value)
  return isNaN(date.getTime()) ? null : date
}

export function DatePicker({
  value,
  placeholder = '',
  onChange,
  showTime = false,
  dateFormat = showTime ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd'
}) {
  const initialDate = parseDate(value)
  const [date, setDate] = useState<Date | null>(initialDate)
  const [time, setTime] = useState({
    hour: initialDate ? initialDate.getHours() : 0,
    minute: initialDate ? initialDate.getMinutes() : 0,
    second: initialDate ? initialDate.getSeconds() : 0
  })
  const [open, setOpen] = useState(false)

  const dateStr = useMemo(() => {
    if (!date) return ''
    const mergedDate = new Date(date)
    if (showTime) {
      mergedDate.setHours(time.hour)
      mergedDate.setMinutes(time.minute)
      mergedDate.setSeconds(time.second)
    }
    return formatDate(mergedDate, dateFormat)
  }, [date, time, showTime, dateFormat])

  useEffect(() => {
    const parsed = parseDate(value)
    setDate(parsed)
    if (showTime && parsed) {
      setTime({
        hour: parsed.getHours(),
        minute: parsed.getMinutes(),
        second: parsed.getSeconds()
      })
    }
  }, [value, showTime])

  const handleTimeChange = (type: 'hour' | 'minute' | 'second', val: number) => {
    if (!showTime) return
    const newValue = Math.min(type === 'hour' ? 23 : 59, Math.max(0, val))
    setTime(prev => ({ ...prev, [type]: newValue }))
  }

  const handleConfirm = () => {
    if (!date) return
    const mergedDate = new Date(date)
    if (showTime) {
      mergedDate.setHours(time.hour)
      mergedDate.setMinutes(time.minute)
      mergedDate.setSeconds(time.second)
    } else {
      mergedDate.setHours(0, 0, 0, 0)
    }
    onChange?.(mergedDate)
    setOpen(false)
  }

  const handleNow = () => {
    if (!showTime) return
    const now = new Date()
    setDate(now)
    setTime({
      hour: now.getHours(),
      minute: now.getMinutes(),
      second: now.getSeconds()
    })
  }

  const TimeInput = ({ value, onChange, max, placeholder }: {
    value: number
    onChange: (val: number) => void
    max: number
    placeholder: string
  }) => (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(parseInt(e.target.value) || 0)}
      className="w-10 py-1 text-sm border rounded text-center"
      min="0"
      max={max}
      placeholder={placeholder}
    />
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cname(
            "w-full justify-start text-left font-normal bg-search-input",
            !dateStr && "text-muted-foreground"
          )}
        >
          <CalendarDays className="mr-2 h-4 w-4" />
          {dateStr || <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-auto p-4"
        align="start"
        sideOffset={5}
        collisionPadding={16}
      >
        <div className="-space-y-2">
          <Calendar
            mode="single"
            selected={date}
            onSelect={setDate}
            initialFocus
          />

          {showTime && (
            <div className="flex flex-col sm:flex-row items-center gap-3">
              <div className="flex items-center gap-2 order-2 sm:order-1">
                <TimeInput
                  value={time.hour}
                  onChange={(val) => handleTimeChange('hour', val)}
                  max={23}
                  placeholder="时"
                />
                <span className="text-gray-400">:</span>
                <TimeInput
                  value={time.minute}
                  onChange={(val) => handleTimeChange('minute', val)}
                  max={59}
                  placeholder="分"
                />
                <span className="text-gray-400">:</span>
                <TimeInput
                  value={time.second}
                  onChange={(val) => handleTimeChange('second', val)}
                  max={59}
                  placeholder="秒"
                />
              </div>
              <div className="flex gap-2 order-1 sm:order-2 sm:ml-auto w-full sm:w-auto justify-center sm:justify-start">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleNow}
                  className="flex-1 sm:flex-none"
                >
                  此刻
                </Button>
                <Button
                  size="sm"
                  onClick={handleConfirm}
                  disabled={!date}
                  className="flex-1 sm:flex-none"
                >
                  确定
                </Button>
              </div>
            </div>
          )}

          {!showTime && (
            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={!date}
              >
                确认
              </Button>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}