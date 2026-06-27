/**
 * ThinkingContent — collapsible "思考内容" block. Lives inside a
 * DeepThinkingGroup wrapper which owns the duration display, so this
 * component intentionally has no timer or duration text.
 *
 * Layout follows the timeline-item design: a left rail (16px icon +
 * 1px vertical connector) next to a body column (trigger + collapsible text).
 */
import { Outlined } from "bisheng-icons";
import { memo, useCallback, useState, type FC, type MouseEvent } from "react";
import { cn } from "~/utils";

export interface ThinkingContentProps {
    reasoning: string;
}

const ThinkingContent: FC<ThinkingContentProps> = memo(({ reasoning }) => {
    // Collapsed by default — each timeline node is independently expandable.
    const [isExpanded, setIsExpanded] = useState(false);

    const handleClick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
        e.preventDefault();
        setIsExpanded((prev) => !prev);
    }, []);

    if (!reasoning) return null;

    return (
        <div className="flex w-full min-w-0 gap-2 animate-thinking-appear">
            <div className="flex shrink-0 items-start pt-[3px]">
                <Outlined.CheckCircle size={16} className="shrink-0 text-[#999999]" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={handleClick}
                    className="group flex w-fit max-w-full items-center gap-1 text-sm leading-[22px] text-[#999999] transition-colors hover:text-[#212121]"
                >
                    <span>思考内容</span>
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
});

ThinkingContent.displayName = "ThinkingContent";

export default ThinkingContent;
