import {
    ArrowLeftRightIcon,
    ChevronDown,
    PanelLeftOpenIcon,
    PanelRightOpenIcon,
    Plus
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KnowledgeSpace, SortType, getMineSpacesApi, getJoinedSpacesApi } from "~/api/knowledge";
import { Button } from "~/components/ui/Button";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";
import { SectionHeader } from "./SectionHeader";
import { useSpaceActions } from "../hooks/useSpaceActions";
import { useLocalize } from "~/hooks";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";

interface KnowledgeSpaceSidebarProps {
    activeSpaceId?: string;
    onSpaceSelect: (space: KnowledgeSpace | null) => void;
    onCreateSpace: () => void;
    onSpaceSettings: (space: KnowledgeSpace) => void;
    onManageMembers: (space: KnowledgeSpace) => void;
    onKnowledgeSquare?: () => void;
}

// Sort cycle: update_time → name → update_time
const SORT_CYCLE = [SortType.UPDATE_TIME, SortType.NAME];

function getSortLabel(sort: SortType, localize: any) {
    return sort === SortType.NAME ? localize("com_knowledge.name") : localize("com_knowledge.recently_updated");
}

export function KnowledgeSpaceSidebar({
    activeSpaceId,
    onSpaceSelect,
    onCreateSpace,
    onSpaceSettings,
    onManageMembers,
    onKnowledgeSquare,
}: KnowledgeSpaceSidebarProps) {
    const localize = useLocalize();
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [joinedCollapsed, setJoinedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [joinedSortBy, setJoinedSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const queryClient = useQueryClient();

    // Fetch "my created" space list — re-fetched whenever sort changes
    const { data: createdSpaces = [], isLoading: isCreatedLoading } = useQuery({
        queryKey: ["knowledgeSpaces", "mine", createdSortBy],
        queryFn: () => getMineSpacesApi({ order_by: createdSortBy }),
        placeholderData: (prev) => prev,
    });

    // Fetch "joined" space list
    const { data: joinedSpaces = [], isLoading: isJoinedLoading } = useQuery({
        queryKey: ["knowledgeSpaces", "joined", joinedSortBy],
        queryFn: () => getJoinedSpacesApi({ order_by: joinedSortBy }),
        placeholderData: (prev) => prev,
    });

    // CRUD operations with optimistic updates (mirrors useChannelActions)
    const {
        handleUpdateSpace,
        handleDeleteSpace,
        handleLeaveSpace,
        handlePinSpace,
    } = useSpaceActions({
        activeSpaceId,
        createdSortBy,
        joinedSortBy,
        createdSpaces,
        joinedSpaces,
        onSpaceSelect,
    });

    // Auto-select first space when no space is active (mirrors ChannelSidebar)
    useEffect(() => {
        if (!activeSpaceId) {
            // Wait for both to finish initial loading to guarantee priorities
            if (isCreatedLoading || isJoinedLoading) return;

            if (createdSpaces.length > 0) {
                onSpaceSelect(createdSpaces[0]);
            } else if (joinedSpaces.length > 0) {
                onSpaceSelect(joinedSpaces[0]);
            }
        }
    }, [activeSpaceId, createdSpaces, joinedSpaces, isCreatedLoading, isJoinedLoading, onSpaceSelect]);

    const toggleSort = (type: "created" | "joined") => {
        if (type === "created") {
            const next = SORT_CYCLE[(SORT_CYCLE.indexOf(createdSortBy) + 1) % SORT_CYCLE.length];
            queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "mine", createdSortBy] });
            setCreatedSortBy(next);
        } else {
            const next = SORT_CYCLE[(SORT_CYCLE.indexOf(joinedSortBy) + 1) % SORT_CYCLE.length];
            queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "joined", joinedSortBy] });
            setJoinedSortBy(next);
        }
    };

    const handleListScroll = () => {
        setIsListScrolling(true);
        if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
        listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
    };

    return (
        <div
            className={[
                "h-full bg-white border-r border-[#e5e6eb] flex flex-col overflow-hidden flex-shrink-0",
                "transition-[width] duration-[350ms] ease-in-out",
                collapsed ? "w-12" : "w-60",
            ].join(" ")}
        >
            {/* Top actions */}
            <div className={collapsed ? "px-0 py-5" : "px-3 py-5"}>
                <div className={collapsed ? "flex items-center justify-center" : "border-b border-[#e5e6eb] space-y-4 pb-4"}>
                    <div className={collapsed ? "flex items-center justify-center" : "px-2 flex justify-between items-center text-[14px] font-medium"}>
                        {!collapsed && <span className="text-[#1d2129]">{localize("com_knowledge.knowledge_space")}</span>}
                        <Button
                            size="icon"
                            variant="ghost"
                            className={collapsed ? "w-5 h-5" : "w-5 h-5 text-[#86909c]"}
                            onClick={() => setCollapsed((v) => !v)}
                        >
                            {collapsed ? (
                                <PanelLeftOpenIcon className="size-5" />
                            ) : (
                                <PanelRightOpenIcon className="size-5" />
                            )}
                        </Button>
                    </div>
                    {!collapsed && (
                        <div className="flex items-center gap-3">
                            <Button variant="secondary" onClick={onCreateSpace} className="flex-1 h-8 text-[13px] text-[#212121] bg-[#F7F7F7] hover:bg-[#E5E6EB] border-none gap-1">
                                <Plus className="size-4" />
                                {localize("com_knowledge.create")}
                            </Button>
                            <Button variant="secondary" onClick={() => onKnowledgeSquare?.()} className="flex-1 h-8 text-[13px] text-[#212121] bg-[#F7F7F7] hover:bg-[#E5E6EB] border-none gap-1">
                                <ChannelBlocksArrowsIcon className="size-4" />
                                {localize("com_knowledge.go_to_square")}
                            </Button>
                        </div>
                    )}
                </div>
            </div>

            <div
                className={[
                    "flex-1 min-h-0",
                    collapsed ? "opacity-0 pointer-events-none" : "opacity-100",
                    "transition-opacity duration-[350ms] ease-in-out",
                ].join(" ")}
            >
                <div
                    className="h-full overflow-y-auto scroll-on-scroll px-3 pb-5"
                    onScroll={handleListScroll}
                    data-scrolling={isListScrolling ? "true" : "false"}
                >
                    {/* My created */}
                    <div className="pt-0">
                        <SectionHeader
                            title={localize("com_knowledge.created_by_me")}
                            collapsed={createdCollapsed}
                            onToggle={() => setCreatedCollapsed(!createdCollapsed)}
                            sortText={getSortLabel(createdSortBy, localize)}
                            onSort={() => toggleSort("created")}
                        />
                        {!createdCollapsed && (
                            <div className="space-y-1">
                                {createdSpaces.map(s => (
                                    <KnowledgeSpaceItem
                                        key={s.id}
                                        space={s}
                                        type="created"
                                        isActive={s.id === activeSpaceId}
                                        onSelect={onSpaceSelect}
                                        onUpdate={handleUpdateSpace}
                                        onDelete={handleDeleteSpace}
                                        onLeave={handleLeaveSpace}
                                        onPin={(id, pinned) => handlePinSpace(id, pinned, "created")}
                                        onSettings={onSpaceSettings}
                                        onManageMembers={onManageMembers}
                                    />
                                ))}
                                {!createdSpaces.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_knowledge.no_data")}</div>}
                            </div>
                        )}
                    </div>

                    {/* Joined */}
                    <div className="py-4">
                        <SectionHeader
                            title={localize("com_knowledge.joined_by_me")}
                            collapsed={joinedCollapsed}
                            onToggle={() => setJoinedCollapsed(!joinedCollapsed)}
                            sortText={getSortLabel(joinedSortBy, localize)}
                            onSort={() => toggleSort("joined")}
                        />
                        {!joinedCollapsed && (
                            <div className="space-y-1">
                                {joinedSpaces.map(s => (
                                    <KnowledgeSpaceItem
                                        key={s.id}
                                        space={s}
                                        type="joined"
                                        isActive={s.id === activeSpaceId}
                                        onSelect={onSpaceSelect}
                                        onUpdate={handleUpdateSpace}
                                        onDelete={handleDeleteSpace}
                                        onLeave={handleLeaveSpace}
                                        onPin={(id, pinned) => handlePinSpace(id, pinned, "joined")}
                                        onSettings={onSpaceSettings}
                                        onManageMembers={onManageMembers}
                                    />
                                ))}
                                {!joinedSpaces.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_knowledge.no_data")}</div>}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
