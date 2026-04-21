/**
 * AgentThinkingHeader — collapsible header for the agent reasoning block.
 *
 * Streaming state: shows "思考中（用时 x 秒）" with a live-ticking elapsed
 *                  counter and a subtle pulse.
 * Finalised state: shows "已深度思考 (用时 N 秒)" and the elapsed duration chip.
 *
 * Re-uses Thinking.tsx styles (rounded pill button + chevron + left-bordered
 * content panel) so the agent bubble blends with the existing chat look.
 */
import { Atom, ChevronDown } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState, type FC, type MouseEvent } from "react";
import { useRecoilValue } from "recoil";
import { cn } from "~/utils";
import store from "~/store";

const BUTTON_STYLES = {
    base: "group mt-3 flex w-fit items-center justify-center py-2 text-sm leading-[18px] animate-thinking-appear",
    icon: "icon-sm ml-1.5 transform-gpu text-text-primary transition-transform duration-200",
} as const;

const CONTENT_STYLES = {
    wrapper: "relative pl-3 text-text-secondary",
    border:
        "absolute left-0 h-[calc(100%)] border-r pl-1 border-border-medium dark:border-border-heavy",
    text: "whitespace-pre-wrap leading-[26px] text-sm",
} as const;

export interface AgentThinkingHeaderProps {
    reasoning: string;
    /** Final duration (ms). When undefined, component renders the streaming state. */
    durationMs?: number;
    /** Overrides whether the stream is still in progress (defaults: durationMs == null). */
    isStreaming?: boolean;
}

function formatSeconds(ms: number): string {
    if (!ms || ms <= 0) return "0";
    const sec = ms / 1000;
    return sec < 10 ? sec.toFixed(1) : Math.round(sec).toString();
}

const AgentThinkingHeader: FC<AgentThinkingHeaderProps> = memo(
    ({ reasoning, durationMs, isStreaming }) => {
        const showThinkingDefault = useRecoilValue<boolean>(store.showThinking);
        const [isExpanded, setIsExpanded] = useState(showThinkingDefault);

        const streaming = isStreaming ?? durationMs == null;

        // Live-tick the elapsed time while streaming so the label shows
        // "思考中（用时 x 秒）" with x counting up in real time (spec §3 TC-A15).
        const startRef = useRef<number | null>(null);
        const [elapsedMs, setElapsedMs] = useState(0);
        useEffect(() => {
            if (!streaming) {
                startRef.current = null;
                setElapsedMs(0);
                return;
            }
            startRef.current = Date.now();
            setElapsedMs(0);
            const id = window.setInterval(() => {
                if (startRef.current != null) {
                    setElapsedMs(Date.now() - startRef.current);
                }
            }, 100);
            return () => {
                window.clearInterval(id);
            };
        }, [streaming]);

        const label = useMemo(() => {
            if (streaming) return `思考中（用时 ${formatSeconds(elapsedMs)} 秒）`;
            return `已深度思考 (用时 ${formatSeconds(durationMs || 0)} 秒)`;
        }, [streaming, elapsedMs, durationMs]);

        const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            setIsExpanded((prev) => !prev);
        }, []);

        if (!reasoning) return null;

        return (
            <>
                <button
                    type="button"
                    onClick={handleClick}
                    className={cn(BUTTON_STYLES.base, streaming && "animate-pulse")}
                >
                    <Atom size={14} className="mr-1.5 text-gray-400" />
                    <span>{label}</span>
                    <ChevronDown
                        className={cn(BUTTON_STYLES.icon, isExpanded && "rotate-180")}
                    />
                </button>
                <div
                    className={cn(
                        "grid transition-all duration-300 ease-out",
                        isExpanded && "mb-4",
                    )}
                    style={{ gridTemplateRows: isExpanded ? "1fr" : "0fr" }}
                >
                    <div className="overflow-hidden mt-3">
                        <div className={CONTENT_STYLES.wrapper}>
                            <div className={CONTENT_STYLES.border} />
                            <p className={CONTENT_STYLES.text}>{reasoning}</p>
                        </div>
                    </div>
                </div>
            </>
        );
    },
);

AgentThinkingHeader.displayName = "AgentThinkingHeader";

export default AgentThinkingHeader;
