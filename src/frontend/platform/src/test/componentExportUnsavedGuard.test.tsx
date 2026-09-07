import { renderHook, act } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { exportComponentAll, exportComponentDetail } from "@/controllers/API/dashboard"
import { useComponentExport } from "@/pages/Dashboard/components/export/useComponentExport"
import { useEditorDashboardStore } from "@/store/dashboardStore"

vi.mock("@/controllers/API/dashboard", () => ({
  exportComponentAll: vi.fn(),
  exportComponentDetail: vi.fn(),
}))

const mockToast = vi.fn()
vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ toast: mockToast }),
}))

// Export reads a component's saved configuration from the server by id, so a chart that
// only exists in the editor has nothing to read and the request comes back 404
// "资源不存在" (reported on 171, 2026-09-07). The hook must catch that locally instead.
function seedSavedDashboard(componentIds: string[]) {
  useEditorDashboardStore.setState({
    savedDashboard: {
      id: "dashboard-1",
      components: componentIds.map(id => ({ id })),
    } as any,
  })
}

describe("useComponentExport unsaved-component guard", () => {
  beforeEach(() => {
    // jsdom has no window.open; the hook opens the returned file url in a new tab.
    vi.spyOn(window, "open").mockImplementation(() => null)
    vi.mocked(exportComponentAll).mockReset()
    vi.mocked(exportComponentDetail).mockReset()
    mockToast.mockReset()
    useEditorDashboardStore.setState({ savedDashboard: null })
  })

  it("refuses to export a chart that is not saved on the server yet", async () => {
    seedSavedDashboard(["saved-chart"])

    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "dashboard-1", componentId: "draft-chart" })
    )

    expect(result.current.canExport).toBe(false)
    await act(async () => {
      await result.current.exportAll()
      await result.current.exportDetail("belonging_department_name", "生产制造部")
    })

    expect(exportComponentAll).not.toHaveBeenCalled()
    expect(exportComponentDetail).not.toHaveBeenCalled()
    expect(mockToast).toHaveBeenCalledTimes(2)
    expect(mockToast.mock.calls[0][0].variant).toBe("error")
  })

  it("exports normally once the component exists in the saved dashboard", async () => {
    seedSavedDashboard(["saved-chart"])
    vi.mocked(exportComponentAll).mockResolvedValue({ file_url: "https://example.com/a.xlsx" } as any)

    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "dashboard-1", componentId: "saved-chart" })
    )

    expect(result.current.canExport).toBe(true)
    await act(async () => {
      await result.current.exportAll()
    })

    expect(exportComponentAll).toHaveBeenCalledTimes(1)
    expect(mockToast).not.toHaveBeenCalled()
  })

  it("stays disabled when the dashboard has never been saved", () => {
    const { result } = renderHook(() =>
      useComponentExport({ dashboardId: "dashboard-1", componentId: "saved-chart" })
    )

    expect(result.current.canExport).toBe(false)
  })
})
