import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppReviewView, type AppReviewTarget } from "./AppReviewView";
import type { LocalizeFn } from "./approvalPresentation";

const mockGetSnapshotTreeApi = jest.fn();
const mockGetReviewContextApi = jest.fn();
const mockGetSnapshotFileApi = jest.fn();
const mockGetVersionDiffApi = jest.fn();

jest.mock("~/api/hostedAppReview", () => ({
  getSnapshotTreeApi: (...args: unknown[]) => mockGetSnapshotTreeApi(...args),
  getReviewContextApi: (...args: unknown[]) => mockGetReviewContextApi(...args),
  getSnapshotFileApi: (...args: unknown[]) => mockGetSnapshotFileApi(...args),
  getVersionDiffApi: (...args: unknown[]) => mockGetVersionDiffApi(...args),
}));

/**
 * The preview panel has its own suite; here it is stubbed so this file asserts
 * *where* it sits rather than what it does — and so the review view's tests do
 * not fire a real XHR at the preview endpoint.
 */
jest.mock("./AppPreviewPanel", () => ({
  AppPreviewPanel: ({ appId, versionId }: Record<string, unknown>) => (
    <div data-testid="preview-panel-stub">{`${String(appId)}/${String(versionId)}`}</div>
  ),
}));

/**
 * The diff presentation is the shared `@bisheng/file-viewers` component, tested
 * on its own in the platform suite. Here it is a stub, so this file asserts
 * what the review view *feeds* it — which two versions, and whether it asks
 * for a diff at all.
 */
jest.mock("@bisheng/file-viewers", () => ({
  VersionDiffView: ({ files, caption, emptyMessage }: Record<string, unknown>) => (
    <div data-testid="diff-stub">
      <span data-testid="diff-caption">{String(caption ?? "")}</span>
      <span data-testid="diff-empty">{String(emptyMessage ?? "")}</span>
      <span data-testid="diff-files">{(files as unknown[]).length}</span>
    </div>
  ),
}));

// jsdom ships no ResizeObserver, and `@bisheng/ui`'s Tabs measures its ink bar
// with one. Without the stub every render here throws before any assertion.
beforeAll(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

/**
 * The design-system Tabs renders each label twice (a hidden copy it measures
 * the ink bar against), so a plain getByText is ambiguous; the visible one is
 * first.
 */
function clickTab(label: string) {
  // Radix Tabs run on `activationMode="automatic"`: the trigger switches on
  // mousedown/focus, not on a synthetic click.
  const trigger = screen.getAllByRole("tab").find((node) => node.textContent?.includes(label));
  if (!trigger) throw new Error(`no tab labelled ${label}`);
  fireEvent.mouseDown(trigger);
  fireEvent.focus(trigger);
}

/** Echoes the key back so assertions read as the copy contract. */
const localize: LocalizeFn = (key) => String(key);

const TARGET: AppReviewTarget = {
  appId: "app-1",
  versionId: "ver-2",
  appName: "form-survey",
  versionNo: 2,
  releaseKindText: "iteration",
  capabilities: [{ type: "model", name: "qwen", description: "chat model" }],
};

const TREE = {
  version: { version_id: "ver-2", version_no: 2, kind: "iteration", terminal_state: null, submitted_at: null },
  role: "approver",
  entries: [
    { path: "bisheng-app.yaml", name: "bisheng-app.yaml", type: "file", size: 20, previewable: true, reason: null },
    { path: "logo.png", name: "logo.png", type: "file", size: 9000, previewable: false, reason: "binary" },
  ],
  total_files: 2,
  truncated: false,
};

const CONTEXT = {
  version: TREE.version,
  role: "approver",
  current_version_id: "ver-1",
  pending_version_id: "ver-2",
  versions: [
    { version_id: "ver-2", version_no: 2, kind: "iteration", terminal_state: null, submitted_at: null, is_current: false, is_pending: true },
    { version_id: "ver-1", version_no: 1, kind: "initial", terminal_state: "online", submitted_at: null, is_current: true, is_pending: false },
  ],
};

function renderView(overrides: Partial<AppReviewTarget> = {}) {
  return render(
    <AppReviewView target={{ ...TARGET, ...overrides }} localize={localize} onBack={jest.fn()} />,
  );
}

describe("AppReviewView", () => {
  beforeEach(() => {
    mockGetSnapshotTreeApi.mockResolvedValue(TREE);
    mockGetReviewContextApi.mockResolvedValue(CONTEXT);
    mockGetSnapshotFileApi.mockResolvedValue({
      version: TREE.version,
      role: "approver",
      path: "bisheng-app.yaml",
      size: 20,
      previewable: true,
      reason: null,
      content: "name: form-survey\nruntime: python3.11\n",
      masked_secrets: 0,
      line_count: 2,
    });
    mockGetVersionDiffApi.mockResolvedValue({
      base: CONTEXT.versions[1],
      target: CONTEXT.versions[0],
      role: "approver",
      summary: { files_changed: 1, additions: 1, deletions: 0, truncated: false },
      files: [{ path: "main.py", change: "modified", additions: 1, deletions: 0, comparable: true, reason: null }],
      patches: [],
    });
  });

  it("opens on the source tab with the manifest already loaded", async () => {
    renderView();

    await screen.findByTestId("review-source-pane");
    expect(mockGetSnapshotTreeApi).toHaveBeenCalledWith("app-1", "ver-2");
    await waitFor(() => expect(mockGetSnapshotFileApi).toHaveBeenCalledWith("app-1", "ver-2", "bisheng-app.yaml"));
    expect(await screen.findByText(/runtime: python3.11/)).toBeInTheDocument();
  });

  it("does not fetch a file the tree already said cannot be shown", async () => {
    renderView();
    await screen.findByTestId("review-source-pane");
    await waitFor(() => expect(mockGetSnapshotFileApi).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTitle("logo.png"));

    expect(await screen.findByText("com_approval_review_not_previewable_binary")).toBeInTheDocument();
    expect(mockGetSnapshotFileApi).toHaveBeenCalledTimes(1);
  });

  it("shows an empty file as empty, not as one it refuses to display", async () => {
    // `content: ""` is a real, readable file. Branching on the text rather than
    // on `previewable` would tell the approver the platform will not show it.
    mockGetSnapshotFileApi.mockResolvedValue({
      version: TREE.version,
      role: "approver",
      path: "bisheng-app.yaml",
      size: 0,
      previewable: true,
      reason: null,
      content: "",
      masked_secrets: 0,
      line_count: 0,
    });

    renderView();

    await screen.findByTestId("review-source-pane");
    await waitFor(() => expect(mockGetSnapshotFileApi).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByText("com_approval_review_not_previewable_generic"),
    ).not.toBeInTheDocument();
  });

  it("lists the version history an approver has no other way to read", async () => {
    renderView();
    await screen.findByTestId("review-source-pane");

    clickTab("com_approval_review_tab_versions");

    expect(await screen.findByText("v1")).toBeInTheDocument();
    expect(screen.getByText("com_approval_review_version_current")).toBeInTheDocument();
    expect(screen.getByText("com_approval_review_version_pending")).toBeInTheDocument();
    expect(screen.getByText("com_approval_review_terminal_online")).toBeInTheDocument();
  });

  it("diffs the pending version against the published one, and only when that tab is opened", async () => {
    renderView();
    await screen.findByTestId("review-source-pane");
    expect(mockGetVersionDiffApi).not.toHaveBeenCalled();

    clickTab("com_approval_review_tab_diff");

    // base = the running version, target = the one under approval (AC-41).
    await waitFor(() => expect(mockGetVersionDiffApi).toHaveBeenCalledWith("app-1", "ver-1", "ver-2"));
    expect(await screen.findByTestId("diff-caption")).toHaveTextContent("v1 → v2");
  });

  it("says a first release has nothing to compare against instead of calling the endpoint", async () => {
    mockGetReviewContextApi.mockResolvedValue({ ...CONTEXT, current_version_id: null });
    renderView();
    await screen.findByTestId("review-source-pane");

    clickTab("com_approval_review_tab_diff");

    expect(await screen.findByTestId("diff-empty")).toHaveTextContent("com_approval_review_no_baseline");
    expect(mockGetVersionDiffApi).not.toHaveBeenCalled();
  });

  it("shows the refusal message rather than an empty frame when the reads are denied", async () => {
    const refusal = "not allowed to read this version";
    mockGetSnapshotTreeApi.mockRejectedValue(new Error(refusal));
    mockGetReviewContextApi.mockRejectedValue(new Error(refusal));

    renderView();

    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.queryByTestId("review-source-pane")).not.toBeInTheDocument();
  });
});

test("the try-it-out panel is pinned above the tabs, not hidden inside one", async () => {
  render(<AppReviewView target={TARGET} localize={localize} onBack={jest.fn()} />);

  const panel = await screen.findByTestId("preview-panel-stub");
  expect(panel).toHaveTextContent("app-1/ver-2");
  // Pinned means "before the tab strip in document order", which is what an
  // approver actually experiences as the panel being at the top.
  const tablist = screen.getByRole("tablist");
  expect(panel.compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
