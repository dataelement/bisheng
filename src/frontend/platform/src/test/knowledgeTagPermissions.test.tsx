import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BatchTagDraftDialog } from "@/pages/KnowledgePage/components/BatchTagDraftDialog";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({ permissions: vi.fn(), review: vi.fn(), tags: vi.fn() }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: mocks.permissions }));
vi.mock("@/controllers/API/knowledgeTags", () => ({ getKnowledgeTagsApi: mocks.tags }));
const scope: KnowledgeQueryScope = { identityKey: "member:7", tenantId: 101, managementTenantId: null, view: "ordinary" };
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const content = (currentScope = scope, open = true) => <QueryClientProvider client={client}>
    <BatchTagDraftDialog scope={currentScope} spaceId={7} availableTags={[{ id: 4, name: "Finance" }]}
      open={open} onClose={vi.fn()} onReview={mocks.review} />
  </QueryClientProvider>;
  const view = render(content());
  return { update: (next: KnowledgeQueryScope, open = true) => view.rerender(content(next, open)) };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.permissions.mockResolvedValue({ actions: ["visible"] });
  mocks.tags.mockResolvedValue({ data: [{ id: 11, name: "Space-only tag" }], total: 1 });
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });

it("explains the missing space permission and still reviews assignments of existing tags", async () => {
  mount();
  expect(await screen.findByText("tagEditor.spacePermissionRequired")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "batch.new_tag" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "batch.add_tag" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Finance" }));
  fireEvent.click(screen.getByRole("button", { name: "batch.review" }));
  expect(mocks.review).toHaveBeenCalledWith([4], []);
});

it("allows a local new-tag draft after space edit is verified", async () => {
  mocks.permissions.mockResolvedValue({ actions: ["visible", "edit"] });
  mount();
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "New tag" } });
  fireEvent.click(screen.getByRole("button", { name: "batch.add_tag" }));
  fireEvent.click(screen.getByRole("button", { name: "batch.review" }));
  expect(mocks.review).toHaveBeenCalledWith([], ["New tag"]);
});

it("keeps creation disabled on permission failure and supports retry without losing existing tag selections", async () => {
  mocks.permissions.mockRejectedValue(new Error("unavailable"));
  mount();
  expect(await screen.findByText("tagEditor.permissionUnavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", { name: "Finance" }));
  expect(screen.getByRole("textbox")).toBeDisabled();
  mocks.permissions.mockResolvedValue({ actions: ["edit"] });
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  expect(screen.getByRole("checkbox", { name: "Finance" })).toBeChecked();
});

it("does not reuse an old tenant's space edit permission while checking the new scope", async () => {
  mocks.permissions.mockResolvedValueOnce({ actions: ["edit"] });
  const view = mount();
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  mocks.permissions.mockReturnValue(new Promise(() => undefined));
  view.update({ ...scope, tenantId: 202, managementTenantId: 202 });
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByText("tagEditor.checkingPermission")).toBeVisible();
});

it("offers space tags absent from selected files with root visible but no root edit", async () => {
  mount();
  fireEvent.click(await screen.findByRole("checkbox", { name: "Space-only tag" }));
  expect(mocks.tags).toHaveBeenCalledWith(7, undefined, true);
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "batch.review" }));
  expect(mocks.review).toHaveBeenCalledWith([11], []);
});

it("keeps known file tags usable without root visible and does not read the root dictionary", async () => {
  mocks.permissions.mockResolvedValue({ actions: [] });
  mount();
  await screen.findByText("tagEditor.spacePermissionRequired");
  expect(mocks.tags).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Finance" }));
  fireEvent.click(screen.getByRole("button", { name: "batch.review" }));
  expect(mocks.review).toHaveBeenCalledWith([4], []);
});

it("retries a failed catalog read without losing selected file tags or granting creation", async () => {
  mocks.tags.mockRejectedValueOnce(new Error("unavailable"));
  mount();
  await screen.findByText("batch.tags_load_failed");
  fireEvent.click(screen.getByRole("checkbox", { name: "Finance" }));
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(await screen.findByRole("checkbox", { name: "Space-only tag" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Finance" })).toBeChecked();
  expect(screen.getByRole("textbox")).toBeDisabled();
});

it("does not display a late catalog response after switching tenant scope", async () => {
  let resolve!: (value: { data: { id: number; name: string }[]; total: number }) => void;
  mocks.tags.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const view = mount();
  await waitFor(() => expect(mocks.tags).toHaveBeenCalledOnce());
  mocks.permissions.mockResolvedValue({ actions: [] });
  view.update({ ...scope, tenantId: 202 });
  await act(async () => { resolve({ data: [{ id: 12, name: "Old tenant" }], total: 1 }); });
  expect(screen.queryByRole("checkbox", { name: "Old tenant" })).not.toBeInTheDocument();
});
