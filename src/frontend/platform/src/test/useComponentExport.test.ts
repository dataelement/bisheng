import { exportComponentAll, exportComponentDetail } from "@/controllers/API/dashboard"
import { useComponentExport } from "@/pages/Dashboard/components/export/useComponentExport"
import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// F058 AC-09/AC-10: drill-down and whole-chart export hook.

vi.mock("@/controllers/API/dashboard", () => ({
  exportComponentDetail: vi.fn(),
  exportComponentAll: vi.fn(),
}))

const store = vi.hoisted(() => ({
  savedDashboard: { components: [{ id: "c1" }] },
  chartRefreshTriggers: {} as Record<string, { queryParams: any[] }>,
}))
vi.mock("@/store/dashboardStore", () => ({
  useEditorDashboardStore: (selector: (state: any) => unknown) =>
    selector(store),
}))

const mockedExportDetail = vi.mocked(exportComponentDetail)
const mockedExportAll = vi.mocked(exportComponentAll)

beforeEach(() => {
  mockedExportDetail.mockReset()
  mockedExportAll.mockReset()
  store.chartRefreshTriggers = {}
  window.open = vi.fn()
})

describe("useComponentExport", () => {
  it("exports the currently applied chart filters and clears them on the next query", async () => {
    const dimensions = [
      { fieldId: "original_upload_department_name", values: ["北京首钢生产制造部"] },
      { fieldId: "uploader_user_name", values: ["张三"] },
    ]
    store.chartRefreshTriggers.c1 = { queryParams: [
      { queryComponentParams: { shortcutKey: "last_7", isDynamic: true, startTime: 100, endTime: 200 } },
      { dimensionFilters: dimensions },
    ] }
    mockedExportAll.mockResolvedValue({ file_url: "https://minio/all.xlsx" })
    mockedExportDetail.mockResolvedValue({ file_url: "https://minio/detail.xlsx" })
    const { result, rerender } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )
    await act(async () => {
      await result.current.exportAll()
      await result.current.exportDetail("space_level_name", "公共库")
    })
    const expected = {
      timeFilters: [{ type: "recent_days", mode: "dynamic", recentDays: 7, startDate: 100, endDate: 200 }],
      dimensionFilters: dimensions,
    }
    expect(mockedExportAll).toHaveBeenLastCalledWith(expect.objectContaining(expected))
    expect(mockedExportDetail).toHaveBeenLastCalledWith(expect.objectContaining({
      ...expected, dimensionField: "space_level_name", dimensionValue: "公共库",
    }))
    store.chartRefreshTriggers.c1 = { queryParams: [] }
    rerender()
    await act(async () => { await result.current.exportAll() })
    expect(mockedExportAll).toHaveBeenLastCalledWith(expect.objectContaining({ timeFilters: [], dimensionFilters: [] }))
  })

  it.each(["生产制造部", null, 0])("exportDetail forwards the original value %s and opens the returned file_url", async dimensionValue => {
    mockedExportDetail.mockResolvedValue({ file_url: "https://minio/detail.xlsx" })
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )

    await act(async () => {
      await result.current.exportDetail("belonging_department_name", dimensionValue)
    })

    expect(mockedExportDetail).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboardId: "d1",
        componentId: "c1",
        dimensionField: "belonging_department_name",
        dimensionValue,
      }),
    )
    expect(window.open).toHaveBeenCalledWith(
      "https://minio/detail.xlsx", "_blank", "noopener,noreferrer",
    )
  })

  it("isExportingDetail reflects the in-flight (field, value) pair only", async () => {
    let resolveExport: (value: { file_url: string }) => void
    mockedExportDetail.mockReturnValue(
      new Promise(resolve => { resolveExport = resolve }),
    )
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )

    act(() => {
      void result.current.exportDetail("belonging_department_name", "生产制造部")
    })

    await waitFor(() => {
      expect(result.current.isExportingDetail("belonging_department_name", "生产制造部")).toBe(true)
    })
    expect(result.current.isExportingDetail("belonging_department_name", "安全环保监察部")).toBe(false)

    await act(async () => {
      resolveExport({ file_url: "https://minio/x.xlsx" })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(result.current.isExportingDetail("belonging_department_name", "生产制造部")).toBe(false)
    })
  })

  it("exportAll calls the API and opens the returned file_url", async () => {
    mockedExportAll.mockResolvedValue({ file_url: "https://minio/all.xlsx" })
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )

    await act(async () => {
      await result.current.exportAll()
    })

    expect(mockedExportAll).toHaveBeenCalledWith(
      expect.objectContaining({ dashboardId: "d1", componentId: "c1" }),
    )
    expect(window.open).toHaveBeenCalledWith(
      "https://minio/all.xlsx", "_blank", "noopener,noreferrer",
    )
  })

  it("does not throw and clears the loading flag when the API call fails", async () => {
    mockedExportAll.mockRejectedValue(new Error("network error"))
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )

    await act(async () => {
      await result.current.exportAll()
    })

    expect(result.current.isExportingAll).toBe(false)
    expect(window.open).not.toHaveBeenCalled()
  })
})
