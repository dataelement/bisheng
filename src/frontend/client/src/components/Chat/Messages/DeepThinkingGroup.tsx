/**
 * DeepThinkingGroup — renders a contiguous run of thinking + tool_call events
 * as a flat timeline. There is no outer "已深度思考" wrapper anymore: the
 * thinking block and each tool-call card sit at the top level, laid out
 * sequentially, and each node owns its own (collapsed-by-default) toggle.
 *
 * The thinking node surfaces its own live status (正在深度思考… → 已深度思考)
 * via the timing fields computed here from this group's thinking events.
 */
import { memo, useMemo, type FC } from "react";
import type { AgentEvent } from "~/api/chatApi";
import ThinkingContent from "./ThinkingContent";
import ToolCallDisplay from "./ToolCallDisplay";

export interface DeepThinkingGroupProps {
    /** Ordered events in this group — only thinking + tool_call entries. */
    events: AgentEvent[];
    /** True if this group is the currently-open trailing run (message still
     *  streaming, no final answer text yet). Drives the thinking node's
     *  正在/已 status. */
    isStreaming: boolean;
}

type ThinkingEvent = Extract<AgentEvent, { type: "thinking" }>;

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(({ events, isStreaming }) => {
    const thinkingEvents = useMemo(
        () => events.filter((e): e is ThinkingEvent => e.type === "thinking"),
        [events],
    );

    // Concatenated reasoning for the inner ThinkingContent block.
    const reasoning = useMemo(
        () => thinkingEvents.map((e) => e.content).join("\n\n"),
        [thinkingEvents],
    );

    const toolCalls = useMemo(
        () =>
            events.filter(
                (e): e is Extract<AgentEvent, { type: "tool_call" }> =>
                    e.type === "tool_call",
            ),
        [events],
    );

    // Timing for the thinking node: span the earliest start → latest end across
    // this group's thinking segments, with a per-segment duration sum fallback.
    const { startedAt, endedAt, durationMs } = useMemo(() => {
        let start: number | undefined;
        let end: number | undefined;
        let sum = 0;
        for (const e of thinkingEvents) {
            if (e.started_at != null && (start == null || e.started_at < start)) start = e.started_at;
            if (e.ended_at != null && (end == null || e.ended_at > end)) end = e.ended_at;
            sum += e.duration_ms ?? 0;
        }
        return { startedAt: start, endedAt: end, durationMs: sum };
    }, [thinkingEvents]);

    // The reasoning is still "live" only while the group streams AND the last
    // thinking segment hasn't closed (once a tool starts, that segment carries
    // an ended_at and the node settles to "已深度思考").
    const lastThinking = thinkingEvents[thinkingEvents.length - 1];
    const thinkingStreaming = isStreaming && !!lastThinking && lastThinking.ended_at == null;

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            <ThinkingContent
                reasoning={reasoning}
                isStreaming={thinkingStreaming}
                startedAt={startedAt}
                endedAt={endedAt}
                durationMs={durationMs}
            />
            {toolCalls.map((tc, i) => (
                <ToolCallDisplay key={tc.tool_call_id || `tc-${i}`} toolCall={tc} />
            ))}
        </div>
    );
});

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
