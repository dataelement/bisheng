import { createMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { ChatMessageType } from "@/types/chat";
import { beforeEach, describe, expect, it } from "vitest";

const store = createMessageStore();
type RunLogCard = ChatMessageType & { interrupted?: boolean };

const asMessages = (rows: unknown[]) => rows as ChatMessageType[];
const readMessages = () => store.getState().messages as RunLogCard[];

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
    store.setState({ messages: [], hisMessages: [] });
  });

  it("settles a tool card whose end frame never arrived", () => {
    store.setState({ messages: asMessages([runLog("a", true), runLog("b", false)]) });

    store.getState().closeDanglingRunLogs();

    const [settled, interrupted] = readMessages();
    expect(settled.interrupted).toBeUndefined();
    // Marked, not silently ticked: it never earned a success icon.
    expect(interrupted.end).toBe(true);
    expect(interrupted.interrupted).toBe(true);
  });

  it("leaves the streaming answer alone", () => {
    const answer = { id: "answer", category: "answer", end: false, message: "", thought: "" };
    store.setState({ messages: asMessages([answer]) });

    store.getState().closeDanglingRunLogs();

    expect(readMessages()[0].end).toBe(false);
  });

  it("does not touch the list when every card is already closed", () => {
    const messages = asMessages([runLog("a", true)]);
    store.setState({ messages });

    store.getState().closeDanglingRunLogs();

    expect(store.getState().messages).toBe(messages);
  });
});
