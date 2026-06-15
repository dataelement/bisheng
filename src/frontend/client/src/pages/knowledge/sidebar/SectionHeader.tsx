import { Outlined } from "bisheng-icons";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";

interface SortOption {
    value: string;
    label: string;
}

interface SectionHeaderProps {
    title: string;
    collapsed: boolean;
    onToggle: () => void;
    /** Currently-selected sort field value. */
    sortValue: string;
    /** Available sort fields rendered in the sort dropdown. */
    sortOptions: SortOption[];
    /** Heading shown above the sort options (e.g. "排序字段"). */
    sortFieldLabel: string;
    onSortChange: (value: string) => void;
    /** When provided, renders a "+" button before the sort icon (e.g. create space on "我创建的"). */
    onAdd?: () => void;
    addLabel?: string;
    /** When provided, renders a knowledge-square entry icon in the right group. */
    onSquare?: () => void;
    squareLabel?: string;
    /** Mobile full-page list styling: larger title/padding, dark icons, always-visible chevron. */
    mobile?: boolean;
    /** Compact dropdown styling: dark right-side icons. */
    compact?: boolean;
}

export function SectionHeader({
    title,
    collapsed,
    onToggle,
    sortValue,
    sortOptions,
    sortFieldLabel,
    onSortChange,
    onAdd,
    addLabel,
    onSquare,
    squareLabel,
    mobile = false,
    compact = false,
}: SectionHeaderProps) {
    // Mobile right-side icon button: same color as the title (#212121), larger hit area.
    const mobileIconBtnClassName =
        "flex size-6 items-center justify-center rounded text-[#212121] outline-none active:bg-[#f2f3f5]";
    // Right-side icon button (+ / square / sort). Compact dropdown uses dark icons (#212121),
    // the PC sidebar keeps grey (#999); mobile full-page uses its own larger button.
    const rightIconBtn = mobile
        ? mobileIconBtnClassName
        : compact
            ? "flex size-5 items-center justify-center rounded text-[#212121] outline-none"
            : "flex size-5 items-center justify-center rounded text-[#999] outline-none hover:bg-[#f2f3f5] hover:text-[#4e5969]";
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
            className={
                mobile
                    ? "group sticky top-0 left-0 z-[2] flex w-[100cqi] cursor-pointer items-center justify-between bg-[#FBFBFB] px-5 py-2"
                    : compact
                        ? "group sticky top-0 left-0 z-[2] mb-2 flex h-[38px] w-[100cqi] cursor-pointer items-center justify-between bg-[#FBFBFB] px-4"
                        : "group sticky top-0 left-0 z-[2] mb-2 flex h-7 w-[100cqi] cursor-pointer items-center justify-between bg-[#FBFBFB] px-4 transition-colors hover:bg-[#F4F4F4]"
            }
        >
            <div
                className={
                    mobile
                        ? "flex items-center gap-1 text-[14px] leading-5 text-[#212121]"
                        : compact
                            ? "flex h-full items-center gap-1 text-[14px] text-[#999]"
                            : "flex h-full items-center gap-1 text-[12px] text-[#999] group-hover:text-[#4e5969]"
                }
            >
                <span>{title}</span>
                {/* Collapse arrow: placed after the title. Always visible in mobile/compact modes;
                    hidden by default on PC and revealed on row hover. */}
                <Outlined.Down
                    className={`size-4 transition-[opacity,transform] group-hover:opacity-100 ${
                        mobile || compact ? "opacity-100" : "opacity-0"
                    } ${collapsed ? "-rotate-90" : ""}`}
                />
            </div>
            <div className={mobile ? "flex items-center gap-2" : "flex items-center gap-1"}>
                {onAdd && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onAdd();
                        }}
                        title={addLabel}
                        aria-label={addLabel}
                        className={rightIconBtn}
                    >
                        <Outlined.Plus className="size-4" />
                    </button>
                )}
                {/* Knowledge-square entry. Placed before the sort icon per design. */}
                {onSquare && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onSquare();
                        }}
                        title={squareLabel}
                        aria-label={squareLabel}
                        className={rightIconBtn}
                    >
                        <Outlined.BlocksAndArrows className="size-4" />
                    </button>
                )}
                {/* Sort field dropdown — opens a menu of sort options with the
                    currently-selected one marked, mirroring the right-side panel. */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button
                            onClick={(e) => e.stopPropagation()}
                            title={sortFieldLabel}
                            aria-label={sortFieldLabel}
                            className={`${rightIconBtn} data-[state=open]:bg-[#f2f3f5]`}
                        >
                            <Outlined.Sort className="size-4" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                        align="end"
                        className={`${knowledgeSpaceDropdownSurfaceClassName} z-[100]`}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{sortFieldLabel}</div>
                        {sortOptions.map((opt) => {
                            const active = opt.value === sortValue;
                            return (
                                <DropdownMenuItem
                                    key={opt.value}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onSortChange(opt.value);
                                    }}
                                    className="flex items-center justify-between gap-6"
                                >
                                    <span>{opt.label}</span>
                                    {active && <Outlined.Check className="size-4 shrink-0" />}
                                </DropdownMenuItem>
                            );
                        })}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}
