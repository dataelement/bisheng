import type { TdHTMLAttributes, ThHTMLAttributes } from "react"
import type { MouseEvent as ReactMouseEvent } from "react"
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/bs-ui/tooltip"
import { cname } from "@/components/bs-ui/utils"
import { TableCell, TableHead } from "@/components/bs-ui/table"
import { ColumnResizeHandle } from "@/components/bs-ui/table/useResizableColumns"

export function TruncatedTableCell({
    tdProps,
    text,
    multiline = false,
    full = false,
}: {
    tdProps: TdHTMLAttributes<HTMLTableCellElement>
    text: string
    multiline?: boolean
    full?: boolean
}) {
    return (
        <TableCell {...tdProps} className={full ? "align-top" : "overflow-hidden"}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <div
                        className={cname(
                            "min-w-0 max-w-full cursor-default",
                            full
                                ? "whitespace-pre-line break-all"
                                : multiline
                                    ? "whitespace-pre-line break-all line-clamp-3"
                                    : "truncate",
                        )}
                    >
                        {text}
                    </div>
                </TooltipTrigger>
                <TooltipContent className="max-h-80 max-w-lg overflow-y-auto whitespace-pre-wrap break-all">
                    {text}
                </TooltipContent>
            </Tooltip>
        </TableCell>
    )
}

export function ResizableTableHead({
    label,
    columnIndex,
    lastColumn,
    thProps,
    startResize,
    className,
}: {
    label: string
    columnIndex: number
    lastColumn: boolean
    thProps: ThHTMLAttributes<HTMLTableCellElement>
    startResize: (columnIndex: number) => (e: ReactMouseEvent<HTMLSpanElement>) => void
    className?: string
}) {
    return (
        <TableHead
            {...thProps}
            className={cname(
                thProps.className,
                className,
            )}
        >
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="block min-w-0 w-full truncate pr-2">{label}</span>
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
            </Tooltip>
            <ColumnResizeHandle
                columnIndex={columnIndex}
                lastColumn={lastColumn}
                startResize={startResize}
            />
        </TableHead>
    )
}
