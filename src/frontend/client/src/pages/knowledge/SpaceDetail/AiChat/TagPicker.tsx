/**
 * TagPicker — floating popup that displays available tags.
 * Triggered when user types '#' in the chat input.
 * Supports keyboard navigation and click selection.
 */
import { useEffect, useRef, useState } from "react";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";

interface TagPickerProps {
    tags: string[];
    searchText: string; // text after '#' for filtering
    onSelect: (tag: string) => void;
    onClose: () => void;
}

export function TagPicker({ tags, searchText, onSelect, onClose }: TagPickerProps) {
    const localize = useLocalize();
    const [activeIndex, setActiveIndex] = useState(0);
    const containerRef = useRef<HTMLDivElement>(null);

    // Filter tags by search text
    const filtered = tags.filter(t =>
        t.toLowerCase().includes(searchText.toLowerCase())
    );

    // Reset active index when filter changes
    useEffect(() => {
        setActiveIndex(0);
    }, [searchText]);

    // Keyboard navigation
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIndex(prev => Math.min(prev + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIndex(prev => Math.max(prev - 1, 0));
            } else if (e.key === "Enter" && filtered.length > 0) {
                e.preventDefault();
                onSelect(filtered[activeIndex]);
            } else if (e.key === "Escape") {
                e.preventDefault();
                onClose();
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [filtered, activeIndex, onSelect, onClose]);

    if (filtered.length === 0) {
        return (
            <div
                ref={containerRef}
                className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-[#e5e6eb] rounded-lg shadow-lg p-3 z-50"
            >
                <p className="text-sm text-[#86909c] text-center">{localize("com_knowledge.no_matched_tags")}</p>
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-[#e5e6eb] rounded-lg shadow-lg z-50 max-h-[200px] overflow-y-auto"
        >
            <div className="p-1.5">
                {filtered.map((tag, i) => (
                    <button
                        key={tag}
                        className={cn(
                            "w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors",
                            i === activeIndex
                                ? "bg-[#f2f3f5] text-[#1d2129]"
                                : "text-[#4e5969] hover:bg-[#f7f8fa]"
                        )}
                        onMouseEnter={() => setActiveIndex(i)}
                        onClick={() => onSelect(tag)}
                    >
                        <span className="inline-flex items-center gap-1">
                            <span className="text-[#165dff]">#</span>
                            {tag}
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
}
