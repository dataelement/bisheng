/**
 * DeepThinkingGroup — outer collapsible wrapper around a contiguous run of
 * thinking + tool_call events. Header reads "已深度思考（用时 N 秒）" once
 * the run is closed by a following text block (or stream end), or
 * "正在深度思考（已用 N 秒）..." while still open. Collapsing the wrapper
 * hides everything inside, including any inner ThinkingContent state.
 */
import { ChevronDown } from "lucide-react";
import {
    memo,
    useCallback,
    useEffect,
    useMemo,
    useState,
    type FC,
    type MouseEvent,
} from "react";
import type { AgentEvent } from "~/api/chatApi";
import { cn } from "~/utils";
import ThinkingContent from "./ThinkingContent";
import ToolCallDisplay from "./ToolCallDisplay";

const BUTTON_STYLES = {
    base: "group flex w-fit items-center justify-center py-2 text-sm leading-[18px] font-medium",
    icon: "icon-sm ml-1.5 transform-gpu text-text-primary transition-transform duration-200",
} as const;

export interface DeepThinkingGroupProps {
    /** Ordered events in this group — only thinking + tool_call entries. */
    events: AgentEvent[];
    /** True if this group is the currently-open trailing run. */
    isStreaming: boolean;
}

function formatSeconds(ms: number): string {
    if (!ms || ms <= 0) return "0";
    const sec = ms / 1000;
    return sec < 10 ? sec.toFixed(1) : Math.round(sec).toString();
}

/** Pick the earliest started_at across events; fall back to undefined. */
function groupStart(events: AgentEvent[]): number | undefined {
    let earliest: number | undefined;
    for (const ev of events) {
        if (ev.type === "thinking" || ev.type === "tool_call") {
            if (ev.started_at != null && (earliest == null || ev.started_at < earliest)) {
                earliest = ev.started_at;
            }
        }
    }
    return earliest;
}

/** Pick the latest ended_at across events. */
function groupEnd(events: AgentEvent[]): number | undefined {
    let latest: number | undefined;
    for (const ev of events) {
        if (ev.type === "thinking" || ev.type === "tool_call") {
            if (ev.ended_at != null && (latest == null || ev.ended_at > latest)) {
                latest = ev.ended_at;
            }
        }
    }
    return latest;
}

/** Fallback: sum duration_ms when wall-clock fields aren't on legacy rows. */
function durationFallback(events: AgentEvent[]): number {
    let sum = 0;
    for (const ev of events) {
        if (ev.type === "thinking" || ev.type === "tool_call") {
            sum += ev.duration_ms ?? 0;
        }
    }
    return sum;
}

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(
    ({ events, isStreaming }) => {
        const [isExpanded, setIsExpanded] = useState(true);

        const start = groupStart(events);
        const end = groupEnd(events);

        // Live-tick while streaming so the header counter advances every 100ms.
        const [tick, setTick] = useState(0);
        useEffect(() => {
            if (!isStreaming) return;
            const id = window.setInterval(() => setTick((t) => t + 1), 100);
            return () => window.clearInterval(id);
        }, [isStreaming]);

        const elapsedMs = (() => {
            if (start == null) return durationFallback(events);
            // For closed groups with no end_at, fall back to the per-event sum
            // so the label doesn't creep upward against Date.now().
            if (!isStreaming && end == null) return durationFallback(events);
            const stop = isStreaming ? Date.now() : end!;
            return Math.max(0, stop - start);
        })();
        // `tick` is read here so the IIFE re-runs on every interval render.
        void tick;

        const label = (() => {
            // Hide the duration entirely when it's 0 — happens on legacy
            // history rows (no started_at/ended_at/duration_ms) and the
            // brief moment before any tick lands.
            const showDuration = elapsedMs > 0;
            if (isStreaming) {
                return showDuration
                    ? `正在深度思考（已用 ${formatSeconds(elapsedMs)} 秒）...`
                    : `正在深度思考...`;
            }
            return showDuration
                ? `已深度思考（用时 ${formatSeconds(elapsedMs)} 秒）`
                : `已深度思考`;
        })();

        const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            setIsExpanded((prev) => !prev);
        }, []);

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
            <>
                <button
                    type="button"
                    onClick={handleClick}
                    className={cn(BUTTON_STYLES.base, isStreaming && "animate-pulse")}
                >
                    <span>{label}</span>
                    <ChevronDown
                        className={cn(BUTTON_STYLES.icon, isExpanded && "rotate-180")}
                    />
                </button>
                <div
                    className="grid transition-all duration-300 ease-out"
                    style={{ gridTemplateRows: isExpanded ? "1fr" : "0fr" }}
                >
                    <div className="overflow-hidden">
                        <ThinkingContent
                            reasoning={reasoning}
                            showConnector={!!reasoning && toolCalls.length > 0}
                        />
                        {toolCalls.map((tc, i) => (
                            <ToolCallDisplay
                                key={tc.tool_call_id || `tc-${i}`}
                                toolCall={tc}
                                showConnector={i < toolCalls.length - 1}
                            />
                        ))}
                    </div>
                </div>
            </>
        );
    },
);

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
