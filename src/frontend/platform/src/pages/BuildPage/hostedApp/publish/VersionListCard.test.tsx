import { fireEvent, render, screen, within } from "@testing-library/react"
import type { HostedAppVersion } from "@/controllers/API/hostedApp"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { VersionListCard } from "./VersionListCard"

const state = vi.hoisted(() => ({ rows: [] as HostedAppVersion[] }))
vi.mock("@/util/hook", () => ({
  useTable: () => ({
    data: state.rows,
    total: state.rows.length,
    page: 1,
    pageSize: 10,
    loading: false,
    loaded: true,
    setPage: vi.fn(),
    reload: vi.fn(),
    filterData: vi.fn(),
  }),
}))
vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppVersionPageApi: vi.fn(),
  getHostedAppErrorMessage: vi.fn(),
}))

function version(
  id: string,
  no: number,
  notes?: string | null,
): HostedAppVersion {
  return {
    version_id: id,
    version_no: no,
    release_notes: notes,
    kind: "iteration",
    terminal_state: "online",
    submitted_at: null,
    is_current: no === 2,
    is_pending: false,
  }
}

describe("version history release notes", () => {
  beforeEach(() => {
    state.rows = []
  })

  it("keeps each full text next to its own version after rows change", () => {
    state.rows = [
      version("two", 2, "Second\n  details"),
      version("one", 1, "First"),
    ]
    const view = render(<VersionListCard appId="app" />)
    const actions = screen.getAllByRole("button", { name: "hostedApp.releaseNotes.column" })
    const row = actions[1].closest("tr")
    fireEvent.click(actions[0])
    expect(screen.getByText(/Second/).textContent).toBe("Second\n  details")
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })
    expect(row?.textContent).toContain("v1")
    expect(screen.getByRole("columnheader", { name: "operations" })).toBeInTheDocument()
    expect(view.container.querySelectorAll("tbody tr")).toHaveLength(2)
    state.rows = [version("three", 3, "Third")]
    view.rerender(<VersionListCard appId="app" reloadKey="changed" />)
    fireEvent.click(screen.getAllByRole("button", { name: "hostedApp.releaseNotes.column" })[0])
    expect(screen.getByText("Third")).not.toBeNull()
    expect(screen.queryByText("First")).toBeNull()
  })

  it("handles missing fields and renders hostile markup as text", () => {
    const notes = '<script>alert("x")</script> **new**'
    state.rows = [version("one", 1), version("two", 2, notes)]
    const { container } = render(<VersionListCard appId="app" />)
    fireEvent.click(screen.getAllByRole("button", { name: "hostedApp.releaseNotes.column" })[0])
    expect(screen.getByText("hostedApp.releaseNotes.empty")).not.toBeNull()
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })
    fireEvent.click(screen.getAllByRole("button", { name: "hostedApp.releaseNotes.column" })[1])
    expect(
      within(screen.getByRole("dialog")).getByText(notes),
    ).not.toBeNull()
    expect(container.querySelector("script")).toBeNull()
  })
})
