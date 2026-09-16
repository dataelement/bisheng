import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { HostedAppVersion } from "@/controllers/API/hostedApp"
import { VersionDiff, defaultDiffPair } from "./VersionDiff"

const getHostedAppVersionsApi = vi.fn()
const getHostedAppVersionDiffApi = vi.fn()

vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppVersionsApi: (...args: unknown[]) => getHostedAppVersionsApi(...args),
  getHostedAppVersionDiffApi: (...args: unknown[]) => getHostedAppVersionDiffApi(...args),
  getHostedAppErrorMessage: (error: unknown) =>
    error && typeof error === "object" && "status_message" in error
      ? String((error as { status_message: unknown }).status_message)
      : "",
}))

function version(overrides: Partial<HostedAppVersion> & { version_no: number }): HostedAppVersion {
  return {
    version_id: `ver-${overrides.version_no}`,
    kind: "iteration",
    terminal_state: null,
    submitted_at: "2026-09-01T10:00:00",
    is_current: false,
    is_pending: false,
    ...overrides,
  }
}

const DIFF = {
  base: { version_id: "ver-1", version_no: 1, kind: "initial", terminal_state: "online", submitted_at: null },
  target: { version_id: "ver-2", version_no: 2, kind: "iteration", terminal_state: null, submitted_at: null },
  role: "owner",
  summary: { files_changed: 1, additions: 2, deletions: 1, truncated: false },
  files: [{ path: "main.py", change: "modified", additions: 2, deletions: 1, comparable: true, reason: null }],
  patches: [
    {
      path: "main.py",
      change: "modified",
      patch: "--- a/main.py\n+++ b/main.py\n@@ -1 +1,2 @@\n-a = 1\n+a = 2\n+b = 3\n",
      truncated: false,
      masked_secrets: 0,
    },
  ],
}

describe("defaultDiffPair", () => {
  it("test_pairs_the_pending_version_against_the_running_one", () => {
    const versions = [
      version({ version_no: 3, is_pending: true }),
      version({ version_no: 2, is_current: true, terminal_state: "online" }),
      version({ version_no: 1, terminal_state: "online" }),
    ]
    expect(defaultDiffPair(versions)).toEqual({ base: "ver-2", target: "ver-3" })
  })

  it("test_falls_back_to_the_last_published_version_when_none_is_running", () => {
    const versions = [
      version({ version_no: 3, is_pending: true }),
      version({ version_no: 2, terminal_state: "rejected" }),
      version({ version_no: 1, terminal_state: "online" }),
    ]
    expect(defaultDiffPair(versions)).toEqual({ base: "ver-1", target: "ver-3" })
  })

  it("test_no_pair_when_there_is_nothing_older_to_compare_against", () => {
    expect(defaultDiffPair([])).toBeNull()
    expect(defaultDiffPair([version({ version_no: 1 })])).toBeNull()
    // Two rows but the pending one is the oldest: there is no earlier release.
    expect(
      defaultDiffPair([version({ version_no: 2 }), version({ version_no: 1, is_pending: true })]),
    ).toBeNull()
  })
})

describe("VersionDiff", () => {
  beforeEach(() => {
    getHostedAppVersionsApi.mockReset()
    getHostedAppVersionDiffApi.mockReset()
  })

  it("test_compares_the_default_pair_and_renders_the_shared_view", async () => {
    getHostedAppVersionsApi.mockResolvedValue([
      version({ version_no: 2, is_pending: true }),
      version({ version_no: 1, is_current: true, terminal_state: "online" }),
    ])
    getHostedAppVersionDiffApi.mockResolvedValue(DIFF)

    render(<VersionDiff appId="app-1" />)

    await waitFor(() => expect(getHostedAppVersionDiffApi).toHaveBeenCalledWith("app-1", "ver-1", "ver-2"))
    // The presentation is `@bisheng/file-viewers`' shared component — the same
    // one the client's review view mounts (AC-41 "同一呈现").
    await screen.findByTestId("version-diff-view")
    expect(screen.getByText("v1 → v2")).toBeInTheDocument()
    expect(screen.getByText("+a = 2")).toBeInTheDocument()
  })

  it("test_single_version_says_so_and_never_calls_the_diff_endpoint", async () => {
    getHostedAppVersionsApi.mockResolvedValue([version({ version_no: 1, is_current: true })])

    render(<VersionDiff appId="app-1" />)

    expect(await screen.findByText("hostedApp.versionDiff.needTwoVersions")).toBeInTheDocument()
    expect(getHostedAppVersionDiffApi).not.toHaveBeenCalled()
  })

  it("test_a_refused_read_shows_its_own_message_rather_than_an_empty_diff", async () => {
    getHostedAppVersionsApi.mockResolvedValue([
      version({ version_no: 2, is_pending: true }),
      version({ version_no: 1, is_current: true }),
    ])
    // Stands for the backend's 16257 copy; the assertion is that whatever the
    // envelope said reaches the screen, not what the sentence is.
    const refusal = "not allowed to read this version"
    getHostedAppVersionDiffApi.mockRejectedValue({
      status_code: 16257,
      status_message: refusal,
    })

    render(<VersionDiff appId="app-1" />)

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(screen.queryByTestId("version-diff-view")).not.toBeInTheDocument()
  })

  it("test_rows_without_a_version_id_are_dropped_before_they_reach_a_select_item", async () => {
    // A Radix SelectItem with value="" throws and blanks the whole page; the
    // backend has shipped such rows before, so the filter is on this side.
    getHostedAppVersionsApi.mockResolvedValue([
      { ...version({ version_no: 2, is_pending: true }), version_id: "" },
      version({ version_no: 1, is_current: true }),
    ])

    render(<VersionDiff appId="app-1" />)

    expect(await screen.findByText("hostedApp.versionDiff.needTwoVersions")).toBeInTheDocument()
    expect(getHostedAppVersionDiffApi).not.toHaveBeenCalled()
  })
})
