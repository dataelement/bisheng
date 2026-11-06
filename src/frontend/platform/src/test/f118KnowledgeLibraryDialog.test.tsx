import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { knowledgeSpaceApi, type SpaceCreationSettings } from "@/controllers/API/knowledgeSpace";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeLibraryDialog } from "@/pages/KnowledgePage/components/KnowledgeLibraryDialog";

const mocks = vi.hoisted(() => ({ models: vi.fn(), navigate: vi.fn(), legacy: vi.fn() }));
vi.mock("@/controllers/API", () => ({ createFileLib: mocks.legacy, updateKnowledge: mocks.legacy, getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/API/finetune", () => ({ getModelListApi: mocks.models, getKnowledgeModelConfig: async () => ({ embedding_model_id: 19 }) }));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: vi.fn() }));
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: { user_id: 7, leaf_tenant_id: 101 } }) }));
vi.mock("react-router-dom", () => ({ useNavigate: () => mocks.navigate }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en" } }) }));
vi.mock("@/pages/ModelPage/manage", () => ({ useModel: () => ({ embeddings: [{ value: 1, label: "Provider", children: [{ value: "19", label: "Model A" }] }], isLoading: false }) }));
// Preserve the existing ModelSelect port while avoiding unrelated model settings imports.
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({ ModelSelect: ({ label, value, options, onChange }: { label: string; value: string; options: { children: { value: string; label: string }[] }[]; onChange: (value: string) => void }) => <select aria-label={label || "f118.embedding_model"} value={value} onChange={event => onChange(event.target.value)}><option value="">Select</option>{options.flatMap(group => group.children).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select> }));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({ KnowledgeHint: () => null, KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children }));
const scope: KnowledgeQueryScope = { identityKey: "user:7", tenantId: 101, managementTenantId: 101, view: "ordinary" };
const bootstrap: SpaceCreationSettings = { embedding_model: { id: "19", name: "Original model" }, system_defaults: { schema_version: 1,
  document: { split_mode: "custom", separator: ["\\n", ""], separator_rule: ["after", "after"], chunk_size: 300, chunk_overlap: 20, hierarchy_level: 3, append_title: false, max_chunk_size: 600, retain_images: 1, force_ocr: 1, enable_formula: 0, filter_page_header_footer: 1 },
  table: { slice_length: 10, header_start_row: 1, header_end_row: 2, append_header: 0 },
} };
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.clearAllMocks(); });
function setup() {
  mocks.models.mockResolvedValue([{ id: 1, name: "Provider", models: [
    { id: 19, model_name: "Model A", model_type: "embedding", online: true },
    { id: 20, model_name: "Model B", model_type: "embedding", online: true },
    { id: 21, model_name: "Offline", model_type: "embedding", online: false },
    { id: 22, model_name: "Chat", model_type: "llm", online: true },
  ] }]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } }, logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } });
  clients.push(client);
  const api = { ...knowledgeSpaceApi, getCreationSettings: vi.fn().mockResolvedValue(bootstrap), createSpace: vi.fn().mockResolvedValue({ id: 8, name: "Created" }),
    getSpaceInfo: vi.fn().mockResolvedValue({ id: 7, name: "Actual name", description: "Actual description", is_released: true }),
    updateSpaceBasicInfo: vi.fn().mockResolvedValue({ id: 7, name: "Changed" }),
  };
  const changed = vi.fn(), loaded = vi.fn();
  const draw = (value = scope, open = true, mode: "create" | "edit" = "create") => <QueryClientProvider client={client}><KnowledgeLibraryDialog datalist={[]} scope={value} open={open} mode={mode} currentLib={{ id: 7, name: "Stale row", description: "Stale description", model: "old" }} onOpenChange={changed} onLoadEnd={loaded} api={api} /></QueryClientProvider>;
  return { client, api, changed, loaded, draw };
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
const ready = () => screen.findByRole("spinbutton", { name: "splitLength" });
const fillName = () => fireEvent.change(screen.getByRole("textbox", { name: "f118.space_name" }), { target: { value: "Created" } });

it("reads creation defaults and scoped model metadata only while open", async () => {
  const f = setup(), view = render(f.draw(scope, false));
  expect(f.api.getCreationSettings).not.toHaveBeenCalled(); expect(mocks.models).not.toHaveBeenCalled();
  view.rerender(f.draw()); await ready();
  expect(f.api.getCreationSettings).toHaveBeenCalledTimes(1); expect(mocks.models).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("combobox", { name: "f118.embedding_model" })).toHaveValue("19");
  expect(screen.queryByRole("option", { name: "Offline" })).toBeNull(); expect(screen.queryByRole("option", { name: "Chat" })).toBeNull();
});

it.each([false, true])("creates an actual SPACE with both rules and follows the original import=%s route", async importing => {
  const f = setup(); render(f.draw()); await ready(); fillName();
  fireEvent.change(screen.getByRole("combobox", { name: "f118.embedding_model" }), { target: { value: "20" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "splitLength" }), { target: { value: "501" } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.tables" }), { button: 0, ctrlKey: false });
  fireEvent.change(screen.getByRole("spinbutton", { name: "maxRowsPerSegment" }), { target: { value: "55" } });
  fireEvent.click(screen.getByRole("button", { name: importing ? "createImport" : "finishCreate" }));
  await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith(importing ? "/filelib/upload/8" : "/filelib/8"));
  expect(f.api.createSpace).toHaveBeenCalledWith({ name: "Created", description: "", embedding_model_id: 20, processing_defaults: { ...bootstrap.system_defaults, document: { ...bootstrap.system_defaults.document, chunk_size: 501 }, table: { ...bootstrap.system_defaults.table, slice_length: 55 } } }, 101);
  expect(mocks.legacy).not.toHaveBeenCalled(); expect(f.loaded).toHaveBeenCalledTimes(1);
  expect(bootstrap.system_defaults.document.chunk_size).toBe(300);
});

it.each([null, { id: "019", name: "Original model" }, { id: "retired", name: "Original model" }, { id: "21", name: "Original model" }])("requires explicit repair of an unusable original model %j", async embedding_model => {
  const f = setup(); f.api.getCreationSettings.mockResolvedValueOnce({ ...bootstrap, embedding_model });
  render(f.draw()); await ready(); fillName();
  expect(screen.getByRole("button", { name: "finishCreate" })).toBeDisabled();
  expect(screen.getByText("f118.invalid_embedding_model")).toBeVisible();
  if (embedding_model) expect(screen.getByText("Original model")).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "f118.embedding_model" }), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "finishCreate" }));
  await waitFor(() => expect(f.api.createSpace).toHaveBeenCalledWith(expect.objectContaining({ embedding_model_id: 20 }), 101));
});

it("blocks hidden invalid rules and unadded literal input without discarding the draft", async () => {
  const f = setup(); render(f.draw()); await ready(); fillName();
  fireEvent.change(screen.getByRole("textbox", { name: "addCustomRule" }), { target: { value: "(?P<label>name)" } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.tables" }), { button: 0, ctrlKey: false });
  expect(screen.getByRole("button", { name: "finishCreate" })).toBeDisabled();
  fireEvent.change(screen.getByRole("spinbutton", { name: "f118.header_start" }), { target: { value: "9" } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.documents" }), { button: 0, ctrlKey: false });
  expect(screen.getByRole("textbox", { name: "addCustomRule" })).toHaveValue("(?P<label>name)");
  expect(f.api.createSpace).not.toHaveBeenCalled();
});

it("keeps the draft and original ApiError after a creation failure", async () => {
  const f = setup(), error = { status_code: 19000, data: { original: true } };
  f.api.createSpace.mockRejectedValueOnce(error);
  render(f.draw()); await ready(); fillName();
  fireEvent.click(screen.getByRole("button", { name: "finishCreate" }));
  await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
  expect(screen.getByRole("textbox", { name: "f118.space_name" })).toHaveValue("Created");
  expect(f.changed).not.toHaveBeenCalled(); expect(mocks.navigate).not.toHaveBeenCalled();
});

it.each([true, false])("edits only basic information from actual detail and preserves published=%s", async is_released => {
  const f = setup(); f.api.getSpaceInfo.mockResolvedValueOnce({ id: 7, name: "Actual name", description: "Actual description", is_released });
  render(f.draw(scope, true, "edit"));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "f118.space_name" })).toHaveValue("Actual name"));
  expect(screen.queryByRole("combobox")).toBeNull(); expect(f.api.getCreationSettings).not.toHaveBeenCalled(); expect(mocks.models).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox", { name: "f118.space_name" }), { target: { value: "Changed" } });
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(f.api.updateSpaceBasicInfo).toHaveBeenCalledWith(7, { name: "Changed", description: "Actual description", is_released }));
  expect(mocks.legacy).not.toHaveBeenCalled(); expect(mocks.navigate).not.toHaveBeenCalled();
});

it("does not guess an absent publication flag when editing", async () => {
  const f = setup(); f.api.getSpaceInfo.mockResolvedValueOnce({ id: 7, name: "Actual name", description: "Actual description" });
  render(f.draw(scope, true, "edit"));
  await screen.findByDisplayValue("Actual name");
  expect(screen.getByRole("button", { name: "confirm" })).toBeDisabled();
  expect(f.api.updateSpaceBasicInfo).not.toHaveBeenCalled();
});

it("retires an initial creation GET across close and reopen", async () => {
  const f = setup(), old = deferred<SpaceCreationSettings>();
  f.api.getCreationSettings.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...bootstrap, system_defaults: { ...bootstrap.system_defaults, document: { ...bootstrap.system_defaults.document, chunk_size: 700 } } });
  const view = render(f.draw()); await waitFor(() => expect(f.api.getCreationSettings).toHaveBeenCalledTimes(1));
  view.rerender(f.draw(scope, false)); view.rerender(f.draw());
  await act(async () => old.resolve(bootstrap)); await ready();
  expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue("700");
  expect(f.api.getCreationSettings).toHaveBeenCalledTimes(2);
});

it.each(["scope", "close", "unmount", "ABA"])("does not consume late creation success after %s", async change => {
  const f = setup(), response = deferred<{ id: number; name: string }>();
  f.api.createSpace.mockReturnValueOnce(response.promise);
  const view = render(f.draw()); await ready(); fillName();
  fireEvent.click(screen.getByRole("button", { name: "finishCreate" }));
  await waitFor(() => expect(f.api.createSpace).toHaveBeenCalledTimes(1));
  if (change === "unmount") view.unmount();
  else if (change === "close") view.rerender(f.draw(scope, false));
  else { view.rerender(f.draw({ ...scope, tenantId: 202, managementTenantId: 202 })); await ready(); if (change === "ABA") { view.rerender(f.draw()); await ready(); } }
  await act(async () => response.resolve({ id: 8, name: "Created" }));
  expect(f.changed).not.toHaveBeenCalled(); expect(f.loaded).not.toHaveBeenCalled(); expect(mocks.navigate).not.toHaveBeenCalled();
});

it("rechecks lifecycle after the host's awaited reload before closing or navigating", async () => {
  const f = setup(), done = deferred<void>(); f.loaded.mockReturnValueOnce(done.promise);
  const view = render(f.draw()); await ready(); fillName();
  fireEvent.click(screen.getByRole("button", { name: "finishCreate" }));
  await waitFor(() => expect(f.loaded).toHaveBeenCalledTimes(1));
  view.rerender(f.draw(scope, false));
  await act(async () => done.resolve());
  expect(f.changed).not.toHaveBeenCalled(); expect(mocks.navigate).not.toHaveBeenCalled();
  expect(f.client.getQueryData(knowledgeQueryKeys.creation(scope))).toBeDefined();
});
