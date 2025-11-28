"use client"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { formatDate } from "@/util/utils"
import { CalendarDays, Clock } from "lucide-react"
import { useMemo, useEffect, useState, useCallback, useRef } from "react"
import { Button } from "../button"
import { Calendar } from "../calendar"
import { cname } from "../utils"

const parseDate = (value: string | Date | number | undefined): Date | null => {
  if (!value) return null
  if (value instanceof Date) return value
  
  // 处理数字时间戳（可能是秒级或毫秒级）
  if (typeof value === 'number') {
    console.log('Parsing timestamp:', value)
    // 判断是秒级还是毫秒级时间戳
    // 如果数值小于 1000000000000（即小于 2001-09-09），则认为是秒级
    const timestamp = value < 1000000000000 ? value * 1000 : value
    const date = new Date(timestamp)
    console.log('Timestamp result:', date)
    return isNaN(date.getTime()) ? null : date
  }
  
  // 处理字符串日期
  if (typeof value === 'string') {
    let date: Date
    
    // 处理 ISO 格式 (包含 T 的格式)
    if (value.includes('T')) {
      date = new Date(value)
    } 
    // 处理 yyyy-MM-dd HH:mm:ss 格式
    else if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
      date = new Date(value.replace(' ', 'T'))
    }
    // 处理 yyyy-MM-dd 格式
    else if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      date = new Date(value + 'T00:00:00')
    }
    // 其他格式
    else {
      date = new Date(value)
    }
    
    console.log('Parsing date string:', value, '->', date)
    return isNaN(date.getTime()) ? null : date
  }
  
  return null
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
  const scrollTimeoutRef = useRef<NodeJS.Timeout>()
  const isScrollingRef = useRef(false)

  // 滚动到指定值
  const scrollToValue = useCallback((val: number, smooth = true) => {
    if (columnRef.current) {
      const scrollTop = val * itemHeight
      columnRef.current.scrollTo({
        top: scrollTop,
        behavior: smooth ? 'smooth' : 'auto'
      })
    }
  }, [itemHeight])

  // 初始化滚动位置
  useEffect(() => {
    scrollToValue(value, false)
  }, [])

  // 当 value 变化时，平滑滚动到新位置
  useEffect(() => {
    if (columnRef.current && !isScrollingRef.current) {
      scrollToValue(value, true)
    }
  }, [value, scrollToValue])

  // 处理滚动事件
  const handleScroll = useCallback(() => {
    if (!columnRef.current) return
    
    isScrollingRef.current = true
    
    // 清除之前的定时器
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current)
    }
    
    // 设置新的定时器，在滚动停止后对齐
    scrollTimeoutRef.current = setTimeout(() => {
      if (!columnRef.current) return
      
      const scrollTop = columnRef.current.scrollTop
      const currentIndex = Math.round(scrollTop / itemHeight)
      const clampedIndex = Math.max(0, Math.min(max, currentIndex))
      
      if (clampedIndex !== value) {
        onChange(clampedIndex)
      }
      
      isScrollingRef.current = false
    }, 150) // 滚动结束后150ms触发对齐
  }, [value, onChange, max, itemHeight])

  // 处理点击
  const handleClick = useCallback((val: number) => {
    onChange(val)
    scrollToValue(val, true)
  }, [onChange, scrollToValue])

  // 处理滚轮事件
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    if (!columnRef.current) return
    
    const delta = e.deltaY > 0 ? 1 : -1
    const newValue = Math.max(0, Math.min(max, value + delta))
    
    onChange(newValue)
    scrollToValue(newValue, true)
  }, [value, onChange, max, scrollToValue])

  // 清理定时器
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current)
      }
    }
  }, [])

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
          onScroll={handleScroll}
          onWheel={handleWheel}
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
  disabled?: boolean
}

export function DatePicker({
  value,
  placeholder = '',
  onChange,
  showTime = false,
  dateFormat = showTime ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd',
  disabled = false
}: DatePickerProps) {
  
  console.log('DatePicker value:', value)
  
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
    console.log('Parsed date:', parsed)
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
          disabled={disabled}
          className={cname(
            "w-full justify-start text-left font-normal bg-search-input",
            !dateStr && "text-muted-foreground"
          )}
        >
          <CalendarDays className={cname(
            "h-4 w-4",
            !dateStr && "mr-2"
          )}/>
          {dateStr || <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-auto p-0"
        align="start"
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