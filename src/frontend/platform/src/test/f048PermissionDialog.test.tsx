import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog"
import {
  applyResourcePermissionModeDraftApi,
  createResourcePermissionModeDraftApi,
  getMyResourcePermissionsApi,
  getResourcePermissionContextApi,
  getResourcePermissionGrantsApi,
} from "@/controllers/API/permission"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/permission", () => ({
  applyResourcePermissionModeDraftApi: vi.fn(),
  createResourcePermissionModeDraftApi: vi.fn(),
  getGrantablePermissionModelsApi: vi.fn(),
  getMyResourcePermissionsApi: vi.fn(),
  getResourcePermissionContextApi: vi.fn(),
  getResourcePermissionGrantsApi: vi.fn(),
  mutateResourceGrantsApi: vi.fn(),
}))

const customContext = {
  mode: "CUSTOM" as const,
  parent_type: "knowledge_space" as const,
  parent_id: "space-1",
  resource_version: 7,
  catalog_release_id: 12,
  projection_state: "READY",
  can_manage_permission: true,
}

const protectedAssignee = {
  assignee_id: 81,
  assignee_version: 4,
  subject: { type: "user" as const, id: "3", name: "Creator" },
  model: {
    key: "owner",
    name: "Owner",
    level: 4 as const,
    active: true,
  },
  source: { type: "CREATOR", include_children: false },
  scope: "LOCAL" as const,
  inherited_from: null,
  protected: true,
  editable: false,
}

describe("F048 PermissionDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getResourcePermissionContextApi).mockResolvedValue(customContext)
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [protectedAssignee],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    })
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["visible"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    })
    vi.mocked(createResourcePermissionModeDraftApi).mockResolvedValue({
      draft_id: "mode-draft-1",
      target_mode: "INHERIT",
      impact_checksum: "a".repeat(64),
      affected_assignees: 6,
      expires_at: "2099-07-29T13:00:00Z",
    })
    vi.mocked(applyResourcePermissionModeDraftApi).mockResolvedValue({
      applied: true,
      mode: "INHERIT",
      resource_version: 8,
    })
  })

  it("loads context first, then shows roster and protected state", async () => {
    render(
      <PermissionDialog
        open
        onOpenChange={vi.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Report"
      />,
    )

    expect(getResourcePermissionContextApi).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
    )
    expect(await screen.findByText("mode.custom")).toBeInTheDocument()
    expect(screen.getAllByText("knowledge_space:space-1").length).toBeGreaterThan(
      0,
    )
    expect(screen.getByTestId("permission-assignee-81")).toHaveTextContent(
      "roster.protected",
    )
    expect(getResourcePermissionGrantsApi).toHaveBeenCalled()
    expect(getMyResourcePermissionsApi).not.toHaveBeenCalled()
  })

  it("uses only the current-user summary when roster access is absent", async () => {
    vi.mocked(getResourcePermissionContextApi).mockResolvedValue({
      ...customContext,
      can_manage_permission: false,
    })

    render(
      <PermissionDialog
        open
        onOpenChange={vi.fn()}
        resourceType="workflow"
        resourceId="flow-1"
        resourceName="Flow"
      />,
    )

    expect(await screen.findByText("roster.summaryOnly")).toBeInTheDocument()
    expect(getMyResourcePermissionsApi).toHaveBeenCalledWith(
      "workflow",
      "flow-1",
    )
    expect(getResourcePermissionGrantsApi).not.toHaveBeenCalled()
    expect(
      screen.queryByRole("tab", { name: "dialog.manageGrants" }),
    ).toBeNull()
  })

  it("creates a mode impact, supports cancel, and applies only its draft", async () => {
    render(
      <PermissionDialog
        open
        onOpenChange={vi.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Report"
      />,
    )

    fireEvent.click(
      await screen.findByRole("button", { name: "mode.switchToInherit" }),
    )
    await waitFor(() => {
      expect(createResourcePermissionModeDraftApi).toHaveBeenCalledWith(
        "knowledge_file",
        "file-1",
        {
          target_mode: "INHERIT",
          expected_resource_version: 7,
          expected_catalog_release_id: 12,
        },
      )
    })
    expect(screen.getByTestId("mode-affected-assignees")).toHaveTextContent("6")
    fireEvent.click(screen.getByRole("button", { name: "mode.cancel" }))
    expect(applyResourcePermissionModeDraftApi).not.toHaveBeenCalled()

    fireEvent.click(
      screen.getByRole("button", { name: "mode.switchToInherit" }),
    )
    fireEvent.click(
      await screen.findByRole("button", { name: "mode.confirm" }),
    )
    await waitFor(() => {
      expect(applyResourcePermissionModeDraftApi).toHaveBeenCalledWith(
        "knowledge_file",
        "file-1",
        "mode-draft-1",
        {
          idempotency_key: expect.stringMatching(/^mode-apply-/),
          expected_resource_version: 7,
          expected_catalog_release_id: 12,
          confirmed: true,
        },
      )
    })
    expect(await screen.findAllByText("mode.inherit")).not.toHaveLength(0)
  })

  it("blocks expired previews and reports version conflicts", async () => {
    vi.mocked(createResourcePermissionModeDraftApi).mockResolvedValue({
      draft_id: "expired",
      target_mode: "INHERIT",
      impact_checksum: "b".repeat(64),
      affected_assignees: 2,
      expires_at: "2000-01-01T00:00:00Z",
    })

    render(
      <PermissionDialog
        open
        onOpenChange={vi.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Report"
      />,
    )
    fireEvent.click(
      await screen.findByRole("button", { name: "mode.switchToInherit" }),
    )

    expect(await screen.findByText("mode.expired")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "mode.confirm" })).toBeDisabled()
  })
})
