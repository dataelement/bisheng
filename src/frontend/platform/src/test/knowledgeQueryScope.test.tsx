import {
  knowledgeQueryKeys,
  useCreateKnowledgeSpace,
  useKnowledgeCreationSettings,
  useKnowledgeVisibleSpaces,
  useKnowledgeAdminSpaces,
  useKnowledgeProcessingActions,
  useKnowledgeProcessingItems,
  useKnowledgeProcessingJobs,
  useKnowledgeProcessingSettings,
  useKnowledgeSpaceChildren,
  useKnowledgeSpaceInfo,
  useKnowledgeDetails,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import type {
  KnowledgeSpaceApi,
  OperationPrecheck,
  ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const legacy = vi.hoisted(() => ({ detail: vi.fn() }));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: legacy.detail }));

const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const settings: ProcessingSettingsRead = {
  space_id: 7,
  config_version: 0,
  saved_defaults: null,
  effective_defaults: {
    schema_version: 1,
    document: {
      split_mode: "auto",
      separator: ["\n"],
      separator_rule: ["after"],
      chunk_size: 1000,
      chunk_overlap: 0,
      hierarchy_level: 3,
      append_title: false,
      max_chunk_size: 2000,
      retain_images: 1,
      force_ocr: 1,
      enable_formula: 0,
      filter_page_header_footer: 0,
    },
    table: {
      slice_length: 10,
      header_start_row: 1,
      header_end_row: 1,
      append_header: 1,
    },
  },
};
const plan: OperationPrecheck = {
  confirmation_id: "plan-1",
  plan_digest: "a".repeat(64),
  expires_at: "2026-11-06T12:00:00Z",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 7, type: "space" }],
  invalid_items: [],
  impact: {},
  requires_skip_confirmation: false,
};

function apiPort() {
  return {
    listVisibleSpaces: vi.fn().mockResolvedValue({ data: [], page_size: 20, has_more: false, next_cursor: null }),
    getCreationSettings: vi.fn().mockResolvedValue({ embedding_model: null, system_defaults: settings.effective_defaults }),
    createSpace: vi.fn().mockResolvedValue({ id: 8, name: "Created" }),
    getSpaceInfo: vi.fn().mockResolvedValue({ id: 7, name: "Space" }),
    updateSpaceBasicInfo: vi.fn().mockResolvedValue({ id: 7, name: "Changed" }),
    listChildren: vi.fn().mockResolvedValue({
      data: [],
      page_size: 40,
      has_more: false,
      next_cursor: null,
    }),
    listAdminSpaces: vi.fn().mockResolvedValue({ data: [], total: 0 }),
    getProcessingSettings: vi.fn().mockResolvedValue(settings),
    updateProcessingSettings: vi
      .fn()
      .mockResolvedValue({ ...settings, config_version: 1 }),
    precheckProcessing: vi.fn().mockResolvedValue(plan),
    createProcessingJob: vi.fn().mockResolvedValue({
      job_id: "job-1",
      accepted: true,
      state: "running",
      reused: true,
    }),
    listProcessingJobs: vi.fn().mockResolvedValue({ data: [], total: 0 }),
    getProcessingJob: vi.fn(),
    listProcessingItems: vi.fn().mockResolvedValue({ data: [], total: 0 }),
    retryProcessingJob: vi.fn().mockResolvedValue({
      job_id: "job-1",
      accepted: true,
      state: "partial_failed",
      reused: true,
    }),
  } satisfies KnowledgeSpaceApi;
}

const clients: QueryClient[] = [];
function queryHost() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.clearAllMocks();
});

describe("knowledge query scope", () => {
  it("continues from an empty visible page using the opaque server cursor", async () => {
    const api = apiPort();
    api.listVisibleSpaces.mockResolvedValueOnce({ data: [], page_size: 20, has_more: true, next_cursor: "opaque/+==" });
    const query = { keyword: "same", page_size: 20 };
    const { result } = renderHook(() => useKnowledgeVisibleSpaces(scope, query, api), queryHost());
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => { await result.current.fetchNextPage(); });
    expect(api.listVisibleSpaces.mock.calls).toEqual([[query], [{ ...query, cursor: "opaque/+==" }]]);
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(result.current.data?.pages).toHaveLength(2);
    expect(knowledgeQueryKeys.visible(scope, query)).not.toEqual(knowledgeQueryKeys.visible(scope, { ...query, keyword: "other" }));
  });

  it("does not fetch ordinary pages from the admin view", () => {
    const api = apiPort();
    renderHook(() => useKnowledgeVisibleSpaces({ ...scope, view: "admin" }, {}, api), queryHost());
    expect(api.listVisibleSpaces).not.toHaveBeenCalled();
  });

  it("does not expose a previous scope's late creation settings", async () => {
    const first = deferred<Awaited<ReturnType<KnowledgeSpaceApi["getCreationSettings"]>>>();
    const api = apiPort();
    api.getCreationSettings.mockReturnValueOnce(first.promise);
    const host = queryHost();
    const { result, rerender } = renderHook(({ value }) => useKnowledgeCreationSettings(value, api), { ...host, initialProps: { value: scope } });
    await waitFor(() => expect(api.getCreationSettings).toHaveBeenCalledTimes(1));
    rerender({ value: { ...scope, managementTenantId: 202 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await act(async () => first.resolve({ embedding_model: { id: "old", name: "Old" }, system_defaults: settings.effective_defaults }));
    expect(result.current.data?.embedding_model).toBeNull();
    expect(host.client.getQueriesData({ queryKey: knowledgeQueryKeys.scope(scope) })).toEqual([]);
  });

  it("preserves bootstrap ApiError and never substitutes fabricated defaults", async () => {
    const api = apiPort();
    const error = { status_code: 19000, data: { reason: "creation" } };
    api.getCreationSettings.mockRejectedValue(error);
    const { result } = renderHook(() => useKnowledgeCreationSettings(scope, api), queryHost());
    await waitFor(() => expect(result.current.error).toBe(error));
    expect(result.current.data).toBeUndefined();
  });

  it("retains equal scope values and invalidates only issuing lists after creation", async () => {
    const api = apiPort(), host = queryHost();
    const other = { ...scope, managementTenantId: 202 };
    const keys = [knowledgeQueryKeys.visible(scope, { keyword: "x" }), knowledgeQueryKeys.admin(scope, { page: 1, page_size: 20 }), knowledgeQueryKeys.visible(other, {})];
    keys.forEach(key => host.client.setQueryData(key, { data: [] }));
    const detail = knowledgeQueryKeys.info(scope, 7);
    host.client.setQueryData(detail, { id: 7 });
    const { result, rerender } = renderHook(({ value }) => useCreateKnowledgeSpace(value, api), { ...host, initialProps: { value: scope } });
    const original = result.current;
    rerender({ value: { ...scope } });
    expect(await original.createSpace({ name: "Created", embedding_model_id: 19 })).toEqual({ id: 8, name: "Created" });
    expect(api.createSpace).toHaveBeenCalledWith({ name: "Created", embedding_model_id: 19 }, 101);
    expect(keys.map(key => host.client.getQueryState(key)?.isInvalidated)).toEqual([true, true, false]);
    expect(host.client.getQueryState(detail)?.isInvalidated).toBe(false);
  });

  it.each([
    { ...scope, identityKey: "user:8" }, { ...scope, tenantId: 202 },
    { ...scope, managementTenantId: 202 }, { ...scope, view: "admin" as const },
  ])("rejects a stale creation result without enabling navigation or touching new lists: %j", async (nextScope) => {
    const api = apiPort(), host = queryHost(), response = deferred<{ id: number; name: string }>();
    api.createSpace.mockReturnValueOnce(response.promise);
    const nextKey = knowledgeQueryKeys.visible(nextScope, {});
    host.client.setQueryData(nextKey, { data: [] });
    const navigate = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useCreateKnowledgeSpace(value, api), { ...host, initialProps: { value: scope } });
    const old = result.current;
    const pending = old.createSpace({ name: "Late" }).then(navigate);
    const rejected = expect(pending).rejects.toMatchObject({ code: "knowledge_scope_changed" });
    rerender({ value: nextScope });
    await act(async () => response.resolve({ id: 8, name: "Late" }));
    await rejected;
    expect(navigate).not.toHaveBeenCalled();
    expect(host.client.getQueryState(nextKey)?.isInvalidated).toBe(false);
    rerender({ value: scope });
    await expect(old.createSpace({ name: "Old handler" })).rejects.toMatchObject({ code: "knowledge_scope_changed" });
    expect(api.createSpace).toHaveBeenCalledTimes(1);
  });

  it("preserves creation errors and performs no list invalidation on failure", async () => {
    const api = apiPort(), host = queryHost();
    const error = { status_code: 18001, data: null }, key = knowledgeQueryKeys.visible(scope, {});
    host.client.setQueryData(key, { data: [] });
    api.createSpace.mockRejectedValue(error);
    const { result } = renderHook(() => useCreateKnowledgeSpace(scope, api), host);
    await expect(result.current.createSpace({ name: "Failed" })).rejects.toBe(error);
    expect(host.client.getQueryState(key)?.isInvalidated).toBe(false);
  });
  it("separates identity, current tenant, management tenant, view and request filters", () => {
    const scopes = [
      scope,
      { ...scope, identityKey: "user:8" },
      { ...scope, tenantId: 202 },
      { ...scope, managementTenantId: 202 },
      { ...scope, view: "admin" as const },
    ];
    const keys = scopes.map((value) => knowledgeQueryKeys.settings(value, 7));
    expect(new Set(keys.map((key) => JSON.stringify(key))).size).toBe(
      scopes.length,
    );
    expect(knowledgeQueryKeys.settings(scope, 7)).not.toEqual(
      knowledgeQueryKeys.settings(scope, 8),
    );
    expect(knowledgeQueryKeys.children(scope, 7, { cursor: "a" })).not.toEqual(
      knowledgeQueryKeys.children(scope, 7, { cursor: "b" }),
    );
    expect(
      knowledgeQueryKeys.jobs(scope, 7, { page: 1, page_size: 20 }),
    ).not.toEqual(
      knowledgeQueryKeys.jobs(scope, 7, { page: 2, page_size: 20 }),
    );
    expect(
      knowledgeQueryKeys.items(scope, 7, "job-a", { page: 1, page_size: 20 }),
    ).not.toEqual(
      knowledgeQueryKeys.items(scope, 7, "job-b", { page: 1, page_size: 20 }),
    );
  });

  it("uses the supplied API port for info, cursor children, jobs and items", async () => {
    const api = apiPort();
    const host = queryHost();
    const children = { parent_id: 3, cursor: "cursor-a", page_size: 40 };
    const page = { page: 2, page_size: 20 };
    const { result } = renderHook(
      () => ({
        info: useKnowledgeSpaceInfo(scope, 7, api),
        children: useKnowledgeSpaceChildren(scope, 7, children, api),
        jobs: useKnowledgeProcessingJobs(scope, 7, page, api),
        items: useKnowledgeProcessingItems(scope, 7, "job-1", page, api),
      }),
      host,
    );
    await waitFor(() => expect(result.current.items.isSuccess).toBe(true));
    expect(api.getSpaceInfo).toHaveBeenCalledWith(7);
    expect(api.listChildren).toHaveBeenCalledWith(7, children);
    expect(api.listProcessingJobs).toHaveBeenCalledWith(7, page);
    expect(api.listProcessingItems).toHaveBeenCalledWith(7, "job-1", page);
    expect(result.current.children.data).not.toHaveProperty("total");
    expect(result.current.jobs.data).not.toHaveProperty("next_cursor");
  });

  it("does not request the admin list from the ordinary view", async () => {
    const api = apiPort();
    const host = queryHost();
    const query = { page: 1, page_size: 20 };
    const { result, rerender } = renderHook(
      ({ value }) => useKnowledgeAdminSpaces(value, query, api),
      { ...host, initialProps: { value: scope } },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(api.listAdminSpaces).not.toHaveBeenCalled();
    rerender({ value: { ...scope, view: "admin" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.listAdminSpaces).toHaveBeenCalledWith(query);
  });

  it.each([
    { ...scope, identityKey: "user:8" },
    { ...scope, tenantId: 202 },
    { ...scope, managementTenantId: 202 },
    { ...scope, view: "admin" as const },
  ])(
    "does not reuse a previous scope's cached detail: %j",
    async (nextScope) => {
      const api = apiPort();
      api.getProcessingSettings
        .mockResolvedValueOnce(settings)
        .mockResolvedValueOnce({ ...settings, config_version: 2 });
      const host = queryHost();
      const { result, rerender } = renderHook(
        ({ value }) => useKnowledgeProcessingSettings(value, 7, api),
        { ...host, initialProps: { value: scope } },
      );
      await waitFor(() => expect(result.current.data?.config_version).toBe(0));
      rerender({ value: nextScope });
      await waitFor(() => expect(result.current.data?.config_version).toBe(2));
      expect(api.getProcessingSettings).toHaveBeenCalledTimes(2);
    },
  );

  it("ignores an old scope's late query response and removes its query cache", async () => {
    const first = deferred<ProcessingSettingsRead>();
    const api = apiPort();
    api.getProcessingSettings
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...settings, config_version: 9 });
    const host = queryHost();
    const nextScope = { ...scope, tenantId: 202 };
    const { result, rerender } = renderHook(
      ({ value }) => useKnowledgeProcessingSettings(value, 7, api),
      { ...host, initialProps: { value: scope } },
    );
    await waitFor(() =>
      expect(api.getProcessingSettings).toHaveBeenCalledTimes(1),
    );
    rerender({ value: nextScope });
    await waitFor(() => expect(result.current.data?.config_version).toBe(9));
    await act(async () => first.resolve(settings));
    expect(result.current.data?.config_version).toBe(9);
    expect(
      host.client.getQueryData(knowledgeQueryKeys.settings(nextScope, 7)),
    ).toEqual({ ...settings, config_version: 9 });
    expect(
      host.client.getQueriesData({ queryKey: knowledgeQueryKeys.scope(scope) }),
    ).toEqual([]);
  });

  it("preserves a processing query's original rejection", async () => {
    const error = {
      status_code: 19000,
      status_message: "denied",
      data: { reason: "scope" },
    };
    const api = apiPort();
    api.getProcessingSettings.mockRejectedValue(error);
    const { result } = renderHook(
      () => useKnowledgeProcessingSettings(scope, 7, api),
      queryHost(),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBe(error);
    expect(result.current.data).toBeUndefined();
  });
});

describe("processing actions retain their issuing scope", () => {
  it("keeps a confirmed plan across ordinary rerenders with equal scope values", async () => {
    const api = apiPort();
    const { result, rerender } = renderHook(
      ({ value }) => useKnowledgeProcessingActions(value, 7, api),
      { ...queryHost(), initialProps: { value: scope } },
    );
    await result.current.precheck({
      kind: "embedding_rebuild",
      parameters: {},
    });
    rerender({ value: { ...scope } });
    await expect(
      result.current.createJob({
        idempotency_key: "create-1",
        confirmation_id: plan.confirmation_id,
        plan_digest: plan.plan_digest,
      }),
    ).resolves.toMatchObject({ job_id: "job-1", state: "running" });
  });

  it("passes only frozen plan/retry data and preserves the server's job state", async () => {
    const api = apiPort();
    const { result } = renderHook(
      () => useKnowledgeProcessingActions(scope, 7, api),
      queryHost(),
    );
    const checked = await result.current.precheck({
      kind: "embedding_rebuild",
      parameters: {},
    });
    expect(checked).toBe(plan);
    const create = {
      idempotency_key: "create-1",
      confirmation_id: checked.confirmation_id,
      plan_digest: checked.plan_digest,
    };
    expect(await result.current.createJob(create)).toEqual({
      job_id: "job-1",
      accepted: true,
      state: "running",
      reused: true,
    });
    expect(api.createProcessingJob).toHaveBeenCalledWith(7, create);
    const retry = { idempotency_key: "retry-1", expected_job_revision: 4 };
    expect((await result.current.retryJob("job-1", retry)).state).toBe(
      "partial_failed",
    );
    expect(api.retryProcessingJob).toHaveBeenCalledWith(7, "job-1", retry);
  });

  it("invalidates only the current space within the issuing scope", async () => {
    const api = apiPort();
    const host = queryHost();
    const other = { ...scope, tenantId: 202 };
    const currentKey = knowledgeQueryKeys.settings(scope, 7);
    const otherKey = knowledgeQueryKeys.settings(other, 7);
    host.client.setQueryData(currentKey, settings);
    host.client.setQueryData(otherKey, settings);
    const { result } = renderHook(
      () => useKnowledgeProcessingActions(scope, 7, api),
      host,
    );
    await result.current.updateSettings({
      expected_config_version: 0,
      defaults: settings.effective_defaults,
    });
    expect(host.client.getQueryState(currentKey)?.isInvalidated).toBe(true);
    expect(host.client.getQueryState(otherKey)?.isInvalidated).toBe(false);
  });

  it("rejects a late mutation without touching the new scope's cache", async () => {
    const response = deferred<ProcessingSettingsRead>();
    const api = apiPort();
    api.updateProcessingSettings.mockReturnValueOnce(response.promise);
    const host = queryHost();
    const other = { ...scope, managementTenantId: 202 };
    const otherKey = knowledgeQueryKeys.settings(other, 7);
    host.client.setQueryData(otherKey, { ...settings, config_version: 9 });
    const { result, rerender } = renderHook(
      ({ value }) => useKnowledgeProcessingActions(value, 7, api),
      { ...host, initialProps: { value: scope } },
    );
    const mutation = result.current.updateSettings({
      expected_config_version: 0,
      defaults: settings.effective_defaults,
    });
    const rejected = expect(mutation).rejects.toMatchObject({
      code: "knowledge_scope_changed",
    });
    rerender({ value: other });
    await act(async () => response.resolve(settings));
    await rejected;
    expect(host.client.getQueryData(otherKey)).toEqual({
      ...settings,
      config_version: 9,
    });
    expect(host.client.getQueryState(otherKey)?.isInvalidated).toBe(false);
  });

  it("does not reuse an old confirmation after switching scope, including a return to the original scope", async () => {
    const api = apiPort();
    const { result, rerender } = renderHook(
      ({ value }) => useKnowledgeProcessingActions(value, 7, api),
      { ...queryHost(), initialProps: { value: scope } },
    );
    await result.current.precheck({
      kind: "embedding_rebuild",
      parameters: {},
    });
    const body = {
      idempotency_key: "create-1",
      confirmation_id: plan.confirmation_id,
      plan_digest: plan.plan_digest,
    };
    const oldActions = result.current;
    rerender({ value: { ...scope, tenantId: 202 } });
    await expect(result.current.createJob(body)).rejects.toMatchObject({
      code: "knowledge_confirmation_scope_changed",
    });
    await expect(oldActions.createJob(body)).rejects.toMatchObject({
      code: "knowledge_scope_changed",
    });
    rerender({ value: scope });
    await expect(result.current.createJob(body)).rejects.toMatchObject({
      code: "knowledge_confirmation_scope_changed",
    });
    expect(api.createProcessingJob).not.toHaveBeenCalled();
  });

  it("does not issue a create command from an incomplete/non-executable precheck", async () => {
    const api = apiPort();
    api.precheckProcessing.mockResolvedValue({
      ...plan,
      can_execute: false,
      check_complete: false,
      valid_items: [],
    });
    const { result } = renderHook(
      () => useKnowledgeProcessingActions(scope, 7, api),
      queryHost(),
    );
    await result.current.precheck({
      kind: "embedding_rebuild",
      parameters: {},
    });
    await expect(
      result.current.createJob({
        idempotency_key: "x",
        confirmation_id: plan.confirmation_id,
        plan_digest: plan.plan_digest,
      }),
    ).rejects.toMatchObject({ code: "knowledge_confirmation_scope_changed" });
    expect(api.createProcessingJob).not.toHaveBeenCalled();
  });

  it("retains the old useKnowledgeDetails tuple and rejected fetch contract", async () => {
    const error = new Error("detail unavailable");
    legacy.detail.mockRejectedValue(error);
    const { result } = renderHook(() => useKnowledgeDetails([7]));
    await waitFor(() => expect(result.current[2]).toBe(error));
    expect(result.current[0]).toEqual([]);
    await expect(result.current[1]([7])).rejects.toBe(error);
  });
});
