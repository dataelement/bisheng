import { userContext } from "@/contexts/userContext"
import { useResourceActions } from "@/components/bs-comp/permission/useResourceActions"
import { render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const getMyResourcePermissionsApi = vi.fn()

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: (...args: unknown[]) =>
    getMyResourcePermissionsApi(...args),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

function PermissionProbe() {
  const { loading } = useResourceActions(
    "workflow",
    ["workflow-cache-test"],
    ["edit", "publish"],
  )

  return <span>{loading ? "loading" : "ready"}</span>
}

function renderProbe() {
  return render(
    <userContext.Provider value={{
      user: { user_id: "permission-cache-user", role: "user" },
      setUser: vi.fn(),
      savedComponents: [],
      addSavedComponent: vi.fn(),
      checkComponentsName: vi.fn(),
      delComponent: vi.fn(),
    }}>
      <PermissionProbe />
    </userContext.Provider>,
  )
}

describe("useResourceActions cache", () => {
  it("reuses a workflow permission result after the header remounts", async () => {
    getMyResourcePermissionsApi.mockResolvedValue({
      resource_type: "workflow",
      resource_id: "workflow-cache-test",
      actions: ["edit", "publish", "visible"],
    })

    const firstRender = renderProbe()
    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
      expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
    })

    firstRender.unmount()
    renderProbe()

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
    })
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
  })
})
