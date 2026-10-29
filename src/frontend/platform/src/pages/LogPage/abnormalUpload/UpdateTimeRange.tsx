import ClearableFilter from "@/components/bs-comp/filterTableDataComponent/ClearableFilter"
import { Button } from "@/components/bs-ui/button"
import { Calendar } from "@/components/bs-ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { cname } from "@/components/bs-ui/utils"
import { formatDate } from "@/util/utils"
import { CalendarDays } from "lucide-react"
import { useState } from "react"
import type { DateRange } from "react-day-picker"

function parseDay(value: string): Date | undefined {
    if (!value) return undefined
    const date = new Date(`${value}T00:00:00`)
    return Number.isNaN(date.getTime()) ? undefined : date
}

/** 一个「更新时间」入口，点开后选择起止日期。 */
export default function UpdateTimeRange({
    from,
    to,
    label,
    onChange,
}: {
    from: string
    to: string
    label: string
    onChange: (from: string, to: string) => void
}) {
    const [open, setOpen] = useState(false)
    const selected: DateRange | undefined = from
        ? { from: parseDay(from), to: parseDay(to) }
        : undefined
    const text = from && to ? `${from} ~ ${to}` : from

    return (
        <ClearableFilter
            className="w-[240px]"
            isDate
            hasValue={Boolean(from || to)}
            label={label}
            onClear={() => onChange("", "")}
        >
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                    <Button
                        variant="outline"
                        className={cname(
                            "w-[240px] justify-start text-left font-normal bg-search-input",
                            !text && "text-muted-foreground",
                        )}
                    >
                        <CalendarDays className="mr-2 h-4 w-4" />
                        {text || label}
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                    <Calendar
                        mode="range"
                        selected={selected}
                        numberOfMonths={2}
                        onSelect={(range) => {
                            const nextFrom = range?.from ? formatDate(range.from, "yyyy-MM-dd") : ""
                            const nextTo = range?.to ? formatDate(range.to, "yyyy-MM-dd") : ""
                            onChange(nextFrom, nextTo)
                            if (nextFrom && nextTo) setOpen(false)
                        }}
                    />
                </PopoverContent>
            </Popover>
        </ClearableFilter>
    )
}
