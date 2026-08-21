import { PermissionGrantTab } from "@/components/bs-comp/permission/PermissionGrantTab"
import {
  getGrantablePermissionModelsApi,
  mutateResourceGrantsApi,
  type PermissionGrantAssignee,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/permission", () => ({
  getGrantablePermissionModelsApi: vi.fn(),
  mutateResourceGrantsApi: vi.fn(),
}))

vi.mock("@/components/bs-comp/permission/SubjectSearchUser", () => ({
  SubjectSearchUser: (props: {
    value: Array<{ type: "user"; id: number; name: string }>
    onChange: (
      value: Array<{ type: "user"; id: number; name: string }>,
    ) => void
  }) => (
    <button
      type="button"
      onClick={() =>
        props.onChange([{ type: "user", id: 9, name: "Alice" }])
      }
    >
      select-alice
    </button>
  ),
}))

vi.mock("@/components/bs-comp/permission/SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: () => <div>department-picker</div>,
}))

vi.mock("@/components/bs-comp/permission/SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: () => <div>group-picker</div>,
}))

const context: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: null,
  parent_id: null,
  resource_version: 8,
  catalog_release_id: 14,
  projection_state: "READY",
  can_manage_permission: true,
}

const editableAssignee: PermissionGrantAssignee = {
  assignee_id: "41",
  assignee_version: 2,
  subject: { type: "user", id: "10", name: "Bob" },
  model: { key: "viewer", name: "Viewer", level: 1, active: true },
  source: { type: "DIRECT", include_children: false },
  scope: "LOCAL",
  inherited_from: null,
  protected: false,
  editable: true,
}

const protectedAssignee: PermissionGrantAssignee = {
  ...editableAssignee,
  assignee_id: "42",
  assignee_version: 5,
  subject: { type: "user", id: "11", name: "Creator" },
  model: { key: "owner", name: "Owner", level: 4, active: true },
  protected: true,
  editable: false,
}

describe("F048 PermissionGrantTab", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      { key: "viewer", name: "Viewer", level: 1, active: true },
      { key: "editor", name: "Editor", level: 2, active: true },
      { key: "owner", name: "Owner", level: 4, active: true },
    ])
    vi.mocked(mutateResourceGrantsApi).mockResolvedValue({
      resource_version: 9,
      items: [],
    })
  })

  it("keeps the legacy add-dialog layout while submitting an F048 mutation", async () => {
    render(
      <PermissionGrantTab
        resourceType="workflow"
        resourceId="flow-1"
        context={context}
        fixedSubjectType="user"
        legacyAddLayout
        showExistingAssignees={false}
        onSuccess={vi.fn()}
      />,
    )

    expect(
      await screen.findByTestId("legacy-permission-grant-layout"),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "select-alice" }))
    fireEvent.change(screen.getByLabelText("grant.addModel"), {
      target: { value: "editor" },
    })
    fireEvent.click(screen.getByRole("button", { name: "grant.submit" }))

    await waitFor(() => {
      expect(mutateResourceGrantsApi).toHaveBeenCalledWith(
        "workflow",
        "flow-1",
        expect.objectContaining({
          expected_resource_version: 8,
          expected_catalog_release_id: 14,
          changes: [
            {
              op: "ADD",
              model_key: "editor",
              subject: { type: "user", id: "9" },
            },
          ],
        }),
      )
    })
  })

  it("submits ADD with only a stable model key and subject contract", async () => {
    render(
      <PermissionGrantTab
        resourceType="workflow"
        resourceId="flow-1"
        context={context}
        onSuccess={vi.fn()}
      />,
    )

    expect(await screen.findByText("Editor")).toBeInTheDocument()
    expect(screen.getByText("Owner")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "select-alice" }))
    fireEvent.change(screen.getByLabelText("grant.addModel"), {
      target: { value: "editor" },
    })
    fireEvent.click(screen.getByRole("button", { name: "grant.submit" }))

    await waitFor(() => {
      expect(mutateResourceGrantsApi).toHaveBeenCalledWith(
        "workflow",
        "flow-1",
        {
          idempotency_key: expect.stringMatching(/^grant-mutate-/),
          expected_resource_version: 8,
          expected_catalog_release_id: 14,
          changes: [
            {
              op: "ADD",
              model_key: "editor",
              subject: {
                type: "user",
                id: "9",
              },
            },
          ],
        },
      )
    })
    const payload = vi.mocked(mutateResourceGrantsApi).mock.calls[0][2]
    expect(payload.changes[0]).not.toHaveProperty("source")
    expect(payload.changes[0]).not.toHaveProperty("protected")
    expect(payload.changes[0]).not.toHaveProperty("level")
    expect(payload.changes[0]).not.toHaveProperty("derived_level")
  })

  it("moves an editable assignee using its stable id and version", async () => {
    render(
      <PermissionGrantTab
        resourceType="workflow"
        resourceId="flow-1"
        context={context}
        assignees={[editableAssignee, protectedAssignee]}
        onSuccess={vi.fn()}
      />,
    )

    fireEvent.change(
      await screen.findByLabelText("grant.model.41"),
      { target: { value: "editor" } },
    )
    fireEvent.click(screen.getByRole("button", { name: "grant.move.41" }))

    await waitFor(() => {
      expect(mutateResourceGrantsApi).toHaveBeenCalledWith(
        "workflow",
        "flow-1",
        expect.objectContaining({
          changes: [
            {
              op: "MOVE",
              assignee_id: "41",
              expected_assignee_version: 2,
              target_model_key: "editor",
            },
          ],
        }),
      )
    })
    expect(screen.getByLabelText("grant.model.42")).toBeDisabled()
    expect(screen.getByRole("button", { name: "grant.remove.42" })).toBeDisabled()
  })

  it("removes exactly one editable assignee and reports stale conflicts", async () => {
    vi.mocked(mutateResourceGrantsApi).mockRejectedValueOnce(
      new Error("stale resource version"),
    )
    render(
      <PermissionGrantTab
        resourceType="workflow"
        resourceId="flow-1"
        context={context}
        assignees={[editableAssignee]}
        onSuccess={vi.fn()}
      />,
    )

    fireEvent.click(
      await screen.findByRole("button", { name: "grant.remove.41" }),
    )
    await waitFor(() => {
      expect(mutateResourceGrantsApi).toHaveBeenCalledWith(
        "workflow",
        "flow-1",
        expect.objectContaining({
          changes: [
            {
              op: "REMOVE",
              assignee_id: "41",
              expected_assignee_version: 2,
            },
          ],
        }),
      )
      expect(screen.getByText("grant.conflict")).toBeInTheDocument()
    })
  })

  it("keeps an inactive existing row while excluding it from ADD and MOVE targets", async () => {
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValueOnce([
      { key: "viewer", name: "Viewer", level: 1, active: true },
      { key: "editor", name: "Editor", level: 2, active: true },
      { key: "retired-editor", name: "Retired editor", level: 3, active: false },
    ])
    const inactiveAssignee: PermissionGrantAssignee = {
      ...editableAssignee,
      model: {
        key: "retired-editor",
        name: "Retired editor",
        level: 3,
        active: false,
      },
    }
    render(
      <PermissionGrantTab
        resourceType="workflow"
        resourceId="flow-1"
        context={context}
        assignees={[inactiveAssignee]}
        onSuccess={vi.fn()}
      />,
    )

    const rowModel = await screen.findByLabelText("grant.model.41")
    expect(rowModel).toHaveValue("retired-editor")
    expect(rowModel).toHaveTextContent("Retired editor")
    expect(screen.getByLabelText("grant.addModel")).not.toHaveTextContent(
      "Retired editor",
    )

    fireEvent.change(rowModel, { target: { value: "editor" } })
    fireEvent.click(screen.getByRole("button", { name: "grant.move.41" }))
    await waitFor(() => {
      expect(mutateResourceGrantsApi).toHaveBeenCalledWith(
        "workflow",
        "flow-1",
        expect.objectContaining({
          changes: [
            {
              op: "MOVE",
              assignee_id: "41",
              expected_assignee_version: 2,
              target_model_key: "editor",
            },
          ],
        }),
      )
    })
  })
})
