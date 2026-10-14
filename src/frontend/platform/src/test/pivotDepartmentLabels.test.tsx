import { fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { PivotTable } from "@/pages/Dashboard/components/charts/PivotTable"
import { ChartType, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"

const { exportDetail } = vi.hoisted(() => ({ exportDetail: vi.fn() }))
vi.mock("@/pages/Dashboard/components/export/useComponentExport", () => ({
  useComponentExport: () => ({ exportDetail, isExportingDetail: () => false, canExport: true }),
}))

const component = {
  type: ChartType.PivotTable,
  data_config: {
    dimensions: [{ fieldId: "uploader_department_name", fieldName: "上传人部门" }],
    stackDimension: { fieldId: "space_level_name", fieldName: "知识库大类" },
    metrics: [{ fieldId: "count", fieldName: "文档数" }],
  },
} as DashboardComponent

describe("pivot department display names", () => {
  beforeEach(() => vi.clearAllMocks())
  it("shows short names and fallback names while keeping same-short-name rows and raw export values", () => {
    const names = ["北京首钢生产一部", "北京首钢生产二部", "安全环保监察部"]
    const data = transformPivotData({
      dimensions: names.map(name => [name, "公共库"]),
      value: [[1], [2], [3]],
      dimension_labels: { uploader_department_name: {
        [names[0]]: "生产部", [names[1]]: "生产部", [names[2]]: names[2],
      } },
    }, component)
    expect(data.rows.map(row => row.key)).toEqual(names.map(name => [name]))
    expect(data.grandTotal).toBe(6)
    render(<PivotTable data={data} dataConfig={component.data_config} isDark={false} />)
    const rows = within(screen.getByRole("table")).getAllByRole("row")
    expect(within(rows[1]).getByText("生产部")).toBeInTheDocument()
    expect(within(rows[2]).getByText("生产部")).toBeInTheDocument()
    expect(within(rows[3]).getByText(names[2])).toBeInTheDocument()
    fireEvent.click(within(rows[1]).getByText("生产部"))
    expect(exportDetail).toHaveBeenCalledWith("uploader_department_name", names[0])
  })

  it.each(["group", "person"])("uses short names in %s rows while keeping original grouping", mode => {
    const department = "北京首钢生产制造部"
    const dimensions = mode === "group"
      ? ["uploader_department_name", "uploader_office_name"]
      : ["uploader_user_name", "uploader_department_name"]
    const groupedComponent = {
      ...component,
      data_config: {
        ...component.data_config,
        dimensions: dimensions.map(fieldId => ({ fieldId, fieldName: fieldId })),
      },
    } as DashboardComponent
    const data = transformPivotData({
      dimensions: mode === "group"
        ? [[department, "轧钢科室", "公共库"]]
        : [["张三", department, "公共库"]],
      value: [[2]],
      dimension_labels: { uploader_department_name: { [department]: "生产部" } },
    }, groupedComponent, mode === "group" ? [{ fieldId: dimensions[0], values: [department] }] : [])
    render(<PivotTable data={data} dataConfig={groupedComponent.data_config} isDark={false} />)
    const text = mode === "group" ? "生产部" : "张三(生产部)"
    expect(screen.getByText(text)).toBeInTheDocument()
    if (mode === "group") {
      fireEvent.click(screen.getByText(text))
      expect(exportDetail).toHaveBeenCalledWith(dimensions[0], department)
    }
  })
})
