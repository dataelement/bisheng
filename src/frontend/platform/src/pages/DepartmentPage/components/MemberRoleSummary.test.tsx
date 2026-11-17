import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MemberRoleSummary } from "./MemberRoleSummary";
afterEach(cleanup);
it("keeps valid roles separate from explicitly inactive bindings", () => {
  render(<MemberRoleSummary member={{ roles: [{ id: 219, role_name: "Shared role" }], is_department_admin: false,
    role_binding_issues: [{ binding_id: 1, role_id: 110, role_name: "Old role", reason: "binding_tenant_mismatch" }] }} />);
  expect(screen.getByText("Shared role")).toBeVisible();
  expect(screen.getByText("Old role · memberRoleIssues.inactive")).toBeVisible();
  expect(screen.getByLabelText("Old role: memberRoleIssues.binding_tenant_mismatch")).toBeVisible();
});
it("renders a missing definition by ID without pretending it is an effective role", () => {
  render(<MemberRoleSummary member={{ roles: [], is_department_admin: false,
    role_binding_issues: [{ binding_id: 2, role_id: 999, role_name: null, reason: "definition_missing" }] }} />);
  expect(screen.getByText("-")).toBeVisible();
  expect(screen.getByText("memberRoleIssues.missingRole · memberRoleIssues.inactive")).toBeVisible();
});
it("has no diagnostic placeholder when the server omits private diagnostics", () => {
  render(<MemberRoleSummary member={{ roles: [{ id: 2, role_name: "Tenant role" }], is_department_admin: true }} />);
  expect(screen.getByText("department.deptAdminRoleName, Tenant role")).toBeVisible();
  expect(screen.queryByText(/memberRoleIssues/)).toBeNull();
});
