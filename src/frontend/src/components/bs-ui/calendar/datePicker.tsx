"use client"

import * as React from "react"
import { CalendarIcon } from "@radix-ui/react-icons"
import { Button } from "../button"
import { Calendar } from "../calendar"
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover"
import { cname } from "../utils"
import { useMemo } from "react"
import { formatDate } from "@/util/utils"

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
    },[value])

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
                    <CalendarIcon className="mr-2 h-4 w-4" />
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
