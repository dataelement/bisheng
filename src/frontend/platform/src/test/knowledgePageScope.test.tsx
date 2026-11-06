import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import type { User } from "@/types/api/user";

const mocks = vi.hoisted(() => ({ scope: vi.fn(), error: vi.fn() }));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: null }),
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: mocks.scope }));
vi.mock("@/controllers/request", () => ({ showApiError: mocks.error }));

let user: Partial<User> | null;
let management: {
  scope: { scope_tenant_id: number | null; expires_at: string | null };
  loading: boolean;
  refresh: ReturnType<typeof vi.fn>;
};

function Wrapper({ children }: PropsWithChildren) {
  return (
    <userContext.Provider
      value={{
        user,
        setUser: vi.fn(),
        savedComponents: [],
        addSavedComponent: async () => undefined,
        checkComponentsName: () => false,
        delComponent: vi.fn(),
      }}
    >
      {children}
    </userContext.Provider>
  );
}

function deferred() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  user = { user_id: 7, tenant_id: 1, leaf_tenant_id: 101 };
  management = {
    scope: { scope_tenant_id: 202, expires_at: null },
    loading: false,
    refresh: vi.fn().mockResolvedValue(undefined),
  };
  mocks.scope.mockImplementation(() => management);
});
afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

it("uses an ordinary user's active leaf without adopting home or management scope", () => {
  const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
  expect(mocks.scope).toHaveBeenCalledWith({ enabled: false });
  expect(result.current).toMatchObject({
    user,
    canManage: false,
    isLoading: false,
  });
  expect(result.current.scopes).toEqual({
    ordinary: {
      identityKey: "user:7",
      tenantId: 101,
      managementTenantId: 101,
      view: "ordinary",
    },
    admin: {
      identityKey: "user:7",
      tenantId: 101,
      managementTenantId: 101,
      view: "admin",
    },
  });
});

it("uses only a super's selected server tenant while preserving the original user", () => {
  user = { ...user, is_global_super: true };
  const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
  expect(mocks.scope).toHaveBeenCalledWith({ enabled: true });
  expect(result.current.scopes?.ordinary.tenantId).toBe(202);
  expect(result.current.canManage).toBe(true);
  expect(result.current.user).toBe(user);
  expect(user?.tenant_id).toBe(1);
});

it.each([null, 0, -1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
  "does not fall back to leaf or home for invalid selected scope %s",
  (tenant) => {
    user = { ...user, is_global_super: true };
    management.scope.scope_tenant_id = tenant;
    const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
    expect(result.current.scopes).toBeNull();
  },
);

it.each([undefined, 0, -1, 1.5, Number.NaN])(
  "does not query an invalid active leaf %s",
  (leaf) => {
    user = { ...user, leaf_tenant_id: leaf };
    const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
    expect(result.current.scopes).toBeNull();
  },
);

it("requires an authenticated positive user id and retires the scope on logout", () => {
  const { result, rerender } = renderHook(useKnowledgePageScope, {
    wrapper: Wrapper,
  });
  user = { ...user, user_id: 0 };
  rerender();
  expect(result.current.scopes).toBeNull();
  user = null;
  rerender();
  expect(result.current).toMatchObject({
    scopes: null,
    user: null,
    canManage: false,
  });
});

it("keeps management eligibility limited to super or active tenant admin", () => {
  user = { ...user, is_child_admin: true };
  const { result, rerender } = renderHook(useKnowledgePageScope, {
    wrapper: Wrapper,
  });
  expect(result.current.canManage).toBe(true);
  user = { ...user, is_child_admin: false };
  rerender();
  expect(result.current.canManage).toBe(false);
});

it("does not expose a super scope while its server read is loading", () => {
  user = { ...user, is_global_super: true };
  management.loading = true;
  const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
  expect(result.current).toMatchObject({ isLoading: true, scopes: null });
});

it("reports the original refresh error and unlocks the current retry", async () => {
  user = { ...user, is_global_super: true };
  const pending = deferred();
  const error = { status_code: 19704, data: { original: true } };
  management.refresh.mockReturnValue(pending.promise);
  const { result, rerender } = renderHook(useKnowledgePageScope, {
    wrapper: Wrapper,
  });
  let request!: Promise<void>;
  act(() => {
    request = result.current.retry();
  });
  expect(result.current.isLoading).toBe(true);
  user = { ...user };
  rerender();
  await act(async () => {
    pending.reject(error);
    await request;
  });
  expect(mocks.error).toHaveBeenCalledExactlyOnceWith(error);
  expect(result.current.isLoading).toBe(false);
});

it("retires retries on identity ABA without clearing a newer retry or presenting its old error", async () => {
  user = { ...user, is_global_super: true };
  const old = deferred();
  const next = deferred();
  management.refresh
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(next.promise);
  const { result, rerender } = renderHook(useKnowledgePageScope, {
    wrapper: Wrapper,
  });
  let first!: Promise<void>;
  act(() => {
    first = result.current.retry();
  });
  user = { ...user, user_id: 8 };
  rerender();
  expect(result.current.isLoading).toBe(false);
  user = { ...user, user_id: 7 };
  rerender();
  let second!: Promise<void>;
  act(() => {
    second = result.current.retry();
  });
  await act(async () => {
    old.reject(new Error("old identity"));
    await first;
  });
  expect(mocks.error).not.toHaveBeenCalled();
  expect(result.current.isLoading).toBe(true);
  await act(async () => {
    next.resolve();
    await second;
  });
  expect(result.current.isLoading).toBe(false);
  expect(management.refresh).toHaveBeenCalledTimes(2);
});

it("does not report an obsolete retry after unmount", async () => {
  user = { ...user, is_global_super: true };
  const pending = deferred();
  management.refresh.mockReturnValue(pending.promise);
  const { result, unmount } = renderHook(useKnowledgePageScope, {
    wrapper: Wrapper,
  });
  let request!: Promise<void>;
  act(() => {
    request = result.current.retry();
  });
  unmount();
  await act(async () => {
    pending.reject(new Error("closed page"));
    await request;
  });
  expect(mocks.error).not.toHaveBeenCalled();
});

it("keeps the ordinary retry as a full reload", async () => {
  const reload = vi.fn();
  const { result } = renderHook(useKnowledgePageScope, { wrapper: Wrapper });
  vi.stubGlobal("window", { location: { reload } });
  try {
    await act(() => result.current.retry());
  } finally {
    vi.unstubAllGlobals();
  }
  expect(reload).toHaveBeenCalledOnce();
  expect(management.refresh).not.toHaveBeenCalled();
});
