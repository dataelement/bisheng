import type { AgentEvent } from "~/api/chatApi";
import { ASK_USER_TOOL_NAME } from "~/store/runAskUser";

type ToolCallEvent = Extract<AgentEvent, { type: "tool_call" }>;

/** A vertical block in the rendered transcript. */
export type DisplayBlock =
    | { kind: "group"; events: AgentEvent[] }
    | { kind: "text"; content: string }
    /** A question the run asked the user, with the user's answer. */
    | { kind: "question"; event: ToolCallEvent };

/**
 * Split an ordered AgentEvent[] into display blocks. Consecutive thinking +
 * tool_call events become one "group" block (the deep-thinking wrapper);
 * each text event becomes its own "text" block.
 */
export function groupEventsForDisplay(events: AgentEvent[]): DisplayBlock[] {
    const blocks: DisplayBlock[] = [];
    let current: AgentEvent[] | null = null;

    const flushGroup = () => {
        if (current && current.length > 0) {
            blocks.push({ kind: "group", events: current });
        }
        current = null;
    };

    for (const ev of events) {
        if (ev.type === "text") {
            flushGroup();
            blocks.push({ kind: "text", content: ev.content });
            continue;
        }
        if (ev.type === "tool_call" && ev.tool_name === ASK_USER_TOOL_NAME) {
            // The open question is the card above the input box, not a tool
            // step; once answered it shows as its own question-and-answer block.
            if (ev.results == null || ev.inflight) continue;
            flushGroup();
            blocks.push({ kind: "question", event: ev });
            continue;
        }
        if (current == null) current = [];
        current.push(ev);
    }
    flushGroup();
    return blocks;
}
