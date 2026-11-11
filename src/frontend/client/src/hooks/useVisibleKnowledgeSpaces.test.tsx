import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import {
  getVisibleSpacesPageApi,
  getVisibleSpacesTenant,
  type VisibleSpacesPage,
} from "~/api/knowledgeVisible";
import { useVisibleKnowledgeSpaces } from "./useVisibleKnowledgeSpaces";
let mockIdentity = {
  user: { id: "7" },
  token: "credential-one",
  isAuthenticated: true,
};
jest.mock("./AuthContext", () => ({ useAuthContext: () => mockIdentity }));
jest.mock("~/api/knowledgeVisible", () => ({
  getVisibleSpacesPageApi: jest.fn(),
  getVisibleSpacesTenant: jest.fn(),
}));
const readPage = jest.mocked(getVisibleSpacesPageApi);
const readTenant = jest.mocked(getVisibleSpacesTenant);
function page(
  names: string[],
  cursor: string | null = null,
): VisibleSpacesPage {
  return {
    data: names.map((id) => ({ id, name: id })) as VisibleSpacesPage["data"],
    page_size: 50,
    has_more: cursor != null,
    next_cursor: cursor,
  };
}
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: jest.fn(), warn: console.warn, error: () => {} },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
beforeEach(() => {
  mockIdentity = {
    user: { id: "7" },
    token: "credential-one",
    isAuthenticated: true,
  };
  readTenant.mockReset().mockResolvedValue(101);
  readPage.mockReset();
});
test("does not prefetch; explicitly advances through empty pages and retries only the failed cursor", async () => {
  readPage
    .mockResolvedValueOnce(page([], "one"))
    .mockResolvedValueOnce(page(["direct"], "two"))
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(page(["later", "direct"]));
  const view = renderHook(() => useVisibleKnowledgeSpaces(), setup());
  await waitFor(() => expect(view.result.current.hasMore).toBe(true));
  expect(readPage).toHaveBeenCalledTimes(1);
  expect(view.result.current.spaces).toEqual([]);
  act(() => view.result.current.loadMore());
  await waitFor(() =>
    expect(view.result.current.spaces.map((s) => s.id)).toEqual(["direct"]),
  );
  act(() => view.result.current.loadMore());
  await waitFor(() => expect(view.result.current.isError).toBe(true));
  await act(async () => {
    await view.result.current.retry();
  });
  await waitFor(() =>
    expect(view.result.current.spaces.map((s) => s.id)).toEqual([
      "direct",
      "later",
    ]),
  );
  expect(readPage.mock.calls.map(([input]) => input?.cursor)).toEqual([
    undefined,
    "one",
    "two",
    "two",
  ]);
  expect(view.result.current.hasMore).toBe(false);
});
test("late responses and new credentials stay in their actual actor/tenant/search scopes without JWT keys", async () => {
  let resolveOld: (value: VisibleSpacesPage) => void = () => {};
  readPage
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue(page(["current"]));
  const env = setup();
  const view = renderHook(
    ({ keyword }) => useVisibleKnowledgeSpaces({ keyword }),
    { ...env, initialProps: { keyword: "" } },
  );
  await waitFor(() => expect(readPage).toHaveBeenCalledTimes(1));
  mockIdentity = {
    user: { id: "8" },
    token: "credential-two",
    isAuthenticated: true,
  };
  readTenant.mockResolvedValue(202);
  view.rerender({ keyword: "fresh" });
  expect(view.result.current.spaces).toEqual([]);
  await waitFor(() =>
    expect(view.result.current.spaces.map((s) => s.id)).toEqual(["current"]),
  );
  await act(async () => resolveOld(page(["old-private"])));
  expect(view.result.current.spaces.map((s) => s.id)).toEqual(["current"]);
  expect(
    env.client
      .getQueryCache()
      .findAll({ queryKey: ["visible-space-candidates", "8", 202] }).length,
  ).toBe(1);
  expect(
    JSON.stringify(
      env.client
        .getQueryCache()
        .getAll()
        .map((q) => q.queryKey),
    ),
  ).not.toContain("credential-two");
  mockIdentity = { ...mockIdentity, token: "credential-three" };
  view.rerender({ keyword: "fresh" });
  expect(view.result.current.spaces).toEqual([]);
  await waitFor(() => expect(readTenant).toHaveBeenCalledTimes(3));
});
test("closed pickers do not fetch; tenant failures retry before candidate reads; logout hides results", async () => {
  readTenant
    .mockRejectedValueOnce(new Error("tenant unavailable"))
    .mockResolvedValue(101);
  readPage.mockResolvedValue(page(["direct"]));
  const view = renderHook(
    ({ enabled }) => useVisibleKnowledgeSpaces({ enabled }),
    { ...setup(), initialProps: { enabled: false } },
  );
  expect(readTenant).not.toHaveBeenCalled();
  expect(readPage).not.toHaveBeenCalled();
  view.rerender({ enabled: true });
  await waitFor(() => expect(view.result.current.isError).toBe(true));
  expect(readPage).not.toHaveBeenCalled();
  await act(async () => {
    await view.result.current.retry();
  });
  await waitFor(() =>
    expect(view.result.current.spaces.map((s) => s.id)).toEqual(["direct"]),
  );
  mockIdentity = { ...mockIdentity, isAuthenticated: false };
  view.rerender({ enabled: true });
  expect(view.result.current.spaces).toEqual([]);
});
