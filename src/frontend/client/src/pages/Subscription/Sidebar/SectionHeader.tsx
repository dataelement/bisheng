import { ArrowLeftRightIcon, ChevronDown } from "lucide-react";

interface SectionHeaderProps {
    title: string;
    collapsed: boolean;
    onToggle: () => void;
    sortText: string;
    onSort: () => void;
}

export function SectionHeader({ title, collapsed, onToggle, sortText, onSort }: SectionHeaderProps) {
    return (
        <div className="flex items-center justify-between mb-2">
            <button onClick={onToggle} className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]">
                <ChevronDown className={`size-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} />
                {title}
            </button>
            <button onClick={onSort} className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]">
                {sortText}
                <ArrowLeftRightIcon className="size-3" />
            </button>
        </div>
    );
}
