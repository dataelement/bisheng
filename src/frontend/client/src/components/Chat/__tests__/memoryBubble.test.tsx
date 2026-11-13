import { render, screen } from "@testing-library/react";
import type { ChatMessage } from "~/api/chatApi";
import AiMessageBubble from "../AiMessageBubble";
import ToolCallDisplay from "../Messages/ToolCallDisplay";

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
// The task-turn panel pulls the linsight stream stack, which is not under test here.
jest.mock("~/components/Linsight/Execution/TaskTurnPanel", () => ({ TaskTurnPanel: () => null }));
jest.mock("~/components/Chat/Messages/Content/Markdown", () => ({
  __esModule: true,
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));
jest.mock("~/components/Chat/Messages/Content/CitationReferencesDrawer", () => ({
  __esModule: true,
  default: ({ actionButtons }: { actionButtons?: React.ReactNode }) => <div>{actionButtons}</div>,
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
jest.mock("~/components/Chat/MemoryNotice", () => ({
  MemoryNotice: ({ flags, messageId }: { flags?: { turn_id: string }; messageId?: string }) =>
    flags ? <div data-testid="memory-notice">{`${flags.turn_id}:${messageId}`}</div> : null,
}));

const answer = (overrides: Partial<ChatMessage>): ChatMessage => ({
  messageId: "101",
  parentMessageId: "100",
  conversationId: "c1",
  sender: "assistant",
  text: "Noted.",
  category: "agent_answer",
  events: [{ type: "text", content: "Noted." }],
  ...overrides,
});

it("mounts the memory notice on an answer that carries memory flags (AC-21, AC-87)", () => {
  render(<AiMessageBubble message={answer({ memory: { turn_id: "t-9", has_write: true, has_attribution: true } })} />);
  expect(screen.getByTestId("memory-notice")).toHaveTextContent("t-9:101");
});

it("mounts no memory notice on an answer without flags (AC-21)", () => {
  render(<AiMessageBubble message={answer({})} />);
  expect(screen.queryByTestId("memory-notice")).toBeNull();
});

it("holds the notice back while the answer is still streaming (AC-21)", () => {
  render(
    <AiMessageBubble
      isLatest
      isStreaming
      message={answer({ memory: { turn_id: "t-9", has_write: true, has_attribution: false } })}
    />,
  );
  expect(screen.queryByTestId("memory-notice")).toBeNull();
});

it("renders a redacted memory tool event as a placeholder without its raw structure (AC-87)", () => {
  const { container } = render(
    <ToolCallDisplay
      toolCall={{
        tool_call_id: "tc1",
        tool_name: "memory_search",
        args: { redacted: true, op: "search", item_ids: ["m-secret-1"] },
        results: { redacted: true, op: "search", item_ids: ["m-secret-1", "m-secret-2"] },
      }}
    />,
  );
  expect(screen.getByText("memory.tool_operation")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/redacted|m-secret|item_ids|search/);
  expect(screen.queryByRole("link")).toBeNull();
});

it("treats any redacted payload as a memory operation, even under another name (AC-87)", () => {
  const { container } = render(
    <ToolCallDisplay
      toolCall={{
        tool_call_id: "tc2",
        tool_name: "unknown_tool",
        args: JSON.stringify({ redacted: true, op: "remember", item_ids: ["m-secret-3"] }),
        results: null,
      }}
    />,
  );
  expect(screen.getByText("memory.tool_operation")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/m-secret|unknown_tool/);
});

it("keeps ordinary tool calls unchanged (AC-87)", () => {
  render(
    <ToolCallDisplay
      toolCall={{ tool_call_id: "tc3", tool_name: "calculator", display_name: "Calculator", args: { a: 1 }, results: "2" }}
    />,
  );
  expect(screen.queryByText("memory.tool_operation")).toBeNull();
  expect(screen.getByText("com_tools_state_tool_done")).toBeInTheDocument();
});
