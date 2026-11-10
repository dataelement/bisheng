import { render, screen } from "@/test/test-utils"
import { expect, it, vi } from "vitest"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { ServiceAccount } from "./index"
import { listServiceAccountsApi } from "@/controllers/API/serviceAccount"

vi.mock("@/controllers/API/serviceAccount", () => ({
  getServiceAccountManagementScopeApi: vi.fn().mockResolvedValue({ scope_tenant_id: null }),
  setServiceAccountManagementScopeApi: vi.fn(),
  getServiceAccountApi: vi.fn(),
  listServiceAccountsApi: vi.fn().mockResolvedValue({
    data: [1, 2].map(id => ({ id, tenant_id: id, tenant_name: `Organization ${id}`, name: `account-${id}`, status: "enabled", active_key_count: 0, resource_owner: { user_id: id, user_name: "owner", disabled: false } })),
    total: 2, idle_days: 30,
  }),
}))
vi.mock("./CreateServiceAccountDialog", () => ({ CreateServiceAccountDialog: () => <div data-testid="create-form" /> }))
vi.mock("./ApiKeysTab", () => ({ ApiKeysTab: () => null }))
vi.mock("./OverviewTab", () => ({ OverviewTab: () => null }))
vi.mock("./ResourceGrantsTab", () => ({ ResourceGrantsTab: () => null }))

it("does not load accounts for a legacy null scope", async () => {
  render(<locationContext.Provider value={{ appConfig: { multiTenantEnabled: true } } as never}>
    <userContext.Provider value={{ user: { user_id: 3, tenant_id: 1, is_global_super: true } } as never}>
      <ServiceAccount />
    </userContext.Provider>
  </locationContext.Provider>)
  expect(await screen.findByText("openApiManagement.tenantScope.choose")).toBeInTheDocument()
  expect(screen.queryByText("account-1")).toBeNull()
  expect(screen.queryByText("account-2")).toBeNull()
  expect(screen.queryByTestId("create-form")).toBeNull()
  expect(listServiceAccountsApi).not.toHaveBeenCalled()
})
