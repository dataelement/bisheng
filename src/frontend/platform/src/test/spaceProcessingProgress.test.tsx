import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import {
  readProcessingItems,
  readProcessingJob,
  retryProcessing,
} from "@/controllers/API/knowledgeProcessing";
import type { ProcessingJobRead } from "@/controllers/API/knowledgeSpace";
import { SpaceProcessingProgress } from "@/pages/KnowledgePage/components/SpaceProcessingProgress";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
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

const client = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.useRealTimers();
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
  await act(async () => {
    await vi.mocked(bsConfirm).mock.calls.at(-1)![0].onOk?.(vi.fn());
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
});
