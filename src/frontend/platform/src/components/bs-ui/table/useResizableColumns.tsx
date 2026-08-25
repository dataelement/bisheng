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
    const cap = typeof window !== "undefined" ? Math.max(400, window.innerWidth - 80) : 2000
    const next = Math.min(cap, Math.max(colDefs.minWidth, Math.round(d.startW + dx)))
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
      if (colIndex < 0 || colIndex >= widthsRef.current.length) return
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
      return {
        className: "relative",
        style: {
          width: w,
          minWidth: w,
          maxWidth: w,
          boxSizing: "border-box",
        },
      }
    },
    [widths]
  )

  const getTdProps = useCallback(
    (columnIndex: number): TdHTMLAttributes<HTMLTableCellElement> => {
      const w = widths[columnIndex]
      return {
        style: {
          width: w,
          minWidth: w,
          maxWidth: w,
          boxSizing: "border-box",
        },
      }
    },
    [widths]
  )

  return {
    widths,
    totalWidth,
    getThProps,
    getTdProps,
    startResize,
  }
}

/** 放在表头单元格右侧边缘，拖拽以调整当前列宽。操作列可传 lastColumn 隐藏把手。 */
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
      className="group/col-resize absolute right-0 top-0 z-20 flex h-full w-4 min-w-[14px] -translate-x-1/2 cursor-col-resize select-none items-center justify-center"
      onMouseDown={startResize(columnIndex)}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("system.columnResizeHint")}
    >
      {/*
        The handle itself is the visible column split. Header border-l stays off
        so the two lines do not stack.
      */}
      <span
        className="pointer-events-none h-full w-px bg-[#C9CDD4] transition-[width,background-color] duration-150 group-hover/col-resize:w-0.5 group-hover/col-resize:bg-[#165dff] dark:bg-zinc-500 dark:group-hover/col-resize:bg-[#165dff]"
        aria-hidden
      />
    </span>
  )
}
