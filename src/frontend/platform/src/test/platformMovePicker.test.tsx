import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import request from "@/controllers/request";
import { confirmMove, precheckMove } from "@/controllers/API/knowledgeMove";
import { MoveDialog } from "@/pages/KnowledgePage/components/MoveDialog";

vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn() },
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/API/knowledgeMove", () => ({
  precheckMove: vi.fn(),
  confirmMove: vi.fn(),
}));
vi.mock("@/controllers/managementScope", () => ({
  managementRequestScope: () => 101,
}));
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.resetAllMocks();
});

it("uses the actual shared picker and commits its folder without treating picker close as cancellation", async () => {
  vi.mocked(request.get).mockImplementation(async (url, config) => {
    if (url.endsWith("/list"))
      return {
        data: [{ id: 1, name: "My space" }],
        has_more: false,
        next_cursor: null,
      };
    if (url.endsWith("/department")) return [{ id: 1, name: "My space" }];
    if (url.endsWith("/mine") || url.endsWith("/joined")) return [];
    const params = config?.params as
      { parent_id?: string; file_type?: number } | undefined;
    const rows = params?.parent_id
      ? []
      : [{ id: 7, file_name: "Destination folder", file_type: 0 }];
    return { data: rows, has_more: false, next_cursor: null };
  });
  vi.mocked(precheckMove).mockResolvedValue({
    confirmation_id: "shared-picker-plan",
    plan_digest: "digest",
    expires_at: "2030-01-01",
    check_complete: true,
    can_execute: true,
    valid_items: [{ id: 99, type: "file" }],
    invalid_items: [],
    impact: { cross_space: false },
    requires_skip_confirmation: false,
  });
  vi.mocked(confirmMove).mockResolvedValue({
    moved: [{ id: 99, type: "file" }],
    invalid: [],
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MoveDialog
        scope={{
          identityKey: "shared-picker",
          tenantId: 101,
          managementTenantId: 101,
          view: "ordinary",
        }}
        spaceId={1}
        parentId={null}
        items={[{ id: 99, type: "file" }]}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  const folders = await screen.findAllByRole("button", {
    name: "Destination folder",
  });
  fireEvent.click(folders[folders.length - 1]);
  expect(precheckMove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await waitFor(() =>
    expect(precheckMove).toHaveBeenCalledWith(
      1,
      [{ id: 99, type: "file" }],
      { spaceId: 1, folderId: 7 },
      101,
    ),
  );
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(confirmMove).toHaveBeenCalledOnce();
});
