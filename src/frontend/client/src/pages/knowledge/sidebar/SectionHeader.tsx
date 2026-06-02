import { Outlined } from "bisheng-icons";

interface SectionHeaderProps {
    title: string;
    collapsed: boolean;
    onToggle: () => void;
    sortText: string;
    onSort: () => void;
    /** When provided, renders a "+" button before the sort icon (e.g. create space on "我创建的"). */
    onAdd?: () => void;
    addLabel?: string;
}

export function SectionHeader({ title, collapsed, onToggle, sortText, onSort, onAdd, addLabel }: SectionHeaderProps) {
    return (
        // group: enables hover-reveal for the collapse chevron.
        // h-7 (28px) + rounded-md + hover bg: matches the tree nodes below.
        // The whole row is the toggle target; right-side icons stop propagation.
        <div
            role="button"
            tabIndex={0}
            onClick={onToggle}
            onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onToggle();
                }
            }}
            /* sticky top-0 + left-0 + width 100cqi:
               • width: 100cqi sizes the header to the scroll container's full visible inline
                 size (the scroll container has NO horizontal padding — items get their 12px
                 left/right gutter from their own list's px-3 instead). So the header spans
                 the panel edge-to-edge, fully covering items that scroll underneath with no
                 left/right peek-through.
               • top-0 keeps the header pinned to the viewport top during vertical scroll.
               • left-0 keeps the header pinned to the viewport left during horizontal scroll.
                 Because the scroll container has no padding, the sticky offset reference is
                 the true edge, so the header does NOT shift on horizontal scroll.
               • Inner px-4 (16px) aligns the title text with the items' left gutter. */
            className="group sticky top-0 left-0 z-[2] mb-2 flex h-7 w-[100cqi] cursor-pointer items-center justify-between bg-[#FBFBFB] px-4 transition-colors hover:bg-[#F4F4F4]"
        >
            <div className="flex h-full items-center gap-1 text-[12px] text-[#999] group-hover:text-[#4e5969]">
                <span>{title}</span>
                {/* Collapse arrow: placed after the title; hidden by default, revealed on row hover. */}
                <Outlined.Down
                    className={`size-4 opacity-0 transition-[opacity,transform] group-hover:opacity-100 ${
                        collapsed ? "-rotate-90" : ""
                    }`}
                />
            </div>
            <div className="flex items-center gap-1">
                {onAdd && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onAdd();
                        }}
                        title={addLabel}
                        aria-label={addLabel}
                        className="flex size-5 items-center justify-center rounded text-[#999] hover:bg-[#f2f3f5] hover:text-[#4e5969]"
                    >
                        <Outlined.Plus className="size-4" />
                    </button>
                )}
                <button
                    onClick={(e) => {
                        e.stopPropagation();
                        onSort();
                    }}
                    title={sortText}
                    aria-label={sortText}
                    className="flex size-5 items-center justify-center rounded text-[#999] hover:bg-[#f2f3f5] hover:text-[#4e5969]"
                >
                    <Outlined.Sort className="size-4" />
                </button>
            </div>
        </div>
    );
}
