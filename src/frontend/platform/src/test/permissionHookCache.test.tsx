import { userContext } from "@/contexts/userContext"
import { usePermissionIds } from "@/components/bs-comp/permission/usePermissionLevels"
import { render, screen, waitFor } from "@testing-library/react"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { describe, expect, it, vi, beforeEach } from "vitest"

const checkPermission = vi.fn()

vi.mock("@/controllers/API/permission", () => ({
  checkPermission: (...args: unknown[]) => checkPermission(...args),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

type ProbeOptions = {
  resourceId: string
  permissionIds: string[]
}

function makeProbe({ resourceId, permissionIds }: ProbeOptions) {
  return function PermissionProbe() {
    const { loading } = usePermissionIds("workflow", [resourceId], permissionIds)

    return <span>{loading ? "loading" : "ready"}</span>
  }
}

function renderProbe(options: ProbeOptions) {
  const Probe = makeProbe(options)
  return render(
    <userContext.Provider value={{
      user: { user_id: "permission-cache-user", role: "user" },
      setUser: vi.fn(),
      savedComponents: [],
      addSavedComponent: vi.fn(),
      checkComponentsName: vi.fn(),
      delComponent: vi.fn(),
    }}>
      <Probe />
    </userContext.Provider>,
  )
}

const CACHE_TEST_ID = "workflow-cache-test"
const FIRST_TIME_USER_ID = "tool-first-time-user"
const FGA_OUTAGE_ID = "tool-fga-outage"

describe("usePermissionIds cache", () => {
  beforeEach(() => {
    vi.mocked(toast).mockClear()
    checkPermission.mockReset()
  })

  it("reuses a workflow permission result after the header remounts", async () => {
    checkPermission.mockResolvedValue({ allowed: true })

    const firstRender = renderProbe({
      resourceId: CACHE_TEST_ID,
      permissionIds: ["edit_app", "publish_app"],
    })
    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
      expect(checkPermission).toHaveBeenCalledTimes(2)
    })

    firstRender.unmount()
    renderProbe({
      resourceId: CACHE_TEST_ID,
      permissionIds: ["edit_app", "publish_app"],
    })

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
    })
    expect(checkPermission).toHaveBeenCalledTimes(2)
  })

  // gitee IKB0O4: a first-time / non-admin user legitimately has zero
  // `manage_tool_*` permissions. The probe resolves to { allowed: false } for
  // every tool — that is the expected, non-broken outcome and must not raise a
  // red "权限校验失败" toast on the API/MCP tools page.
  it("does not toast when every check resolves with allowed:false (first-time user)", async () => {
    checkPermission.mockResolvedValue({ allowed: false })

    renderProbe({
      resourceId: FIRST_TIME_USER_ID,
      permissionIds: ["edit_app", "publish_app"],
    })
    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
      expect(checkPermission).toHaveBeenCalledTimes(2)
    })

    expect(vi.mocked(toast)).not.toHaveBeenCalled()
  })

  // Companion to the above: when every probe errors out (FGA truly down) AND
  // nothing resolved, the user-visible toast should still fire exactly once.
  it("toasts exactly once when every check rejects and nothing resolves", async () => {
    checkPermission.mockRejectedValue(new Error("fga down"))

    renderProbe({
      resourceId: FGA_OUTAGE_ID,
      permissionIds: ["edit_app", "publish_app"],
    })
    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument()
      expect(checkPermission).toHaveBeenCalledTimes(2)
    })

    expect(vi.mocked(toast)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(toast)).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "error",
        // eslint-disable-next-line no-restricted-syntax -- mirroring the production toast description (gitee IKB0O4 regression test)
        description: "权限校验失败，请稍后重试",
      }),
    )
  })
})
