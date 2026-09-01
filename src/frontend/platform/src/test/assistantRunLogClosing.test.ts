import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { ChatMessageType } from "@/types/chat";
import { beforeEach, describe, expect, it } from "vitest";

type RunLogCard = ChatMessageType & { interrupted?: boolean };

const asMessages = (rows: unknown[]) => rows as ChatMessageType[];
const readMessages = () => useMessageStore.getState().messages as RunLogCard[];

/**
 * A tool card closes only when its own end frame arrives. One got lost — the
 * knowledge retriever answered with objects the frame could not serialize — and
 * the card kept spinning after the session had ended, with nothing persisted to
 * recover it from. Closing the session must settle whatever is still open.
 */
describe("dangling run-log cards at session close", () => {
  const runLog = (id: string, end: boolean) => ({
    id,
    category: "knowledge",
    end,
    message: { tool_key: "4138" },
    thought: "",
  });

  beforeEach(() => {
    useMessageStore.setState({ messages: [], hisMessages: [] });
  });

  it("settles a tool card whose end frame never arrived", () => {
    useMessageStore.setState({ messages: asMessages([runLog("a", true), runLog("b", false)]) });

    useMessageStore.getState().closeDanglingRunLogs();

    const [settled, interrupted] = readMessages();
    expect(settled.interrupted).toBeUndefined();
    // Marked, not silently ticked: it never earned a success icon.
    expect(interrupted.end).toBe(true);
    expect(interrupted.interrupted).toBe(true);
  });

  it("leaves the streaming answer alone", () => {
    const answer = { id: "answer", category: "answer", end: false, message: "", thought: "" };
    useMessageStore.setState({ messages: asMessages([answer]) });

    useMessageStore.getState().closeDanglingRunLogs();

    expect(readMessages()[0].end).toBe(false);
  });

  it("does not touch the list when every card is already closed", () => {
    const messages = asMessages([runLog("a", true)]);
    useMessageStore.setState({ messages });

    useMessageStore.getState().closeDanglingRunLogs();

    expect(useMessageStore.getState().messages).toBe(messages);
  });
});
