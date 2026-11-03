import { render, screen, within } from "@testing-library/react"
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
vi.mock("@/components/bs-ui/pagination/autoPagination", () => ({
  default: () => null,
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
    expect(screen.getByText(/Second/).textContent).toBe("Second\n  details")
    const row = screen.getByText("First").closest("tr")
    expect(row?.previousElementSibling?.textContent).toContain("v1")
    state.rows = [version("three", 3, "Third")]
    view.rerender(<VersionListCard appId="app" reloadKey="changed" />)
    expect(screen.getByText("Third")).not.toBeNull()
    expect(screen.queryByText("First")).toBeNull()
  })

  it("handles missing fields and renders hostile markup as text", () => {
    const notes = '<script>alert("x")</script> **new**'
    state.rows = [version("one", 1), version("two", 2, notes)]
    const { container } = render(<VersionListCard appId="app" />)
    expect(screen.getByText("hostedApp.releaseNotes.empty")).not.toBeNull()
    expect(
      within(screen.getByText(notes).closest("tr")!).getByText(notes),
    ).not.toBeNull()
    expect(container.querySelector("script")).toBeNull()
  })
})
