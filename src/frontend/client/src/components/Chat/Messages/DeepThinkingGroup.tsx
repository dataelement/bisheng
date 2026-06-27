/**
 * DeepThinkingGroup — renders a contiguous run of thinking + tool_call events
 * as a flat timeline. There is no outer "已深度思考" wrapper anymore: the
 * thinking block and each tool-call card sit at the top level, laid out
 * sequentially, and each node owns its own (collapsed-by-default) toggle.
 */
import { memo, useMemo, type FC } from "react";
import type { AgentEvent } from "~/api/chatApi";
import ThinkingContent from "./ThinkingContent";
import ToolCallDisplay from "./ToolCallDisplay";

export interface DeepThinkingGroupProps {
    /** Ordered events in this group — only thinking + tool_call entries. */
    events: AgentEvent[];
}

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(({ events }) => {
    // Pull thinking content (concat) for the inner ThinkingContent block.
    const reasoning = useMemo(
        () =>
            events
                .filter(
                    (e): e is Extract<AgentEvent, { type: "thinking" }> =>
                        e.type === "thinking",
                )
                .map((e) => e.content)
                .join("\n\n"),
        [events],
    );

    const toolCalls = useMemo(
        () =>
            events.filter(
                (e): e is Extract<AgentEvent, { type: "tool_call" }> =>
                    e.type === "tool_call",
            ),
        [events],
    );

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            <ThinkingContent reasoning={reasoning} />
            {toolCalls.map((tc, i) => (
                <ToolCallDisplay key={tc.tool_call_id || `tc-${i}`} toolCall={tc} />
            ))}
        </div>
    );
});

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
