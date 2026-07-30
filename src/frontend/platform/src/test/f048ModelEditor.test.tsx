import { ImpactDialog } from "@/pages/SystemPage/components/permission/ImpactDialog"
import { ModelEditor } from "@/pages/SystemPage/components/permission/ModelEditor"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
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
    blockers: [],
    expires_at: "2026-07-29T13:00:00Z",
  },
}

describe("ModelEditor", () => {
  const onCreateDraft = vi.fn()
  const onReviewImpact = vi.fn()
  const onInitializePreset = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    onCreateDraft.mockResolvedValue(draft)
  })

  it("keeps standard fields read-only but allows eligible same-level policy", async () => {
    render(
      <ModelEditor
        model={standardModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
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
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "SET_ALLOW_SAME_LEVEL",
        model_key: "manager",
        allow_same_level: true,
      })
    })
  })

  it("edits custom actions and recalculates the derived level in real time", async () => {
    render(
      <ModelEditor
        model={customModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByTestId("model-derived-level")).toHaveTextContent("3")
    expect(screen.queryByLabelText("model.action.unassigned")).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("model.name"), {
      target: { value: "Workflow collaborator" },
    })
    fireEvent.click(screen.getByLabelText("model.action.edit"))
    fireEvent.click(screen.getByLabelText("model.action.manage_permission"))
    expect(screen.getByTestId("model-derived-level")).toHaveTextContent("2")
    fireEvent.click(screen.getByLabelText("model.active"))
    fireEvent.click(screen.getByRole("button", { name: "model.save" }))

    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "UPDATE_MODEL",
        model_key: "collaborator",
        name: "Workflow collaborator",
        action_codes: ["visible", "edit"],
        active: false,
        allow_same_level: false,
      })
    })
    expect(screen.getByTestId("model-derived-level")).toHaveTextContent("2")
  })

  it("disables same-level without manage_permission and copies preset actions", () => {
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
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByLabelText("model.allowSameLevel")).toBeDisabled()
    fireEvent.change(screen.getByLabelText("model.preset.label"), {
      target: { value: "reviewer" },
    })
    fireEvent.click(
      screen.getByRole("button", { name: "model.preset.apply" }),
    )
    expect(onInitializePreset).toHaveBeenCalledWith({
      key: "reviewer",
      name: "Reviewer",
      action_codes: ["visible", "edit"],
    })
    expect(screen.getByLabelText("model.action.edit")).toBeChecked()
    expect(screen.getByTestId("model-derived-level")).toHaveTextContent("2")
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
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "CREATE_MODEL",
        name: "Reviewer",
        action_codes: ["visible"],
        active: true,
        allow_same_level: false,
      })
    })
  })

  it("allows deletion only after a custom model is inactive", async () => {
    const { rerender } = render(
      <ModelEditor
        model={customModel}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(
      screen.getByRole("button", { name: "model.delete" }),
    ).toBeDisabled()

    rerender(
      <ModelEditor
        model={{ ...customModel, active: false }}
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: "model.delete" }))
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "DELETE_MODEL",
        model_key: "collaborator",
      })
    })
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

    expect(screen.getByTestId("impact-resource-count")).toHaveTextContent("8")
    expect(screen.getByTestId("impact-grant-count")).toHaveTextContent("5")
    expect(screen.getByTestId("impact-assignee-count")).toHaveTextContent("12")
    expect(screen.getByTestId("impact-revocation-count")).toHaveTextContent("3")

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
