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
        // h-7 (28px): matches the height of tree nodes below.
        <div className="group mb-2 flex h-7 items-center justify-between">
            <button
                onClick={onToggle}
                className="flex h-full items-center gap-1 text-[12px] text-[#999] hover:text-[#4e5969]"
            >
                <span>{title}</span>
                {/* Collapse arrow: placed after the title; hidden by default, revealed on row hover. */}
                <Outlined.Down
                    className={`size-4 opacity-0 transition-[opacity,transform] group-hover:opacity-100 ${
                        collapsed ? "-rotate-90" : ""
                    }`}
                />
            </button>
            <div className="flex items-center gap-1">
                {onAdd && (
                    <button
                        onClick={onAdd}
                        title={addLabel}
                        aria-label={addLabel}
                        className="flex size-5 items-center justify-center rounded text-[#999] hover:bg-[#f2f3f5] hover:text-[#4e5969]"
                    >
                        <Outlined.Plus className="size-4" />
                    </button>
                )}
                <button
                    onClick={onSort}
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
