import * as api from "@/controllers/API/knowledgeSpace";
import type {
  DocumentProcessingRule,
  KnowledgeSpaceCreateRequest,
  SpaceCreationSettings,
  JobAccepted,
  OperationPrecheck,
  ProcessingPrecheckRequest,
  ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({ default: request }));

const document: DocumentProcessingRule = {
  split_mode: "hierarchical",
  separator: ["\n\n", "。"],
  separator_rule: ["before", "after"],
  chunk_size: 1200,
  chunk_overlap: 120,
  hierarchy_level: 6,
  append_title: true,
  max_chunk_size: 2400,
  retain_images: 1,
  force_ocr: 0,
  enable_formula: 1,
  filter_page_header_footer: 0,
};
const settings: ProcessingSettingsRead = {
  space_id: 7,
  config_version: 0,
  saved_defaults: null,
  effective_defaults: {
    schema_version: 1,
    document,
    table: {
      slice_length: 10,
      header_start_row: 1,
      header_end_row: 2,
      append_header: 1,
    },
  },
};
const precheck: OperationPrecheck = {
  confirmation_id: "confirmation-1",
  plan_digest: "a".repeat(64),
  expires_at: "2026-11-06T12:00:00Z",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 7, type: "space", name: "Visible space" }],
  invalid_items: [{ reason: "permission_denied", error_code: 19000 }],
  impact: { owner_defined: { opaque: ["must remain unchanged"] } },
  requires_skip_confirmation: true,
};
const accepted: JobAccepted = {
  job_id: "job-1",
  accepted: true,
  state: "partial_failed",
  reused: true,
};

beforeEach(() => vi.resetAllMocks());

describe("ordinary spaces and creation wire contract", () => {
  it("keeps the ordinary cursor page opaque, including an empty progressing page", async () => {
    const page = { data: [], page_size: 20, has_more: true, next_cursor: "opaque/+==" };
    request.get.mockResolvedValue(page);
    const query = { keyword: "Space", page_size: 20, cursor: "before/+==" };
    expect(await api.listVisibleSpaces(query)).toBe(page);
    expect(request.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", { params: query });
    await api.listVisibleSpaces();
    expect(request.get).toHaveBeenLastCalledWith("/api/v1/knowledge/space/list", { params: {} });
    expect(page).not.toHaveProperty("total");
  });

  it.each([null, { id: "retired-nonnumeric-id", name: "Original model" }])(
    "reads the closed creation settings without replacing the original default %j", async (embedding_model) => {
      const bootstrap: SpaceCreationSettings = { embedding_model, system_defaults: settings.effective_defaults };
      request.get.mockResolvedValue(bootstrap);
      expect(await api.getCreationSettings()).toBe(bootstrap);
      expect(request.get).toHaveBeenCalledExactlyOnceWith("/api/v1/knowledge/space/creation-settings");
      expect(request.post).not.toHaveBeenCalled();
    },
  );

  const body: KnowledgeSpaceCreateRequest = {
    name: "Created space", description: null, icon: null, auth_type: "approval", is_released: false,
    auto_tag_enabled: true, auto_tag_library_id: null, auto_tag_custom_tags: ["tag"],
    creation_request_id: "same-request", initial_permissions: {
      expected_catalog_release_id: 9,
      grants: [{ model_key: "viewer", subject: { type: "user", id: "7", include_children: false } }],
    },
    embedding_model_id: 19, processing_defaults: settings.effective_defaults,
  };
  it.each([
    body, { name: "Model only", embedding_model_id: 19 },
    { name: "Rules only", processing_defaults: settings.effective_defaults },
  ])("pins only advanced creation to its captured management tenant", async (requestBody) => {
    const response = { id: 8, name: requestBody.name, type: 3, model: "19", initial_permission_result: {
      status: "failed" as const, resource_version: null, assignee_ids: [], error_code: 19000, message: null,
    } };
    request.post.mockResolvedValue(response);
    expect(await api.createSpace(requestBody, 101)).toBe(response);
    expect(request.post).toHaveBeenCalledExactlyOnceWith("/api/v1/knowledge/space", requestBody, {
      headers: { "X-Management-Tenant": "101" },
    });
    expect(response).not.toHaveProperty("file_num");
    expect(response).not.toHaveProperty("actions");
  });

  it.each([null, 0, -1, 1.5, Number.NaN])("rejects an advanced command without a concrete captured pin %s", async (pin) => {
    await expect(api.createSpace(body, pin)).rejects.toMatchObject({ code: "knowledge_management_tenant_required" });
    expect(request.post).not.toHaveBeenCalled();
  });

  it.each([null, 101])("keeps simplified creation free of management write headers with pin %s", async (pin) => {
    const simple = { name: "Simple", embedding_model_id: null, processing_defaults: null };
    request.post.mockResolvedValue({ id: 9, name: "Simple" });
    await api.createSpace(simple, pin);
    expect(request.post).toHaveBeenCalledExactlyOnceWith("/api/v1/knowledge/space", simple);
  });

  it.each(["list", "bootstrap", "create"])("preserves the original ApiError for %s", async (operation) => {
    const error = { status_code: 10998, status_message: "original", data: { reason: "scope" } };
    request.get.mockRejectedValue(error);
    request.post.mockRejectedValue(error);
    const action = operation === "list" ? api.listVisibleSpaces() : operation === "bootstrap"
      ? api.getCreationSettings() : api.createSpace(body, 101);
    await expect(action).rejects.toBe(error);
  });
});

describe("A1 processing API wire contract", () => {
  it("reads info and existing cursor children without inventing a total", async () => {
    const info = { id: 7, name: "Space", actions: ["visible"] };
    const page = {
      data: [{ id: 8, knowledge_id: 7, file_name: "Folder", file_type: 0 }],
      page_size: 40,
      has_more: true,
      next_cursor: "opaque",
    };
    request.get.mockResolvedValueOnce(info).mockResolvedValueOnce(page);
    const query = {
      parent_id: 3,
      file_ids: [8],
      order_field: "file_type" as const,
      order_sort: "asc" as const,
      file_status: [2],
      page_size: 40,
      cursor: "before",
      file_type: 0 as const,
    };
    expect(await api.getSpaceInfo(7)).toBe(info);
    expect(await api.listChildren(7, query)).toBe(page);
    expect(request.get.mock.calls).toEqual([
      ["/api/v1/knowledge/space/7/info"],
      ["/api/v1/knowledge/space/7/children", { params: query }],
    ]);
    expect(page).not.toHaveProperty("total");
  });

  it("uses the distinct paginated admin list without a client-selected tenant", async () => {
    const page = { data: [{ id: 7, name: "Space" }], total: 1 };
    request.get.mockResolvedValue(page);
    const query = { keyword: "Space", page: 2, page_size: 20 };
    expect(await api.listAdminSpaces(query)).toBe(page);
    expect(request.get).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/admin/list",
      { params: query },
    );
    expect(page).not.toHaveProperty("has_more");
  });

  it("retains both settings rules, null saved defaults and compare-and-swap version", async () => {
    request.get.mockResolvedValue(settings);
    request.put.mockResolvedValue({ ...settings, config_version: 1 });
    expect(await api.getProcessingSettings(7)).toBe(settings);
    const write = {
      expected_config_version: 0,
      defaults: settings.effective_defaults,
    };
    expect(await api.updateProcessingSettings(7, write)).toEqual({
      ...settings,
      config_version: 1,
    });
    expect(request.get).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-settings",
    );
    expect(request.put).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-settings",
      write,
    );
    expect(JSON.parse(JSON.stringify(write))).toEqual(write);
    expect(write.defaults.document.force_ocr).toBe(0);
    expect(write.defaults.document.append_title).toBe(true);
  });

  const prechecks: ProcessingPrecheckRequest[] = [
    { kind: "embedding_rebuild", parameters: { embedding_model_id: 19 } },
    {
      kind: "file_reprocess",
      targets: [{ file_id: 8, version_id: 9 }],
      parameters: {
        overrides: { document: { force_ocr: 1, chunk_overlap: null } },
      },
    },
    {
      kind: "file_resplit",
      targets: [{ file_id: 8, document_id: 10, version_id: 9 }],
      parameters: { overrides: { table: { slice_length: 4 } } },
    },
    {
      kind: "metadata_schema_change",
      parameters: {
        expected_schema_revision: 3,
        changes: [
          { operation: "add", field_name: "rating", field_type: "number" },
          { operation: "rename", field_name: "old", new_field_name: "new" },
          { operation: "delete", field_name: "removed" },
        ],
      },
    },
  ];
  it.each(prechecks)(
    "serializes $kind and leaves owner-defined impact opaque",
    async (body) => {
      request.post.mockResolvedValue(precheck);
      expect(await api.precheckProcessing(7, body)).toBe(precheck);
      expect(request.post).toHaveBeenCalledWith(
        "/api/v1/knowledge/space/7/processing-jobs/precheck",
        body,
      );
      expect(JSON.parse(JSON.stringify(body))).toEqual(body);
      expect(precheck.invalid_items[0]).not.toHaveProperty("id");
      expect(precheck.invalid_items[0]).not.toHaveProperty("name");
    },
  );

  it("creates with only the frozen plan and preserves reused non-accepted job state", async () => {
    const body = {
      idempotency_key: "create-1",
      confirmation_id: precheck.confirmation_id,
      plan_digest: precheck.plan_digest,
    };
    request.post.mockResolvedValue(accepted);
    expect(await api.createProcessingJob(7, body)).toBe(accepted);
    expect(request.post).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-jobs",
      body,
    );
    expect(request.post.mock.calls[0][1]).not.toHaveProperty("targets");
    expect(accepted.state).toBe("partial_failed");
  });

  it("keeps job/item pages, nullable hidden identities and retry revision unchanged", async () => {
    const job = {
      id: "job-1",
      space_id: 7,
      kind: "file_resplit",
      state: "partial_failed",
      revision: 4,
      accepted_at: "2026-11-06T10:00:00Z",
      started_at: null,
      finished_at: null,
      total_count: 3,
      succeeded_count: 1,
      failed_count: 1,
      pending_count: 1,
      hidden_item_count: 1,
      retryable: true,
      obsolete_reason: null,
      error_code: null,
    };
    const jobs = { data: [job], total: 1 };
    const items = {
      data: [
        {
          id: "item-1",
          file_id: null,
          document_id: null,
          version_id: null,
          step: "index",
          state: "failed",
          attempt: 1,
          error_code: 10999,
          message: null,
          retryable: true,
        },
      ],
      total: 1,
    };
    const jobQuery = {
      page: 1,
      page_size: 20,
      kind: "file_resplit" as const,
      state: "partial_failed" as const,
    };
    const itemQuery = { page: 2, page_size: 10, state: "failed" as const };
    request.get
      .mockResolvedValueOnce(jobs)
      .mockResolvedValueOnce(job)
      .mockResolvedValueOnce(items);
    request.post.mockResolvedValue(accepted);
    expect(await api.listProcessingJobs(7, jobQuery)).toBe(jobs);
    expect(await api.getProcessingJob(7, "job-1")).toBe(job);
    expect(await api.listProcessingItems(7, "job-1", itemQuery)).toBe(items);
    const retry = { idempotency_key: "retry-1", expected_job_revision: 4 };
    expect(await api.retryProcessingJob(7, "job-1", retry)).toBe(accepted);
    expect(request.get.mock.calls).toEqual([
      ["/api/v1/knowledge/space/7/processing-jobs", { params: jobQuery }],
      ["/api/v1/knowledge/space/7/processing-jobs/job-1"],
      [
        "/api/v1/knowledge/space/7/processing-jobs/job-1/items",
        { params: itemQuery },
      ],
    ]);
    expect(request.post).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-jobs/job-1/retry",
      retry,
    );
  });

  it("rejects with the original business envelope instead of returning empty data", async () => {
    const error = {
      status_code: 10998,
      status_message: "plan conflict",
      data: { reason: "reference_confirmation_changed_or_expired" },
    };
    request.post.mockRejectedValue(error);
    await expect(
      api.createProcessingJob(7, {
        idempotency_key: "x",
        confirmation_id: "plan",
        plan_digest: "b".repeat(64),
      }),
    ).rejects.toBe(error);
  });

  it("keeps existing managed and selectable helper paths compatible", async () => {
    request.get.mockResolvedValueOnce([{ id: 1, name: "managed" }]);
    expect(
      await api.getManagedKnowledgeSpacesApi({ order_by: "name" }),
    ).toEqual([{ id: 1, name: "managed" }]);
    request.get
      .mockResolvedValueOnce([{ id: 1, name: "first" }])
      .mockResolvedValueOnce([{ id: 1, name: "second" }])
      .mockResolvedValueOnce([{ id: 2, name: "department" }]);
    expect(await api.getSelectableKnowledgeSpacesApi()).toEqual([
      { id: 1, name: "first" },
      { id: 2, name: "department" },
    ]);
  });
});
