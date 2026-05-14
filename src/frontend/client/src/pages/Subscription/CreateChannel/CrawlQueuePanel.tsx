// src/frontend/client/src/pages/Subscription/CreateChannel/CrawlQueuePanel.tsx
import { Loader2, X, ArrowRight, TriangleAlert, CircleCheck, ChevronDown, ChevronUp } from "lucide-react";
import { useLocalize } from "~/hooks";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import type { CrawlQueueItem } from "../hooks/useCrawlQueue";
import { crawlErrorMessageKey } from "./crawlErrorUtils";

interface CrawlQueuePanelProps {
    queue: CrawlQueueItem[];
    inProgressCount: number;
    panelOpen: boolean;
    onPanelOpenChange: (v: boolean) => void;
    onAbort: (id: string) => void;
    onOpenPreview: (id: string) => void;
    onOpenFeedback: () => void;
}

function truncate(str: string, max = 32): string {
    if (str.length <= max) return str;
    return str.slice(0, max - 3) + "...";
}

export function CrawlQueuePanel({
    queue,
    inProgressCount,
    panelOpen,
    onPanelOpenChange,
    onAbort,
    onOpenPreview,
    onOpenFeedback,
}: CrawlQueuePanelProps) {
    const localize = useLocalize();

    if (queue.length === 0) return null;

    return (
        <div className="relative inline-block">
            <button
                type="button"
                onClick={() => onPanelOpenChange(!panelOpen)}
                className="inline-flex items-center gap-1 whitespace-nowrap text-[12px] text-[#86909C] hover:text-[#4E5969]"
            >
                <span>{localize("com_subscription.website_crawl_queue")}</span>
                {inProgressCount > 0 ? (
                    <Loader2 className="size-3 animate-spin text-[#165DFF]" />
                ) : panelOpen ? (
                    <ChevronUp className="size-3" />
                ) : (
                    <ChevronDown className="size-3" />
                )}
            </button>

            {panelOpen && (
                <div className="absolute right-0 top-6 z-[230] w-[320px] max-h-[360px] overflow-y-auto rounded-[8px] bg-white px-[8px] py-[12px] flex flex-col gap-[4px] drop-shadow-[0px_4px_10px_rgba(7,34,88,0.07)]">
                    {queue.map(item => {
                        if (item.status === "pending" || item.status === "crawling") {
                            return (
                                <div
                                    key={item.id}
                                    className="group relative flex items-center gap-[8px] rounded-[6px] px-[12px] py-[6px] hover:bg-[#F8F8F8]"
                                >
                                    <span className="flex-1 truncate text-[14px] leading-[22px] text-[#999]">
                                        {truncate(item.url)}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => onAbort(item.id)}
                                        className="shrink-0 p-1 text-[#86909C] opacity-0 transition-opacity hover:text-[#F53F3F] group-hover:opacity-100"
                                        aria-label={localize("cancel")}
                                    >
                                        <X className="size-3.5" />
                                    </button>
                                    {item.status === "crawling" && (
                                        <div className="pointer-events-none absolute inset-x-[12px] bottom-0 h-[1px] overflow-hidden">
                                            <div className="h-full w-1/4 animate-crawl-slide bg-gradient-to-r from-transparent via-[#165DFF] to-transparent" />
                                        </div>
                                    )}
                                </div>
                            );
                        }
                        if (item.status === "success") {
                            return (
                                <div
                                    key={item.id}
                                    className="group flex items-center gap-[8px] rounded-[6px] px-[12px] py-[6px] hover:bg-[#F8F8F8]"
                                >
                                    <CircleCheck className="size-4 shrink-0 text-[#00B42A]" />
                                    <span className="flex-1 truncate text-[14px] leading-[22px] text-[#212121]">
                                        {truncate(item.sourceName ?? item.url, 28)}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => onOpenPreview(item.id)}
                                        className="shrink-0 p-1 text-[#165DFF] hover:text-[#4080FF]"
                                        aria-label={localize("com_subscription.crawled_content_preview")}
                                    >
                                        <ArrowRight className="size-4" />
                                    </button>
                                </div>
                            );
                        }
                        // failed
                        return (
                            <Tooltip key={item.id}>
                                <TooltipTrigger asChild>
                                    <div
                                        role="button"
                                        tabIndex={0}
                                        onClick={onOpenFeedback}
                                        onKeyDown={e => {
                                            if (e.key === "Enter" || e.key === " ") {
                                                e.preventDefault();
                                                onOpenFeedback();
                                            }
                                        }}
                                        className="flex items-center gap-[8px] rounded-[6px] px-[12px] py-[6px] cursor-pointer hover:bg-[#F8F8F8]"
                                    >
                                        <TriangleAlert className="size-4 shrink-0 text-[#FF7D00]" />
                                        <span className="flex-1 truncate text-[14px] leading-[22px] text-[#212121]">
                                            {truncate(item.url)}
                                        </span>
                                    </div>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-[280px] z-[260] bg-[rgba(23,23,23,0.85)]">
                                    {localize(crawlErrorMessageKey(item.errorCode))}
                                </TooltipContent>
                            </Tooltip>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
