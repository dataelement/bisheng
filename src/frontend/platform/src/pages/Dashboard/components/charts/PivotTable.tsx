"use client"

import { memo, useMemo } from "react"

import { PivotTableDataResponse } from "../../types/chartData"
import { DataConfig } from "../../types/dataConfig"
import { unitConversion } from "./MetricCard"

interface PivotTableProps {
  data: PivotTableDataResponse
  dataConfig: DataConfig
  isDark: boolean
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
}: PivotTableProps) {
  const maxValue = useMemo(
    () => Math.max(0, ...data.rows.flatMap(row => row.values)),
    [data.rows]
  )

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
          <tr>
            {data.rowHeaders.map((header, index) => (
              <th
                key={`${header}-${index}`}
                className="sticky left-0 z-30 w-32 min-w-32 max-w-32 border-b border-r border-border bg-sky-600 px-3 py-2 text-left font-semibold text-white"
                style={{ left: `${index * 128}px` }}
              >
                {header}
              </th>
            ))}
            {data.columns.map((column, columnIndex) => {
              const originalColumn = data.originalColumns?.[columnIndex] || column
              return (
                <th
                  key={`${originalColumn}-${columnIndex}`}
                  className="min-w-24 border-b border-r border-border bg-emerald-600 px-3 py-2 text-right font-semibold text-white"
                  title={
                    originalColumn === column
                      ? `${data.columnHeader}：${column}`
                      : `${data.columnHeader}：${originalColumn} → ${column}`
                  }
                >
                  {column}
                </th>
              )
            })}
            <th className="min-w-24 border-b border-border bg-amber-500 px-3 py-2 text-right font-semibold text-white">
              合计
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, rowIndex) => (
            <tr key={JSON.stringify(row.key)} className="hover:brightness-[0.98]">
              {row.key.map((label, dimensionIndex) => (
                <th
                  key={`${label}-${dimensionIndex}`}
                  className="sticky z-10 w-32 min-w-32 max-w-32 border-b border-r border-border bg-background px-3 py-2 text-left font-medium text-foreground"
                  style={{
                    left: `${dimensionIndex * 128}px`,
                    paddingLeft: `${12 + dimensionIndex * 12}px`,
                  }}
                  title={label}
                >
                  <span className="block max-w-28 truncate">
                    {label || "未分类"}
                  </span>
                </th>
              ))}
              {data.rowHeaders.slice(row.key.length).map((_, missingIndex) => (
                <th
                  key={`missing-${missingIndex}`}
                  className="border-b border-r border-border bg-background px-3 py-2"
                />
              ))}
              {row.values.map((value, columnIndex) => (
                <td
                  key={`${rowIndex}-${data.originalColumns?.[columnIndex] || data.columns[columnIndex]}`}
                  className="border-b border-r border-border px-3 py-2 text-right tabular-nums text-foreground"
                  style={{ backgroundColor: cellBackground(value) }}
                  title={`${row.key.join(" / ")} · ${data.columns[columnIndex]}：${formatValue(value, dataConfig)}`}
                >
                  {value ? formatValue(value, dataConfig) : "—"}
                </td>
              ))}
              <td className="border-b border-border bg-amber-50 px-3 py-2 text-right font-semibold tabular-nums text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                {formatValue(row.total, dataConfig)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="sticky bottom-0 z-10">
          <tr>
            <th
              colSpan={Math.max(1, data.rowHeaders.length)}
              className="sticky left-0 z-30 border-r border-t border-border bg-slate-100 px-3 py-2 text-left font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              合计
            </th>
            {data.columnTotals.map((value, index) => (
              <td
                key={`total-${data.originalColumns?.[index] || data.columns[index]}`}
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
