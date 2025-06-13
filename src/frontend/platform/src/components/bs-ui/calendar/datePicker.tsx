"use client"
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/bs-ui/popover"
import { formatDate } from "@/util/utils"
import { CalendarDays, X } from "lucide-react"
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
                    "w-full justify-start text-left font-normal bg-search-input group",
                    !date && "text-muted-foreground"
                )}
                >
                <div className="inline-flex flex-1 items-center justify-between overflow-hidden">
                    <div className="flex items-center truncate">
                    <CalendarDays className="mr-2 h-4 w-4 flex-shrink-0" />
                    {dateStr || <span>{placeholder}</span>}
                    </div>
                    {date && (
                    <X
                        className="
                        h-3.5 w-3.5 min-w-3.5 
                        opacity-0 group-hover:opacity-100
                        transition-opacity duration-200
                        bg-black rounded-full
                        flex items-center justify-center
                        flex-shrink-0 ml-2
                        "
                        color="#ffffff"
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                        e.stopPropagation();
                        setDate(undefined);
                        onChange?.(undefined);
                        }}
                    />
                    )}
                </div>
                </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                mode="single"
                selected={date}
                onSelect={(d) => {
                    setDate(d);
                    onChange?.(d);
                }}
                initialFocus
                />
            </PopoverContent>
        </Popover>
    )
}
