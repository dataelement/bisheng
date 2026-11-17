import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => vi.fn());
vi.mock("@bisheng/ui", () => ({ notification: { open: toast } }));
vi.mock("i18next", () => ({ default: { t: (key: string) => key, exists: () => false } }));
beforeEach(async () => {
  vi.resetModules();
  const storage = () => {
    const values = new Map<string, string>();
    return {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    };
  };
  vi.stubGlobal("localStorage", storage());
  vi.stubGlobal("sessionStorage", storage());
  toast.mockClear();
  const { acceptManagementScope } = await import("./managementScope");
  acceptManagementScope(60);
});
afterEach(() => vi.unstubAllGlobals());

describe("shared streaming request policy", () => {
  it("reuses base URL and Bearer authentication without buffering the successful body", async () => {
    const request = (await import("./request")).default;
    request.defaults.baseURL = "/base/";
    localStorage.setItem("ws_token", "synthetic-session");
    const bytes = new TextEncoder().encode('{"type":"meta"}\n');
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes);
      },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(body, {
          headers: { "content-type": "application/x-ndjson" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { requestStream } = await import("./requestStream");
    const result = await requestStream("/api/v1/audit");
    expect(result).toBe(body);
    expect(fetchMock.mock.calls[0]?.[0].pathname).toBe("/base/api/v1/audit");
    expect(fetchMock.mock.calls[0]?.[1].headers.Authorization).toBe(
      "Bearer synthetic-session",
    );
    await result.cancel();
  });
  it("retains the central kicked-session confirmation for HTTP 200 business errors", async () => {
    const { requestInterceptor } = await import("./request");
    const kicked = vi.fn();
    requestInterceptor.remoteLoginFuc = kicked;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status_code: 10604,
            status_message: "kicked",
          }),
          { headers: { "content-type": "application/json" } },
        ),
      ),
    );
    const { requestStream } = await import("./requestStream");
    await expect(requestStream("/api/v1/audit")).rejects.toMatchObject({ status_code: 10604 });
    expect(kicked).toHaveBeenCalledTimes(1);
  });
  it("reuses session invalidation on HTTP 401 without logging response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    const { requestStream } = await import("./requestStream");
    await expect(requestStream("/api/v1/audit")).rejects.toBeTruthy();
    expect(localStorage.getItem("ws_token")).toBeNull();
  });
  it("preserves the shared business-403 policy without a component-level branch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status_code: 403,
            status_message: "denied",
          }),
          { headers: { "content-type": "application/json" } },
        ),
      ),
    );
    const { requestStream } = await import("./requestStream");
    await expect(requestStream("/api/v1/audit")).rejects.toMatchObject({ status_code: 403 });
    expect(localStorage.getItem("noAccessUrl")).toContain("/api/v1/audit");
  });
});


it("rejects a mismatched stream target before handing out its reader", async () => {
  const { acceptManagementScope } = await import("./managementScope");
  acceptManagementScope(60);
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({cancel: cancelled});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, {
    headers: {"content-type": "application/x-ndjson", "x-management-tenant": "65"},
  })));
  const { requestStream } = await import("./requestStream");
  await expect(requestStream("/api/v1/dsh/admin/model-audit/requests/synthetic/body-access")).rejects.toMatchObject({status_code: 19704});
  expect(cancelled).toHaveBeenCalledTimes(1);
});


it("does not send the confirmed tenant to an unrelated origin", async () => {
  const { acceptManagementScope, managementRequestScope } = await import("./managementScope");
  acceptManagementScope(60);
  const body = new ReadableStream<Uint8Array>();
  const fetchMock = vi.fn().mockResolvedValue(new Response(body, {headers: {"content-type": "application/x-ndjson", "x-management-tenant": "65"}}));
  vi.stubGlobal("fetch", fetchMock);
  const { requestStream } = await import("./requestStream");
  const result = await requestStream("https://external.example.invalid/api/v1/dsh/admin/model-audit/requests/synthetic/body-access");
  expect(fetchMock.mock.calls[0]?.[1].headers["X-Management-Tenant"]).toBeUndefined();
  expect(managementRequestScope()).toBe(60);
  await result.cancel();
});


it("keeps a stale-scope error distinct from a successful HTTP envelope", async () => {
  const { acceptManagementScope } = await import("./managementScope");
  acceptManagementScope(60);
  const { handleRequestResponse } = await import("./request");
  await expect(handleRequestResponse({
    config: {method: "get", url: "/api/v1/guest-link/workflow/synthetic", managementScopeSnapshot: 65},
    headers: {"x-management-tenant": "60"}, status: 200, data: {status_code: 200, data: {}},
  })).rejects.toMatchObject({status_code: 19704});
});
