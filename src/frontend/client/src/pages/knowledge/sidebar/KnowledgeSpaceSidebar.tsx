import {
    ArrowLeftRightIcon,
    ChevronDown,
    LayoutGridIcon,
    PanelLeftOpenIcon,
    PanelRightOpenIcon,
    Plus
} from "lucide-react";
import { useState, useMemo } from "react";
import { KnowledgeSpace, SortType } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";

interface KnowledgeSpaceSidebarProps {
    createdSpaces: KnowledgeSpace[];
    joinedSpaces: KnowledgeSpace[];
    activeSpaceId?: string;
    onSpaceSelect: (space: KnowledgeSpace) => void;
    onCreateSpace: () => void;
    onUpdateSpace: (space: KnowledgeSpace) => void;
    onDeleteSpace: (spaceId: string) => void;
    onLeaveSpace: (spaceId: string) => void;
    onPinSpace: (spaceId: string, pinned: boolean) => void;
    onKnowledgeSquare?: () => void;
}

function SectionHeader({ title, collapsed, onToggle, sortText, onSort }: any) {
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

export function KnowledgeSpaceSidebar({
    createdSpaces,
    joinedSpaces,
    activeSpaceId,
    onSpaceSelect,
    onCreateSpace,
    onUpdateSpace,
    onDeleteSpace,
    onLeaveSpace,
    onPinSpace,
    onKnowledgeSquare
}: KnowledgeSpaceSidebarProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [joinedCollapsed, setJoinedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [joinedSortBy, setJoinedSortBy] = useState<SortType>(SortType.UPDATE_TIME);

    const { showToast } = useToastContext();

    const getSortText = (sortType: SortType) => {
        switch (sortType) {
            case SortType.UPDATE_TIME: return "最近更新";
            case SortType.NAME: return "名称";
            default: return "最近更新";
        }
    };

    const toggleSort = (type: "created" | "joined") => {
        const sortTypes = [SortType.UPDATE_TIME, SortType.NAME];
        const currentSort = type === "created" ? createdSortBy : joinedSortBy;
        const nextSort = sortTypes[(sortTypes.indexOf(currentSort) + 1) % sortTypes.length];
        type === "created" ? setCreatedSortBy(nextSort) : setJoinedSortBy(nextSort);
    };

    const sortList = (list: KnowledgeSpace[], sortType: SortType) => {
        return [...list].sort((a, b) => {
            if (a.isPinned && !b.isPinned) return -1;
            if (!a.isPinned && b.isPinned) return 1;

            if (sortType === SortType.UPDATE_TIME) {
                return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
            } else if (sortType === SortType.NAME) {
                return a.name.localeCompare(b.name);
            }
            return 0;
        });
    };

    const sortedCreated = useMemo(() => sortList(createdSpaces, createdSortBy), [createdSpaces, createdSortBy]);
    const sortedJoined = useMemo(() => sortList(joinedSpaces, joinedSortBy), [joinedSpaces, joinedSortBy]);

    const handlePin = (spaceId: string, pinned: boolean) => {
        const targetSpaces = createdSpaces.find(s => s.id === spaceId) ? createdSpaces : joinedSpaces;
        const pinnedCount = targetSpaces.filter(s => s.isPinned).length;
        if (pinned && pinnedCount >= 5) {
            showToast({ message: "已达置顶数量限制", severity: NotificationSeverity.INFO });
            return;
        }
        onPinSpace(spaceId, pinned);
    };

    const handleSquareClick = () => {
        if (onKnowledgeSquare) onKnowledgeSquare();
        else showToast({ message: "前往广场功能开发中", severity: NotificationSeverity.INFO });
    };

    if (collapsed) {
        return (
            <div className="w-12 h-full bg-white flex flex-col items-center pt-[22px]">
                <Button size="icon" variant="ghost" className="w-5 h-5" onClick={() => setCollapsed(false)}>
                    <PanelLeftOpenIcon className="size-3.5" />
                </Button>
            </div>
        );
    }

    return (
        <div className="w-60 min-w-60 h-full bg-white border-r border-[#e5e6eb] flex flex-col px-3 py-5">
            {/* 顶部操作区 */}
            <div className="border-b border-[#e5e6eb] space-y-4 pb-4">
                <div className="px-2 flex justify-between items-center text-[14px] font-medium">
                    <span className="text-[#1d2129]">知识空间</span>
                    <Button size="icon" variant="ghost" className="w-5 h-5 text-[#86909c]" onClick={() => setCollapsed(true)}>
                        <PanelRightOpenIcon className="size-3.5" />
                    </Button>
                </div>
                <div className="flex items-center gap-3">
                    <Button variant="secondary" onClick={onCreateSpace} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                        <Plus className="size-4" />创建
                    </Button>
                    <Button variant="secondary" onClick={handleSquareClick} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                        <LayoutGridIcon className="size-4" />前往广场
                    </Button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar">
                {/* 我创建的 */}
                <div className="pt-4">
                    <SectionHeader
                        title="我创建的"
                        collapsed={createdCollapsed}
                        onToggle={() => setCreatedCollapsed(!createdCollapsed)}
                        sortText={getSortText(createdSortBy)}
                        onSort={() => toggleSort("created")}
                    />
                    {!createdCollapsed && (
                        <div className="space-y-1">
                            {sortedCreated.map(s => (
                                <KnowledgeSpaceItem
                                    key={s.id}
                                    space={s}
                                    type="created"
                                    isActive={s.id === activeSpaceId}
                                    onSelect={onSpaceSelect}
                                    onUpdate={onUpdateSpace}
                                    onDelete={onDeleteSpace}
                                    onLeave={onLeaveSpace}
                                    onPin={handlePin}
                                />
                            ))}
                            {!sortedCreated.length && <div className="py-6 text-center text-sm text-[#818181]">暂无数据</div>}
                        </div>
                    )}
                </div>

                {/* 我加入的 */}
                <div className="py-4">
                    <SectionHeader
                        title="我加入的"
                        collapsed={joinedCollapsed}
                        onToggle={() => setJoinedCollapsed(!joinedCollapsed)}
                        sortText={getSortText(joinedSortBy)}
                        onSort={() => toggleSort("joined")}
                    />
                    {!joinedCollapsed && (
                        <div className="space-y-1">
                            {sortedJoined.map(s => (
                                <KnowledgeSpaceItem
                                    key={s.id}
                                    space={s}
                                    type="joined"
                                    isActive={s.id === activeSpaceId}
                                    onSelect={onSpaceSelect}
                                    onUpdate={onUpdateSpace}
                                    onDelete={onDeleteSpace}
                                    onLeave={onLeaveSpace}
                                    onPin={handlePin}
                                />
                            ))}
                            {!sortedJoined.length && <div className="py-6 text-center text-sm text-[#818181]">暂无数据</div>}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
