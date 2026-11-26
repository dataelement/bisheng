/**
 * The conversation page's send path under the run protocol (F004): what a
 * send carries (knowledge scope, project, skills, lease), which conversation
 * and draft it belongs to, and the gates that refuse it. The run itself (its
 * live row, stop, regenerate) is covered by useAiChat.unified and the
 * useUnifiedRun suites.
 */
import { useLayoutEffect, useState } from "react";
import store from "~/store";
import { parkChatAsk, useChatAskHandoff } from "~/components/Chat/chatAskHandoff";
import { act, renderHook, waitFor } from "@testing-library/react";

jest.mock("react-activation", () => ({ useActivate: jest.fn() }));

let mockBsConfig: { models?: { id: number; visual: boolean }[]; enable_etl4lm?: boolean } = {};
let mockKnowledgeBlocked = false;
let mockKnowledgeVerifying = false;
const mockToast = jest.fn();
jest.mock('./useKnowledgeSpaceAccess', () => ({
    useKnowledgeSpaceAccess: (selection) => ({
        available: mockKnowledgeBlocked ? [] : selection,
        blocked: mockKnowledgeBlocked || mockKnowledgeVerifying,
        message: mockKnowledgeBlocked ? 'knowledgeAccess.revoked' : '',
        verifying: mockKnowledgeVerifying,
    }),
}));

let mockSelectedSkills: Array<{ name: string }> = [];

jest.mock("./useRunEvents", () => ({ useRunEvents: () => ({ follow: jest.fn() }) }));
const mockSendRunMessage = jest.fn();
jest.mock("~/api/runApi", () => ({
  sendRunMessage: (...args: unknown[]) => mockSendRunMessage(...args),
  stopConversationRun: jest.fn().mockResolvedValue(undefined),
}));

const mockGetAgentMessages = jest.fn();
const mockGetSessionName = jest.fn();
jest.mock("~/api/chatApi", () => ({
  getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args),
  getSessionName: (...args: unknown[]) => mockGetSessionName(...args),
}));
jest.mock("~/api/memory", () => ({
  getMemoryFlagsApi: () => Promise.resolve({}),
  mergeMemoryFlags: (messages: unknown) => messages,
}));
jest.mock('~/api/request', () => ({ __esModule: true, default: {}, translateApiErrorMessage: () => '' }));

// Recoil atoms are read-only fixtures here: `~/store` hands out tagged objects
// and the mocked `useRecoilState` unwraps whatever value each one carries.
jest.mock("recoil", () => ({
  useRecoilState: (atom: { __testValue?: unknown }) => [atom?.__testValue, jest.fn()],
}));
jest.mock("~/store", () => ({
  __esModule: true,
  default: {
    chatModel: { __testValue: { id: 1, name: "test-model" } },
    selectedAgentTools: { __testValue: [] },
  },
}));
jest.mock("~/store/linsight", () => ({
  SopStatus: { Running: "running", Stoped: "stoped", SopGenerating: "sop_generating" },
  taskModeSkillsState: () => ({ __testValue: mockSelectedSkills }),
}));

jest.mock("~/hooks/AuthContext", () => ({ useAuthContext: () => ({ user: { id: "test-user" } }) }));

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: mockBsConfig }) }));
jest.mock("~/utils/mediaAttachmentUtils", () => ({
  isMediaAttachmentFile: () => false,
}));
let mockUUIDSequence = 0;
jest.mock("uuid", () => ({ v4: () => `test-${++mockUUIDSequence}` }));
jest.mock("~/hooks/useLinsightManager", () => ({
  useLinsightManager: () => ({ linsightMap: new Map() }),
}));
jest.mock("~/api/linsight", () => ({
  getLinsightSessionVersionList: jest.fn().mockResolvedValue([]),
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

// Imported after the jest.mock calls above on purpose — the hook pulls those
// modules in at import time.
import useAiChat from "./useAiChat";
import { useRunStore, type RunEvent } from "~/store/runStore";
import { resetDesktopConversationBridge } from "~/components/Chat/desktopConversationBridge";

// The desktop channel is sticky once sampled; tests choose it explicitly.
let mockDesktopChannel = "web";
jest.mock("~/utils/clientEnvironment", () => {
  const actual = jest.requireActual("~/utils/clientEnvironment");
  // React snapshots must stay stable between reads, so reuse one object per channel.
  const snapshots = new Map();
  const getClientEnvironment = () => {
    const base = actual.getClientEnvironment();
    const cached = snapshots.get(mockDesktopChannel);
    if (cached?.base === base) return cached.value;
    const value = { ...base, channel: mockDesktopChannel };
    snapshots.set(mockDesktopChannel, { base, value });
    return value;
  };
  return { ...actual, getClientEnvironment };
});

type Payload = {
  text: string;
  conversationId: string | null;
  messageId: string;
  parentMessageId: string;
  model: string;
  task_mode: boolean;
  skills: string[];
  project_id?: string;
  use_knowledge_base: {
    organization_knowledge_ids: number[];
    knowledge_space_ids: number[];
    knowledge_space_tag_filters?: Record<string, number>;
  };
};

const historyOf = (conversationId: string) => [
  {
    text: `${conversationId} history`,
    sender: "User",
    isCreatedByUser: true,
    messageId: `${conversationId}-q`,
    parentMessageId: "",
    conversationId,
    error: false,
  },
];

const sendAnswer = (data: Record<string, unknown>) => ({ status_code: 200, status_message: "SUCCESS", data });
let mockRunSequence = 0;
/** The server's answer to a send: a started run, in a new conversation for a draft. */
const startedRun = (payload: Payload) => {
  const n = ++mockRunSequence;
  return sendAnswer({
    run_id: `r${n}`,
    disposition: "started",
    message_id: `m${n}`,
    conversation_id: payload.conversationId ?? `chat-${n}`,
  });
};

/** Every payload the run send received, in order. */
const payloads = (): Payload[] => mockSendRunMessage.mock.calls.map((call) => call[0] as Payload);
const lastPayload = () => payloads()[payloads().length - 1];

let eventEntry = 0;
const finishRun = (cid: string, runId: string) =>
  act(() => {
    useRunStore.getState().applyEvent(cid, { run_id: runId, data: {}, type: "run_finished" } as RunEvent, `9-${++eventEntry}`);
  });

const renderChat = (conversationId: string) =>
  renderHook(({ cid }: { cid: string }) => useAiChat(cid), {
    initialProps: { cid: conversationId },
  });

beforeEach(() => {
  mockUUIDSequence = 0;
  mockRunSequence = 0;
  eventEntry = 0;
  mockKnowledgeBlocked = false;
  mockKnowledgeVerifying = false;
  localStorage.clear();
  mockBsConfig = { models: [{ id: 1, visual: true }] };
  mockSelectedSkills = [];
  mockGetAgentMessages.mockImplementation((cid: string) => Promise.resolve(historyOf(cid)));
  mockGetSessionName.mockResolvedValue("");
  mockSendRunMessage.mockReset().mockImplementation((payload: Payload) => Promise.resolve(startedRun(payload)));
  act(() => useRunStore.setState({ conversations: {} }));
  (store.chatModel as unknown as { __testValue: { id: number; name: string } }).__testValue = { id: 1, name: 'test-model' };
});

describe('project draft in the run send', () => {
  const firstProject = '11111111-1111-4111-8111-111111111111';
  const otherProject = '22222222-2222-4222-8222-222222222222';
  it.each([false, true])('keeps the project selected before an asynchronous lease, task mode=%s', async taskMode => {
    window.history.replaceState({ key: 'project-origin' }, '', `/workspace/c/new?projectId=${firstProject}`);
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const lease = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const { result } = renderHook(() => useAiChat('new', '', () => lease));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('From the first project', undefined, { taskMode }); });
    window.history.replaceState({ key: 'another-project' }, '', `/workspace/c/new?projectId=${otherProject}`);
    await act(async () => { grant({ leaseId: 'lease-one', blocked: false }); await sending; });
    expect(payloads()[0]).toMatchObject({ project_id: firstProject, task_mode: taskMode });
    expect(mockSendRunMessage.mock.calls[0][1]).toEqual({ flowLeaseId: 'lease-one' });
  });

  it('does not adopt a later project when an ordinary draft waits for its lease', async () => {
    window.history.replaceState({ key: 'ordinary-origin' }, '', '/workspace/c/new');
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const lease = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const { result } = renderHook(() => useAiChat('new', '', () => lease));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('Ordinary question'); });
    window.history.replaceState({ key: 'later-project' }, '', `/workspace/c/new?projectId=${otherProject}`);
    await act(async () => { grant({ leaseId: 'lease-two', blocked: false }); await sending; });
    expect(payloads()[0].project_id).toBeUndefined();
  });

  it.each([false, true])('keeps the project on a same-draft retry, task mode=%s', async taskMode => {
    window.history.replaceState({ key: 'draft-retry', usr: { newChatKey: 'same-intent' } }, '', `/workspace/c/new?projectId=${firstProject}`);
    mockSendRunMessage.mockRejectedValueOnce(new Error('response lost'));
    const { result } = renderHook(() => useAiChat('new'));
    await act(async () => { await result.current.sendMessage('Retry this question', undefined, { taskMode }); });
    await act(async () => { await result.current.sendMessage('Retry this question', undefined, { taskMode }); });
    expect(payloads()[0].messageId).not.toBe(payloads()[1].messageId);
    expect(payloads()[1].project_id).toBe(firstProject);
  });
});

describe('new draft identity', () => {
  const firstProject = '11111111-1111-4111-8111-111111111111';
  const otherProject = '22222222-2222-4222-8222-222222222222';
  const draft = () => renderHook(({ cid, key }: { cid: string; key: string }) => useAiChat(cid, '', undefined, key), {
    initialProps: { cid: 'new', key: 'first-project-draft' },
  });

  it('resets a promoted unsaved route on a same-URL explicit new-chat action', async () => {
    const { result, rerender } = draft();
    await act(async () => { await result.current.sendMessage('Earlier question'); });
    expect(result.current.conversationId).toBe('chat-1');
    rerender({ cid: 'new', key: 'new-click-before-rewrite' });
    expect(result.current.conversationId).toBe('new');
    expect(result.current.messages).toEqual([]);
  });

  it('keeps a lease-delayed send from copying another draft’s messages', async () => {
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${firstProject}`);
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const pending = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const getLease = jest.fn().mockReturnValueOnce(pending).mockResolvedValue({ leaseId: 'immediate', blocked: false });
    const { result, rerender } = renderHook(({ key }) => useAiChat('new', '', getLease, key), { initialProps: { key: 'first-draft' } });
    act(() => result.current.setSelectedOrgKbs([{ id: '101', name: 'A', type: 'space' }]));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('First question waits'); });
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${otherProject}`);
    rerender({ key: 'other-draft' });
    act(() => result.current.setSelectedOrgKbs([{ id: '202', name: 'B', type: 'space' }]));
    await act(async () => { await result.current.sendMessage('Other draft question'); });
    await act(async () => { grant({ leaseId: 'delayed', blocked: false }); await sending; });
    const first = lastPayload();
    expect(first.text).toBe('First question waits');
    expect(result.current.selectedOrgKbs).toEqual([{ id: '202', name: 'B', type: 'space' }]);
    expect(first.use_knowledge_base.knowledge_space_ids).toEqual([101]);
    expect(first.parentMessageId).toBe('00000000-0000-0000-0000-000000000000');
    expect(result.current.messages[0].text).toBe('Other draft question');
  });
});

describe("useAiChat conversation switching", () => {
  it("keeps each conversation's parsing flag to itself", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("with a video", [{ name: "clip.mp4", filepath: "p" }]); });

    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));
    expect(result.current.isParsingMedia).toBe(false);

    rerender({ cid: "c1" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c1 history"));
  });
});

/**
 * Moving the view to a new conversation id must move the turn's state with it.
 * Each turn writes into a bucket keyed by the conversation it started in; a
 * bucket left under the draft id would resurface the next time someone opens
 * a new chat.
 */
describe("useAiChat adopts a new conversation id", () => {
  it("leaves nothing behind under the id the turn started with", async () => {
    const { result, rerender } = renderChat("new");

    await act(async () => { await result.current.sendMessage("write me a report"); });
    await waitFor(() => expect(result.current.conversationId).toBe("chat-1"));

    // The view rewrites its own URL to the id the server just minted.
    rerender({ cid: "chat-1" });

    // Starting another new chat must land on the welcome page, not on the
    // messages the previous turn left behind under "new".
    rerender({ cid: "new" });
    await waitFor(() => expect(result.current.conversationId).toBe("new"));
    expect(result.current.messages).toHaveLength(0);
  });
});

describe("history failure recovery", () => {
  it("retries a failed history request without changing the conversation", async () => {
    const failure = new Error("history unavailable");
    mockGetAgentMessages.mockRejectedValueOnce(failure);
    const { result } = renderChat("retry-history");
    await waitFor(() => expect(result.current.historyError).toBe(failure));
    act(() => result.current.retryHistory());
    await waitFor(() => expect(result.current.messages[0]?.text).toBe("retry-history history"));
    expect(result.current.historyError).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });
  it("ignores a history failure from a conversation that was left behind", async () => {
    let failOld: (reason: unknown) => void = () => undefined;
    mockGetAgentMessages.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          failOld = reject;
        }),
    );
    const { result, rerender } = renderChat("old-history");
    rerender({ cid: "current-history" });
    await waitFor(() => expect(result.current.messages[0]?.text).toBe("current-history history"));
    await act(async () => {
      failOld(new Error("old failure"));
    });
    expect(result.current.historyError).toBeNull();
    expect(result.current.messages[0]?.text).toBe("current-history history");
  });
});
describe("both modes mount the selected skills", () => {
  it.each([false, true])("sends the skill selection when taskMode=%s", async (taskMode) => {
    mockSelectedSkills = [{ name: "writing" }];
    const { result } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    await act(async () => { await result.current.sendMessage("Use this skill", null, { taskMode }); });
    expect(lastPayload()).toMatchObject({
      task_mode: taskMode,
      skills: ["writing"],
    });
  });
});

test("an incomplete upload rejects submission before sending", async () => {
  const { result } = renderChat("c1");
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  let accepted;
  await act(async () => {
    accepted = await result.current.sendMessage("Use this file", [{ name: "draft.txt", valid: false }], {
      taskMode: true,
    });
  });
  expect(accepted).toBe(false);
  expect(mockSendRunMessage).not.toHaveBeenCalled();
});

describe("conversation knowledge isolation", () => {
  const k1 = [{ id: "101", name: "K1", type: "space" }];
  const k2 = [{ id: "202", name: "K2", type: "space" }];
  const scope = () => lastPayload().use_knowledge_base;

  it("restores C1 and C2 independently and sends their saved scopes after reopening", async () => {
    const chat = renderChat("c1");
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
    act(() => chat.result.current.setSelectedOrgKbs(k1));
    chat.rerender({ cid: "c2" });
    expect(chat.result.current.selectedOrgKbs).toEqual([]);
    act(() => chat.result.current.setSelectedOrgKbs(k2));
    for (const [cid, knowledge] of [
      ["c1", k1],
      ["c2", k2],
      ["c1", k1],
    ] as const) {
      chat.rerender({ cid });
      expect(chat.result.current.selectedOrgKbs).toEqual(knowledge);
    }
    chat.unmount();
    const reopened = renderChat("c1");
    await waitFor(() => expect(reopened.result.current.isLoading).toBe(false));
    expect(reopened.result.current.selectedOrgKbs).toEqual(k1);
    await act(async () => { await reopened.result.current.sendMessage("search C1"); });
    expect(scope()).toMatchObject({ knowledge_space_ids: [101], organization_knowledge_ids: [] });
    reopened.rerender({ cid: "c2" });
    await waitFor(() => expect(reopened.result.current.isLoading).toBe(false));
    expect(reopened.result.current.selectedOrgKbs).toEqual(k2);
    await act(async () => { await reopened.result.current.sendMessage("search C2"); });
    expect(scope()).toMatchObject({ knowledge_space_ids: [202] });
  });

  it("commits the destination conversation and selection together on a route switch", async () => {
    const commits: Array<{ route: string; active: string; ids: string[] }> = [];
    const chat = renderHook(
      ({ cid }) => {
        const value = useAiChat(cid);
        useLayoutEffect(() => {
          commits.push({
            route: cid,
            active: value.conversationId,
            ids: value.selectedOrgKbs.map((item) => item.id),
          });
        });
        return value;
      },
      { initialProps: { cid: "c1" } },
    );
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
    act(() => chat.result.current.setSelectedOrgKbs(k1));
    chat.rerender({ cid: "c2" });
    expect(commits.filter((entry) => entry.route === "c2")).toEqual(
      expect.arrayContaining([{ route: "c2", active: "c2", ids: [] }]),
    );
    expect(commits.every((entry) => entry.route === entry.active)).toBe(true);
    expect(commits.filter((entry) => entry.route === "c2").every((entry) => entry.ids.length === 0)).toBe(
      true,
    );
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
  });

  it("regenerates from the current conversation and persists an explicit empty scope", async () => {
    const chat = renderChat("c1");
    await waitFor(() => expect(chat.result.current.messages).toHaveLength(1));
    act(() => chat.result.current.setSelectedOrgKbs(k1));
    chat.rerender({ cid: "c2" });
    await waitFor(() => expect(chat.result.current.messages[0]?.messageId).toBe("c2-q"));
    act(() => chat.result.current.setSelectedOrgKbs(k2));
    chat.rerender({ cid: "c1" });
    await waitFor(() => expect(chat.result.current.messages[0]?.messageId).toBe("c1-q"));
    await act(async () => { await chat.result.current.regenerate("c1-q"); });
    expect(lastPayload()).toMatchObject({ text: "c1 history", conversationId: "c1" });
    expect(scope()).toMatchObject({ knowledge_space_ids: [101] });
    finishRun("c1", "r1");
    act(() => chat.result.current.setSelectedOrgKbs([]));
    chat.unmount();
    const reopened = renderChat("c1");
    await waitFor(() => expect(reopened.result.current.isLoading).toBe(false));
    expect(reopened.result.current.selectedOrgKbs).toEqual([]);
    await act(async () => { await reopened.result.current.sendMessage("empty selection"); });
    expect(scope()).toMatchObject({ knowledge_space_ids: [], organization_knowledge_ids: [] });
  });

  it("carries the first turn scope into its server id while C2 stays selected", async () => {
    let answer: (value: unknown) => void = () => undefined;
    mockSendRunMessage.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
    const chat = renderChat("new");
    act(() => chat.result.current.setSelectedOrgKbs(k1));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = chat.result.current.sendMessage("first turn"); });
    await waitFor(() => expect(mockSendRunMessage).toHaveBeenCalledTimes(1));
    chat.rerender({ cid: "c2" });
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
    act(() => chat.result.current.setSelectedOrgKbs(k2));
    await act(async () => {
      answer(sendAnswer({ run_id: "r1", disposition: "started", message_id: "m1", conversation_id: "created-c1" }));
      await sending;
    });
    expect(chat.result.current.conversationId).toBe("c2");
    expect(chat.result.current.selectedOrgKbs).toEqual(k2);
    chat.rerender({ cid: "created-c1" });
    expect(chat.result.current.selectedOrgKbs).toEqual(k1);
    chat.rerender({ cid: "new" });
    expect(chat.result.current.selectedOrgKbs).toEqual([]);
  });

  it("starts historical sessions with their own scope when only legacy account memory exists", async () => {
    localStorage.setItem("bs:test-user:selectedOrgKbs", JSON.stringify(k2));
    const chat = renderChat("c1");
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
    expect(chat.result.current.selectedOrgKbs).toEqual([]);
  });
});

describe("knowledge-space asks across cached conversations", () => {
  it.each([
    ["same space after completion", "101", true],
    ["same space during generation", "101", false],
    ["different space after completion", "102", true],
    ["different space during generation", "102", false],
  ] as const)("starts a fresh second conversation: %s", async (_case, spaceId, finishFirst) => {
    parkChatAsk({ text: "first question", space: { id: "101", name: "Space one" } });
    const { result, rerender } = renderHook(
      ({ cid, locationKey }) => {
        const chat = useAiChat(cid);
        useChatAskHandoff({
          conversationId: cid,
          activeConversationId: chat.conversationId,
          locationKey,
          selectedKbs: chat.selectedOrgKbs,
          setSelectedKbs: chat.setSelectedOrgKbs,
          sendMessage: chat.sendMessage,
          ready: true,
          selectedModelId: 1,
          selectModel: jest.fn(() => true),
          onModelUnavailable: jest.fn(),
        });
        return chat;
      },
      { initialProps: { cid: "new", locationKey: "first" } },
    );

    await waitFor(() => expect(result.current.conversationId).toBe("chat-1"));
    expect(mockSendRunMessage).toHaveBeenCalledTimes(1);
    if (finishFirst) finishRun("chat-1", "r1");
    rerender({ cid: "chat-1", locationKey: "first-rewrite" });
    parkChatAsk({ text: "second question", space: { id: spaceId, name: spaceId } });
    rerender({ cid: "new", locationKey: "second" });

    await waitFor(() => expect(mockSendRunMessage).toHaveBeenCalledTimes(2));
    expect(lastPayload()).toMatchObject({
      conversationId: null,
      use_knowledge_base: { knowledge_space_ids: [Number(spaceId)] },
    });
    expect(result.current.messages[0].text).toBe("second question");
    rerender({ cid: "new", locationKey: "second-again" });
    expect(mockSendRunMessage).toHaveBeenCalledTimes(2);
  });
});

test("knowledge handoff submits the chosen model ID and space in the real chat payload", async () => {
  const modelAtom = store.chatModel as unknown as { __testValue: { id: number; name: string } };
  const initialModel = modelAtom.__testValue;
  parkChatAsk({ text: "Count entries", modelId: 2, space: { id: "28", name: "Knowledge" } });
  try {
    renderHook(() => {
      const [model, setModel] = useState(initialModel);
      modelAtom.__testValue = model;
      const chat = useAiChat('new');
      useChatAskHandoff({
        conversationId: "new",
        activeConversationId: chat.conversationId,
        locationKey: "knowledge",
        selectedKbs: chat.selectedOrgKbs,
        setSelectedKbs: chat.setSelectedOrgKbs,
        sendMessage: chat.sendMessage,
        ready: true,
        selectedModelId: model.id,
        selectModel: (id) => {
          setModel({ id, name: "Beta" });
          return true;
        },
        onModelUnavailable: jest.fn(),
      });
    });
    await waitFor(() => expect(mockSendRunMessage).toHaveBeenCalledTimes(1));
    expect(lastPayload()).toEqual(
      expect.objectContaining({
        text: "Count entries",
        model: "2",
        task_mode: false,
        use_knowledge_base: {
          personal_knowledge_enabled: false,
          organization_knowledge_ids: [],
          knowledge_space_ids: [28],
        },
      }),
    );
  } finally {
    modelAtom.__testValue = initialModel;
  }
});

test('preserves a space tag across send, regeneration and conversation reload', async () => {
  const tagged = [{ id: '12', name: 'Space', type: 'space', tag: { id: 7, name: 'Report' } }];
  const { result, unmount } = renderChat('c1');
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  act(() => result.current.setSelectedOrgKbs(tagged));
  await act(async () => { await result.current.sendMessage('tagged question'); });
  expect(lastPayload().use_knowledge_base.knowledge_space_tag_filters).toEqual({ '12': 7 });
  finishRun('c1', 'r1');
  await waitFor(() => expect(result.current.isStreaming).toBe(false));
  await act(async () => { await result.current.regenerate('c1-q'); });
  expect(mockSendRunMessage).toHaveBeenCalledTimes(2);
  expect(lastPayload().use_knowledge_base.knowledge_space_tag_filters).toEqual({ '12': 7 });
  unmount();
  const restored = renderChat('c1');
  expect(restored.result.current.selectedOrgKbs).toEqual(tagged);
});

test('rejects task-mode tag filtering without clearing the draft', async () => {
  const tagged = [{ id: '12', name: 'Space', type: 'space', tag: { id: 7, name: 'Report' } }];
  const { result } = renderChat('c1');
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  act(() => result.current.setSelectedOrgKbs(tagged));
  await act(async () => { expect(await result.current.sendMessage('question', [], { taskMode: true })).toBe(false); });
  expect(mockSendRunMessage).not.toHaveBeenCalled();
  expect(result.current.selectedOrgKbs).toEqual(tagged);
});

test('blocks image sends at the shared entry when neither vision nor image parsing is available', async () => {
  mockBsConfig = { models: [{ id: 1, visual: false }], enable_etl4lm: false };
  const { result } = renderChat('c1');
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  await act(async () => { expect(await result.current.sendMessage('Describe', [{ name: 'image.png', filepath: 'image.png' }])).toBe(false); });
  expect(mockSendRunMessage).not.toHaveBeenCalled();
  expect(result.current.messages).toHaveLength(1);
});

describe('revoked knowledge scope submission gate', () => {
    it('blocks sending during verification without a second warning toast', async () => {
        mockKnowledgeVerifying = true;
        const { result } = renderChat('new');
        await act(async () => { expect(await result.current.sendMessage('Keep this draft')).toBe(false); });
        expect(mockSendRunMessage).not.toHaveBeenCalled();
        expect(mockToast).not.toHaveBeenCalled();
    });

    it('keeps the old conversation intact and blocks sending and regenerating', async () => {
        mockKnowledgeBlocked = true;
        const { result } = renderChat('retained');
        await waitFor(() => expect(result.current.messages.length).toBeGreaterThan(0));
        const originalMessages = result.current.messages;
        await act(async () => { expect(await result.current.sendMessage('D6-W')).toBe(false); });
        await act(async () => { await result.current.regenerate('retained-q'); });
        expect(mockSendRunMessage).not.toHaveBeenCalled();
        expect(result.current.messages).toEqual(originalMessages);
        expect(result.current.knowledgeAccessMessage).toBe('knowledgeAccess.revoked');
    });
});

describe("desktop host conversation sync", () => {
  let renamed: ((conversationId: string) => void) | undefined;
  const reportRunning = jest.fn();
  beforeEach(() => {
    resetDesktopConversationBridge();
    reportRunning.mockClear();
    mockDesktopChannel = "desktop";
    window.dshChatPresentation = {
      reportLanding: jest.fn(),
      reportRunning,
      onConversationRenamed: (listener) => { renamed = listener; return () => { renamed = undefined; }; },
    };
  });
  afterEach(() => {
    delete window.dshChatPresentation;
    mockDesktopChannel = "web";
  });

  it("reports a send as running while it is in flight, including after switching away", async () => {
    let answer: (value: unknown) => void = () => undefined;
    mockSendRunMessage.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage("hello"); });
    await waitFor(() => expect(reportRunning).toHaveBeenLastCalledWith(["c1"]));
    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));
    expect(reportRunning).toHaveBeenLastCalledWith(["c1"]);
    await act(async () => {
      answer(sendAnswer({ run_id: "r1", disposition: "started", message_id: "m1", conversation_id: "c1" }));
      await sending;
    });
  });

  it("rereads the open conversation's name after the host renames it", async () => {
    mockGetSessionName.mockResolvedValue("Quarterly review");
    const { result } = renderChat("c1");
    await waitFor(() => expect(result.current.title).toBe("Quarterly review"));
    mockGetSessionName.mockResolvedValue("Annual review");
    act(() => renamed?.("c1"));
    await waitFor(() => expect(result.current.title).toBe("Annual review"));
    expect(mockGetSessionName).toHaveBeenLastCalledWith("c1");
  });

  it("keeps the current name when the reread fails", async () => {
    mockGetSessionName.mockResolvedValue("Quarterly review");
    const { result } = renderChat("c1");
    await waitFor(() => expect(result.current.title).toBe("Quarterly review"));
    mockGetSessionName.mockRejectedValueOnce(new Error("offline"));
    await act(async () => { renamed?.("c1"); });
    expect(result.current.title).toBe("Quarterly review");
  });
});
