import { locationContext } from "@/contexts/locationContext"
import { CreateServiceAccountDialog } from "@/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog"
import { render, screen } from "@/test/test-utils"
import { describe, expect, it, vi } from "vitest"

// The owner picker fetches departments/users; only its placeholder matters here.
vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  default: ({ placeholder }: { placeholder: string }) => (
    <div data-testid="owner-select">{placeholder}</div>
  ),
}))

vi.mock("@/controllers/API/serviceAccount", () => ({
  createServiceAccountApi: vi.fn(),
}))

const NEUTRAL_PLACEHOLDER = "create.resourceOwnerPlaceholder"
const TENANT_PLACEHOLDER = "create.resourceOwnerPlaceholderTenant"
const TENANT_FIXED_TIP = "create.tenantFixedTip"

function renderDialog(multiTenantEnabled: boolean) {
  return render(
    <locationContext.Provider value={{ appConfig: { multiTenantEnabled } } as never}>
      <CreateServiceAccountDialog open onClose={vi.fn()} onCreated={vi.fn()} />
    </locationContext.Provider>
  )
}

describe("CreateServiceAccountDialog tenant copy", () => {
  it("single-tenant: neutral owner placeholder, no tenant-fixed notice", () => {
    renderDialog(false)
    expect(screen.getByTestId("owner-select")).toHaveTextContent(NEUTRAL_PLACEHOLDER)
    expect(screen.getByTestId("owner-select")).not.toHaveTextContent(TENANT_PLACEHOLDER)
    expect(screen.queryByText(TENANT_FIXED_TIP)).toBeNull()
  })

  it("multi-tenant: tenant-scoped placeholder and the tenant-fixed notice stay", () => {
    renderDialog(true)
    expect(screen.getByTestId("owner-select")).toHaveTextContent(TENANT_PLACEHOLDER)
    expect(screen.getByText(TENANT_FIXED_TIP)).toBeInTheDocument()
  })
})
