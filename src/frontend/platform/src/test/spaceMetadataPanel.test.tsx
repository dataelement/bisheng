import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceMetadataPanel } from "@/pages/KnowledgePage/components/SpaceMetadataPanel";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
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
  SpaceProcessingProgress: () => <p>updating-metadata</p>,
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
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <SpaceMetadataPanel scope={scope} spaceId={7} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  mocks.read.mockResolvedValue({ revision: 5, fields: [] });
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
});
it("performs the existing native checks and confirmation internally on create", async () => {
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
  mount();
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

it("renames an existing field through the restored row action", async () => {
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
  fireEvent.click(await screen.findByRole("button", { name: "rename" }));
  fireEvent.change(await screen.findByDisplayValue("category"), {
    target: { value: "topic" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
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
