import type { AgentEvent } from "~/api/chatApi";

/** A vertical block in the rendered transcript. */
export type DisplayBlock =
    | { kind: "group"; events: AgentEvent[] }
    | { kind: "text"; content: string };

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
        if (current == null) current = [];
        current.push(ev);
    }
    flushGroup();
    return blocks;
}
