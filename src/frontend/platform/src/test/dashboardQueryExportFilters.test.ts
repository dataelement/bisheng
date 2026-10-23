import { act, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { queryChartData } from "@/controllers/API/dashboard"
import request from "@/controllers/request"
import { useComponentExport } from "@/pages/Dashboard/components/export/useComponentExport"
import { ChartType, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"
import { useEditorDashboardStore } from "@/store/dashboardStore"

vi.mock("@/controllers/request", () => ({ default: { post: vi.fn() } }))

const chart = {
  id: "c1", dashboard_id: "d1", type: ChartType.PivotTable,
  dataset_code: "mid_knowledge_space_content_stat", data_config: {},
} as DashboardComponent
const dimensions = [
  { fieldId: "original_upload_company_name", values: ["首钢股份"] },
  { fieldId: "original_upload_department_name", values: [null, "生产部"] },
  { fieldId: "uploader_user_name", values: ["张三"] },
]

describe("chart query and export filter parity", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, "open").mockImplementation(() => null)
    vi.mocked(request.post).mockImplementation(async url =>
      url.endsWith("/query") ? { value: [] } : { file_url: "https://example.com/detail.xlsx" },
    )
  })

  it.each([
    [{ queryComponentParams: { startTime: 100, endTime: 200 } }, { type: "custom", mode: "fixed", startDate: 100, endDate: 200 }],
    [{ queryConditions: { hasDefaultValue: true, defaultValue: { type: "recent_days", mode: "dynamic", recentDays: 30 } } },
      { type: "recent_days", mode: "dynamic", recentDays: 30 }],
  ])("sends the same applied time and dimension conditions through both HTTP routes (%j)", async (dateParam, expectedTime) => {
    const queryParams = [dateParam, { dimensionFilters: dimensions }]
    useEditorDashboardStore.setState({
      savedDashboard: { id: "d1", components: [chart] } as any,
      chartRefreshTriggers: { c1: { trigger: 1, queryParams } },
    })
    const { result } = renderHook(() => useComponentExport({ dashboardId: "d1", componentId: "c1" }))
    await queryChartData({ useId: true, dashboardId: "d1", component: chart, queryParams })
    await act(async () => { await result.current.exportAll() })
    const query = vi.mocked(request.post).mock.calls[0][1] as any
    const exported = vi.mocked(request.post).mock.calls[1][1] as any
    expect(query.time_filters).toEqual([expectedTime])
    expect(query.dimension_filters).toEqual(dimensions)
    expect(exported.time_filters).toEqual(query.time_filters)
    expect(exported.dimension_filters).toEqual(query.dimension_filters)
    expect(vi.mocked(request.post).mock.calls[1][0]).toBe("/api/v1/telemetry/dashboard/component/c1/export-all")
  })
})
