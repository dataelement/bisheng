/**
 * Regression cover for the "switch away mid-answer and the turn is lost" bug.
 *
 * Chat state used to be one active set held by whichever conversation was on
 * screen, and navigating to another one wiped it and aborted the SSE. The
 * backend runs the whole turn inside that stream, so the abort killed the
 * generation server-side and coming back showed a truncated, error-flagged
 * reply. These tests pin the two properties that fix depends on: leaving a
 * conversation neither closes its stream nor refetches over its live bucket.
 */
import { useLayoutEffect, useState } from "react";
import store from "~/store";
import { parkChatAsk, useChatAskHandoff } from "~/components/Chat/chatAskHandoff";
import { act, renderHook, waitFor } from "@testing-library/react";

import type { SSESubmission } from "./useAiChatSSE";

/** Every SSE turn opened during a test, in order. */
jest.mock("react-activation", () => ({ useActivate: jest.fn() }));

let mockBsConfig: { models?: { id: number; visual: boolean }[]; enable_etl4lm?: boolean } = {};
let mockKnowledgeBlocked = false;
jest.mock('./useKnowledgeSpaceAccess', () => ({
    useKnowledgeSpaceAccess: (selection) => ({
        available: mockKnowledgeBlocked ? [] : selection,
        blocked: mockKnowledgeBlocked,
        message: mockKnowledgeBlocked ? 'knowledgeAccess.revoked' : '',
    }),
}));

let mockSelectedSkills: Array<{ name: string }> = [];
const mockOpenedStreams: Array<{ submission: SSESubmission; close: jest.Mock }> = [];
let mockUseRealProjectTransport = false;
const mockTransportPayloads: Record<string, unknown>[] = [];
jest.mock('sse.js', () => ({ SSE: jest.fn().mockImplementation((_url, options) => {
  mockTransportPayloads.push(JSON.parse(options.payload));
  return { addEventListener: jest.fn(), stream: jest.fn(), close: jest.fn() };
}) }));

jest.mock("./useAiChatSSE", () => ({
  openChatStream: (submission: SSESubmission, localize: (key: string) => string) => {
    const handle = mockUseRealProjectTransport
      ? jest.requireActual('./useAiChatSSE').openChatStream(submission, localize)
      : { close: jest.fn() };
    const close = handle.close;
    mockOpenedStreams.push({ submission, close });
    return { close };
  },
}));

const mockGetAgentMessages = jest.fn();
const mockGetSessionName = jest.fn();
jest.mock("~/api/chatApi", () => ({
  getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args),
  getSessionName: (...args: unknown[]) => mockGetSessionName(...args),
  getSSEUrl: () => '/workstation/chat',
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
    searchType: { __testValue: "" },
    selectedAgentTools: { __testValue: [] },
  },
}));
jest.mock("~/store/linsight", () => ({
  SopStatus: { Running: "running", Stoped: "stoped", SopGenerating: "sop_generating" },
  taskModeSkillsState: () => ({ __testValue: mockSelectedSkills }),
}));

jest.mock("~/hooks/AuthContext", () => ({ useAuthContext: () => ({ user: { id: "test-user" } }) }));

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: mockBsConfig }) }));
// Added since the fix was lost: the hook now reads media metadata off
// attachments and mints an owner id for the stream registry.
jest.mock("~/utils/mediaAttachmentUtils", () => ({
  isMediaAttachmentFile: () => false,
}));
let mockUUIDSequence = 0;
jest.mock("uuid", () => ({ v4: () => `test-${++mockUUIDSequence}` }));
jest.mock("~/hooks/useLinsightManager", () => ({
  useLinsightManager: () => ({ createLinsight: jest.fn(), updateLinsight: jest.fn(), linsightMap: new Map() }),
}));
jest.mock("~/api/linsight", () => ({
  startLinsight: jest.fn().mockResolvedValue(undefined),
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
import { dataService } from "~/types/chat";

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

const renderChat = (conversationId: string) =>
  renderHook(({ cid }: { cid: string }) => useAiChat(cid), {
    initialProps: { cid: conversationId },
  });

/** The most recently opened turn's SSE callbacks. */
const latestStream = () => mockOpenedStreams[mockOpenedStreams.length - 1];

beforeEach(() => {
  mockUUIDSequence = 0;
  mockUseRealProjectTransport = false;
  mockTransportPayloads.length = 0;
  mockKnowledgeBlocked = false;
  localStorage.clear();
  mockOpenedStreams.length = 0;
  mockBsConfig = { models: [{ id: 1, visual: true }] };
  mockSelectedSkills = [];
  mockGetAgentMessages.mockImplementation((cid: string) => Promise.resolve(historyOf(cid)));
  mockGetSessionName.mockResolvedValue("");
});

describe('project draft through the real SSE serializer', () => {
  const firstProject = '11111111-1111-4111-8111-111111111111';
  const otherProject = '22222222-2222-4222-8222-222222222222';
  it.each([false, true])('keeps the project selected before an asynchronous lease, task mode=%s', async taskMode => {
    mockUseRealProjectTransport = true;
    window.history.replaceState({ key: 'project-origin' }, '', `/workspace/c/new?projectId=${firstProject}`);
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const lease = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const { result } = renderHook(() => useAiChat('new', false, '', 'chat', () => lease));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('From the first project', undefined, { taskMode }); });
    window.history.replaceState({ key: 'another-project' }, '', `/workspace/c/new?projectId=${otherProject}`);
    await act(async () => { grant({ leaseId: 'lease-one', blocked: false }); await sending; });
    expect(mockTransportPayloads[0]).toMatchObject({ project_id: firstProject, project_request_id: expect.any(String), task_mode: taskMode });
  });

  it('does not adopt a later project when an ordinary draft waits for its lease', async () => {
    mockUseRealProjectTransport = true;
    window.history.replaceState({ key: 'ordinary-origin' }, '', '/workspace/c/new');
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const lease = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const { result } = renderHook(() => useAiChat('new', false, '', 'chat', () => lease));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('Ordinary question'); });
    window.history.replaceState({ key: 'later-project' }, '', `/workspace/c/new?projectId=${otherProject}`);
    await act(async () => { grant({ leaseId: 'lease-two', blocked: false }); await sending; });
    expect(mockTransportPayloads[0].project_id).toBeUndefined();
    expect(mockTransportPayloads[0].project_request_id).toBeUndefined();
  });

  it.each([false, true])('reuses the first-message request id on a same-draft retry despite new UI message IDs, task mode=%s', async taskMode => {
    mockUseRealProjectTransport = true;
    window.history.replaceState({ key: 'draft-retry', usr: { newChatKey: 'same-intent' } }, '', `/workspace/c/new?projectId=${firstProject}`);
    const { result } = renderHook(() => useAiChat('new'));
    await act(async () => { await result.current.sendMessage('Retry this question', undefined, { taskMode }); });
    act(() => { latestStream().submission.onError('response lost'); latestStream().submission.onEnd(); });
    await act(async () => { await result.current.sendMessage('Retry this question', undefined, { taskMode }); });
    expect(mockTransportPayloads[0].messageId).not.toBe(mockTransportPayloads[1].messageId);
    expect(mockTransportPayloads[0].project_request_id).toBe(mockTransportPayloads[1].project_request_id);
  });
});

describe('new draft identity', () => {
  const firstProject = '11111111-1111-4111-8111-111111111111';
  const otherProject = '22222222-2222-4222-8222-222222222222';
  const draft = () => renderHook(({ cid, key }: { cid: string; key: string }) => useAiChat(cid, false, '', 'chat', undefined, key), {
    initialProps: { cid: 'new', key: 'first-project-draft' },
  });
  it.each([
    ['same project', firstProject], ['another project', otherProject], ['ordinary draft', ''],
  ])('starts an empty draft after a failed unsaved turn when opening %s', async (_label, project) => {
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${firstProject}`);
    const { result, rerender } = draft();
    await act(async () => { await result.current.sendMessage('Failed earlier question'); });
    const old = latestStream();
    act(() => { old.submission.onError('failed'); old.submission.onEnd(); });
    expect(result.current.messages).toHaveLength(2);
    window.history.replaceState({}, '', `/workspace/c/new${project ? '?projectId=' + project : ''}`);
    rerender({ cid: 'new', key: 'fresh-explicit-draft' });
    expect(result.current.conversationId).toBe('new');
    expect(result.current.messages).toEqual([]);
    expect(result.current.isStreaming).toBe(false);
    expect(old.close).not.toHaveBeenCalled();
  });

  it('keeps late created/answer callbacks in the original draft without cancelling generation', async () => {
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${firstProject}`);
    const { result, rerender } = draft();
    await act(async () => { await result.current.sendMessage('First project question'); });
    const old = latestStream();
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${otherProject}`);
    rerender({ cid: 'new', key: 'second-project-draft' });
    await act(async () => { await result.current.sendMessage('Second project question'); });
    const current = latestStream();
    act(() => {
      old.submission.onCreated('first-real-chat', { ...old.submission.userMessage, conversationId: 'first-real-chat' });
      old.submission.onAgentUpdate?.({ text: 'Answer for first project' });
    });
    expect(result.current.conversationId).toBe('new');
    expect(result.current.messages[0].text).toBe('Second project question');
    act(() => current.submission.onCreated('second-real-chat', { ...current.submission.userMessage, conversationId: 'second-real-chat' }));
    expect(result.current.conversationId).toBe('second-real-chat');
    expect(result.current.messages[0].text).toBe('Second project question');
    expect(old.close).not.toHaveBeenCalled();
    await act(async () => { old.submission.onFinal({ final: true }); });
    expect(dataService.genTitle).toHaveBeenLastCalledWith({ conversationId: 'first-real-chat' });
    rerender({ cid: 'first-real-chat', key: 'first-real-route' });
    expect(result.current.messages[0].text).toBe('First project question');
    expect(result.current.messages[1].text).toBe('Answer for first project');
  });

  it('resets a promoted unsaved route on a same-URL explicit new-chat action', async () => {
    const { result, rerender } = draft();
    await act(async () => { await result.current.sendMessage('Earlier question'); });
    const old = latestStream();
    act(() => old.submission.onCreated('created-before-url-rewrite', { ...old.submission.userMessage, conversationId: 'created-before-url-rewrite' }));
    expect(result.current.conversationId).toBe('created-before-url-rewrite');
    rerender({ cid: 'new', key: 'new-click-before-rewrite' });
    expect(result.current.conversationId).toBe('new');
    expect(result.current.messages).toEqual([]);
    expect(old.close).not.toHaveBeenCalled();
  });

  it('keeps a lease-delayed send from copying another draft’s messages', async () => {
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${firstProject}`);
    let grant: (value: { leaseId: string; blocked: boolean }) => void = () => {};
    const pending = new Promise<{ leaseId: string; blocked: boolean }>(resolve => { grant = resolve; });
    const getLease = jest.fn().mockReturnValueOnce(pending).mockResolvedValue({ leaseId: 'immediate', blocked: false });
    const { result, rerender } = renderHook(({ key }) => useAiChat('new', false, '', 'chat', getLease, key), { initialProps: { key: 'first-draft' } });
    act(() => result.current.setSelectedOrgKbs([{ id: '101', name: 'A', type: 'space' }]));
    let sending: Promise<boolean> | undefined;
    act(() => { sending = result.current.sendMessage('First question waits'); });
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${otherProject}`);
    rerender({ key: 'other-draft' });
    act(() => result.current.setSelectedOrgKbs([{ id: '202', name: 'B', type: 'space' }]));
    await act(async () => { await result.current.sendMessage('Other draft question'); });
    await act(async () => { grant({ leaseId: 'delayed', blocked: false }); await sending; });
    const first = latestStream();
    expect(result.current.selectedOrgKbs).toEqual([{ id: '202', name: 'B', type: 'space' }]);
    expect(first.submission.payload.use_knowledge_base.knowledge_space_ids).toEqual([101]);
    act(() => first.submission.onCreated('first-real-chat', { ...first.submission.userMessage, conversationId: 'first-real-chat' }));
    expect(result.current.messages[0].text).toBe('Other draft question');
    expect(first.submission.payload.parentMessageId).toBe('00000000-0000-0000-0000-000000000000');
  });

  it('discards an ended abandoned draft instead of retaining every old unsaved bucket', async () => {
    const { result, rerender } = draft();
    await act(async () => { await result.current.sendMessage('Ended draft'); });
    act(() => { latestStream().submission.onError('failed'); latestStream().submission.onEnd(); });
    rerender({ cid: 'new', key: 'next-draft' });
    rerender({ cid: 'new', key: 'first-project-draft' });
    expect(result.current.messages).toEqual([]);
  });
});

describe("useAiChat conversation switching", () => {
  it("keeps a turn streaming into its own conversation while another is on screen", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("hello"); });
    expect(mockOpenedStreams).toHaveLength(1);
    const turn = latestStream();

    act(() => {
      turn.submission.onStart();
      turn.submission.onAgentUpdate?.({ text: "half an answ" });
    });
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[result.current.messages.length - 1].text).toBe("half an answ");

    // Walk away mid-answer.
    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

    // The stream must survive — closing it is what killed the generation.
    expect(turn.close).not.toHaveBeenCalled();
    // ...and c2 must not inherit c1's streaming state.
    expect(result.current.isStreaming).toBe(false);

    // Tokens that arrive while the user is elsewhere still land in c1.
    act(() => {
      turn.submission.onAgentUpdate?.({ text: "half an answer, then the rest" });
      turn.submission.onFinal({ final: true });
      turn.submission.onEnd();
    });
    expect(result.current.messages[0].text).toBe("c2 history");

    // Coming back shows the completed turn, not a refetched stub.
    mockGetAgentMessages.mockClear();
    rerender({ cid: "c1" });
    await waitFor(() =>
      expect(result.current.messages[result.current.messages.length - 1].text).toBe(
        "half an answer, then the rest",
      ),
    );
  });

  /**
   * Added with the restore: the attachment-ingest poll was written after this
   * fix was lost, on the assumption that one conversation is live at a time.
   * It used a single timer, cancelled it on every switch, and wrote its result
   * into whatever was on screen. Under buckets that is a silent corruption —
   * it compiles, it passes the older tests, and it occasionally files one
   * conversation's attachments under another.
   */
  it("does not cancel a conversation's attachment poll when the user walks away", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("with a video", [{ name: "clip.mp4", filepath: "p" }]); });
    const before = jest.getTimerCount?.() ?? 0;

    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

    // Switching is not a reason to stop parsing what c1 uploaded.
    expect(jest.getTimerCount?.() ?? 0).toBeGreaterThanOrEqual(before);
    // And c2 must not show c1's parsing state.
    expect(result.current.isParsingMedia).toBe(false);
  });

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

  it("does not refetch over a bucket whose turn is still streaming", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("hello"); });
    act(() => {
      latestStream().submission.onStart();
      latestStream().submission.onAgentUpdate?.({ text: "streaming" });
    });

    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

    mockGetAgentMessages.mockClear();
    rerender({ cid: "c1" });
    await waitFor(() =>
      expect(result.current.messages[result.current.messages.length - 1].text).toBe("streaming"),
    );
    expect(mockGetAgentMessages).not.toHaveBeenCalledWith("c1", undefined);
    expect(result.current.isStreaming).toBe(true);
  });

  it("stops only the conversation on screen", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("hello"); });
    const turn = latestStream();
    act(() => turn.submission.onStart());

    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

    // Stop pressed while looking at c2 must not touch c1's turn.
    act(() => result.current.stopGenerating());
    expect(turn.close).not.toHaveBeenCalled();

    rerender({ cid: "c1" });
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => result.current.stopGenerating());
    expect(turn.close).toHaveBeenCalledTimes(1);
    expect(result.current.isStreaming).toBe(false);
  });

  it("closes live turns when the hook unmounts for good", async () => {
    const { result, unmount } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    await act(async () => { await result.current.sendMessage("hello"); });
    const turn = latestStream();
    act(() => turn.submission.onStart());

    unmount();
    expect(turn.close).toHaveBeenCalledTimes(1);
  });
});

/**
 * Moving the view to a new conversation id must move the turn's state with it.
 *
 * Each turn writes into a bucket keyed by the conversation it started in, and
 * what the caller sees is the bucket of whichever id is current. So pointing
 * the view at a freshly minted id without carrying the bucket over lands on an
 * empty one: the answer is on screen one moment and the pane is blank the next.
 *
 * Task mode is where this bites. The daily stream's last act is a handoff that
 * binds the conversation to a server-minted chat id, and it also suppresses the
 * one history refetch that would otherwise repaint the pane — so nothing brings
 * the content back until the user navigates away and returns.
 *
 * The second test covers what the orphaned bucket does afterwards: it still
 * sits under the id the turn started with, so going back to a new chat finds
 * the previous turn's messages instead of the welcome page.
 */
describe("useAiChat adopts a new conversation id", () => {
  it("keeps the turn on screen when the task handoff binds a real chat id", async () => {
    const { result } = renderChat("new");

    await act(async () => { await result.current.sendMessage("write me a report", null, { taskMode: true }); });
    const turn = latestStream();
    act(() => {
      turn.submission.onStart();
      turn.submission.onAgentUpdate?.({ text: "working on it" });
    });
    expect(result.current.messages.length).toBeGreaterThan(0);

    act(() => turn.submission.onTaskHandoff?.({ session_version_id: "sv-1", chat_id: "c-real" }));

    await waitFor(() => expect(result.current.conversationId).toBe("c-real"));
    expect(result.current.messages.length).toBeGreaterThan(0);
    expect(result.current.messages[result.current.messages.length - 1].text).toBe("working on it");
  });

  it("does not blank a new chat when the reply finishes in the same tick the id is minted", async () => {
    const { result } = renderChat("new");

    await act(async () => { await result.current.sendMessage("blocked keyword"); });
    const turn = latestStream();
    mockGetAgentMessages.mockClear();

    act(() => {
      turn.submission.onStart();
      turn.submission.onCreated?.("c-real", {
        messageId: "42",
        parentMessageId: "",
        sender: "user",
        conversationId: "c-real",
        text: "blocked keyword",
      });
      turn.submission.onAgentUpdate?.({
        text: "cannot answer that",
        category: "agent_answer",
        finalised: true,
        messageId: "43",
      });
      turn.submission.onFinal({
        final: true,
        conversation: { conversationId: "c-real" },
        responseMessage: { messageId: "43", conversationId: "c-real" },
      });
      turn.submission.onEnd();
    });

    await waitFor(() => expect(result.current.conversationId).toBe("c-real"));
    expect(result.current.isLoading).toBe(false);
    expect(mockGetAgentMessages).not.toHaveBeenCalled();
    expect(result.current.messages[result.current.messages.length - 1].text).toBe("cannot answer that");
  });

  it("leaves nothing behind under the id the turn started with", async () => {
    const { result, rerender } = renderChat("new");

    await act(async () => { await result.current.sendMessage("write me a report", null, { taskMode: true }); });
    const turn = latestStream();
    act(() => {
      turn.submission.onStart();
      turn.submission.onAgentUpdate?.({ text: "working on it" });
    });
    act(() => turn.submission.onTaskHandoff?.({ session_version_id: "sv-1", chat_id: "c-real" }));
    await waitFor(() => expect(result.current.conversationId).toBe("c-real"));

    // The view rewrites its own URL to the id the handoff just minted.
    rerender({ cid: "c-real" });

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
describe("task mode owns skill execution", () => {
  it.each([false, true])("sends the mode-scoped skill selection when taskMode=%s", async (taskMode) => {
    mockSelectedSkills = [{ name: "writing" }];
    const { result } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    await act(async () => { await result.current.sendMessage("Use this skill", null, { taskMode }); });
    expect(latestStream().submission.payload).toMatchObject({
      task_mode: taskMode,
      skills: taskMode ? ["writing"] : [],
    });
  });
});

test("an incomplete upload rejects submission before starting a stream", async () => {
  const { result } = renderChat("c1");
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  let accepted;
  await act(async () => {
    accepted = await result.current.sendMessage("Use this file", [{ name: "draft.txt", valid: false }], {
      taskMode: true,
    });
  });
  expect(accepted).toBe(false);
  expect(mockOpenedStreams).toHaveLength(0);
});

describe("conversation knowledge isolation", () => {
  const k1 = [{ id: "101", name: "K1", type: "space" }];
  const k2 = [{ id: "202", name: "K2", type: "space" }];
  const scope = () => latestStream().submission.payload.use_knowledge_base;

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
    expect(scope()).toMatchObject({ knowledge_space_ids: [101] });
    act(() => {
      latestStream().submission.onEnd();
      chat.result.current.setSelectedOrgKbs([]);
    });
    chat.unmount();
    const reopened = renderChat("c1");
    await waitFor(() => expect(reopened.result.current.isLoading).toBe(false));
    expect(reopened.result.current.selectedOrgKbs).toEqual([]);
    await act(async () => { await reopened.result.current.sendMessage("empty selection"); });
    expect(scope()).toMatchObject({ knowledge_space_ids: [], organization_knowledge_ids: [] });
  });

  it("carries the first turn scope into its server id while C2 stays selected", async () => {
    const chat = renderChat("new");
    act(() => chat.result.current.setSelectedOrgKbs(k1));
    await act(async () => { await chat.result.current.sendMessage("first turn"); });
    const first = latestStream();
    chat.rerender({ cid: "c2" });
    await waitFor(() => expect(chat.result.current.isLoading).toBe(false));
    act(() => chat.result.current.setSelectedOrgKbs(k2));
    act(() => first.submission.onFinal({ conversation: { conversationId: "created-c1" } }));
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

    expect(mockOpenedStreams).toHaveLength(1);
    const first = latestStream();
    act(() => {
      first.submission.onCreated("first-chat", {
        ...first.submission.userMessage,
        conversationId: "first-chat",
      });
      if (finishFirst) first.submission.onEnd();
    });
    rerender({ cid: "first-chat", locationKey: "first-rewrite" });
    parkChatAsk({ text: "second question", space: { id: spaceId, name: spaceId } });
    rerender({ cid: "new", locationKey: "second" });

    await waitFor(() => expect(mockOpenedStreams).toHaveLength(2));
    expect(latestStream().submission.payload).toMatchObject({
      conversationId: null,
      use_knowledge_base: { knowledge_space_ids: [Number(spaceId)] },
    });
    expect(result.current.messages[0].text).toBe("second question");
    if (!finishFirst) expect(first.close).not.toHaveBeenCalled();
    rerender({ cid: "new", locationKey: "second-again" });
    expect(mockOpenedStreams).toHaveLength(2);
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
      const chat = useAiChat("new");
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
    await waitFor(() => expect(mockOpenedStreams).toHaveLength(1));
    expect(latestStream().submission.payload).toEqual(
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
    expect(latestStream().submission.userMessage.text).toBe("Count entries");
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
  expect(latestStream().submission.payload.use_knowledge_base.knowledge_space_tag_filters).toEqual({ '12': 7 });
  act(() => latestStream().submission.onEnd());
  await act(async () => { await result.current.regenerate(result.current.messages[result.current.messages.length - 1].messageId); });
  expect(latestStream().submission.payload.use_knowledge_base.knowledge_space_tag_filters).toEqual({ '12': 7 });
  act(() => latestStream().submission.onEnd());
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
  expect(mockOpenedStreams).toHaveLength(0);
  expect(result.current.selectedOrgKbs).toEqual(tagged);
});

test('blocks image sends at the shared entry when neither vision nor image parsing is available', async () => {
  mockBsConfig = { models: [{ id: 1, visual: false }], enable_etl4lm: false };
  const { result } = renderChat('c1');
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  await act(async () => { expect(await result.current.sendMessage('Describe', [{ name: 'image.png', filepath: 'image.png' }])).toBe(false); });
  expect(mockOpenedStreams).toHaveLength(0);
  expect(result.current.messages).toHaveLength(1);
});

test('does not regenerate an image turn with a model that has lost image support', async () => {
  mockBsConfig = { models: [{ id: 1, visual: false }], enable_etl4lm: false };
  mockGetAgentMessages.mockResolvedValue([{ ...historyOf('c1')[0], files: [{ name: 'image.png', filepath: 'image.png' }] }]);
  const { result } = renderChat('c1');
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  await act(async () => { await result.current.regenerate('c1-q'); });
  expect(mockOpenedStreams).toHaveLength(0);
  expect(result.current.messages).toHaveLength(1);
});


describe('revoked knowledge scope submission gate', () => {
    it('keeps the old conversation intact and blocks sending and regenerating', async () => {
        mockKnowledgeBlocked = true;
        const { result } = renderChat('retained');
        await waitFor(() => expect(result.current.messages.length).toBeGreaterThan(0));
        const originalMessages = result.current.messages;
        await act(async () => { expect(await result.current.sendMessage('D6-W')).toBe(false); });
        await act(async () => { await result.current.regenerate('retained-q'); });
        expect(mockOpenedStreams).toHaveLength(0);
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

  it("reports an answer as running while it streams, including after switching away", async () => {
    const { result, rerender } = renderChat("c1");
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    // Sending awaits the department lease before the stream opens.
    await act(async () => { await result.current.sendMessage("hello"); });
    const turn = latestStream();
    act(() => turn.submission.onStart());
    expect(reportRunning).toHaveBeenLastCalledWith(["c1"]);
    rerender({ cid: "c2" });
    await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));
    expect(reportRunning).toHaveBeenLastCalledWith(["c1"]);
    act(() => {
      turn.submission.onFinal({ final: true });
      turn.submission.onEnd();
    });
    expect(reportRunning).toHaveBeenLastCalledWith([]);
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
