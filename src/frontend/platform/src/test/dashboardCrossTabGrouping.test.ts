import { describe, expect, it } from "vitest"

import {
  groupCrossTabRows,
  mergePersonDedupValues,
  resolveGroupDimensionIndex,
  resolvePersonDedupIndices,
} from "@/pages/Dashboard/utils/groupCrossTabRows"

// F058 AC-12/AC-13: cross-tab rows group by the finest actively-filtered org-hierarchy
// dimension; boundary case is "filtered down to 班组" (no next level) -> stay flat.

describe("resolveGroupDimensionIndex", () => {
  it("groups by department when department is actively filtered and office is not", () => {
    const rowFieldIds = ["belonging_department_name", "belonging_office_name"]
    const filters = [{ fieldId: "belonging_department_name", values: ["生产制造部"] }]

    expect(resolveGroupDimensionIndex(rowFieldIds, filters)).toBe(0)
  })

  it("groups by office (not department) when both are actively filtered — picks the finest level", () => {
    const rowFieldIds = ["belonging_department_name", "belonging_office_name", "belonging_squad_name"]
    const filters = [
      { fieldId: "belonging_department_name", values: ["生产制造部"] },
      { fieldId: "belonging_office_name", values: ["轧钢科室"] },
    ]

    expect(resolveGroupDimensionIndex(rowFieldIds, filters)).toBe(1)
  })

  it("returns null when the finest filtered level (班组/squad) has no next row dimension to nest", () => {
    const rowFieldIds = ["belonging_office_name", "belonging_squad_name"]
    const filters = [
      { fieldId: "belonging_office_name", values: ["轧钢科室"] },
      { fieldId: "belonging_squad_name", values: ["甲班"] },
    ]

    expect(resolveGroupDimensionIndex(rowFieldIds, filters)).toBeNull()
  })

  it("returns null when no org-hierarchy dimension has an active filter value", () => {
    const rowFieldIds = ["belonging_department_name", "belonging_office_name"]
    expect(resolveGroupDimensionIndex(rowFieldIds, [])).toBeNull()
    expect(
      resolveGroupDimensionIndex(rowFieldIds, [{ fieldId: "belonging_department_name", values: [] }]),
    ).toBeNull()
  })

  it("ignores non-org-hierarchy row dimensions and filters", () => {
    const rowFieldIds = ["file_category_name", "belonging_department_name", "belonging_office_name"]
    const filters = [
      { fieldId: "file_category_name", values: ["标准文档"] },
      { fieldId: "belonging_department_name", values: ["生产制造部"] },
    ]

    expect(resolveGroupDimensionIndex(rowFieldIds, filters)).toBe(1)
  })

  it("recognizes uploader_* fields with the same level ordering as belonging_*", () => {
    const rowFieldIds = ["uploader_department_name", "uploader_office_name"]
    const filters = [{ fieldId: "uploader_department_name", values: ["生产制造部"] }]

    expect(resolveGroupDimensionIndex(rowFieldIds, filters)).toBe(0)
  })
})

describe("groupCrossTabRows", () => {
  it("returns null (flat rendering) when groupDimensionIndex is null", () => {
    const rows = [{ key: ["生产制造部", "轧钢科室"], values: [10], total: 10 }]
    expect(groupCrossTabRows(rows, null)).toBeNull()
  })

  it("groups rows sharing the same value at the group dimension index, preserving row order within a group", () => {
    const rows = [
      { key: ["生产制造部", "轧钢科室"], values: [10], total: 10 },
      { key: ["生产制造部", "炼钢科室"], values: [5], total: 5 },
      { key: ["安全环保监察部", "监察科室"], values: [3], total: 3 },
    ]

    const grouped = groupCrossTabRows(rows, 0)

    expect(grouped).toEqual([
      {
        groupKey: "生产制造部",
        groupLabel: "生产制造部",
        childRows: [rows[0], rows[1]],
        subtotalRow: { groupLabel: "生产制造部", values: [15], total: 15 },
      },
      {
        groupKey: "安全环保监察部",
        groupLabel: "安全环保监察部",
        childRows: [rows[2]],
        subtotalRow: { groupLabel: "安全环保监察部", values: [3], total: 3 },
      },
    ])
  })

  it("sums each column across the group's child rows for the subtotal row", () => {
    const rows = [
      { key: ["生产制造部", "轧钢科室"], values: [10, 1], total: 11 },
      { key: ["生产制造部", "炼钢科室"], values: [5, 2], total: 7 },
    ]

    const grouped = groupCrossTabRows(rows, 0)

    expect(grouped?.[0].subtotalRow).toEqual({ groupLabel: "生产制造部", values: [15, 3], total: 18 })
  })

  it("falls back to 未分类 when the group dimension value is missing", () => {
    const rows = [{ key: [], values: [1], total: 1 }]
    const grouped = groupCrossTabRows(rows, 0)
    expect(grouped?.[0].groupLabel).toBe("未分类")
  })
})

// F058 AC-11: 上传人姓名 + 上传人部门 merge into one cell to disambiguate same-named
// uploaders across departments — only when both are actually configured row dimensions.
describe("resolvePersonDedupIndices", () => {
  it("finds the pair when both uploader_user_name and uploader_department_name are configured", () => {
    const rowFieldIds = ["uploader_department_name", "uploader_user_name", "file_category_name"]
    expect(resolvePersonDedupIndices(rowFieldIds)).toEqual({ personIndex: 1, deptIndex: 0 })
  })

  it("returns null when only the person field is configured (no silent query injection)", () => {
    const rowFieldIds = ["uploader_user_name", "file_category_name"]
    expect(resolvePersonDedupIndices(rowFieldIds)).toBeNull()
  })

  it("returns null when neither field is configured", () => {
    expect(resolvePersonDedupIndices(["belonging_department_name"])).toBeNull()
  })
})

describe("mergePersonDedupValues", () => {
  it("merges the department value into the person cell and drops the department entry", () => {
    const values = ["生产制造部", "张三", "标准文档"]
    expect(mergePersonDedupValues(values, 1, 0)).toEqual(["张三(生产制造部)", "标准文档"])
  })

  it("falls back to 未分类 when the department value is missing", () => {
    const values = ["", "张三"]
    expect(mergePersonDedupValues(values, 1, 0)).toEqual(["张三(未分类)"])
  })
})
