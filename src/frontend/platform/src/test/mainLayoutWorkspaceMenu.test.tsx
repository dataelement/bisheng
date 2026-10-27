import MainLayout from "@/layout/MainLayout";
import { darkContext } from "@/contexts/darkContext";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { render, screen } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/layout/HeaderMenu", () => ({
  default: () => <div data-testid="header-menu" />,
  HeaderMenu: () => <div data-testid="header-menu" />,
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

vi.mock("@/components/bs-ui/separator", () => ({
  Separator: () => null,
}));



vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}));

vi.mock("@/controllers/API/user", () => ({
  logoutApi: vi.fn(),
}));

vi.mock("@/controllers/API/tenant", () => ({
  getUserTenantsApi: vi.fn(),
  switchTenantApi: vi.fn(),
}));

vi.mock("@/controllers/request", async (importOriginal) => ({
  ...await importOriginal<typeof import('@/controllers/request')>(),
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => Promise.resolve(promise)),
}));

vi.mock("@/hooks/useDshBrowserConfig", () => ({
  useDshBrowserConfig: () => ({
    config: { management_enabled: true, enabled: true },
    failed: false,
  }),
}));

vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({
  toast: vi.fn(),
}))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
});

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
  role: "editor",
  web_menu: [] as string[],
  avatar: "",
  external_id: null,
  is_department_admin: false,
};

function renderLayout(webMenu: string[]) {
  const setUser = vi.fn();
  const setDark = vi.fn();

  return render(
    <darkContext.Provider value={{ dark: false, setDark } as any}>
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
          appConfig: { multiTenantEnabled: false, noFace: true },
          reloadConfig: vi.fn(),
        } as any}
      >
        <userContext.Provider
          value={{
            user: { ...baseUser, web_menu: webMenu },
            setUser,
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

// The account menu is a Radix DropdownMenu: its items only exist once it is open.
async function openAccountMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "tester" }));
  await screen.findByRole("menu");
  return user;
}

describe("MainLayout workspace entry", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
  });

  it("shows the workspace entry for the canonical workstation menu key", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    renderLayout(["workstation"]);
    const user = await openAccountMenu();

    const workspaceEntry = screen.getByRole("menuitem", { name: "menu.workspace" });
    expect(workspaceEntry).toBeInTheDocument();

    await user.click(workspaceEntry);
    expect(openSpy).toHaveBeenCalledWith("/workspace/");
  });

  it("keeps the workspace entry visible for legacy frontend menu data", async () => {
    renderLayout(["frontend"]);
    await openAccountMenu();

    expect(
      screen.getByRole("menuitem", { name: "menu.workspace" }),
    ).toBeInTheDocument();
  });

  it("hides the workspace entry when the user lacks both menu keys", async () => {
    renderLayout(["knowledge"]);
    await openAccountMenu();

    expect(screen.getByRole("menuitem", { name: "menu.changePwd" })).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "menu.workspace" }),
    ).not.toBeInTheDocument();
  });
});
