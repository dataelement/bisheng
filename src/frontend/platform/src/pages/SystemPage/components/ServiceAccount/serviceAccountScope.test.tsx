// Covers AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-27.
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode, type ReactNode } from "react";
import * as api from "@/controllers/API/serviceAccount";
import { getTenantsApi } from "@/controllers/API/tenant";
import request from "@/controllers/request";
import {
  loadActiveServiceAccountTenants,
  useServiceAccountManagementScope,
} from "./useServiceAccountManagementScope";

vi.mock("@/controllers/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
  },
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API/tenant", () => ({ getTenantsApi: vi.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, cacheTime: 0 } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}
const options = { enabled: true, userId: 7, tenantId: 1 };
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

describe("service account request scope", () => {
  it("binds every mutation to the form snapshot, including explicit Root", async () => {
    const controller = new AbortController();
    const scope = {
      tenantId: 1,
      signal: controller.signal,
      onScopeChanged: vi.fn(),
    };
    const calls = [
      () =>
        api.createServiceAccountApi(
          { name: "test", resource_owner_user_id: 21 },
          scope,
        ),
      () => api.updateServiceAccountApi(4, { name: "changed" }, scope),
      () => api.setServiceAccountEnabledApi(4, false, scope),
      () => api.setServiceAccountEnabledApi(4, true, scope),
      () => api.deleteServiceAccountApi(4, scope),
      () =>
        api.issueServiceAccountKeyApi(
          4,
          {} as Parameters<typeof api.issueServiceAccountKeyApi>[1],
          scope,
        ),
      () => api.updateServiceAccountKeyApi(4, 8, {}, scope),
      () => api.revokeServiceAccountKeyApi(4, 8, scope),
      () => api.revokeAllServiceAccountKeysApi(4, scope),
      () =>
        api.mutateServiceAccountResourceGrantsApi(
          4,
          "app",
          "example",
          {} as Parameters<typeof api.mutateServiceAccountResourceGrantsApi>[3],
          scope,
        ),
    ];
    for (const call of calls) await call();
    const configs = [request.post, request.patch, request.delete].flatMap(
      (fn) => vi.mocked(fn).mock.calls.map((args) => args.at(-1)),
    );
    expect(configs).toHaveLength(10);
    for (const config of configs)
      expect(config).toMatchObject({
        headers: { "X-Service-Account-Tenant": "1" },
      });
  });

  it("rejects stale scope once without replay and drops late accepted results", async () => {
    const onScopeChanged = vi.fn();
    const controller = new AbortController();
    const scope = { tenantId: 60, signal: controller.signal, onScopeChanged };
    vi.mocked(request.post).mockRejectedValueOnce({ status_code: 26073 });
    await expect(
      api.revokeAllServiceAccountKeysApi(4, scope),
    ).rejects.toMatchObject({ status_code: 26073 });
    expect(request.post).toHaveBeenCalledTimes(1);
    expect(onScopeChanged).toHaveBeenCalledTimes(1);
    const old = deferred<never>();
    vi.mocked(request.get).mockReturnValueOnce(old.promise);
    const pending = api.getServiceAccountApi(4, scope);
    controller.abort();
    old.resolve({ id: 4 } as never);
    await expect(pending).rejects.toMatchObject({ code: "ERR_CANCELED" });
    await expect(api.deleteServiceAccountApi(4, scope)).rejects.toMatchObject({
      code: "ERR_CANCELED",
    });
    expect(request.delete).not.toHaveBeenCalled();
  });

  it("scopes owner candidate pagination and honors the picker cancellation", async () => {
    const controller = new AbortController();
    const picker = new AbortController();
    await api.listServiceAccountOwnerCandidatesApi(
      { page: 3, page_size: 50, keyword: "owner" },
      { tenantId: 60, signal: controller.signal, onScopeChanged: vi.fn() },
      picker.signal,
    );
    expect(request.get).toHaveBeenCalledWith(
      expect.stringContaining("owner-candidates"),
      expect.objectContaining({
        headers: { "X-Service-Account-Tenant": "60" },
        params: { page: 3, page_size: 50, keyword: "owner" },
      }),
    );
  });
});

describe("management scope lifecycle", () => {
  it("allows the global list without selecting Root", async () => {
    vi.mocked(request.get).mockResolvedValue({ scope_tenant_id: null });
    const { result } = renderHook(
      () => useServiceAccountManagementScope(options),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ready).toBe(true);
    expect(result.current.requestScope?.tenantId).toBeNull();
    await api.listServiceAccountsApi({ page: 1, page_size: 20 }, result.current.requestScope!);
    expect(request.get).toHaveBeenLastCalledWith("/api/v1/service-accounts", expect.objectContaining({ headers: { "X-Service-Account-Tenant": "all" } }));
    expect(request.put).not.toHaveBeenCalled();
    await act(async () => {
      vi.mocked(request.put).mockResolvedValueOnce({ scope_tenant_id: 1 });
      await result.current.selectScope(1);
    });
    expect(request.put).toHaveBeenCalledWith(expect.any(String), {
      tenant_id: 1,
    });
    expect(result.current.ready).toBe(true);
    expect(result.current.currentTenantId).toBe(1);
  });

  it("blocks forms while switching and keeps the previous scope after failure", async () => {
    vi.mocked(request.get).mockResolvedValue({ scope_tenant_id: 60 });
    const { result } = renderHook(
      () => useServiceAccountManagementScope(options),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.ready).toBe(true));
    const oldSignal = result.current.requestScope!.signal;
    const change = deferred<never>();
    vi.mocked(request.put).mockReturnValueOnce(change.promise);
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.selectScope(1);
    });
    expect(result.current.ready).toBe(false);
    expect(oldSignal.aborted).toBe(true);
    await act(async () => {
      change.reject(new Error("unavailable"));
      await pending.catch(() => undefined);
    });
    expect(result.current.currentTenantId).toBe(60);
    expect(result.current.ready).toBe(true);
    expect(result.current.requestScope!.signal.aborted).toBe(false);
  });

  it("stale submission clears the view until explicit refresh, without mutation replay", async () => {
    vi.mocked(request.get).mockResolvedValue({ scope_tenant_id: 60 });
    const { result } = renderHook(
      () => useServiceAccountManagementScope(options),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.mocked(request.get).mockResolvedValue({ scope_tenant_id: 1 });
    act(() => result.current.requestScope!.onScopeChanged());
    await waitFor(() => expect(result.current.currentTenantId).toBe(1));
    expect(result.current.ready).toBe(false);
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.ready).toBe(true);
    expect(request.put).not.toHaveBeenCalled();
  });

  it("keeps ordinary admins on their authenticated tenant without reading super scope", () => {
    const { result } = renderHook(
      () =>
        useServiceAccountManagementScope({
          ...options,
          enabled: false,
          tenantId: 60,
        }),
      { wrapper: wrapper() },
    );
    expect(result.current.requestScope?.tenantId).toBe(60);
    expect(result.current.ready).toBe(true);
    expect(request.get).not.toHaveBeenCalled();
  });

  it("loads all active tenant pages and discards malformed ids", async () => {
    vi.mocked(getTenantsApi)
      .mockResolvedValueOnce({
        data: [
          { id: 1, status: "active" },
          { id: null, status: "active" },
        ] as never,
        total: 3,
      })
      .mockResolvedValueOnce({
        data: [{ id: 60, status: "active" }] as never,
        total: 3,
      });
    expect(
      (await loadActiveServiceAccountTenants()).map((row) => row.id),
    ).toEqual([1, 60]);
    expect(getTenantsApi).toHaveBeenLastCalledWith({
      page: 2,
      page_size: 100,
      status: "active",
    });
  });
});

it("recovers its request lifetime after StrictMode effect replay", async () => {
  const Provider = wrapper();
  const { result } = renderHook(() => useServiceAccountManagementScope({ ...options, enabled: false, tenantId: 1 }), {
    wrapper: ({ children }) => <StrictMode><Provider>{children}</Provider></StrictMode>,
  });
  await waitFor(() => expect(result.current.requestScope!.signal.aborted).toBe(false));
  expect(result.current.ready).toBe(true);
});
