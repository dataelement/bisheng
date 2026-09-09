import { render, screen } from "@/test/test-utils"
import type { OpenApiScopeItem } from "@/types/api/openApi"
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
