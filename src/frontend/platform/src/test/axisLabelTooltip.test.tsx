import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  BaseChart,
  formatCategoryAxisLabel,
  generateChartOption,
  getTruncatedAxisLabelText,
} from "../pages/Dashboard/components/charts/BaseChart"
import {
  ChartType,
  ComponentStyleConfig,
} from "../pages/Dashboard/types/dataConfig"

describe("dashboard category axis label tooltip", () => {
  afterEach(() => {
    cleanup()
    delete (window as any).echarts
    vi.unstubAllGlobals()
  })

  it("keeps the full name available when the category label is truncated", () => {
    const fullName = "测试部门10-子部门名称"

    expect(formatCategoryAxisLabel(fullName)).toBe("测试部门10-子部门...")
    expect(getTruncatedAxisLabelText({
      componentType: "yAxis",
      targetType: "axisLabel",
      value: fullName,
    })).toBe(fullName)
    expect(getTruncatedAxisLabelText({
      componentType: "yAxis",
      targetType: "axisLabel",
      value: "测试部门",
    })).toBeNull()
  })

  it("enables axis label events for a horizontal chart", () => {
    const option = generateChartOption({
      data: {
        dimensions: ["测试部门10-子部门名称"],
        series: [{ name: "预览次数", data: [30] }],
      },
      chartType: ChartType.HorizontalBar,
      styleConfig: {
        xAxisTitle: "",
        yAxisTitle: "",
        xAxisFontSize: 12,
        yAxisFontSize: 12,
      } as ComponentStyleConfig,
    })

    expect(option.yAxis.triggerEvent).toBe(true)
    expect(option.yAxis.axisLabel.formatter("测试部门10-子部门名称"))
      .toBe("测试部门10-子部门...")
  })

  it("shows the full name while hovering a truncated axis label", async () => {
    const handlers: Record<string, (params: any) => void> = {}
    const chart = {
      dispose: vi.fn(),
      on: vi.fn((eventName: string, handler: (params: any) => void) => {
        handlers[eventName] = handler
      }),
      resize: vi.fn(),
      setOption: vi.fn(),
    }
    ;(window as any).echarts = {
      init: vi.fn(() => chart),
      registerTheme: vi.fn(),
    }
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    })

    render(
      <BaseChart
        isDark={false}
        data={{
          dimensions: ["测试部门10-子部门名称"],
          series: [{ name: "预览次数", data: [30] }],
        }}
        chartType={ChartType.HorizontalBar}
        styleConfig={{
          xAxisTitle: "",
          yAxisTitle: "",
          xAxisFontSize: 12,
          yAxisFontSize: 12,
        } as ComponentStyleConfig}
      />,
    )

    await waitFor(() => expect(chart.on).toHaveBeenCalledTimes(2))

    act(() => {
      handlers.mouseover({
        componentType: "yAxis",
        targetType: "axisLabel",
        value: "测试部门10-子部门名称",
        event: { offsetX: 30, offsetY: 40 },
      })
    })
    expect(screen.getByText("测试部门10-子部门名称")).toBeInTheDocument()

    act(() => handlers.mouseout({}))
    expect(screen.queryByText("测试部门10-子部门名称")).not.toBeInTheDocument()
  })
})
