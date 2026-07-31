/**
 * KnowledgeAttachmentStrip — grey reference strip stacked above the collapsed
 * dock input (Figma 13022:46625). Mirrors the home-page AttachmentBar: a
 * light-grey strip with rounded top corners that overlaps the input card by
 * 16px (-mb-4 = the card's corner radius) so the white card reads as emerging
 * from the strip.
 *
 * Chips are the rows ticked in the file list, in tick order; the row scrolls
 * horizontally (wheel + pager arrows + edge fades) instead of wrapping. The
 * dock's history / expand controls dock into the strip's right end (trailing),
 * separated from the pager arrow by a "｜" divider when both are present.
 */
import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type ReactNode,
} from "react";
import { Outlined } from "bisheng-icons";
import { AttachmentChip } from "~/components/Chat/Input/AttachmentBar";
import { cn } from "~/utils";
import {
    AUDIO_FILE_EXTENSIONS,
    IMAGE_FILE_EXTENSIONS,
    VIDEO_FILE_EXTENSIONS,
} from "../../knowledgeUtils";
import type { KnowledgeAiReference } from "./KnowledgeAiInput";

/** File icon mirroring the file list exactly (FileTable.renderRowFileIcon):
 *  audio / video / image get their media icons, everything else the generic
 *  file glyph — NOT the home-chat per-format mapping (W/P/T…), so a chip always
 *  shows the same icon as the row it was ticked from. */
export const KnowledgeChipFileIcon = ({ name }: { name: string }) => {
    const ext = name.split(".").pop()?.toLowerCase() || "";
    if ((AUDIO_FILE_EXTENSIONS as readonly string[]).includes(ext)) {
        return <Outlined.FileAudio size={16} />;
    }
    if ((VIDEO_FILE_EXTENSIONS as readonly string[]).includes(ext)) {
        return <Outlined.FileVideo size={16} />;
    }
    if ((IMAGE_FILE_EXTENSIONS as readonly string[]).includes(ext)) {
        return <Outlined.FileImage size={16} />;
    }
    return <Outlined.File size={16} />;
};

/** Shared by this strip and the expanded-state reference row (KnowledgeAiInput). */
export const PagerButton = ({
    direction,
    onClick,
}: {
    direction: "left" | "right";
    onClick: () => void;
}) => {
    const Icon = direction === "left" ? Outlined.Left : Outlined.Right;
    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={direction === "left" ? "Scroll back" : "Scroll forward"}
            className="flex size-8 shrink-0 items-center justify-center rounded-[20px] text-[#86909c] transition-colors hover:text-[#4e5969]"
        >
            <Icon size={16} />
        </button>
    );
};

interface KnowledgeAttachmentStripProps {
    /** Ticked rows, in tick order. The strip should not mount when empty. */
    items: KnowledgeAiReference[];
    /** Removing a chip unticks that row in the file list. */
    onRemove?: (id: string) => void;
    /** Controls docked at the strip's right end (history / expand pair). */
    trailing?: ReactNode;
}

export function KnowledgeAttachmentStrip({
    items,
    onRemove,
    trailing,
}: KnowledgeAttachmentStripProps) {
    const scrollRef = useRef<HTMLDivElement>(null);
    const [canLeft, setCanLeft] = useState(false);
    const [canRight, setCanRight] = useState(false);

    const updateEdges = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        const maxScroll = el.scrollWidth - el.clientWidth;
        setCanLeft(el.scrollLeft > 1);
        setCanRight(el.scrollLeft < maxScroll - 1);
    }, []);

    // Recompute affordances when the item set changes or the row resizes.
    useLayoutEffect(() => {
        updateEdges();
        const el = scrollRef.current;
        if (!el || typeof ResizeObserver === "undefined") return;
        const ro = new ResizeObserver(() => updateEdges());
        ro.observe(el);
        return () => ro.disconnect();
    }, [updateEdges, items.length]);

    // Newly ticked rows append at the row's end — bring them into view. Only on
    // growth, so removing a chip doesn't yank the row to the far end.
    const prevLenRef = useRef(items.length);
    useEffect(() => {
        const el = scrollRef.current;
        if (el && items.length > prevLenRef.current) {
            el.scrollTo({ left: el.scrollWidth });
        }
        prevLenRef.current = items.length;
    }, [items.length]);

    // Native non-passive wheel listener so preventDefault actually works
    // (React's synthetic onWheel is passive and can't block page scroll).
    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        const onWheel = (e: WheelEvent) => {
            if (el.scrollWidth <= el.clientWidth) return;
            const delta = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
            if (delta === 0) return;
            e.preventDefault();
            el.scrollLeft += delta;
        };
        el.addEventListener("wheel", onWheel, { passive: false });
        return () => el.removeEventListener("wheel", onWheel);
    }, []);

    const pageScroll = useCallback((dir: "left" | "right") => {
        const el = scrollRef.current;
        if (!el) return;
        el.scrollBy({ left: dir === "left" ? -el.clientWidth : el.clientWidth, behavior: "smooth" });
    }, []);

    return (
        <div className="relative -mb-4 w-full shrink-0 overflow-hidden rounded-t-[20px] bg-[#f8f8f8] px-3 pb-6 pt-3 touch-mobile:rounded-t-2xl">
            <div className="flex items-center gap-2">
                {canLeft && <PagerButton direction="left" onClick={() => pageScroll("left")} />}
                <div className="relative min-w-0 flex-1">
                    <div
                        ref={scrollRef}
                        onScroll={updateEdges}
                        className="flex gap-2 overflow-x-auto [&::-webkit-scrollbar]:hidden"
                        style={{ scrollbarWidth: "none" }}
                    >
                        {items.map((item) => (
                            <AttachmentChip
                                key={item.id}
                                icon={
                                    item.isFolder ? (
                                        <Outlined.FolderClose size={16} />
                                    ) : (
                                        <KnowledgeChipFileIcon name={item.name} />
                                    )
                                }
                                label={item.name}
                                className="h-8"
                                onRemove={onRemove ? () => onRemove(item.id) : undefined}
                            />
                        ))}
                    </div>
                    {/* Edge fades hinting at content scrolled out of view. */}
                    <div
                        className={cn(
                            "pointer-events-none absolute left-0 top-0 h-full w-6 bg-gradient-to-r from-[#f9f9f9] from-[49%] to-transparent transition-opacity",
                            canLeft ? "opacity-100" : "opacity-0",
                        )}
                    />
                    <div
                        className={cn(
                            "pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-[#f9f9f9] from-[49%] to-transparent transition-opacity",
                            canRight ? "opacity-100" : "opacity-0",
                        )}
                    />
                </div>
                {canRight && <PagerButton direction="right" onClick={() => pageScroll("right")} />}
                {/* Hairline divider between the pager arrow and the docked controls. */}
                {trailing && canRight && (
                    <span aria-hidden className="h-3 w-px shrink-0 bg-[#D8D8D8]" />
                )}
                {trailing}
            </div>
        </div>
    );
}
