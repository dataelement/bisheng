/**
 * ThinkingContent — collapsible thinking block. Mirrors task-mode's
 * DeepStepGroup thinking node: the header reads "正在深度思考（已用 N 秒）..."
 * while reasoning is live (with a spinner icon + pulsing label), then settles
 * to "已深度思考（用时 N 秒）" once the segment closes. With no timing info
 * (legacy :::thinking::: rows) it falls back to a plain "已深度思考" label.
 *
 * Layout: a left icon column next to a body column (trigger + collapsible text).
 */
import { Outlined } from "bisheng-icons";
import { memo, useCallback, useEffect, useState, type FC, type MouseEvent } from "react";
import { cn, formatSeconds } from "~/utils";

export interface ThinkingContentProps {
    reasoning: string;
    /** True while the reasoning is still streaming (no end frame yet). Drives
     *  the spinner icon, pulsing label and live elapsed ticker. */
    isStreaming?: boolean;
    /** Epoch ms of the first thinking delta — anchors the elapsed clock. */
    startedAt?: number;
    /** Epoch ms of the thinking end frame — freezes the elapsed clock. */
    endedAt?: number;
    /** Fallback total duration when started/ended wall-clock isn't available. */
    durationMs?: number;
}

const ThinkingContent: FC<ThinkingContentProps> = memo(
    ({ reasoning, isStreaming = false, startedAt, endedAt, durationMs }) => {
        // Always default collapsed — even while reasoning is still streaming —
        // so the answer body stays the focus; the user expands to read.
        const [isExpanded, setIsExpanded] = useState(false);

        // Live-tick while streaming so the header counter advances every 100ms.
        const [tick, setTick] = useState(0);
        useEffect(() => {
            if (!isStreaming) return;
            const id = window.setInterval(() => setTick((t) => t + 1), 100);
            return () => window.clearInterval(id);
        }, [isStreaming]);

        const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            setIsExpanded((prev) => !prev);
        }, []);

        if (!reasoning) return null;

        const elapsedMs = (() => {
            if (startedAt == null) return durationMs ?? 0;
            // Closed segment with no end frame: fall back to the recorded duration
            // so the label doesn't creep against Date.now().
            if (!isStreaming && endedAt == null) return durationMs ?? 0;
            const stop = isStreaming ? Date.now() : endedAt!;
            return Math.max(0, stop - startedAt);
        })();
        // Read `tick` so the elapsed value re-evaluates on every interval render.
        void tick;
        const showDuration = elapsedMs > 0;

        const label = isStreaming
            ? showDuration
                ? `正在深度思考（已用 ${formatSeconds(elapsedMs)} 秒）...`
                : `正在深度思考...`
            : showDuration
                ? `已深度思考（用时 ${formatSeconds(elapsedMs)} 秒）`
                : `已深度思考`;

        return (
            <div className="flex w-full min-w-0 gap-2 animate-thinking-appear">
                <div className="flex shrink-0 items-start pt-[3px]">
                    {isStreaming && !isExpanded ? (
                        <Outlined.Loading size={16} className="shrink-0 animate-spin text-primary" />
                    ) : (
                        <Outlined.Bulb size={16} className="shrink-0 text-[#1D2129]" />
                    )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col pb-3">
                    <button
                        type="button"
                        onClick={handleClick}
                        className={cn(
                            "group flex w-fit max-w-full items-center gap-1 text-sm leading-[22px] text-[#999999] transition-colors hover:text-[#212121]",
                            isStreaming && "animate-pulse group-hover:animate-none",
                        )}
                    >
                        <span>{label}</span>
                        <Outlined.Down
                            size={16}
                            className={cn(
                                "shrink-0 transform-gpu transition-transform duration-200",
                                !isExpanded && "-rotate-90",
                            )}
                        />
                    </button>
                    <div
                        className={cn("grid transition-all duration-300 ease-out", isExpanded && "mt-2")}
                        style={{ gridTemplateRows: isExpanded ? "1fr" : "0fr" }}
                    >
                        <div className="min-h-0 overflow-hidden">
                            <p className="whitespace-pre-wrap text-xs leading-5 text-[#818181]">{reasoning}</p>
                        </div>
                    </div>
                </div>
            </div>
        );
    },
);

ThinkingContent.displayName = "ThinkingContent";

export default ThinkingContent;
