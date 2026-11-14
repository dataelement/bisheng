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

it("lists only the items this turn's search returned, each deletable in place (AC-87)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({
      retrieved: [item("r1", "Budget is 5000"), item("p1", "Answer in English", { pinned: true })],
      // Carried into every turn, so it is not listed as something this answer drew on.
      resident: [item("p1", "Answer in English", { pinned: true }), item("p2", "Works in finance", { pinned: true })],
    }),
  );
  renderNotice({ flags: ATTR_FLAGS });

  const entry = screen.getByRole("button", { name: /memory\.attribution\.entry/ });
  expect(mockApi.getMemoryTurnApi).not.toHaveBeenCalled();
  fireEvent.click(entry);

  await screen.findByText("Budget is 5000");
  const lists = screen.getAllByRole("list");
  expect(lists).toHaveLength(1);
  const rows = within(lists[0]).getAllByRole("listitem");
  expect(rows.map((r) => r.querySelector("p")?.textContent)).toEqual(["Budget is 5000", "Answer in English"]);
  expect(screen.queryByText("Works in finance")).toBeNull();
  // No section headings, groups, hint or expand toggle.
  expect(screen.queryByRole("region")).toBeNull();
  expect(screen.queryByRole("heading")).toBeNull();
  expect(screen.queryByText(/resident/i)).toBeNull();
  expect(screen.getAllByRole("button", { name: "memory.delete" })).toHaveLength(2);

  const row = screen.getByText("Budget is 5000").closest("li") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "memory.delete" }));
  await waitFor(() => expect(mockApi.deleteMemoryItemApi).toHaveBeenCalledWith("r1"));
  await waitFor(() => expect(screen.queryByText("Budget is 5000")).toBeNull());
  expect(screen.getByText("Answer in English")).toBeInTheDocument();
});

it("shows no attribution in probe mode when the turn only carried resident memory (AC-87)", async () => {
  mockApi.getMemoryTurnApi.mockResolvedValue(
    turn({ retrieved: [], resident: [item("p2", "Works in finance", { pinned: true })] }),
  );
  const { container } = renderNotice({ messageId: "9", probe: true });
  await waitFor(() => expect(mockApi.getMemoryTurnApi).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: /memory\.attribution\.entry/ })).toBeNull();
  expect(container).toBeEmptyDOMElement();
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
