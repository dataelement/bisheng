/**
 * F004 T048: the mark under a message sent while a run was busy (AC-13/AC-14),
 * and the streaming state of the live answer row once it is no longer last.
 */
import { act, render, screen } from "@testing-library/react";
import type { ChatMessage } from "~/api/chatApi";
import { useRunStore } from "~/store/runStore";
import AiMessageBubble from "../AiMessageBubble";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ user: { id: 1, username: "alice" } }),
}));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: undefined }) }));
jest.mock("~/hooks/useMessageSelection", () => ({ useMessageSelection: () => ({ isActiveForChat: () => false }) }));
jest.mock("~/components/Chat/MessageSelection", () => ({
  ExportSelectionButton: () => null,
  MessageCheckbox: () => null,
}));
jest.mock("~/components/Linsight/Execution/TaskTurnPanel", () => ({ TaskTurnPanel: () => null }));
jest.mock("~/components/Chat/Messages/Content/Markdown", () => ({
  __esModule: true,
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));
jest.mock("~/components/Chat/Messages/Content/CitationReferencesDrawer", () => ({
  __esModule: true,
  default: ({ actionButtons }: { actionButtons?: React.ReactNode }) => <div data-testid="answer-actions">{actionButtons}</div>,
}));
jest.mock("~/components/Voice/TextToSpeechButton", () => ({ TextToSpeechButton: () => null }));
jest.mock("~/components/Chat/MessageFeedbackButtons", () => ({ MessageFeedbackButtons: () => null }));
jest.mock("~/components/Chat/MessageCopyButton", () => ({ CopyButton: () => null }));
jest.mock("~/components/Chat/attachments/ChatHistoryFileRow", () => ({ ChatHistoryFileRow: () => null }));
jest.mock("~/components/Chat/attachments/MediaAttachmentChip", () => ({
  MediaAttachmentChip: () => null,
  isMediaChipFile: () => false,
}));
jest.mock("~/components/Chat/Messages/Content/MessageImage", () => ({ MessageImage: () => null }));
jest.mock("~/components/Chat/MemoryNotice", () => ({ MemoryNotice: () => null }));

const CID = "c1";
const question = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  messageId: "201",
  parentMessageId: "200",
  conversationId: CID,
  sender: "User",
  text: "Change step 3 to slides",
  isCreatedByUser: true,
  ...overrides,
});
const event = (type: string, data: Record<string, unknown> = {}) =>
  ({ type, data, run_id: "r1", ts: 1 }) as Parameters<ReturnType<typeof useRunStore.getState>["applyEvent"]>[1];

beforeEach(() => {
  act(() => useRunStore.getState().resetConversation(CID));
});

it("shows the queued mark under a message the run has not read yet (AC-13)", () => {
  act(() => {
    useRunStore.getState().applyEvent(CID, event("run_started"));
    useRunStore.getState().applySendResult(CID, { run_id: "r1", disposition: "queued", message_id: "201", conversation_id: CID });
  });
  render(<AiMessageBubble message={question()} />);
  expect(screen.getByTestId("message-queued")).toHaveTextContent("dshChat.messageQueued");
});

it("removes the mark once the agent read the message and shows nothing in its place (AC-14)", () => {
  act(() => {
    useRunStore.getState().applyEvent(CID, event("run_started"));
    useRunStore.getState().applyEvent(CID, event("steer_accepted", { message_id: "201" }));
  });
  render(<AiMessageBubble message={question()} />);
  expect(screen.getByTestId("message-queued")).toBeInTheDocument();
  act(() => useRunStore.getState().applyEvent(CID, event("steer_read", { message_id: "201" })));
  expect(screen.queryByTestId("message-queued")).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
});

it("shows no mark on other messages or with an empty store (switch off)", () => {
  const view = render(<AiMessageBubble message={question()} />);
  expect(screen.queryByTestId("message-queued")).toBeNull();
  act(() => useRunStore.getState().applySendResult(CID, { run_id: "r1", disposition: "queued", message_id: "999", conversation_id: CID }));
  view.rerender(<AiMessageBubble message={question()} />);
  expect(screen.queryByTestId("message-queued")).toBeNull();
});

const answer = (overrides: Partial<ChatMessage>): ChatMessage => ({
  messageId: "run:r1",
  parentMessageId: "200",
  conversationId: CID,
  sender: "assistant",
  text: "Working on it",
  category: "agent_answer",
  events: [{ type: "text", content: "Working on it" }],
  ...overrides,
});

it("keeps the live answer row in its streaming state when it is no longer the last row", () => {
  render(<AiMessageBubble isLatest={false} isStreaming={false} message={answer({ liveRunId: "r1" })} />);
  expect(screen.queryByTestId("answer-actions")).toBeNull();
});

it("shows the actions of an answer row without liveRunId as before", () => {
  render(<AiMessageBubble isLatest={false} isStreaming={false} message={answer({ messageId: "202" })} />);
  expect(screen.getByTestId("answer-actions")).toBeInTheDocument();
});
