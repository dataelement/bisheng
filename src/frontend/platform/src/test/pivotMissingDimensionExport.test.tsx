import { fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { PivotTable } from "@/pages/Dashboard/components/charts/PivotTable"
import { DashboardComponent, DataConfig } from "@/pages/Dashboard/types/dataConfig"

const { exportDetail } = vi.hoisted(() => ({ exportDetail: vi.fn() }))
vi.mock("@/pages/Dashboard/components/export/useComponentExport", () => ({
  useComponentExport: () => ({ exportDetail, isExportingDetail: () => false, canExport: true }),
}))

describe("交叉表缺失维度导出", () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([false, true])("保留空值、真实未分类名称和空字符串的独立明细（分组=%s）", grouped => {
    const field = "uploader_department_name"
    const rawValues = [null, "未分类", "", 0]
    const dimensions = grouped ? [field, "uploader_office_name"] : [field]
    const component = {
      data_config: {
        dimensions: dimensions.map(fieldId => ({ fieldId })),
        stackDimension: { fieldId: "space_level_name" },
        metrics: [{ fieldId: "total_file_count" }],
      },
    } as DashboardComponent
    const rollup = (indexes: number[], rows: { dimensions: unknown[], value: number }[]) => ({
      metric_index: 0, dimension_indexes: indexes, rows,
    })
    const columnIndex = dimensions.length
    const data = transformPivotData({
      dimensions: rawValues.map(value => grouped ? [value, "甲科室", "公共库"] : [value, "公共库"]),
      value: [[2], [3], [4], [5]],
      rollups: [
        rollup([], [{ dimensions: [], value: 14 }]),
        rollup(dimensions.map((_, index) => index), rawValues.map((value, index) => ({
          dimensions: grouped ? [value, "甲科室"] : [value], value: index + 2,
        }))),
        rollup([columnIndex], [{ dimensions: ["公共库"], value: 14 }]),
        ...(grouped ? [
          rollup([0], rawValues.map((value, index) => ({ dimensions: [value], value: index + 2 }))),
          rollup([0, columnIndex], rawValues.map((value, index) => ({ dimensions: [value, "公共库"], value: index + 2 }))),
        ] : []),
      ],
    }, component, grouped ? [{ fieldId: field, values: rawValues }] : [])

    expect(data.rows).toHaveLength(4)
    expect(data.rows.map(row => row.total)).toEqual([2, 3, 4, 5])
    render(<PivotTable data={data} dataConfig={component.data_config as DataConfig} isDark={false} />)
    const rows = within(screen.getByRole("table")).getAllByRole("row")
    rawValues.forEach((value, index) => {
      const row = rows[1 + index * (grouped ? 2 : 1)]
      const label = value === null || value === "" ? "未分类" : String(value)
      fireEvent.click(within(row).getByText(label))
      expect(exportDetail).toHaveBeenLastCalledWith(field, value)
      const cells = within(row).getAllByRole("cell")
      expect(cells[cells.length - 1]).toHaveTextContent(String(index + 2))
    })
  })

  it("列维度的空值和真实未分类名称分别保留数值及服务端合计", () => {
    const component = {
      data_config: {
        dimensions: [{ fieldId: "uploader_department_name" }],
        stackDimension: { fieldId: "space_level_name" },
        metrics: [{ fieldId: "total_file_count" }],
      },
    } as DashboardComponent
    const data = transformPivotData({
      dimensions: [["生产部", null], ["生产部", "未分类"]], value: [[2], [3]],
      rollups: [
        { metric_index: 0, dimension_indexes: [], rows: [{ dimensions: [], value: 5 }] },
        { metric_index: 0, dimension_indexes: [0], rows: [{ dimensions: ["生产部"], value: 5 }] },
        { metric_index: 0, dimension_indexes: [1], rows: [
          { dimensions: [null], value: 2 }, { dimensions: ["未分类"], value: 3 },
        ] },
      ],
    }, component)
    expect(data.rows[0].values).toEqual([2, 3])
    expect(data.columnTotals).toEqual([2, 3])
    expect(data.grandTotal).toBe(5)
  })
})
