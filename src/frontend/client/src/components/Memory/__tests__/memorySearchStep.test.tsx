import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AgentEvent } from "~/api/chatApi";
import type { MemoryItem } from "~/api/memory";
import DeepThinkingGroup from "~/components/Chat/Messages/DeepThinkingGroup";

// F132 (AC-87, 2026-11-14): the items a turn looked up are listed on its search step,
// and searches fired back to back read as one step.
const mockList = jest.fn();
const mockDelete = jest.fn();
jest.mock("~/api/memory", () => ({
  ...jest.requireActual("~/api/memory"),
  listMemoryItemsApi: () => mockList(),
  deleteMemoryItemApi: (id: string) => mockDelete(id),
}));
// Reasoning text itself is not under test here (it reads a Recoil setting).
jest.mock("~/components/Chat/Messages/ThinkingContent", () => ({
  __esModule: true,
  default: ({ reasoning }: { reasoning: string }) => <p>{reasoning}</p>,
}));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string, options?: Record<string, unknown>) =>
    options && Object.keys(options).length ? `${key}|${Object.values(options).join("|")}` : key,
}));

const item = (id: string, content: string): MemoryItem => ({
  id,
  content,
  type: "fact",
  status: "active",
  recorded_at: "2026-11-14 08:00",
  event_time: null,
  source: { scene: "daily", app_id: null, app_name: null, chat_id: "c1", origin: "explicit" },
  pinned: false,
  has_detail: false,
});

const search = (id: string, ids: string[]): AgentEvent =>
  ({
    type: "tool_call",
    tool_call_id: id,
    tool_name: "memory_search",
    args: { redacted: true, op: "search", item_ids: [] },
    results: { redacted: true, op: "search", item_ids: ids, ok: true, reason_code: null },
  }) as unknown as AgentEvent;

function renderGroup(events: AgentEvent[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DeepThinkingGroup events={events} isStreaming={true} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockList.mockResolvedValue([item("a", "Trip to Hainan in December"), item("b", "Prefers short answers")]);
  mockDelete.mockResolvedValue(undefined);
});

it("merges back-to-back searches into one row and lists their distinct items on demand", async () => {
  renderGroup([search("s1", ["a", "b"]), search("s2", ["b", "a"])]);
  const rows = screen.getAllByRole("button", { name: /memory\.step\.done_search/ });
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent("memory.step.done_search|2");
  expect(mockList).not.toHaveBeenCalled();

  fireEvent.click(rows[0]);
  expect(await screen.findByText("Trip to Hainan in December")).toBeInTheDocument();
  expect(screen.getByText("Prefers short answers")).toBeInTheDocument();

  // The server no longer has the item once it is deleted.
  mockList.mockResolvedValue([item("b", "Prefers short answers")]);
  fireEvent.click(screen.getAllByRole("button", { name: "memory.delete" })[0]);
  await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("a"));
  await waitFor(() => expect(screen.queryByText("Trip to Hainan in December")).toBeNull());
});

it("keeps searches separated by reasoning as separate rows", () => {
  renderGroup([
    search("s1", ["a"]),
    { type: "thinking", content: "Look again." } as unknown as AgentEvent,
    search("s2", ["b"]),
  ]);
  expect(screen.getAllByRole("button", { name: /memory\.step\.done_search\|1/ })).toHaveLength(2);
});

it("says the items are gone when none of them is in the viewer's own memory", async () => {
  renderGroup([search("s1", ["x"])]);
  fireEvent.click(screen.getByRole("button", { name: /memory\.step\.done_search/ }));
  expect(await screen.findByText("memory.step.hits_gone")).toBeInTheDocument();
});

it("does not open an empty search", () => {
  renderGroup([search("s1", [])]);
  expect(screen.queryByRole("button", { name: /memory\.step/ })).toBeNull();
  expect(screen.getByText("memory.step.done_search_empty")).toBeInTheDocument();
});
