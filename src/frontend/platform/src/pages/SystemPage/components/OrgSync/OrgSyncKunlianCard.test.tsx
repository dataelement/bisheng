import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { act, fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OrgSync from "./index";

const {
  mockListGatewayOrgSyncLogsApi,
  mockGetStatusApi,
  mockGetStatusSilentApi,
  mockTriggerKunlianSyncApi,
  mockShowApiError,
  mockToastShow,
} = vi.hoisted(() => ({
  mockListGatewayOrgSyncLogsApi: vi.fn(),
  mockGetStatusApi: vi.fn(),
  mockGetStatusSilentApi: vi.fn(),
  mockTriggerKunlianSyncApi: vi.fn(),
  mockShowApiError: vi.fn(),
  mockToastShow: vi.fn(),
}));

vi.mock("@/controllers/API/orgSync", () => ({
  listGatewayOrgSyncLogsApi: mockListGatewayOrgSyncLogsApi,
}));

vi.mock("@/controllers/API/kunlianApiKeys", () => ({
  getKunlianIntegrationStatusApi: mockGetStatusApi,
  getKunlianIntegrationStatusSilentApi: mockGetStatusSilentApi,
  triggerKunlianSyncApi: mockTriggerKunlianSyncApi,
}));

vi.mock("@/controllers/request", () => ({
  showApiError: mockShowApiError,
}));

vi.mock("@bisheng/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@bisheng/ui")>();
  return {
    ...actual,
    toast: { show: mockToastShow },
  };
});

function renderOrgSync({
  kunlianSsoConfigured = true,
  isGlobalSuper = true,
}: {
  kunlianSsoConfigured?: boolean;
  isGlobalSuper?: boolean;
} = {}) {
  return render(
    <locationContext.Provider
      value={{
        current: ["sys"],
        setCurrent: vi.fn(),
        isStackedOpen: false,
        setIsStackedOpen: vi.fn(),
        showSideBar: false,
        setShowSideBar: vi.fn(),
        extraNavigation: { title: "" },
        setExtraNavigation: vi.fn(),
        extraComponent: <></>,
        setExtraComponent: vi.fn(),
        appConfig: { kunlianSsoConfigured },
        reloadConfig: vi.fn(),
      }}
    >
      <userContext.Provider
        value={
          {
            user: {
              user_id: 1,
              role: "admin",
              is_global_super: isGlobalSuper,
            },
            setUser: vi.fn(),
          } as never
        }
      >
        <OrgSync />
      </userContext.Provider>
    </locationContext.Provider>,
  );
}

describe("OrgSync Kunlian manual sync card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListGatewayOrgSyncLogsApi.mockResolvedValue({ data: [], total: 0 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("hides KunlianSyncCard when kunlianSsoConfigured is false or user is not global super", async () => {
    renderOrgSync({ kunlianSsoConfigured: false, isGlobalSuper: true });
    await waitFor(() => expect(mockListGatewayOrgSyncLogsApi).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("kunlianSync.title")).not.toBeInTheDocument();
    expect(mockGetStatusSilentApi).not.toHaveBeenCalled();

    renderOrgSync({ kunlianSsoConfigured: true, isGlobalSuper: false });
    await waitFor(() => expect(mockListGatewayOrgSyncLogsApi).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("kunlianSync.title")).not.toBeInTheDocument();
    expect(mockGetStatusSilentApi).not.toHaveBeenCalled();
  });

  it("triggers manual sync, polls status until completed, and updates metrics", async () => {
    mockGetStatusSilentApi
      .mockResolvedValueOnce({
        connection_id: "kunlian-workflow-test",
        directory_status: "PUBLISHED",
        projection_status: "SUCCEEDED",
        member_count: 10,
        unmapped_count: 1,
        projection_pending: 0,
        projection_failed: 0,
        sync_requested_version: 2,
        sync_completed_version: 2,
        last_published_at: "2026-11-26T08:00:00Z",
        last_run_at: "2026-11-26T08:00:00Z",
        ready: true,
        reasons: [],
      })
      .mockResolvedValueOnce({
        connection_id: "kunlian-workflow-test",
        directory_status: "FETCHING",
        projection_status: "PENDING",
        running_batch_id: "batch-next",
        member_count: 10,
        unmapped_count: 1,
        projection_pending: 2,
        projection_failed: 0,
        sync_requested_version: 3,
        sync_completed_version: 2,
        ready: false,
        reasons: ["PROJECTION_NOT_READY"],
      })
      .mockResolvedValueOnce({
        connection_id: "kunlian-workflow-test",
        directory_status: "PUBLISHED",
        projection_status: "SUCCEEDED",
        running_batch_id: null,
        member_count: 15,
        unmapped_count: 0,
        projection_pending: 0,
        projection_failed: 0,
        sync_requested_version: 3,
        sync_completed_version: 3,
        last_published_at: "2026-11-26T09:00:00Z",
        last_run_at: "2026-11-26T09:00:00Z",
        ready: true,
        reasons: [],
      });
    mockTriggerKunlianSyncApi.mockResolvedValue({
      connection_id: "kunlian-workflow-test",
      requested_version: 3,
      status: "REQUESTED",
      dispatched: true,
    });

    renderOrgSync({ kunlianSsoConfigured: true, isGlobalSuper: true });

    expect(await screen.findByText("kunlianSync.title")).toBeInTheDocument();
    expect(await screen.findByText("10")).toBeInTheDocument();

    vi.useFakeTimers();
    const syncBtn = screen.getByRole("button", { name: "kunlianSync.actions.syncNow" });
    fireEvent.click(syncBtn);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockTriggerKunlianSyncApi).toHaveBeenCalledTimes(1);
    expect(mockToastShow).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", message: "kunlianSync.feedback.triggered" }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByText("15")).toBeInTheDocument();
    expect(mockToastShow).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", message: "kunlianSync.feedback.completed" }),
    );
    expect(screen.getByRole("button", { name: "kunlianSync.actions.syncNow" })).toBeEnabled();
  });

  it("shows failure alert when directory_status is FAILED and fallback info toast when dispatched is false", async () => {
    mockGetStatusSilentApi.mockResolvedValue({
      connection_id: "kunlian-workflow-test",
      directory_status: "FAILED",
      projection_status: "FAILED",
      member_count: 0,
      unmapped_count: 0,
      projection_pending: 0,
      projection_failed: 2,
      last_reason_code: "DIRECTORY_CREDENTIAL_UNAVAILABLE",
      sync_requested_version: 1,
      sync_completed_version: 0,
      ready: false,
      reasons: ["DIRECTORY_CREDENTIAL_UNAVAILABLE"],
    });
    mockTriggerKunlianSyncApi.mockResolvedValue({
      connection_id: "kunlian-workflow-test",
      requested_version: 2,
      status: "REQUESTED",
      dispatched: false,
    });

    renderOrgSync({ kunlianSsoConfigured: true, isGlobalSuper: true });

    expect(await screen.findByText("kunlianSync.alerts.syncFailed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "kunlianSync.actions.syncNow" }));
    await waitFor(() => expect(mockTriggerKunlianSyncApi).toHaveBeenCalledTimes(1));
    expect(mockToastShow).toHaveBeenCalledWith(
      expect.objectContaining({ type: "info", message: "kunlianSync.feedback.queuedFallback" }),
    );
  });
});
