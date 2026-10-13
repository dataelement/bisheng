import { describe, expect, it } from "vitest"
import { generateChartOption } from "../pages/Dashboard/components/charts/BaseChart"
import type { ComponentStyleConfig, DataConfig } from "../pages/Dashboard/types/dataConfig"

describe("收藏图表缺失样式回归", () => {
  it.each(["bar", "horizontal-bar"])("%s 只有标题时仍保留收藏数据", (chartType) => {
    const option = generateChartOption({
      chartType: chartType as any,
      data: { dimensions: ["公共库", "部门库"], series: [{ name: "收藏次数", data: [4, 2] }] },
      dataConfig: { dimensions: [{ fieldId: "space_level_name" }], metrics: [], filters: [] } as DataConfig,
      styleConfig: { title: "收藏量", xAxisAlign: "right", yAxisAlign: "left" } as ComponentStyleConfig,
      containerSize: [720, 350],
    })
    expect(option.series[0].data).toEqual([4, 2])
    expect(option.xAxis.nameTextStyle.padding.every(Number.isFinite)).toBe(true)
    expect(option.yAxis.nameTextStyle.padding.every(Number.isFinite)).toBe(true)
  })
})
