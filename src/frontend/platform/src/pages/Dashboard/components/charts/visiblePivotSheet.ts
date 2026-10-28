// 交叉表「导出全部明细」的第一页. 格子, 合并和提示必须跟 PivotTable 当前画出来的表一致.
// 分组, 简称, 列别名和 500 行 / 100 列截断都已经反映在传入的 data 里, 这里不再重算.

import type { PivotTableDataResponse, PivotTableRow } from "../../types/chartData"
import { groupCrossTabRows } from "../../utils/groupCrossTabRows"

export const PIVOT_TRUNCATED_NOTICE =
  "数据超过交叉表上限，当前仅展示前 500 行、100 列，请增加筛选条件后查看。"
export const PIVOT_EXACT_TOTAL_NOTICE =
  "合计按全部筛选结果重新计算；同一知识跨组出现时只计一次，合计可能不等于各项相加。"
export const PIVOT_EMPTY_NOTICE = "当前图表无数据"

export interface PivotHeaderCell {
  label: string
  path: string[]
  colSpan: number
}

export interface PivotSheetMerge {
  row: number
  column: number
  rowSpan: number
  columnSpan: number
}

export interface VisiblePivotSheet {
  hasTable: boolean
  rows: (string | number | null)[][]
  merges: PivotSheetMerge[]
}

type DisplayRow =
  | { kind: "subtotal"; groupLabel: string; values: number[]; total: number; childRows: PivotTableRow[] }
  | { kind: "child"; row: PivotTableRow }

const sheets = new Map<string, VisiblePivotSheet>()

export function publishVisiblePivotSheet(componentId: string, sheet: VisiblePivotSheet | null) {
  if (!componentId) return
  if (sheet) sheets.set(componentId, sheet)
  else sheets.delete(componentId)
}

export function readVisiblePivotSheet(componentId: string): VisiblePivotSheet | null {
  return sheets.get(componentId) ?? null
}

export function emptyVisiblePivotSheet(notice = PIVOT_EMPTY_NOTICE): VisiblePivotSheet {
  return { hasTable: false, rows: [[notice]], merges: [] }
}

export function buildHeaderRows(columnPaths: string[][]): PivotHeaderCell[][] {
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

function rowIdentity(row: PivotTableRow) {
  return row.id ?? JSON.stringify(row.key)
}

function displayRowsOf(data: PivotTableDataResponse): DisplayRow[] {
  const groups = groupCrossTabRows(data.rows, data.groupDimensionIndex ?? null, data.groupTotals)
  if (!groups) return data.rows.map(row => ({ kind: "child", row }))
  return groups.flatMap(group => [
    {
      kind: "subtotal" as const,
      groupLabel: group.groupLabel,
      values: group.subtotalRow.values,
      total: group.subtotalRow.total,
      childRows: group.childRows,
    },
    ...group.childRows.map(row => ({ kind: "child" as const, row })),
  ])
}

function pad(row: (string | number | null)[], width: number) {
  while (row.length < width) row.push(null)
  return row
}

export function buildVisiblePivotSheet(data: PivotTableDataResponse): VisiblePivotSheet {
  const columnPaths = data.columnPaths?.length === data.columns.length
    ? data.columnPaths
    : data.columns.map(column => [column])
  const headerRows = buildHeaderRows(columnPaths)
  const headerDepth = headerRows.length
  const rowHeaderCount = data.rowHeaders.length
  const valueCount = columnPaths.length
  const width = 1 + rowHeaderCount + valueCount + 1
  const totalColumn = width - 1
  const rows: (string | number | null)[][] = []
  const merges: PivotSheetMerge[] = []
  const notices = [
    data.exactDocumentTotals ? PIVOT_EXACT_TOTAL_NOTICE : "",
    data.truncated ? PIVOT_TRUNCATED_NOTICE : "",
  ].filter(Boolean)

  notices.forEach(notice => {
    const rowIndex = rows.length
    rows.push(pad([notice], width))
    if (width > 1) merges.push({ row: rowIndex, column: 0, rowSpan: 1, columnSpan: width })
  })

  const headerStart = rows.length
  for (let level = 0; level < headerDepth; level += 1) rows.push(pad([], width))
  rows[headerStart][0] = "序号"
  if (headerDepth > 1) merges.push({ row: headerStart, column: 0, rowSpan: headerDepth, columnSpan: 1 })
  data.rowHeaders.forEach((header, index) => {
    rows[headerStart][1 + index] = header
    if (headerDepth > 1) {
      merges.push({ row: headerStart, column: 1 + index, rowSpan: headerDepth, columnSpan: 1 })
    }
  })
  headerRows.forEach((headerRow, level) => {
    let columnIndex = 0
    headerRow.forEach(cell => {
      const column = 1 + rowHeaderCount + columnIndex
      rows[headerStart + level][column] = cell.label
      if (cell.colSpan > 1) {
        merges.push({ row: headerStart + level, column, rowSpan: 1, columnSpan: cell.colSpan })
      }
      columnIndex += cell.colSpan
    })
  })
  rows[headerStart][totalColumn] = "合计"
  if (headerDepth > 1) {
    merges.push({ row: headerStart, column: totalColumn, rowSpan: headerDepth, columnSpan: 1 })
  }

  const groupDimensionIndex = data.groupDimensionIndex ?? null
  displayRowsOf(data).forEach((entry, rowIndex) => {
    const excelRow = pad([], width)
    const excelRowIndex = rows.length
    excelRow[0] = rowIndex + 1
    if (entry.kind === "subtotal") {
      const groupIndex = groupDimensionIndex ?? 0
      const firstRow = entry.childRows[0]
      const labels = data.rowLabels?.[rowIdentity(firstRow)]
      excelRow[1 + groupIndex] = labels?.[groupIndex] || entry.groupLabel || "未分类"
      const span = entry.childRows.length + 1
      if (span > 1) {
        merges.push({ row: excelRowIndex, column: 1 + groupIndex, rowSpan: span, columnSpan: 1 })
      }
      const remaining = Math.max(0, rowHeaderCount - (groupIndex + 1))
      if (remaining > 0) {
        excelRow[2 + groupIndex] = "汇总"
        if (remaining > 1) {
          merges.push({ row: excelRowIndex, column: 2 + groupIndex, rowSpan: 1, columnSpan: remaining })
        }
      }
      entry.values.forEach((value, columnIndex) => {
        excelRow[1 + rowHeaderCount + columnIndex] = value
      })
      excelRow[totalColumn] = entry.total
    } else {
      const labels = data.rowLabels?.[rowIdentity(entry.row)]
      entry.row.key.forEach((label, dimensionIndex) => {
        if (dimensionIndex === groupDimensionIndex) return
        excelRow[1 + dimensionIndex] = (labels?.[dimensionIndex] ?? label) || "未分类"
      })
      entry.row.values.forEach((value, columnIndex) => {
        excelRow[1 + rowHeaderCount + columnIndex] = value
      })
      excelRow[totalColumn] = entry.row.total
    }
    rows.push(excelRow)
  })

  const footerIndex = rows.length
  const footer = pad(["合计"], width)
  const footerSpan = Math.max(1, rowHeaderCount + 1)
  if (footerSpan > 1) merges.push({ row: footerIndex, column: 0, rowSpan: 1, columnSpan: footerSpan })
  data.columnTotals.forEach((value, index) => {
    footer[1 + rowHeaderCount + index] = value
  })
  footer[totalColumn] = data.grandTotal
  rows.push(footer)
  return { hasTable: true, rows, merges }
}
