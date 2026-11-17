/**
 * F004 (T061): how the conversation page renders a deep-research turn on each
 * side of the tenant switch, and the typing cursor of a run that waits.
 */
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import type { ChatMessage } from "~/api/chatApi";
import { useRunStore, type RunEvent } from "~/store/runStore";
import AiMessageBubble from "./AiMessageBubble";
import { UnifiedRuntimeContext } from "./unifiedRuntimeContext";

const mockTaskPanels: Array<{ versionId: string; liveChannel?: boolean }> = [];
const mockMarkdown: Array<{ content: string; showCursor?: boolean }> = [];

jest.mock("~/components/Linsight/Execution/TaskTurnPanel", () => ({
  TaskTurnPanel: (props: { versionId: string; liveChannel?: boolean }) => {
    mockTaskPanels.push({ versionId: props.versionId, liveChannel: props.liveChannel });
    return null;
  },
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
jest.mock("~/components/ChatErrorCard", () => ({ ChatErrorCard: () => null, isTransientErrorType: () => false }));
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

const renderBubble = (message: ChatMessage, unified: boolean) => {
  const wrap = (node: ReactNode) => <UnifiedRuntimeContext.Provider value={unified}>{node}</UnifiedRuntimeContext.Provider>;
  return render(wrap(<AiMessageBubble message={message} isLatest />));
};
const emit = (event: Record<string, unknown>, id: string) =>
  act(() => {
    useRunStore.getState().applyEvent("c1", { run_id: "r1", data: {}, ...event } as RunEvent, id);
  });

beforeEach(() => {
  mockTaskPanels.length = 0;
  mockMarkdown.length = 0;
  act(() => useRunStore.setState({ conversations: {} }));
});

describe("tenant switch off", () => {
  it("renders a task turn in the inline task panel with its live channel", () => {
    renderBubble(taskRow(), false);
    expect(mockTaskPanels).toEqual([{ versionId: "sv1", liveChannel: true }]);
    expect(mockMarkdown).toHaveLength(0);
  });
});

describe("tenant switch on", () => {
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
