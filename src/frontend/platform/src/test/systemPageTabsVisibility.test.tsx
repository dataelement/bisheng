import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { render, screen } from "@/test/test-utils";
import { userContext } from "@/contexts/userContext";
import SystemPage from "@/pages/SystemPage";

// Stub the heavy children — we only assert which tab triggers render.
vi.mock("@/pages/SystemPage/components/Config", () => ({
  default: () => <div data-testid="config" />,
}));
vi.mock("@/pages/SystemPage/components/OrganizationAndMembers", () => ({
  default: () => <div data-testid="org" />,
}));
vi.mock("@/pages/SystemPage/components/OrgSync", () => ({
  default: () => <div data-testid="org-sync" />,
}));
vi.mock("@/pages/SystemPage/components/RolesAndPermissions", () => ({
  default: () => <div data-testid="roles" />,
}));
vi.mock("@/pages/SystemPage/theme", () => ({
  default: () => <div data-testid="theme" />,
}));
vi.mock("@/pages/SystemPage/components/UserGroup", () => ({
  default: () => <div data-testid="user-group" />,
}));
vi.mock("@/pages/SystemPage/components/Users", () => ({
  default: () => <div data-testid="legacy-users" />,
}));

type UserShape = Record<string, unknown>;

const renderWithUser = (user: UserShape) => {
  const value = {
    user,
    setUser: () => {},
    contextOpen: false,
    setContextOpen: () => {},
  } as unknown as React.ContextType<typeof userContext>;
  return render(
    <userContext.Provider value={value}>
      <SystemPage />
    </userContext.Provider> as ReactNode,
  );
};

const ORG = "system.orgAndMembers";
const ROLE = "system.roleAndPermissions";
const SYSCFG = "system.systemConfiguration";
const THEME = "system.themeColor";
const ORG_SYNC = "orgSync:title";
const USER_GROUP = "system.userGroupsM";
const LEGACY = "system.userManagement";

describe("SystemPage tab visibility (PRD §3.3)", () => {
  it("global super admin sees org/userGroup/role/orgSync/system/theme; legacy user table hidden", () => {
    renderWithUser({ role: "admin", user_id: 1 });
    expect(screen.getByText(ORG)).toBeInTheDocument();
    expect(screen.getByText(USER_GROUP)).toBeInTheDocument();
    expect(screen.getByText(ROLE)).toBeInTheDocument();
    expect(screen.getByText(ORG_SYNC)).toBeInTheDocument();
    expect(screen.getByText(SYSCFG)).toBeInTheDocument();
    expect(screen.getByText(THEME)).toBeInTheDocument();
    expect(screen.queryByText(LEGACY)).toBeNull();
  });

  it("Child Admin sees org/role but NOT system config / theme / org sync (instance-level only)", () => {
    renderWithUser({ role: "user", is_child_admin: true, user_id: 2 });
    expect(screen.getByText(ORG)).toBeInTheDocument();
    expect(screen.getByText(ROLE)).toBeInTheDocument();
    expect(screen.queryByText(SYSCFG)).toBeNull();
    expect(screen.queryByText(THEME)).toBeNull();
    expect(screen.queryByText(ORG_SYNC)).toBeNull();
    expect(screen.queryByText(LEGACY)).toBeNull();
  });

  it("Department Admin sees org/role but NOT system config / theme / org sync", () => {
    renderWithUser({ role: "user", is_department_admin: true, user_id: 3 });
    expect(screen.getByText(ORG)).toBeInTheDocument();
    expect(screen.getByText(ROLE)).toBeInTheDocument();
    expect(screen.queryByText(SYSCFG)).toBeNull();
    expect(screen.queryByText(THEME)).toBeNull();
    expect(screen.queryByText(ORG_SYNC)).toBeNull();
  });

  it("plain user sees neither org nor role; falls back to legacy user table", () => {
    renderWithUser({ role: "user", user_id: 4 });
    expect(screen.queryByText(ORG)).toBeNull();
    expect(screen.queryByText(ROLE)).toBeNull();
    expect(screen.queryByText(SYSCFG)).toBeNull();
    expect(screen.queryByText(THEME)).toBeNull();
    expect(screen.queryByText(ORG_SYNC)).toBeNull();
    expect(screen.getByText(LEGACY)).toBeInTheDocument();
  });

  it("user-group manager sees the user-group tab even without admin flags", () => {
    renderWithUser({ role: "user", can_manage_user_groups: true, user_id: 5 });
    expect(screen.getByText(USER_GROUP)).toBeInTheDocument();
  });
});
