import { describe, expect, it } from "vitest"
import { generateChartOption } from "../pages/Dashboard/components/charts/BaseChart"
import { ChartType, ComponentStyleConfig } from "../pages/Dashboard/types/dataConfig"
import { displayJoinedDimension, organizationDisplayName } from "../pages/Dashboard/utils/organizationLabels"

const FULL_DEPARTMENT = "北京首钢股份有限公司制造部"
const FULL_COMPANY = "北京首钢股份有限公司"

describe("dashboard organization short names", () => {
  it("uses the short name and falls back to the original text", () => {
    const labels = {
      belonging_department_name: { [FULL_DEPARTMENT]: "制造部" },
      belonging_company_name: { [FULL_COMPANY]: "" },
    }

    expect(organizationDisplayName(labels, "belonging_department_name", FULL_DEPARTMENT)).toBe("制造部")
    expect(organizationDisplayName(labels, "belonging_company_name", FULL_COMPANY)).toBe("")
    expect(organizationDisplayName(labels, "belonging_office_name", "安全管理室")).toBe("安全管理室")
    expect(displayJoinedDimension(
      `${FULL_COMPANY}\n${FULL_DEPARTMENT}`,
      ["belonging_company_name", "belonging_department_name"],
      { belonging_department_name: { [FULL_DEPARTMENT]: "制造部" } },
    )).toBe(`${FULL_COMPANY}\n制造部`)
  })

  it("shows the department short name on the axis while keeping the full name for click export", () => {
    const option = generateChartOption({
      data: {
        dimensions: [FULL_DEPARTMENT],
        series: [{ name: "文件数", data: [3] }],
        dimensionLabels: { belonging_department_name: { [FULL_DEPARTMENT]: "制造部" } },
        categoryFieldIds: ["belonging_department_name"],
      },
      chartType: ChartType.Bar,
      styleConfig: {
        xAxisTitle: "",
        yAxisTitle: "",
      } as ComponentStyleConfig,
    })

    expect(option.xAxis.data).toEqual([FULL_DEPARTMENT])
    expect(option.xAxis.axisLabel.formatter(FULL_DEPARTMENT)).toBe("制造部")
  })

  it("shows company and department short names on a stacked chart without changing series data names", () => {
    const option = generateChartOption({
      data: {
        dimensions: [FULL_COMPANY],
        series: [{ name: FULL_DEPARTMENT, data: [3] }],
        dimensionLabels: {
          belonging_company_name: { [FULL_COMPANY]: "股份" },
          belonging_department_name: { [FULL_DEPARTMENT]: "制造部" },
        },
        categoryFieldIds: ["belonging_company_name"],
        seriesFieldId: "belonging_department_name",
      },
      chartType: ChartType.StackedBar,
      dataConfig: {
        dimensions: [{ fieldId: "belonging_company_name" }],
        metrics: [],
      } as never,
      styleConfig: {
        showLegend: true,
        xAxisTitle: "",
        yAxisTitle: "",
      } as ComponentStyleConfig,
    })

    expect(option.xAxis.data).toEqual([FULL_COMPANY])
    expect(option.xAxis.axisLabel.formatter(FULL_COMPANY)).toBe("股份")
    expect(option.series[0].name).toBe(FULL_DEPARTMENT)
    expect(option.legend.formatter(FULL_DEPARTMENT)).toBe("制造部")
  })
})
