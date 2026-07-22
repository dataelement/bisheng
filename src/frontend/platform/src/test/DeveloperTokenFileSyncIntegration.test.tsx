import type {
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule as FileSyncRule,
} from "@/controllers/API/developerToken"
import {
  createDeveloperTokenApi,
  getDeveloperTokenFileSyncOptionsApi,
  getDeveloperTokenDetailApi,
  listDeveloperTokensApi,
} from "@/controllers/API/developerToken"
import { userContext } from "@/contexts/userContext"
import DeveloperToken from "@/pages/SystemPage/components/DeveloperToken"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const configuredRule: FileSyncRule = {
  category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
  business_domain: { mode: "fixed", code: "SAFETY" },
  target_space: { mode: "dynamic", knowledge_id: null },
  dynamic_source: "department_id",
}

const emptyOptions = (tenantId: number): DeveloperTokenFileSyncOptions => ({
  tenant_id: tenantId,
  categories: [{
    code: "POLICY",
    label: "Policy",
    children: [{ code: "MGMT_POLICY", label: "Management policy" }],
  }],
  business_domains: [{ code: "SAFETY", name: "Safety" }],
  knowledge_spaces: { data: [], total: 0 },
})

vi.mock("@/controllers/API/developerToken", () => ({
  createDeveloperTokenApi: vi.fn(),
  deleteDeveloperTokenApi: vi.fn(),
  getDeveloperTokenDetailApi: vi.fn(),
  getDeveloperTokenFileSyncOptionsApi: vi.fn(),
  getDeveloperTokenGlobalConfigApi: vi.fn(),
  listDeveloperTokensApi: vi.fn(),
  updateDeveloperTokenApi: vi.fn(),
  updateDeveloperTokenGlobalConfigApi: vi.fn(),
  viewDeveloperTokenSecretApi: vi.fn(),
}))

vi.mock("@/components/bs-icons", () => ({
  PlusIcon: () => null,
  SearchIcon: () => null,
}))

vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  __esModule: true,
  default: ({ onChange }: { onChange: (value: unknown[]) => void }) => (
    <div>
      <button type="button" onClick={() => onChange([{
        label: "User 2",
        value: 22,
        department_id: 202,
        dept_id: "D-2",
        tenant_id: 2,
      }])}>
        select-tenant-2
      </button>
      <button type="button" onClick={() => onChange([{
        label: "User 3",
        value: 33,
        department_id: 303,
        dept_id: "D-3",
        tenant_id: 3,
      }])}>
        select-tenant-3
      </button>
    </div>
  ),
}))

vi.mock("@/pages/SystemPage/components/DeveloperTokenFileSyncRule", () => ({
  __esModule: true,
  default: ({ value, onChange }: {
    value: FileSyncRule | null
    onChange: (value: FileSyncRule | null) => void
  }) => (
    <div>
      <span data-testid="integrated-rule-state">{value ? "configured" : "empty"}</span>
      <button type="button" onClick={() => onChange(configuredRule)}>configure-file-sync</button>
    </div>
  ),
}))

vi.mock("@/pages/SystemPage/components/DeveloperTokenRouteAllowlist", () => ({
  __esModule: true,
  default: () => null,
}))

vi.mock("@/components/bs-ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }))
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: vi.fn() }))

const mockedList = vi.mocked(listDeveloperTokensApi)
const mockedGetDetail = vi.mocked(getDeveloperTokenDetailApi)
const mockedGetOptions = vi.mocked(getDeveloperTokenFileSyncOptionsApi)
const mockedCreate = vi.mocked(createDeveloperTokenApi)

describe("DeveloperToken file-sync integration", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedList.mockResolvedValue({
      data: [{
        id: 1,
        tenant_id: 2,
        user_id: 22,
        name: "existing",
        token_prefix: "bs_123",
        enabled: true,
        override_ip_whitelist: false,
        override_rate_limit: false,
        route_rule_count: 0,
        file_sync_rule: configuredRule,
      }],
      total: 1,
    })
    mockedGetDetail.mockResolvedValue({} as never)
    mockedGetOptions.mockImplementation(async ({ tenant_id }) => emptyOptions(tenant_id))
    mockedCreate.mockResolvedValue({ plaintext_token: "secret", token: {} as never })
  })

  it("loads options by binding tenant, clears cross-tenant config, saves it, refreshes, and lists a summary", async () => {
    render(
      <userContext.Provider value={{ user: { role: "member", tenant_id: 1 } } as never}>
        <DeveloperToken />
      </userContext.Provider>
    )

    expect(await screen.findByText(/POLICY\/MGMT_POLICY/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "system.developerToken.create" }))
    fireEvent.change(screen.getByPlaceholderText("system.developerToken.namePlaceholder"), {
      target: { value: "new token" },
    })

    fireEvent.click(screen.getByRole("button", { name: "select-tenant-2" }))
    await waitFor(() => expect(mockedGetOptions).toHaveBeenCalledWith(expect.objectContaining({ tenant_id: 2 })))
    fireEvent.click(screen.getByRole("button", { name: "configure-file-sync" }))
    expect(screen.getByTestId("integrated-rule-state")).toHaveTextContent("configured")

    fireEvent.click(screen.getByRole("button", { name: "select-tenant-3" }))
    expect(screen.getByTestId("integrated-rule-state")).toHaveTextContent("empty")
    await waitFor(() => expect(mockedGetOptions).toHaveBeenCalledWith(expect.objectContaining({ tenant_id: 3 })))

    fireEvent.click(screen.getByRole("button", { name: "configure-file-sync" }))
    fireEvent.click(screen.getByRole("button", { name: "confirmButton" }))

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({
      user_id: 33,
      file_sync_rule: configuredRule,
    })))
    expect(mockedList).toHaveBeenCalledTimes(2)
  })
})
