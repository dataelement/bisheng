import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const testState = vi.hoisted(() => ({
  resourceId: "601",
  secondResourceId: null as string | null,
  state: 1,
}));

const permissionApi = vi.hoisted(() => vi.fn());
const permissionError = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn() },
  }),
}));

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: permissionApi,
}));
vi.mock("@/controllers/API/knowledgeSpace", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/controllers/API/knowledgeSpace")>();
  return {
    ...actual,
    knowledgeSpaceApi: {
      ...actual.knowledgeSpaceApi,
      listVisibleSpaces: async () => ({
        data: [testState.resourceId, testState.secondResourceId]
          .filter((id): id is string => !!id)
          .map((id) => ({
            id: Number(id),
            name: "Knowledge",
            description: "Description",
            state: testState.state,
            actions: ["visible"],
            update_time: "2026-08-25T10:00:00",
            user_name: "Owner",
          })),
        page_size: 20,
        has_more: false,
        next_cursor: null,
      }),
    },
  };
});
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@bisheng/ui", async () => {
  const actual =
    await vi.importActual<typeof import("@bisheng/ui")>("@bisheng/ui");
  const React = await import("react");
  interface DropdownContextValue {
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }
  const DropdownContext = React.createContext<DropdownContextValue | null>(
    null,
  );
  // Row menu item label key -> the action id the assertions below look up.
  const actionByLabel: Record<string, string> = {
    managePermission: "permission",
    "lib.copy": "copy",
    settings: "set",
    setting: "set",
    delete: "delete",
    "knowledgeRowActions.loading": "loading",
    "knowledgeRowActions.empty": "empty",
  };
  function Dropdown({
    children,
    menu,
    open,
    onOpenChange,
  }: {
    children: ReactNode;
    menu: ReactNode;
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) {
    return (
      <DropdownContext.Provider value={{ open, onOpenChange }}>
        <span
          data-testid="row-actions-trigger"
          onClick={() => onOpenChange(!open)}
        >
          {children}
        </span>
        {open ? <div data-testid="row-actions-menu">{menu}</div> : null}
        <button
          type="button"
          data-testid="row-actions-close"
          onClick={(event) => {
            event.stopPropagation();
            onOpenChange(false);
          }}
        >
          close
        </button>
      </DropdownContext.Provider>
    );
  }
  function DropdownItem({
    children,
    disabled,
    onSelect,
  }: {
    children: ReactNode;
    disabled?: boolean;
    onSelect?: () => void;
  }) {
    const context = React.useContext(DropdownContext);
    return (
      <button
        type="button"
        data-value={
          typeof children === "string"
            ? (actionByLabel[children] ?? children)
            : undefined
        }
        disabled={disabled}
        onClick={() => {
          context?.onOpenChange(false);
          onSelect?.();
        }}
      >
        {children}
      </button>
    );
  }
  const DropdownSeparator = () => null;
  const previous = await (() => ({
    toast: permissionError,
    useToast: () => ({ toast: permissionError, message: permissionError }),
  }))();
  const hooks = Reflect.get(previous, "useToast")?.() ?? {};
  return {
    ...actual,
    Dropdown,
    DropdownItem,
    DropdownSeparator,
    notification: {
      ...actual.notification,
      open:
        Reflect.get(previous, "toast") ??
        Reflect.get(hooks, "toast") ??
        actual.notification.open,
    },
    toast: {
      ...actual.toast,
      show:
        Reflect.get(previous, "message") ??
        Reflect.get(hooks, "message") ??
        actual.toast.show,
    },
  };
});

vi.mock("@/components/bs-icons/knowledge", () => ({
  BookIcon: () => <span data-testid="book-icon" />,
  QaIcon: () => <span data-testid="qa-icon" />,
}));

vi.mock("@/components/bs-icons/loading", () => ({
  LoadIcon: () => <span data-testid="load-icon" />,
  LoadingIcon: () => <span data-testid="loading-icon" />,
}));

vi.mock("@/util/hook", () => ({
  useInfiniteCursorTable: () => ({
    data: [testState.resourceId, testState.secondResourceId]
      .filter((resourceId): resourceId is string => Boolean(resourceId))
      .map((resourceId) => ({
        id: resourceId,
        name: "Knowledge",
        description: "Description",
        state: testState.state,
        actions: ["visible"],
        update_time: "2026-08-25T10:00:00",
        create_time: "2026-08-25T10:00:00",
        user_name: "Owner",
        model: "model-1",
      })),
    loading: false,
    hasMore: false,
    search: vi.fn(),
    reload: vi.fn(),
    loadMore: vi.fn(),
  }),
}));

vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}));

import KnowledgeQa from "@/pages/KnowledgePage/KnowledgeQa";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderPage(page: ReactNode, webMenu: string[] = []) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <userContext.Provider
          value={
            {
              user: { user_id: 841, role: "", web_menu: webMenu },
            } as never
          }
        >
          {page}
        </userContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
describe.each([
  ["QA knowledge", <KnowledgeQa />, "qa-knowledge", "knowledge_library"],
])("F051 lazy row actions: %s", (_label, page, resourceId, resourceType) => {
  beforeEach(() => {
    testState.resourceId = resourceId;
    testState.secondResourceId = null;
    testState.state = 1;
    permissionApi.mockReset();
    permissionError.mockReset();
  });

  afterEach(cleanup);

  it("keeps the trigger visible and loads only after the menu opens", async () => {
    const request = deferred<{ actions: string[] }>();
    permissionApi.mockReturnValue(request.promise);
    renderPage(page);

    expect(permissionApi).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("row-actions-trigger"));

    expect(permissionApi).toHaveBeenCalledTimes(1);
    expect(permissionApi).toHaveBeenCalledWith(resourceType, resourceId);
    expect(document.querySelector('[data-value="loading"]')).not.toBeNull();
    expect(document.querySelector('[data-value="set"]')).toBeNull();

    request.resolve({ actions: ["visible", "edit", "manage_permission"] });
    await waitFor(() => {
      expect(document.querySelector('[data-value="set"]')).not.toBeNull();
      expect(
        document.querySelector('[data-value="permission"]'),
      ).not.toBeNull();
    });
    expect(document.querySelector('[data-value="delete"]')).toBeNull();
  });
});

describe("F051 lazy row action failure and busy states", () => {
  beforeEach(() => {
    testState.resourceId = "602";
    testState.secondResourceId = null;
    testState.state = 1;
    permissionApi.mockReset();
    permissionError.mockReset();
  });

  afterEach(cleanup);



  it("does not query actions for a busy row", () => {
    testState.state = 2;
    renderPage(<KnowledgeQa />);

    fireEvent.click(screen.getByTestId("row-actions-trigger"));
    expect(permissionApi).not.toHaveBeenCalled();
  });



  it("does not reopen a menu after it is closed while loading", async () => {
    testState.resourceId = "closed-while-loading";
    const request = deferred<{ actions: string[] }>();
    permissionApi.mockReturnValue(request.promise);
    renderPage(<KnowledgeQa />);

    fireEvent.click(screen.getByTestId("row-actions-trigger"));
    fireEvent.click(screen.getByTestId("row-actions-close"));
    request.resolve({ actions: ["edit"] });

    await waitFor(() => expect(permissionApi).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("row-actions-menu")).toBeNull();
  });


});
