/**
 * F004 (T061): both sides of the tenant switch for a deep-research send.
 * Off: the page takes the handoff frame and starts the task as today.
 * On: no handoff, no legacy task start; the turn is fed by the run store.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

jest.mock("react-activation", () => ({ useActivate: jest.fn() }));

let mockBsConfig: Record<string, unknown> = {};
jest.mock("./useKnowledgeSpaceAccess", () => ({
  useKnowledgeSpaceAccess: (selection: unknown) => ({ available: selection, blocked: false, message: "" }),
}));

const mockOpenedStreams: unknown[] = [];
jest.mock("sse.js", () => ({ SSE: jest.fn() }));
jest.mock("./useAiChatSSE", () => ({
  openChatStream: (submission: unknown) => {
    mockOpenedStreams.push(submission);
    return { close: jest.fn() };
  },
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
  getSSEUrl: () => "/workstation/chat",
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
  useLinsightManager: () => ({
    createLinsight: (...args: unknown[]) => mockCreateLinsight(...args),
    updateLinsight: jest.fn(),
    linsightMap: new Map(),
  }),
}));
jest.mock("~/hooks/inviteQuotaRefresh", () => ({ refreshInviteQuota: jest.fn() }));
const mockStartLinsight = jest.fn();
const mockCreateLinsight = jest.fn();
jest.mock("~/api/linsight", () => ({
  startLinsight: (...args: unknown[]) => mockStartLinsight(...args),
  getLinsightSessionVersionList: () => Promise.resolve([]),
}));
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
import { useRunStore, type RunEvent } from "~/store/runStore";

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
  mockOpenedStreams.length = 0;
  mockSubscribed.length = 0;
  mockBsConfig = { models: [{ id: 1, visual: true }], unified_runtime_enabled: true };
  mockGetAgentMessages.mockResolvedValue([]);
  mockSendRunMessage.mockReset();
  mockStopConversationRun.mockReset().mockResolvedValue(undefined);
  act(() => useRunStore.setState({ conversations: {} }));
});


beforeEach(() => {
  mockStartLinsight.mockReset().mockResolvedValue(undefined);
  mockCreateLinsight.mockReset();
});

type Handoff = (data: { session_version_id: string; chat_id: string }) => void;

describe("deep-research send, tenant switch off", () => {
  it("still takes the handoff: seeds the task store and starts the task (legacy WebSocket path)", async () => {
    mockBsConfig = { models: [{ id: 1, visual: true }] };
    const { result } = renderChat("new");
    await act(async () => {
      await result.current.sendMessage("research this", null, { taskMode: true });
    });
    expect(mockSendRunMessage).not.toHaveBeenCalled();
    expect(mockOpenedStreams).toHaveLength(1);
    const submission = mockOpenedStreams[0] as { payload: { task_mode?: boolean }; onTaskHandoff?: Handoff };
    expect(submission.payload.task_mode).toBe(true);
    expect(typeof submission.onTaskHandoff).toBe("function");
    await act(async () => {
      submission.onTaskHandoff?.({ session_version_id: "sv1", chat_id: "c9" });
    });
    expect(mockCreateLinsight).toHaveBeenCalledWith("sv1", expect.anything());
    expect(mockStartLinsight).toHaveBeenCalledWith("sv1");
    const taskTurn = result.current.messages.find((m) => m.category === "task");
    expect(taskTurn).toMatchObject({ linsightSessionVersionId: "sv1" });
    expect(taskTurn?.liveRunId).toBeUndefined();
    expect(result.current.unifiedRuntime).toBe(false);
  });
});

describe("deep-research send, tenant switch on", () => {
  it("opens no handoff stream and starts no legacy task; the turn is a row fed by the run store", async () => {
    mockSendRunMessage.mockResolvedValue(
      sendAnswer({ run_id: "r1", disposition: "started", message_id: "m1", conversation_id: "c9" }),
    );
    const { result } = renderChat("new");
    await act(async () => {
      await result.current.sendMessage("research this", null, { taskMode: true });
    });
    expect(mockOpenedStreams).toHaveLength(0);
    expect(mockSendRunMessage.mock.calls[0][0]).toMatchObject({ text: "research this", task_mode: true });
    expect(mockCreateLinsight).not.toHaveBeenCalled();
    expect(mockStartLinsight).not.toHaveBeenCalled();
    expect(result.current.unifiedRuntime).toBe(true);
    emit("c9", { type: "run_started" });
    emit("c9", { type: "plan", data: { items: [{ id: "p1", content: "step", status: "in_progress" }] } });
    emit("c9", { type: "text", data: { text: "working" } });
    const live = result.current.messages.find((m) => m.liveRunId === "r1");
    expect(live).toMatchObject({ text: "working", messageId: "run:r1" });
    expect(result.current.messages.some((m) => m.category === "task")).toBe(false);
  });

  it("sends the answer to a pending question through the send entry", async () => {
    mockGetAgentMessages.mockResolvedValue([row("101", true, "q")]);
    const { result } = renderChat("c9");
    await waitFor(() => expect(result.current.messages.length).toBeGreaterThan(0));
    emit("c9", { type: "run_started" });
    emit("c9", { type: "ask_user", data: { call_id: "k1", questions: [{ question: "which?" }] } });
    mockSendRunMessage.mockResolvedValue(
      sendAnswer({ run_id: "r1", disposition: "started", message_id: "m2", conversation_id: "c9" }),
    );
    await act(async () => {
      await result.current.sendMessage("the second one");
    });
    expect(mockSendRunMessage.mock.calls[0][0]).toMatchObject({ text: "the second one", conversationId: "c9" });
    expect(mockOpenedStreams).toHaveLength(0);
    expect(useRunStore.getState().conversations.c9.run).toMatchObject({ status: "running", pendingQuestion: null });
  });
});
