import { exportComponentAll, exportComponentDetail } from "@/controllers/API/dashboard"
import { useComponentExport } from "@/pages/Dashboard/components/export/useComponentExport"
import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// F058 AC-09/AC-10: drill-down and whole-chart export hook.

vi.mock("@/controllers/API/dashboard", () => ({
  exportComponentDetail: vi.fn(),
  exportComponentAll: vi.fn(),
}))

const mockedExportDetail = vi.mocked(exportComponentDetail)
const mockedExportAll = vi.mocked(exportComponentAll)

beforeEach(() => {
  mockedExportDetail.mockReset()
  mockedExportAll.mockReset()
  window.open = vi.fn()
})

describe("useComponentExport", () => {
  it("exportDetail calls the API with the given field/value and opens the returned file_url", async () => {
    mockedExportDetail.mockResolvedValue({ file_url: "https://minio/detail.xlsx" })
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "d1", componentId: "c1" }),
    )

    await act(async () => {
      await result.current.exportDetail("belonging_department_name", "生产制造部")
    })

    expect(mockedExportDetail).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboardId: "d1",
        componentId: "c1",
        dimensionField: "belonging_department_name",
        dimensionValue: "生产制造部",
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
