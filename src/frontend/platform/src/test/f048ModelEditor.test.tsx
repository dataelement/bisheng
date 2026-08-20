import { ImpactDialog } from "@/pages/SystemPage/components/permission/ImpactDialog"
import { ModelEditor } from "@/pages/SystemPage/components/permission/ModelEditor"
import { fireEvent, render, screen, selectOption, waitFor } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

const actions = [
  {
    code: "visible",
    name: "Visible",
    level: 1 as const,
    active: true,
    sort_order: 1,
    resource_types: ["workflow" as const],
  },
  {
    code: "edit",
    name: "Edit",
    level: 2 as const,
    active: true,
    sort_order: 2,
    resource_types: ["workflow" as const],
  },
  {
    code: "manage_permission",
    name: "Manage permission",
    level: 3 as const,
    active: true,
    sort_order: 3,
    resource_types: ["workflow" as const],
  },
  {
    code: "unassigned",
    name: "Unassigned",
    level: null,
    active: true,
    sort_order: 4,
    resource_types: ["workflow" as const],
  },
]

const standardModel = {
  key: "manager",
  name: "Manager",
  kind: "STANDARD" as const,
  config_scope: "PLATFORM" as const,
  derived_level: 3 as const,
  active: true,
  allow_same_level: false,
  action_codes: ["visible", "edit", "manage_permission"],
  version: 2,
}

const customModel = {
  key: "collaborator",
  name: "Collaborator",
  kind: "CUSTOM" as const,
  config_scope: "PLATFORM" as const,
  derived_level: 3 as const,
  active: true,
  allow_same_level: false,
  action_codes: ["visible", "manage_permission"],
  version: 4,
}

const draft = {
  draft_id: 13,
  base_release_id: 12,
  impact: {
    checksum: "c".repeat(64),
    resource_count: 8,
    grant_count: 5,
    assignee_count: 12,
    expansion_count: 2,
    revocation_count: 3,
    action_changes: [
      {
        action_code: "manage_permission",
        action_name: "Manage permission",
        before_level: 3 as const,
        after_level: 4 as const,
        before_active: true,
        after_active: true,
      },
    ],
    model_changes: [
      {
        model_key: "manager",
        model_name: "Manager",
        kind: "STANDARD" as const,
        before_level: 3 as const,
        after_level: 3 as const,
        added_action_codes: [],
        removed_action_codes: ["manage_permission"],
        affected_assignee_count: 12,
      },
      {
        model_key: "collaborator",
        model_name: "Collaborator",
        kind: "CUSTOM" as const,
        before_level: 3 as const,
        after_level: 4 as const,
        added_action_codes: [],
        removed_action_codes: [],
        affected_assignee_count: 0,
      },
    ],
    blockers: [],
    expires_at: "2026-07-29T13:00:00Z",
  },
}

const { confirmSpy } = vi.hoisted(() => ({ confirmSpy: vi.fn() }))

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: confirmSpy,
}))

describe("ModelEditor", () => {
  const onCreateDraft = vi.fn()
  const onDeleteModel = vi.fn()
  const onReviewImpact = vi.fn()
  const onInitializePreset = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    onCreateDraft.mockResolvedValue(draft)
    onDeleteModel.mockResolvedValue(draft)
    confirmSpy.mockImplementation(
      (params: { onOk?: (next: () => void) => void }) =>
        params.onOk?.(() => {}),
    )
  })

  it("keeps standard fields read-only but allows eligible same-level policy", async () => {
    render(
      <ModelEditor
        model={standardModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByLabelText("model.name")).toBeDisabled()
    expect(screen.getByLabelText("model.action.edit")).toBeDisabled()
    expect(screen.getByLabelText("model.active")).toBeDisabled()
    expect(screen.getByLabelText("model.allowSameLevel")).toBeEnabled()

    fireEvent.click(screen.getByLabelText("model.allowSameLevel"))
    fireEvent.click(screen.getByRole("button", { name: "model.save" }))

    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith([
        {
          type: "SET_ALLOW_SAME_LEVEL",
          model_key: "manager",
          allow_same_level: true,
        },
      ])
    })
  })

  it("edits custom actions and recalculates the derived level in real time", async () => {
    render(
      <ModelEditor
        model={customModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByTestId("model-derived-level")).toHaveAttribute("data-level", "3")
    expect(screen.queryByLabelText("model.action.unassigned")).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("model.name"), {
      target: { value: "Workflow collaborator" },
    })
    fireEvent.click(screen.getByLabelText("model.action.edit"))
    fireEvent.click(screen.getByLabelText("model.action.manage_permission"))
    expect(screen.getByTestId("model-derived-level")).toHaveAttribute("data-level", "2")
    fireEvent.click(screen.getByLabelText("model.active"))
    fireEvent.click(screen.getByRole("button", { name: "model.save" }))

    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith([
        {
          type: "UPDATE_MODEL",
          model_key: "collaborator",
          name: "Workflow collaborator",
          action_codes: ["visible", "edit"],
          active: false,
          allow_same_level: false,
        },
      ])
    })
    expect(screen.getByTestId("model-derived-level")).toHaveAttribute("data-level", "2")
  })

  it("disables same-level without manage_permission and copies preset actions", async () => {
    render(
      <ModelEditor
        model={{
          ...customModel,
          action_codes: ["visible"],
          derived_level: 1,
        }}
        actions={actions}
        presets={[
          {
            key: "reviewer",
            name: "Reviewer",
            action_codes: ["visible", "edit"],
          },
        ]}
        onInitializePreset={onInitializePreset}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByLabelText("model.allowSameLevel")).toBeDisabled()
    await selectOption("model.preset.label", "Reviewer")
    fireEvent.click(
      screen.getByRole("button", { name: "model.preset.apply" }),
    )
    expect(onInitializePreset).toHaveBeenCalledWith({
      key: "reviewer",
      name: "Reviewer",
      action_codes: ["visible", "edit"],
    })
    expect(screen.getByLabelText("model.action.edit")).toBeChecked()
    expect(screen.getByTestId("model-derived-level")).toHaveAttribute("data-level", "2")
  })

  it("offers a blank preset that clears the selection", async () => {
    // Picking the placeholder only disabled the button, so a model could gain
    // actions from a preset but never be emptied again.
    render(
      <ModelEditor
        model={{
          ...customModel,
          action_codes: ["visible", "edit"],
          derived_level: 2,
        }}
        actions={actions}
        presets={[
          { key: "reviewer", name: "Reviewer", action_codes: ["visible", "edit"] },
        ]}
        onInitializePreset={onInitializePreset}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByLabelText("model.action.edit")).toBeChecked()

    await selectOption("model.preset.label", "model.preset.blank")
    fireEvent.click(screen.getByRole("button", { name: "model.preset.apply" }))

    expect(screen.getByLabelText("model.action.edit")).not.toBeChecked()
    expect(screen.getByLabelText("model.action.visible")).not.toBeChecked()
    expect(onInitializePreset).toHaveBeenCalledWith({
      key: "__blank__",
      name: "model.preset.blank",
      action_codes: [],
    })
  })

  it("offers the blank preset even when the server ships none", async () => {
    render(
      <ModelEditor
        model={{ ...customModel, action_codes: ["edit"], derived_level: 2 }}
        actions={actions}
        presets={[]}
        onInitializePreset={onInitializePreset}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectOption("model.preset.label", "model.preset.blank")
    fireEvent.click(screen.getByRole("button", { name: "model.preset.apply" }))

    expect(screen.getByLabelText("model.action.edit")).not.toBeChecked()
  })

  it("creates only a non-empty custom model", async () => {
    render(
      <ModelEditor
        createMode
        model={{
          ...customModel,
          key: "__new_custom_model__",
          name: "",
          derived_level: null,
          action_codes: [],
          version: 0,
        }}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    const save = screen.getByRole("button", { name: "model.save" })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText("model.name"), {
      target: { value: "Reviewer" },
    })
    expect(save).toBeDisabled()
    fireEvent.click(screen.getByLabelText("model.action.visible"))
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith([
        {
          type: "CREATE_MODEL",
          name: "Reviewer",
          action_codes: ["visible"],
          active: true,
          allow_same_level: false,
        },
      ])
    })
  })

  it("says a drafted change is unpublished instead of implying it landed", async () => {
    // Saving drafts the change; nothing lands until it is published, and the
    // strip used to report only the impact volume.
    render(
      <ModelEditor
        model={{ ...customModel, active: false }}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    fireEvent.click(screen.getByLabelText("model.action.edit"))
    fireEvent.click(screen.getByRole("button", { name: "model.save" }))

    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent("impact.unpublished")
    expect(
      screen.getByRole("button", { name: "impact.publishChanges" }),
    ).toBeInTheDocument()
  })

  it("keeps active as an assignability switch rather than a deletion precondition", async () => {
    render(
      <ModelEditor
        model={customModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    const button = screen.getByRole("button", { name: "model.delete" })
    expect(screen.getByText("model.activeHint")).toBeInTheDocument()
    expect(screen.getByText("model.deleteRequirement")).toBeInTheDocument()
    expect(button).toBeEnabled()
    fireEvent.click(button)

    await waitFor(() => {
      expect(onDeleteModel).toHaveBeenCalledWith(customModel.key)
      expect(onReviewImpact).toHaveBeenCalledWith(draft)
    })
    expect(await screen.findByRole("status")).toHaveTextContent(
      "impact.pending",
    )
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it("shows the zero-reference guidance when deletion draft creation is blocked", async () => {
    onDeleteModel.mockRejectedValueOnce(new Error("25004"))
    render(
      <ModelEditor
        model={{ ...customModel, active: false }}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    const button = screen.getByRole("button", { name: "model.delete" })
    fireEvent.click(button)

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "model.deleteBlocked",
    )
    expect(onReviewImpact).not.toHaveBeenCalled()
  })

  it("blocks invalid custom selections until unavailable actions are removed", () => {
    render(
      <ModelEditor
        model={{
          ...customModel,
          action_codes: ["unassigned"],
          derived_level: null,
        }}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByLabelText("model.action.unassigned")).toBeChecked()
    expect(
      screen.getByRole("button", { name: "model.save" }),
    ).toBeDisabled()
    fireEvent.click(screen.getByLabelText("model.action.unassigned"))
    fireEvent.click(screen.getByLabelText("model.action.visible"))
    expect(
      screen.getByRole("button", { name: "model.save" }),
    ).toBeEnabled()
  })
})

describe("ImpactDialog", () => {
  const onPublish = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    onPublish.mockResolvedValue(undefined)
  })

  it("shows server impact and publishes only the confirmed draft identity", async () => {
    render(
      <ImpactDialog
        open
        draft={draft}
        onOpenChange={vi.fn()}
        onPublish={onPublish}
        now={new Date("2026-07-29T12:00:00Z")}
      />,
    )

    expect(screen.getByTestId("impact-assignee-count")).toHaveTextContent("12")
    expect(screen.getByText("impact.changeTitle")).toBeInTheDocument()
    expect(screen.getByText("level.manager")).toBeInTheDocument()
    expect(screen.getByText("Collaborator")).toBeInTheDocument()
    expect(screen.getByText("impact.customLevelOnly")).toBeInTheDocument()
    expect(screen.queryByText("impact.resources")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "impact.publish" }))
    await waitFor(() => {
      expect(onPublish).toHaveBeenCalledWith(13, {
        expected_current_release_id: 12,
        idempotency_key: expect.stringMatching(/^catalog-publish-/),
        confirmed: true,
      })
    })
  })

  it("blocks publish when the preview expired or has blockers", () => {
    const { rerender } = render(
      <ImpactDialog
        open
        draft={draft}
        onOpenChange={vi.fn()}
        onPublish={onPublish}
        now={new Date("2026-07-29T14:00:00Z")}
      />,
    )
    expect(screen.getByText("impact.expired")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "impact.publish" }),
    ).toBeDisabled()

    rerender(
      <ImpactDialog
        open
        draft={{
          ...draft,
          impact: { ...draft.impact, blockers: ["active model is empty"] },
        }}
        onOpenChange={vi.fn()}
        onPublish={onPublish}
        now={new Date("2026-07-29T12:00:00Z")}
      />,
    )
    expect(screen.getByText("active model is empty")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "impact.publish" }),
    ).toBeDisabled()
  })
})
