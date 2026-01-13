import { Button } from "@/components/bs-ui/button";
import { Calendar } from "@/components/bs-ui/calendar";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { cn } from "@/utils";
import { endOfDay, endOfMonth, format, getHours, getMonth, getYear, setHours, startOfDay, startOfMonth, subDays } from "date-fns";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

// --- Type Definitions ---

export type DateGranularity = "month" | "day" | "hour";

export interface DatePickerValue {
  startTime: number; // 10-digit Unix timestamp (seconds)
  endTime: number;   // 10-digit Unix timestamp (seconds)
  shortcutKey?: string; // Key of the selected shortcut
  isDynamic?: boolean;  // Whether the time range updates dynamically relative to "now"
}

interface AdvancedDatePickerProps {
  value?: DatePickerValue;
  onChange: (value: DatePickerValue) => void;
  granularity?: DateGranularity; // Precision: month | day | hour
  mode?: "single" | "range";     // Selection mode: single point or range
  placeholder?: string;
  isDark?: boolean;
}

// --- Helper Component: MonthPicker ---
// Custom lightweight Month Picker as standard Shadcn/Date-pickers often focus on days
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
  const { t } = useTranslation("dashboard")
  const [year, setYearState] = useState(currentDate.getFullYear());

  const months = Array.from({ length: 12 }, (_, i) => i);

  const isSelected = (m: number) => {
    if (mode === "single") {
      return selection && getYear(selection) === year && getMonth(selection) === m;
    }
    // Simple Range highlighting (highlights endpoints for visual clarity)
    if (selection?.from && getYear(selection.from) === year && getMonth(selection.from) === m) return true;
    if (selection?.to && getYear(selection.to) === year && getMonth(selection.to) === m) return true;
    return false;
  };

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-4">
        <Button variant="outline" size="icon" onClick={() => setYearState(year - 1)} className="h-7 w-7"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="font-semibold">{year}{t('yearUnit')}</span>
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
            {m + 1}{t('monthUnit')}
          </Button>
        ))}
      </div>
    </div>
  );
};

// --- Main Component ---
export function AdvancedDatePicker({
  value,
  onChange,
  granularity = "day",
  mode = "range",
  placeholder = "select time",
  isDark = false
}: AdvancedDatePickerProps) {
  const { t } = useTranslation("dashboard")
  const [open, setOpen] = useState(false);

  // Internal State
  const [dateRange, setDateRange] = useState<{ from?: Date; to?: Date } | undefined>();
  const [selectedShortcut, setSelectedShortcut] = useState<string | undefined>(undefined);
  const [isDynamic, setIsDynamic] = useState(false);

  // Hour State (Managed independently for easier UI binding)
  const [startHour, setStartHour] = useState(0);
  const [endHour, setEndHour] = useState(0);

  // Sync internal state with external value when popover opens or value changes
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
      // Reset to default
      setDateRange(undefined);
      setStartHour(0);
      setEndHour(0);
      setSelectedShortcut(undefined);
      setIsDynamic(false);
    }
  }, [value, open]);

  // --- Logic Handlers ---

  const handleShortcutClick = (days: number, key: string) => {
    const end = new Date();
    const start = subDays(end, days);
    setDateRange({ from: start, to: end });

    // Shortcuts usually default to 00:00:00 of the start day to 23:59:59 of the current day
    setStartHour(0);
    setEndHour(23);

    setSelectedShortcut(key);
    // Reset dynamic toggle unless business logic requires persistence
    setIsDynamic(false);
  };

  const handleConfirm = () => {
    if (!dateRange?.from) return;

    let finalStart = new Date(dateRange.from);
    let finalEnd = dateRange.to ? new Date(dateRange.to) : new Date(dateRange.from);

    // 1. Process StartTime based on granularity
    if (granularity === "month") {
      finalStart = startOfMonth(finalStart);
    } else if (granularity === "day") {
      finalStart = startOfDay(finalStart);
    } else if (granularity === "hour") {
      finalStart = setHours(startOfDay(finalStart), startHour);
      finalStart.setMinutes(0);
      finalStart.setSeconds(0);
    }

    // 2. Process EndTime based on granularity
    if (granularity === "month") {
      finalEnd = endOfMonth(finalEnd);
      finalEnd = endOfDay(finalEnd);
    } else if (granularity === "day") {
      finalEnd = endOfDay(finalEnd);
    } else if (granularity === "hour") {
      // If single mode, EndHour matches StartHour; otherwise use endHour state
      finalEnd = setHours(startOfDay(finalEnd), mode === 'single' ? startHour : endHour);
      // Logic: For hour granularity, we treat the selection as the start of that hour block
      finalEnd.setMinutes(0);
      finalEnd.setSeconds(0);
    }

    // Convert to Unix timestamp (seconds)
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

  // --- Display Formatting ---
  const getDisplayValue = () => {
    if (!value?.startTime) return "";
    // if (selectedShortcut) return shortcuts.find((s) => s.key === selectedShortcut)?.label;
    if (selectedShortcut) {
      return t(`shortcut.${selectedShortcut}`);
    }

    const start = new Date(value.startTime * 1000);
    const end = new Date(value.endTime * 1000);

    // Formatting templates
    let fmt = "yyyy/MM/dd";
    if (granularity === "month") fmt = "yyyy/MM";
    if (granularity === "hour") fmt = "yyyy/MM/dd HH";

    const sStr = format(start, fmt);
    const eStr = format(end, fmt);

    // Check if it's effectively a single point in time based on granularity
    const isSamePoint = sStr === eStr;

    if (mode === "single" || isSamePoint) {
      return sStr;
    }
    return `${sStr} - ${eStr}`;
  };

  // --- Shortcut Configurations ---
  const shortcuts = [
    { label: t('shortcut.last_7'), days: 7, key: "last_7" },
    { label: t('shortcut.last_30'), days: 30, key: "last_30" },
    { label: t('shortcut.last_90'), days: 90, key: "last_90" },
    { label: t('shortcut.last_180'), days: 180, key: "last_180" },
  ];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={"outline"}
          className={cn(
            "w-92 justify-start text-left font-normal dark:text-gray-200",
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
                {/* Simplified Month Selection: 
                   First click selects 'from', second click selects 'to'. 
                */}
                <MonthPicker
                  mode={mode}
                  currentDate={dateRange?.from || new Date()}
                  selection={dateRange}
                  onSelect={(d) => {
                    if (mode === 'single') {
                      setDateRange({ from: d, to: d });
                    } else {
                      if (!dateRange?.from || (dateRange.from && dateRange.to)) {
                        setDateRange({ from: d, to: undefined });
                      } else {
                        // Ensure chronological order (from < to)
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

          {/* Hour Inputs Area (Visible only for hour granularity) */}
          {granularity === "hour" && (
            <div className="flex justify-between items-center px-3 mb-3">
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground break-keep">{t('startHour')}</Label>
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
                  <Label className="text-xs text-muted-foreground break-keep">{t('endHour')}</Label>
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

          {/* Shortcuts Area (Range Mode only) */}
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

              {/* Dynamic Checkbox - Appears only when a shortcut is active */}
              {selectedShortcut && (
                <div className="flex items-center space-x-2 px-1 mt-2">
                  <Checkbox
                    id="dynamic-mode"
                    checked={isDynamic}
                    onCheckedChange={(c) => setIsDynamic(c as boolean)}
                  />
                  <Label htmlFor="dynamic-mode" className="text-xs cursor-pointer">
                    {t('dynamicUpdate')}
                  </Label>
                </div>
              )}
            </div>
          )}

          {/* Footer Action */}
          <div className="flex justify-end gap-2  px-3 mb-3">
            <Button className="h-6" variant="ghost" size="sm" onClick={() => setOpen(false)}>{t('cancel')}</Button>
            <Button className="h-6" size="sm" onClick={handleConfirm}>{t('confirm')}</Button>
          </div>

        </div>
      </PopoverContent>
    </Popover>
  );
}