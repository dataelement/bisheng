import request from "~/api/request";
import * as api from "./knowledgeProcessing";
import type {
  JobAccepted,
  KnowledgeSpaceRead,
  OperationPrecheck,
  ProcessingDefaults,
  ProcessingIdentityScope,
  ProcessingJobRead,
  ProcessingPrecheckRequest,
} from "./knowledgeProcessing";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    paramsSerializer: jest.fn(),
  },
}));

const transport = request as jest.Mocked<typeof request>;
const envelope = <T,>(data: T) => ({ status_code: 200, status_message: "SUCCESS", data });
const scope: ProcessingIdentityScope = { userId: "7", tenantId: "101", view: "ordinary" };
const defaults: ProcessingDefaults = {
  schema_version: 1,
  document: {
    split_mode: "hierarchical", separator: ["\n"], separator_rule: ["after"], chunk_size: 500,
    chunk_overlap: 20, hierarchy_level: 2, append_title: true, max_chunk_size: 1000,
    retain_images: 1, force_ocr: 0, enable_formula: 1, filter_page_header_footer: 1,
  },
  table: { slice_length: 200, header_start_row: 1, header_end_row: 2, append_header: 1 },
};
const precheck: OperationPrecheck = {
  confirmation_id: "confirmation-a", plan_digest: "a".repeat(64), expires_at: "2026-11-06T12:00:00Z",
  check_complete: true, can_execute: true, valid_items: [{ id: 10, type: "file", name: "visible.pdf" }],
  invalid_items: [{ id: null, type: null, name: null, reason: "not_visible", error_code: 10995 }],
  impact: { opaque_future_impact: { count: 2 } }, requires_skip_confirmation: true,
};
const job: ProcessingJobRead = {
  id: "job-a", space_id: 3, kind: "move_index", state: "partial_failed", revision: 4,
  accepted_at: "2026-11-06T10:00:00Z", started_at: "2026-11-06T10:01:00Z", finished_at: null,
  total_count: 3, succeeded_count: 1, failed_count: 1, pending_count: 1, hidden_item_count: 1,
  retryable: true, obsolete_reason: null, error_code: null,
};

beforeEach(() => jest.clearAllMocks());

it("keeps existing space info and cursor children on their original routes", async () => {
  const info = { id: 3, name: "Space", actions: ["visible"], type: 3 };
  const children = { data: [{ id: 10, name: "visible.pdf", type: "file" }], page_size: 40, has_more: true, next_cursor: "cursor-a" };
  transport.get.mockResolvedValueOnce(envelope(info)).mockResolvedValueOnce(envelope(children));
  expect(await api.getSpaceInfo(3)).toBe(info);
  const query = { parent_id: 2, file_ids: [10], file_status: [2], file_type: 1 as const, cursor: "cursor-old", page_size: 40, order_field: "file_name" as const, order_sort: "desc" as const };
  expect(await api.listChildren(3, query)).toBe(children);
  expect(transport.get).toHaveBeenNthCalledWith(1, "/api/v1/knowledge/space/3/info");
  expect(transport.get).toHaveBeenNthCalledWith(2, "/api/v1/knowledge/space/3/children", { params: query, paramsSerializer: request.paramsSerializer });
  expect(children).not.toHaveProperty("total");
});

it("preserves approval-required access in the existing space info response", async () => {
  const info: KnowledgeSpaceRead = {
    id: 3, name: "Approval space", type: 3, auth_type: "approval", actions: ["visible"],
  };
  transport.get.mockResolvedValueOnce(envelope(info));
  const received = await api.getSpaceInfo(3);
  expect(received).toBe(info);
  expect(received.auth_type).toBe("approval");
  expect(transport.get).toHaveBeenCalledWith("/api/v1/knowledge/space/3/info");
});

it("keeps admin PageData separate from cursor pagination without adding a UI entry", async () => {
  const page = { data: [{ id: 3, name: "Space", actions: ["visible"] }], total: 1 };
  const params = { keyword: "space", page: 2, page_size: 20 };
  transport.get.mockResolvedValueOnce(envelope(page));
  expect(await api.listAdminSpaces(params)).toBe(page);
  expect(transport.get).toHaveBeenCalledWith("/api/v1/knowledge/space/admin/list", { params });
});

it("preserves nullable saved settings and complete resolved document/table defaults", async () => {
  const read = { space_id: 3, config_version: 4, saved_defaults: null, effective_defaults: defaults };
  transport.get.mockResolvedValueOnce(envelope(read));
  transport.put.mockResolvedValueOnce(envelope({ ...read, config_version: 5, saved_defaults: defaults }));
  expect(await api.getProcessingSettings(3)).toBe(read);
  const write = { expected_config_version: 4, defaults };
  const updated = await api.updateProcessingSettings(3, write);
  expect(updated.config_version).toBe(5);
  expect(transport.get).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-settings");
  expect(transport.put).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-settings", write);
});

const commands: ProcessingPrecheckRequest[] = [
  { kind: "embedding_rebuild", parameters: { embedding_model_id: 5 } },
  { kind: "file_reprocess", targets: [{ file_id: 10, version_id: 12 }], parameters: { overrides: { document: { force_ocr: 1 } } } },
  { kind: "file_resplit", targets: [{ file_id: 10, document_id: 11, version_id: 12 }], parameters: { overrides: { table: { append_header: 0 } } } },
  { kind: "metadata_schema_change", parameters: { expected_schema_revision: 2, changes: [{ operation: "rename", field_name: "old_name", new_field_name: "new_name" }] } },
];

it.each(commands)("passes the frozen $kind parameters and opaque impact without deriving an execution", async (command) => {
  transport.post.mockResolvedValueOnce(envelope(precheck));
  expect(await api.precheckProcessing(3, command)).toBe(precheck);
  expect(transport.post).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-jobs/precheck", command);
  expect(precheck.invalid_items[0]).toEqual({ id: null, type: null, name: null, reason: "not_visible", error_code: 10995 });
  expect(transport.post).toHaveBeenCalledTimes(1);
});

it.each<JobAccepted["state"]>(["accepted", "running", "succeeded", "partial_failed", "failed", "obsolete"])(
  "does not turn accepted:true with persisted %s into successful completion",
  async (state) => {
    const accepted: JobAccepted = { job_id: "job-a", accepted: true, state, reused: true };
    const command = { idempotency_key: "same-command", confirmation_id: precheck.confirmation_id, plan_digest: precheck.plan_digest };
    transport.post.mockResolvedValueOnce(envelope(accepted));
    expect(await api.createProcessingJob(3, command)).toBe(accepted);
    expect(transport.post).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-jobs", command);
    expect(Object.keys(command).sort()).toEqual(["confirmation_id", "idempotency_key", "plan_digest"]);
  },
);

it("keeps filtered job/item pagination, revisions and hidden item redaction", async () => {
  const jobs = { data: [job], total: 1 };
  const item = { id: "item-a", file_id: null, document_id: null, version_id: null, step: "parse", state: "failed", attempt: 2, error_code: 10996, message: null, retryable: true };
  const items = { data: [item], total: 1 };
  const jobQuery = { page: 2, page_size: 20, kind: "move_index" as const, state: "partial_failed" as const };
  const itemQuery = { page: 1, page_size: 20, state: "failed" as const };
  transport.get.mockResolvedValueOnce(envelope(jobs)).mockResolvedValueOnce(envelope(job)).mockResolvedValueOnce(envelope(items));
  expect(await api.listProcessingJobs(3, jobQuery)).toBe(jobs);
  expect(await api.getProcessingJob(3, "job-a")).toBe(job);
  expect(await api.listProcessingItems(3, "job-a", itemQuery)).toBe(items);
  expect(transport.get).toHaveBeenNthCalledWith(1, "/api/v1/knowledge/space/3/processing-jobs", { params: jobQuery });
  expect(transport.get).toHaveBeenNthCalledWith(2, "/api/v1/knowledge/space/3/processing-jobs/job-a");
  expect(transport.get).toHaveBeenNthCalledWith(3, "/api/v1/knowledge/space/3/processing-jobs/job-a/items", { params: itemQuery });
  expect(item).not.toHaveProperty("name");
  expect(job.hidden_item_count).toBe(1);
});

it("retries the original job with only its revision and idempotency key", async () => {
  const command = { idempotency_key: "retry-a", expected_job_revision: 4 };
  const accepted: JobAccepted = { job_id: "job-a", accepted: true, state: "running", reused: true };
  transport.post.mockResolvedValueOnce(envelope(accepted));
  expect(await api.retryProcessingJob(3, "job-a", command)).toBe(accepted);
  expect(transport.post).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-jobs/job-a/retry", command);
});

it("preserves status_code, status_message and data when a business envelope fails", async () => {
  const error = { status_code: 18087, status_message: "Plan changed", data: { reason: "reference_changed", confirmation_id: null } };
  transport.post.mockResolvedValueOnce(error);
  await expect(api.createProcessingJob(3, { idempotency_key: "create-a", confirmation_id: "old-plan", plan_digest: "a".repeat(64) })).rejects.toMatchObject(error);
  expect(transport.post).toHaveBeenCalledTimes(1);
});

it("propagates a rejected request unchanged instead of returning an empty page", async () => {
  const failure = { status_code: 10994, status_message: "Coverage unavailable", data: { reason: "not_ready" } };
  transport.get.mockRejectedValueOnce(failure);
  await expect(api.listProcessingJobs(3, { page: 1, page_size: 20 })).rejects.toBe(failure);
});

it("isolates identity, tenant, ordinary/admin view, job and query filters", () => {
  const current = api.knowledgeProcessingKeys.jobs(scope, 3, { page: 1, page_size: 20 });
  for (const other of [{ ...scope, userId: "8" }, { ...scope, tenantId: "202" }, { ...scope, view: "admin" as const }]) {
    expect(api.knowledgeProcessingKeys.jobs(other, 3, { page: 1, page_size: 20 })).not.toEqual(current);
  }
  expect(api.knowledgeProcessingKeys.jobs(scope, 4, { page: 1, page_size: 20 })).not.toEqual(current);
  expect(api.knowledgeProcessingKeys.jobs(scope, 3, { page: 2, page_size: 20 })).not.toEqual(current);
  expect(api.knowledgeProcessingKeys.items(scope, 3, "job-a", { page: 1, page_size: 20 })).not.toEqual(api.knowledgeProcessingKeys.items(scope, 3, "job-b", { page: 1, page_size: 20 }));
  expect(api.knowledgeProcessingKeys.children(scope, 3, { file_ids: [10], cursor: "one" })).not.toEqual(api.knowledgeProcessingKeys.children(scope, 3, { file_ids: [11], cursor: "one" }));
});

it("captures a copy of the issuing scope so later mutations cannot reuse its plan in another scope", () => {
  const mutable: ProcessingIdentityScope = { ...scope };
  const captured = api.captureProcessingScope(mutable);
  const key = api.knowledgeProcessingKeys.settings(mutable, 3);
  mutable.tenantId = "202";
  expect(captured.tenantId).toBe("101");
  expect(Object.isFrozen(captured)).toBe(true);
  expect(api.isProcessingScopeCurrent(captured, mutable)).toBe(false);
  expect(api.isProcessingScopeCurrent(captured, { ...scope })).toBe(true);
  expect(key).toEqual(api.knowledgeProcessingKeys.settings(scope, 3));
});
