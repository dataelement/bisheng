import {
  deleteHostedAppApi,
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  getHostedAppApi,
  getHostedAppInstanceApi,
  getHostedAppLogsApi,
  getHostedAppRuntimeStatusApi,
  getHostedAppVersionsApi,
  HOSTED_APP_ERROR,
  manualPublishHostedAppApi,
  publishHostedAppApi,
  resumeHostedAppApi,
  stopHostedAppApi,
  updateHostedAppMetaApi,
} from "@/controllers/API/hostedApp"
import { getAppsApi } from "@/controllers/API/flow"
import { beforeEach, describe, expect, it, vi } from "vitest"

const requestMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock("@/controllers/request", () => ({
  default: requestMocks,
  captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise,
}))

describe("F054 hosted application API", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    requestMocks.get.mockResolvedValue({})
    requestMocks.post.mockResolvedValue({})
    requestMocks.patch.mockResolvedValue({})
    requestMocks.delete.mockResolvedValue({})
  })

  it("uses the /api/v1/apps contract for every read and write", async () => {
    await getHostedAppApi("app-1")
    await getHostedAppInstanceApi("app-1")
    await getHostedAppVersionsApi("app-1")
    await getHostedAppRuntimeStatusApi()
    await updateHostedAppMetaApi("app-1", { name: "n" })
    await deleteHostedAppApi("app-1")
    await publishHostedAppApi("app-1")
    await manualPublishHostedAppApi("app-1")
    await stopHostedAppApi("app-1")
    await resumeHostedAppApi("app-1")

    const readUrls = requestMocks.get.mock.calls.map((call) => call[0])
    expect(readUrls).toEqual([
      "/api/v1/apps/app-1",
      "/api/v1/apps/app-1/instance",
      "/api/v1/apps/app-1/versions",
      "/api/v1/apps/runtime-status",
    ])
    expect(requestMocks.patch).toHaveBeenCalledWith("/api/v1/apps/app-1", {
      name: "n",
    })
    expect(requestMocks.delete).toHaveBeenCalledWith("/api/v1/apps/app-1")
    expect(requestMocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/apps/app-1/actions/publish",
      "/api/v1/apps/app-1/actions/manual-publish",
      "/api/v1/apps/app-1/actions/stop",
      "/api/v1/apps/app-1/actions/resume",
    ])
  })

  it("asks for the envelope on reads a non-owner can legitimately hit", async () => {
    // Without `silent` the interceptor turns a refusal into a bare string and
    // the 161xx code is gone — and a real 403/404 on a GET would navigate the
    // whole SPA to /403, costing the page over one tab (design pit 25).
    await getHostedAppLogsApi("app-1")
    expect(requestMocks.get).toHaveBeenCalledWith("/api/v1/apps/app-1/logs", {
      silent: true,
    })
  })

  it("only sends the log filters that were provided", async () => {
    await getHostedAppLogsApi("app-1", {
      tail: 500,
      since: "1700000000",
      keyword: "boom",
    })
    expect(requestMocks.get.mock.calls[0][0]).toBe(
      "/api/v1/apps/app-1/logs?tail=500&since=1700000000&keyword=boom",
    )
  })

  it("reads the business code out of a rejected envelope", () => {
    const envelope = { status_code: 16161, status_message: "no log access" }
    expect(getHostedAppErrorCode(envelope)).toBe(HOSTED_APP_ERROR.LOG_FORBIDDEN)
    expect(getHostedAppErrorMessage(envelope)).toBe("no log access")
    expect(getHostedAppErrorCode("plain string rejection")).toBeUndefined()
    expect(getHostedAppErrorMessage("plain string rejection")).toBe(
      "plain string rejection",
    )
  })
})

describe("F054 app list parameters", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    requestMocks.get.mockResolvedValue({
      data: [],
      page_size: 20,
      has_more: false,
      next_cursor: null,
    })
  })

  it("maps the hosted type onto flow_type 35", async () => {
    await getAppsApi({ type: "app", pageSize: 14 })
    expect(requestMocks.get.mock.calls[0][0]).toContain("flow_type=35")
  })

  it("sends the five application states through app_state, not status", async () => {
    // `status` is projected 2/1 for the shared on-off switch and the backend
    // only honours those two values; pushing an application state into it
    // would be dropped before it ever reached the query.
    await getAppsApi({ type: "app", app_state: "pending_capacity" })
    const url = requestMocks.get.mock.calls[0][0]
    expect(url).toContain("app_state=pending_capacity")
    expect(url).not.toContain("status=")
  })

  it("keeps the workflow and assistant mappings untouched", async () => {
    await getAppsApi({ type: "flow" })
    await getAppsApi({ type: "assistant" })
    expect(requestMocks.get.mock.calls[0][0]).toContain("flow_type=10")
    expect(requestMocks.get.mock.calls[1][0]).toContain("flow_type=5")
  })
})
