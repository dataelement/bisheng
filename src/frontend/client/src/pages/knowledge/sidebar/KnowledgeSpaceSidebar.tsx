import {
    ArrowLeftRightIcon,
    ChevronDown,
    Plus
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KnowledgeSpace, SpaceSortType, getMineSpacesApi, getJoinedSpacesApi } from "~/api/knowledge";
import { Button } from "~/components/ui/Button";
import NavToggle from "~/components/Nav/NavToggle";
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
    collapsed?: boolean;
    onCollapsedChange?: (collapsed: boolean) => void;
    /** When true, hide ONLY the expand toggle in collapsed mode (expand is provided elsewhere). */
    hideExpandToggleWhenCollapsed?: boolean;
}

// Sort cycle: update_time → name → update_time
const SORT_CYCLE = [SpaceSortType.UPDATE_TIME, SpaceSortType.NAME];

function getSortLabel(sort: SpaceSortType, localize: any) {
    return sort === SpaceSortType.NAME ? localize("com_knowledge.name") : localize("com_knowledge.recently_updated");
}

export function KnowledgeSpaceSidebar({
    activeSpaceId,
    onSpaceSelect,
    onCreateSpace,
    onSpaceSettings,
    onManageMembers,
    onKnowledgeSquare,
    collapsed: collapsedProp,
    onCollapsedChange,
    hideExpandToggleWhenCollapsed,
}: KnowledgeSpaceSidebarProps) {
    const localize = useLocalize();
    const [collapsedState, setCollapsedState] = useState(false);
    const collapsed = collapsedProp ?? collapsedState;
    const setCollapsed = (next: boolean) => {
        onCollapsedChange?.(next);
        if (collapsedProp === undefined) setCollapsedState(next);
    };
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [joinedCollapsed, setJoinedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SpaceSortType>(SpaceSortType.UPDATE_TIME);
    const [joinedSortBy, setJoinedSortBy] = useState<SpaceSortType>(SpaceSortType.UPDATE_TIME);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [isToggleHovering, setIsToggleHovering] = useState(false);

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
        <div className="relative flex-shrink-0">
            <div
                className={[
                    `h-full bg-white flex flex-col overflow-hidden ${collapsed ? "" : "border-r border-[#e5e6eb]"}`,
                    collapsed ? "w-0" : "w-60",
                ].join(" ")}
                style={{
                    transitionProperty: 'width',
                    transitionDuration: '300ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
            >
                {/* Top actions */}
                <div className={collapsed ? "px-0 py-5" : "px-3 py-5"}>
                    <div className={collapsed ? "flex items-center justify-center h-7" : "border-b border-[#e5e6eb] space-y-4 pb-4"}>
                        {!collapsed && <div className="px-2 flex justify-between items-center text-[16px] font-medium">
                            <span className="text-[#1d2129]">{localize("com_knowledge.knowledge_space")}</span>
                        </div>}
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
                    ].join(" ")}
                    style={{
                        transitionProperty: 'background-color',
                        transitionDuration: '350ms',
                        transitionTimingFunction: 'ease-in-out'
                    }}
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
            <NavToggle
                navVisible={!collapsed}
                onToggle={() => setCollapsed(!collapsed)}
                isHovering={isToggleHovering}
                setIsHovering={setIsToggleHovering}
                className="absolute top-1/2 left-0 z-[40]"
                translateX={230}
            />
        </div>
    );
}
