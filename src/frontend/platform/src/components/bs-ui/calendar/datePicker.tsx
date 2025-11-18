"use client"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { formatDate } from "@/util/utils"
import { CalendarDays, Clock } from "lucide-react"
import { useMemo, useEffect, useState, useCallback, useRef } from "react"
import { Button } from "../button"
import { Calendar } from "../calendar"
import { cname } from "../utils"

const parseDate = (value: string | Date | undefined): Date | null => {
  if (!value) return null
  if (value instanceof Date) return value
  const date = new Date(value)
  return isNaN(date.getTime()) ? null : date
}

// 滚动式时间选择器列
const TimeColumn = ({
  value,
  onChange,
  max,
  label
}: {
  value: number
  onChange: (val: number) => void
  max: number
  label: string
}) => {
  const columnRef = useRef<HTMLDivElement>(null)
  const itemHeight = 32 // 每项高度

  // 滚动到指定值
  const scrollToValue = useCallback((val: number, smooth = true) => {
    if (columnRef.current) {
      const scrollTop = val * itemHeight - 0 // itemHeight * 2 // 居中显示
      columnRef.current.scrollTo({
        top: scrollTop,
        behavior: smooth ? 'smooth' : 'auto'
      })
    }
  }, [itemHeight])

  // 初始化滚动位置 - 立即滚动，不使用动画
  useEffect(() => {
    scrollToValue(value, false)
  }, [])

  // 当 value 变化时，平滑滚动到新位置
  useEffect(() => {
    if (columnRef.current) {
      scrollToValue(value, true)
    }
  }, [value, scrollToValue])

  // 处理点击
  const handleClick = useCallback((val: number) => {
    onChange(val)
    scrollToValue(val, true)
  }, [onChange, scrollToValue])

  return (
    <div className="flex flex-col items-center">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className="relative h-40 w-16 overflow-hidden rounded border border-border">
        {/* 选中指示器 */}
        {/* <div className="absolute top-1/2 left-0 right-0 h-8 -translate-y-1/2 border-y border-primary/20 bg-primary/5 pointer-events-none z-10" /> */}

        {/* 滚动列表 */}
        <div
          ref={columnRef}
          className="h-full overflow-y-auto scrollbar-hide scroll-smooth"
          style={{
            paddingTop: `${itemHeight * 2}px`,
            paddingBottom: `${itemHeight * 2}px`
          }}
        >
          {Array.from({ length: max + 1 }, (_, i) => (
            <div
              key={i}
              className={cname(
                "flex items-center justify-center cursor-pointer transition-colors text-sm select-none",
                value === i ? "text-foreground font-semibold" : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              )}
              style={{
                height: `${itemHeight}px`
              }}
              onClick={() => handleClick(i)}
            >
              {i.toString().padStart(2, '0')}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// 时间选择器弹窗
const TimePicker = ({
  value,
  onChange
}: {
  value: { hour: number; minute: number; second: number }
  onChange: (time: { hour: number; minute: number; second: number }) => void
}) => {
  const [open, setOpen] = useState(false)
  const [tempTime, setTempTime] = useState(value)

  // 当弹窗打开时，同步外部时间到临时状态
  useEffect(() => {
    if (open) {
      setTempTime(value)
    }
  }, [open, value])

  const handleConfirm = useCallback(() => {
    onChange(tempTime)
    setOpen(false)
  }, [tempTime, onChange])

  const handleNow = useCallback(() => {
    const now = new Date()
    const newTime = {
      hour: now.getHours(),
      minute: now.getMinutes(),
      second: now.getSeconds()
    }
    setTempTime(newTime)
    onChange(newTime) // 立即更新外部状态
  }, [onChange])

  const timeStr = useMemo(() =>
    `${value.hour.toString().padStart(2, '0')}:${value.minute.toString().padStart(2, '0')}:${value.second.toString().padStart(2, '0')}`,
    [value]
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2 font-normal"
        >
          <Clock className="mr-1.5 h-3.5 w-3.5" />
          {timeStr}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="center">
        <div className="flex flex-col gap-2">
          <div className="flex gap-2 justify-center">
            <TimeColumn
              value={tempTime.hour}
              onChange={(hour) => setTempTime(prev => ({ ...prev, hour }))}
              max={23}
              label="时"
            />
            <TimeColumn
              value={tempTime.minute}
              onChange={(minute) => setTempTime(prev => ({ ...prev, minute }))}
              max={59}
              label="分"
            />
            <TimeColumn
              value={tempTime.second}
              onChange={(second) => setTempTime(prev => ({ ...prev, second }))}
              max={59}
              label="秒"
            />
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleNow}
              className="flex-1"
            >
              此刻
            </Button>
            <Button
              size="sm"
              onClick={handleConfirm}
              className="flex-1"
            >
              确定
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

interface DatePickerProps {
  value?: string | Date
  placeholder?: string
  onChange?: (date: Date) => void
  showTime?: boolean
  dateFormat?: string
}

export function DatePicker({
  value,
  placeholder = '',
  onChange,
  showTime = false,
  dateFormat = showTime ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd'
}: DatePickerProps) {
  const initialDate = useMemo(() => parseDate(value), [value])
  const now = useMemo(() => new Date(), [])

  const [date, setDate] = useState<Date | null>(initialDate)
  const [time, setTime] = useState({
    hour: initialDate ? initialDate.getHours() : now.getHours(),
    minute: initialDate ? initialDate.getMinutes() : now.getMinutes(),
    second: initialDate ? initialDate.getSeconds() : now.getSeconds()
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

  const handleTimeChange = useCallback((newTime: { hour: number; minute: number; second: number }) => {
    setTime(newTime)
  }, [])

  const handleConfirm = useCallback(() => {
    if (!date) return
    const mergedDate = new Date(date)
    if (showTime) {
      mergedDate.setHours(time.hour, time.minute, time.second, 0)
    } else {
      mergedDate.setHours(0, 0, 0, 0)
    }
    onChange?.(mergedDate)
    setOpen(false)
  }, [date, time, showTime, onChange])

  const handleNow = useCallback(() => {
    const now = new Date()
    setDate(now)
    if (showTime) {
      setTime({
        hour: now.getHours(),
        minute: now.getMinutes(),
        second: now.getSeconds()
      })
    }
  }, [showTime])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          // disabled={!isKnowledgeAdmin}
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
        className="w-auto p-0"
        align="start"
      // sideOffset={5}
      // collisionPadding={16}
      >
        <div className="">
          <Calendar
            mode="single"
            selected={date}
            onSelect={setDate}
            initialFocus
          />

          {showTime && (
            <div className="flex flex-col mx-2 mt-0 py-2 border-t">
              <div className="flex items-center justify-between">
                <TimePicker
                  value={time}
                  onChange={handleTimeChange}
                />
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleNow}
                  >
                    此刻
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleConfirm}
                    disabled={!date}
                  >
                    确定
                  </Button>
                </div>
              </div>
            </div>
          )}

          {!showTime && (
            <div className="flex justify-end pt-2 border-t">
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