"use client"
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/bs-ui/popover"
import { formatDate } from "@/util/utils"
import { CalendarDays } from "lucide-react"
import * as React from "react"
import { useMemo } from "react"
import { Button } from "../button"
import { Calendar } from "../calendar"
import { cname } from "../utils"

export function DatePicker({
    value,
    placeholder = '',
    onChange
}) {
    const [date, setDate] = React.useState<Date>(value)

    const dateStr = useMemo(() => {
        return date ? formatDate(date, 'yyyy-MM-dd') : ''
    }, [date])

    React.useEffect(() => {
        setDate(value)
    }, [value])

    return (
        <Popover>
            <PopoverTrigger asChild>
                <Button
                    variant={"outline"}
                    className={cname(
                        "w-full justify-start text-left font-normal bg-search-input",
                        !date && "text-muted-foreground"
                    )}
                >
                    <CalendarDays className="mr-2 h-4 w-4" />
                    {dateStr || <span>{placeholder}</span>}
                </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                    mode="single"
                    selected={date}
                    onSelect={(d) => {
                        setDate(d)
                        onChange?.(d)
                    }}
                    initialFocus
                />
            </PopoverContent>
        </Popover>
    )
}
