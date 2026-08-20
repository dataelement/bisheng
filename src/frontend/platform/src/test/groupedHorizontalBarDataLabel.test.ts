import { describe, expect, it } from "vitest"
import { generateChartOption } from "../pages/Dashboard/components/charts/BaseChart"
import {
  ChartType,
  ComponentStyleConfig,
} from "../pages/Dashboard/types/dataConfig"

describe("grouped horizontal bar data labels", () => {
  it("places values at the end of each bar instead of above it", () => {
    const option = generateChartOption({
      data: {
        dimensions: ["部门库", "公共库"],
        series: [
          { name: "总文件数", data: [3283, 1023] },
          { name: "新增文件数", data: [120, 80] },
        ],
      },
      chartType: ChartType.GroupedHorizontalBar,
      styleConfig: {
        showDataLabel: true,
        showLegend: false,
        xAxisTitle: "",
        yAxisTitle: "",
        xAxisFontSize: 12,
        yAxisFontSize: 12,
      } as ComponentStyleConfig,
    })

    expect(option.series.map(series => series.label.position)).toEqual([
      "right",
      "right",
    ])
  })
})
