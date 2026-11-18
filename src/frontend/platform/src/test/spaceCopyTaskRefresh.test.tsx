import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { listOwnedSpaceCopies, type SpaceCopyTask } from "@/controllers/API/knowledgeCopy";
import { knowledgeQueryKeys } from "@/controllers/hooks/knowledge";
import { useSpaceCopyTasks } from "@/pages/KnowledgePage/useSpaceCopyTasks";

vi.mock("@/controllers/API/knowledgeCopy", () => ({ listOwnedSpaceCopies: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: vi.fn() }));
const scope = { identityKey: "user:7", tenantId: 101, managementTenantId: 101, view: "ordinary" as const };
const task: SpaceCopyTask = { id: 8, name: "Copy", user_id: 7, state: 0, job_id: "job", job_state: "running", phase: "copying", total_count: 10, succeeded_count: 1, failed_count: 0 };
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.clearAllMocks(); });

it("updates copy progress without reloading the knowledge page and scopes terminal changes to the copy", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  clients.push(client);
  vi.mocked(listOwnedSpaceCopies).mockResolvedValue([task]);
  const key = [...knowledgeQueryKeys.scope(scope), "copy-tasks"];
  const copied = knowledgeQueryKeys.info(scope, 8);
  const unrelated = knowledgeQueryKeys.children(scope, 7);
  const otherTenant = knowledgeQueryKeys.info({ ...scope, tenantId: 202 }, 8);
  const list = knowledgeQueryKeys.visible(scope);
  for (const cacheKey of [copied, unrelated, otherTenant, list]) client.setQueryData(cacheKey, {});
  renderHook(() => useSpaceCopyTasks(scope), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await waitFor(() => expect(client.getQueryData(key)).toEqual([task]));
  await act(async () => { client.setQueryData(key, [{ ...task, succeeded_count: 2 }]); });
  for (const cacheKey of [copied, unrelated, otherTenant, list]) expect(client.getQueryState(cacheKey)?.isInvalidated).toBe(false);
  await act(async () => { client.setQueryData(key, []); });
  await waitFor(() => expect(client.getQueryState(copied)?.isInvalidated).toBe(true));
  expect(client.getQueryState(list)?.isInvalidated).toBe(true);
  expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
  expect(client.getQueryState(otherTenant)?.isInvalidated).toBe(false);
});
