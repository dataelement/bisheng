import { render, screen } from "@/test/test-utils"
import type { ApiKeyItem, OpenApiScopeItem } from "@/types/api/openApi"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { KeyIssueDialog } from "@/pages/SystemPage/components/ServiceAccount/KeyIssueDialog"

vi.mock("@/controllers/API/serviceAccount", () => ({
  issueServiceAccountKeyApi: vi.fn(),
  updateServiceAccountKeyApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/calendar/datePicker", () => ({
  DatePicker: ({ placeholder }: { placeholder: string }) => (
    <button aria-label="date-picker" type="button">
      {placeholder}
    </button>
  ),
}))

vi.mock("@/components/bs-ui/tooltip", () => ({
  QuestionTooltip: () => <button aria-label="scope-endpoints" type="button" />,
}))

vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  default: () => null,
}))

vi.mock("@/components/bs-comp/department/TreeDepartmentSelect", () => ({
  TreeDepartmentSelect: () => null,
}))

const scopes: OpenApiScopeItem[] = [
  {
    code: "knowledge:read",
    group: "knowledge",
    label_key: "openApiManagement.scopes.knowledge_read.label",
    desc_key: "openApiManagement.scopes.knowledge_read.desc",
    endpoints: [{ method: "GET", path: "/api/v2/filelib/" }],
    hint_keys: [],
  },
  {
    code: "delegate",
    group: "delegation",
    label_key: "openApiManagement.scopes.delegate.label",
    desc_key: "openApiManagement.scopes.delegate.desc",
    endpoints: [],
    hint_keys: ["openApiManagement.scopes.delegate.warning"],
  },
  {
    code: "chat:invoke",
    group: "assistant",
    label_key: "openApiManagement.scopes.chat_invoke.label",
    desc_key: "openApiManagement.scopes.chat_invoke.desc",
    endpoints: [
      { method: "POST", path: "/api/v2/workstation/chat/completions" },
    ],
    hint_keys: [],
  },
]

describe("service-account key issue dialog", () => {
  it("shows localized permission names and keeps endpoint paths in help tooltips", () => {
    render(
      <KeyIssueDialog
        serviceAccountId={12}
        scopes={scopes}
        editingKey={null}
        open
        onOpenChange={vi.fn()}
        onIssued={vi.fn()}
        onUpdated={vi.fn()}
      />,
    )

    expect(
      screen.getByText("openApiManagement.scopes.knowledge_read.label"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("openApiManagement.scopes.chat_invoke.label"),
    ).toBeInTheDocument()
    expect(screen.queryByText("knowledge:read")).not.toBeInTheDocument()
    expect(screen.queryByText("/api/v2/filelib/")).not.toBeInTheDocument()
    expect(
      screen.getAllByRole("button", { name: "scope-endpoints" }),
    ).toHaveLength(2)
    expect(
      screen.getByText("openApiManagement.scopes.delegate.label"),
    ).toBeInTheDocument()
    expect(
      screen.queryByText("openApiManagement.scopeGroups.delegation"),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "date-picker" }),
    ).toBeInTheDocument()
    expect(document.querySelector('input[type="datetime-local"]')).toBeNull()
  })
})

// 伴生 PRD §4.2.4 / AC-48: `delegate` and the local development toolkit scopes
// must be impossible to tick together — the backend refuses the pair at issue
// and edit time (26050), the form has to say so before the admin fills in a
// delegation scope and hits save. Which scopes belong to the toolkit is read
// off the catalog `group`, so the fixture below only sets `group`, never a code
// list the component would have to know about.
const toolkitScopes: OpenApiScopeItem[] = [
  {
    code: "app:manage",
    group: "local_dev_toolkit",
    label_key: "openApiManagement.scopes.app_manage.label",
    desc_key: "openApiManagement.scopes.app_manage.desc",
    endpoints: [{ method: "POST", path: "/api/v2/apps/deploy" }],
    hint_keys: ["openApiManagement.scopes.app_manage.hint"],
  },
  {
    code: "identity:read",
    group: "local_dev_toolkit",
    label_key: "openApiManagement.scopes.identity_read.label",
    desc_key: "openApiManagement.scopes.identity_read.desc",
    endpoints: [],
    hint_keys: ["openApiManagement.scopes.identity_read.warning"],
  },
]

const scopesWithToolkit: OpenApiScopeItem[] = [...scopes, ...toolkitScopes]

const LOCAL_DEV_HINT = "openApiManagement.keys.localDevExclusiveHint"
const DELEGATE_HINT = "openApiManagement.keys.delegateExclusiveHint"
const CONFLICT = "openApiManagement.keys.scopeExclusiveConflict"

/** The Radix checkbox is a button inside the scope's <label>, not an <input>. */
const checkboxFor = (labelKey: string): HTMLElement => {
  const label = screen.getByText(labelKey).closest("label")
  const box = label?.querySelector('[role="checkbox"]')
  if (!box) throw new Error(`no checkbox for ${labelKey}`)
  return box as HTMLElement
}

const renderDialog = (editingKey: ApiKeyItem | null = null) =>
  render(
    <KeyIssueDialog
      serviceAccountId={12}
      scopes={scopesWithToolkit}
      editingKey={editingKey}
      open
      onOpenChange={vi.fn()}
      onIssued={vi.fn()}
      onUpdated={vi.fn()}
    />,
  )

describe("delegate ⊗ local development toolkit exclusivity", () => {
  it("delegation first: the toolkit scopes go unavailable and say why, and come back when it is cleared", async () => {
    const user = userEvent.setup()
    renderDialog()

    expect(checkboxFor(toolkitScopes[0].label_key)).toBeEnabled()
    expect(checkboxFor(toolkitScopes[1].label_key)).toBeEnabled()
    expect(screen.queryByText(LOCAL_DEV_HINT)).toBeNull()

    await user.click(checkboxFor("openApiManagement.scopes.delegate.label"))

    expect(checkboxFor(toolkitScopes[0].label_key)).toBeDisabled()
    expect(checkboxFor(toolkitScopes[1].label_key)).toBeDisabled()
    expect(screen.getByText(LOCAL_DEV_HINT)).toBeInTheDocument()
    // Scopes outside the toolkit group are untouched.
    expect(
      checkboxFor("openApiManagement.scopes.knowledge_read.label"),
    ).toBeEnabled()

    await user.click(checkboxFor("openApiManagement.scopes.delegate.label"))

    expect(checkboxFor(toolkitScopes[0].label_key)).toBeEnabled()
    expect(checkboxFor(toolkitScopes[1].label_key)).toBeEnabled()
    expect(screen.queryByText(LOCAL_DEV_HINT)).toBeNull()
  })

  it("toolkit first: delegation goes unavailable and says why, and comes back when the toolkit scope is cleared", async () => {
    const user = userEvent.setup()
    renderDialog()

    const delegateBox = () =>
      checkboxFor("openApiManagement.scopes.delegate.label")
    expect(delegateBox()).toBeEnabled()
    expect(screen.queryByText(DELEGATE_HINT)).toBeNull()

    await user.click(checkboxFor(toolkitScopes[0].label_key))

    expect(delegateBox()).toBeDisabled()
    expect(screen.getByText(DELEGATE_HINT)).toBeInTheDocument()
    // The delegation sub-form never opens, so no scope can be filled in either.
    expect(
      screen.queryByText("openApiManagement.keys.delegateUsers"),
    ).toBeNull()
    // The other toolkit scope stays selectable — the block is delegation-only.
    expect(checkboxFor(toolkitScopes[1].label_key)).toBeEnabled()

    await user.click(checkboxFor(toolkitScopes[0].label_key))

    expect(delegateBox()).toBeEnabled()
    expect(screen.queryByText(DELEGATE_HINT)).toBeNull()
  })

  it("clicking through the label cannot assemble the pair either", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(checkboxFor("openApiManagement.scopes.delegate.label"))
    // The whole row is a <label>; a click on its text would normally forward to
    // the control, so the state guard has to refuse it too.
    await user.click(screen.getByText(toolkitScopes[0].label_key))

    expect(checkboxFor(toolkitScopes[0].label_key)).not.toBeChecked()
    expect(screen.queryByText(CONFLICT)).toBeNull()
  })

  it("a key issued before the gate keeps both boxes clickable, blocks save, and clears once one side is dropped", async () => {
    const user = userEvent.setup()
    const legacyKey: ApiKeyItem = {
      id: 7,
      subject_kind: "service_account",
      subject_id: 12,
      name: "legacy",
      key_mask: "bs-sak-********abcd",
      scopes: ["delegate", "app:manage"],
      expires_at: null,
      revoked_at: null,
      last_used_at: null,
      revoke_reason: null,
      is_valid: true,
      create_time: null,
      delegate_scopes: [
        { subject_type: "user", subject_id: 3, subject_name: "alice" },
      ],
    }
    renderDialog(legacyKey)

    expect(screen.getByText(CONFLICT)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "save" })).toBeDisabled()
    // Neither side is frozen, or the conflict could never be resolved.
    expect(checkboxFor(toolkitScopes[0].label_key)).toBeEnabled()
    expect(
      checkboxFor("openApiManagement.scopes.delegate.label"),
    ).toBeEnabled()

    await user.click(checkboxFor(toolkitScopes[0].label_key))

    expect(screen.queryByText(CONFLICT)).toBeNull()
    expect(screen.getByRole("button", { name: "save" })).toBeEnabled()
  })
})
