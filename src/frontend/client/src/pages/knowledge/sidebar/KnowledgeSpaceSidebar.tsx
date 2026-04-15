import {
    ArrowLeftRightIcon,
    ChevronDown,
    Plus,
    X
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
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "~/utils";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { appsSectionLinkTarget, lastSectionPaths } from "~/layouts/appModuleNavPaths";
import { UserPopMenu } from "~/layouts/UserPopMenu";
import BookOpenIcon from "~/components/ui/icon/BookOpen";
import GlobeIcon from "~/components/ui/icon/Globe";
import HomeIcon from "~/components/ui/icon/Home";
import LinkIcon from "~/components/ui/icon/Link";

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
    /** H5：置于移动端抽屉内，隐藏 PC 折叠把手，宽度随父容器 */
    mobileDrawerMode?: boolean;
    /** H5 抽屉：右上角关闭 */
    onDrawerClose?: () => void;
}

// Sort cycle: update_time → name → update_time
const SORT_CYCLE = [SpaceSortType.UPDATE_TIME, SpaceSortType.NAME];

function KnowledgeMobileDrawerNavTabs({ onAfterPick }: { onAfterPick?: () => void }) {
    const { pathname } = useLocation();
    const localize = useLocalize();
    const { user } = useAuthContext();
    const plugins: string[] | null = Array.isArray((user as { plugins?: unknown })?.plugins)
        ? ((user as { plugins: string[] }).plugins)
        : null;
    const showSubscriptionTab = plugins ? plugins.includes("subscription") : true;
    const showKnowledgeSpaceTab = plugins ? plugins.includes("knowledge_space") : true;
    const links = [
        {
            section: "home",
            to: lastSectionPaths.home || "/c/new",
            icon: HomeIcon,
            label: localize("com_nav_home"),
            isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
            closeOnPick: true,
        },
        {
            section: "apps",
            to: appsSectionLinkTarget(),
            icon: GlobeIcon,
            label: localize("com_nav_app_center"),
            isActive: /^\/apps(\/|$)/.test(pathname) || /^\/app\//.test(pathname),
            closeOnPick: true,
        },
        {
            section: "channel",
            to: lastSectionPaths.channel || "/channel",
            icon: LinkIcon,
            label: localize("com_ui_channel"),
            isActive: pathname.startsWith("/channel"),
            closeOnPick: false,
        },
        {
            section: "knowledge",
            to: lastSectionPaths.knowledge || "/knowledge",
            icon: BookOpenIcon,
            label: localize("com_knowledge.knowledge_space"),
            isActive: pathname.startsWith("/knowledge"),
            closeOnPick: false,
        },
    ].filter((link) => {
        if (link.section === "channel") return showSubscriptionTab;
        if (link.section === "knowledge") return showKnowledgeSpaceTab;
        return true;
    });

    return (
        <div className="flex shrink-0 items-stretch gap-1 border-b border-[#e5e6eb] px-2 py-2">
            {links.map((link) => {
                const Icon = link.icon;
                return (
                    <NavLink
                        key={link.section}
                        to={link.to}
                        title={link.label}
                        onClick={() => {
                            if (link.closeOnPick) onAfterPick?.();
                        }}
                        className={cn(
                            "flex min-w-0 flex-1 flex-col items-center justify-center rounded-lg py-1.5 transition-colors hover:bg-[#f2f3f5]",
                            link.isActive && "bg-[#e6edfc]",
                        )}
                    >
                        <Icon className={cn("size-5 shrink-0", link.isActive ? "text-[#335CFF]" : "text-[#818181]")} />
                    </NavLink>
                );
            })}
        </div>
    );
}

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
    mobileDrawerMode = false,
    onDrawerClose,
}: KnowledgeSpaceSidebarProps) {
    const localize = useLocalize();
    const { data: bsConfig } = useGetBsConfig();
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

    useEffect(() => {
        if (mobileDrawerMode) setCollapsed(false);
    }, [mobileDrawerMode]);

    return (
        <div className={`relative flex-shrink-0 ${mobileDrawerMode ? "h-full min-h-0 w-full" : ""}`}>
            <div
                className={[
                    `h-full bg-white flex flex-col overflow-hidden ${collapsed ? "" : "border-r border-[#e5e6eb]"}`,
                    mobileDrawerMode ? "w-full" : collapsed ? "w-0" : "w-60",
                ].join(" ")}
                style={mobileDrawerMode ? undefined : {
                    transitionProperty: 'width',
                    transitionDuration: '300ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
            >
                {mobileDrawerMode ? (
                    <div className="shrink-0 border-b border-[#e5e6eb] px-3 py-2.5">
                        <div className="flex items-center justify-between">
                            {bsConfig?.sidebarIcon?.image ? (
                                <img
                                    className="h-8 w-8 rounded-md object-contain"
                                    src={bsConfig.sidebarIcon.image}
                                    alt={localize("com_nav_home")}
                                />
                            ) : (
                                <div className="h-8 w-8 rounded-md bg-[#F2F3F5]" />
                            )}
                            {onDrawerClose ? (
                                <button
                                    type="button"
                                    onClick={onDrawerClose}
                                    aria-label={localize("com_nav_close_sidebar")}
                                    className="inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
                                >
                                    <X className="size-4" />
                                </button>
                            ) : null}
                        </div>
                    </div>
                ) : null}
                {mobileDrawerMode ? <KnowledgeMobileDrawerNavTabs onAfterPick={onDrawerClose} /> : null}
                {/* Top actions */}
                <div className={collapsed ? "px-0 py-5" : mobileDrawerMode ? "px-3 py-3" : "px-3 py-5"}>
                    {mobileDrawerMode ? (
                        <div className="border-b border-[#e5e6eb] pb-3">
                            <Button
                                variant="secondary"
                                onClick={onCreateSpace}
                                className="h-9 w-full gap-1 border border-[#EBECF0] bg-white text-[13px] text-[#212121] hover:bg-[#F7F8FA]"
                            >
                                <Plus className="size-4" />
                                {localize("com_knowledge.create")}
                            </Button>
                        </div>
                    ) : null}
                    <div className={cn(
                        collapsed ? "flex items-center justify-center h-7" : "border-b border-[#e5e6eb] space-y-4 pb-4",
                        mobileDrawerMode && "hidden"
                    )}>
                        {!collapsed && !mobileDrawerMode && <div className="px-2 flex justify-between items-center text-[16px] font-medium">
                            <span className="text-[#1d2129]">{localize("com_knowledge.knowledge_space")}</span>
                        </div>}
                        {!collapsed && (
                            <div className="flex items-center gap-3">
                                <Button
                                    variant="secondary"
                                    onClick={onCreateSpace}
                                    className={cn(
                                        "flex-1 h-8 gap-1 text-[13px] text-[#212121]",
                                        mobileDrawerMode
                                            ? "border border-[#EBECF0] bg-white hover:bg-[#F7F8FA]"
                                            : "border-none bg-[#F7F7F7] hover:bg-[#E5E6EB]"
                                    )}
                                >
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
                {mobileDrawerMode ? (
                    <div className="shrink-0 border-t border-[#ececec] px-2 pb-2 pt-1">
                        <UserPopMenu variant="drawer" />
                    </div>
                ) : null}
            </div>
            <NavToggle
                navVisible={!collapsed}
                onToggle={() => setCollapsed(!collapsed)}
                isHovering={isToggleHovering}
                setIsHovering={setIsToggleHovering}
                className={`absolute top-1/2 left-0 z-[40] ${mobileDrawerMode ? "hidden" : ""}`}
                translateX={230}
            />
        </div>
    );
}
