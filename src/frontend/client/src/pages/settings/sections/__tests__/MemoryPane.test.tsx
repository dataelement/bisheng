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

it("lists content, type, recorded time, event time and source, with no pinned/resident mark (AC-88)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");

  const first = rowOf("Prefers short answers");
  expect(within(first).getByText("memory.type.preference")).toBeInTheDocument();
  expect(within(first).getByText(/2026-11-01 09:30/)).toBeInTheDocument();
  expect(within(first).getByText(/memory\.source\.daily/)).toBeInTheDocument();
  // A pinned item carries no extra label.
  expect(within(first).queryByText(/resident/i)).toBeNull();

  const second = rowOf("Team offsite in Hangzhou");
  expect(within(second).getByText("memory.type.fact")).toBeInTheDocument();
  // The event date is already in the content, so the meta line leaves it out.
  expect(within(second).queryByText(/2026-12-05/)).toBeNull();
  expect(within(second).getByText(/Travel helper/)).toBeInTheDocument();
});

it("shows a manually added item as added by hand (AC-88)", async () => {
  renderPane();
  await screen.findByText("Uses metric units");
  expect(within(rowOf("Uses metric units")).getByText(/memory\.source\.manual/)).toBeInTheDocument();
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

it("adds, edits and deletes an item (AC-89)", async () => {
  renderPane();
  await screen.findByText("Prefers short answers");

  fireEvent.click(screen.getByRole("button", { name: "memory.add" }));
  fireEvent.change(await screen.findByLabelText("memory.field.content"), { target: { value: "Likes green tea" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.save" }));
  await waitFor(() =>
    expect(mockApi.addMemoryItemApi).toHaveBeenCalledWith({ content: "Likes green tea", type: "fact", event_time: null }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  fireEvent.click(within(rowOf("Prefers short answers")).getByRole("button", { name: "memory.edit" }));
  const box = await screen.findByLabelText("memory.field.content");
  expect(box).toHaveValue("Prefers short answers");
  fireEvent.change(box, { target: { value: "Prefers very short answers" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.save" }));
  await waitFor(() =>
    expect(mockApi.editMemoryItemApi).toHaveBeenCalledWith("m1", {
      content: "Prefers very short answers",
      type: "preference",
      event_time: null,
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  fireEvent.click(within(rowOf("Team offsite in Hangzhou")).getByRole("button", { name: "memory.delete" }));
  await waitFor(() => expect(mockApi.deleteMemoryItemApi).toHaveBeenCalledWith("m2"));
});

it("shows the backend reason when an add or edit is rejected, and keeps the dialog open (AC-89)", async () => {
  mockApi.addMemoryItemApi.mockRejectedValueOnce(new Error("Looks like a password; not saved"));
  renderPane();
  await screen.findByText("Prefers short answers");

  fireEvent.click(screen.getByRole("button", { name: "memory.add" }));
  fireEvent.change(await screen.findByLabelText("memory.field.content"), { target: { value: "password: hunter2" } });
  fireEvent.click(screen.getByRole("button", { name: "memory.save" }));
  expect(await screen.findByText("Looks like a password; not saved")).toBeInTheDocument();
  expect(screen.getByLabelText("memory.field.content")).toHaveValue("password: hunter2");

  mockApi.editMemoryItemApi.mockRejectedValueOnce(new Error("Exceeds 200 characters"));
  fireEvent.click(screen.getByRole("button", { name: "memory.cancel" }));
  fireEvent.click(within(rowOf("Prefers short answers")).getByRole("button", { name: "memory.edit" }));
  fireEvent.click(await screen.findByRole("button", { name: "memory.save" }));
  expect(await screen.findByText("Exceeds 200 characters")).toBeInTheDocument();
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
  const row = rowOf("Prefers short answers");
  expect(within(row).getByRole("button", { name: "memory.edit" })).toBeEnabled();
  fireEvent.click(within(row).getByRole("button", { name: "memory.delete" }));
  await waitFor(() => expect(mockApi.deleteMemoryItemApi).toHaveBeenCalledWith("m1"));
});
