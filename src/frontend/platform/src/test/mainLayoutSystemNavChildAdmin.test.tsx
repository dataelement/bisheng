import type { ReactNode } from "react";

import { darkContext } from "@/contexts/darkContext";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import MainLayout from "@/layout/MainLayout";
import { render, screen } from "@/test/test-utils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/layout/HeaderMenu", () => ({
  default: () => <div data-testid="header-menu" />,
}));

vi.mock("@/components/bs-icons", () => {
  const Icon = () => <span aria-hidden="true" />;
  return {
    ApplicationIcon: Icon,
    BookOpenIcon: Icon,
    EvaluatingIcon: Icon,
    GithubIcon: Icon,
    KnowledgeIcon: Icon,
    LabelIcon: Icon,
    LogIcon: Icon,
    ModelIcon: Icon,
    QuitIcon: Icon,
    SystemIcon: Icon,
    TechnologyIcon: Icon,
  };
});

vi.mock("@/components/bs-icons/loading", () => ({
  LoadingIcon: () => <span aria-hidden="true" />,
}));

vi.mock("@/components/bs-icons/menu/dataset", () => ({
  DatasetIcon: () => <span aria-hidden="true" />,
}));

vi.mock("@/components/bs-icons/menu/system", () => ({
  DashboardIcon: () => <span aria-hidden="true" />,
}));

vi.mock("@/components/bs-ui/select/hover", () => ({
  SelectHover: ({ triagger, children }: { triagger: ReactNode; children: ReactNode }) => (
    <div>
      {triagger}
      <div>{children}</div>
    </div>
  ),
  SelectHoverItem: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/bs-ui/separator", () => ({
  Separator: () => null,
}));

vi.mock("@/components/bs-ui/tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children, ...props }: { children: ReactNode } & Record<string, unknown>) => (
    <button type="button" {...props}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}));

vi.mock("@/controllers/API/user", () => ({
  logoutApi: vi.fn(),
}));

vi.mock("@/controllers/API/tenant", () => ({
  getUserTenantsApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => Promise.resolve(promise)),
}));

beforeAll(() => {
  (globalThis as any).__APP_ENV__ = { BASE_URL: "" };
});

const localStorageMock = {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
};

const baseUser = {
  user_id: 1,
  user_name: "tester",
  role: "user",
  web_menu: [] as string[],
  avatar: "",
  external_id: null,
  is_department_admin: false,
  is_child_admin: false,
  tenant_name: "集团总部",
  leaf_tenant_name: "华东子公司",
};

function renderLayout(userOverrides: Record<string, unknown> = {}) {
  return render(
    <darkContext.Provider value={{ dark: false, setDark: vi.fn() } as any}>
      <locationContext.Provider
        value={{
          current: [""],
          setCurrent: vi.fn(),
          isStackedOpen: true,
          setIsStackedOpen: vi.fn(),
          showSideBar: true,
          setShowSideBar: vi.fn(),
          extraNavigation: { title: "" },
          setExtraNavigation: vi.fn(),
          extraComponent: null,
          setExtraComponent: vi.fn(),
          appConfig: { multiTenantEnabled: true, noFace: true },
          reloadConfig: vi.fn(),
        } as any}
      >
        <userContext.Provider
          value={{
            user: { ...baseUser, ...userOverrides },
            setUser: vi.fn(),
            savedComponents: [],
            addSavedComponent: vi.fn(),
            checkComponentsName: vi.fn(),
            delComponent: vi.fn(),
          } as any}
        >
          <MainLayout />
        </userContext.Provider>
      </locationContext.Provider>
    </darkContext.Provider>,
  );
}

describe("MainLayout system / tenant nav for Child Admin (PRD §3.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
  });

  it("Child Admin sees the system menu entry", () => {
    renderLayout({ is_child_admin: true });
    expect(screen.getByText("menu.system")).toBeInTheDocument();
  });

  it("Child Admin does NOT see the tenant management entry (super-only until backend is opened up)", () => {
    renderLayout({ is_child_admin: true });
    expect(screen.queryByText("tenant.management")).toBeNull();
  });

  it("Child Admin does NOT see the dataset entry (super / dept admin only)", () => {
    renderLayout({ is_child_admin: true });
    expect(screen.queryByText("menu.dataset")).toBeNull();
  });

  it("plain user without any admin flag sees neither system nor tenant management", () => {
    renderLayout();
    expect(screen.queryByText("menu.system")).toBeNull();
    expect(screen.queryByText("tenant.management")).toBeNull();
  });

  it("global super admin still sees both system and tenant management entries", () => {
    renderLayout({ role: "admin" });
    expect(screen.getByText("menu.system")).toBeInTheDocument();
    expect(screen.getByText("tenant.management")).toBeInTheDocument();
  });
});
