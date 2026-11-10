import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { PreviewStatus } from "@/controllers/API/hostedAppPreview"
import { OwnerPreviewCard } from "./OwnerPreviewCard"

/**
 * `react-i18next` is mocked globally (src/test/setup.ts) to echo keys, so the
 * assertions read as the i18n contract of the card. The API module rejects with
 * an already-localized message string, which is what the mocks below do.
 */

const getPreviewStatusApi = vi.fn()
const startPreviewApi = vi.fn()
const reclaimPreviewApi = vi.fn()

vi.mock("@/controllers/API/hostedAppPreview", () => ({
  getPreviewStatusApi: (...args: unknown[]) => getPreviewStatusApi(...args),
  startPreviewApi: (...args: unknown[]) => startPreviewApi(...args),
  reclaimPreviewApi: (...args: unknown[]) => reclaimPreviewApi(...args),
}))

vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppErrorMessage: (error: unknown) =>
    typeof error === "string" ? error : "",
}))

const K = "hostedApp.publishStatus"

function status(overrides: Partial<PreviewStatus> = {}): PreviewStatus {
  return {
    state: "absent",
    session_id: null,
    entry_url: null,
    expires_at: null,
    reclaim_reason: null,
    runnable: true,
    not_runnable_reason: null,
    ...overrides,
  }
}

const RUNNING = status({
  state: "running",
  session_id: "sess-1",
  entry_url: "https://apps.example.com/preview/sess-1/",
  expires_at: "2026-10-18T10:00:00",
})

function renderCard() {
  return render(<OwnerPreviewCard appId="app-1" versionId="ver-2" />)
}

describe("OwnerPreviewCard", () => {
  beforeEach(() => {
    getPreviewStatusApi.mockReset()
    startPreviewApi.mockReset()
    reclaimPreviewApi.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("test_absent_offers_start_and_explains_what_a_preview_is", async () => {
    getPreviewStatusApi.mockResolvedValue(status())
    renderCard()

    const start = await screen.findByRole("button", { name: `${K}.previewStart` })
    await waitFor(() => expect(start).toBeEnabled())
    expect(getPreviewStatusApi).toHaveBeenCalledWith("app-1", "ver-2")
    expect(screen.getByText(`${K}.previewHint`)).toBeInTheDocument()
    expect(screen.queryByText(`${K}.previewOpen`)).not.toBeInTheDocument()
  })

  it("test_start_shows_progress_then_the_running_actions", async () => {
    getPreviewStatusApi.mockResolvedValue(status())
    let resolveStart: (value: PreviewStatus) => void = () => {}
    startPreviewApi.mockReturnValue(
      new Promise<PreviewStatus>((resolve) => {
        resolveStart = resolve
      }),
    )
    renderCard()

    const start = await screen.findByRole("button", { name: `${K}.previewStart` })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)

    // Starting is the client's own state: busy button + "this can take a while".
    expect(await screen.findByText(`${K}.previewStarting`)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: `${K}.previewStart` })).toBeDisabled()
    expect(startPreviewApi).toHaveBeenCalledWith("app-1", "ver-2")

    resolveStart(RUNNING)
    expect(await screen.findByRole("button", { name: `${K}.previewOpen` })).toBeEnabled()
    expect(screen.getByRole("button", { name: `${K}.previewReclaim` })).toBeEnabled()
    expect(screen.getByText(`${K}.previewExpiresAt`)).toBeInTheDocument()
  })

  it("test_open_goes_to_the_entry_url_in_a_new_tab", async () => {
    getPreviewStatusApi.mockResolvedValue(RUNNING)
    const open = vi.spyOn(window, "open").mockImplementation(() => null)
    renderCard()

    fireEvent.click(await screen.findByRole("button", { name: `${K}.previewOpen` }))

    expect(open).toHaveBeenCalledWith(
      "https://apps.example.com/preview/sess-1/",
      "_blank",
      "noopener,noreferrer",
    )
  })

  it("test_reclaim_sends_the_session_and_shows_the_reclaimed_state", async () => {
    getPreviewStatusApi.mockResolvedValue(RUNNING)
    reclaimPreviewApi.mockResolvedValue(
      status({ state: "reclaimed", session_id: "sess-1", reclaim_reason: "manual" }),
    )
    renderCard()

    fireEvent.click(await screen.findByRole("button", { name: `${K}.previewReclaim` }))

    expect(await screen.findByRole("button", { name: `${K}.previewStartAgain` })).toBeEnabled()
    expect(reclaimPreviewApi).toHaveBeenCalledWith("app-1", "ver-2", "sess-1")
    expect(screen.getByText(`${K}.previewReclaimedManual`)).toBeInTheDocument()
    expect(screen.queryByText(`${K}.previewOpen`)).not.toBeInTheDocument()
  })

  it.each([
    ["approval_terminal", `${K}.previewReclaimedApproval`],
    ["expired", `${K}.previewReclaimedExpired`],
    ["start_failed", `${K}.previewReclaimedStartFailed`],
  ])("test_reclaimed_by_%s_says_why", async (reason, key) => {
    getPreviewStatusApi.mockResolvedValue(
      status({ state: "reclaimed", session_id: "sess-0", reclaim_reason: reason }),
    )
    renderCard()

    expect(await screen.findByText(key)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: `${K}.previewStartAgain` })).toBeEnabled()
  })

  it.each([
    ["no_image", `${K}.previewBlockedNoImage`],
    ["settled", `${K}.previewBlockedSettled`],
  ])("test_blocked_by_%s_explains_and_disables_start", async (reason, key) => {
    getPreviewStatusApi.mockResolvedValue(
      status({ runnable: false, not_runnable_reason: reason }),
    )
    renderCard()

    expect(await screen.findByText(key)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: `${K}.previewStart` })).toBeDisabled()
  })

  it("test_a_failed_start_shows_the_reason_and_stays_startable", async () => {
    getPreviewStatusApi.mockResolvedValue(status())
    startPreviewApi.mockRejectedValue("The preview instance could not be started")
    renderCard()

    const start = await screen.findByRole("button", { name: `${K}.previewStart` })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)

    expect(
      await screen.findByText("The preview instance could not be started"),
    ).toBeInTheDocument()
    // Not drawn as running, and the owner can retry.
    expect(screen.queryByText(`${K}.previewOpen`)).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole("button", { name: `${K}.previewStart` })).toBeEnabled(),
    )
  })

  it("test_a_failed_reclaim_keeps_the_instance_drawn_as_running", async () => {
    getPreviewStatusApi.mockResolvedValue(RUNNING)
    reclaimPreviewApi.mockRejectedValue("")
    renderCard()

    fireEvent.click(await screen.findByRole("button", { name: `${K}.previewReclaim` }))

    // An empty message still reads as a failure, never as a normal card.
    expect(await screen.findByText(`${K}.previewActionFailed`)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: `${K}.previewOpen` })).toBeInTheDocument()
  })

  it("test_a_failed_status_read_shows_the_reason", async () => {
    getPreviewStatusApi.mockRejectedValue("You do not have permission to run a preview of this version")
    renderCard()

    expect(
      await screen.findByText("You do not have permission to run a preview of this version"),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: `${K}.previewStart` })).toBeDisabled()
  })
})
