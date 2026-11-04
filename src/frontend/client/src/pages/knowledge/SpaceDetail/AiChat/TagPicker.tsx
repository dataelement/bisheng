// @ts-strict-ignore
/**
 * TagPicker — floating popup that displays available tags.
 * Triggered when user types '#' in the chat input.
 * Supports keyboard navigation and click selection.
 */
import { Button } from "@bisheng/ui";
import { useEffect, useRef, useState } from "react";
import { cn } from "~/utils";
import { useLocalize, useScrollRevealRef } from "~/hooks";

interface TagPickerProps {
    tags: string[];
    loading?: boolean;
    failed?: boolean;
    onRetry?: () => void;
    searchText: string; // text after '#' for filtering
    onSelect: (tag: string) => void;
    onClose: () => void;
}

export function TagPicker({ tags, searchText, onSelect, onClose, loading = false, failed = false, onRetry }: TagPickerProps) {
    const localize = useLocalize();
    const [activeIndex, setActiveIndex] = useState(0);
    const containerRef = useRef<HTMLDivElement>(null);
    const listScrollRevealRef = useScrollRevealRef<HTMLDivElement>();

    // Filter tags by search text
    const filtered = tags.filter(t =>
        t.toLowerCase().includes(searchText.toLowerCase())
    );

    // Reset active index when filter changes
    useEffect(() => {
        setActiveIndex(0);
    }, [searchText, tags]);

    // Keyboard navigation
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (loading || failed) { if (e.key === "Escape") onClose(); return; }
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIndex(prev => Math.max(0, Math.min(prev + 1, filtered.length - 1)));
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIndex(prev => Math.max(prev - 1, 0));
            } else if (e.key === "Enter" && filtered.length > 0) {
                e.preventDefault();
                onSelect(filtered[Math.min(activeIndex, filtered.length - 1)]);
            } else if (e.key === "Escape") {
                e.preventDefault();
                onClose();
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [filtered, activeIndex, onSelect, onClose, loading, failed]);

    if (loading || failed || filtered.length === 0) {
        return (
            <div
                ref={(el) => {
                    containerRef.current = el;
                }}
                className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-border-base rounded-lg shadow-lg p-3 z-50"
            >
                {loading ? <p role="status" className="text-body-sm text-text-3 text-center">{localize("com_ui_loading")}</p>
                    : failed ? <div role="alert" className="text-body-sm text-danger text-center">
                        {localize("com_knowledge.load_tags_failed")}
                        <Button type="button" color="primary" variant="text" size="small" className="ml-2" onClick={onRetry}>{localize("com_ui_retry")}</Button>
                    </div> : <p className="text-body-sm text-text-3 text-center">{localize(tags.length ? "com_knowledge.no_matched_tags" : "com_knowledge.no_tags")}</p>}
            </div>
        );
    }

    return (
        <div
            ref={(el) => {
                containerRef.current = el;
                listScrollRevealRef(el);
            }}
            className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-border-base rounded-lg shadow-lg z-50 max-h-[200px] overflow-y-auto scrollbar-on-scroll"
        >
            <div className="p-1.5">
                {filtered.map((tag, i) => (
                    <button
                        key={tag}
                        className={cn(
                            "w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors",
                            i === activeIndex
                                ? "bg-fill-2 text-text-1"
                                : "text-text-2 hover:bg-fill-1"
                        )}
                        onMouseEnter={() => setActiveIndex(i)}
                        onClick={() => onSelect(tag)}
                    >
                        <span className="inline-flex items-center gap-1">
                            <span className="text-blue-500">#</span>
                            {tag}
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
}
