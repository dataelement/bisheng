import { ActionLevelBoard } from "@/pages/SystemPage/components/permission/ActionLevelBoard"
import { fireEvent, render, screen, waitFor, within } from "@/test/test-utils"
import userEvent from "@testing-library/user-event"
import type { ComponentProps } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const actions = [
  {
    code: "visible",
    name: "Visible",
    level: 1 as const,
    active: true,
    sort_order: 1,
    resource_types: ["workflow" as const, "dashboard" as const],
  },
  {
    code: "edit",
    name: "Edit",
    level: null,
    active: true,
    sort_order: 2,
    resource_types: ["workflow" as const],
  },
  {
    code: "edit",
    name: "Duplicate Edit",
    level: 2 as const,
    active: true,
    sort_order: 3,
    resource_types: ["workflow" as const],
  },
  {
    code: "delete",
    name: "Delete",
    level: 4 as const,
    active: false,
    sort_order: 4,
    resource_types: ["workflow" as const],
  },
]

const draft = {
  draft_id: 13,
  base_release_id: 12,
  impact: {
    checksum: "a".repeat(64),
    resource_count: 2,
    grant_count: 3,
    assignee_count: 4,
    expansion_count: 1,
    revocation_count: 0,
    blockers: [],
    expires_at: "2026-07-29T12:00:00Z",
  },
}

function OpenActionLevelBoard(props: Omit<ComponentProps<typeof ActionLevelBoard>, "open" | "onOpenChange">) {
  return <ActionLevelBoard open onOpenChange={vi.fn()} {...props} />
}

function moveAction(actionCode: string, targetZone: string) {
  const dragData = new Map<string, string>()
  const dataTransfer = {
    effectAllowed: "none",
    dropEffect: "none",
    setData: (format: string, value: string) => dragData.set(format, value),
    getData: (format: string) => dragData.get(format) ?? "",
  }
  const card = screen.getByTestId(`permission-action-${actionCode}`)
  const target = screen.getByTestId(`action-level-zone-${targetZone}`)

  fireEvent.dragStart(card, { dataTransfer })
  fireEvent.dragOver(target, { dataTransfer })
  fireEvent.drop(target, { dataTransfer })
}

describe("ActionLevelBoard", () => {
  const onCreateDraft = vi.fn()
  const onReviewImpact = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    onCreateDraft.mockResolvedValue(draft)
  })

  it("renders four levels and shows legacy unassigned actions with a disabled switch", () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    for (const zone of ["1", "2", "3", "4"]) {
      expect(
        screen.getByTestId(`action-level-zone-${zone}`),
      ).toBeInTheDocument()
    }
    expect(screen.queryByTestId("action-level-zone-unassigned")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "actionLevel.clearLevel" })).not.toBeInTheDocument()
    expect(screen.getAllByTestId("permission-action-edit")).toHaveLength(1)
    const card = screen.getByTestId("permission-action-edit")
    expect(screen.getByTestId("action-level-zone-4")).toContainElement(card)
    expect(card).toHaveTextContent("actionLevel.unassigned")
    expect(card).toHaveAttribute("data-model-eligible", "false")
    expect(card).toHaveAttribute("draggable", "true")
    const toggle = within(card).getByRole("switch", { name: "actionLevel.active · actionName.edit" })
    expect(toggle).not.toBeChecked()
    expect(toggle).toBeDisabled()
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^actionLevel\.change/)).not.toBeInTheDocument()
  })

  it("prepares one draft for confirmation without displaying inline details", async () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("edit", "3")
    expect(
      screen.getByTestId("action-level-zone-3"),
    ).toContainElement(screen.getByTestId("permission-action-edit"))
    const toggle = screen.getByRole("switch", { name: "actionLevel.active · actionName.edit" })
    expect(toggle).toBeEnabled()
    expect(toggle).not.toBeChecked()

    moveAction("visible", "2")

    // Editing must not reach the server: one draft per edit meant publishing
    // applied only the last one and silently dropped the rest.
    expect(onCreateDraft).not.toHaveBeenCalled()
    expect(screen.queryByRole("status")).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    )
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledTimes(1)
    })
    expect(onCreateDraft).toHaveBeenCalledWith([
      { type: "ASSIGN_ACTION_LEVEL", action_code: "visible", level: 2 },
      { type: "ASSIGN_ACTION_LEVEL", action_code: "edit", level: 3 },
      { type: "SET_ACTION_ACTIVE", action_code: "edit", active: false },
    ])
    expect(onReviewImpact).toHaveBeenCalledWith(draft)
  })

  it("drops a change once the action is moved back where it started", () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("visible", "3")
    const confirm = screen.getByRole("button", { name: "actionLevel.publishChanges" })
    expect(confirm).toBeEnabled()

    moveAction("visible", "1")
    expect(confirm).toBeDisabled()
  })

  it("discards every pending change back to the published release", () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("edit", "3")
    fireEvent.click(screen.getByLabelText("actionLevel.active · actionName.delete"))
    const restore = screen.getByRole("button", { name: "actionLevel.discardChanges" })
    expect(restore).toBeEnabled()

    fireEvent.click(restore)

    expect(restore).toBeDisabled()
    expect(onCreateDraft).not.toHaveBeenCalled()
    const card = screen.getByTestId("permission-action-edit")
    expect(screen.getByTestId("action-level-zone-4")).toContainElement(card)
    expect(card).toHaveTextContent("actionLevel.unassigned")
    const toggle = within(card).getByRole("switch", { name: "actionLevel.active · actionName.edit" })
    expect(toggle).toBeDisabled()
    expect(toggle).not.toBeChecked()
    expect(screen.getByRole("switch", { name: "actionLevel.active · actionName.delete" })).not.toBeChecked()
  })

  it("changes an assigned action's active state without moving it to another level", async () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    const toggle = screen.getByRole("switch", { name: "actionLevel.active · actionName.visible" })
    fireEvent.click(toggle)
    expect(toggle).not.toBeChecked()
    expect(screen.getByTestId("action-level-zone-1")).toContainElement(
      screen.getByTestId("permission-action-visible"),
    )
    expect(onCreateDraft).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("button", { name: "actionLevel.publishChanges" }))
    await waitFor(() => expect(onCreateDraft).toHaveBeenCalledWith([
      { type: "SET_ACTION_ACTIVE", action_code: "visible", active: false },
    ]))
  })

  it("assigns a legacy action dropped into its display column and supports explicit activation", async () => {
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("edit", "4")

    const card = screen.getByTestId("permission-action-edit")
    expect(card).not.toHaveTextContent("actionLevel.unassigned")
    const toggle = within(card).getByRole("switch", { name: "actionLevel.active · actionName.edit" })
    expect(toggle).toBeEnabled()
    expect(toggle).not.toBeChecked()
    fireEvent.click(toggle)
    expect(toggle).toBeChecked()

    fireEvent.click(screen.getByRole("button", { name: "actionLevel.publishChanges" }))
    await waitFor(() => expect(onCreateDraft).toHaveBeenCalledWith([
      { type: "ASSIGN_ACTION_LEVEL", action_code: "edit", level: 4 },
    ]))
  })

  it("surfaces a failure to prepare the draft", async () => {
    onCreateDraft.mockRejectedValueOnce(new Error("boom"))
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("edit", "3")
    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    )

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("actionLevel.draftFailed")
    expect(onReviewImpact).not.toHaveBeenCalled()
  })

  it("shows the localized business reason returned by draft validation", async () => {
    onCreateDraft.mockRejectedValueOnce(
      "Turn off same-level grants for Manager before moving permission management to a higher level.",
    )
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    moveAction("edit", "3")
    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Turn off same-level grants for Manager",
    )
    expect(onReviewImpact).not.toHaveBeenCalled()
  })

  it("shows resource scope on the card and the inactive marker on the card", async () => {
    // Show the resource scope on the card as well as in the tooltip.
    render(
      <OpenActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    const card = screen.getByTestId("permission-action-visible")
    expect(card).toHaveTextContent("resourceTypeName.workflow")
    expect(card).toHaveTextContent("resourceTypeName.dashboard")

    await userEvent.hover(within(card).getByText("actionName.visible"))
    const tip = await screen.findByRole("tooltip")
    expect(tip).toHaveTextContent("resourceTypeName.workflow")
    expect(tip).toHaveTextContent("resourceTypeName.dashboard")

    expect(screen.getByTestId("permission-action-delete")).toHaveTextContent(
      "actionLevel.inactive",
    )
  })
})

describe("action labels", () => {
  const onCreateDraft = vi.fn()
  const onReviewImpact = vi.fn()

  it("labels actions and resource types by code, not by the stored English name", async () => {
    // The catalog seeds `name` to the code itself, so the panel used to render
    // "manage_permission" / "knowledge_file" at users. One column cannot serve
    // three languages, so the label is resolved from the code.
    render(
      <OpenActionLevelBoard
        actions={[
          {
            code: "manage_permission",
            name: "manage_permission",
            level: 3 as const,
            active: true,
            sort_order: 1,
            resource_types: ["knowledge_file" as const, "folder" as const],
          },
        ]}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    const card = screen.getByTestId("permission-action-manage_permission")
    expect(card).toHaveTextContent("actionName.manage_permission")

    await userEvent.hover(
      within(card).getByText("actionName.manage_permission"),
    )
    const tip = await screen.findByRole("tooltip")
    expect(tip).toHaveTextContent("resourceTypeName.knowledge_file")
    expect(tip).toHaveTextContent("resourceTypeName.folder")
    expect(tip).toHaveTextContent("actionLevel.managePermissionHint")
  })
})
