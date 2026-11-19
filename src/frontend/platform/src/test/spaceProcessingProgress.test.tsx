import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import {
  readProcessingItems,
  readProcessingJob,
  retryProcessing,
} from "@/controllers/API/knowledgeProcessing";
import type { ProcessingItemRead, ProcessingJobRead } from "@/controllers/API/knowledgeSpace";
import { SpaceProcessingProgress } from "@/pages/KnowledgePage/components/SpaceProcessingProgress";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { showApiError } from "@/controllers/request";
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  readProcessingItems: vi.fn(),
  readProcessingJob: vi.fn(),
  retryProcessing: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => key === "f118.processing_counts"
      ? `${key} ${values?.completed}/${values?.failed}/${values?.pending}`
      : key,
  }),
}));

const client = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

it("shows loading instead of retry while a move job has not arrived", async () => {
  vi.mocked(readProcessingJob).mockReturnValue(new Promise(() => undefined));
  vi.mocked(readProcessingItems).mockReturnValue(new Promise(() => undefined));
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="job-pending"
        kind="move_index"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("status", { name: "loading" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "retry" })).toBeNull();
});

it("shows loading before move progress arrives and offers retry only once the read fails", async () => {
  let rejectRead!: (error: Error) => void;
  vi.mocked(readProcessingJob).mockImplementation(
    () => new Promise((_resolve, reject) => { rejectRead = reject; }),
  );
  vi.mocked(readProcessingItems).mockResolvedValue({ data: [], total: 0 });
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="move-job"
        kind="move_index"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("status", { name: "loading" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "retry" })).not.toBeInTheDocument();
  await act(async () => rejectRead(new Error("Progress read failed")));
  expect(await screen.findByRole("alert")).toHaveTextContent("detail.load_failed");
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(readProcessingJob).toHaveBeenCalledTimes(2);
  expect(await screen.findByRole("status", { name: "loading" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "retry" })).not.toBeInTheDocument();
});

it("polls metadata progress and requests only failed items when failures appear", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const running: ProcessingJobRead = {
    id: "job-7",
    space_id: 7,
    kind: "metadata_schema_change",
    state: "running",
    revision: 2,
    accepted_at: "2026-11-17T07:00:00Z",
    started_at: "2026-11-17T07:00:01Z",
    finished_at: null,
    total_count: 20,
    succeeded_count: 6,
    failed_count: 0,
    pending_count: 14,
    hidden_item_count: 0,
    retryable: false,
    obsolete_reason: null,
    error_code: null,
  };
  vi.mocked(readProcessingJob)
    .mockResolvedValueOnce(running)
    .mockResolvedValueOnce(running)
    .mockResolvedValue({
      ...running,
      state: "partial_failed",
      revision: 3,
      finished_at: "2026-11-17T07:00:03Z",
      succeeded_count: 19,
      failed_count: 1,
      pending_count: 0,
      retryable: true,
    });
  vi.mocked(readProcessingItems).mockResolvedValue({
    data: [
      {
        id: "item-38",
        file_id: 38,
        file_name: "changed-metadata.txt",
        failure_reason: "file_changed",
        document_id: 62,
        version_id: 95,
        step: "metadata_index_written",
        state: "failed",
        attempt: 1,
        error_code: 10953,
        message: null,
        retryable: true,
      },
    ],
    total: 1,
  });

  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="job-7"
        kind="metadata_schema_change"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("30%")).toBeVisible();
  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "30",
  );
  expect(screen.queryByRole("table")).toBeNull();
  expect(readProcessingItems).not.toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(readProcessingJob).toHaveBeenCalledTimes(2);
  expect(readProcessingItems).not.toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });

  expect(
    await screen.findByText("f118.processing_state_partial_failed"),
  ).toBeVisible();
  const details = await screen.findByRole("table", {
    name: "f118.processing_items",
  });
  expect(
    within(details).getByRole("rowheader", { name: "changed-metadata.txt" }),
  ).toBeVisible();
  expect(
    within(details).getByRole("cell", { name: "f118.processing_item_failed" }),
  ).toBeVisible();
  expect(
    within(details).getByRole("cell", { name: "f118.failure_file_changed" }),
  ).toBeVisible();
  expect(readProcessingItems).toHaveBeenCalledExactlyOnceWith(
    7,
    "job-7",
    { page: 1, page_size: 20, state: "failed" },
    "metadata_schema_change",
  );
});

it("requires explicit confirmation before refreshing failed copy inputs", async () => {
  vi.mocked(readProcessingJob).mockReset().mockResolvedValue({
    id: "copy-7",
    space_id: 7,
    kind: "space_copy",
    state: "failed",
    revision: 5,
    accepted_at: "2026-11-18T07:00:00Z",
    started_at: null,
    finished_at: null,
    total_count: 1,
    succeeded_count: 0,
    failed_count: 1,
    pending_count: 0,
    hidden_item_count: 0,
    retryable: true,
    obsolete_reason: null,
    error_code: null,
  });
  vi.mocked(readProcessingItems).mockResolvedValue({ data: [], total: 0 });
  vi.mocked(retryProcessing).mockReset().mockResolvedValue({
    job_id: "copy-7",
    state: "accepted",
    reused: false,
    accepted: true,
  });
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="copy-7"
        kind="space_copy"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "f118.copy_refresh_source" }),
  );
  expect(retryProcessing).not.toHaveBeenCalled();
  expect(bsConfirm).toHaveBeenCalledWith(
    expect.objectContaining({ desc: "f118.copy_refresh_source_notice" }),
  );
  const close = vi.fn();
  await act(async () => {
    await vi.mocked(bsConfirm).mock.calls.at(-1)![0].onOk?.(close);
  });
  await waitFor(() =>
    expect(retryProcessing).toHaveBeenCalledWith(
      7,
      "copy-7",
      expect.objectContaining({
        expected_job_revision: 5,
        refresh_source: true,
      }),
      "space_copy",
    ),
  );
  expect(close).toHaveBeenCalledOnce();
});

it("closes the copy refresh dialog when the job can no longer be retried", async () => {
  const failed = {
    id: "copy-7",
    space_id: 7,
    kind: "space_copy" as const,
    state: "failed" as const,
    revision: 5,
    accepted_at: "2026-11-18T07:00:00Z",
    started_at: null,
    finished_at: null,
    total_count: 17,
    succeeded_count: 1,
    failed_count: 0,
    pending_count: 16,
    hidden_item_count: 0,
    retryable: true,
    obsolete_reason: null,
    error_code: null,
  };
  let current: ProcessingJobRead = failed;
  vi.mocked(readProcessingJob).mockReset().mockImplementation(async () => current);
  vi.mocked(readProcessingItems).mockResolvedValue({ data: [], total: 0 });
  vi.mocked(retryProcessing).mockReset();
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="copy-7"
        kind="space_copy"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "f118.copy_refresh_source" }),
  );
  current = { ...failed, state: "running", revision: 6, retryable: false };
  const close = vi.fn();
  await act(async () => {
    await vi.mocked(bsConfirm).mock.calls.at(-1)![0].onOk?.(close);
  });
  expect(retryProcessing).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalledOnce();
});

it("closes the copy refresh dialog after a rejected retry", async () => {
  vi.mocked(readProcessingJob).mockReset().mockResolvedValue({
    id: "copy-7",
    space_id: 7,
    kind: "space_copy",
    state: "failed",
    revision: 5,
    accepted_at: "2026-11-18T07:00:00Z",
    started_at: null,
    finished_at: null,
    total_count: 1,
    succeeded_count: 0,
    failed_count: 1,
    pending_count: 0,
    hidden_item_count: 0,
    retryable: true,
    obsolete_reason: null,
    error_code: null,
  });
  vi.mocked(readProcessingItems).mockResolvedValue({ data: [], total: 0 });
  vi.mocked(retryProcessing).mockReset().mockRejectedValue(new Error("18084"));
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7}
        jobId="copy-7"
        kind="space_copy"
        scope={{
          identityKey: "user:5",
          tenantId: 60,
          managementTenantId: 60,
          view: "ordinary",
        }}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "f118.copy_refresh_source" }),
  );
  const close = vi.fn();
  await act(async () => {
    await vi.mocked(bsConfirm).mock.calls.at(-1)![0].onOk?.(close);
  });
  expect(showApiError).toHaveBeenCalled();
  expect(close).toHaveBeenCalledOnce();
});

it("filters history items on the server from later pages and recovers an empty selection", async () => {
  const job: ProcessingJobRead = {
    id: "history-7", space_id: 7, kind: "move_index", state: "partial_failed", revision: 2,
    accepted_at: "2026-11-18", started_at: null, finished_at: null,
    total_count: 21, succeeded_count: 20, failed_count: 1, pending_count: 0,
    hidden_item_count: 0, retryable: false, obsolete_reason: null, error_code: null,
  };
  const succeeded: ProcessingItemRead[] = Array.from({ length: 20 }, (_, index) => ({
    id: `item-${index + 1}`, file_id: index + 1, file_name: `File ${index + 1}.txt`,
    document_id: index + 1, version_id: index + 1, step: "index_written", state: "succeeded",
    attempt: 1, error_code: null, message: null, retryable: false,
  }));
  const failed: ProcessingItemRead = {
    ...succeeded[0], id: "failed-item", file_id: 21, file_name: "Changed.txt",
    state: "failed", failure_reason: "file_changed", retryable: true,
  };
  const records = [...succeeded, failed];
  vi.mocked(readProcessingJob).mockReset().mockResolvedValue(job);
  const read = vi.mocked(readProcessingItems).mockReset().mockImplementation(async (_space, _job, query) => {
    const filtered = records.filter((item) => !query.state || item.state === query.state);
    const offset = ((query.page ?? 1) - 1) * (query.page_size ?? 20);
    return { data: filtered.slice(offset, offset + (query.page_size ?? 20)), total: filtered.length };
  });
  render(
    <QueryClientProvider client={client}>
      <SpaceProcessingProgress
        spaceId={7} jobId={job.id} kind="move_index" onBack={vi.fn()}
        scope={{ identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" }}
      />
    </QueryClientProvider>,
  );
  const interaction = userEvent.setup();
  const table = await screen.findByRole("table", { name: "f118.processing_items" });
  const summary = await screen.findByText("f118.processing_counts 20/1/0");
  expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
  expect(within(table).queryByRole("columnheader", { name: "batch.column_reason" })).not.toBeInTheDocument();
  const first = (await within(table).findByRole("rowheader", { name: "File 1.txt" })).closest("tr")!;
  expect(within(first).queryByRole("button")).not.toBeInTheDocument();
  expect(within(first).getByText("f118.processing_item_succeeded").parentElement).toHaveClass("text-success", "h-5");
  await interaction.click(screen.getByRole("button", { name: "pagination.next" }));
  expect(await screen.findByRole("rowheader", { name: "Changed.txt" })).toBeVisible();
  expect(read).toHaveBeenLastCalledWith(7, job.id, { page: 2, page_size: 20, state: undefined }, "move_index");

  const selectStatus = async (label: string) => {
    await interaction.click(screen.getByRole("combobox", { name: /^f118.processing_filter_status/ }));
    await interaction.click(await screen.findByRole("option", { name: label }));
  };
  await selectStatus("f118.processing_item_failed");
  await waitFor(() => expect(read).toHaveBeenLastCalledWith(7, job.id, { page: 1, page_size: 20, state: "failed" }, "move_index"));
  const filtered = (await screen.findByRole("rowheader", { name: "Changed.txt" })).closest("tr")!;
  expect(within(filtered).getByText("f118.processing_item_failed").parentElement).toHaveClass("text-danger", "h-5");
  expect(screen.queryByText("f118.failure_file_changed")).not.toBeInTheDocument();
  await interaction.hover(within(filtered).getByRole("button", { name: "f118.failure_file_changed" }));
  expect(await screen.findByRole("tooltip")).toHaveTextContent("f118.failure_file_changed");
  await interaction.keyboard("{Escape}");

  await selectStatus("f118.processing_item_running");
  expect(await screen.findByText("f118.processing_no_matching_items")).toBeVisible();
  expect(screen.getByRole("table", { name: "f118.processing_items" })).toBeVisible();
  expect(screen.getByText("f118.processing_counts 20/1/0")).toBe(summary);
  await selectStatus("all");
  expect(await screen.findByRole("rowheader", { name: "File 1.txt" })).toBeVisible();
  expect(read).toHaveBeenLastCalledWith(7, job.id, { page: 1, page_size: 20, state: undefined }, "move_index");
  expect(screen.queryByText("f118.processing_no_matching_items")).not.toBeInTheDocument();
  expect(screen.getByText("f118.processing_counts 20/1/0")).toBe(summary);
});
