import { ActionLevelBoard } from "@/pages/SystemPage/components/permission/ActionLevelBoard"
import { fireEvent, render, screen, selectMenuOption, waitFor, within } from "@/test/test-utils"
import userEvent from "@testing-library/user-event"
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

describe("ActionLevelBoard", () => {
  const onCreateDraft = vi.fn()
  const onReviewImpact = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    onCreateDraft.mockResolvedValue(draft)
  })

  it("renders unassigned plus levels 1-4 and keeps every action unique", () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    for (const zone of ["unassigned", "1", "2", "3", "4"]) {
      expect(
        screen.getByTestId(`action-level-zone-${zone}`),
      ).toBeInTheDocument()
    }
    expect(screen.getAllByTestId("permission-action-edit")).toHaveLength(1)
    expect(screen.getByTestId("permission-action-edit")).toHaveAttribute(
      "data-model-eligible",
      "false",
    )
  })

  it("keeps edits local until the whole batch is published", async () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectMenuOption("actionLevel.change.edit", 3)
    expect(
      screen.getByTestId("action-level-zone-3"),
    ).toContainElement(screen.getByTestId("permission-action-edit"))

    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn(() => "visible"),
      effectAllowed: "move",
    }
    fireEvent.dragStart(screen.getByTestId("permission-action-visible"), {
      dataTransfer,
    })
    fireEvent.drop(screen.getByTestId("action-level-zone-2"), {
      dataTransfer,
    })

    // Editing must not reach the server: one draft per edit meant publishing
    // applied only the last one and silently dropped the rest.
    expect(onCreateDraft).not.toHaveBeenCalled()
    expect(screen.getByRole("status")).toHaveTextContent(
      "actionLevel.pendingChanges",
    )

    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    )
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledTimes(1)
    })
    expect(onCreateDraft).toHaveBeenCalledWith([
      { type: "ASSIGN_ACTION_LEVEL", action_code: "visible", level: 2 },
      { type: "ASSIGN_ACTION_LEVEL", action_code: "edit", level: 3 },
    ])
    expect(onReviewImpact).toHaveBeenCalledWith(draft)
  })

  it("drops a change once the action is moved back where it started", async () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectMenuOption("actionLevel.change.visible", 3)
    expect(screen.getByRole("status")).toBeInTheDocument()

    // Re-query: moving zones remounts the card, so the old node is detached.
    await selectMenuOption("actionLevel.change.visible", 1)
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    ).toBeDisabled()
  })

  it("discards every pending change back to the published release", async () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectMenuOption("actionLevel.change.edit", 3)
    fireEvent.click(screen.getByLabelText("actionLevel.active.delete"))
    expect(screen.getByRole("status")).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.discardChanges" }),
    )

    expect(screen.queryByRole("status")).not.toBeInTheDocument()
    expect(onCreateDraft).not.toHaveBeenCalled()
    expect(
      screen.getByTestId("action-level-zone-unassigned"),
    ).toContainElement(screen.getByTestId("permission-action-edit"))
  })

  it("surfaces a failure to prepare the draft", async () => {
    onCreateDraft.mockRejectedValueOnce(new Error("boom"))
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectMenuOption("actionLevel.change.edit", 3)
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
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    await selectMenuOption("actionLevel.change.edit", 3)
    fireEvent.click(
      screen.getByRole("button", { name: "actionLevel.publishChanges" }),
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Turn off same-level grants for Manager",
    )
    expect(onReviewImpact).not.toHaveBeenCalled()
  })

  it("shows resource scope on the card and the inactive marker on the card", async () => {
    // Scope used to be hover-only, which meant an admin who never hovered
    // assumed every operation applied to every resource. It now sits on the
    // card, in the row the level dropdown already occupies.
    render(
      <ActionLevelBoard
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
      <ActionLevelBoard
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

    // The raw code and the resource scope moved into the tooltip: both are
    // reference detail, not something to scan a column for.
    await userEvent.hover(
      within(card).getByText("actionName.manage_permission"),
    )
    const tip = await screen.findByRole("tooltip")
    expect(tip).toHaveTextContent("resourceTypeName.knowledge_file")
    expect(tip).toHaveTextContent("resourceTypeName.folder")
    expect(tip).toHaveTextContent("manage_permission")
  })
})
