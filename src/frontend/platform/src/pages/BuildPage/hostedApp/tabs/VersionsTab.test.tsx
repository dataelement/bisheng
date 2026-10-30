import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { HostedAppVersion } from "@/controllers/API/hostedApp"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { VersionsTab } from "./VersionsTab"

const mock = vi.hoisted(() => ({ fetch: vi.fn(), t: (key: string) => key }))
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mock.t }) }))
vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppVersionsApi: mock.fetch,
  getHostedAppErrorMessage: () => "load failed",
}))

function version(id: string, notes?: string | null): HostedAppVersion {
  return {
    version_id: id,
    version_no: 1,
    kind: "initial",
    terminal_state: "online",
    submitted_at: null,
    is_current: true,
    is_pending: false,
    release_notes: notes,
  }
}

describe("version tab release notes", () => {
  beforeEach(() => mock.fetch.mockReset())

  it("shows full plain text and the old-version empty state", async () => {
    const notes = "<script>evil()</script>\n  **Feature**"
    mock.fetch.mockResolvedValue([version("new", notes), version("old")])
    const { container } = render(<VersionsTab appId="app" />)
    const actions = await screen.findAllByRole("button", { name: "hostedApp.releaseNotes.column" })
    expect(screen.getByRole("columnheader", { name: "operations" })).toBeInTheDocument()
    fireEvent.click(actions[0])
    const text = screen.getByText(/evil/)
    expect(text.textContent).toBe(notes)
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2)
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })
    fireEvent.click(actions[1])
    expect(screen.getByText("hostedApp.releaseNotes.empty")).not.toBeNull()
    expect(container.querySelector("script")).toBeNull()
  })

  it("does not let an old application response overwrite the new notes", async () => {
    let resolveOld!: (rows: HostedAppVersion[]) => void
    mock.fetch
      .mockImplementationOnce(
        () =>
          new Promise<HostedAppVersion[]>((resolve) => {
            resolveOld = resolve
          }),
      )
      .mockResolvedValueOnce([version("new", "Current app")])
    const view = render(<VersionsTab appId="old" />)
    await waitFor(() => expect(mock.fetch).toHaveBeenCalledWith("old"))
    view.rerender(<VersionsTab appId="new" />)
    fireEvent.click((await screen.findAllByRole("button", { name: "hostedApp.releaseNotes.column" }))[0])
    expect(screen.getByText("Current app")).toBeInTheDocument()
    await act(async () => resolveOld([version("old", "Other app")]))
    expect(screen.queryByText("Other app")).toBeNull()
    expect(screen.getByText("Current app")).not.toBeNull()
  })
})


it.each(["pending", "rejected", "withdrawn", "exception", "cancelled", "approved"])("shows the actual %s approval while the runtime outcome is empty", async (status) => {
  mock.fetch.mockResolvedValue([{ ...version("v1"), terminal_state: null, approval_status: status }])
  render(<VersionsTab appId="app" />)
  expect(await screen.findByText(`hostedApp.publishStatus.approvalState.${status}`)).toBeInTheDocument()
})
