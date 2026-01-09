import React, { useState, useEffect } from "react";
import { format, subDays, startOfMonth, endOfMonth, startOfDay, endOfDay, setHours, getHours, setMonth, setYear, getYear, getMonth, isValid, parse } from "date-fns";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, X } from "lucide-react";
import { Button } from "@/components/bs-ui/button";
import { cn } from "@/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Calendar } from "@/components/bs-ui/calendar";
import { Label } from "@/components/bs-ui/label";
import { Input } from "@/components/bs-ui/input";
import { Checkbox } from "@/components/bs-ui/checkbox";

// --- 类型定义 ---

export type DateGranularity = "month" | "day" | "hour";

export interface DatePickerValue {
  startTime: number; // 10位时间戳 (秒)
  endTime: number;   // 10位时间戳 (秒)
  shortcutKey?: string; // 选中的快捷键 key
  isDynamic?: boolean;  // 是否动态更新
}

interface AdvancedDatePickerProps {
  value?: DatePickerValue;
  onChange: (value: DatePickerValue) => void;
  granularity?: DateGranularity; // 粒度：month | day | hour
  mode?: "single" | "range";     // 模式：单点 | 范围
  placeholder?: string;
  isDark?: boolean;
}

// --- 辅助组件：月份选择器 ---
// Shadcn/RD-Picker 不好支持纯月份选择，手写一个轻量级的
const MonthPicker = ({
  currentDate,
  onSelect,
  selection, // { from, to } or single Date
  mode
}: {
  currentDate: Date;
  onSelect: (date: Date) => void;
  selection: any;
  mode: "single" | "range";
}) => {
  const [year, setYearState] = useState(currentDate.getFullYear());

  const months = Array.from({ length: 12 }, (_, i) => i);

  const isSelected = (m: number) => {
    const target = new Date(year, m, 1);
    if (mode === "single") {
      return selection && getYear(selection) === year && getMonth(selection) === m;
    }
    // Range 简单的判断 (仅高亮端点，为了视觉简单)
    if (selection?.from && getYear(selection.from) === year && getMonth(selection.from) === m) return true;
    if (selection?.to && getYear(selection.to) === year && getMonth(selection.to) === m) return true;
    return false;
  };

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-4">
        <Button variant="outline" size="icon" onClick={() => setYearState(year - 1)} className="h-7 w-7"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="font-semibold">{year}年</span>
        <Button variant="outline" size="icon" onClick={() => setYearState(year + 1)} className="h-7 w-7"><ChevronRight className="h-4 w-4" /></Button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {months.map((m) => (
          <Button
            key={m}
            variant={isSelected(m) ? "default" : "outline"}
            className={cn("h-9", isSelected(m) && "bg-primary text-primary-foreground")}
            onClick={() => onSelect(new Date(year, m, 1))}
          >
            {m + 1}月
          </Button>
        ))}
      </div>
    </div>
  );
};

// --- 主组件 ---
export function AdvancedDatePicker({
  value,
  onChange,
  granularity = "day",
  mode = "range",
  placeholder = "选择时间",
  isDark = false
}: AdvancedDatePickerProps) {
  const [open, setOpen] = useState(false);

  // 内部状态
  const [dateRange, setDateRange] = useState<{ from?: Date; to?: Date } | undefined>();
  const [selectedShortcut, setSelectedShortcut] = useState<string | undefined>(undefined);
  const [isDynamic, setIsDynamic] = useState(false);

  // 小时状态 (独立管理，为了方便 UI 绑定)
  const [startHour, setStartHour] = useState(0);
  const [endHour, setEndHour] = useState(0);

  // 初始化回显逻辑
  useEffect(() => {
    if (value && value.startTime) {
      const start = new Date(value.startTime * 1000);
      const end = new Date(value.endTime * 1000);

      setDateRange({ from: start, to: end });
      setStartHour(getHours(start));
      setEndHour(getHours(end));
      setSelectedShortcut(value.shortcutKey);
      setIsDynamic(!!value.isDynamic);
    } else {
      // 默认空
      setDateRange(undefined);
      setStartHour(0);
      setEndHour(0);
      setSelectedShortcut(undefined);
      setIsDynamic(false);
    }
  }, [value, open]); // 打开时也可以重置一下状态确保同步

  // --- 逻辑处理函数 ---

  const handleShortcutClick = (days: number, key: string) => {
    const end = new Date();
    const start = subDays(end, days);
    setDateRange({ from: start, to: end });

    // 快捷键默认设为 0点 到 当前时间 或者 23点? 
    // 通常最近7天是: 7天前的0点 到 今天的当前时间 或 23:59:59
    // 这里简化为整天逻辑
    setStartHour(0);
    setEndHour(23);

    setSelectedShortcut(key);
    // 重置动态勾选，除非业务要求保留
    setIsDynamic(false);
  };

  const handleConfirm = () => {
    if (!dateRange?.from) return;

    let finalStart = new Date(dateRange.from);
    let finalEnd = dateRange.to ? new Date(dateRange.to) : new Date(dateRange.from);

    // 1. 根据粒度 处理 StartTime
    if (granularity === "month") {
      finalStart = startOfMonth(finalStart);
    } else if (granularity === "day") {
      finalStart = startOfDay(finalStart);
    } else if (granularity === "hour") {
      finalStart = setHours(startOfDay(finalStart), startHour);
      // 分秒置0
      finalStart.setMinutes(0);
      finalStart.setSeconds(0);
    }

    // 2. 根据粒度 处理 EndTime
    // 如果是单选模式，user只点了一个日期，我们需要把它扩展成这个时间段的末尾
    if (granularity === "month") {
      finalEnd = endOfMonth(finalEnd);
      // 23:59:59 由 endOfMonth 配合 endOfDay处理，或者手动处理
      finalEnd = endOfDay(finalEnd);
    } else if (granularity === "day") {
      finalEnd = endOfDay(finalEnd);
    } else if (granularity === "hour") {
      finalEnd = setHours(startOfDay(finalEnd), mode === 'single' ? startHour : endHour); // 单选模式下 EndHour 跟 StartHour 一样（还是说业务想要这个小时结束？）
      // 这里的业务逻辑：选某个小时，通常指 XX:00:00 到 XX:59:59 ?
      // 题目说：选某天就是0点到23:59:59。
      // 并没有明确说选小时。假设：小时粒度下，如果是单点，就是这个小时的0分到59分？ 
      // 这里为了简单，如果选小时粒度，开始和结束时间戳如果不跨度，就给那个小时的起止。
      // 但题目要求返回 10位时间戳。

      // 修正逻辑：
      // 范围+年月日时：2025/09/02 09 - 2025/10/02 09
      // 这意味着开始时间是 09:00:00，结束时间是 09:00:00 还是 09:59:59？
      // 通常范围选择器选的是标点。比如 9点到10点。
      // 按照常规理解：
      finalStart.setMinutes(0); finalStart.setSeconds(0);
      finalEnd.setMinutes(0); finalEnd.setSeconds(0);
    }

    // 转换成秒级时间戳
    const startStamp = Math.floor(finalStart.getTime() / 1000);
    const endStamp = Math.floor(finalEnd.getTime() / 1000);

    onChange({
      startTime: startStamp,
      endTime: endStamp,
      shortcutKey: selectedShortcut,
      isDynamic: selectedShortcut ? isDynamic : false,
    });
    setOpen(false);
  };

  // --- 显示格式化 ---
  const getDisplayValue = () => {
    if (!value?.startTime) return "";
    if (selectedShortcut) return shortcuts.find((s) => s.key === selectedShortcut)?.label;
    const start = new Date(value.startTime * 1000);
    const end = new Date(value.endTime * 1000);

    // 格式化模板
    let fmt = "yyyy/MM/dd";
    if (granularity === "month") fmt = "yyyy/MM";
    if (granularity === "hour") fmt = "yyyy/MM/dd HH";

    const sStr = format(start, fmt);
    const eStr = format(end, fmt);

    // 如果是单点模式，或者开始等于结束 (且没有明确说是Range模式强制显示两个)
    // 题目要求：时间+年月：2025/09。
    // 判断是否实际上是同一个“时间点”（根据粒度）
    const isSamePoint = sStr === eStr;

    if (mode === "single" || isSamePoint) {
      return sStr;
    }
    return `${sStr}-${eStr}`;
  };

  // --- 快捷选项配置 ---
  const shortcuts = [
    { label: "最近7天", days: 7, key: "last_7" },
    { label: "最近30天", days: 30, key: "last_30" },
    { label: "最近90天", days: 90, key: "last_90" },
    { label: "最近180天", days: 180, key: "last_180" },
  ];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={"outline"}
          className={cn(
            "w-92 justify-start text-left font-normal",
            !value && "text-muted-foreground"
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {getDisplayValue() || placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className={cn("w-auto p-0", isDark && 'dark bg-gray-950 border-gray-600')} align="start">
        <div className="flex flex-col">

          {/* Calendar Area */}
          <div className="flex">
            {granularity === "month" ? (
              <div className="flex flex-row gap-2 p-2">
                {/* 为了模拟 Range 左右两个面板的效果，如果是 Range 模式且 granularity=month，可以渲染两个MonthPicker，
                     但这比较复杂，通常月份选择只要一个面板选范围即可。
                     为了简化，这里Month只用单面板逻辑处理 Range (第一次点Start，第二次点End) 
                 */}
                <MonthPicker
                  mode={mode}
                  currentDate={dateRange?.from || new Date()}
                  selection={dateRange}
                  onSelect={(d) => {
                    // 简单的 Range 逻辑
                    if (mode === 'single') {
                      setDateRange({ from: d, to: d });
                    } else {
                      if (!dateRange?.from || (dateRange.from && dateRange.to)) {
                        setDateRange({ from: d, to: undefined });
                      } else {
                        // 比较大小，确保 from < to
                        if (d < dateRange.from) {
                          setDateRange({ from: d, to: dateRange.from });
                        } else {
                          setDateRange({ from: dateRange.from, to: d });
                        }
                      }
                    }
                    setSelectedShortcut(undefined);
                  }}
                />
              </div>
            ) : (
              <Calendar
                mode={mode === "range" ? "range" : "single"}
                defaultMonth={dateRange?.from}
                selected={mode === "range" ? dateRange : dateRange?.from}
                onSelect={(val: any) => {
                  if (mode === "single") {
                    setDateRange({ from: val, to: val });
                  } else {
                    setDateRange(val);
                  }
                  setSelectedShortcut(undefined);
                }}
                numberOfMonths={mode === "range" ? 2 : 1}
              />
            )}
          </div>

          {/* Hour Inputs Area (Only if granularity is hour) */}
          {granularity === "hour" && (
            <div className="flex justify-between items-center px-3 mb-3">
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground break-keep">开始小时</Label>
                <Input
                  type="number"
                  min={0} max={23}
                  className="w-16 h-6"
                  value={startHour}
                  onChange={(e) => {
                    const v = parseInt(e.target.value);
                    if (!isNaN(v) && v >= 0 && v <= 23) setStartHour(v);
                  }}
                />
              </div>

              {mode === "range" && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground break-keep">结束小时</Label>
                  <Input
                    type="number"
                    min={0} max={23}
                    className="w-16 h-6"
                    value={endHour}
                    onChange={(e) => {
                      const v = parseInt(e.target.value);
                      if (!isNaN(v) && v >= 0 && v <= 23) setEndHour(v);
                    }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Shortcuts Area (Only for Range Mode) */}
          {mode === "range" && (
            <div className="px-3 mb-3">
              <div className="flex flex-wrap gap-2">
                {shortcuts.map((sc) => (
                  <Button
                    key={sc.key}
                    variant={selectedShortcut === sc.key ? "default" : "outline"}
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => handleShortcutClick(sc.days, sc.key)}
                  >
                    {sc.label}
                  </Button>
                ))}
              </div>

              {/* Dynamic Checkbox - Only show when shortcut is selected */}
              {selectedShortcut && (
                <div className="flex items-center space-x-2 px-1 mt-2">
                  <Checkbox
                    id="dynamic-mode"
                    checked={isDynamic}
                    onCheckedChange={(c) => setIsDynamic(c as boolean)}
                  />
                  <Label htmlFor="dynamic-mode" className="text-xs cursor-pointer">
                    动态更新 (下次查看时自动根据当前时间推算)
                  </Label>
                </div>
              )}
            </div>
          )}

          {/* Footer Action */}
          <div className="flex justify-end gap-2  px-3 mb-3">
            <Button className="h-6" variant="ghost" size="sm" onClick={() => setOpen(false)}>取消</Button>
            <Button className="h-6" size="sm" onClick={handleConfirm}>确定</Button>
          </div>

        </div>
      </PopoverContent>
    </Popover>
  );
}