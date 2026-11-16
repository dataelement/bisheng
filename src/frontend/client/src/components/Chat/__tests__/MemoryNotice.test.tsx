import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { MemoryItem, MemoryTurn } from "~/api/memory";
import { MemoryNotice } from "../MemoryNotice";

const mockApi = {
  getMemoryTurnApi: jest.fn(),
  undoMemoryWriteApi: jest.fn(),
  deleteMemoryItemApi: jest.fn(),
};

jest.mock("~/api/memory", () => ({
  ...jest.requireActual("~/api/memory"),
  getMemoryTurnApi: (...args: unknown[]) => mockApi.getMemoryTurnApi(...args),
  undoMemoryWriteApi: (...args: unknown[]) => mockApi.undoMemoryWriteApi(...args),
  deleteMemoryItemApi: (...args: unknown[]) => mockApi.deleteMemoryItemApi(...args),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string, options?: Record<string, unknown>) =>
    options && Object.keys(options).length ? `${key}|${Object.values(options).join("|")}` : key,
}));

const item = (id: string, content: string, extra: Partial<MemoryItem> = {}): MemoryItem => ({
  id,
  content,
  type: "fact",
  status: "active",
  recorded_at: "2026-11-01 09:30",
  event_time: null,
  source: { scene: "daily", app_id: null, app_name: null, chat_id: "c1", origin: "explicit" },
  pinned: false,
  has_detail: false,
  ...extra,
});

const turn = (overrides: Partial<MemoryTurn>): MemoryTurn => ({
  turn_id: "t1",
  writes: [],
  retrieved: [],
  resident: [],
  ...overrides,
});

function renderNotice(props: Parameters<typeof MemoryNotice>[0]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryNotice {...props} />
    </QueryClientProvider>,
  );
}

const WRITE_FLAGS = { turn_id: "t1", has_write: true, has_attribution: false };
const ATTR_FLAGS = { turn_id: "t1", has_write: false, has_attribution: true };

beforeEach(() => {
  mockApi.undoMemoryWriteApi.mockResolvedValue({ item_id: "m1", related_item_id: null });
  mockApi.deleteMemoryItemApi.mockResolvedValue(undefined);
});

it("shows an operation notice for a write and expands to the item text (AC-21)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      writes: [{ record_id: 5, op: "remember", item_id: "m1", related_item_id: null, undone: false, item: item("m1", "Flight on Dec 5"), related_item: null }],
    }),
  );
  renderNotice({ flags: WRITE_FLAGS });

  const toggle = await screen.findByRole("button", { name: /memory\.notice\.remember\|1/ });
  expect(mockApi.getMemoryTurnApi).toHaveBeenCalledWith({ turnId: "t1", messageId: undefined });
  expect(screen.queryByText("Flight on Dec 5")).toBeNull();
  fireEvent.click(toggle);
  expect(await screen.findByText("Flight on Dec 5")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /memory\.attribution\.entry/ })).toBeNull();
});

it("shows corrected and forgotten items with their text (AC-21)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      writes: [
        { record_id: 6, op: "correct", item_id: "m2", related_item_id: "m1", undone: false, item: item("m2", "Prefers tea"), related_item: item("m1", "Prefers coffee", { status: "superseded" }) },
        { record_id: 7, op: "forget", item_id: null, related_item_id: "m3", undone: false, item: null, related_item: item("m3", "Lives in Beijing", { status: "deleted" }) },
      ],
    }),
  );
  renderNotice({ flags: WRITE_FLAGS });
  fireEvent.click(await screen.findByRole("button", { name: /memory\.notice\.updated\|2/ }));
  expect(await screen.findByText("Prefers tea")).toBeInTheDocument();
  expect(screen.getByText(/Prefers coffee/)).toBeInTheDocument();
  expect(screen.getByText("Lives in Beijing")).toBeInTheDocument();
  expect(screen.getByText("memory.notice.op_correct")).toBeInTheDocument();
  expect(screen.getByText("memory.notice.op_forget")).toBeInTheDocument();
});

it("undoes a write through the API and marks it undone (AC-22)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      writes: [{ record_id: 5, op: "remember", item_id: "m1", related_item_id: null, undone: false, item: item("m1", "Flight on Dec 5"), related_item: null }],
    }),
  );
  renderNotice({ flags: WRITE_FLAGS });
  fireEvent.click(await screen.findByRole("button", { name: /memory\.notice\.remember/ }));
  fireEvent.click(await screen.findByRole("button", { name: "memory.notice.undo" }));
  await waitFor(() => expect(mockApi.undoMemoryWriteApi).toHaveBeenCalledWith(5));
  expect(await screen.findByText("memory.notice.undone")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "memory.notice.undo" })).toBeNull();
});

it("shows the backend reason when an undo fails (AC-22)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      writes: [{ record_id: 5, op: "remember", item_id: "m1", related_item_id: null, undone: false, item: item("m1", "Flight on Dec 5"), related_item: null }],
    }),
  );
  mockApi.undoMemoryWriteApi.mockRejectedValueOnce(new Error("Cannot undo: the memory item has been changed again"));
  renderNotice({ flags: WRITE_FLAGS });
  fireEvent.click(await screen.findByRole("button", { name: /memory\.notice\.remember/ }));
  fireEvent.click(await screen.findByRole("button", { name: "memory.notice.undo" }));
  expect(await screen.findByText("Cannot undo: the memory item has been changed again")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "memory.notice.undo" })).toBeInTheDocument();
});

it("lists nothing it only looked up: retrieved items belong to the search step (AC-87)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(turn({ retrieved: [item("r1", "Budget is 5000")] }));
  const { container } = renderNotice({ flags: ATTR_FLAGS });
  expect(container).toBeEmptyDOMElement();
  expect(mockApi.getMemoryTurnApi).not.toHaveBeenCalled();

  // Probe mode (deep research) reads the turn but still shows only writes.
  const probed = renderNotice({ messageId: "9", probe: true });
  await waitFor(() => expect(mockApi.getMemoryTurnApi).toHaveBeenCalled());
  expect(probed.container).toBeEmptyDOMElement();
});

it("sits inside the answer's action row when inline (AC-21)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      writes: [{ record_id: 1, op: "remember", item_id: "a", related_item_id: null, undone: false, item: item("a", "Likes tea"), related_item: null }],
    }),
  );
  const { container } = renderNotice({ flags: WRITE_FLAGS, inline: true });
  const root = container.querySelector('[data-slot="memory-notice"]') as HTMLElement;
  expect(root.className).toContain("contents");
  fireEvent.click(await screen.findByRole("button", { name: /memory\.notice\.remember/ }));
  expect(await screen.findByText("Likes tea")).toBeInTheDocument();
  // The opened list takes a line of its own at the end of the wrapping row.
  expect(screen.getByText("Likes tea").closest(".basis-full")).not.toBeNull();
});

it("renders nothing and asks nothing without memory flags (AC-21, AC-87)", () => {
  const { container, rerender } = renderNotice({});
  expect(container).toBeEmptyDOMElement();
  rerender(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryNotice flags={{ turn_id: "t1", has_write: false, has_attribution: false }} />
    </QueryClientProvider>,
  );
  expect(container).toBeEmptyDOMElement();
  expect(mockApi.getMemoryTurnApi).not.toHaveBeenCalled();
});

it("reads a reloaded answer by message id when no turn id is known (AC-21)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(turn({ writes: [] }));
  renderNotice({ flags: { turn_id: "", has_write: true, has_attribution: false }, messageId: "42" });
  await waitFor(() => expect(mockApi.getMemoryTurnApi).toHaveBeenCalledWith({ turnId: undefined, messageId: "42" }));
});

it("probes a round by message id and stays hidden when it has no memory (AC-87)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(turn({ turn_id: null }));
  const { container } = renderNotice({ messageId: "77", probe: true });
  await waitFor(() => expect(mockApi.getMemoryTurnApi).toHaveBeenCalledWith({ turnId: undefined, messageId: "77" }));
  expect(container).toBeEmptyDOMElement();
});
