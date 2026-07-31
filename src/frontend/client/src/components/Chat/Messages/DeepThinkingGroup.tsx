/**
 * DeepThinkingGroup — renders a contiguous run of thinking + tool_call events
 * as a flat timeline. There is no outer "已深度思考" wrapper anymore: the
 * thinking blocks and each tool-call card sit at the top level, laid out
 * sequentially, and each node owns its own (collapsed-by-default) toggle.
 *
 * Order is the event order. The wire and the DB already interleave thinking
 * and tool calls truthfully (the backend closes the open thinking segment
 * before every tool call), so the render must not regroup them: reasoning
 * that happened after a search belongs below that search, not merged into the
 * block above it. Only ADJACENT thinking fragments fold into one passage —
 * task mode's DeepStepGroup algorithm.
 *
 * Each thinking node surfaces its own live status (正在深度思考… → 已深度思考);
 * only the trailing segment of a still-streaming run can be live.
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

type ThinkingSegment = {
    kind: "thinking";
    key: string;
    content: string;
    startedAt?: number;
    endedAt?: number;
    durationMs: number;
    /** ended_at of the segment's last underlying event — open means live. */
    closed: boolean;
};
type ToolSegment = {
    kind: "tool";
    key: string;
    toolCall: Extract<AgentEvent, { type: "tool_call" }>;
};
type Segment = ThinkingSegment | ToolSegment;

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(({ events, isStreaming }) => {
    const segments = useMemo<Segment[]>(() => {
        const out: Segment[] = [];
        events.forEach((ev, i) => {
            if (ev.type === "thinking") {
                // A just-opened live segment has no text yet — skip it until the
                // first token lands so no empty node flashes into the timeline.
                if (!ev.content) return;
                const last = out[out.length - 1];
                if (last?.kind === "thinking") {
                    // Adjacent rounds are distinct closed passages (unlike task
                    // mode's per-frame chunks), so a paragraph break is right.
                    last.content += `\n\n${ev.content}`;
                    if (ev.started_at != null && (last.startedAt == null || ev.started_at < last.startedAt)) {
                        last.startedAt = ev.started_at;
                    }
                    if (ev.ended_at != null && (last.endedAt == null || ev.ended_at > last.endedAt)) {
                        last.endedAt = ev.ended_at;
                    }
                    last.durationMs += ev.duration_ms ?? 0;
                    last.closed = ev.ended_at != null;
                } else {
                    out.push({
                        kind: "thinking",
                        key: `think-${i}`,
                        content: ev.content,
                        startedAt: ev.started_at,
                        endedAt: ev.ended_at,
                        durationMs: ev.duration_ms ?? 0,
                        closed: ev.ended_at != null,
                    });
                }
            } else if (ev.type === "tool_call") {
                out.push({ kind: "tool", key: ev.tool_call_id || `tc-${i}`, toolCall: ev });
            }
        });
        return out;
    }, [events]);

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            {segments.map((seg, i) =>
                seg.kind === "thinking" ? (
                    <ThinkingContent
                        key={seg.key}
                        reasoning={seg.content}
                        // Live only for the run's trailing segment while it is
                        // still open; anything earlier has settled by definition.
                        isStreaming={isStreaming && i === segments.length - 1 && !seg.closed}
                        startedAt={seg.startedAt}
                        endedAt={seg.endedAt}
                        durationMs={seg.durationMs}
                    />
                ) : (
                    <ToolCallDisplay key={seg.key} toolCall={seg.toolCall} />
                ),
            )}
        </div>
    );
});

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
