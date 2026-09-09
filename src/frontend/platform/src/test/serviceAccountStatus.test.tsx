import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  getServiceAccountApi,
  listServiceAccountsApi,
  setServiceAccountEnabledApi,
} from "@/controllers/API/serviceAccount"
import { ServiceAccount } from "@/pages/SystemPage/components/ServiceAccount"
import { render, screen } from "@/test/test-utils"
import type { ServiceAccountItem, ServiceAccountStatus } from "@/types/api/openApi"

vi.mock("@/controllers/API/serviceAccount", () => ({
  deleteServiceAccountApi: vi.fn(),
  getServiceAccountApi: vi.fn(),
  listServiceAccountsApi: vi.fn(),
  setServiceAccountEnabledApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: () => null,
}))

vi.mock("@/pages/SystemPage/components/ServiceAccount/ApiKeysTab", () => ({
  ApiKeysTab: () => null,
}))

vi.mock("@/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog", () => ({
  CreateServiceAccountDialog: () => null,
}))

vi.mock("@/pages/SystemPage/components/ServiceAccount/ResourceGrantsTab", () => ({
  ResourceGrantsTab: () => null,
}))

function account(status: ServiceAccountStatus): ServiceAccountItem {
  return {
    id: 2,
    tenant_id: 1,
    name: "integration",
    description: null,
    status,
    resource_owner: { user_id: 10, user_name: "owner", disabled: false },
    active_key_count: 1,
    last_used_at: null,
    idle: false,
    created_by: 1,
    create_time: null,
    update_time: null,
  }
}

async function openAccountDetail(item: ServiceAccountItem) {
  vi.mocked(listServiceAccountsApi).mockResolvedValue({ data: [item], total: 1, idle_days: 30 })
  vi.mocked(getServiceAccountApi).mockResolvedValue(item)

  const user = userEvent.setup()
  render(<ServiceAccount />)
  await user.click(await screen.findByRole("button", { name: "openApiManagement.actions.details" }))
  return user
}

describe("service-account status", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows an enabled account and sends the disable action", async () => {
    const enabled = account("enabled")
    const disabled = account("disabled")
    const user = await openAccountDetail(enabled)
    vi.mocked(setServiceAccountEnabledApi).mockResolvedValue(disabled)

    expect(screen.getByText("openApiManagement.status.enabled")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "openApiManagement.actions.disable" }))

    expect(setServiceAccountEnabledApi).toHaveBeenCalledWith(2, false)
    expect(await screen.findByText("openApiManagement.status.disabled")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "openApiManagement.actions.enable" })).toBeInTheDocument()
  })

  it("shows a disabled account and sends the enable action", async () => {
    const disabled = account("disabled")
    const enabled = account("enabled")
    const user = await openAccountDetail(disabled)
    vi.mocked(setServiceAccountEnabledApi).mockResolvedValue(enabled)

    expect(screen.getByText("openApiManagement.status.disabled")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "openApiManagement.actions.enable" }))

    expect(setServiceAccountEnabledApi).toHaveBeenCalledWith(2, true)
    expect(await screen.findByText("openApiManagement.status.enabled")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "openApiManagement.actions.disable" })).toBeInTheDocument()
  })
})
