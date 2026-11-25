/**
 * F004 (T047): the send path and the live answer row of the conversation
 * page under the run protocol.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

jest.mock("react-activation", () => ({ useActivate: jest.fn() }));

let mockBsConfig: Record<string, unknown> = {};
jest.mock("./useKnowledgeSpaceAccess", () => ({
  useKnowledgeSpaceAccess: (selection: unknown) => ({ available: selection, blocked: false, message: "" }),
}));

const mockFollow = jest.fn();
const mockSubscribed: Array<[string, boolean]> = [];
jest.mock("./useRunEvents", () => ({
  useRunEvents: (cid: string, enabled: boolean) => {
    mockSubscribed.push([cid, enabled]);
    return { follow: mockFollow };
  },
}));

const mockSendRunMessage = jest.fn();
const mockStopConversationRun = jest.fn();
jest.mock("~/api/runApi", () => ({
  sendRunMessage: (...args: unknown[]) => mockSendRunMessage(...args),
  stopConversationRun: (...args: unknown[]) => mockStopConversationRun(...args),
}));

const mockGetAgentMessages = jest.fn();
jest.mock("~/api/chatApi", () => ({
  getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args),
  getSessionName: () => Promise.resolve(""),
}));
jest.mock("~/api/memory", () => ({
  getMemoryFlagsApi: () => Promise.resolve({}),
  mergeMemoryFlags: (messages: unknown) => messages,
}));
jest.mock("~/api/request", () => ({ __esModule: true, default: {}, translateApiErrorMessage: () => "failed" }));

jest.mock("recoil", () => ({
  useRecoilState: (atom: { __testValue?: unknown }) => [atom?.__testValue, jest.fn()],
}));
jest.mock("~/store", () => ({
  __esModule: true,
  default: {
    chatModel: { __testValue: { id: 1, name: "test-model" } },
    searchType: { __testValue: "" },
    selectedAgentTools: { __testValue: [] },
  },
}));
jest.mock("~/store/linsight", () => ({
  SopStatus: { Running: "running", Stoped: "stoped", SopGenerating: "sop_generating" },
  taskModeSkillsState: () => ({ __testValue: [] }),
}));
jest.mock("~/hooks/AuthContext", () => ({ useAuthContext: () => ({ user: { id: "test-user" } }) }));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
const mockShowToast = jest.fn();
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: mockBsConfig }) }));
jest.mock("~/utils/mediaAttachmentUtils", () => ({ isMediaAttachmentFile: () => false }));
let mockUUIDSequence = 0;
jest.mock("uuid", () => ({ v4: () => `test-${++mockUUIDSequence}` }));
jest.mock("~/hooks/useLinsightManager", () => ({
  useLinsightManager: () => ({ createLinsight: jest.fn(), updateLinsight: jest.fn(), linsightMap: new Map() }),
}));
jest.mock("~/api/linsight", () => ({ startLinsight: jest.fn(), getLinsightSessionVersionList: jest.fn() }));
jest.mock("~/types/chat", () => ({
  QueryKeys: { allConversations: "allConversations" },
  dataService: { genTitle: jest.fn().mockResolvedValue({}) },
}));
jest.mock("~/utils", () => ({
  addConversation: (data: unknown) => data,
  updateConvoFields: (data: unknown) => data,
}));
jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ setQueryData: jest.fn(), getQueryData: jest.fn() }),
}));

import useAiChat from "./useAiChat";
import { selectIsMessageQueued, useRunStore, type RunEvent } from "~/store/runStore";

const row = (id: string, isCreatedByUser: boolean, text = id) => ({
  text, sender: isCreatedByUser ? "User" : "AI", isCreatedByUser, messageId: id, parentMessageId: "",
  conversationId: "c9", error: false,
});
const sendAnswer = (data: Record<string, unknown>) => ({ status_code: 200, status_message: "SUCCESS", data });
let entry = 0;
const emit = (cid: string, event: Record<string, unknown>) =>
  act(() => {
    useRunStore.getState().applyEvent(cid, { run_id: "r1", data: {}, ...event } as RunEvent, `9-${++entry}`);
  });

const renderChat = (conversationId: string) =>
  renderHook(({ cid }: { cid: string }) => useAiChat(cid), { initialProps: { cid: conversationId } });

beforeEach(() => {
  mockUUIDSequence = 0;
  entry = 0;
  localStorage.clear();
  mockSubscribed.length = 0;
  mockBsConfig = { models: [{ id: 1, visual: true }] };
  mockGetAgentMessages.mockResolvedValue([]);
  mockSendRunMessage.mockReset();
  mockStopConversationRun.mockReset().mockResolvedValue(undefined);
  act(() => useRunStore.setState({ conversations: {} }));
});

describe("conversation page", () => {
  it("shows saved references after the run ends, on reload and on the share page", async () => {
    mockSendRunMessage.mockResolvedValue(
      sendAnswer({ run_id: "r1", disposition: "started", message_id: "m1", conversation_id: "c9" }),
    );
    const { result, unmount } = renderChat("new");
    const composerReferences = [
      { kind: "skill", label: "Web report", offset: 0 },
      { kind: "space", label: "Library", offset: 7 },
      { kind: "space", label: "#Reports", offset: 7, is_tag: true },
    ] as const;

    await act(async () => {
      await result.current.sendMessage("Make a report", [], { composerReferences: [...composerReferences] });
    });

    expect(mockSendRunMessage).toHaveBeenCalledWith(expect.objectContaining({
      text: "Make a report",
      composer_references: composerReferences,
    }), expect.anything());
    expect(result.current.messages[0]).toMatchObject({ messageId: "m1", composerReferences });

    mockGetAgentMessages.mockResolvedValue([
      { ...row("101", true, "Make a report"), category: "question", composerReferences: [...composerReferences] },
      row("102", false, "Here is your report"),
    ]);
    emit("c9", { type: "run_finished" });

    await waitFor(() => expect(result.current.messages.map((message) => message.messageId)).toEqual(["101", "102"]));
    expect(result.current.messages[0]).toMatchObject({ text: "Make a report", composerReferences });

    unmount();
    act(() => useRunStore.setState({ conversations: {} }));
    const reopened = renderChat("c9");
    await waitFor(() => expect(reopened.result.current.messages[0]).toMatchObject({ messageId: "101", composerReferences }));

    const shared = renderHook(() => useAiChat("c9", "share-token"));
    await waitFor(() => expect(shared.result.current.messages[0]).toMatchObject({ messageId: "101", composerReferences }));
  });

  it("starts a run, shows it in one row and lets the stored turn replace that row", async () => {
    mockSendRunMessage.mockResolvedValue(
      sendAnswer({ run_id: "r1", disposition: "started", message_id: "m1", conversation_id: "c9" }),
    );
    const { result } = renderChat("new");
    let accepted: boolean | undefined;
    await act(async () => {
      accepted = await result.current.sendMessage("hello");
    });
    expect(accepted).toBe(true);
    expect(mockSendRunMessage.mock.calls[0][0]).toMatchObject({ text: "hello", conversationId: null, task_mode: false });
    expect(result.current.conversationId).toBe("c9");
    expect(result.current.messages.map((m) => m.messageId)).toEqual(["m1", "run:r1"]);
    expect(result.current.isStreaming).toBe(true);
    expect(mockFollow).toHaveBeenCalled();
    // The new id must not trigger a history load over the optimistic rows.
    expect(mockGetAgentMessages).not.toHaveBeenCalled();

    emit("c9", { type: "run_started" });
    emit("c9", { type: "thinking", data: { text: "hmm", call_id: "t" } });
    emit("c9", { type: "text", data: { text: "Hi there" } });
    expect(result.current.messages[1]).toMatchObject({ text: "Hi there", category: "agent_answer", liveRunId: "r1" });
    expect(result.current.messages[1].events).toEqual([{ type: "thinking", content: "hmm" }]);

    mockGetAgentMessages.mockResolvedValue([row("101", true, "hello"), row("102", false, "Hi there")]);
    emit("c9", { type: "run_finished" });
    await waitFor(() => expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "102"]));
    expect(result.current.messages.some((m) => m.liveRunId !== undefined)).toBe(false);
    expect(result.current.isStreaming).toBe(false);
  });

  it("queues a message sent during a run and marks it by the server id", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    await waitFor(() => expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "run:r1"]));

    mockSendRunMessage.mockResolvedValue(sendAnswer({ run_id: "r1", disposition: "queued", message_id: "m2" }));
    await act(async () => {
      expect(await result.current.sendMessage("change step 3")).toBe(true);
    });
    expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "run:r1", "m2"]);
    expect(selectIsMessageQueued("c9", "m2")(useRunStore.getState())).toBe(true);

    emit("c9", { type: "steer_read", data: { message_id: "m2" } });
    expect(selectIsMessageQueued("c9", "m2")(useRunStore.getState())).toBe(false);
  });

  it("answers a pending question in the run's answer row and clears the question", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    emit("c9", { type: "ask_user", data: { call_id: "c", questions: [{ question: "which?" }] } });
    expect(useRunStore.getState().conversations.c9.run?.pendingQuestion).not.toBeNull();

    mockSendRunMessage.mockResolvedValue(sendAnswer({ run_id: "r1", disposition: "started", message_id: "m3" }));
    await act(async () => {
      await result.current.sendMessage("the second one");
    });
    // The answer is no row of its own: the answer row shows the question with it.
    expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "run:r1"]);
    const run = useRunStore.getState().conversations.c9.run;
    expect(run?.pendingQuestion).toBeNull();
    expect(run?.status).toBe("running");
  });

  it("keeps the draft and leaves no row behind when the send is rejected", async () => {
    mockSendRunMessage.mockRejectedValue(Object.assign(new Error("department is full"), { status_code: 19999 }));
    const { result } = renderChat("new");
    let accepted: boolean | undefined;
    await act(async () => {
      accepted = await result.current.sendMessage("hello");
    });
    expect(accepted).toBe(false);
    expect(result.current.messages).toEqual([]);
    expect(result.current.isStreaming).toBe(false);
    expect(mockShowToast).toHaveBeenCalledWith({ message: "department is full", status: "error" });
  });

  it("asks the backend to stop the run on screen", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    act(() => result.current.stopGenerating());
    expect(mockStopConversationRun).toHaveBeenCalledWith("c9", "r1");
    // The run ends on screen only when the server says so.
    expect(result.current.isStreaming).toBe(true);
    emit("c9", { type: "run_stopped" });
    expect(result.current.isStreaming).toBe(false);
  });

  it("tells the user when the stop request fails, and leaves the run on screen", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    mockStopConversationRun.mockRejectedValue(new Error("network"));
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    mockShowToast.mockClear();
    await act(async () => {
      result.current.stopGenerating();
    });
    expect(mockShowToast).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith({ message: "runComposer.stopFailed", status: "error" });
    expect(result.current.isStreaming).toBe(true);
  });

  it("shows the reason of a business stop failure once", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    mockStopConversationRun.mockRejectedValue(
      Object.assign(new Error("The conversation no longer exists."), { kind: "business", status_code: 13001, presentation: "none" }),
    );
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    mockShowToast.mockClear();
    await act(async () => {
      result.current.stopGenerating();
    });
    expect(mockShowToast).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith({ message: "The conversation no longer exists.", status: "error" });
    expect(result.current.isStreaming).toBe(true);
  });

  it("does not repeat a stop failure the request layer already showed", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    mockStopConversationRun.mockRejectedValue(Object.assign(new Error("denied"), { presentation: "toast" }));
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    mockShowToast.mockClear();
    await act(async () => {
      result.current.stopGenerating();
    });
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("shows no stop failure when the stop request succeeds", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "first")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    emit("c9", { type: "run_started" });
    mockShowToast.mockClear();
    await act(async () => {
      result.current.stopGenerating();
    });
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("regenerate sends the question again as a new run", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "what is up"), { ...row("102", false, "busy"), parentMessageId: "101", error: true }]);
    mockSendRunMessage.mockResolvedValue(sendAnswer({ run_id: "r1", disposition: "started", message_id: "103", conversation_id: "c9" }));
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    await act(async () => {
      await result.current.regenerate("101");
    });
    expect(mockSendRunMessage).toHaveBeenCalledTimes(1);
    expect(mockSendRunMessage.mock.calls[0][0]).toMatchObject({ text: "what is up", conversationId: "c9", files: [], task_mode: false });
    expect(mockSendRunMessage.mock.calls[0][0].isRegenerate).toBeUndefined();
    expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "102", "103", "run:r1"]);
    // The next message goes into the run.
    mockSendRunMessage.mockResolvedValue(sendAnswer({ run_id: "r1", disposition: "queued", message_id: "m2", conversation_id: "c9" }));
    emit("c9", { type: "run_started" });
    let accepted: boolean | void = false;
    await act(async () => {
      accepted = await result.current.sendMessage("and then?");
    });
    expect(accepted).toBe(true);
    expect(mockSendRunMessage).toHaveBeenCalledTimes(2);
  });

  it("regenerate does nothing while a run is in progress", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "q"), { ...row("102", false, "a"), parentMessageId: "101" }]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    emit("c9", { type: "run_started" });
    await act(async () => {
      await result.current.regenerate("101");
    });
    expect(mockSendRunMessage).not.toHaveBeenCalled();
  });

  it("does not show a second answer for a turn the history already holds", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "q"), row("102", false, "stored task row")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    emit("c9", { type: "run_started" });
    emit("c9", { type: "text", data: { text: "live text" } });
    expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "102"]);
  });
});

describe("share view", () => {
  it("loads and shows the history but never subscribes to runs or sends", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "q"), row("102", false, "a")]);
    const { result } = renderHook(() => useAiChat("c9", "share-token"));
    await waitFor(() => expect(result.current.messages.map((m) => m.messageId)).toEqual(["101", "102"]));
    expect(mockGetAgentMessages).toHaveBeenCalledWith("c9", "share-token");
    expect(mockSubscribed.every(([, enabled]) => enabled === false)).toBe(true);
    let accepted: boolean | undefined;
    await act(async () => {
      accepted = await result.current.sendMessage("hello");
    });
    expect(accepted).toBe(false);
    expect(mockSendRunMessage).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(2);
  });
});
