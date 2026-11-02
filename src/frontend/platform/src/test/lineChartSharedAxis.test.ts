import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import zhDashboard from "../../public/locales/zh-Hans/dashboard.json"
import { generateChartOption } from "@/pages/Dashboard/components/charts/BaseChart"
import {
  canAddLineMetric,
  canChangeLineMetricFormat,
  maxCategoryDimensions,
  maxSharedLineMetrics,
} from "@/pages/Dashboard/components/config/lineAxisRules"
import { useChartState } from "@/pages/Dashboard/components/config/useChartState"
import { ChartType, ComponentStyleConfig, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"

const { toastMock } = vi.hoisted(() => ({
  toastMock: vi.fn(),
}))

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ toast: toastMock }),
}))

vi.mock("@/store/dashboardStore", () => ({
  useComponentEditorStore: () => ({ updateEditingComponent: vi.fn() }),
  useEditorDashboardStore: (selector?: (state: { refreshChart: () => void }) => unknown) => {
    const state = { refreshChart: vi.fn(), savedDashboard: null, chartRefreshTriggers: {} }
    return selector ? selector(state) : state
  },
}))

const numberFormat = (type: "number" | "percent" | "duration" | "storage") => ({
  type,
  decimalPlaces: 0,
  thousandSeparator: type === "number",
})

function metric(fieldId: string, type: "number" | "percent" | "duration" | "storage", extra: Record<string, unknown> = {}) {
  return {
    fieldId,
    fieldName: fieldId,
    fieldCode: fieldId,
    displayName: fieldId,
    aggregation: "sum",
    isVirtual: false,
    sort: null,
    numberFormat: numberFormat(type),
    ...extra,
  }
}

function chart(type: ChartType, metrics: ReturnType<typeof metric>[], dimensions = [{
  fieldId: "timestamp",
  fieldName: "时间",
  fieldCode: "timestamp",
  displayName: "时间",
  sort: null,
  timeGranularity: "month",
}]) {
  return {
    id: `chart-${type}-${metrics.map(item => item.fieldId).join("-") || "empty"}-${dimensions.length}`,
    title: type,
    type,
    dataset_code: "mid_user_increment",
    data_config: {
      dimensions,
      metrics,
      fieldOrder: [],
      filters: [],
      resultLimit: { limitType: "all" },
      isConfigured: true,
    },
    style_config: {},
  } as unknown as DashboardComponent
}

function drop(fieldId: string, fieldType: "metric" | "dimension", formatType?: "number" | "percent" | "duration" | "storage") {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: {
      getData: () => JSON.stringify({
        id: fieldId,
        name: fieldId,
        displayName: fieldId,
        fieldType,
        numberFormat: formatType ? numberFormat(formatType) : undefined,
      }),
    },
  } as unknown as React.DragEvent
}

describe("line chart shared axis rules", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("keeps the confirmed Chinese messages", () => {
    expect(zhDashboard.componentConfigDrawer.toast.lineAxisSingleKind).toBe("纵轴只能共用数量或百分比")
    expect(zhDashboard.componentConfigDrawer.toast.lineMaxTwo).toBe("折线图最多两条线")
    expect(zhDashboard.componentConfigDrawer.toast.lineMaxThree).toBe("组合折线图最多三条线")
    expect(zhDashboard.componentConfigDrawer.toast.lineSingleDimension).toBe("折线图的横轴只能有一个维度")
  })

  it("allows a second count or percent and rejects every other pair", () => {
    expect(canAddLineMetric([metric("online", "number")], metric("active", "number"))).toEqual({ ok: true })
    expect(canAddLineMetric([metric("rate", "percent")], metric("share", "percent"))).toEqual({ ok: true })
    expect(canAddLineMetric(
      [metric("rate", "number", { isDivide: "divide" })],
      metric("share", "percent"),
    )).toEqual({ ok: true })
    expect(canAddLineMetric([metric("online", "number")], metric("rate", "percent"))).toEqual({ ok: false, reason: "kind" })
    expect(canAddLineMetric([metric("duration", "duration")], metric("other", "duration"))).toEqual({ ok: false, reason: "kind" })
    expect(canAddLineMetric([metric("storage", "storage")], metric("count", "number"))).toEqual({ ok: false, reason: "kind" })
    expect(canAddLineMetric(
      [metric("online", "number"), metric("active", "number")],
      metric("silent", "number"),
    )).toEqual({ ok: false, reason: "max" })
    expect(maxSharedLineMetrics(ChartType.Line)).toBe(2)
    expect(maxSharedLineMetrics(ChartType.StackedLine)).toBe(3)
    expect(canAddLineMetric(
      [metric("online", "number"), metric("active", "number")],
      metric("silent", "number"),
      3,
    )).toEqual({ ok: true })
    expect(canAddLineMetric(
      [metric("online", "number"), metric("active", "number"), metric("silent", "number")],
      metric("away", "number"),
      3,
    )).toEqual({ ok: false, reason: "max" })
    expect(canAddLineMetric(
      [metric("online", "number"), metric("rate", "percent")],
      metric("silent", "number"),
      3,
    )).toEqual({ ok: false, reason: "kind" })
    expect(maxCategoryDimensions(ChartType.Line)).toBe(1)
    expect(maxCategoryDimensions(ChartType.StackedLine)).toBe(1)
    expect(maxCategoryDimensions(ChartType.Bar)).toBe(2)
  })

  it("rejects a format change that breaks a legal pair and allows repairing an old mixed pair", () => {
    const counts = [metric("online", "number"), metric("active", "number")]
    expect(canChangeLineMetricFormat(counts, 1, numberFormat("percent"))).toEqual({ ok: false, reason: "kind" })

    const mixed = [metric("online", "number"), metric("rate", "percent")]
    expect(canChangeLineMetricFormat(mixed, 1, numberFormat("number"))).toEqual({ ok: true })
    expect(canChangeLineMetricFormat(mixed, 1, numberFormat("duration"))).toEqual({ ok: false, reason: "kind" })
    expect(canChangeLineMetricFormat([metric("online", "number")], 0, numberFormat("duration"))).toEqual({ ok: true })
    expect(canChangeLineMetricFormat(
      [metric("online", "number"), metric("active", "number"), metric("silent", "number")],
      2,
      numberFormat("percent"),
    )).toEqual({ ok: false, reason: "kind" })
  })

  it("drops a second count onto a basic line chart and rejects a third metric", async () => {
    const { result } = renderHook(() => useChartState(chart(ChartType.Line, [metric("用户在线数", "number")])))
    await waitFor(() => expect(result.current.valueDimensions).toHaveLength(1))

    act(() => {
      result.current.handleDrop(drop("用户活跃数", "metric", "number"), "value", true)
    })
    expect(result.current.valueDimensions.map(item => item.fieldId)).toEqual(["用户在线数", "用户活跃数"])

    act(() => {
      result.current.handleDrop(drop("用户活跃率", "metric", "percent"), "value", true)
    })
    expect(result.current.valueDimensions).toHaveLength(2)
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineMaxTwo",
    }))
  })

  it("rejects a percent dropped onto one count", async () => {
    const { result } = renderHook(() => useChartState(chart(ChartType.Line, [metric("用户在线数", "number")])))
    await waitFor(() => expect(result.current.valueDimensions).toHaveLength(1))
    act(() => {
      result.current.handleDrop(drop("用户活跃率", "metric", "percent"), "value", true)
    })
    expect(result.current.valueDimensions.map(item => item.fieldId)).toEqual(["用户在线数"])
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineAxisSingleKind",
    }))
  })

  it("rejects a second duration and a third count", async () => {
    const durationChart = renderHook(() => useChartState(chart(ChartType.StackedLine, [metric("时长甲", "duration")])))
    await waitFor(() => expect(durationChart.result.current.chartType).toBe(ChartType.StackedLine))
    act(() => {
      durationChart.result.current.handleDrop(drop("时长乙", "metric", "duration"), "value", true)
    })
    expect(durationChart.result.current.valueDimensions).toHaveLength(1)
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineAxisSingleKind",
    }))

    toastMock.mockClear()
    const twoCounts = renderHook(() => useChartState(chart(ChartType.Line, [
      metric("用户在线数", "number"),
      metric("用户活跃数", "number"),
    ])))
    await waitFor(() => expect(twoCounts.result.current.valueDimensions).toHaveLength(2))
    act(() => {
      twoCounts.result.current.handleDrop(drop("用户沉默数", "metric", "number"), "value", true)
    })
    expect(twoCounts.result.current.valueDimensions).toHaveLength(2)
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineMaxTwo",
    }))

    toastMock.mockClear()
    const combination = renderHook(() => useChartState(chart(ChartType.StackedLine, [
      metric("用户在线数", "number"),
      metric("用户活跃数", "number"),
    ])))
    await waitFor(() => expect(combination.result.current.valueDimensions).toHaveLength(2))
    act(() => {
      combination.result.current.handleDrop(drop("用户沉默数", "metric", "number"), "value", true)
    })
    expect(combination.result.current.valueDimensions.map(item => item.fieldId)).toEqual([
      "用户在线数",
      "用户活跃数",
      "用户沉默数",
    ])
    act(() => {
      combination.result.current.handleDrop(drop("用户离开数", "metric", "number"), "value", true)
    })
    expect(combination.result.current.valueDimensions).toHaveLength(3)
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineMaxThree",
    }))
  })

  it("rejects a second category on line charts and still accepts one on a bar chart", async () => {
    const line = renderHook(() => useChartState(chart(ChartType.Line, [metric("用户在线数", "number")])))
    await waitFor(() => expect(line.result.current.categoryDimensions).toHaveLength(1))
    act(() => {
      line.result.current.handleDrop(drop("department", "dimension"), "category", true)
    })
    expect(line.result.current.categoryDimensions.map(item => item.fieldId)).toEqual(["timestamp"])
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
      description: "componentConfigDrawer.toast.lineSingleDimension",
    }))

    toastMock.mockClear()
    const bar = renderHook(() => useChartState(chart(ChartType.Bar, [metric("用户在线数", "number")])))
    await waitFor(() => expect(bar.result.current.chartType).toBe(ChartType.Bar))
    act(() => {
      bar.result.current.handleDrop(drop("department", "dimension"), "category", true)
    })
    expect(bar.result.current.categoryDimensions.map(item => item.fieldId)).toEqual(["timestamp", "department"])
    expect(toastMock).not.toHaveBeenCalled()
  })

  it("keeps a saved second dimension and a saved mixed metric pair", async () => {
    const twoDimensions = renderHook(() => useChartState(chart(
      ChartType.Line,
      [metric("用户在线数", "number")],
      [
        { fieldId: "timestamp", fieldName: "时间", fieldCode: "timestamp", displayName: "时间", sort: null, timeGranularity: "month" },
        { fieldId: "department", fieldName: "部门", fieldCode: "department", displayName: "部门", sort: null, timeGranularity: null },
      ],
    )))
    await waitFor(() => expect(twoDimensions.result.current.categoryDimensions).toHaveLength(2))
    expect(twoDimensions.result.current.getDataConfig("all", "").dimensions.map(item => item.fieldId)).toEqual([
      "timestamp",
      "department",
    ])

    const mixed = renderHook(() => useChartState(chart(ChartType.StackedLine, [
      metric("用户在线数", "number"),
      metric("用户活跃率", "percent"),
    ])))
    await waitFor(() => expect(mixed.result.current.valueDimensions).toHaveLength(2))
    expect(mixed.result.current.getDataConfig("all", "").metrics.map(item => item.fieldId)).toEqual([
      "用户在线数",
      "用户活跃率",
    ])
    act(() => {
      mixed.result.current.handleDrop(drop("用户沉默数", "metric", "number"), "value", true)
    })
    expect(mixed.result.current.valueDimensions).toHaveLength(2)
  })

  it("forces the legend to the top right for two lines and leaves one line alone", () => {
    const hiddenLegend = {
      showLegend: false,
      legendPosition: "bottom",
      legendAlign: "left",
    } as ComponentStyleConfig
    const twoLines = generateChartOption({
      data: {
        dimensions: ["2026-01"],
        series: [
          { name: "用户在线数", data: [1] },
          { name: "用户活跃数", data: [2] },
        ],
      },
      chartType: ChartType.Line,
      styleConfig: hiddenLegend,
      dataConfig: chart(ChartType.Line, []).data_config,
    })
    expect(twoLines.legend).toMatchObject({
      top: 0,
      right: 0,
      data: ["用户在线数", "用户活跃数"],
    })

    const oneLine = generateChartOption({
      data: {
        dimensions: ["2026-01"],
        series: [{ name: "用户在线数", data: [1] }],
      },
      chartType: ChartType.StackedLine,
      styleConfig: hiddenLegend,
    })
    expect(oneLine.legend).toBeUndefined()
  })

  it("uses blue and orange for two lines on a combination line chart", () => {
    const option = generateChartOption({
      data: {
        dimensions: ["2026-01"],
        series: [
          { name: "用户在线数", data: [1] },
          { name: "用户活跃数", data: [2] },
        ],
      },
      chartType: ChartType.StackedLine,
      styleConfig: { themeColor: "professional-blue" } as ComponentStyleConfig,
      dataConfig: chart(ChartType.StackedLine, []).data_config,
    })
    expect(option.series.map((item: { itemStyle: { color?: string }, lineStyle?: { color?: string } }) => ({
      item: item.itemStyle.color,
      line: item.lineStyle?.color,
    }))).toEqual([
      { item: "#3B82F6", line: "#3B82F6" },
      { item: "#F59E0B", line: "#F59E0B" },
    ])
    expect(option.series.map((item: { itemStyle: { color?: string } }) => item.itemStyle.color)).not.toEqual(["#3B82F6", "#60A5FA"])

    const threeLines = generateChartOption({
      data: {
        dimensions: ["2026-01"],
        series: [
          { name: "用户在线数", data: [1] },
          { name: "用户活跃数", data: [2] },
          { name: "用户沉默数", data: [3] },
        ],
      },
      chartType: ChartType.StackedLine,
      styleConfig: { themeColor: "professional-blue" } as ComponentStyleConfig,
      dataConfig: chart(ChartType.StackedLine, []).data_config,
    })
    expect(threeLines.series.map((item: { itemStyle: { color?: string } }) => item.itemStyle.color)).toEqual([
      "#3B82F6",
      "#F59E0B",
      "#10B981",
    ])

    const basicLine = generateChartOption({
      data: {
        dimensions: ["2026-01"],
        series: [
          { name: "用户在线数", data: [1] },
          { name: "用户活跃数", data: [2] },
        ],
      },
      chartType: ChartType.Line,
      styleConfig: { themeColor: "professional-blue" } as ComponentStyleConfig,
      dataConfig: chart(ChartType.Line, []).data_config,
    })
    expect(basicLine.series[0].itemStyle.color).toBeUndefined()
    expect(basicLine.series[1].lineStyle).toBeUndefined()
  })
})
