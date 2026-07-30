import { ActionLevelBoard } from "@/pages/SystemPage/components/permission/ActionLevelBoard"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
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

  it("creates a server draft for keyboard and drag changes before impact review", async () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    fireEvent.change(screen.getByLabelText("actionLevel.change.edit"), {
      target: { value: "3" },
    })
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "ASSIGN_ACTION_LEVEL",
        action_code: "edit",
        level: 3,
      })
    })
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
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenLastCalledWith({
        type: "ASSIGN_ACTION_LEVEL",
        action_code: "visible",
        level: 2,
      })
    })

    fireEvent.click(screen.getByRole("button", { name: "impact.review" }))
    expect(onReviewImpact).toHaveBeenCalledWith(draft)
  })

  it("shows scope and drafts active-state changes without publishing", async () => {
    render(
      <ActionLevelBoard
        actions={actions}
        onCreateDraft={onCreateDraft}
        onReviewImpact={onReviewImpact}
      />,
    )

    expect(screen.getByTestId("permission-action-visible")).toHaveTextContent(
      "workflow",
    )
    expect(screen.getByTestId("permission-action-visible")).toHaveTextContent(
      "dashboard",
    )
    expect(screen.getByTestId("permission-action-delete")).toHaveTextContent(
      "actionLevel.inactive",
    )

    fireEvent.click(screen.getByLabelText("actionLevel.active.delete"))
    await waitFor(() => {
      expect(onCreateDraft).toHaveBeenCalledWith({
        type: "SET_ACTION_ACTIVE",
        action_code: "delete",
        active: true,
      })
    })
    expect(onReviewImpact).not.toHaveBeenCalled()
  })
})
