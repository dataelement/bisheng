import { ImpactDialog } from "@/pages/SystemPage/components/permission/ImpactDialog"
import { ModelCatalogPanel } from "@/pages/SystemPage/components/permission/ModelEditor"
import type { PermissionCatalogRelease } from "@/controllers/API/permission"
import { act, fireEvent, render, screen, waitFor, within } from "@/test/test-utils"
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

describe("ModelCatalogPanel", () => {
  const onCreateDraft = vi.fn()
  const onDeleteModel = vi.fn()
  const onReviewImpact = vi.fn()
  const catalog: PermissionCatalogRelease = {
    id: 12,
    release_key: "release-12",
    version: 12,
    status: "PUBLISHED",
    authorization_model_id: "fga-model-12",
    checksum: "a".repeat(64),
    actions,
    models: [standardModel, customModel],
    presets: [{ key: "reviewer", name: "Reviewer", action_codes: ["visible", "edit"] }],
  }

  function renderPanel(overrides: Partial<PermissionCatalogRelease> = {}) {
    render(
      <ModelCatalogPanel
        catalog={{ ...catalog, ...overrides }}
        onCreateDraft={onCreateDraft}
        onDeleteModel={onDeleteModel}
        onReviewImpact={onReviewImpact}
      />,
    )
  }

  function getRow(modelKey: string) {
    return within(screen.getByTestId("permission-model-" + modelKey))
  }

  function editRow(modelKey: string) {
    fireEvent.click(getRow(modelKey).getByRole("button", { name: "model.editNamed" }))
    return getRow(modelKey)
  }

  function confirmEdit(modelKey: string) {
    return getRow(modelKey).getByRole("button", { name: "confirm" })
  }

  beforeEach(() => {
    vi.clearAllMocks()
    onCreateDraft.mockResolvedValue(draft)
    onDeleteModel.mockResolvedValue(draft)
    confirmSpy.mockImplementation(
      ({ onOk }: { onOk?: (close: () => void) => unknown }) => onOk?.(() => {}),
    )
  })

  it("keeps standard action edits local and still saves the existing same-level policy", async () => {
    renderPanel()
    const standardEdit = getRow(standardModel.key).getByRole("checkbox", { name: "model.action.edit" })
    const customRow = getRow(customModel.key)
    expect(standardEdit).toBeChecked()
    expect(standardEdit).toBeDisabled()
    expect(customRow.queryByRole("checkbox", { name: "model.action.edit" })).not.toBeInTheDocument()

    const row = editRow(standardModel.key)
    const edit = row.getByRole("checkbox", { name: "model.action.edit" })
    const save = confirmEdit(standardModel.key)

    expect(row.getByText("level.manager")).toBeInTheDocument()
    expect(row.queryByRole("textbox", { name: "model.name" })).toBeNull()
    expect(row.getByLabelText("model.active")).toBeDisabled()
    expect(row.getByLabelText("model.allowSameLevel")).toBeEnabled()
    expect(edit).toBeChecked()
    expect(edit).toBeEnabled()
    expect(customRow.queryByRole("checkbox", { name: "model.action.edit" })).not.toBeInTheDocument()
    const customVisible = customRow.getByRole("checkbox", { name: "model.action.visible" })
    expect(customVisible).toBeChecked()
    expect(customVisible).toBeDisabled()

    fireEvent.click(edit)
    fireEvent.click(row.getByLabelText("model.allowSameLevel"))
    expect(edit).not.toBeChecked()
    expect(edit).toBeEnabled()
    expect(screen.queryByText("model.builtinActionPreview")).not.toBeInTheDocument()
    expect(save).toBeEnabled()
    fireEvent.click(save)
    expect(onCreateDraft).not.toHaveBeenCalled()
    expect(onReviewImpact).not.toHaveBeenCalled()
    expect(confirmEdit(standardModel.key)).toBeEnabled()
    expect(row.getByRole("checkbox", { name: "model.action.edit" })).not.toBeChecked()

    fireEvent.click(edit)
    expect(edit).toBeChecked()
    expect(save).toBeEnabled()
    fireEvent.click(save)

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
    renderPanel()
    const rowCount = screen.getAllByRole("row").length
    const row = editRow(customModel.key)

    expect(screen.getAllByRole("row")).toHaveLength(rowCount)
    expect(screen.queryByLabelText("model.preset.label")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "model.preset.apply" })).not.toBeInTheDocument()
    expect(row.getByTestId("model-derived-level")).toHaveAttribute("data-level", "3")
    expect(row.queryByLabelText("model.action.unassigned")).not.toBeInTheDocument()

    fireEvent.change(row.getByLabelText("model.name"), {
      target: { value: "Workflow collaborator" },
    })
    fireEvent.click(row.getByLabelText("model.action.edit"))
    fireEvent.click(row.getByLabelText("model.action.manage_permission"))
    expect(row.getByTestId("model-derived-level")).toHaveAttribute("data-level", "2")
    fireEvent.click(row.getByLabelText("model.active"))
    fireEvent.click(confirmEdit(customModel.key))

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
  })

  it("enables same-level only after the permission management action is selected", () => {
    renderPanel({
      models: [{ ...customModel, action_codes: ["visible"], derived_level: 1 }],
    })
    const row = editRow(customModel.key)

    expect(row.getByLabelText("model.allowSameLevel")).toBeDisabled()
    fireEvent.click(row.getByLabelText("model.action.edit"))

    expect(row.getByLabelText("model.action.edit")).toBeChecked()
    expect(row.getByTestId("model-derived-level")).toHaveAttribute("data-level", "2")
    expect(row.getByLabelText("model.allowSameLevel")).toBeDisabled()

    fireEvent.click(row.getByLabelText("model.action.manage_permission"))
    expect(row.getByLabelText("model.allowSameLevel")).toBeEnabled()
  })

  it("appends a new row and creates only a non-empty custom model", async () => {
    renderPanel()
    const rowCount = screen.getAllByRole("row").length
    fireEvent.click(screen.getByRole("button", { name: "model.create" }))
    const row = getRow("__new_custom_model__")
    const save = row.getByRole("button", { name: "confirm" })

    const rows = screen.getAllByRole("row")
    expect(rows).toHaveLength(rowCount + 1)
    expect(rows.at(-1)).toBe(screen.getByTestId("permission-model-__new_custom_model__"))
    expect(screen.queryByLabelText("model.preset.label")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "model.preset.apply" })).not.toBeInTheDocument()
    expect(save).toBeDisabled()
    fireEvent.change(row.getByLabelText("model.name"), {
      target: { value: "Reviewer" },
    })
    expect(save).toBeDisabled()
    fireEvent.click(row.getByLabelText("model.action.visible"))
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

  it("initializes a copy with the source actions and saves it as a new custom model", async () => {
    renderPanel()
    fireEvent.click(getRow(standardModel.key).getByRole("button", { name: "model.copyNamed" }))
    const row = getRow("__new_custom_model__")

    expect(row.getByLabelText("model.action.visible")).toBeChecked()
    expect(row.getByLabelText("model.action.edit")).toBeChecked()
    expect(row.getByLabelText("model.action.manage_permission")).toBeChecked()
    fireEvent.change(row.getByLabelText("model.name"), {
      target: { value: "Manager copy" },
    })
    fireEvent.click(row.getByRole("button", { name: "confirm" }))

    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith([
        {
          type: "CREATE_MODEL",
          name: "Manager copy",
          action_codes: ["visible", "edit", "manage_permission"],
          active: true,
          allow_same_level: false,
        },
      ])
    })
  })

  it("opens the impact confirmation using the server draft after editing", async () => {
    renderPanel()
    const row = editRow(customModel.key)

    fireEvent.click(row.getByLabelText("model.action.edit"))
    fireEvent.click(confirmEdit(customModel.key))

    await waitFor(() => expect(onReviewImpact).toHaveBeenCalledWith(draft, "modelEdit"))
  })

  it("cancels unchanged edits, new templates, and copies without a prompt", () => {
    renderPanel()
    const newRowId = "permission-model-__new_custom_model__"

    const row = editRow(customModel.key)
    fireEvent.click(row.getByRole("button", { name: "impact.cancel" }))
    expect(row.queryByLabelText("model.name")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "model.create" }))
    fireEvent.click(getRow("__new_custom_model__").getByRole("button", { name: "impact.cancel" }))
    expect(screen.queryByTestId(newRowId)).not.toBeInTheDocument()

    fireEvent.click(getRow(standardModel.key).getByRole("button", { name: "model.copyNamed" }))
    const copy = getRow("__new_custom_model__")
    expect(copy.getByLabelText("model.action.edit")).toBeChecked()
    fireEvent.click(copy.getByRole("button", { name: "impact.cancel" }))
    expect(screen.queryByTestId(newRowId)).not.toBeInTheDocument()
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it("keeps a renamed template open until discard is confirmed", () => {
    renderPanel()
    confirmSpy.mockImplementationOnce(() => {})
    const row = editRow(customModel.key)
    const name = row.getByLabelText("model.name")
    fireEvent.change(name, { target: { value: "Unsaved name" } })
    fireEvent.click(row.getByRole("button", { name: "impact.cancel" }))

    expect(confirmSpy).toHaveBeenCalledWith(expect.objectContaining({
      title: "model.unsavedTitle",
      desc: "model.discardUnsavedDescription",
      okTxt: "model.discard",
      canelTxt: "organization.keepEditing",
      variant: "default",
    }))
    const [[{ onCancel, onOk }]] = confirmSpy.mock.calls
    expect(onCancel).toBeUndefined()
    expect(name).toHaveValue("Unsaved name")
    expect(onCreateDraft).not.toHaveBeenCalled()

    const closePrompt = vi.fn()
    act(() => onOk(closePrompt))
    expect(closePrompt).toHaveBeenCalledOnce()
    expect(row.queryByLabelText("model.name")).not.toBeInTheDocument()
    expect(row.getByText(customModel.name)).toBeInTheDocument()
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it.each([
    "model.action.edit",
    "model.active",
    "model.allowSameLevel",
  ])("prompts when cancelling a changed %s and cancels directly once reverted", (label) => {
    renderPanel()
    confirmSpy.mockImplementationOnce(() => {})
    const row = editRow(customModel.key)
    const cancel = row.getByRole("button", { name: "impact.cancel" })
    const control = row.getByLabelText(label)

    fireEvent.click(control)
    fireEvent.click(cancel)
    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(row.getByLabelText("model.name")).toBeInTheDocument()

    fireEvent.click(control)
    fireEvent.click(cancel)
    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(row.queryByLabelText("model.name")).not.toBeInTheDocument()
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it("keeps the edited row open until the unsaved changes prompt is resolved", () => {
    renderPanel()
    confirmSpy.mockImplementationOnce(() => {})
    const row = editRow(customModel.key)

    fireEvent.change(row.getByLabelText("model.name"), {
      target: { value: "Unsaved name" },
    })
    editRow(standardModel.key)

    expect(row.getByLabelText("model.name")).toHaveValue("Unsaved name")
    expect(confirmSpy).toHaveBeenCalledWith(expect.objectContaining({ title: "model.unsavedTitle" }))
    expect(onCreateDraft).not.toHaveBeenCalled()

    const [[{ onCancel }]] = confirmSpy.mock.calls
    act(() => onCancel())

    expect(row.queryByLabelText("model.name")).toBeNull()
    expect(confirmEdit(standardModel.key)).toBeInTheDocument()
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it("can generate a deletion draft for an active custom model after confirmation", async () => {
    renderPanel()
    confirmSpy.mockImplementationOnce(() => {})
    const row = getRow(customModel.key)
    const remove = row.getByRole("button", { name: "model.deleteNamed" })

    expect(remove).toBeEnabled()
    fireEvent.click(remove)
    expect(onDeleteModel).not.toHaveBeenCalled()

    const [[{ onOk }]] = confirmSpy.mock.calls
    await act(async () => onOk(() => {}))

    expect(onDeleteModel).toHaveBeenCalledWith(customModel.key)
    expect(onReviewImpact).toHaveBeenCalledWith(draft)
    expect(onCreateDraft).not.toHaveBeenCalled()
  })

  it("blocks invalid custom selections until unavailable actions are removed", () => {
    renderPanel({
      models: [{ ...customModel, action_codes: ["unassigned"], derived_level: null }],
    })
    const rowCount = screen.getAllByRole("row").length
    const row = editRow(customModel.key)

    expect(screen.getAllByRole("row")).toHaveLength(rowCount)
    expect(row.getByLabelText("model.action.unassigned")).toBeChecked()
    expect(row.getByRole("status")).toHaveTextContent("model.unavailableSelection")
    expect(confirmEdit(customModel.key)).toBeDisabled()
    fireEvent.click(row.getByLabelText("model.action.unassigned"))
    expect(row.queryByRole("status")).not.toBeInTheDocument()
    fireEvent.click(row.getByLabelText("model.action.visible"))
    expect(confirmEdit(customModel.key)).toBeEnabled()
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
    expect(screen.getByText("actionLevel.pendingChanges")).toBeInTheDocument()
    expect(screen.getByText("impact.changeTitle")).toBeInTheDocument()
    expect(screen.getByText("impact.actionLevelChanged")).toBeInTheDocument()
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

  it("shows the expiry warning at the deadline while the dialog is open", () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] })
    vi.setSystemTime(new Date("2026-07-29T12:59:59Z"))
    try {
      render(
        <ImpactDialog
          open
          draft={draft}
          onOpenChange={vi.fn()}
          onPublish={onPublish}
        />,
      )

      const publish = screen.getByRole("button", { name: "impact.publish" })
      expect(publish).toBeEnabled()
      expect(screen.queryByText("impact.expiresAt")).not.toBeInTheDocument()
      expect(screen.queryByText("impact.expired")).not.toBeInTheDocument()

      act(() => vi.advanceTimersByTime(1000))

      expect(screen.getByText("impact.expired")).toBeInTheDocument()
      expect(publish).toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })
})
