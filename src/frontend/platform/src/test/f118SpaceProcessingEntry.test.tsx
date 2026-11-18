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
  type ProcessingJobRead,
  type ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import * as indexApi from "@/controllers/API/knowledgeIndex";
import * as api from "@/controllers/API/knowledgeProcessing";
import {
  SpaceProcessingDialog,
  SpaceProcessingPanel,
} from "@/pages/KnowledgePage/components/SpaceProcessingDialog";

vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/API/knowledgeIndex", () => ({
  readFileMetadata: vi.fn(),
}));
vi.mock("@/pages/KnowledgePage/components/FileProcessingPreview", () => ({
  FileProcessingPreview: ({
    onReady,
  }: {
    onReady: (ready: boolean) => void;
  }) => <button onClick={() => onReady(true)}>preview-complete</button>,
}));
vi.mock("@/controllers/API/finetune", () => ({ getModelListApi: vi.fn() }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({
  embeddingGroups: () => [],
}));
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: ({
    value,
    onChange,
    label,
  }: {
    value: string;
    onChange: (value: string) => void;
    label: string;
  }) => (
    <input
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
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
  vi.mocked(indexApi.readFileMetadata).mockResolvedValue({
    id: 82,
    file_name: "history.txt",
    status: 2,
  });
  vi.spyOn(knowledgeSpaceApi, "getProcessingSettings").mockResolvedValue(
    settings,
  );
  vi.spyOn(knowledgeSpaceApi, "listProcessingJobs").mockResolvedValue({
    data: [],
    total: 0,
  });
  vi.mocked(api.readProcessingItems).mockResolvedValue({ data: [], total: 0 });
});
function setup(mode: "file" | "embedding") {
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
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockResolvedValue({
    id: 40,
    name: "Space",
    model: "19",
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  setup("embedding");
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "f118.embedding_model" }),
    ).toHaveValue("19"),
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "f118.embedding_model" }),
    { target: { value: "25" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "f118.processing_review_action" }),
  );
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(40, {
      kind: "embedding_rebuild",
      parameters: { embedding_model_id: 25 },
    }),
  );
});

it("does not overwrite a manual model choice when the initial read finishes late", async () => {
  let resolve!: (value: { id: number; name: string; model: string }) => void;
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  setup("embedding");
  const review = screen.getByRole("button", {
    name: "f118.processing_review_action",
  });
  expect(review).toBeDisabled();
  fireEvent.change(
    screen.getByRole("textbox", { name: "f118.embedding_model" }),
    { target: { value: "25" } },
  );
  resolve({ id: 40, name: "Space", model: "19" });
  await waitFor(() => expect(review).not.toBeDisabled());
  expect(
    screen.getByRole("textbox", { name: "f118.embedding_model" }),
  ).toHaveValue("25");
});

it("blocks model review after a failed current configuration read and supports retry", async () => {
  const read = vi
    .spyOn(knowledgeSpaceApi, "getSpaceInfo")
    .mockRejectedValueOnce(new Error("read failed"))
    .mockResolvedValueOnce({ id: 40, name: "Space", model: "19" });
  setup("embedding");
  const retry = await screen.findByRole("button", { name: "retry" });
  expect(
    screen.getByRole("button", { name: "f118.processing_review_action" }),
  ).toBeDisabled();
  fireEvent.click(retry);
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "f118.embedding_model" }),
    ).toHaveValue("19"),
  );
  expect(read).toHaveBeenCalledTimes(2);
});

it("retains a legacy stored model label and rebuilds the current model without sending NaN", async () => {
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo").mockResolvedValue({
    id: 40,
    name: "Space",
    model: "legacy-embedding",
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  setup("embedding");
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "f118.embedding_model" }),
    ).toHaveValue("legacy-embedding"),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "f118.processing_review_action" }),
  );
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(40, {
      kind: "embedding_rebuild",
      parameters: { embedding_model_id: null },
    }),
  );
});

it("retires a previous space's pending model read when switching panels", async () => {
  let resolve!: (value: { id: number; name: string; model: string }) => void;
  vi.spyOn(knowledgeSpaceApi, "getSpaceInfo")
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce({ id: 41, name: "Current", model: "25" });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const draw = (spaceId: number) => (
    <QueryClientProvider client={client}>
      <SpaceProcessingDialog
        scope={scope}
        spaceId={spaceId}
        mode="embedding"
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>
  );
  const view = render(draw(40));
  await waitFor(() =>
    expect(knowledgeSpaceApi.getSpaceInfo).toHaveBeenCalledWith(40),
  );
  view.rerender(draw(41));
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "f118.embedding_model" }),
    ).toHaveValue("25"),
  );
  await act(async () => resolve({ id: 40, name: "Retired", model: "19" }));
  expect(
    screen.getByRole("textbox", { name: "f118.embedding_model" }),
  ).toHaveValue("25");
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
      screen.getByText("f118.processing_preview_chunks"),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("f118.processing_preview_chunks"));
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(
      40,
      expect.objectContaining({
        kind: "file_reprocess",
        targets: [{ file_id: 82, document_id: 80, version_id: 182 }],
      }),
    ),
  );
  expect(screen.getByText("f118.processing_replace_chunks")).toBeDisabled();
  fireEvent.click(await screen.findByText("preview-complete"));
  expect(screen.queryByText("f118.processing_review")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("f118.processing_replace_chunks"));
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

it("fetches and retries move tasks using their job kind", async () => {
  const job: ProcessingJobRead = {
    id: "move-job",
    space_id: 40,
    kind: "move_index",
    state: "failed",
    revision: 3,
    accepted_at: "2026-11-17",
    started_at: null,
    finished_at: null,
    total_count: 1,
    pending_count: 0,
    succeeded_count: 0,
    failed_count: 1,
    hidden_item_count: 0,
    retryable: true,
    obsolete_reason: null,
    error_code: null,
  };
  const list = vi
    .mocked(knowledgeSpaceApi.listProcessingJobs)
    .mockResolvedValue({ data: [job], total: 1 });
  vi.mocked(api.readProcessingJob).mockResolvedValue(job);
  vi.mocked(api.retryProcessing).mockResolvedValue({
    job_id: job.id,
    accepted: true,
    state: "accepted",
    reused: false,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingPanel
        scope={scope}
        spaceId={40}
        mode="jobs"
        jobKind="move_index"
        presentation="inline"
      />
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: "move.jobs" })).toBeVisible();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "move.jobs · f118.processing_state_failed",
    }),
  );
  expect(list).toHaveBeenCalledWith(40, {
    page: 1,
    page_size: 20,
    kind: "move_index",
  });
  await waitFor(() =>
    expect(api.readProcessingJob).toHaveBeenCalledWith(
      40,
      job.id,
      "move_index",
    ),
  );
  expect(api.readProcessingItems).toHaveBeenCalledWith(
    40,
    job.id,
    { page: 1, page_size: 20, state: undefined },
    "move_index",
  );
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  await waitFor(() =>
    expect(api.retryProcessing).toHaveBeenCalledWith(
      40,
      job.id,
      { expected_job_revision: 3, idempotency_key: expect.any(String) },
      "move_index",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "detail.back_to_jobs" }));
  expect(
    await screen.findByRole("button", {
      name: "move.jobs · f118.processing_state_failed",
    }),
  ).toBeVisible();
});

it("loads only Embedding rebuild jobs for the embedded model history", async () => {
  const read = vi.mocked(knowledgeSpaceApi.listProcessingJobs);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingPanel
        scope={scope}
        spaceId={40}
        mode="jobs"
        jobKind="embedding_rebuild"
      />
    </QueryClientProvider>,
  );
  await waitFor(() =>
    expect(read).toHaveBeenCalledWith(40, {
      page: 1,
      page_size: 20,
      kind: "embedding_rebuild",
    }),
  );
  expect(
    read.mock.calls.every(([, query]) => query.kind === "embedding_rebuild"),
  ).toBe(true);
});

it.each(["xlsx", "html", "mp3", "mp4"])(
  "shows only rules applicable to %s",
  async (suffix) => {
    vi.mocked(api.readProcessingTarget).mockResolvedValue({
      file_id: 82,
      document_id: 80,
      version_id: 182,
    });
    vi.mocked(indexApi.readFileMetadata).mockResolvedValue({
      id: 82,
      file_name: `sample.${suffix}`,
      status: 2,
    });
    setup("file");
    await waitFor(() =>
      expect(
        screen.getByText("f118.processing_preview_chunks"),
      ).not.toBeDisabled(),
    );
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(
      screen.queryByText("f118.processing_kind_file_resplit"),
    ).not.toBeInTheDocument();
    if (["mp3", "mp4"].includes(suffix)) {
      expect(
        screen.getByText("f118.specialized_processing_rules"),
      ).toBeInTheDocument();
      expect(screen.queryByText("docSplitStrategy")).not.toBeInTheDocument();
    } else if (suffix === "xlsx") {
      expect(screen.queryByText("docSplitStrategy")).not.toBeInTheDocument();
    } else {
      expect(
        screen.queryByRole("radio", { name: /hierarchicalSplit/ }),
      ).not.toBeInTheDocument();
    }
  },
);
