import userEvent from "@testing-library/user-event"
import type { InputHTMLAttributes } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { message } from "@/components/bs-ui/toast/use-toast"
import {
  listServiceAccountGrantableResourcesApi,
  listServiceAccountKeysApi,
  listServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import {
  getGrantablePermissionModelsApi,
  getResourcePermissionContextApi,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ResourceGrantDialog } from "@/pages/SystemPage/components/ServiceAccount/ResourceGrantDialog"
import { ResourceGrantsTab } from "@/pages/SystemPage/components/ServiceAccount/ResourceGrantsTab"
import {
  formatServiceAccountGrantTime,
  isServiceAccountGrantEffective,
  SERVICE_ACCOUNT_PERMISSION_TIERS,
  SERVICE_ACCOUNT_RESOURCE_TYPES,
} from "@/pages/SystemPage/components/ServiceAccount/resourceGrantUtils"
import { render, screen, waitFor, within } from "@/test/test-utils"
import type {
  ApiKeyItem,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi"
import { copyText } from "@/utils"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const value = options ? Object.values(options)[0] : undefined
      return value === undefined ? key : `${key}:${String(value)}`
    },
  }),
}))

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
  captureAndAlertRequestErrorHoc: vi.fn(),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  message: vi.fn(),
  toast: vi.fn(),
}))

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: (props: InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
}))

vi.mock("@/components/bs-icons", () => ({
  LoadIcon: () => <span data-testid="load-icon" />,
  PlusIcon: () => <span data-testid="plus-icon" />,
  ThunmbIcon: () => <span data-testid="copy-icon" />,
  TipIcon: () => <span data-testid="tip-icon" />,
  TrashIcon: () => <span data-testid="trash-icon" />,
}))

vi.mock("@/utils", () => ({
  copyText: vi.fn(),
}))

function grant(
  values: Partial<ServiceAccountResourceGrant>,
): ServiceAccountResourceGrant {
  return {
    resource_type: "knowledge_library",
    resource_id: "1042",
    resource_name: "Contract library",
    model_key: "manager",
    model_name: "Manager",
    assignee_id: "grant-1",
    assignee_version: 1,
    source_type: "CREATOR_GRANT",
    granted_at: "2026-09-01T10:22:00",
    protected: false,
    editable: true,
    ...values,
  }
}

function apiKey(scopes: string[]): ApiKeyItem {
  return {
    id: 1,
    subject_kind: "service_account",
    subject_id: 7,
    name: "Integration key",
    key_mask: "sk-****",
    scopes,
    expires_at: null,
    revoked_at: null,
    last_used_at: null,
    revoke_reason: null,
    is_valid: true,
    create_time: null,
    delegate_scopes: [],
  }
}

const creatorGrant = grant({})
const directGrant = grant({
  resource_id: "8",
  resource_name: "Company policy library",
  model_key: "viewer",
  model_name: "Viewer",
  assignee_id: "grant-2",
  source_type: "DIRECT",
})
const workflowGrant = grant({
  resource_type: "workflow",
  resource_id: "21",
  resource_name: "Reimbursement workflow",
  model_key: "editor",
  model_name: "Editor",
  assignee_id: "grant-3",
  source_type: "DIRECT",
})

describe("service-account resource grants", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listServiceAccountResourceGrantsApi).mockResolvedValue([
      creatorGrant,
      directGrant,
      workflowGrant,
    ])
    vi.mocked(listServiceAccountKeysApi).mockResolvedValue([
      apiKey(["knowledge:read", "knowledge:write"]),
    ])
    vi.mocked(listServiceAccountGrantableResourcesApi).mockResolvedValue([])
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([])
    vi.mocked(getResourcePermissionContextApi).mockResolvedValue({
      mode: "CUSTOM",
      parent_type: null,
      parent_id: null,
      resource_version: 1,
      catalog_release_id: 1,
      projection_state: "READY",
      can_manage_permission: true,
    })
    vi.mocked(captureAndAlertRequestErrorHoc).mockImplementation(
      async (request) => {
        try {
          return await request
        } catch {
          return undefined
        }
      },
    )
    vi.mocked(copyText).mockResolvedValue(undefined)
  })

  it("renders the requested columns, effective state, copy action, and count", async () => {
    const user = userEvent.setup()
    render(
      <ResourceGrantsTab
        serviceAccountId={7}
        serviceAccountName="Application test"
      />,
    )

    const creatorName = await screen.findByText("Contract library")
    expect(screen.getByText("openApiManagement.grants.model")).toBeVisible()
    expect(screen.getByText("openApiManagement.grants.grantedAt")).toBeVisible()
    expect(
      screen.getAllByText("openApiManagement.grants.effectiveActive"),
    ).toHaveLength(2)
    expect(
      screen.getByText("openApiManagement.grants.ineffective"),
    ).toBeVisible()
    expect(screen.getByText("openApiManagement.grants.total:3")).toBeVisible()

    const creatorRow = creatorName.closest("tr")
    expect(creatorRow).not.toBeNull()
    await user.click(
      within(creatorRow!).getByRole("button", {
        name: "openApiManagement.grants.copyResource:Contract library",
      }),
    )
    expect(copyText).toHaveBeenCalledWith("knowledge_library:1042")
    expect(message).toHaveBeenCalledWith(
      expect.objectContaining({
        className: expect.stringContaining("bottom-6"),
        description:
          "openApiManagement.feedback.resourceCopied:knowledge_library:1042",
      }),
    )

    await user.type(
      screen.getByRole("textbox", {
        name: "openApiManagement.grants.resourceSearch",
      }),
      "Reimbursement",
    )
    expect(screen.queryByText("Contract library")).not.toBeInTheDocument()
    expect(screen.getByText("Reimbursement workflow")).toBeVisible()
    expect(screen.getByText("openApiManagement.grants.total:1")).toBeVisible()
  })

  it("uses distinct creator and direct single-revoke dialogs", async () => {
    const user = userEvent.setup()
    render(
      <ResourceGrantsTab
        serviceAccountId={7}
        serviceAccountName="Application test"
      />,
    )

    const creatorRow = (await screen.findByText("Contract library")).closest(
      "tr",
    )
    await user.click(
      within(creatorRow!).getByRole("button", {
        name: "openApiManagement.grants.revokeResource:Contract library",
      }),
    )
    let dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("openApiManagement.grants.creatorRevokeTitle"),
    ).toBeVisible()
    expect(
      within(dialog).getByText(
        "openApiManagement.grants.creatorRevokeConfirm:Contract library",
      ),
    ).toBeVisible()
    expect(
      within(dialog).getByText("openApiManagement.grants.revokeAnyway"),
    ).toBeVisible()
    await user.click(within(dialog).getByText("cancel"))

    const directRow = screen.getByText("Company policy library").closest("tr")
    await user.click(
      within(directRow!).getByRole("button", {
        name: "openApiManagement.grants.revokeResource:Company policy library",
      }),
    )
    dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("openApiManagement.grants.revokeTitle"),
    ).toBeVisible()
    expect(
      within(dialog).getByText(
        "openApiManagement.grants.revokeConfirm:Company policy library",
      ),
    ).toBeVisible()
    expect(
      within(dialog).getByText("openApiManagement.permissionTiers.viewer"),
    ).toBeVisible()
    expect(
      within(dialog).getByText("openApiManagement.grants.directSourceDetail"),
    ).toBeVisible()
    await user.click(within(dialog).getByText("cancel"))

    const workflowRow = screen.getByText("Reimbursement workflow").closest("tr")
    await user.click(
      within(workflowRow!).getByRole("button", {
        name: "openApiManagement.grants.revokeResource:Reimbursement workflow",
      }),
    )
    dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText(
        "openApiManagement.grants.revokeConfirm:Reimbursement workflow",
      ),
    ).toBeVisible()
    expect(
      within(dialog).getByText("openApiManagement.permissionTiers.editor"),
    ).toBeVisible()
  })

  it("filters grants by resource type and source", async () => {
    const user = userEvent.setup()
    render(
      <ResourceGrantsTab
        serviceAccountId={7}
        serviceAccountName="Application test"
      />,
    )

    await screen.findByText("Contract library")
    await user.click(
      screen.getByLabelText("openApiManagement.grants.typeFilter"),
    )
    await user.click(
      await screen.findByRole("option", {
        name: "openApiManagement.resourceTypes.workflow",
      }),
    )
    expect(screen.getByText("Reimbursement workflow")).toBeVisible()
    expect(screen.queryByText("Contract library")).toBeNull()
    expect(screen.getByText("openApiManagement.grants.total:1")).toBeVisible()

    await user.click(
      screen.getByLabelText("openApiManagement.grants.typeFilter"),
    )
    await user.click(
      await screen.findByRole("option", {
        name: "openApiManagement.grants.allTypes",
      }),
    )
    await user.click(
      screen.getByLabelText("openApiManagement.grants.sourceFilter"),
    )
    await user.click(
      await screen.findByRole("option", {
        name: "openApiManagement.grantSources.DIRECT",
      }),
    )
    expect(screen.queryByText("Contract library")).toBeNull()
    expect(screen.getByText("Company policy library")).toBeVisible()
    expect(screen.getByText("Reimbursement workflow")).toBeVisible()
    expect(screen.getByText("openApiManagement.grants.total:2")).toBeVisible()
  })

  it("lists direct grants and retains creator grants in bulk revoke", async () => {
    const user = userEvent.setup()
    render(
      <ResourceGrantsTab
        serviceAccountId={7}
        serviceAccountName="Application test"
      />,
    )

    await screen.findByText("Contract library")
    await user.click(
      screen.getByRole("button", {
        name: "openApiManagement.grants.revokeAll",
      }),
    )
    const dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("openApiManagement.grants.revokeAllTitle"),
    ).toBeVisible()
    expect(within(dialog).getByText("Company policy library")).toBeVisible()
    expect(within(dialog).getByText("Reimbursement workflow")).toBeVisible()
    expect(within(dialog).queryByText("Contract library")).toBeNull()
    expect(
      within(dialog).getByText(
        "openApiManagement.grants.revokeAllRetainedTitle:1",
      ),
    ).toBeVisible()
    expect(
      within(dialog).getByText("openApiManagement.grants.revokeCount:2"),
    ).toBeVisible()
  })

  it("restricts add-resource types and permission tiers and names the account", async () => {
    vi.mocked(listServiceAccountGrantableResourcesApi).mockResolvedValue([
      {
        resource_type: "knowledge_library",
        resource_id: "99",
        resource_name: "Available library",
        mode: "CUSTOM",
        resource_version: 1,
      },
    ])
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      { key: "owner", name: "Owner", level: 4, active: true },
      { key: "manager", name: "Manager", level: 3, active: true },
      { key: "viewer", name: "Viewer", level: 1, active: true },
      { key: "editor", name: "Editor", level: 2, active: true },
    ])
    const user = userEvent.setup()

    render(
      <ResourceGrantDialog
        serviceAccountId={7}
        serviceAccountName="Application test"
        existingGrants={[]}
        editingGrant={null}
        open
        onOpenChange={vi.fn()}
        onGranted={vi.fn()}
      />,
    )

    expect(
      screen.getByText(
        "openApiManagement.grants.fixedSubjectHint:Application test",
      ),
    ).toBeVisible()
    await user.click(
      screen.getByLabelText("openApiManagement.grants.resourceType"),
    )
    expect(await screen.findAllByRole("option")).toHaveLength(
      SERVICE_ACCOUNT_RESOURCE_TYPES.length,
    )
    await user.keyboard("{Escape}")

    await user.click(await screen.findByRole("checkbox"))
    await waitFor(() =>
      expect(getGrantablePermissionModelsApi).toHaveBeenCalledWith(
        "knowledge_library",
        "99",
      ),
    )
    await user.click(screen.getByLabelText("openApiManagement.grants.model"))
    expect(await screen.findAllByRole("option")).toHaveLength(
      SERVICE_ACCOUNT_PERMISSION_TIERS.length,
    )
    expect(screen.queryByRole("option", { name: /owner/i })).toBeNull()
  })

  it("requires an active key with the matching non-delegate scope", () => {
    expect(formatServiceAccountGrantTime("2026-09-01T10:22:00")).toBe(
      "2026-09-01 10:22",
    )
    expect(
      isServiceAccountGrantEffective(directGrant, [apiKey(["knowledge:read"])]),
    ).toBe(true)
    expect(
      isServiceAccountGrantEffective(workflowGrant, [
        apiKey(["workflow:read"]),
      ]),
    ).toBe(false)
    expect(
      isServiceAccountGrantEffective(directGrant, [
        apiKey(["delegate", "knowledge:read"]),
      ]),
    ).toBe(false)
  })
})
