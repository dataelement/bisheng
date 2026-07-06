/**
 * ThinkingContent — collapsible thinking block. Mirrors task-mode's
 * DeepStepGroup thinking node: the header reads "正在深度思考..." while
 * reasoning is live (with a spinner icon + pulsing label), then settles to
 * "已深度思考" once the segment closes.
 *
 * Timing props (startedAt/endedAt/durationMs) are still accepted so callers
 * stay unchanged, but the "（用时 N 秒）" clause is intentionally not rendered.
 *
 * Layout: a left icon column next to a body column (trigger + collapsible text).
 */
import { Outlined } from "bisheng-icons";
import { memo, useCallback, useState, type FC, type MouseEvent } from "react";
import { cn } from "~/utils";

export interface ThinkingContentProps {
    reasoning: string;
    /** True while the reasoning is still streaming (no end frame yet). Drives
     *  the spinner icon and pulsing label. */
    isStreaming?: boolean;
    /** Accepted for caller compatibility; duration is no longer rendered. */
    startedAt?: number;
    /** Accepted for caller compatibility; duration is no longer rendered. */
    endedAt?: number;
    /** Accepted for caller compatibility; duration is no longer rendered. */
    durationMs?: number;
}

const ThinkingContent: FC<ThinkingContentProps> = memo(
    ({ reasoning, isStreaming = false }) => {
        // Always default collapsed — even while reasoning is still streaming —
        // so the answer body stays the focus; the user expands to read.
        const [isExpanded, setIsExpanded] = useState(false);

        const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            setIsExpanded((prev) => !prev);
        }, []);

        if (!reasoning) return null;

        const label = isStreaming ? `正在深度思考...` : `已深度思考`;

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
