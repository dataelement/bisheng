"use client"

import { Download } from "lucide-react"
import { memo, useMemo } from "react"

import { PivotTableDataResponse } from "../../types/chartData"
import { DataConfig } from "../../types/dataConfig"
import { GroupedPivotRows, groupCrossTabRows } from "../../utils/groupCrossTabRows"
import { useComponentExport } from "../export/useComponentExport"
import { unitConversion } from "./MetricCard"

type DisplayRow =
  | { kind: "subtotal"; group: GroupedPivotRows }
  | { kind: "child"; row: PivotTableDataResponse["rows"][number] }

interface PivotTableProps {
  data: PivotTableDataResponse
  dataConfig: DataConfig
  isDark: boolean
  // F058 AC-09: optional — omit to disable drill-down export (e.g. in contexts with no
  // saved dashboard/component id yet).
  dashboardId?: string
  componentId?: string
}

interface PivotHeaderCell {
  label: string
  path: string[]
  colSpan: number
}

const buildHeaderRows = (columnPaths: string[][]): PivotHeaderCell[][] => {
  const depth = Math.max(1, ...columnPaths.map(path => path.length))
  return Array.from({ length: depth }, (_, level) => {
    const cells: PivotHeaderCell[] = []
    let columnIndex = 0

    while (columnIndex < columnPaths.length) {
      const currentPath = columnPaths[columnIndex]
      const prefix = currentPath.slice(0, level + 1)
      let colSpan = 1
      while (
        columnIndex + colSpan < columnPaths.length
        && JSON.stringify(columnPaths[columnIndex + colSpan].slice(0, level + 1)) === JSON.stringify(prefix)
      ) {
        colSpan += 1
      }
      cells.push({
        label: currentPath[level] || "未分类",
        path: currentPath,
        colSpan,
      })
      columnIndex += colSpan
    }

    return cells
  })
}

const formatValue = (value: number, dataConfig: DataConfig) => {
  const metric = dataConfig.metrics?.[0]
  if (!metric?.numberFormat) {
    return new Intl.NumberFormat("zh-CN").format(value)
  }
  const [formattedValue, unit] = unitConversion(value, dataConfig)
  return `${formattedValue}${unit}`
}

export const PivotTable = memo(function PivotTable({
  data,
  dataConfig,
  isDark,
  dashboardId,
  componentId,
}: PivotTableProps) {
  // F058 AC-09: click a row's category cell to export that category's detail rows.
  // Disabled (no-op) when this table has no saved dashboard/component id yet.
  const canExportDetail = Boolean(dashboardId && componentId)
  const { exportDetail, isExportingDetail } = useComponentExport({
    dashboardId: dashboardId || "",
    componentId: componentId || "",
  })

  const maxValue = useMemo(
    () => Math.max(0, ...data.rows.flatMap(row => row.values)),
    [data.rows]
  )
  const columnPaths = useMemo(
    () => data.columnPaths?.length === data.columns.length
      ? data.columnPaths
      : data.columns.map(column => [column]),
    [data.columnPaths, data.columns]
  )
  const originalColumnPaths = useMemo(
    () => data.originalColumnPaths?.length === data.columns.length
      ? data.originalColumnPaths
      : (data.originalColumns || data.columns).map(column => [column]),
    [data.columns, data.originalColumnPaths, data.originalColumns]
  )
  const headerRows = useMemo(() => buildHeaderRows(columnPaths), [columnPaths])
  const headerDepth = headerRows.length

  // F058 AC-12/AC-13: when the query resolved a group dimension (see transformPivotData),
  // re-cluster rows so same-group rows are contiguous, then rowSpan-merge the group's
  // cell across its rows instead of repeating the label on every row. Per customer
  // feedback, the group's own subtotal (sum of its child rows) leads each group,
  // ahead of the individual child rows.
  const groupDimensionIndex = data.groupDimensionIndex ?? null
  const displayRows = useMemo((): DisplayRow[] => {
    const groups = groupCrossTabRows(data.rows, groupDimensionIndex)
    if (!groups) {
      return data.rows.map(row => ({ kind: "child" as const, row }))
    }
    return groups.flatMap(group => [
      { kind: "subtotal" as const, group },
      ...group.childRows.map(row => ({ kind: "child" as const, row })),
    ])
  }, [data.rows, groupDimensionIndex])

  const cellBackground = (value: number) => {
    if (!value || !maxValue) return isDark ? "rgba(71, 85, 105, 0.18)" : "#f8fafc"
    const opacity = 0.14 + (value / maxValue) * 0.58
    return `rgba(34, 197, 94, ${opacity.toFixed(3)})`
  }

  return (
    <div className="flex size-full min-h-0 flex-col gap-2">
      {data.truncated && (
        <div
          className="shrink-0 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
          role="status"
        >
          数据超过交叉表上限，当前仅展示前 500 行、100 列，请增加筛选条件后查看。
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-background">
        <table
          className="min-w-full border-separate border-spacing-0 text-xs"
          aria-label={`${data.metricName}交叉表`}
        >
        <thead className="sticky top-0 z-20">
          {headerRows.map((headerRow, level) => (
            <tr key={`header-${level}`}>
              {level === 0 && (
                <th
                  scope="col"
                  rowSpan={headerDepth}
                  className="sticky left-0 z-40 w-16 min-w-16 max-w-16 border-b border-r border-border bg-sky-700 px-2 py-2 text-center font-semibold text-white"
                >
                  序号
                </th>
              )}
              {level === 0 && data.rowHeaders.map((header, index) => (
                <th
                  key={`${header}-${index}`}
                  scope="col"
                  rowSpan={headerDepth}
                  className="sticky left-0 z-30 w-32 min-w-32 max-w-32 border-b border-r border-border bg-sky-600 px-3 py-2 text-left font-semibold text-white"
                  style={{ left: `${64 + index * 128}px` }}
                >
                  {header}
                </th>
              ))}
              {headerRow.map((cell, cellIndex) => (
                <th
                  key={`${cell.path.join("-")}-${level}-${cellIndex}`}
                  scope="col"
                  colSpan={cell.colSpan}
                  className={`${level === 0 ? "bg-emerald-700" : "bg-emerald-600"} min-w-24 border-b border-r border-border px-3 py-2 text-center font-semibold text-white`}
                  title={`${data.columnHeaders?.[level] || data.columnHeader}：${cell.label}`}
                >
                  {cell.label}
                </th>
              ))}
              {level === 0 && (
                <th
                  scope="col"
                  rowSpan={headerDepth}
                  className="min-w-24 border-b border-border bg-amber-500 px-3 py-2 text-right font-semibold text-white"
                >
                  合计
                </th>
              )}
            </tr>
          ))}
        </thead>
        <tbody>
          {displayRows.map((entry, rowIndex) => {
            if (entry.kind === "subtotal") {
              const { group } = entry
              // Guaranteed non-null: a "subtotal" entry only exists when groupCrossTabRows
              // resolved groups, which itself requires groupDimensionIndex !== null.
              const gdi = groupDimensionIndex as number
              const remainingDimCount = Math.max(0, data.rowHeaders.length - (gdi + 1))
              const fieldId = data.rowFieldIds?.[gdi]
              const isClickable = canExportDetail && fieldId && group.groupLabel
              const exporting = fieldId ? isExportingDetail(fieldId, group.groupLabel) : false
              return (
                <tr key={`subtotal-${group.groupKey}`} className="bg-slate-50 font-semibold dark:bg-slate-800/40">
                  <th
                    scope="row"
                    className="sticky left-0 z-20 w-16 min-w-16 max-w-16 border-b border-r border-border bg-slate-50 px-2 py-2 text-center font-medium tabular-nums text-foreground dark:bg-slate-800/40"
                  >
                    {rowIndex + 1}
                  </th>
                  <th
                    scope="row"
                    rowSpan={group.childRows.length + 1}
                    className={`sticky z-10 w-32 min-w-32 max-w-32 border-b border-r border-border bg-background px-3 py-2 text-left font-semibold text-foreground ${
                      isClickable ? "cursor-pointer hover:underline hover:text-primary" : ""
                    }`}
                    style={{ left: `${64 + gdi * 128}px`, paddingLeft: `${12 + gdi * 12}px` }}
                    title={isClickable ? `${group.groupLabel}（点击导出该分类明细）` : group.groupLabel}
                    onClick={isClickable ? () => void exportDetail(fieldId, group.groupLabel) : undefined}
                  >
                    <span className="block max-w-28 truncate">
                      {exporting ? "导出中…" : group.groupLabel}
                    </span>
                  </th>
                  {remainingDimCount > 0 && (
                    <th
                      scope="row"
                      colSpan={remainingDimCount}
                      className="sticky z-10 border-b border-r border-border bg-slate-50 px-3 py-2 text-left font-semibold text-slate-500 dark:bg-slate-800/40 dark:text-slate-300"
                      style={{ left: `${64 + (gdi + 1) * 128}px`, paddingLeft: `${12 + (gdi + 1) * 12}px` }}
                    >
                      汇总
                    </th>
                  )}
                  {group.subtotalRow.values.map((value, columnIndex) => (
                    <td
                      key={`subtotal-${group.groupKey}-${JSON.stringify(originalColumnPaths[columnIndex])}`}
                      className="border-b border-r border-border bg-slate-50 px-3 py-2 text-right tabular-nums text-foreground dark:bg-slate-800/40"
                      title={`${group.groupLabel} · 汇总 · ${columnPaths[columnIndex].join(" / ")}：${formatValue(value, dataConfig)}`}
                    >
                      {value ? formatValue(value, dataConfig) : "—"}
                    </td>
                  ))}
                  <td className="border-b border-border bg-amber-100 px-3 py-2 text-right font-semibold tabular-nums text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                    {formatValue(group.subtotalRow.total, dataConfig)}
                  </td>
                </tr>
              )
            }

            const { row } = entry
            return (
              <tr key={JSON.stringify(row.key)} className="hover:brightness-[0.98]">
                <th
                  scope="row"
                  className="sticky left-0 z-20 w-16 min-w-16 max-w-16 border-b border-r border-border bg-background px-2 py-2 text-center font-medium tabular-nums text-foreground"
                >
                  {rowIndex + 1}
                </th>
                {row.key.map((label, dimensionIndex) => {
                  // The group dimension's cell is fully rendered on the group's subtotal
                  // row (with a rowSpan covering this row) — never repeated here.
                  if (dimensionIndex === groupDimensionIndex) {
                    return null
                  }
                  // F058 AC-09/AC-11: the merged "name(dept)" cell has no single raw value
                  // to filter on, so it never becomes a drill-down export target.
                  const fieldId = data.rowFieldIds?.[dimensionIndex]
                  const isDedupMergedCell = dimensionIndex === data.personDedupIndex
                  const isClickable = canExportDetail && fieldId && !isDedupMergedCell && label
                  const exporting = fieldId ? isExportingDetail(fieldId, label) : false
                  return (
                    <th
                      key={`${label}-${dimensionIndex}`}
                      scope="row"
                      className={`sticky z-10 w-32 min-w-32 max-w-32 border-b border-r border-border bg-background px-3 py-2 text-left font-medium text-foreground ${
                        isClickable ? "cursor-pointer hover:underline hover:text-primary" : ""
                      }`}
                      style={{
                        left: `${64 + dimensionIndex * 128}px`,
                        paddingLeft: `${12 + dimensionIndex * 12}px`,
                      }}
                      title={isClickable ? `${label}（点击导出该分类明细）` : label}
                      onClick={isClickable ? () => void exportDetail(fieldId, label) : undefined}
                    >
                      <span className="block max-w-28 truncate">
                        {exporting ? "导出中…" : (label || "未分类")}
                      </span>
                    </th>
                  )
                })}
                {data.rowHeaders.slice(row.key.length).map((_, missingIndex) => (
                  <th
                    key={`missing-${missingIndex}`}
                    className="border-b border-r border-border bg-background px-3 py-2"
                  />
                ))}
                {row.values.map((value, columnIndex) => (
                  <td
                    key={`${rowIndex}-${JSON.stringify(originalColumnPaths[columnIndex])}`}
                    className="border-b border-r border-border px-3 py-2 text-right tabular-nums text-foreground"
                    style={{ backgroundColor: cellBackground(value) }}
                    title={`${row.key.join(" / ")} · ${columnPaths[columnIndex].join(" / ")}：${formatValue(value, dataConfig)}`}
                  >
                    {value ? formatValue(value, dataConfig) : "—"}
                  </td>
                ))}
                <td className="border-b border-border bg-amber-50 px-3 py-2 text-right font-semibold tabular-nums text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                  {formatValue(row.total, dataConfig)}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot className="sticky bottom-0 z-10">
          <tr>
            <th
              colSpan={Math.max(1, data.rowHeaders.length + 1)}
              className="sticky left-0 z-30 border-r border-t border-border bg-slate-100 px-3 py-2 text-left font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              合计
            </th>
            {data.columnTotals.map((value, index) => (
              <td
                key={`total-${JSON.stringify(originalColumnPaths[index])}`}
                className="border-r border-t border-border bg-slate-100 px-3 py-2 text-right font-semibold tabular-nums text-slate-700 dark:bg-slate-800 dark:text-slate-100"
              >
                {formatValue(value, dataConfig)}
              </td>
            ))}
            <td className="border-t border-border bg-amber-100 px-3 py-2 text-right font-bold tabular-nums text-amber-950 dark:bg-amber-900/50 dark:text-amber-100">
              {formatValue(data.grandTotal, dataConfig)}
            </td>
          </tr>
        </tfoot>
        </table>
      </div>
    </div>
  )
})
