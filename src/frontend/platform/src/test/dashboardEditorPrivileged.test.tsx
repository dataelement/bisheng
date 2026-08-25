/**
 * A super admin must reach the board editor.
 *
 * `useDashboardPermissions` short-circuits for an admin: it returns an empty
 * action map and reports `privileged` instead of asking the backend. The editor
 * read the map alone, so every admin failed its `canEdit` gate and was bounced
 * to /404 the moment the board loaded.
 */
import EditorPage from "@/pages/Dashboard/editor"
import { render, screen, waitFor } from "@/test/test-utils"
import { describe, expect, it, vi } from "vitest"

const navigate = vi.fn()

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom")
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ id: "7" }) }
})

vi.mock("@/controllers/API/dashboard", () => ({
  getDashboard: vi.fn(async () => ({ id: 7, name: "board" })),
  getDashboards: vi.fn(async () => []),
}))

vi.mock("@/pages/Dashboard/components/editor/EditorCanvas", () => ({
  EditorCanvas: () => <div>canvas</div>,
}))

vi.mock("@/pages/Dashboard/components/editor/EditorHeader", () => ({
  EditorHeader: () => <div>header</div>,
}))

const permissionsResult = {
  permissions: {} as Record<string, string[]>,
  loading: false,
  privileged: true,
}

vi.mock("@/pages/Dashboard/hook", async () => {
  const actual = await vi.importActual<typeof import("@/pages/Dashboard/hook")>("@/pages/Dashboard/hook")
  return {
    ...actual,
    useDashboardPermissions: () => permissionsResult,
    useEditorShortcuts: () => undefined,
  }
})

describe("dashboard editor permission gate", () => {
  it("lets a privileged admin in even though the action map is empty", async () => {
    render(<EditorPage />)

    await waitFor(() => expect(screen.getByText("canvas")).toBeTruthy())
    expect(navigate).not.toHaveBeenCalled()
  })

  it("still bounces a user with no edit action", async () => {
    permissionsResult.privileged = false
    permissionsResult.permissions = { "7": ["view"] }

    render(<EditorPage />)

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("404"))
  })
})
