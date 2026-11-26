import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { MemoryItem } from "~/api/memory";
import { MemoryPane } from "../MemoryPane";

const mockApi = {
  listMemoryItemsApi: jest.fn(),
  getMemorySettingApi: jest.fn(),
  updateMemorySettingApi: jest.fn(),
  addMemoryItemApi: jest.fn(),
  editMemoryItemApi: jest.fn(),
  deleteMemoryItemApi: jest.fn(),
  clearMemoryItemsApi: jest.fn(),
  getMemoryItemDetailApi: jest.fn(),
  reviseMemoryItemApi: jest.fn(),
};

jest.mock("~/api/memory", () => ({
  ...jest.requireActual("~/api/memory"),
  listMemoryItemsApi: (...args: unknown[]) => mockApi.listMemoryItemsApi(...args),
  getMemorySettingApi: (...args: unknown[]) => mockApi.getMemorySettingApi(...args),
  updateMemorySettingApi: (...args: unknown[]) => mockApi.updateMemorySettingApi(...args),
  addMemoryItemApi: (...args: unknown[]) => mockApi.addMemoryItemApi(...args),
  editMemoryItemApi: (...args: unknown[]) => mockApi.editMemoryItemApi(...args),
  deleteMemoryItemApi: (...args: unknown[]) => mockApi.deleteMemoryItemApi(...args),
  clearMemoryItemsApi: (...args: unknown[]) => mockApi.clearMemoryItemsApi(...args),
  getMemoryItemDetailApi: (...args: unknown[]) => mockApi.getMemoryItemDetailApi(...args),
  reviseMemoryItemApi: (...args: unknown[]) => mockApi.reviseMemoryItemApi(...args),
}));
// The markdown renderer pulls ESM-only plugins; the detail text itself is what is under test.
jest.mock("~/components/Chat/Messages/Content/MarkdownLite", () => ({
  __esModule: true,
  default: ({ content }: { content: string }) => <div data-testid="markdown">{content}</div>,
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string, options?: Record<string, unknown>) =>
    options && Object.keys(options).length ? `${key}|${Object.values(options).join("|")}` : key,
}));

const item = (overrides: Partial<MemoryItem>): MemoryItem => ({
  id: "m1",
  content: "Prefers short answers",
  type: "preference",
  status: "active",
  recorded_at: "2026-11-01 09:30",
  event_time: null,
  source: { scene: "daily", app_id: null, app_name: null, chat_id: "c1", origin: "explicit" },
  pinned: true,
  has_detail: false,
  ...overrides,
});

const ITEMS: MemoryItem[] = [
  item({}),
  item({
    id: "m2",
    content: "Team offsite in Hangzhou",
    type: "fact",
    recorded_at: "2026-11-02 10:00",
    event_time: "2026-12-05",
    source: { scene: "assistant", app_id: "a1", app_name: "Travel helper", chat_id: "c2", origin: "auto" },
    pinned: false,
  }),
  item({
    id: "m3",
    content: "Uses metric units",
    type: "fact",
    source: { scene: "manual", app_id: null, app_name: null, chat_id: null, origin: "manual" },
    pinned: false,
  }),
];

function renderPane() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryPane />
    </QueryClientProvider>,
  );
}

const rowOf = (text: string) => screen.getByText(text).closest("[data-memory-item]") as HTMLElement;

beforeEach(() => {
  mockApi.listMemoryItemsApi.mockResolvedValue(ITEMS);
  mockApi.getMemorySettingApi.mockResolvedValue({ enabled: true, timezone: "Asia/Taipei" });
  mockApi.updateMemorySettingApi.mockImplementation(async (enabled: boolean) => ({ enabled, timezone: null }));
  mockApi.addMemoryItemApi.mockResolvedValue({ item_id: "m9" });
  mockApi.editMemoryItemApi.mockResolvedValue({ item_id: "m8", replaced_item_id: "m1" });
  mockApi.deleteMemoryItemApi.mockResolvedValue(undefined);
  mockApi.clearMemoryItemsApi.mockResolvedValue(undefined);
});

it("groups memories by type and shows each summary with its date, nothing else (AC-88)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");

  // Preferences come first, each group under its own heading.
  expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual([
    "memory.group.preference",
    "memory.group.fact",
  ]);
  const first = rowOf("Prefers short answers");
  expect(within(first).getByText("2026-11-01")).toBeInTheDocument();
  // Type, source, event date and a pinned mark stay off the list.
  expect(within(first).queryByText(/memory\.type|memory\.source|resident/i)).toBeNull();
  expect(within(rowOf("Team offsite in Hangzhou")).queryByText(/2026-12-05|Travel helper/)).toBeNull();
});

const LONG = item({ id: "d1", content: "Weekly report format", type: "experience", has_detail: true });
const PLAIN = item({ id: "d2", content: "Likes iced coffee", has_detail: false });

async function openMemory(content: string) {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(content) }));
  return screen.findByRole("textbox", { name: "memory.revise_label" });
}

it("opens a memory with last updated, summary and details, and goes back (AC-88)", async () => {
  mockApi.listMemoryItemsApi.mockResolvedValue([LONG, PLAIN]);
  mockApi.getMemoryItemDetailApi.mockResolvedValue("- Conclusion first\n- Then the process");
  renderPane();
  await screen.findByText("Weekly report format");
  // The list shows summaries only; nothing is read until a memory is opened.
  expect(mockApi.getMemoryItemDetailApi).not.toHaveBeenCalled();
  expect(screen.queryByText(/full_text/)).toBeNull();

  await openMemory("Weekly report format");
  // The memory is the title; category, source and last update sit under it, then details.
  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Weekly report format");
  expect(screen.getByText("memory.field.type").nextSibling).toHaveTextContent("memory.type.experience");
  expect(screen.getByText("memory.field.source").nextSibling).toHaveTextContent("memory.source.daily");
  expect(screen.getByText("memory.updated_at")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 4 })).toHaveTextContent("memory.detail_label");
  // No hand editing: only delete and the AI box.
  expect(screen.queryByRole("button", { name: "memory.edit" })).toBeNull();
  expect(screen.getByRole("button", { name: "memory.delete" })).toBeInTheDocument();
  expect(await screen.findByTestId("markdown")).toHaveTextContent("- Conclusion first - Then the process");
  expect(mockApi.getMemoryItemDetailApi).toHaveBeenCalledWith("d1");
  expect(screen.queryByText("memory.list_title")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "memory.back" }));
  expect(await screen.findByText("Likes iced coffee")).toBeInTheDocument();

  await openMemory("Likes iced coffee");
  expect(screen.queryByTestId("markdown")).toBeNull();
  expect(screen.getByText("memory.no_detail")).toBeInTheDocument();
});

it("lets the AI change a memory, follows the new version, and undoes it (AC-107)", async () => {
  const revised = item({ id: "d9", content: "Weekly report: conclusion only", type: "experience", has_detail: true });
  mockApi.listMemoryItemsApi.mockResolvedValue([LONG]);
  mockApi.getMemoryItemDetailApi.mockImplementation(async (id: string) => (id === "d9" ? "Conclusion only" : "Old detail"));
  mockApi.reviseMemoryItemApi.mockResolvedValue({
    item_id: "d9",
    changed: true,
    previous: { summary: "Weekly report format", detail: "Old detail", type: "experience", event_time: null },
  });
  mockApi.editMemoryItemApi.mockResolvedValue({ item_id: "d10", replaced_item_id: "d9" });
  renderPane();
  await openMemory("Weekly report format");

  const box = screen.getByRole("textbox", { name: "memory.revise_label" });
  fireEvent.change(box, { target: { value: "Keep only the conclusion" } });
  mockApi.listMemoryItemsApi.mockResolvedValue([revised]);
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => expect(mockApi.reviseMemoryItemApi).toHaveBeenCalledWith("d1", "Keep only the conclusion"));
  expect(await screen.findByText("Weekly report: conclusion only")).toBeInTheDocument();
  expect(await screen.findByText("Conclusion only")).toBeInTheDocument();
  expect(screen.getByText("memory.revised")).toBeInTheDocument();
  expect(box).toHaveValue("");

  // Undo edits the new version back to the previous one, details included.
  mockApi.listMemoryItemsApi.mockResolvedValue([{ ...LONG, id: "d10" }]);
  fireEvent.click(screen.getByRole("button", { name: "memory.undo" }));
  await waitFor(() =>
    expect(mockApi.editMemoryItemApi).toHaveBeenCalledWith("d9", {
      content: "Weekly report format",
      type: "experience",
      event_time: null,
      detail: "Old detail",
    }),
  );
  expect(await screen.findByText("Weekly report format")).toBeInTheDocument();
  expect(screen.queryByText("memory.revised")).toBeNull();
});

it("shows that the AI is working while a change is in flight (AC-107)", async () => {
  mockApi.listMemoryItemsApi.mockResolvedValue([PLAIN]);
  mockApi.reviseMemoryItemApi.mockReturnValue(new Promise(() => {}));
  renderPane();
  const box = await openMemory("Likes iced coffee");
  fireEvent.change(box, { target: { value: "Make it hot coffee" } });
  fireEvent.keyDown(box, { key: "Enter" });

  expect(await screen.findByText("memory.revising")).toBeInTheDocument();
  expect(box).toBeDisabled();
  // One busy button: the spinner takes the arrow's place instead of sitting next to it.
  const send = screen.getByRole("button", { name: "memory.revise_send" });
  expect(send).toHaveAttribute("aria-busy", "true");
  expect(send.querySelectorAll("svg")).toHaveLength(1);
});

it("keeps the request and shows why when the AI could not change it (AC-107)", async () => {
  mockApi.listMemoryItemsApi.mockResolvedValue([LONG]);
  mockApi.getMemoryItemDetailApi.mockResolvedValue("Old detail");
  mockApi.reviseMemoryItemApi.mockRejectedValueOnce(new Error("The AI could not revise this memory"));
  renderPane();
  await openMemory("Weekly report format");
  const box = screen.getByRole("textbox", { name: "memory.revise_label" });
  fireEvent.change(box, { target: { value: "Make it nicer" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.revise_send" }));
  expect(await screen.findByText("The AI could not revise this memory")).toBeInTheDocument();
  expect(box).toHaveValue("Make it nicer");

  mockApi.reviseMemoryItemApi.mockResolvedValueOnce({
    item_id: "d1",
    changed: false,
    previous: { summary: "Weekly report format", detail: "Old detail", type: "experience", event_time: null },
  });
  fireEvent.click(screen.getByRole("button", { name: "memory.revise_send" }));
  expect(await screen.findByText("memory.revise_unchanged")).toBeInTheDocument();
});

it("shows a manually added item as added by hand (AC-88)", async () => {
  renderPane();
  await openMemory("Uses metric units");
  expect(screen.getByText("memory.field.source").nextSibling).toHaveTextContent("memory.source.manual");
});

it("asks a second time before clearing everything (AC-89)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");

  fireEvent.click(screen.getByRole("button", { name: "memory.clear" }));
  expect(await screen.findByText("memory.clear_confirm_title")).toBeInTheDocument();
  expect(mockApi.clearMemoryItemsApi).not.toHaveBeenCalled();

  mockApi.listMemoryItemsApi.mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "memory.clear_confirm_ok" }));
  await waitFor(() => expect(mockApi.clearMemoryItemsApi).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("memory.empty")).toBeInTheDocument();
});

it("cancelling the confirmation keeps every item (AC-89)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");
  fireEvent.click(screen.getByRole("button", { name: "memory.clear" }));
  fireEvent.click(await screen.findByRole("button", { name: "memory.cancel" }));
  expect(mockApi.clearMemoryItemsApi).not.toHaveBeenCalled();
  expect(screen.getByText("Prefers short answers")).toBeInTheDocument();
});

it("adds an item with one box and deletes one from its page; there is no hand editing (AC-89)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");
  expect(within(rowOf("Prefers short answers")).queryByRole("button", { name: "memory.edit" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "memory.add" }));
  fireEvent.change(await screen.findByRole("textbox", { name: "memory.add_title" }), { target: { value: "Likes green tea" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.save" }));
  await waitFor(() =>
    expect(mockApi.addMemoryItemApi).toHaveBeenCalledWith({ content: "Likes green tea", type: "fact", event_time: null }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  // Deleting happens on the memory's own page, which then goes back to the list.
  await openMemory("Team offsite in Hangzhou");
  fireEvent.click(screen.getByRole("button", { name: "memory.delete" }));
  await waitFor(() => expect(mockApi.deleteMemoryItemApi).toHaveBeenCalledWith("m2"));
});

it("shows the backend reason when an add is rejected, and keeps the dialog open (AC-89)", async () => {
  mockApi.addMemoryItemApi.mockRejectedValueOnce(new Error("Looks like a password; not saved"));
  renderPane();
  await screen.findByText("Prefers short answers");

  fireEvent.click(screen.getByRole("button", { name: "memory.add" }));
  fireEvent.change(await screen.findByRole("textbox", { name: "memory.add_title" }), { target: { value: "password: hunter2" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.save" }));
  expect(await screen.findByText("Looks like a password; not saved")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "memory.add_title" })).toHaveValue("password: hunter2");
});

it("shows the switch on by default and saves a change (AC-68)", async () => {
  renderPane();
  const toggle = await screen.findByRole("switch", { name: "memory.switch_label" });
  await waitFor(() => expect(toggle).toBeChecked());
  fireEvent.click(toggle);
  await waitFor(() => expect(mockApi.updateMemorySettingApi).toHaveBeenCalledWith(false));
  await waitFor(() => expect(toggle).not.toBeChecked());
});

it("keeps the list and every action available with my memory off (AC-90)", async () => {
  mockApi.getMemorySettingApi.mockResolvedValue({ enabled: false, timezone: null });
  renderPane();
  await screen.findByText("Prefers short answers");
  const toggle = screen.getByRole("switch", { name: "memory.switch_label" });
  await waitFor(() => expect(toggle).not.toBeChecked());

  expect(screen.getByRole("button", { name: "memory.add" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "memory.clear" })).toBeEnabled();
  await openMemory("Prefers short answers");
  fireEvent.click(screen.getByRole("button", { name: "memory.delete" }));
  await waitFor(() => expect(mockApi.deleteMemoryItemApi).toHaveBeenCalledWith("m1"));
});
