/**
 * DeepThinkingGroup — one "deep thinking" episode of the daily chat: a
 * contiguous run of thinking + tool_call events behind a single collapsible
 * header, aligned with task mode's DeepStepGroup (F—2.4.2):
 *
 * - The header is the stable outer status — 正在深度思考（已用 N 秒）... while
 *   the run is live (spinner + pulsing label), settling to 已深度思考（用时 N 秒）.
 *   Searches and tool calls never replace it. The clock spans only this
 *   group's process events, never the answer text outside it.
 * - One small line under the header tracks the CURRENT step while running
 *   (正在分析问题 / 正在联网搜索 / 正在检索知识 / 正在调用工具：X /
 *   正在整理信息并继续思考); once the run ends it keeps the last sentence of
 *   the reasoning, exactly like task mode's collapsed narration line.
 * - Default collapsed, live or done; expanding reveals the full event
 *   timeline — thinking passages as plain text interleaved with tool rows in
 *   arrival order (only ADJACENT thinking fragments fold together). Folding
 *   only changes visibility, never content or order.
 *
 * Deliberately does NOT import task-mode (Linsight/Execution) modules — the
 * two surfaces stay decoupled; shared primitives live in ~/utils.
 */
import { Outlined } from "bisheng-icons";
import { memo, useEffect, useMemo, useState, type FC } from "react";
import type { AgentEvent } from "~/api/chatApi";
import { NarrationTicker } from "~/components/ui/NarrationTicker";
import { useLocalize } from "~/hooks";
import { cn, formatSeconds } from "~/utils";
import ToolCallDisplay, { classifyToolType, resolveToolName } from "./ToolCallDisplay";

export interface DeepThinkingGroupProps {
    /** Ordered events in this group — only thinking + tool_call entries. */
    events: AgentEvent[];
    /** True if this group is the currently-open trailing run (message still
     *  streaming, no final answer text yet). Drives the 正在/已 status. */
    isStreaming: boolean;
}

type ToolCallEvent = Extract<AgentEvent, { type: "tool_call" }>;
type Segment =
    | { kind: "thinking"; key: string; content: string }
    | { kind: "tool"; key: string; toolCall: ToolCallEvent };

/** Earliest start / latest end across the group's process events, with a
 *  per-event duration sum as the legacy-row fallback (no wall-clock fields). */
function groupSpan(events: AgentEvent[]) {
    let start: number | undefined;
    let end: number | undefined;
    let sum = 0;
    for (const ev of events) {
        if (ev.type !== "thinking" && ev.type !== "tool_call") continue;
        if (ev.started_at != null && (start == null || ev.started_at < start)) start = ev.started_at;
        if (ev.ended_at != null && (end == null || ev.ended_at > end)) end = ev.ended_at;
        sum += ev.duration_ms ?? 0;
    }
    return { start, end, sum };
}

/** Last complete sentence of the reasoning — the finished-state small line,
 *  mirroring task mode's narration. Falls back to the final line fragment. */
function lastReasoningSentence(segments: Segment[]): string {
    for (let i = segments.length - 1; i >= 0; i--) {
        const seg = segments[i];
        if (seg.kind !== "thinking") continue;
        const parts = seg.content
            .split(/[。！？!?\n]/)
            .map((s) => s.trim())
            .filter(Boolean);
        if (parts.length) return parts[parts.length - 1];
    }
    return "";
}

const DeepThinkingGroup: FC<DeepThinkingGroupProps> = memo(({ events, isStreaming }) => {
    const localize = useLocalize();
    // Default collapsed, live or done — the page opens quiet and the small
    // line below carries the current step; the user expands to read.
    const [isExpanded, setIsExpanded] = useState(false);

    // Walk the events in arrival order, folding only ADJACENT thinking
    // fragments into one passage. The wire and the DB already interleave
    // thinking and tool calls truthfully (the backend closes the open thinking
    // segment before every tool call), so the render must not regroup them.
    const segments = useMemo<Segment[]>(() => {
        const out: Segment[] = [];
        events.forEach((ev, i) => {
            if (ev.type === "thinking") {
                // A just-opened live segment has no text yet — skip it until
                // the first token lands so no empty passage flashes in.
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

    // ── Header clock — this group's process events only ────────────────────
    const { start, end, sum } = groupSpan(events);

    // Live-tick while streaming so the counter advances every 100ms.
    const [tick, setTick] = useState(0);
    useEffect(() => {
        if (!isStreaming) return;
        const id = window.setInterval(() => setTick((t) => t + 1), 100);
        return () => window.clearInterval(id);
    }, [isStreaming]);

    const elapsedMs = (() => {
        if (start == null) return sum;
        // A closed group missing its end stamp must not creep against Date.now().
        if (!isStreaming && end == null) return sum;
        return Math.max(0, (isStreaming ? Date.now() : end!) - start);
    })();
    // `tick` is read here so the IIFE re-runs on every interval render.
    void tick;

    const label = (() => {
        // Duration hides at 0 — legacy rows without timing fields, and the
        // brief moment before the first tick lands.
        const seconds = elapsedMs > 0 ? formatSeconds(elapsedMs) : "";
        if (isStreaming) {
            return seconds
                ? localize("com_deep_thinking.running", { 0: seconds })
                : localize("com_deep_thinking.running_no_time");
        }
        return seconds
            ? localize("com_deep_thinking.done", { 0: seconds })
            : localize("com_deep_thinking.done_no_time");
    })();

    // ── Small line under the header ────────────────────────────────────────
    // Running: the CURRENT step, derived from the trailing event. Done: the
    // last reasoning sentence (task mode's narration semantics). Shown while
    // running or collapsed; a finished, expanded group hides it — the full
    // timeline below carries the same information.
    const subline = (() => {
        if (!isStreaming) return lastReasoningSentence(segments);
        const trailing = events[events.length - 1];
        if (!trailing) return localize("com_deep_thinking.step_analyzing");
        if (trailing.type === "tool_call" && trailing.inflight) {
            const variant = classifyToolType(trailing);
            if (variant === "web") return localize("com_deep_thinking.step_web_search");
            if (variant === "knowledge") return localize("com_deep_thinking.step_knowledge");
            return localize("com_deep_thinking.step_tool", { 0: resolveToolName(trailing, localize) });
        }
        // Thinking (or a just-finished tool, about to resume thinking): first
        // round reads as analysis, later rounds as digesting tool output.
        const hasPriorTool = events.some((ev) => ev.type === "tool_call" && ev !== trailing);
        return hasPriorTool
            ? localize("com_deep_thinking.step_continuing")
            : localize("com_deep_thinking.step_analyzing");
    })();

    return (
        <div className="flex w-full min-w-0 flex-col animate-thinking-appear">
            <button
                type="button"
                onClick={() => setIsExpanded((prev) => !prev)}
                className="group flex w-fit max-w-full items-center gap-2 py-1 text-left text-sm font-medium leading-[22px] text-[#999999]"
            >
                <span className="flex size-4 shrink-0 items-center justify-center">
                    {/* Spinner only while running AND collapsed (task-mode icon
                        regime); otherwise the static reasoning bulb. */}
                    {isStreaming && !isExpanded ? (
                        <Outlined.Loading size={16} className="animate-spin text-primary" />
                    ) : (
                        <Outlined.Bulb size={16} className="text-[#1D2129]" />
                    )}
                </span>
                <span
                    className={cn(
                        "min-w-0 truncate transition-colors group-hover:text-[#212121]",
                        isExpanded && "text-[#212121]",
                        isStreaming && "animate-pulse group-hover:animate-none",
                    )}
                >
                    {label}
                </span>
                <Outlined.Down
                    size={16}
                    className={cn(
                        "shrink-0 transform-gpu text-[#8C8C8C] transition duration-200 group-hover:text-[#212121]",
                        !isExpanded && "-rotate-90",
                    )}
                />
            </button>
            {/* Current-step / narration line — indented under the label. The
                ticker crossfades each step upward (task mode's animation) and
                holds the last text through empty updates, so steps never hard-swap. */}
            {(isStreaming || !isExpanded) && (
                <div className="pl-6">
                    <NarrationTicker text={subline} />
                </div>
            )}
            <div
                className={cn("grid transition-all duration-300 ease-out", isExpanded && "mt-2")}
                style={{ gridTemplateRows: isExpanded ? "1fr" : "0fr" }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="flex flex-col gap-1.5 pl-6 pb-1">
                        {segments.map((seg) =>
                            seg.kind === "thinking" ? (
                                // Plain passage — single-level fold, no inner
                                // "思考内容" collapsible (task-mode alignment).
                                <p
                                    key={seg.key}
                                    className="whitespace-pre-wrap break-words text-xs leading-5 text-[#818181]"
                                >
                                    {seg.content}
                                </p>
                            ) : (
                                <ToolCallDisplay key={seg.key} toolCall={seg.toolCall} />
                            ),
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
});

DeepThinkingGroup.displayName = "DeepThinkingGroup";

export default DeepThinkingGroup;
