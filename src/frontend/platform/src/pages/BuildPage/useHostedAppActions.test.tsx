import { act, renderHook } from "@testing-library/react"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { useHostedAppActions } from "./useHostedAppActions"

const mocks = vi.hoisted(() => ({ confirm: vi.fn(), stop: vi.fn(), resume: vi.fn(), notify: vi.fn(), t: (key: string) => key }))
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: mocks.confirm }))
vi.mock("@bisheng/ui", () => ({ notification: { open: mocks.notify } }))
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mocks.t }) }))
vi.mock("@/controllers/API/hostedApp", () => ({
  stopHostedAppApi: mocks.stop, resumeHostedAppApi: mocks.resume,
  deleteHostedAppApi: vi.fn(), manualPublishHostedAppApi: vi.fn(),
  getHostedAppErrorCode: (error: { status_code?: number }) => error.status_code,
  getHostedAppErrorMessage: () => "fallback",
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.stop.mockResolvedValue({ ok: true, state: "stopped" })
  mocks.resume.mockResolvedValue({ ok: true, state: "online" })
})

const app = { appId: "app", name: "demo", state: "stopped" as const }

describe("shared list/detail confirmation", () => {
  it.each(["stopApp", "resumeApp"] as const)("%s sends no request until confirmation and cancel is harmless", async (action) => {
    const { result } = renderHook(() => useHostedAppActions())
    let completion!: Promise<boolean>
    act(() => { completion = result.current[action](app) })
    expect(mocks.stop).not.toHaveBeenCalled()
    expect(mocks.resume).not.toHaveBeenCalled()
    await act(async () => { mocks.confirm.mock.calls[0][0].onCancel(); await completion })
    expect(await completion).toBe(false)
    expect(mocks.stop).not.toHaveBeenCalled()
    expect(mocks.resume).not.toHaveBeenCalled()
  })

  it.each(["stopApp", "resumeApp"] as const)("%s executes once after accepting", async (action) => {
    const { result } = renderHook(() => useHostedAppActions())
    let completion!: Promise<boolean>
    act(() => { completion = result.current[action](app) })
    await act(async () => { mocks.confirm.mock.calls[0][0].onOk(vi.fn()); await completion })
    expect(action === "stopApp" ? mocks.stop : mocks.resume).toHaveBeenCalledOnce()
  })

  it("explains a withdrawn release rather than a generic state conflict", async () => {
    mocks.resume.mockRejectedValue({ status_code: 16102, data: { reason: "approval_withdrawn" } })
    const { result } = renderHook(() => useHostedAppActions())
    let completion!: Promise<boolean>
    act(() => { completion = result.current.resumeApp(app) })
    await act(async () => { mocks.confirm.mock.calls[0][0].onOk(vi.fn()); await completion })
    expect(mocks.notify).toHaveBeenCalledWith(expect.objectContaining({ description: "api_errors:appStartApprovalWithdrawn" }))
  })
})
