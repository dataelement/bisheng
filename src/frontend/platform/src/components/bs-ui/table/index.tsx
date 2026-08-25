import * as React from "react"
import { cname } from "../utils"

type TableVariant = "default" | "filelist"

const TableVariantContext = React.createContext<TableVariant>("default")

const Table = React.forwardRef<
    HTMLTableElement,
    React.HTMLAttributes<HTMLTableElement> & { noScroll?: boolean; variant?: TableVariant }
>(({ className, noScroll, variant = "default", ...props }, ref) => (
    <TableVariantContext.Provider value={variant}>
        <div
            className={cname(
                "relative w-full max-w-full",
                noScroll ? "overflow-x-auto" : "overflow-auto"
            )}
        >
            <table
                ref={ref}
                className={cname(
                    "w-full caption-bottom text-sm",
                    variant === "filelist"
                        ? "border-collapse"
                        : "border-separate border-spacing-y-1",
                    className
                )}
                {...props}
            />
        </div>
    </TableVariantContext.Provider>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
    HTMLTableSectionElement,
    React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => {
    const variant = React.useContext(TableVariantContext)
    return (
        <thead
            ref={ref}
            className={cname(
                variant === "filelist"
                    ? "border-b border-[#e5e6eb] bg-[#F3F4F6] dark:border-zinc-700 dark:bg-zinc-800"
                    : "[&>tr]:first:bg-transparent [&>tr]:first:border-none",
                className
            )}
            {...props}
        />
    )
})
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
    HTMLTableSectionElement,
    React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
    <tbody
        ref={ref}
        className={cname("[&_tr:last-child]:border-0", className)}
        {...props}
    />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
    HTMLTableSectionElement,
    React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
    <tfoot
        ref={ref}
        className={cname(
            "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
            className
        )}
        {...props}
    />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
    HTMLTableRowElement,
    React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => {
    const variant = React.useContext(TableVariantContext)
    return (
        <tr
            ref={ref}
            className={cname(
                "group data-[state=selected]:bg-muted",
                variant === "filelist"
                    ? "border-b border-[#e5e6eb] bg-transparent hover:bg-transparent dark:border-zinc-700"
                    : "transition-colors hover:bg-muted/50",
                className
            )}
            {...props}
        />
    )
})
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
    HTMLTableCellElement,
    React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
    const variant = React.useContext(TableVariantContext)
    return (
        <th
            ref={ref}
            className={cname(
                "text-left align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
                variant === "filelist"
                    ? "h-12 bg-[#F3F4F6] px-3 font-normal text-[15px] text-[#545A60] dark:bg-zinc-800 dark:text-zinc-300"
                    : "h-10 px-2 font-medium text-muted-foreground text-md",
                className
            )}
            {...props}
        />
    )
})
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
    HTMLTableCellElement,
    React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
    const variant = React.useContext(TableVariantContext)
    return (
        <td
            ref={ref}
            className={cname(
                "align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
                variant === "filelist"
                    ? "bg-white px-3 py-3 text-[#1d2129] transition-colors duration-150 group-hover:bg-[#f7f7f7] dark:bg-[#171717] dark:text-zinc-200 dark:group-hover:bg-[#2a2b2e]"
                    : "first:rounded-l-md last:rounded-r-md bg-[#FBFBFB] p-2 group-odd:bg-[#f4f5f8] group-hover:bg-[#ebf0ff] dark:bg-[#171717] dark:group-odd:bg-[#111] dark:group-hover:bg-[#2a2b2e]",
                className
            )}
            {...props}
        />
    )
})
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
    HTMLTableCaptionElement,
    React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
    <caption
        ref={ref}
        className={cname("mt-4 text-sm text-muted-foreground", className)}
        {...props}
    />
))
TableCaption.displayName = "TableCaption"

export {
    Table,
    TableHeader,
    TableBody,
    TableFooter,
    TableHead,
    TableRow,
    TableCell,
    TableCaption,
}
