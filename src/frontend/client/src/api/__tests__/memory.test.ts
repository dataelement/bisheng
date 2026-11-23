import request from "~/api/request";
import type { ChatMessage } from "~/api/chatApi";
import {
  addMemoryItemApi,
  clearMemoryItemsApi,
  deleteMemoryItemApi,
  editMemoryItemApi,
  getMemoryFlagsApi,
  getMemorySettingApi,
  getMemoryTurnApi,
  listMemoryItemsApi,
  mergeMemoryFlags,
  parseMemorySignal,
  reportMemoryTimezoneApi,
  undoMemoryWriteApi,
  updateMemorySettingApi,
} from "~/api/memory";
import { reportTimezoneIfChanged, timezoneStorageKey } from "~/hooks/useMemoryTimezone";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
  translateApiErrorMessage: () => "",
  prepareBrowserHeaders: () => Promise.resolve({}),
}));


const mockedRequest = request as jest.Mocked<typeof request>;
const envelope = (data: unknown) => ({ status_code: 200, status_message: "SUCCESS", data });
const quiet = { skip403Redirect: true, showError: false };

describe("memory API wrapper (AC-14, AC-21)", () => {
  beforeEach(() => {
    mockedRequest.get.mockResolvedValue(envelope([]));
    mockedRequest.post.mockResolvedValue(envelope({ item_id: "m1" }));
    mockedRequest.put.mockResolvedValue(envelope({ item_id: "m2", replaced_item_id: "m1" }));
    mockedRequest.delete.mockResolvedValue(envelope(null));
  });

  it("calls every /api/v1/memory endpoint with its path and parameters (AC-21, AC-14)", async () => {
    await listMemoryItemsApi();
    expect(mockedRequest.get).toHaveBeenLastCalledWith("/api/v1/memory/items", quiet);

    await expect(addMemoryItemApi({ content: "likes tea", type: "preference" })).resolves.toEqual({ item_id: "m1" });
    expect(mockedRequest.post).toHaveBeenLastCalledWith(
      "/api/v1/memory/items",
      { content: "likes tea", type: "preference", event_time: null },
      quiet,
    );

    await expect(editMemoryItemApi("m 1", { content: "likes coffee", type: "fact", event_time: "2026-12-01" }))
      .resolves.toEqual({ item_id: "m2", replaced_item_id: "m1" });
    expect(mockedRequest.put).toHaveBeenLastCalledWith(
      "/api/v1/memory/items/m%201",
      { content: "likes coffee", type: "fact", event_time: "2026-12-01" },
      quiet,
    );

    await deleteMemoryItemApi("m1");
    expect(mockedRequest.delete).toHaveBeenLastCalledWith("/api/v1/memory/items/m1", quiet);

    await clearMemoryItemsApi();
    expect(mockedRequest.post).toHaveBeenLastCalledWith("/api/v1/memory/items/clear", {}, quiet);

    await undoMemoryWriteApi(7);
    expect(mockedRequest.post).toHaveBeenLastCalledWith("/api/v1/memory/undo", { record_id: 7 }, quiet);

    await getMemorySettingApi();
    expect(mockedRequest.get).toHaveBeenLastCalledWith("/api/v1/memory/setting", quiet);

    await updateMemorySettingApi(false);
    expect(mockedRequest.put).toHaveBeenLastCalledWith("/api/v1/memory/setting", { enabled: false }, quiet);

    await reportMemoryTimezoneApi("Asia/Taipei");
    expect(mockedRequest.post).toHaveBeenLastCalledWith(
      "/api/v1/memory/timezone",
      { timezone: "Asia/Taipei" },
      quiet,
    );

    mockedRequest.get.mockResolvedValueOnce(envelope({ turn_id: "t1", writes: [], retrieved: [], resident: [] }));
    await expect(getMemoryTurnApi({ turnId: "t 1" })).resolves.toEqual({
      turn_id: "t1",
      writes: [],
      retrieved: [],
      resident: [],
    });
    expect(mockedRequest.get).toHaveBeenLastCalledWith("/api/v1/memory/turn?turn_id=t%201", quiet);

    await getMemoryTurnApi({ messageId: "42" });
    expect(mockedRequest.get).toHaveBeenLastCalledWith("/api/v1/memory/turn?message_id=42", quiet);

    await getMemoryFlagsApi("chat/1");
    expect(mockedRequest.get).toHaveBeenLastCalledWith("/api/v1/memory/flags?chat_id=chat%2F1", quiet);
  });

  it("rejects a business error envelope with the backend message (AC-21)", async () => {
    mockedRequest.post.mockRejectedValueOnce(Object.assign(new Error("looks like a password"), { status_code: 12101 }));
    await expect(addMemoryItemApi({ content: "password: x" })).rejects.toThrow("looks like a password");
  });
});

describe("timezone report (AC-14)", () => {
  const key = timezoneStorageKey("u1");
  let spy: jest.SpyInstance;

  beforeEach(() => {
    localStorage.clear();
    mockedRequest.post.mockResolvedValue(envelope({ changed: true }));
    spy = jest.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      timeZone: "Asia/Taipei",
    } as Intl.ResolvedDateTimeFormatOptions);
  });
  afterEach(() => spy.mockRestore());

  it("reports the browser IANA timezone once and not again while it is unchanged (AC-14)", async () => {
    await expect(reportTimezoneIfChanged("u1")).resolves.toBe(true);
    expect(mockedRequest.post).toHaveBeenCalledWith("/api/v1/memory/timezone", { timezone: "Asia/Taipei" }, quiet);
    expect(localStorage.getItem(key)).toBe("Asia/Taipei");

    mockedRequest.post.mockClear();
    await expect(reportTimezoneIfChanged("u1")).resolves.toBe(false);
    expect(mockedRequest.post).not.toHaveBeenCalled();
  });

  it("reports again when the timezone changed (AC-14)", async () => {
    localStorage.setItem(key, "Europe/Paris");
    await expect(reportTimezoneIfChanged("u1")).resolves.toBe(true);
    expect(mockedRequest.post).toHaveBeenCalledWith("/api/v1/memory/timezone", { timezone: "Asia/Taipei" }, quiet);
  });

  it("keeps the last value when the report fails, so the next load retries (AC-14)", async () => {
    mockedRequest.post.mockRejectedValueOnce(new Error("offline"));
    await expect(reportTimezoneIfChanged("u1")).resolves.toBe(false);
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("still reports when browser storage is unavailable (AC-14)", async () => {
    const getItem = jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await expect(reportTimezoneIfChanged("u1")).resolves.toBe(true);
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it("does nothing without a user (AC-14)", async () => {
    await expect(reportTimezoneIfChanged("")).resolves.toBe(false);
    expect(mockedRequest.post).not.toHaveBeenCalled();
  });
});

describe("memory signal and history flags (AC-21)", () => {
  it("ignores a memory event without a turn id (AC-21)", () => {
    expect(parseMemorySignal({ category: "memory", message: { has_write: true } })).toBeNull();
    expect(parseMemorySignal({ category: "memory", message: JSON.stringify({ turn_id: "t", has_write: 1 }) }))
      .toEqual({ turn_id: "t", has_write: true, has_attribution: false });
  });

  it("merges flags fetched by chat id into loaded history (AC-21)", () => {
    const history = [
      { messageId: "1", text: "q", isCreatedByUser: true },
      { messageId: "2", text: "a" },
      { messageId: "3", text: "b" },
    ] as ChatMessage[];
    const merged = mergeMemoryFlags(history, {
      "2": { turn_id: "t2", has_write: false, has_attribution: true },
    });
    expect(merged[1].memory).toEqual({ turn_id: "t2", has_write: false, has_attribution: true });
    expect(merged[0]).toBe(history[0]);
    expect(merged[2]).toBe(history[2]);
    expect(mergeMemoryFlags(history, {})).toBe(history);
  });
});
