import { userContext } from "@/contexts/userContext"
import { usePermissionIds } from "@/components/bs-comp/permission/usePermissionLevels"
import { render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const checkPermission = vi.fn()

vi.mock("@/controllers/API/permission", () => ({
  checkPermission: (...args: unknown[]) => checkPermission(...args),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

function PermissionProbe() {
  const { loading } = usePermissionIds(
    "workflow",
    ["workflow-cache-test"],
    ["edit_app", "publish_app"],
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

describe("usePermissionIds cache", () => {
  it("reuses a workflow permission result after the header remounts", async () => {
    checkPermission.mockResolvedValue({ allowed: true })

    const firstRender = renderProbe()
    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
      expect(checkPermission).toHaveBeenCalledTimes(2)
    })

    firstRender.unmount()
    renderProbe()

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
    })
    expect(checkPermission).toHaveBeenCalledTimes(2)
  })
})
