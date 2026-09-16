import { render, screen, waitFor, within } from "@/test/test-utils"
import type { ResourceTierAdminItem } from "@/controllers/API/hostedApp"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ResourceTierTab } from "@/pages/SystemPage/components/ResourceTierTab"

/**
 * F055 T066 — the system page's resource-tier tab.
 *
 * What is asserted is the contract the tab owes the tier rules, not its looks:
 * every write goes through `bsConfirm` first, disabling is a PATCH on
 * `enabled` (never a delete), the default tier has no disable button, and the
 * inline edit sends only the fields that changed.
 */

const apiMocks = vi.hoisted(() => ({
  listResourceTiersApi: vi.fn(),
  updateResourceTierApi: vi.fn(),
}))

vi.mock("@/controllers/API/hostedApp", () => apiMocks)

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise,
}))

/** Record every confirm and let the test decide when to press OK. */
const confirmMocks = vi.hoisted(() => ({
  calls: [] as Array<{ title?: string; desc: unknown; onOk?: (close: () => void) => void }>,
}))

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (params: { title?: string; desc: unknown; onOk?: (close: () => void) => void }) => {
    confirmMocks.calls.push(params)
  },
}))

const toastMock = vi.hoisted(() => vi.fn())
vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: toastMock }))

function tier(overrides: Partial<ResourceTierAdminItem>): ResourceTierAdminItem {
  return {
    code: "standard",
    name: "Standard",
    cpu_millicores: 2000,
    memory_mb: 4096,
    description: "General services",
    enabled: true,
    sort_order: 1,
    in_use_app_count: 3,
    is_default: false,
    update_time: null,
    ...overrides,
  }
}

const LIGHT = tier({ code: "light", name: "Light", cpu_millicores: 500, memory_mb: 1024, sort_order: 0, is_default: true, in_use_app_count: 2 })
const STANDARD = tier({})
const PERFORMANCE = tier({ code: "performance", name: "Performance", cpu_millicores: 4000, memory_mb: 8192, sort_order: 2, in_use_app_count: 0, enabled: false })

const EDIT = "hostedApp.tierAdmin.actions.edit"
const SAVE = "hostedApp.tierAdmin.actions.save"
const DISABLE = "hostedApp.tierAdmin.actions.disable"
const ENABLE = "hostedApp.tierAdmin.actions.enable"

function pressOk(index = confirmMocks.calls.length - 1) {
  const call = confirmMocks.calls[index]
  call.onOk?.(() => {})
}

describe("ResourceTierTab (F055 AC-45 / AC-47)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMocks.calls.length = 0
    apiMocks.listResourceTiersApi.mockResolvedValue([LIGHT, STANDARD, PERFORMANCE])
    apiMocks.updateResourceTierApi.mockImplementation(async (code: string, patch: Record<string, unknown>) => {
      const base = [LIGHT, STANDARD, PERFORMANCE].find((row) => row.code === code)!
      return { ...base, ...patch }
    })
  })

  it("lists every tier with spec, status and in-use count, and offers no delete anywhere", async () => {
    render(<ResourceTierTab />)
    const standard = await screen.findByTestId("tier-row-standard")
    expect(within(standard).getByText("Standard")).toBeInTheDocument()
    expect(within(standard).getByText("2000")).toBeInTheDocument()
    expect(within(standard).getByText("4096")).toBeInTheDocument()
    expect(within(standard).getByText("3")).toBeInTheDocument()
    expect(within(standard).getByText("hostedApp.tierAdmin.status.enabled")).toBeInTheDocument()
    // The retired tier is still listed — it still has to resolve for old versions.
    const performance = screen.getByTestId("tier-row-performance")
    expect(within(performance).getByText("hostedApp.tierAdmin.status.disabled")).toBeInTheDocument()
    expect(within(performance).getByText(ENABLE)).toBeInTheDocument()
    // No delete button on any row (AC-47's precondition).
    expect(screen.queryByText("delete")).toBeNull()
    expect(screen.queryByText("hostedApp.tierAdmin.actions.delete")).toBeNull()
    expect(screen.getByText("hostedApp.tierAdmin.hint")).toBeInTheDocument()
  })

  it("hides the disable button on the default tier and explains why", async () => {
    render(<ResourceTierTab />)
    const light = await screen.findByTestId("tier-row-light")
    expect(within(light).getByText("hostedApp.tierAdmin.defaultTag")).toBeInTheDocument()
    expect(within(light).queryByText(DISABLE)).toBeNull()
    expect(within(light).getByText(EDIT)).toBeInTheDocument()
    // A non-default tier does get one.
    expect(within(screen.getByTestId("tier-row-standard")).getByText(DISABLE)).toBeInTheDocument()
  })

  it("inline edit: confirms before saving and sends only the changed fields", async () => {
    const user = userEvent.setup()
    render(<ResourceTierTab />)
    const standard = await screen.findByTestId("tier-row-standard")
    await user.click(within(standard).getByText(EDIT))

    const cpu = within(standard).getByLabelText("hostedApp.tierAdmin.columns.cpu")
    await user.clear(cpu)
    await user.type(cpu, "1500")
    await user.click(within(standard).getByText(SAVE))

    // Nothing is written before the admin confirms.
    expect(apiMocks.updateResourceTierApi).not.toHaveBeenCalled()
    expect(confirmMocks.calls).toHaveLength(1)
    expect(confirmMocks.calls[0].title).toBe("hostedApp.tierAdmin.saveConfirmTitle")

    pressOk()
    await waitFor(() => expect(apiMocks.updateResourceTierApi).toHaveBeenCalledWith("standard", { cpu_millicores: 1500 }))
    // The row re-renders from the answer and leaves edit mode.
    await waitFor(() => expect(within(screen.getByTestId("tier-row-standard")).getByText("1500")).toBeInTheDocument())
    expect(within(screen.getByTestId("tier-row-standard")).queryByText(SAVE)).toBeNull()
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ description: "hostedApp.tierAdmin.feedback.saved" }))
  })

  it("inline edit: rejects a non-positive CPU locally without confirming or writing", async () => {
    const user = userEvent.setup()
    render(<ResourceTierTab />)
    const standard = await screen.findByTestId("tier-row-standard")
    await user.click(within(standard).getByText(EDIT))
    const cpu = within(standard).getByLabelText("hostedApp.tierAdmin.columns.cpu")
    await user.clear(cpu)
    await user.type(cpu, "0")
    await user.click(within(standard).getByText(SAVE))

    expect(confirmMocks.calls).toHaveLength(0)
    expect(apiMocks.updateResourceTierApi).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ description: "hostedApp.tierAdmin.validation.cpu" }))
  })

  it("disable: confirms with the in-use count, then PATCHes enabled=false — never a delete", async () => {
    const user = userEvent.setup()
    render(<ResourceTierTab />)
    const standard = await screen.findByTestId("tier-row-standard")
    await user.click(within(standard).getByText(DISABLE))

    expect(confirmMocks.calls).toHaveLength(1)
    expect(confirmMocks.calls[0].title).toBe("hostedApp.tierAdmin.disableConfirmTitle")
    expect(apiMocks.updateResourceTierApi).not.toHaveBeenCalled()

    pressOk()
    await waitFor(() => expect(apiMocks.updateResourceTierApi).toHaveBeenCalledWith("standard", { enabled: false }))
    await waitFor(() =>
      expect(within(screen.getByTestId("tier-row-standard")).getByText("hostedApp.tierAdmin.status.disabled")).toBeInTheDocument(),
    )
    // The row is still there — retired, not gone.
    expect(within(screen.getByTestId("tier-row-standard")).getByText(ENABLE)).toBeInTheDocument()
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ description: "hostedApp.tierAdmin.feedback.disabled" }))
  })

  it("re-enable: the same endpoint the other way round", async () => {
    const user = userEvent.setup()
    render(<ResourceTierTab />)
    const performance = await screen.findByTestId("tier-row-performance")
    await user.click(within(performance).getByText(ENABLE))
    expect(confirmMocks.calls[0].title).toBe("hostedApp.tierAdmin.enableConfirmTitle")
    pressOk()
    await waitFor(() => expect(apiMocks.updateResourceTierApi).toHaveBeenCalledWith("performance", { enabled: true }))
  })

  it("renders the empty state when the backend has no tiers", async () => {
    apiMocks.listResourceTiersApi.mockResolvedValue([])
    render(<ResourceTierTab />)
    expect(await screen.findByText("hostedApp.tierAdmin.empty")).toBeInTheDocument()
  })
})
