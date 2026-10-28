import { describe, expect, it } from "vitest"

import type { PivotTableDataResponse } from "@/pages/Dashboard/types/chartData"
import {
  PIVOT_EXACT_TOTAL_NOTICE,
  PIVOT_TRUNCATED_NOTICE,
  buildVisiblePivotSheet,
} from "@/pages/Dashboard/components/charts/visiblePivotSheet"
import { dimensionValueKey } from "@/pages/Dashboard/utils/documentRollups"

const grouped = {
  rowHeaders: ["部门", "科室"],
  columnHeader: "分类",
  columnHeaders: ["分类"],
  metricName: "文件数",
  columns: ["制度", "报告", "制度"],
  columnPaths: [["生产", "制度"], ["生产", "报告"], ["研发", "制度"]],
  rows: [
    { id: "a", key: ["生产部", "炼钢"], rawKey: ["生产技术部", "炼钢"], values: [2, 0, 1], total: 3 },
    { id: "b", key: ["生产部", "轧钢"], rawKey: ["生产技术部", "轧钢"], values: [1, 4, 0], total: 5 },
  ],
  rowLabels: { a: ["生产部", "炼钢科"], b: ["生产部", "轧钢科"] },
  columnTotals: [3, 4, 1],
  grandTotal: 9,
  groupDimensionIndex: 0,
  groupTotals: { [dimensionValueKey(["生产技术部"])]: { values: [10, 20, 30], total: 60 } },
  exactDocumentTotals: true,
  truncated: true,
} as PivotTableDataResponse

describe("buildVisiblePivotSheet", () => {
  it("reproduces the grouped table the user sees, including notices, labels and numeric zeros", () => {
    const sheet = buildVisiblePivotSheet(grouped)

    expect(sheet.hasTable).toBe(true)
    expect(sheet.rows[0][0]).toBe(PIVOT_EXACT_TOTAL_NOTICE)
    expect(sheet.rows[1][0]).toBe(PIVOT_TRUNCATED_NOTICE)
    expect(sheet.rows[2]).toEqual(["序号", "部门", "科室", "生产", null, "研发", "合计"])
    expect(sheet.rows[3]).toEqual([null, null, null, "制度", "报告", "制度", null])
    expect(sheet.rows[4]).toEqual([1, "生产部", "汇总", 10, 20, 30, 60])
    expect(sheet.rows[5]).toEqual([2, null, "炼钢科", 2, 0, 1, 3])
    expect(sheet.rows[6]).toEqual([3, null, "轧钢科", 1, 4, 0, 5])
    expect(sheet.rows[7]).toEqual(["合计", null, null, 3, 4, 1, 9])
    expect(sheet.merges).toContainEqual({ row: 4, column: 1, rowSpan: 3, columnSpan: 1 })
    expect(sheet.merges).toContainEqual({ row: 2, column: 3, rowSpan: 1, columnSpan: 2 })
  })

  it("keeps a flat table on one header row when there is no column grouping", () => {
    const sheet = buildVisiblePivotSheet({
      rowHeaders: ["上传人"],
      columnHeader: "",
      metricName: "文件数",
      columns: ["未分类"],
      rows: [{ id: "u", key: ["张三"], values: [4], total: 4 }],
      rowLabels: { u: ["张三(生产部)"] },
      columnTotals: [4],
      grandTotal: 4,
      groupDimensionIndex: null,
    })

    expect(sheet.rows).toEqual([
      ["序号", "上传人", "未分类", "合计"],
      [1, "张三(生产部)", 4, 4],
      ["合计", null, 4, 4],
    ])
  })
})
