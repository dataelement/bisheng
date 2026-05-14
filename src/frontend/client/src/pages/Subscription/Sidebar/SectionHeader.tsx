import { ArrowLeftRightIcon, ChevronDown } from "lucide-react";
import { ChannelExchangeFourIcon } from "~/components/icons/channels";

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
            <button onClick={onToggle} className="flex items-center gap-1 text-[12px] text-[#999] hover:text-[#4e5969]">
                <ChevronDown className={`size-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} />
                {title}
            </button>
            <button onClick={onSort} className="flex items-center gap-1 text-[12px] text-[#999] hover:text-[#4e5969]">
                {sortText}
                <ChannelExchangeFourIcon className="w-4 h-4" />
            </button>
        </div>
    );
}
