import userEvent from "@testing-library/user-event"
import type { InputHTMLAttributes } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  listServiceAccountGrantableResourcesApi,
  listServiceAccountKeysApi,
  listServiceAccountResourceGrantsApi,
  mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import {
  getGrantablePermissionModelsApi,
  getResourcePermissionContextApi,
} from "@/controllers/API/permission"
import { ResourceGrantDialog } from "@/pages/SystemPage/components/ServiceAccount/ResourceGrantDialog"
import { ResourceGrantsTab } from "@/pages/SystemPage/components/ServiceAccount/ResourceGrantsTab"
import { render, screen, waitFor, within } from "@/test/test-utils"
import type { ServiceAccountResourceGrant } from "@/types/api/openApi"

vi.mock("@/controllers/API/serviceAccount", () => ({
  listServiceAccountGrantableResourcesApi: vi.fn(),
  listServiceAccountKeysApi: vi.fn(),
  listServiceAccountResourceGrantsApi: vi.fn(),
  mutateServiceAccountResourceGrantsApi: vi.fn(),
}))

vi.mock("@/controllers/API/permission", () => ({
  getGrantablePermissionModelsApi: vi.fn(),
  getResourcePermissionContextApi: vi.fn(),
}))

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: async (request: Promise<unknown>) =>
    request.catch(() => false),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  message: vi.fn(),
  toast: vi.fn(),
}))

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock("@/components/bs-icons", () => ({
  LoadIcon: () => <span />,
  PlusIcon: () => <span />,
  ThunmbIcon: () => <span />,
  TipIcon: () => <span />,
  TrashIcon: () => <span />,
}))

vi.mock("@/utils", () => ({ copyText: vi.fn() }))

const browserCrypto = globalThis.crypto
const directGrant: ServiceAccountResourceGrant = {
  resource_type: "knowledge_library",
  resource_id: "13",
  resource_name: "Available library",
  model_key: "viewer",
  model_name: "Viewer",
  assignee_id: "grant-13",
  assignee_version: 3,
  source_type: "DIRECT",
  granted_at: null,
  protected: false,
  editable: true,
}

describe("service-account grant mutations over HTTP", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // HTTP origins expose getRandomValues but do not expose randomUUID.
    vi.stubGlobal("crypto", {
      getRandomValues: browserCrypto.getRandomValues.bind(browserCrypto),
    })
    vi.mocked(listServiceAccountGrantableResourcesApi).mockResolvedValue([
      { ...directGrant, mode: "CUSTOM", resource_version: 1 },
    ])
    vi.mocked(listServiceAccountResourceGrantsApi).mockResolvedValue([directGrant])
    vi.mocked(listServiceAccountKeysApi).mockResolvedValue([])
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      { key: "viewer", name: "Viewer", level: 1, active: true },
      { key: "editor", name: "Editor", level: 2, active: true },
    ])
    vi.mocked(getResourcePermissionContextApi).mockResolvedValue({
      mode: "CUSTOM",
      parent_type: null,
      parent_id: null,
      resource_version: 5,
      catalog_release_id: 9,
      projection_state: "READY",
      can_manage_permission: true,
    })
    vi.mocked(mutateServiceAccountResourceGrantsApi).mockResolvedValue({
      resource_version: 6,
      items: [],
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  async function openGrantDialog(editingGrant: ServiceAccountResourceGrant | null = null) {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    const onGranted = vi.fn().mockResolvedValue(undefined)
    render(
      <ResourceGrantDialog
        serviceAccountId={7}
        serviceAccountName="Test account"
        existingGrants={[]}
        editingGrant={editingGrant}
        open
        onOpenChange={onOpenChange}
        onGranted={onGranted}
      />,
    )
    if (!editingGrant) await user.click(await screen.findByRole("checkbox"))
    const tier = screen.getByLabelText("openApiManagement.grants.model")
    await waitFor(() => expect(tier).toBeEnabled())
    await user.click(tier)
    await user.click(await screen.findByRole("option", {
      name: "openApiManagement.permissionTiers.editor",
    }))
    return { user, onOpenChange, onGranted }
  }

  it("submits the selected library with fresh versions and closes after refreshing", async () => {
    const { user, onOpenChange, onGranted } = await openGrantDialog()
    await user.click(screen.getByRole("button", {
      name: "openApiManagement.grants.confirmGrant",
    }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(mutateServiceAccountResourceGrantsApi).toHaveBeenCalledWith(
      7, "knowledge_library", "13", {
        idempotency_key: expect.any(String),
        expected_resource_version: 5,
        expected_catalog_release_id: 9,
        changes: [{ op: "ADD", model_key: "editor", subject: { type: "service_account", id: "7" } }],
      },
    )
    expect(onGranted).toHaveBeenCalledOnce()
    expect(onGranted.mock.invocationCallOrder[0]).toBeLessThan(onOpenChange.mock.invocationCallOrder[0])
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }))
  })

  it("updates a grant from the dialog without randomUUID", async () => {
    const { user, onOpenChange } = await openGrantDialog(directGrant)
    await user.click(screen.getByRole("button", { name: "confirmButton" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(mutateServiceAccountResourceGrantsApi).toHaveBeenCalledWith(
      7, "knowledge_library", "13", expect.objectContaining({
        changes: [{ op: "MOVE", assignee_id: "grant-13", expected_assignee_version: 3, target_model_key: "editor" }],
      }),
    )
  })

  it("keeps the selection and dialog open when the mutation fails", async () => {
    vi.mocked(mutateServiceAccountResourceGrantsApi).mockRejectedValueOnce(new Error("Mutation failed"))
    const { user, onOpenChange, onGranted } = await openGrantDialog()
    const submit = screen.getByRole("button", { name: "openApiManagement.grants.confirmGrant" })
    await user.click(submit)
    await waitFor(() => expect(onGranted).toHaveBeenCalledOnce())
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(screen.getByRole("checkbox")).toBeChecked()
    expect(submit).toBeEnabled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("updates the permission tier from the resource list without randomUUID", async () => {
    const user = userEvent.setup()
    render(<ResourceGrantsTab serviceAccountId={7} serviceAccountName="Test account" />)
    await screen.findByText("Available library")
    await user.click(screen.getByLabelText("openApiManagement.grants.changeTierFor"))
    await user.click(await screen.findByRole("option", { name: "openApiManagement.permissionTiers.editor" }))
    await waitFor(() => expect(listServiceAccountResourceGrantsApi).toHaveBeenCalledTimes(2))
    expect(mutateServiceAccountResourceGrantsApi).toHaveBeenCalledWith(
      7, "knowledge_library", "13", expect.objectContaining({
        changes: [{ op: "MOVE", assignee_id: "grant-13", expected_assignee_version: 3, target_model_key: "editor" }],
      }),
    )
  })

  it.each([false, true])("revokes resources and closes the confirmation (bulk: %s)", async (bulk) => {
    const user = userEvent.setup()
    render(<ResourceGrantsTab serviceAccountId={7} serviceAccountName="Test account" />)
    await screen.findByText("Available library")
    await user.click(screen.getByRole("button", {
      name: bulk ? "openApiManagement.grants.revokeAll" : "openApiManagement.grants.revokeResource",
    }))
    await user.click(within(screen.getByRole("dialog")).getByRole("button", {
      name: bulk ? "openApiManagement.grants.revokeCount" : "openApiManagement.actions.revoke",
    }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(mutateServiceAccountResourceGrantsApi).toHaveBeenCalledWith(
      7, "knowledge_library", "13", expect.objectContaining({
        changes: [{ op: "REMOVE", assignee_id: "grant-13", expected_assignee_version: 3 }],
      }),
    )
    expect(listServiceAccountResourceGrantsApi).toHaveBeenCalledTimes(2)
  })
})
