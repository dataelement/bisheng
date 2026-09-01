import { userContext } from "@/contexts/userContext"
import {
  createPermissionCatalogDraftApi,
  getPermissionCatalogApi,
  publishPermissionCatalogDraftApi,
} from "@/controllers/API/permission"
import { RolesAndPermissions } from "@/pages/SystemPage/components/RolesAndPermissions"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const childCalls = vi.hoisted(() => ({
  actionBoard: vi.fn(),
  modelEditor: vi.fn(),
  impactDialog: vi.fn(),
  message: vi.fn(),
}))

vi.mock("@/pages/SystemPage/components/Roles", () => ({
  default: () => <div data-testid="menu-roles">menu-roles</div>,
}))

vi.mock(
  "@/pages/SystemPage/components/permission/ActionLevelBoard",
  () => ({
    ActionLevelBoard: (props: {
      onCreateDraft: (changes: {
        type: "ASSIGN_ACTION_LEVEL"
        action_code: string
        level: 2
      }[]) => Promise<unknown>
      onReviewImpact: (draft: unknown) => void
    }) => {
      childCalls.actionBoard(props)
      return (
        <button
          type="button"
          onClick={async () => {
            const draft = await props.onCreateDraft([
              {
                type: "ASSIGN_ACTION_LEVEL",
                action_code: "edit",
                level: 2,
              },
            ])
            props.onReviewImpact(draft)
          }}
        >
          action-board.create-draft
        </button>
      )
    },
  }),
)

vi.mock("@/pages/SystemPage/components/permission/ModelEditor", () => ({
  ModelEditor: (props: {
    model: { key: string }
    createMode?: boolean
    onDeleteModel?: (modelKey: string) => Promise<{ draft_id: number }>
    onReviewImpact: (draft: { draft_id: number }) => void
  }) => {
    childCalls.modelEditor(props)
    return (
      <div data-testid="model-editor">
        {props.createMode ? "create" : props.model.key}
        <button
          type="button"
          onClick={() =>
            void props
              .onDeleteModel?.(props.model.key)
              .then((draft) => props.onReviewImpact(draft))
              .catch(() => undefined)
          }
        >
          model-editor.delete
        </button>
      </div>
    )
  },
}))

vi.mock("@/pages/SystemPage/components/permission/ImpactDialog", () => ({
  ImpactDialog: (props: {
    open: boolean
    draft: { draft_id: number } | null
    onPublish: (
      draftId: number,
      payload: {
        expected_current_release_id: number
        idempotency_key: string
        confirmed: true
      },
    ) => Promise<unknown>
  }) => {
    childCalls.impactDialog(props)
    if (!props.open || !props.draft) return null
    return (
      <button
        type="button"
        onClick={() =>
          void props.onPublish(props.draft!.draft_id, {
            expected_current_release_id: 21,
            idempotency_key: "catalog-publish-test",
            confirmed: true,
          })
        }
      >
        impact-dialog.publish
      </button>
    )
  },
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  message: (...args: unknown[]) => childCalls.message(...args),
}))

vi.mock("@/controllers/API/permission", () => ({
  createPermissionCatalogDraftApi: vi.fn(),
  getPermissionCatalogApi: vi.fn(),
  publishPermissionCatalogDraftApi: vi.fn(),
}))

const catalog = {
  id: 21,
  release_key: "release-21",
  version: 21,
  status: "PUBLISHED",
  authorization_model_id: "fga-model-21",
  checksum: "a".repeat(64),
  actions: [
    {
      code: "edit",
      name: "Edit",
      level: 2 as const,
      active: true,
      sort_order: 1,
      resource_types: ["workflow" as const],
    },
  ],
  models: [
    {
      key: "editor",
      name: "Editor",
      kind: "STANDARD" as const,
      config_scope: "PLATFORM" as const,
      derived_level: 2 as const,
      active: true,
      allow_same_level: false,
      action_codes: ["edit"],
      version: 3,
    },
  ],
  published_at: "2026-07-29T12:00:00Z",
}

const draft = {
  draft_id: 31,
  base_release_id: 21,
  impact: {
    checksum: "b".repeat(64),
    resource_count: 4,
    grant_count: 3,
    assignee_count: 2,
    expansion_count: 1,
    revocation_count: 0,
    blockers: [],
    expires_at: "2026-07-29T13:00:00Z",
  },
}

function renderWithUser(
  user: Record<string, unknown>,
  children: ReactNode = <RolesAndPermissions />,
) {
  return render(
    <userContext.Provider value={{ user } as never}>
      {children}
    </userContext.Provider>,
  )
}

describe("F048 RolesAndPermissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getPermissionCatalogApi).mockResolvedValue(catalog)
    vi.mocked(createPermissionCatalogDraftApi).mockResolvedValue(draft)
    vi.mocked(publishPermissionCatalogDraftApi).mockResolvedValue({
      release_id: 22,
      release_key: "release-22",
      status: "PUBLISHED",
      release_checksum: "c".repeat(64),
    })
  })

  it("shows menu roles plus Catalog configuration only to platform super admins", async () => {
    renderWithUser({ role: "admin", is_global_super: true })

    expect(screen.getByTestId("menu-roles")).toBeInTheDocument()
    expect(
      await screen.findByRole("tab", { name: "catalog.actions" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("tab", { name: "catalog.models" }),
    ).toBeInTheDocument()
    expect(screen.queryByText("system.relationModelSelectTemplate")).toBeNull()
    expect(screen.queryByText("permission_id")).toBeNull()
    expect(getPermissionCatalogApi).toHaveBeenCalledTimes(1)
  })

  it("keeps resource Catalog configuration hidden from delegated administrators", () => {
    renderWithUser({ role: "user", is_child_admin: true })

    expect(screen.getByTestId("menu-roles")).toBeInTheDocument()
    expect(
      screen.queryByRole("tab", { name: "catalog.actions" }),
    ).toBeNull()
    expect(
      screen.queryByRole("tab", { name: "catalog.models" }),
    ).toBeNull()
    expect(getPermissionCatalogApi).not.toHaveBeenCalled()
  })

  it("retires the legacy role-to-resource binding editor and API client", () => {
    expect(
      existsSync(
        resolve(
          process.cwd(),
          "src/pages/SystemPage/components/EditRole.tsx",
        ),
      ),
    ).toBe(false)

    const apiSource = readFileSync(
      resolve(process.cwd(), "src/controllers/API/user.ts"),
      "utf8",
    )
    expect(apiSource).not.toMatch(
      /role_access|get_group_resources|getRolePermissionsApi|updateRolePermissionsApi/,
    )
  })

  it("binds draft impact and publish to the current server release", async () => {
    renderWithUser({ role: "admin", is_global_super: true })
    await waitFor(() => expect(getPermissionCatalogApi).toHaveBeenCalled())
    const actionsTab = screen.getByRole("tab", { name: "catalog.actions" })
    fireEvent.mouseDown(actionsTab)
    fireEvent.click(actionsTab)
    fireEvent.click(
      screen.getByRole("button", { name: "action-board.create-draft" }),
    )

    await waitFor(() => {
      expect(createPermissionCatalogDraftApi).toHaveBeenCalledWith(
        {
          idempotency_key: expect.stringMatching(/^catalog-draft-/),
          base_release_id: 21,
          changes: [
            {
              type: "ASSIGN_ACTION_LEVEL",
              action_code: "edit",
              level: 2,
            },
          ],
        },
        {},
      )
    })
    fireEvent.click(
      await screen.findByRole("button", { name: "impact-dialog.publish" }),
    )
    await waitFor(() => {
      expect(publishPermissionCatalogDraftApi).toHaveBeenCalledWith(
        31,
        {
          expected_current_release_id: 21,
          idempotency_key: "catalog-publish-test",
          confirmed: true,
        },
        {},
      )
      expect(getPermissionCatalogApi).toHaveBeenCalledTimes(2)
    })
  })

  it("passes the selected server model to the model editor", async () => {
    renderWithUser({ role: "admin", is_global_super: true })
    await waitFor(() => expect(getPermissionCatalogApi).toHaveBeenCalled())
    const modelsTab = screen.getByRole("tab", { name: "catalog.models" })
    fireEvent.mouseDown(modelsTab)
    fireEvent.click(modelsTab)

    expect(await screen.findByTestId("model-editor")).toHaveTextContent(
      "editor",
    )
    expect(childCalls.modelEditor).toHaveBeenCalledWith(
      expect.objectContaining({
        model: expect.objectContaining({ key: "editor" }),
        actions: catalog.actions,
      }),
    )

    fireEvent.click(screen.getByRole("button", { name: "model.create" }))
    expect(screen.getByTestId("model-editor")).toHaveTextContent("create")
    expect(childCalls.modelEditor).toHaveBeenCalledWith(
      expect.objectContaining({
        createMode: true,
        model: expect.objectContaining({
          key: "__new_custom_model__",
          kind: "CUSTOM",
        }),
      }),
    )
  })

  it("names the blocker when a model cannot be deleted", async () => {
    // 25004 covers several model-state conflicts, so its shared copy says only
    // "state does not allow this". The count is the actionable part: it tells
    // the author how much has to be moved off the model first.
    //
    // The refusal lands on the *draft* leg — the batch is validated as it is
    // drafted, so a fix that only listened to the publish leg never saw it.
    vi.mocked(createPermissionCatalogDraftApi).mockRejectedValueOnce({
      status_code: 25004,
      data: { reason: "referenced_by_grants", reference_count: 3 },
    })

    renderWithUser({ role: "admin", is_global_super: true })
    await waitFor(() => expect(getPermissionCatalogApi).toHaveBeenCalled())
    const modelsTab = screen.getByRole("tab", { name: "catalog.models" })
    fireEvent.mouseDown(modelsTab)
    fireEvent.click(modelsTab)

    fireEvent.click(await screen.findByText("model-editor.delete"))

    await waitFor(() => {
      expect(childCalls.message).toHaveBeenCalledWith({
        variant: "error",
        description: "model.deleteBlockedByGrants",
      })
    })
  })

  it("falls back to the plain failure when the server sends no reason", async () => {
    vi.mocked(createPermissionCatalogDraftApi).mockRejectedValueOnce(
      "some other failure",
    )

    renderWithUser({ role: "admin", is_global_super: true })
    await waitFor(() => expect(getPermissionCatalogApi).toHaveBeenCalled())
    const modelsTab = screen.getByRole("tab", { name: "catalog.models" })
    fireEvent.mouseDown(modelsTab)
    fireEvent.click(modelsTab)

    fireEvent.click(await screen.findByText("model-editor.delete"))

    await waitFor(() => {
      expect(childCalls.message).toHaveBeenCalledWith({
        variant: "error",
        description: "model.deleteFailed",
      })
    })
  })
})
