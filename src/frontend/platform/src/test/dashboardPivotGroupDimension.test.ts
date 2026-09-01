import { describe, expect, it } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { ChartType, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"

// F058 AC-12/AC-13: transformPivotData must resolve and expose groupDimensionIndex so
// PivotTable can rowSpan-merge the finest actively-filtered org-hierarchy row dimension.

function makeComponent(fieldIds: string[]): DashboardComponent {
  return {
    id: "pivot-1",
    dashboard_id: "dashboard-1",
    title: "交叉表",
    type: ChartType.PivotTable,
    dataset_code: "mid_knowledge_space_content_stat",
    data_config: {
      dimensions: fieldIds.map(fieldId => ({ fieldId, displayName: fieldId })),
      metrics: [{ fieldId: "file_count", displayName: "文件数" }],
    } as any,
    style_config: {} as any,
    create_time: "",
    update_time: "",
  }
}

describe("transformPivotData groupDimensionIndex (F058)", () => {
  it("resolves the group index when a row dimension is actively filtered", () => {
    const component = makeComponent(["belonging_department_name", "belonging_office_name"])
    const resData = {
      dimensions: [["生产制造部", "轧钢科室"], ["生产制造部", "炼钢科室"]],
      value: [[10], [5]],
    }

    const result = transformPivotData(resData, component, [
      { fieldId: "belonging_department_name", values: ["生产制造部"] },
    ])

    expect(result.groupDimensionIndex).toBe(0)
  })

  it("is null when no row dimension is actively filtered", () => {
    const component = makeComponent(["belonging_department_name", "belonging_office_name"])
    const resData = {
      dimensions: [["生产制造部", "轧钢科室"]],
      value: [[10]],
    }

    const result = transformPivotData(resData, component, [])

    expect(result.groupDimensionIndex).toBeNull()
  })

  it("is null when the finest filtered level is the last row dimension (AC-13 boundary)", () => {
    const component = makeComponent(["belonging_office_name", "belonging_squad_name"])
    const resData = {
      dimensions: [["轧钢科室", "甲班"]],
      value: [[10]],
    }

    const result = transformPivotData(resData, component, [
      { fieldId: "belonging_office_name", values: ["轧钢科室"] },
      { fieldId: "belonging_squad_name", values: ["甲班"] },
    ])

    expect(result.groupDimensionIndex).toBeNull()
  })

  it("merges uploader_user_name with uploader_department_name into one cell (AC-11)", () => {
    const component = makeComponent(["uploader_department_name", "uploader_user_name"])
    const resData = {
      dimensions: [["生产制造部", "张三"], ["安全环保监察部", "张三"]],
      value: [[10], [5]],
    }

    const result = transformPivotData(resData, component, [])

    expect(result.rowHeaders).toEqual(["uploader_user_name"])
    const rowsByValue = result.rows.map((row: any) => row.key)
    expect(rowsByValue).toContainEqual(["张三(生产制造部)"])
    expect(rowsByValue).toContainEqual(["张三(安全环保监察部)"])
  })

  it("does not merge when only the person field is configured (no query injection)", () => {
    const component = makeComponent(["uploader_user_name"])
    const resData = { dimensions: [["张三"]], value: [[10]] }

    const result = transformPivotData(resData, component, [])

    expect(result.rowHeaders).toEqual(["uploader_user_name"])
    expect(result.rows[0].key).toEqual(["张三"])
  })

  it("defaults dimensionFilters to empty and does not throw when omitted", () => {
    const component = makeComponent(["belonging_department_name"])
    const resData = { dimensions: [["生产制造部"]], value: [[10]] }

    expect(() => transformPivotData(resData, component)).not.toThrow()
  })
})
