import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  knowledgeSpaceApi,
  type OperationPrecheck,
  type ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import * as api from "@/controllers/API/knowledgeProcessing";
import { SpaceProcessingDialog } from "@/pages/KnowledgePage/components/SpaceProcessingDialog";

vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/API/finetune", () => ({ getModelListApi: vi.fn() }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({
  embeddingGroups: () => [],
}));
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: ({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) =>
    <input aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} />,
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en" },
  }),
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  precheckSpaceCopy: vi.fn(),
  confirmSpaceCopy: vi.fn(),
  readProcessingJob: vi.fn(),
  readProcessingItems: vi.fn(),
  retryProcessing: vi.fn(),
  readProcessingTarget: vi.fn(),
  readMetadataSchema: vi.fn(),
}));
const settings: ProcessingSettingsRead = {
  space_id: 40,
  config_version: 4,
  saved_defaults: null,
  effective_defaults: {
    schema_version: 1,
    document: {
      split_mode: "auto",
      separator: ["\n", ""],
      separator_rule: ["after", "after"],
      chunk_size: 300,
      chunk_overlap: 20,
      hierarchy_level: 3,
      append_title: false,
      max_chunk_size: 600,
      retain_images: 1,
      force_ocr: 1,
      enable_formula: 0,
      filter_page_header_footer: 1,
    },
    table: {
      slice_length: 10,
      header_start_row: 1,
      header_end_row: 2,
      append_header: 0,
    },
  },
};
const plan: OperationPrecheck = {
  confirmation_id: "original-plan",
  plan_digest: "a".repeat(64),
  expires_at: "2030-01-01",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 40, type: "space" as const }],
  invalid_items: [],
  impact: {},
  requires_skip_confirmation: false,
};
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
beforeEach(() => {
  vi.spyOn(knowledgeSpaceApi, "getProcessingSettings").mockResolvedValue(
    settings,
  );
  vi.spyOn(knowledgeSpaceApi, "listProcessingJobs").mockResolvedValue({
    data: [],
    total: 0,
  });
  vi.mocked(api.readProcessingItems).mockResolvedValue({ data: [], total: 0 });
});
function setup(mode: "copy" | "file" | "schema" | "embedding") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingDialog
        scope={scope}
        spaceId={40}
        fileId={mode === "file" ? 82 : undefined}
        mode={mode}
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

it("echoes the saved Embedding model and reviews a subsequent manual choice", async () => {
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockResolvedValue({ id: 40, name: "Space", model: "19" });
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  setup("embedding");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("19"));
  fireEvent.change(screen.getByRole("textbox", { name: "f118.embedding_model" }), { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "f118.processing_review_action" }));
  await waitFor(() => expect(precheck).toHaveBeenCalledWith(40, {
    kind: "embedding_rebuild", parameters: { embedding_model_id: 25 },
  }));
});

it("does not overwrite a manual model choice when the initial read finishes late", async () => {
  let resolve!: (value: { id: number; name: string; model: string }) => void;
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockReturnValue(new Promise((done) => { resolve = done; }));
  setup("embedding");
  const review = screen.getByRole("button", { name: "f118.processing_review_action" });
  expect(review).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "f118.embedding_model" }), { target: { value: "25" } });
  resolve({ id: 40, name: "Space", model: "19" });
  await waitFor(() => expect(review).not.toBeDisabled());
  expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("25");
});

it("blocks model review after a failed current configuration read and supports retry", async () => {
  const read = vi.spyOn(knowledgeSpaceApi, "getSpaceInfo")
    .mockRejectedValueOnce(new Error("read failed"))
    .mockResolvedValueOnce({ id: 40, name: "Space", model: "19" });
  setup("embedding");
  const retry = await screen.findByRole("button", { name: "retry" });
  expect(screen.getByRole("button", { name: "f118.processing_review_action" })).toBeDisabled();
  fireEvent.click(retry);
  await waitFor(() => expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("19"));
  expect(read).toHaveBeenCalledTimes(2);
});

it("retains a legacy stored model label and rebuilds the current model without sending NaN", async () => {
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockResolvedValue({ id: 40, name: "Space", model: "legacy-embedding" });
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  setup("embedding");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("legacy-embedding"));
  fireEvent.click(screen.getByRole("button", { name: "f118.processing_review_action" }));
  await waitFor(() => expect(precheck).toHaveBeenCalledWith(40, {
    kind: "embedding_rebuild", parameters: { embedding_model_id: null },
  }));
});

it("retires a previous space's pending model read when switching panels", async () => {
  let resolve!: (value: { id: number; name: string; model: string }) => void;
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo")
    .mockReturnValueOnce(new Promise((done) => { resolve = done; }))
    .mockResolvedValueOnce({ id: 41, name: "Current", model: "25" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const draw = (spaceId: number) => <QueryClientProvider client={client}><SpaceProcessingDialog scope={scope} spaceId={spaceId} mode="embedding" open onOpenChange={vi.fn()} /></QueryClientProvider>;
  const view = render(draw(40));
  await waitFor(() => expect(knowledgeSpaceApi.getSpaceInfo).toHaveBeenCalledWith(40));
  view.rerender(draw(41));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("25"));
  await act(async () => resolve({ id: 40, name: "Retired", model: "19" }));
  expect(screen.getByRole("textbox", { name: "f118.embedding_model" })).toHaveValue("25");
});
it("copy keeps the original confirmation/key after unknown ACK and polls the real target with explicit kind", async () => {
  vi.mocked(api.precheckSpaceCopy).mockResolvedValue(plan);
  vi.mocked(api.confirmSpaceCopy)
    .mockRejectedValueOnce(new Error("unknown ACK"))
    .mockResolvedValueOnce({
      knowledge: { id: 50, name: "copy" },
      processing_job: {
        job_id: "copy-job",
        accepted: true,
        reused: true,
        state: "accepted",
      },
      completed: false,
    });
  vi.mocked(api.readProcessingJob).mockResolvedValue({
    id: "copy-job",
    space_id: 50,
    kind: "space_copy",
    state: "running",
    revision: 1,
    accepted_at: "2030-01-01",
    started_at: "2030-01-01",
    finished_at: null,
    total_count: 2,
    succeeded_count: 0,
    failed_count: 0,
    pending_count: 2,
    hidden_item_count: 0,
    retryable: false,
    obsolete_reason: null,
    error_code: null,
  });
  setup("copy");
  fireEvent.change(screen.getByRole("textbox", { name: "f118.space_name" }), {
    target: { value: "copy" },
  });
  fireEvent.click(screen.getByText("f118.processing_review_action"));
  await screen.findByText("confirm");
  fireEvent.click(screen.getByText("confirm"));
  await waitFor(() => expect(api.confirmSpaceCopy).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByText("confirm")).not.toBeDisabled());
  fireEvent.click(screen.getByText("confirm"));
  await waitFor(() => expect(api.confirmSpaceCopy).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.confirmSpaceCopy).mock.calls[0][1]).toEqual(
    vi.mocked(api.confirmSpaceCopy).mock.calls[1][1],
  );
  await waitFor(() =>
    expect(api.readProcessingJob).toHaveBeenCalledWith(
      50,
      "copy-job",
      "space_copy",
    ),
  );
  expect(screen.queryByText("completed")).toBeNull();
});
it("file processing resolves the selected physical history version and confirms the original plan", async () => {
  vi.mocked(api.readProcessingTarget).mockResolvedValue({
    file_id: 82,
    document_id: 80,
    version_id: 182,
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  const create = vi
    .spyOn(knowledgeSpaceApi, "createProcessingJob")
    .mockResolvedValue({
      completed: true,
      operation: "embedding_rebuild",
      space_id: 40,
      model_config_revision: 5,
    });
  setup("file");
  await waitFor(() =>
    expect(
      screen.getByText("f118.processing_review_action"),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("f118.processing_review_action"));
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(
      40,
      expect.objectContaining({
        kind: "file_reprocess",
        targets: [{ file_id: 82, document_id: 80, version_id: 182 }],
      }),
    ),
  );
  fireEvent.click(await screen.findByText("confirm"));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      40,
      expect.objectContaining({
        confirmation_id: plan.confirmation_id,
        plan_digest: plan.plan_digest,
      }),
    ),
  );
});

it("metadata schema review uses the real revision and waits for the original confirmation", async () => {
  vi.mocked(api.readMetadataSchema).mockResolvedValue({
    revision: 5,
    fields: [],
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  const create = vi
    .spyOn(knowledgeSpaceApi, "createProcessingJob")
    .mockResolvedValue({
      job_id: "schema-job",
      accepted: true,
      state: "accepted",
      reused: false,
    });
  setup("schema");
  fireEvent.change(
    screen.getByRole("textbox", { name: "f118.processing_field_name" }),
    { target: { value: "new-field" } },
  );
  await waitFor(() =>
    expect(
      screen.getByText("f118.processing_review_action"),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("f118.processing_review_action"));
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(40, {
      kind: "metadata_schema_change",
      parameters: {
        expected_schema_revision: 5,
        changes: [
          { operation: "add", field_name: "new-field", field_type: "string" },
        ],
      },
    }),
  );
  expect(create).not.toHaveBeenCalled();
});

it("loads only Embedding rebuild jobs for the embedded model history", async () => {
  const { SpaceProcessingPanel } = await import("@/pages/KnowledgePage/components/SpaceProcessingDialog");
  const read = vi.mocked(knowledgeSpaceApi.listProcessingJobs);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><SpaceProcessingPanel scope={scope} spaceId={40} mode="jobs" jobKind="embedding_rebuild" /></QueryClientProvider>);
  await waitFor(() => expect(read).toHaveBeenCalledWith(40, { page: 1, page_size: 20, kind: "embedding_rebuild" }));
  expect(read.mock.calls.every(([, query]) => query.kind === "embedding_rebuild")).toBe(true);
});
