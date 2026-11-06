import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { KnowledgeLibraryDialog } from "@/pages/KnowledgePage/components/KnowledgeLibraryDialog";
import { QaLibraryDialog } from "@/pages/KnowledgePage/components/QaLibraryDialog";
import KnowledgeFile from "@/pages/KnowledgePage/KnowledgeFile";
import KnowledgeQa from "@/pages/KnowledgePage/KnowledgeQa";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
import { useState } from "react";

const mock = vi.hoisted(() => ({
  create: vi.fn(),
  config: vi.fn(),
  navigate: vi.fn(),
  models: vi.fn(),
  bootstrap: vi.fn(),
  space: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn(), resolvedLanguage: "en" },
  }),
}));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: {} }),
}));
vi.mock("@/controllers/API", () => ({
  createFileLib: mock.create,
  updateKnowledge: vi.fn(),
  readFileLibDatabase: vi.fn(),
  copyLibDatabase: vi.fn(),
  copyQaDatabase: vi.fn(),
  deleteFileLib: vi.fn(),
}));
vi.mock("@/util/hook", () => ({
  useInfiniteCursorTable: () => ({
    data: [],
    loading: false,
    hasMore: false,
    search: vi.fn(),
    reload: vi.fn(),
    loadMore: vi.fn(),
  }),
}));
vi.mock("@/components/bs-comp/permission/useResourceActions", () => ({
  useLazyResourceActions: () => ({
    actions: {},
    loading: false,
    load: vi.fn(),
  }),
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: () => null,
}));
vi.mock("@/controllers/API/finetune", () => ({
  getKnowledgeModelConfig: mock.config,
  getModelListApi: mock.models,
}));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("react-router-dom", () => ({ useNavigate: () => mock.navigate }));
vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}));
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children,
}));
const clients: QueryClient[] = [];
function Wrapper({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => {
    const next = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    clients.push(next);
    return next;
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const scope = {
  identityKey: "user:1",
  tenantId: 60,
  managementTenantId: 60,
  view: "ordinary" as const,
};
const api = {
  ...knowledgeSpaceApi,
  getCreationSettings: mock.bootstrap,
  createSpace: mock.space,
};
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
beforeEach(() => {
  vi.clearAllMocks();
  mock.config.mockResolvedValue({ embedding_model_id: 1 });
  mock.create.mockResolvedValue({ id: 1 });
  mock.space.mockResolvedValue({ id: 1, name: "Test space" });
  mock.models.mockResolvedValue([
    {
      id: 1,
      name: "Provider",
      models: [
        {
          id: 1,
          model_name: "Embedding",
          model_type: "embedding",
          online: true,
        },
      ],
    },
  ]);
  mock.bootstrap.mockResolvedValue({
    embedding_model: { id: "1", name: "Embedding" },
    system_defaults: {
      schema_version: 1,
      document: {
        split_mode: "auto",
        separator: [""],
        separator_rule: ["after"],
        chunk_size: 300,
        chunk_overlap: 20,
        hierarchy_level: 3,
        append_title: false,
        max_chunk_size: 600,
        retain_images: 1,
        force_ocr: 1,
        enable_formula: 0,
        filter_page_header_footer: 0,
      },
      table: {
        slice_length: 10,
        header_start_row: 1,
        header_end_row: 1,
        append_header: 0,
      },
    },
  });
});

it.each([KnowledgeFile, KnowledgeQa])(
  "exposes creation to a tenant admin without a create menu",
  (Page) => {
    const view = render(
      <userContext.Provider
        value={
          {
            user: { role: "user", is_child_admin: true, web_menu: [] },
          } as never
        }
      >
        <Page />
      </userContext.Provider>,
      { wrapper: Wrapper },
    );
    expect(screen.getByRole("button", { name: "create" })).toBeVisible();
    view.rerender(
      <userContext.Provider
        value={
          {
            user: { role: "user", is_child_admin: false, web_menu: [] },
          } as never
        }
      >
        <Page />
      </userContext.Provider>,
    );
    expect(screen.queryByRole("button", { name: "create" })).toBeNull();
  },
);

it("fixes expected tenant when opening the unchanged QA form", async () => {
  const Dialog = QaLibraryDialog;
  const props = {
    datalist: [],
    open: true,
    onOpenChange: vi.fn(),
    onLoadEnd: vi.fn(),
  };
  const view = render(
    <userContext.Provider value={{ user: { leaf_tenant_id: 60 } } as never}>
      <Dialog {...props} />
    </userContext.Provider>,
  );
  await waitFor(() => expect(mock.config).toHaveBeenCalled());
  view.rerender(
    <userContext.Provider value={{ user: { leaf_tenant_id: 61 } } as never}>
      <Dialog {...props} />
    </userContext.Provider>,
  );
  fireEvent.change(screen.getByPlaceholderText("lib.enterLibraryName"), {
    target: { value: "Test library" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /^(finishCreate|completeCreation)$/ }),
  );
  await waitFor(() =>
    expect(mock.create).toHaveBeenCalledWith(
      expect.objectContaining({ expected_tenant_id: 60 }),
    ),
  );
});

it("blocks QA submission when current membership is unknown", async () => {
  const Dialog = QaLibraryDialog;
  render(
    <userContext.Provider value={{ user: {} } as never}>
      <Dialog datalist={[]} open onOpenChange={vi.fn()} onLoadEnd={vi.fn()} />
    </userContext.Provider>,
  );
  await waitFor(() => expect(mock.config).toHaveBeenCalled());
  fireEvent.change(screen.getByPlaceholderText("lib.enterLibraryName"), {
    target: { value: "Test library" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /^(finishCreate|completeCreation)$/ }),
  );
  expect(mock.create).not.toHaveBeenCalled();
});

it("pins SPACE creation to its opening scope instead of rereading a changed leaf", async () => {
  const props = {
    datalist: [],
    scope,
    api,
    open: true,
    onOpenChange: vi.fn(),
    onLoadEnd: vi.fn(),
  };
  const view = render(
    <userContext.Provider value={{ user: { leaf_tenant_id: 60 } } as never}>
      <KnowledgeLibraryDialog {...props} />
    </userContext.Provider>,
    { wrapper: Wrapper },
  );
  await screen.findByRole("spinbutton", { name: "splitLength" });
  view.rerender(
    <userContext.Provider value={{ user: { leaf_tenant_id: 61 } } as never}>
      <KnowledgeLibraryDialog {...props} />
    </userContext.Provider>,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "f118.space_name" }), {
    target: { value: "Test space" },
  });
  fireEvent.click(screen.getByRole("button", { name: "finishCreate" }));
  await waitFor(() =>
    expect(mock.space).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Test space",
        embedding_model_id: 1,
        processing_defaults: expect.any(Object),
      }),
      60,
    ),
  );
  expect(mock.create).not.toHaveBeenCalled();
});

it("blocks SPACE creation before any read when its execution tenant is unknown", async () => {
  render(
    <KnowledgeLibraryDialog
      datalist={[]}
      scope={{ ...scope, tenantId: 0, managementTenantId: null }}
      api={api}
      open
      onOpenChange={vi.fn()}
      onLoadEnd={vi.fn()}
    />,
    { wrapper: Wrapper },
  );
  await screen.findByText("f118.scope_unavailable");
  expect(mock.bootstrap).not.toHaveBeenCalled();
  expect(mock.space).not.toHaveBeenCalled();
});
