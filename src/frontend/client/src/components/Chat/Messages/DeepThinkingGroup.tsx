/**
 * DeepThinkingGroup — outer collapsible wrapper around a contiguous run of
 * thinking + tool_call events. Header reads "已深度思考" once the run is closed
 * by a following text block (or stream end), or "正在深度思考…" while still
 * open. Collapsing the wrapper hides everything inside, including any inner
 * ThinkingContent state.
 *
 * **No duration (2026-08-13).** The header used to end in "（用时 N 秒）", driven
 * by a 100ms ticker. A live counter promises the number matters, and for model
 * reasoning it does not — it only measures how long you have waited, with no
 * denominator to reason against, at a precision that implies the work should
 * have been quick. On a long run it made the product look broken rather than
 * busy. Liveness is carried by the streaming glyph and the reasoning text.
 * Removed here in lockstep with task mode's GroupHeaderLabel, which the two
 * surfaces are deliberately isomorphic with — see Linsight/Execution/
 * GroupHeaderLabel.tsx for the full reasoning.
 */
import { Outlined } from "bisheng-icons";
import {
    memo,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type FC,
    type MouseEvent,
} from "react";
import type { AgentEvent } from "~/api/chatApi";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import ThinkingContent from "./ThinkingContent";
import ToolCallDisplay from "./ToolCallDisplay";

const BUTTON_STYLES = {
    base: "group flex w-fit items-center gap-1 text-sm font-medium leading-[22px] text-text-1",
    icon: "shrink-0 transform-gpu text-text-3 transition-transform duration-200",
} as const;

export interface DeepThinkingGroupProps {
    /** Ordered events in this group — only thinking + tool_call entries. */
    events: AgentEvent[];
    /** True if this group is the currently-open trailing run. */
    isStreaming: boolean;
}

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(
    ({ events, isStreaming }) => {
        const localize = useLocalize();
        // Open while the run is live so the user can watch it; closed for
        // already-finished groups (history rows mount with isStreaming false).
        const [isExpanded, setIsExpanded] = useState(isStreaming);

        // Auto-collapse the moment the run finishes — i.e. the main answer
        // starts streaming and isStreaming flips false — so focus moves to the
        // answer body without a manual click. Manual toggling stays intact
        // afterward since we only react to the streaming → done falling edge.
        const wasStreamingRef = useRef(isStreaming);
        useEffect(() => {
            if (wasStreamingRef.current && !isStreaming) {
                setIsExpanded(false);
            }
            wasStreamingRef.current = isStreaming;
        }, [isStreaming]);

        // Shared with task mode on purpose: the two 深度思考 surfaces are
        // explicitly isomorphic, so one key pair keeps their wording from
        // drifting apart. (The `_compact` name is historical — it was the
        // duration-free variant back when a duration variant existed.)
        const label = localize(
            isStreaming ? "com_linsight_deep_thinking_running_compact" : "com_linsight_deep_thinking_done_compact",
        );

        const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            setIsExpanded((prev) => !prev);
        }, []);

        // Walk the events in arrival order, folding only ADJACENT thinking
        // fragments into one passage. The wire and the DB already interleave
        // thinking and tool calls truthfully (the backend closes the open
        // thinking segment before every tool call), so the render must not
        // regroup them: reasoning that happened after a search belongs below
        // that search, not merged into the block above it. Mirrors task mode's
        // DeepStepGroup.buildSegments.
        const segments = useMemo(() => {
            type Segment =
                | { kind: "thinking"; key: string; content: string }
                | { kind: "tool"; key: string; toolCall: Extract<AgentEvent, { type: "tool_call" }> };
            const out: Segment[] = [];
            events.forEach((ev, i) => {
                if (ev.type === "thinking") {
                    // A just-opened live segment has no text yet — skip it so the
                    // connector chain never points at a row that renders nothing.
                    if (!ev.content) return;
                    const last = out[out.length - 1];
                    if (last?.kind === "thinking") {
                        // Adjacent rounds are distinct closed passages (unlike task
                        // mode's per-frame chunks), so a paragraph break is right.
                        last.content += `\n\n${ev.content}`;
                    } else {
                        out.push({ kind: "thinking", key: `think-${i}`, content: ev.content });
                    }
                } else if (ev.type === "tool_call") {
                    out.push({ kind: "tool", key: ev.tool_call_id || `tc-${i}`, toolCall: ev });
                }
            });
            return out;
        }, [events]);

        return (
            <div className="flex w-full min-w-0 flex-col gap-3">
                <button
                    type="button"
                    onClick={handleClick}
                    className={cn(BUTTON_STYLES.base, isStreaming && "animate-pulse")}
                >
                    <span>{label}</span>
                    <Outlined.Down
                        size={16}
                        className={cn(BUTTON_STYLES.icon, !isExpanded && "-rotate-90")}
                    />
                </button>
                <div
                    className="grid transition-all duration-300 ease-out"
                    style={{ gridTemplateRows: isExpanded ? "1fr" : "0fr" }}
                >
                    <div className="overflow-hidden flex flex-col gap-2">
                        {segments.map((seg, i) => {
                            // Connector runs to the next row, whatever kind it is.
                            const hasNext = i < segments.length - 1;
                            return seg.kind === "thinking" ? (
                                <ThinkingContent
                                    key={seg.key}
                                    reasoning={seg.content}
                                    showConnector={hasNext}
                                />
                            ) : (
                                <ToolCallDisplay
                                    key={seg.key}
                                    toolCall={seg.toolCall}
                                    showConnector={hasNext}
                                />
                            );
                        })}
                    </div>
                </div>
            </div>
        );
    },
);

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
