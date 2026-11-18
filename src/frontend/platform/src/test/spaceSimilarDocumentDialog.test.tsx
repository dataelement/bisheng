import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceSimilarDocumentDialog } from "@/pages/KnowledgePage/components/SpaceSimilarDocumentDialog";
import { knowledgeVersionsApi } from "@/controllers/API/knowledgeVersions";
const mock = vi.hoisted(() => ({ read: vi.fn(), confirm: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: { get: mock.read }, showApiError: mock.error }));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: mock.confirm }));
const scope = { identityKey: "u:3", tenantId: 1, managementTenantId: 1, view: "admin" as const };
const files = [
  { knowledge_file_id: 11, file_name: "First.pdf", candidate_count: 1, current_primary_version_no: 2 },
  { knowledge_file_id: 12, file_name: "Second.pdf", candidate_count: 0, current_primary_version_no: 1 },
];
const clients: QueryClient[] = [];
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } }, logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } });
  clients.push(client);
  const api = { ...knowledgeVersionsApi, getVersionRecommendations: vi.fn().mockResolvedValue([{ target_document_id: 61, title: "Recommended", similarity: 0.98, current_primary_version_no: 3, doc_code: "DOC61" }]), searchVersionDocuments: vi.fn().mockResolvedValue({ data: [], has_more: false, next_cursor: null, page_size: 40 }), linkSpaceFileVersion: vi.fn().mockResolvedValue({ document_id: 61, new_version_no: 4 }), dismissSpaceSimilarFile: vi.fn().mockResolvedValue({}) };
  const close = vi.fn();
  const draw = (current = scope) => <QueryClientProvider client={client}><SpaceSimilarDocumentDialog scope={current} spaceId={7} api={api} onOpenChange={close} /></QueryClientProvider>;
  return { ...render(draw()), api, close, draw };
}
beforeEach(() => { vi.clearAllMocks(); mock.read.mockResolvedValue(files); });
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });
it("shows the client's pending column and four sections with recommendation similarity", async () => {
  const { api } = setup();
  await screen.findByText("Recommended");
  for (const label of ["section_current_file", "section_recommendations", "section_search", "section_dismiss"]) expect(screen.getByText(label)).toBeVisible();
  expect(screen.getByText(/98%/)).toBeVisible();
  const second = screen.getByRole("button", { name: /Second.pdf/ });
  fireEvent.click(second);
  await waitFor(() => expect(api.getVersionRecommendations).toHaveBeenLastCalledWith(12, false, expect.any(AbortSignal)));
  expect(second).toHaveAttribute("aria-pressed", "true");
});
it("links in the same direction, advances to the next file, then keeps it independent", async () => {
  const { api } = setup();
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  expect(api.linkSpaceFileVersion).not.toHaveBeenCalled();
  mock.read.mockResolvedValueOnce([files[1]]).mockResolvedValue([]);
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.linkSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(11, 61, expect.any(AbortSignal));
  await waitFor(() => expect(screen.queryByRole("button", { name: /First.pdf/ })).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "btn_dismiss" }));
  expect(api.dismissSpaceSimilarFile).toHaveBeenCalledExactlyOnceWith(12, expect.any(AbortSignal));
  expect(await screen.findByText("similar_dialog_empty")).toBeVisible();
});
it("debounces keyword edits and clears search when switching pending files", async () => {
  const { api } = setup();
  await screen.findByText("Recommended");
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "manual" } });
  await waitFor(() => expect(api.searchVersionDocuments).toHaveBeenCalledWith(7, 11, "manual", false, undefined, expect.any(AbortSignal)));
  fireEvent.click(screen.getByRole("button", { name: /Second.pdf/ }));
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(screen.queryByText("no_search_results")).toBeNull();
});
it("retires a confirmation when tenant changes before the user confirms", async () => {
  const mounted = setup();
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  expect(await screen.findByRole("alertdialog")).toBeVisible();
  mounted.rerender(mounted.draw({ ...scope, managementTenantId: 60 }));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(mounted.api.linkSpaceFileVersion).not.toHaveBeenCalled();
});
it("freezes writes and selection after an uncertain mutation while preserving the error", async () => {
  const { api } = setup();
  api.linkSpaceFileVersion.mockRejectedValueOnce(new Error("unknown result"));
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(screen.getByRole("alert")).toHaveTextContent("uncertain");
  expect(screen.getByRole("button", { name: /Second.pdf/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "btn_dismiss" })).toBeDisabled();
});
it("does not turn a failed pending-list read into an empty success state", async () => {
  mock.read.mockRejectedValue(new Error("failed"));
  setup();
  const error = await screen.findByRole("alert");
  expect(within(error).getByRole("button", { name: "retry" })).toBeVisible();
  expect(screen.queryByText("similar_dialog_empty")).toBeNull();
});
