import { describe, expect, it } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { DashboardComponent } from "@/pages/Dashboard/types/dataConfig"
import { groupCrossTabRows } from "@/pages/Dashboard/utils/groupCrossTabRows"

const component = {
  data_config: {
    dimensions: [{ fieldId: "uploader_department_name" }, { fieldId: "uploader_office_name" }],
    stackDimensions: [{ fieldId: "timestamp" }],
    metrics: [{ fieldId: "total_file_count" }],
  },
} as DashboardComponent

function rollup(indexes: number[], rows: [unknown[], number][]) {
  return { metric_index: 0, dimension_indexes: indexes, rows: rows.map(([dimensions, value]) => ({ dimensions, value })) }
}

describe("文档统计合计", () => {
  it("跨组织及跨月份重复出现时采用服务端去重合计", () => {
    const result = transformPivotData({
      dimensions: [["A", "甲", "8月"], ["A", "甲", "9月"], ["A", "乙", "9月"]],
      value: [[1], [1], [1]],
      rollups: [
        rollup([], [[[], 1]]),
        rollup([0, 1], [[["A", "甲"], 1], [["A", "乙"], 1]]),
        rollup([2], [[["8月"], 1], [["9月"], 1]]),
        rollup([0], [[["A"], 1]]),
        rollup([0, 2], [[["A", "8月"], 1], [["A", "9月"], 1]]),
      ],
    }, component, [{ fieldId: "uploader_department_name", values: ["A"] }])
    expect(result.rows.map(row => row.total)).toEqual([1, 1])
    expect(result.columnTotals).toEqual([1, 1])
    expect(result.grandTotal).toBe(1)
    const groups = groupCrossTabRows(result.rows, result.groupDimensionIndex, result.groupTotals)
    expect(groups?.[0].subtotalRow).toEqual({ groupLabel: "A", values: [1, 1], total: 1 })
  })

  it("合计不受展示行数截断影响，比例使用整体分子分母计算", () => {
    const result = transformPivotData({
      dimensions: [["A", "甲", "9月"]], value: [[1]],
      rollups: [rollup([], [[[], 0.5]]), rollup([0, 1], [[["A", "甲"], 1]]), rollup([2], [[["9月"], 0.5]])],
    }, component)
    expect(result.grandTotal).toBe(0.5)
    expect(result.columnTotals).toEqual([0.5])
  })

  it("其他数据集没有去重合计时保持相加行为", () => {
    const result = transformPivotData({
      dimensions: [["A", "甲", "8月"], ["A", "甲", "9月"]], value: [[2], [3]],
    }, component)
    expect(result.rows[0].total).toBe(5)
    expect(result.grandTotal).toBe(5)
  })
})
