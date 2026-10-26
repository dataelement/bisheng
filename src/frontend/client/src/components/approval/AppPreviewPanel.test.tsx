import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppPreviewPanel } from "./AppPreviewPanel";
import type { LocalizeFn } from "./approvalPresentation";
import type { PreviewStatus } from "~/api/hostedAppPreview";

const mockGetPreviewStatusApi = jest.fn();
const mockStartPreviewApi = jest.fn();
const mockReclaimPreviewApi = jest.fn();

jest.mock("~/api/hostedAppPreview", () => ({
  getPreviewStatusApi: (...args: unknown[]) => mockGetPreviewStatusApi(...args),
  startPreviewApi: (...args: unknown[]) => mockStartPreviewApi(...args),
  reclaimPreviewApi: (...args: unknown[]) => mockReclaimPreviewApi(...args),
}));

/** Echoes the key back so assertions read as the copy contract. */
const localize: LocalizeFn = (key, options) =>
  options ? `${String(key)}:${JSON.stringify(options)}` : String(key);

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
  };
}

function renderPanel() {
  return render(<AppPreviewPanel appId="app-1" versionId="ver-1" localize={localize} />);
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetPreviewStatusApi.mockResolvedValue(status());
});

// ---------------------------------------------------------------------------
// the four interface states (AC-26)
// ---------------------------------------------------------------------------

test("not raised yet: one button and what a trial is", async () => {
  renderPanel();

  await screen.findByText("com_approval_preview_start");
  expect(screen.getByText("com_approval_preview_hint")).toBeInTheDocument();
  expect(screen.queryByText("com_approval_preview_open")).not.toBeInTheDocument();
});

test("running: open and shut down, with the deadline spelled out", async () => {
  mockGetPreviewStatusApi.mockResolvedValue(
    status({
      state: "running",
      session_id: "sess-1",
      entry_url: "/apps/preview/sess-1",
      expires_at: "2026-09-23T10:00:00",
    }),
  );

  renderPanel();

  await screen.findByText("com_approval_preview_open");
  expect(screen.getByText("com_approval_preview_reclaim")).toBeInTheDocument();
  expect(screen.getByText(/com_approval_preview_expires_at/)).toBeInTheDocument();
  expect(screen.queryByText("com_approval_preview_start")).not.toBeInTheDocument();
});

test("reclaimed: why it ended, and the button says 'again'", async () => {
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ state: "reclaimed", session_id: "sess-1", reclaim_reason: "expired" }),
  );

  renderPanel();

  await screen.findByText("com_approval_preview_start_again");
  expect(screen.getByText("com_approval_preview_reclaimed_expired")).toBeInTheDocument();
});

test("the reclaim reason is not read off a running instance", async () => {
  // A row keeps its previous reason only after it closes; a running instance
  // must never render 「已回收」 copy next to an open button.
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ state: "running", session_id: "s", entry_url: "/apps/preview/s", reclaim_reason: null }),
  );

  renderPanel();

  await screen.findByText("com_approval_preview_open");
  expect(screen.queryByText(/com_approval_preview_reclaimed/)).not.toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// raising one
// ---------------------------------------------------------------------------

test("pressing the button raises one and swaps to the running state", async () => {
  mockStartPreviewApi.mockResolvedValue(
    status({ state: "running", session_id: "sess-2", entry_url: "/apps/preview/sess-2" }),
  );

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_start"));

  await screen.findByText("com_approval_preview_open");
  expect(mockStartPreviewApi).toHaveBeenCalledWith("app-1", "ver-1");
});

test("a version that cannot be previewed says why and offers no button to press", async () => {
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ runnable: false, not_runnable_reason: "no_image" }),
  );

  renderPanel();

  await screen.findByText("com_approval_preview_blocked_no_image");
  const button = screen.getByText("com_approval_preview_start").closest("button");
  expect(button).toBeDisabled();
});

test("a failed start shows the reason and leaves the panel raisable", async () => {
  mockStartPreviewApi.mockRejectedValue(new Error("not enough capacity"));

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_start"));

  await screen.findByText("not enough capacity");
  // AC-26 「允许重新拉起」 — the button is still there and still enabled.
  expect(screen.getByText("com_approval_preview_start").closest("button")).not.toBeDisabled();
});

test("a failed start does not draw an instance as running", async () => {
  mockStartPreviewApi.mockRejectedValue(new Error("boom"));

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_start"));

  await screen.findByText("boom");
  expect(screen.queryByText("com_approval_preview_open")).not.toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// opening and reclaiming
// ---------------------------------------------------------------------------

test("the preview opens in a new tab, not in place", async () => {
  const open = jest.fn();
  (window as unknown as { open: unknown }).open = open;
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ state: "running", session_id: "s", entry_url: "/apps/preview/s" }),
  );

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_open"));

  expect(open).toHaveBeenCalledWith("/apps/preview/s", "_blank", "noopener,noreferrer");
});

test("shutting down calls the session it is looking at and shows the manual reason", async () => {
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ state: "running", session_id: "sess-3", entry_url: "/apps/preview/sess-3" }),
  );
  mockReclaimPreviewApi.mockResolvedValue(
    status({ state: "reclaimed", session_id: "sess-3", reclaim_reason: "manual" }),
  );

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_reclaim"));

  await screen.findByText("com_approval_preview_reclaimed_manual");
  expect(mockReclaimPreviewApi).toHaveBeenCalledWith("app-1", "ver-1", "sess-3");
});

test("a failed reclaim keeps the instance drawn as running", async () => {
  mockGetPreviewStatusApi.mockResolvedValue(
    status({ state: "running", session_id: "s", entry_url: "/apps/preview/s" }),
  );
  mockReclaimPreviewApi.mockRejectedValue(new Error("not allowed"));

  renderPanel();
  fireEvent.click(await screen.findByText("com_approval_preview_reclaim"));

  await screen.findByText("not allowed");
  expect(screen.getByText("com_approval_preview_open")).toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// the read itself
// ---------------------------------------------------------------------------

test("a failed status read is reported rather than drawn as 'nothing raised'", async () => {
  mockGetPreviewStatusApi.mockRejectedValue(new Error("not an approver of this version"));

  renderPanel();

  await screen.findByText("not an approver of this version");
  await waitFor(() =>
    expect(screen.getByText("com_approval_preview_start").closest("button")).toBeDisabled(),
  );
});
