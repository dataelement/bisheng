import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from "react"
import { useTranslation } from "react-i18next"

export type ResizableColumnDef = {
  /** 初始列宽（px） */
  defaultWidth: number
  /** 拖拽时不低于该宽度（px） */
  minWidth: number
}

export type UseResizableColumnsResult = {
  widths: number[]
  totalWidth: number
  getThProps: (columnIndex: number) => ThHTMLAttributes<HTMLTableCellElement>
  getTdProps: (columnIndex: number) => TdHTMLAttributes<HTMLTableCellElement>
  startResize: (columnIndex: number) => (e: ReactMouseEvent<HTMLSpanElement>) => void
}

/**
 * 表头列间拖拽调整列宽。外层请使用 `overflow-x-auto`，表格使用 `table-layout: fixed` 且 `width: totalWidth`。
 */
export function useResizableColumns(defs: ResizableColumnDef[]): UseResizableColumnsResult {
  const defsKey = useMemo(
    () => defs.map((d) => `${d.defaultWidth}:${d.minWidth}`).join("|"),
    [defs]
  )
  const [widths, setWidths] = useState<number[]>(() => defs.map((d) => d.defaultWidth))

  useEffect(() => {
    setWidths(defs.map((d) => d.defaultWidth))
  }, [defsKey, defs])

  const widthsRef = useRef(widths)
  widthsRef.current = widths

  const dragRef = useRef<{ col: number; startX: number; startW: number } | null>(null)
  const defsRef = useRef(defs)
  defsRef.current = defs

  const totalWidth = useMemo(() => widths.reduce((a, b) => a + b, 0), [widths])

  const endDrag = useCallback(() => {
    dragRef.current = null
    document.body.style.removeProperty("cursor")
    document.body.style.removeProperty("user-select")
  }, [])

  const onMove = useCallback((e: globalThis.MouseEvent) => {
    const d = dragRef.current
    if (!d) return
    const colDefs = defsRef.current[d.col]
    if (!colDefs) return
    const dx = e.clientX - d.startX
    const next = Math.max(colDefs.minWidth, Math.round(d.startW + dx))
    setWidths((prev) => {
      if (prev[d.col] === next) return prev
      const copy = [...prev]
      copy[d.col] = next
      return copy
    })
  }, [])

  const onUp = useCallback(() => {
    endDrag()
    document.removeEventListener("mousemove", onMove)
    document.removeEventListener("mouseup", onUp)
  }, [endDrag, onMove])

  const startResize = useCallback(
    (colIndex: number) => (e: ReactMouseEvent<HTMLSpanElement>) => {
      e.preventDefault()
      e.stopPropagation()
      if (colIndex < 0 || colIndex >= widthsRef.current.length - 1) return
      dragRef.current = {
        col: colIndex,
        startX: e.clientX,
        startW: widthsRef.current[colIndex],
      }
      document.body.style.cursor = "col-resize"
      document.body.style.userSelect = "none"
      document.addEventListener("mousemove", onMove)
      document.addEventListener("mouseup", onUp)
    },
    [onMove, onUp]
  )

  const getThProps = useCallback(
    (columnIndex: number): ThHTMLAttributes<HTMLTableCellElement> => {
      const w = widths[columnIndex]
      const m = defs[columnIndex]?.minWidth ?? 80
      return {
        className: "relative",
        style: {
          width: w,
          minWidth: m,
          maxWidth: w,
          boxSizing: "border-box",
        },
      }
    },
    [defs, widths]
  )

  const getTdProps = useCallback(
    (columnIndex: number): TdHTMLAttributes<HTMLTableCellElement> => {
      const w = widths[columnIndex]
      const m = defs[columnIndex]?.minWidth ?? 80
      return {
        style: {
          width: w,
          minWidth: m,
          maxWidth: w,
          boxSizing: "border-box",
        },
      }
    },
    [defs, widths]
  )

  return {
    widths,
    totalWidth,
    getThProps,
    getTdProps,
    startResize,
  }
}

/** 放在表头单元格右侧边缘，用于拖拽左侧列宽（最后一列不要渲染） */
export function ColumnResizeHandle({
  columnIndex,
  lastColumn,
  startResize,
}: {
  columnIndex: number
  lastColumn: boolean
  startResize: (columnIndex: number) => (e: ReactMouseEvent<HTMLSpanElement>) => void
}) {
  const { t } = useTranslation()
  if (lastColumn) return null
  return (
    <span
      title={t("system.columnResizeHint")}
      className="group/col-resize absolute right-0 top-0 z-20 flex h-full w-4 min-w-[14px] -translate-x-1/2 cursor-col-resize select-none items-center justify-center rounded-sm transition-colors hover:bg-muted/50 active:bg-muted/75"
      onMouseDown={startResize(columnIndex)}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("system.columnResizeHint")}
    >
      {/*
        使用命名子组 group/col-resize，避免与 TableRow 上的 `group` 串线，
        否则整行悬停时所有列的细线会一起出现。
      */}
      <span
        className="pointer-events-none flex h-[42%] min-h-[12px] max-h-[1.125rem] items-stretch gap-[2px] opacity-0 transition-[opacity,gap,color] duration-150 group-hover/col-resize:gap-[3px] group-hover/col-resize:opacity-100 group-hover/col-resize:text-primary/75 dark:group-hover/col-resize:text-primary/80"
        aria-hidden
      >
        <span className="w-px shrink-0 rounded-full bg-muted-foreground/70 group-hover/col-resize:bg-current dark:bg-zinc-400/80" />
        <span className="w-px shrink-0 rounded-full bg-muted-foreground/50 group-hover/col-resize:bg-current group-hover/col-resize:opacity-80 dark:bg-zinc-400/60" />
      </span>
    </span>
  )
}
