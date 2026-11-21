/**
 * F004 (T061): how a deep-research turn renders on the conversation page and
 * on a carrier that follows no run events, and the typing cursor of a run that waits.
 */
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import type { ChatMessage } from "~/api/chatApi";
import { useRunStore, type RunEvent } from "~/store/runStore";
import AiMessageBubble from "./AiMessageBubble";
import { RunPageContext } from "./runPageContext";

const mockTaskPanels: Array<{ versionId: string; liveChannel?: boolean }> = [];
const mockMarkdown: Array<{ content: string; showCursor?: boolean }> = [];
const mockErrorCards: unknown[] = [];

jest.mock("~/components/Linsight/Execution/TaskTurnPanel", () => ({
  TaskTurnPanel: (props: { versionId: string; liveChannel?: boolean }) => {
    mockTaskPanels.push({ versionId: props.versionId, liveChannel: props.liveChannel });
    return null;
  },
}));
const mockQueue: { position: number | null; calls: Array<[string | undefined, boolean]> } = { position: null, calls: [] };
jest.mock("~/hooks/useRunQueuePosition", () => ({
  useRunQueuePosition: (conversationId: string | undefined, enabled: boolean) => {
    mockQueue.calls.push([conversationId, enabled]);
    return enabled ? mockQueue.position : null;
  },
}));
jest.mock("~/components/Linsight/Execution/QueueCard", () => ({
  QueueCard: (props: { position: number }) => <div data-testid="queue-card">{props.position}</div>,
}));
jest.mock("~/components/Chat/Messages/Content/Markdown", () => ({
  __esModule: true,
  default: (props: { content: string; showCursor?: boolean }) => {
    mockMarkdown.push({ content: props.content, showCursor: props.showCursor });
    return null;
  },
}));
jest.mock("./MessageTime", () => ({ MessageTime: () => null }));
jest.mock("~/components/Chat/Messages/DeepThinkingGroup", () => ({ __esModule: true, default: () => null }));
jest.mock("~/components/Chat/Messages/ThinkingContent", () => ({ __esModule: true, default: () => null }));
jest.mock("~/components/Chat/Messages/Content/CitationReferencesDrawer", () => ({ __esModule: true, default: () => null }));
jest.mock("~/components/Chat/Messages/Content/SearchWebUrls", () => ({ __esModule: true, default: () => null }));
jest.mock("~/components/ui/Avatar", () => ({ Avatar: () => null, AvatarImage: () => null, AvatarName: () => null }));
jest.mock("~/components/Voice/TextToSpeechButton", () => ({ TextToSpeechButton: () => null }));
jest.mock("~/components/ChatErrorCard", () => ({
  ChatErrorCard: (props: unknown) => {
    mockErrorCards.push(props);
    return null;
  },
  isTransientErrorType: () => false,
}));
jest.mock("~/components/Chat/MessageFeedbackButtons", () => ({ MessageFeedbackButtons: () => null }));
jest.mock("~/components/Chat/MemoryNotice", () => ({ MemoryNotice: () => null }));
jest.mock("~/api/apps", () => ({ likeChatApi: jest.fn(), disLikeCommentApi: jest.fn() }));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: { assistantIcon: {} } }) }));
jest.mock("~/hooks", () => ({ useAuthContext: () => ({ user: { id: 1 } }), useLocalize: () => (key: string) => key }));
jest.mock("~/hooks/useMessageSelection", () => ({ useMessageSelection: () => ({ isActiveForChat: () => false }) }));
jest.mock("~/components/Chat/MessageSelection", () => ({ ExportSelectionButton: () => null, MessageCheckbox: () => null }));
jest.mock("~/utils", () => ({ cn: (...parts: unknown[]) => parts.filter((p) => typeof p === "string").join(" ") }));
jest.mock("~/components/Chat/MessageCopyButton", () => ({ CopyButton: () => null }));
jest.mock("~/components/Chat/attachments/MediaAttachmentChip", () => ({ MediaAttachmentChip: () => null, isMediaChipFile: () => false }));
jest.mock("~/components/Chat/attachments/ChatHistoryFileRow", () => ({ ChatHistoryFileRow: () => null }));
jest.mock("~/components/Chat/attachments/GeneratedFileLink", () => ({ renderGeneratedFileLink: () => () => null }));
jest.mock("~/components/ui/icon/File/FileIcon", () => ({ isImageFileName: () => false }));
jest.mock("~/components/Chat/Messages/Content/MessageImage", () => ({ MessageImage: () => null }));
jest.mock("~/components/ServiceBusyNotice", () => ({ ServiceBusyNotice: () => null }));
jest.mock("./RunMessageNotes", () => ({
  MessageQueuedNote: () => <div data-testid="message-queued" />,
  RunStoppedNote: () => <div data-testid="message-stopped" />,
}));
jest.mock("lucide-react", () => ({ BotIcon: () => null, ChevronLeftIcon: () => null, ChevronRightIcon: () => null }));

const taskRow = (extra: Partial<ChatMessage> = {}): ChatMessage => ({
  text: "",
  sender: "AI",
  isCreatedByUser: false,
  messageId: "t1",
  parentMessageId: "q1",
  conversationId: "c1",
  error: false,
  category: "task",
  linsightSessionVersionId: "sv1",
  ...extra,
});

const renderBubble = (message: ChatMessage, runPage: boolean) => {
  const wrap = (node: ReactNode) => <RunPageContext.Provider value={runPage}>{node}</RunPageContext.Provider>;
  return render(wrap(<AiMessageBubble message={message} isLatest />));
};
const emit = (event: Record<string, unknown>, id: string) =>
  act(() => {
    useRunStore.getState().applyEvent("c1", { run_id: "r1", data: {}, ...event } as RunEvent, id);
  });

beforeEach(() => {
  mockTaskPanels.length = 0;
  mockMarkdown.length = 0;
  mockErrorCards.length = 0;
  act(() => useRunStore.setState({ conversations: {} }));
  mockQueue.position = null;
  mockQueue.calls = [];
});

describe("carrier that follows no run events (share view)", () => {
  it("renders a task turn in the inline task panel with its live channel", () => {
    renderBubble(taskRow(), false);
    expect(mockTaskPanels).toEqual([{ versionId: "sv1", liveChannel: true }]);
    expect(mockMarkdown).toHaveLength(0);
  });
});

describe("conversation page", () => {
  it("shows a stored task turn for review, without the live channel", () => {
    renderBubble(taskRow(), true);
    expect(mockTaskPanels).toEqual([{ versionId: "sv1", liveChannel: false }]);
  });

  it("renders the task turn in progress with the shared timeline, not the task panel", () => {
    emit({ type: "run_started" }, "1-1");
    renderBubble(taskRow({ liveRunId: "r1", text: "partial answer" }), true);
    expect(mockTaskPanels).toHaveLength(0);
    expect(mockMarkdown[mockMarkdown.length - 1]).toEqual({ content: "partial answer", showCursor: true });
  });

  it("hides the typing cursor while the run waits for the user's answer", () => {
    emit({ type: "run_started" }, "1-1");
    renderBubble(taskRow({ liveRunId: "r1", text: "partial answer", category: "agent_answer" }), true);
    expect(mockMarkdown[mockMarkdown.length - 1].showCursor).toBe(true);
    emit({ type: "ask_user", data: { call_id: "k1", questions: [{ question: "which?" }] } }, "1-2");
    expect(mockMarkdown[mockMarkdown.length - 1].showCursor).toBe(false);
    emit({ type: "ask_user_answered", data: { call_id: "k1" } }, "1-3");
    expect(mockMarkdown[mockMarkdown.length - 1].showCursor).toBe(true);
  });
});

describe("queue position of a deep-research run (AC-36)", () => {
  it("shows the position while the run in progress has produced nothing", () => {
    mockQueue.position = 3;
    emit({ type: "run_started" }, "1-1");
    const view = renderBubble(taskRow({ liveRunId: "r1" }), true);
    expect(view.getByTestId("queue-card").textContent).toBe("3");
    expect(mockQueue.calls[mockQueue.calls.length - 1]).toEqual(["c1", true]);
  });

  it("stops asking once the run writes anything", () => {
    mockQueue.position = 3;
    emit({ type: "run_started" }, "1-1");
    const view = renderBubble(taskRow({ liveRunId: "r1" }), true);
    emit({ type: "thinking", data: { text: "thinking", call_id: "t1" } }, "1-2");
    expect(view.queryByTestId("queue-card")).toBeNull();
    expect(mockQueue.calls[mockQueue.calls.length - 1]).toEqual(["c1", false]);
  });

  it("never asks for a direct answer or a stored deep-research turn", () => {
    mockQueue.position = 3;
    emit({ type: "run_started" }, "1-1");
    renderBubble(taskRow({ liveRunId: "r1", category: "agent_answer" }), true);
    renderBubble(taskRow(), true);
    expect(mockQueue.calls.every(([, enabled]) => enabled === false)).toBe(true);
  });
});

describe("stopped answer (design §7 item 2)", () => {
  const answer = (extra: Partial<ChatMessage> = {}): ChatMessage =>
    taskRow({ category: "agent_answer", linsightSessionVersionId: undefined, messageId: "a1", ...extra });
  const text = (content: string) => ({ events: [{ type: "text" as const, content }], text: content });

  it("shows the content written so far with the neutral stopped note, not the error style", () => {
    const view = renderBubble(answer({ ...text("so far"), stopped: true }), true);
    expect(mockMarkdown[mockMarkdown.length - 1].content).toBe("so far");
    expect(view.queryByTestId("message-stopped")).not.toBeNull();
    expect(mockErrorCards).toHaveLength(0);
  });

  it("shows only the note when the run was stopped before it wrote anything", () => {
    const view = renderBubble(answer({ stopped: true, events: [] }), true);
    expect(view.queryByTestId("message-stopped")).not.toBeNull();
    expect(mockMarkdown).toHaveLength(0);
    expect(mockErrorCards).toHaveLength(0);
  });

  it("keeps the error style for a run torn down without a terminal event", () => {
    const view = renderBubble(answer({ error: true, errorText: "stream interrupted", events: [] }), true);
    expect(view.queryByTestId("message-stopped")).toBeNull();
    expect(mockErrorCards).toHaveLength(1);
  });

  it("shows no note on an ordinary answer", () => {
    const view = renderBubble(answer(text("done")), true);
    expect(view.queryByTestId("message-stopped")).toBeNull();
  });
});

// 114, 2026-11-18: a failed direct answer showed the deep-research card.
describe("failed direct answer", () => {
  const failed: Partial<ChatMessage> = {
    category: "agent_answer", linsightSessionVersionId: undefined, messageId: "a1", events: [],
    error: true, errorCode: 11091, errorType: "chat_unknown", errorDetail: "ValueError: boom", referenceId: "run-1",
  };

  it.each([
    ["frozen from the live run", { ...failed, errorText: "" }],
    ["reloaded from the history", failed],
  ])("is a chat failure card with the detail and the reference, %s", (_name, row) => {
    renderBubble(taskRow(row), true);
    expect(mockTaskPanels).toHaveLength(0);
    expect(mockErrorCards).toHaveLength(1);
    expect(mockErrorCards[0]).toMatchObject({
      surface: "chat", hideHint: true, errorType: "chat_unknown", errorCode: 11091,
      detail: "ValueError: boom", referenceId: "run-1",
    });
    // No generic line stands in for the detail.
    expect((mockErrorCards[0] as { fallbackMessage?: string }).fallbackMessage).toBeFalsy();
  });
});

describe("queued mark of a user message", () => {
  const question = (extra: Partial<ChatMessage> = {}): ChatMessage =>
    taskRow({ category: "question", isCreatedByUser: true, sender: "User", messageId: "m1", text: "more", linsightSessionVersionId: undefined, ...extra });

  it("clears when the relay run reads the message", () => {
    emit({ type: "run_started" }, "2-1");
    emit({ type: "steer_accepted", data: { message_id: "m1" } }, "2-2");
    emit({ type: "run_finished" }, "2-3");
    const view = renderBubble(question(), true);
    expect(view.queryByTestId("message-queued")).not.toBeNull();
    emit({ type: "run_started", run_id: "r2", data: { relay: true } }, "2-4");
    expect(view.queryByTestId("message-queued")).not.toBeNull();
    emit({ type: "steer_read", run_id: "r2", data: { message_id: "m1" } }, "2-5");
    expect(view.queryByTestId("message-queued")).toBeNull();
  });

  it("is found by the inbox id on a row loaded from the history", () => {
    emit({ type: "run_started" }, "2-1");
    emit({ type: "steer_accepted", data: { message_id: "m1" } }, "2-2");
    const view = renderBubble(question({ messageId: "8801", steerMessageId: "m1" }), true);
    expect(view.queryByTestId("message-queued")).not.toBeNull();
  });
});
