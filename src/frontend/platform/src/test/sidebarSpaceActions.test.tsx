import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import { useSidebarSpaceActions } from "@/pages/KnowledgePage/sidebar/useSidebarSpaceActions";
import type { ReactNode } from "react";
vi.mock("@bisheng/ui", async (original) => ({
  ...(await original<typeof import("@bisheng/ui")>()),
  DropdownItem: ({
    children,
    onSelect,
  }: {
    children: ReactNode;
    onSelect?: () => void;
  }) => (
    <button role="menuitem" onClick={onSelect}>
      {children}
    </button>
  ),
}));
const mocks = vi.hoisted(() => ({
  user: { user_id: 7, is_global_super: true },
  actions: {} as Record<string, string[]>,
  load: vi.fn(),
  open: vi.fn(),
}));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: mocks.user }),
}));
vi.mock("@/components/bs-comp/permission/useResourceActions", () => ({
  useLazyResourceActions: () => ({
    actions: mocks.actions,
    loading: {},
    load: mocks.load,
  }),
}));
vi.mock("@/pages/KnowledgePage/hooks/useKnowledgeDeletion", () => ({
  useKnowledgeDeletion: () => ({ open: mocks.open, view: null }),
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeDeletionDialog", () => ({
  KnowledgeDeletionDialog: () => null,
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: ({ resourceId }: { resourceId: string }) => (
    <p>permissions:{resourceId}</p>
  ),
}));
vi.mock("@/pages/KnowledgePage/components/SpaceCopyDialog", () => ({
  SpaceCopyDialog: ({ source }: { source: KnowledgeSpaceInfo }) => (
    <p>copy:{source.id}</p>
  ),
}));
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const row = {
  id: 7,
  name: "Source",
  user_id: 7,
  actions: ["delete", "manage_permission"],
};
const clients: QueryClient[] = [];
function setup(canCreate = true, onDeleted = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  function Example() {
    const menu = useSidebarSpaceActions(scope, canCreate, onDeleted);
    return (
      <>
        <button onClick={() => menu.load(row, true)}>open</button>
        {menu.render(row)}
        {menu.dialogs}
      </>
    );
  }
  return {
    ...render(
      <QueryClientProvider client={client}>
        <Example />
      </QueryClientProvider>,
    ),
    onDeleted,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.user.user_id = 7;
  mocks.actions = {};
  mocks.load.mockResolvedValue({ hasError: false });
  mocks.open.mockResolvedValue(true);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
it("loads effective actions only when opened and never trusts list-row action hints", () => {
  setup();
  expect(mocks.load).not.toHaveBeenCalled();
  expect(screen.queryByRole("menuitem")).toBeNull();
  fireEvent.click(screen.getByText("open"));
  expect(mocks.load).toHaveBeenCalledWith("7");
});
it("offers creator copy and passes the original source to its dialog", () => {
  mocks.actions = { "7": ["upload_file", "delete", "manage_permission"] };
  setup();
  fireEvent.click(
    screen.getByRole("menuitem", { name: "f118.processing_title_copy" }),
  );
  expect(screen.getByText("copy:7")).toBeVisible();
});
it("never offers copy to a noncreator administrator", () => {
  mocks.user.user_id = 9;
  mocks.actions = { "7": ["upload_file", "delete", "manage_permission"] };
  setup();
  expect(
    screen.queryByRole("menuitem", { name: "f118.processing_title_copy" }),
  ).toBeNull();
  expect(
    screen.getByRole("menuitem", { name: "deletion.delete_space" }),
  ).toBeVisible();
});
it("keeps copy behind creation eligibility and permission management behind its effective action", () => {
  mocks.actions = { "7": ["upload_file"] };
  setup(false);
  expect(screen.queryByRole("menuitem")).toBeNull();
});
it("opens permission management and the existing reference-aware deletion for the selected space", async () => {
  mocks.actions = { "7": ["delete", "manage_permission"] };
  const view = setup();
  fireEvent.click(screen.getByRole("menuitem", { name: "managePermission" }));
  expect(screen.getByText("permissions:7")).toBeVisible();
  fireEvent.click(
    screen.getByRole("menuitem", { name: "deletion.delete_space" }),
  );
  expect(mocks.open).toHaveBeenCalledWith({ spaceId: 7, kind: "delete" });
  await waitFor(() => expect(view.onDeleted).toHaveBeenCalledWith(7));
});
it("does not navigate after a retired delete result", async () => {
  let resolve!: (value: boolean) => void;
  mocks.open.mockReturnValue(
    new Promise<boolean>((yes) => {
      resolve = yes;
    }),
  );
  mocks.actions = { "7": ["delete"] };
  const view = setup();
  fireEvent.click(
    screen.getByRole("menuitem", { name: "deletion.delete_space" }),
  );
  view.unmount();
  resolve(true);
  await new Promise((yes) => setTimeout(yes, 0));
  expect(view.onDeleted).not.toHaveBeenCalled();
});
