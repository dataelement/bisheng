import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceMetadataPanel } from "@/pages/KnowledgePage/components/SpaceMetadataPanel";
import {
  knowledgeSpaceApi,
  type ProcessingJobRead,
} from "@/controllers/API/knowledgeSpace";
import { createPlatformQueryClient } from "@/queryClient";
const mocks = vi.hoisted(() => ({
  read: vi.fn(),
  error: vi.fn(),
  legacy: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  readMetadataSchema: mocks.read,
}));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API", () => ({
  addMetadata: mocks.legacy,
  updateMetadataFields: mocks.legacy,
  deleteMetadataFields: mocks.legacy,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  KnowledgeHint: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingProgress", () => ({
  SpaceProcessingProgress: ({ jobId }: { jobId: string }) => (
    <p data-job-id={jobId}>updating-metadata</p>
  ),
}));
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const clients: QueryClient[] = [];
const plan = {
  confirmation_id: "plan",
  plan_digest: "digest",
  can_execute: true,
  check_complete: true,
  valid_items: [],
  invalid_items: [],
  expires_at: "later",
  impact: {},
  requires_skip_confirmation: false,
};
const processingJob: ProcessingJobRead = {
  id: "job",
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
function mount(client = createPlatformQueryClient()) {
  if (!clients.includes(client)) clients.push(client);
  const view = render(
    <QueryClientProvider client={client}>
      <SpaceMetadataPanel scope={scope} spaceId={7} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return { ...view, client };
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  mocks.read.mockResolvedValue({ revision: 5, fields: [] });
  vi.spyOn(knowledgeSpaceApi, "listProcessingJobs").mockResolvedValue({
    data: [],
    total: 0,
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
it("shows the old built-in rows read-only and no separate precheck button", async () => {
  mount();
  await screen.findByText("builtInMetadata");
  for (const key of [
    "document_id",
    "document_name",
    "upload_time",
    "update_time",
    "uploader",
    "updater",
  ])
    expect(screen.getByText(key)).toBeVisible();
  expect(screen.queryByRole("button", { name: "rename" })).toBeNull();
  expect(screen.queryByText("f118.processing_review_action")).toBeNull();
  expect(screen.queryByText("updating-metadata")).toBeNull();
});

it("shows the create form above the visible lists and restores focus on cancel", async () => {
  mocks.read.mockResolvedValue({
    revision: 5,
    fields: [{ field_name: "category", field_type: "string" }],
  });
  mount();
  const create = await screen.findByRole("button", { name: "createMetadata" });
  const dialog = screen.getByRole("dialog", { name: "metaData" });
  const customField = within(dialog).getByText("category");
  const builtInField = within(dialog).getByText("document_id");
  fireEvent.click(create);

  expect(screen.getByRole("dialog", { name: "metaData" })).toBe(dialog);
  expect(screen.getAllByRole("dialog", { hidden: true })).toEqual([dialog]);
  const form = within(dialog).getByRole("form", { name: "createMetadata" });
  const name = within(form).getByRole("textbox", { name: "metadatainfor.name" });
  expect(customField).toBeVisible();
  expect(builtInField).toBeVisible();
  expect(
    form.compareDocumentPosition(customField) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  await waitFor(() => expect(name).toHaveFocus());

  fireEvent.click(within(form).getByRole("button", { name: "cancel" }));

  expect(screen.getByRole("dialog", { name: "metaData" })).toBe(dialog);
  expect(form).not.toBeVisible();
  await waitFor(() =>
    expect(within(dialog).getByRole("button", { name: "createMetadata" })).toHaveFocus(),
  );
});

it("explains invalid uppercase metadata names before calling the backend", async () => {
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing");
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "createMetadata" }));
  fireEvent.change(await screen.findByPlaceholderText("pleaseEnter"), { target: { value: "AAA" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(screen.getByText("nameFormatError")).toBeVisible());
  expect(precheck).not.toHaveBeenCalled();
});

it("resumes a submitted metadata job on reopen until it is complete", async () => {
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  const create = vi
    .spyOn(knowledgeSpaceApi, "createProcessingJob")
    .mockImplementation(async () => {
      mocks.read.mockResolvedValue({
        revision: 6,
        fields: [{ field_name: "category", field_type: "string" }],
      });
      return {
        job_id: "job",
        accepted: true,
        state: "accepted",
        reused: false,
      };
    });
  const first = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "createMetadata" }),
  );
  fireEvent.change(await screen.findByPlaceholderText("pleaseEnter"), {
    target: { value: "category" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        confirmation_id: "plan",
        plan_digest: "digest",
      }),
    ),
  );
  expect(precheck).toHaveBeenCalledWith(7, {
    kind: "metadata_schema_change",
    parameters: {
      expected_schema_revision: 5,
      changes: [
        { operation: "add", field_name: "category", field_type: "string" },
      ],
    },
  });
  expect(mocks.legacy).not.toHaveBeenCalled();
  expect(await screen.findByText("updating-metadata")).toBeVisible();
  await waitFor(() => expect(screen.getAllByText("category")).toHaveLength(1));

  first.unmount();
  vi.mocked(knowledgeSpaceApi.listProcessingJobs).mockResolvedValue({
    data: [processingJob],
    total: 1,
  });
  const reopened = mount(first.client);
  expect(await screen.findByText("updating-metadata")).toHaveAttribute(
    "data-job-id",
    "job",
  );
  expect(knowledgeSpaceApi.listProcessingJobs).toHaveBeenLastCalledWith(7, {
    page: 1,
    page_size: 1,
    kind: "metadata_schema_change",
  });
  expect(screen.getByRole("button", { name: "createMetadata" })).toBeDisabled();

  reopened.unmount();
  vi.mocked(knowledgeSpaceApi.listProcessingJobs).mockResolvedValue({
    data: [
      {
        ...processingJob,
        state: "succeeded",
        finished_at: "2026-11-17T07:00:03Z",
        succeeded_count: processingJob.total_count,
        pending_count: 0,
      },
    ],
    total: 1,
  });
  mount(first.client);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "createMetadata" })).toBeEnabled(),
  );
  expect(screen.getByText("category")).toBeVisible();
  expect(screen.queryByText("updating-metadata")).toBeNull();
  expect(create).toHaveBeenCalledTimes(1);
});

it("recovers a partial failure and follows a new job after another edit", async () => {
  vi.mocked(knowledgeSpaceApi.listProcessingJobs).mockResolvedValue({
    data: [
      {
        ...processingJob,
        id: "failed-job",
        state: "partial_failed",
        finished_at: "2026-11-17T07:00:03Z",
        succeeded_count: 19,
        failed_count: 1,
        pending_count: 0,
        retryable: true,
      },
    ],
    total: 1,
  });
  vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockResolvedValue({
    job_id: "next-job",
    accepted: true,
    state: "accepted",
    reused: false,
  });
  mount();
  expect(await screen.findByText("updating-metadata")).toHaveAttribute(
    "data-job-id",
    "failed-job",
  );
  const add = await screen.findByRole("button", { name: "createMetadata" });
  expect(add).toBeEnabled();
  fireEvent.click(add);
  fireEvent.change(await screen.findByPlaceholderText("pleaseEnter"), {
    target: { value: "next_category" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(screen.getByText("updating-metadata")).toHaveAttribute(
      "data-job-id",
      "next-job",
    ),
  );
  expect(create).toHaveBeenCalledTimes(1);
});
it("does not confirm incomplete or blocked prechecks", async () => {
  vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue({
    ...plan,
    check_complete: false,
    can_execute: false,
  });
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob");
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "createMetadata" }),
  );
  fireEvent.change(await screen.findByPlaceholderText("pleaseEnter"), {
    target: { value: "category" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(create).not.toHaveBeenCalled();
});
it("reuses the same confirmation and idempotency key after an unknown acknowledgement", async () => {
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  const create = vi
    .spyOn(knowledgeSpaceApi, "createProcessingJob")
    .mockRejectedValueOnce(new Error("Lost acknowledgement"))
    .mockResolvedValue({
      job_id: "job",
      accepted: true,
      state: "accepted",
      reused: true,
    });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "createMetadata" }),
  );
  fireEvent.change(await screen.findByPlaceholderText("pleaseEnter"), {
    target: { value: "category" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await screen.findByText("Lost acknowledgement");
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await screen.findByText("updating-metadata");
  expect(precheck).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledTimes(2);
  expect(create.mock.calls[0]).toEqual(create.mock.calls[1]);
});
it("does not mutate reserved names or accept a stale result after unmount", async () => {
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing");
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob");
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "createMetadata" }),
  );
  const input = await screen.findByPlaceholderText("pleaseEnter");
  fireEvent.change(input, { target: { value: "document_id" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await screen.findByText("builtInNameError");
  expect(precheck).not.toHaveBeenCalled();
  let resolve!: (value: typeof plan) => void;
  precheck.mockReturnValue(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  fireEvent.change(screen.getByPlaceholderText("pleaseEnter"), {
    target: { value: "category" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(precheck).toHaveBeenCalled());
  view.unmount();
  resolve(plan);
  await new Promise((yes) => setTimeout(yes, 0));
  expect(create).not.toHaveBeenCalled();
});

it("edits a field name in the metadata dialog and submits only on save", async () => {
  mocks.read.mockResolvedValue({
    revision: 5,
    fields: [{ field_name: "category", field_type: "string" }],
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  const create = vi
    .spyOn(knowledgeSpaceApi, "createProcessingJob")
    .mockImplementation(async () => {
      mocks.read.mockResolvedValue({
        revision: 6,
        fields: [{ field_name: "topic", field_type: "string" }],
      });
      return {
        job_id: "job",
        accepted: true,
        state: "accepted",
        reused: false,
      };
    });
  mount();
  const dialog = screen.getByRole("dialog", { name: "metaData" });
  fireEvent.click(await within(dialog).findByRole("button", { name: "rename" }));
  const form = within(dialog).getByRole("form", { name: "rename" });
  const name = within(form).getByRole("textbox", { name: "metadatainfor.name" });
  expect(name).toHaveValue("category");
  expect(screen.getByRole("dialog", { name: "metaData" })).toBe(dialog);
  expect(screen.getAllByRole("dialog", { hidden: true })).toEqual([dialog]);
  expect(within(dialog).getByText("document_id")).toBeVisible();
  expect(
    within(dialog).getByText("category").compareDocumentPosition(form) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  await waitFor(() => expect(name).toHaveFocus());

  fireEvent.change(name, { target: { value: "discarded_topic" } });
  fireEvent.keyDown(name, { key: "Escape" });
  expect(within(dialog).getByRole("button", { name: "confirm" })).toBeVisible();
  expect(screen.getByRole("dialog", { name: "metaData" })).toBe(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "cancel" }));

  const continued = within(dialog).getByRole("form", { name: "rename" });
  expect(within(continued).getByRole("textbox")).toHaveValue("discarded_topic");
  fireEvent.click(within(continued).getByRole("button", { name: "cancel" }));
  expect(within(dialog).queryByRole("textbox")).toBeNull();
  expect(within(dialog).getByText("category")).toBeVisible();
  expect(precheck).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole("button", { name: "rename" }));
  const reopenedName = within(dialog).getByRole("textbox");
  expect(reopenedName).toHaveValue("category");
  fireEvent.change(reopenedName, {
    target: { value: "topic" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(7, {
      kind: "metadata_schema_change",
      parameters: {
        expected_schema_revision: 5,
        changes: [
          {
            operation: "rename",
            field_name: "category",
            new_field_name: "topic",
          },
        ],
      },
    }),
  );
  expect(await within(dialog).findByText("topic")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "metaData" })).toBe(dialog);
  expect(within(dialog).queryByRole("textbox")).toBeNull();
  expect(within(dialog).queryByText("category")).toBeNull();
  expect(create).toHaveBeenCalledOnce();
});
it("requires the existing delete confirmation and then submits the correct field", async () => {
  mocks.read.mockResolvedValue({
    revision: 5,
    fields: [{ field_name: "category", field_type: "string" }],
  });
  const precheck = vi
    .spyOn(knowledgeSpaceApi, "precheckProcessing")
    .mockResolvedValue(plan);
  vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockResolvedValue({
    job_id: "job",
    accepted: true,
    state: "accepted",
    reused: false,
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "delete" }));
  await screen.findByText("confirmDeleteMetadata");
  expect(precheck).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() =>
    expect(precheck).toHaveBeenCalledWith(7, {
      kind: "metadata_schema_change",
      parameters: {
        expected_schema_revision: 5,
        changes: [{ operation: "delete", field_name: "category" }],
      },
    }),
  );
});
