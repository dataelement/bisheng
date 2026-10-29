// Tenant-flavoured copy in the Open API console must not show up on a
// single-tenant deployment.
//
// `multi_tenant.enabled` defaults to false on a standard docker install, where
// there is exactly one (Root) tenant and the word "tenant" appears nowhere else
// in the console. The three surfaces below either hide the tenant-only element
// or swap to a neutral key; the copy itself lives in bs.json (no hardcoded
// strings), so the assertions are on i18n keys — the shared setup mock returns
// the bare key.

import { locationContext } from "@/contexts/locationContext"
import { PersonalToken } from "@/pages/SystemPage/components/PersonalToken"
import { CreateServiceAccountDialog } from "@/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog"
import { OverviewTab } from "@/pages/SystemPage/components/ServiceAccount/OverviewTab"
import { render, screen } from "@/test/test-utils"
import type { PersonalTokenSetting, ServiceAccountItem } from "@/types/api/openApi"
import type { ReactElement } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  getPersonalTokenSettingApi,
  listPersonalTokensApi,
} from "@/controllers/API/personalToken"

// The owner picker fetches departments/users; it plays no part here.
vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  default: () => <div data-testid="owner-select" />,
}))

vi.mock("@/controllers/API/serviceAccount", () => ({
  createServiceAccountApi: vi.fn(),
  deleteServiceAccountApi: vi.fn(),
  listServiceAccountResourceGrantsApi: vi.fn(),
  setServiceAccountEnabledApi: vi.fn(),
  updateServiceAccountApi: vi.fn(),
}))

vi.mock("@/controllers/API/personalToken", () => ({
  getPersonalTokenSettingApi: vi.fn(),
  listPersonalTokensApi: vi.fn(),
  revokePersonalTokenApi: vi.fn(),
  revokePersonalTokensByHolderApi: vi.fn(),
  updatePersonalTokenSettingApi: vi.fn(),
}))

const renderWithTenancy = (ui: ReactElement, multiTenantEnabled: boolean) =>
  render(
    <locationContext.Provider value={{ appConfig: { multiTenantEnabled } } as never}>
      {ui}
    </locationContext.Provider>,
  )

const CREATE_HINT = "openApiManagement.serviceAccount.createHint"
const CREATE_HINT_SINGLE = "openApiManagement.serviceAccount.createHintSingle"
const TENANT_FIELD = "openApiManagement.fields.tenant"
const SETTINGS = "openApiManagement.personalToken.settings"
const SETTINGS_SINGLE = "openApiManagement.personalToken.settingsSingle"

const account: ServiceAccountItem = {
  id: 2,
  tenant_id: 1,
  name: "integration",
  description: null,
  status: "enabled",
  resource_owner: { user_id: 10, user_name: "owner", disabled: false },
  active_key_count: 1,
  has_delegate: false,
  delegate_scopes: [],
  last_used_at: null,
  idle: false,
  created_by: 1,
  creator_name: "admin",
  create_time: null,
  update_time: null,
}

const setting: PersonalTokenSetting = {
  deployment_enabled: true,
  pat_enabled: false,
  effective_enabled: false,
  pat_ttl_days: 30,
  data_scope: "all_visible",
}

describe("CreateServiceAccountDialog tenant copy", () => {
  it("single-tenant: the owner hint drops the 'in this tenant' qualifier", () => {
    renderWithTenancy(
      <CreateServiceAccountDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />,
      false,
    )
    expect(screen.getByText(CREATE_HINT_SINGLE)).toBeInTheDocument()
    expect(screen.queryByText(CREATE_HINT)).toBeNull()
  })

  it("multi-tenant: the tenant-scoped hint stays", () => {
    renderWithTenancy(
      <CreateServiceAccountDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />,
      true,
    )
    expect(screen.getByText(CREATE_HINT)).toBeInTheDocument()
    expect(screen.queryByText(CREATE_HINT_SINGLE)).toBeNull()
  })
})

describe("OverviewTab tenant field", () => {
  it("single-tenant: no tenant field on the account overview", () => {
    renderWithTenancy(
      <OverviewTab detail={account} onChanged={vi.fn()} onDeleted={vi.fn()} />,
      false,
    )
    expect(screen.queryByText(TENANT_FIELD)).toBeNull()
    // The rest of the overview is untouched.
    expect(screen.getByText("openApiManagement.fields.owner")).toBeInTheDocument()
  })

  it("multi-tenant: the tenant field shows the account's tenant", () => {
    renderWithTenancy(
      <OverviewTab detail={account} onChanged={vi.fn()} onDeleted={vi.fn()} />,
      true,
    )
    expect(screen.getByText(TENANT_FIELD)).toBeInTheDocument()
    expect(screen.getByText(String(account.tenant_id))).toBeInTheDocument()
  })
})

describe("PersonalToken policy heading", () => {
  beforeEach(() => {
    vi.mocked(getPersonalTokenSettingApi).mockResolvedValue(setting)
    vi.mocked(listPersonalTokensApi).mockResolvedValue({ data: [], total: 0 })
  })

  it("single-tenant: reads as a token policy, not a tenant policy", async () => {
    renderWithTenancy(<PersonalToken />, false)
    expect(await screen.findByText(SETTINGS_SINGLE)).toBeInTheDocument()
    expect(screen.queryByText(SETTINGS)).toBeNull()
  })

  it("multi-tenant: keeps the per-tenant wording", async () => {
    renderWithTenancy(<PersonalToken />, true)
    expect(await screen.findByText(SETTINGS)).toBeInTheDocument()
    expect(screen.queryByText(SETTINGS_SINGLE)).toBeNull()
  })
})
