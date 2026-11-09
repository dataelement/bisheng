import {
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
  ModelSelect: () => null,
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
const plan = {
  confirmation_id: "original-plan",
  plan_digest: "a".repeat(64),
  expires_at: "2030-01-01",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 40, type: "space" as const }],
  invalid_items: [],
  impact: {},
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
function setup(mode: "copy" | "file" | "schema") {
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
    total_count: 2,
    succeeded_count: 0,
    failed_count: 0,
    pending_count: 2,
    hidden_item_count: 0,
    retryable: false,
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
