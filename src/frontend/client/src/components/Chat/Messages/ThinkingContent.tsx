/**
 * ThinkingContent — collapsible "思考内容" block. Lives inside a
 * DeepThinkingGroup wrapper which owns the duration display, so this
 * component intentionally has no timer or duration text.
 */
import { CircleCheck, ChevronDown } from "lucide-react";
import { memo, useCallback, useState, type FC, type MouseEvent } from "react";
import { useRecoilValue } from "recoil";
import { cn } from "~/utils";
import store from "~/store";

const BUTTON_STYLES = {
    base: "group flex w-fit items-center justify-center py-2 text-sm leading-[18px] animate-thinking-appear",
    icon: "icon-sm ml-1.5 transform-gpu text-text-primary transition-transform duration-200",
} as const;

const CONTENT_STYLES = {
    wrapper: "relative pt-3 pl-3 text-text-secondary",
    border:
        "absolute left-1.5 h-[calc(100%)] border-l border-border-medium dark:border-border-heavy",
    text: "whitespace-pre-wrap leading-[26px] text-sm",
} as const;

export interface ThinkingContentProps {
    reasoning: string;
    /** Whether to render a short vertical timeline connector below this card.
     *  Set to true when something follows in the timeline (e.g., tool cards),
     *  so the timeline is continuous even when this section is collapsed. */
    showConnector?: boolean;
}

const ThinkingContent: FC<ThinkingContentProps> = memo(({ reasoning, showConnector = false }) => {
    const showThinkingDefault = useRecoilValue<boolean>(store.showThinking);
    const [isExpanded, setIsExpanded] = useState(showThinkingDefault);

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
                className={BUTTON_STYLES.base}
            >
                <CircleCheck size={14} className="mr-1.5 text-gray-400" />
                <span>思考内容</span>
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
                <div className="overflow-hidden min-h-0">
                    <div className={CONTENT_STYLES.wrapper}>
                        <div className={CONTENT_STYLES.border} />
                        <p className={CONTENT_STYLES.text}>{reasoning}</p>
                    </div>
                </div>
            </div>
            {showConnector && !isExpanded && (
                <div className="relative h-3 pl-3" aria-hidden="true">
                    <div className="absolute left-1.5 h-full border-r border-border-medium dark:border-border-heavy" />
                </div>
            )}
        </>
    );
});

ThinkingContent.displayName = "ThinkingContent";

export default ThinkingContent;
