import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceFileTools } from "@/pages/KnowledgePage/components/SpaceFileTools";
const mocks = vi.hoisted(() => ({ action: vi.fn(), summary: vi.fn() }));
vi.mock("@/controllers/API/permission", () => ({
  checkResourceActionApi: mocks.action,
  getMyResourcePermissionsApi: mocks.summary,
}));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingDialog", () => ({
  SpaceProcessingDialog: ({ open }: { open: boolean }) => (open ? <p>processing-open</p> : null),
}));
vi.mock("@/pages/KnowledgePage/components/SpaceIndexEditDialog", () => ({
  SpaceIndexEditDialog: () => null,
}));
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const element = (tenantId: number) => (
    <QueryClientProvider client={client}>
      <SpaceFileTools
        scope={{ identityKey: "user:7", tenantId, managementTenantId: tenantId, view: "ordinary" }}
        spaceId={40}
        fileId={81}
        status={2}
      />
    </QueryClientProvider>
  );
  const result = render(element(101));
  return { ...result, tenant: (value: number) => result.rerender(element(value)) };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.action.mockResolvedValue({ allowed: true });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
it("admits the original edit action without looking up a visible-gated root summary", async () => {
  mocks.summary.mockRejectedValue(new Error("Root is not visible"));
  mount();
  await screen.findByRole("button", { name: "f118.processing_title_file" });
  expect(mocks.action).toHaveBeenCalledExactlyOnceWith({
    resource_type: "knowledge_space",
    resource_id: "40",
    action: "edit",
  });
  expect(mocks.summary).not.toHaveBeenCalled();
});
it("does not borrow other root actions or roles to render the tools", async () => {
  mocks.action.mockResolvedValue({ allowed: false });
  mount();
  await waitFor(() => expect(mocks.action).toHaveBeenCalledOnce());
  expect(
    screen.queryByRole("button", { name: "f118.processing_title_file" }),
  ).not.toBeInTheDocument();
});
it("does not revive an old edit response through tenant A-B-A", async () => {
  let resolve!: (value: { allowed: boolean }) => void;
  mocks.action
    .mockReturnValueOnce(
      new Promise((yes) => {
        resolve = yes;
      }),
    )
    .mockResolvedValue({ allowed: false });
  const view = mount();
  await waitFor(() => expect(mocks.action).toHaveBeenCalledTimes(1));
  view.tenant(202);
  await waitFor(() => expect(mocks.action).toHaveBeenCalledTimes(2));
  view.tenant(101);
  await waitFor(() => expect(mocks.action).toHaveBeenCalledTimes(3));
  await act(async () => resolve({ allowed: true }));
  expect(
    screen.queryByRole("button", { name: "f118.processing_title_file" }),
  ).not.toBeInTheDocument();
});
