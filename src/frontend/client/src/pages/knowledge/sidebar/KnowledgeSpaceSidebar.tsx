import {
    ArrowLeftRightIcon,
    ChevronDown,
    Plus,
    X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KnowledgeSpace, SpaceRole, SpaceSortType, getMineSpacesApi, getJoinedSpacesApi, getDepartmentSpacesApi } from "~/api/knowledge";
import { Button } from "~/components/ui/Button";
import NavToggle from "~/components/Nav/NavToggle";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";
import { SectionHeader } from "./SectionHeader";
import { useSpaceActions } from "../hooks/useSpaceActions";
import { useLocalize } from "~/hooks";
import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { UserPopMenu } from "~/layouts/UserPopMenu";
import { HubModuleNavTabs } from "~/components/Nav/HubModuleNavTabs";
import { MobileSidebarHeaderTabs } from "~/components/Nav/MobileSidebarHeaderTabs";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";

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
    /** H5 标题下拉：跳过模块 Tabs 与顶部创建按钮,只渲染空间树形列表 */
    compactMode?: boolean;
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
    mobileDrawerMode = false,
    onDrawerClose,
    compactMode = false,
}: KnowledgeSpaceSidebarProps) {
    const localize = useLocalize();
    const { data: bsConfig } = useGetBsConfig();
    const [collapsedState, setCollapsedState] = useState(false);

    // ─── Resizable sidebar width ────────────────────────────────────────
    const SIDEBAR_WIDTH_KEY = "knowledge-sidebar-width";
    const MIN_SIDEBAR_WIDTH = 200;
    const MAX_SIDEBAR_WIDTH = 480;
    const DEFAULT_SIDEBAR_WIDTH = 240;
    const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
        if (typeof window === "undefined") return DEFAULT_SIDEBAR_WIDTH;
        const stored = parseInt(localStorage.getItem(SIDEBAR_WIDTH_KEY) || "", 10);
        return Number.isFinite(stored) && stored >= MIN_SIDEBAR_WIDTH && stored <= MAX_SIDEBAR_WIDTH
            ? stored
            : DEFAULT_SIDEBAR_WIDTH;
    });
    const [isResizing, setIsResizing] = useState(false);
    const dragStartRef = useRef<{ startX: number; startWidth: number } | null>(null);
    const sidebarWidthRef = useRef(sidebarWidth);
    sidebarWidthRef.current = sidebarWidth;

    const handleResizeStart = (e: React.MouseEvent) => {
        e.preventDefault();
        dragStartRef.current = { startX: e.clientX, startWidth: sidebarWidthRef.current };
        setIsResizing(true);
    };

    // Double-click the resize handle → reset to default width
    const handleResizeReset = () => {
        setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
        if (typeof window !== "undefined") localStorage.setItem(SIDEBAR_WIDTH_KEY, String(DEFAULT_SIDEBAR_WIDTH));
    };

    useEffect(() => {
        if (!isResizing) return;
        const onMove = (e: MouseEvent) => {
            const start = dragStartRef.current;
            if (!start) return;
            const next = Math.max(
                MIN_SIDEBAR_WIDTH,
                Math.min(MAX_SIDEBAR_WIDTH, start.startWidth + (e.clientX - start.startX)),
            );
            setSidebarWidth(next);
        };
        const onUp = () => {
            setIsResizing(false);
            dragStartRef.current = null;
            if (typeof window !== "undefined") {
                localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidthRef.current));
            }
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        // Suppress text selection + force resize cursor while dragging.
        const prevCursor = document.body.style.cursor;
        const prevSelect = document.body.style.userSelect;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        return () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = prevCursor;
            document.body.style.userSelect = prevSelect;
        };
    }, [isResizing]);
    const collapsed = collapsedProp ?? collapsedState;
    const setCollapsed = (next: boolean) => {
        onCollapsedChange?.(next);
        if (collapsedProp === undefined) setCollapsedState(next);
    };
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [joinedCollapsed, setJoinedCollapsed] = useState(false);
    const [departmentCollapsed, setDepartmentCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SpaceSortType>(SpaceSortType.UPDATE_TIME);
    const [joinedSortBy, setJoinedSortBy] = useState<SpaceSortType>(SpaceSortType.UPDATE_TIME);
    const [departmentSortBy, setDepartmentSortBy] = useState<SpaceSortType>(SpaceSortType.UPDATE_TIME);
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

    // Fetch department space list
    const { data: departmentSpaces = [], isLoading: isDepartmentLoading } = useQuery({
        queryKey: ["knowledgeSpaces", "department", departmentSortBy],
        queryFn: () => getDepartmentSpacesApi({ order_by: departmentSortBy }),
        placeholderData: (prev) => prev,
    });

    // Filter department spaces out of other sections to avoid duplication
    const departmentSpaceIds = new Set(departmentSpaces.map(s => s.id));
    const filteredCreatedSpaces = createdSpaces.filter(s => !departmentSpaceIds.has(s.id));
    const filteredJoinedSpaces = joinedSpaces.filter(s => !departmentSpaceIds.has(s.id));
    const permissionSpaceIds = useMemo(
        () => Array.from(new Set([
            ...departmentSpaces.map(s => s.id),
            ...filteredCreatedSpaces.map(s => s.id),
            ...filteredJoinedSpaces.map(s => s.id),
        ])),
        [departmentSpaces, filteredCreatedSpaces, filteredJoinedSpaces],
    );
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(permissionSpaceIds);

    const getItemPermissions = (space: KnowledgeSpace, type: "created" | "joined" | "department") => {
        const isCreator = type === "created" || space.role === SpaceRole.CREATOR;
        const canEditSpace = isCreator || hasKnowledgeSpacePermission(
            spaceActionPermissions,
            space.id,
            "edit_space",
        );
        const canDeleteSpace = isCreator || hasKnowledgeSpacePermission(
            spaceActionPermissions,
            space.id,
            "delete_space",
        );
        const canManageMembers = isCreator || hasKnowledgeSpacePermission(
            spaceActionPermissions,
            space.id,
            "manage_space_relation",
        );
        return { canEditSpace, canDeleteSpace, canManageMembers };
    };

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
        departmentSortBy,
        createdSpaces: filteredCreatedSpaces,
        joinedSpaces: filteredJoinedSpaces,
        departmentSpaces,
        onSpaceSelect,
    });

    // Auto-select first space when no space is active (mirrors ChannelSidebar)
    useEffect(() => {
        if (!activeSpaceId) {
            if (isCreatedLoading || isJoinedLoading || isDepartmentLoading) return;

            if (departmentSpaces.length > 0) {
                onSpaceSelect(departmentSpaces[0]);
            } else if (filteredCreatedSpaces.length > 0) {
                onSpaceSelect(filteredCreatedSpaces[0]);
            } else if (filteredJoinedSpaces.length > 0) {
                onSpaceSelect(filteredJoinedSpaces[0]);
            }
        }
    }, [activeSpaceId, departmentSpaces, filteredCreatedSpaces, filteredJoinedSpaces, isCreatedLoading, isJoinedLoading, isDepartmentLoading, onSpaceSelect]);

    const toggleSort = (type: "created" | "joined" | "department") => {
        if (type === "created") {
            const next = SORT_CYCLE[(SORT_CYCLE.indexOf(createdSortBy) + 1) % SORT_CYCLE.length];
            queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "mine", createdSortBy] });
            setCreatedSortBy(next);
        } else if (type === "department") {
            const next = SORT_CYCLE[(SORT_CYCLE.indexOf(departmentSortBy) + 1) % SORT_CYCLE.length];
            queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "department", departmentSortBy] });
            setDepartmentSortBy(next);
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
        <div className={cn("relative h-full min-h-0 shrink-0", mobileDrawerMode && "w-full")}>
            <div
                className={[
                    `h-full bg-[#FBFBFB] flex flex-col overflow-hidden ${collapsed || mobileDrawerMode ? "" : "border-r-[0.5px] border-[#e5e6eb]"}`,
                    mobileDrawerMode ? "w-full" : collapsed ? "w-0" : "",
                ].join(" ")}
                style={mobileDrawerMode ? undefined : {
                    width: collapsed ? 0 : sidebarWidth,
                    // Disable the width transition while the user is actively dragging,
                    // otherwise the resize feels laggy and rubber-bandy.
                    transitionProperty: isResizing ? 'none' : 'width',
                    transitionDuration: '300ms',
                    transitionTimingFunction: 'ease-in-out',
                }}
            >
                {mobileDrawerMode && !compactMode ? (
                    <MobileSidebarHeaderTabs
                        logoSrc={bsConfig?.sidebarIcon?.image}
                        onClose={onDrawerClose}
                        onLinkClick={(link) => {
                            if (link.closeDrawerOnNavigate) onDrawerClose?.();
                        }}
                    />
                ) : null}
                {/* Top actions */}
                <div className={cn(
                    collapsed ? "px-0 py-5" : mobileDrawerMode ? "px-3 pt-4 pb-6" : "px-3 pt-5 pb-4",
                    compactMode && "hidden",
                )}>
                    {mobileDrawerMode ? (
                        <div>
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
                        collapsed ? "flex items-center justify-center h-7" : "",
                        mobileDrawerMode && "hidden"
                    )}>
                        {!collapsed && !mobileDrawerMode && <div className="flex justify-between items-center text-[16px] font-medium">
                            <span className="text-[#1d2129]">{localize("com_knowledge.knowledge_space")}</span>
                        </div>}
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
                        className="h-full overflow-y-auto overscroll-y-contain scroll-on-scroll px-3 pb-5"
                        onScroll={handleListScroll}
                        data-scrolling={isListScrolling ? "true" : "false"}
                    >
                        {/* Department spaces — always on top per PRD */}
                        {departmentSpaces.length > 0 && (
                            <div className="pt-0 pb-4">
                                <SectionHeader
                                    title={localize("com_knowledge.department_spaces")}
                                    collapsed={departmentCollapsed}
                                    onToggle={() => setDepartmentCollapsed(!departmentCollapsed)}
                                    sortText={getSortLabel(departmentSortBy, localize)}
                                    onSort={() => toggleSort("department")}
                                />
                                {!departmentCollapsed && (
                                    <div className="space-y-0.5">
                                        {departmentSpaces.map(s => (
                                            <KnowledgeSpaceItem
                                                key={s.id}
                                                space={s}
                                                type="department"
                                                isActive={s.id === activeSpaceId}
                                                onSelect={onSpaceSelect}
                                                onUpdate={handleUpdateSpace}
                                                onDelete={handleDeleteSpace}
                                                onLeave={handleLeaveSpace}
                                                onPin={(id, pinned) => handlePinSpace(id, pinned, "department")}
                                                onSettings={onSpaceSettings}
                                                onManageMembers={onManageMembers}
                                                {...getItemPermissions(s, "department")}
                                            />
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* My created */}
                        <div className="pb-4">
                            <SectionHeader
                                title={localize("com_knowledge.created_by_me")}
                                collapsed={createdCollapsed}
                                onToggle={() => setCreatedCollapsed(!createdCollapsed)}
                                sortText={getSortLabel(createdSortBy, localize)}
                                onSort={() => toggleSort("created")}
                                onAdd={onCreateSpace}
                                addLabel={localize("com_knowledge.create")}
                            />
                            {!createdCollapsed && (
                                <div className="space-y-0.5">
                                    {filteredCreatedSpaces.map(s => (
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
                                            {...getItemPermissions(s, "created")}
                                        />
                                    ))}
                                    {!filteredCreatedSpaces.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_knowledge.no_data")}</div>}
                                </div>
                            )}
                        </div>

                        {/* Joined */}
                        <div className="pb-4">
                            <SectionHeader
                                title={localize("com_knowledge.joined_by_me")}
                                collapsed={joinedCollapsed}
                                onToggle={() => setJoinedCollapsed(!joinedCollapsed)}
                                sortText={getSortLabel(joinedSortBy, localize)}
                                onSort={() => toggleSort("joined")}
                            />
                            {!joinedCollapsed && (
                                <div className="space-y-0.5">
                                    {filteredJoinedSpaces.map(s => (
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
                                            {...getItemPermissions(s, "joined")}
                                        />
                                    ))}
                                    {!filteredJoinedSpaces.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_knowledge.no_data")}</div>}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
                {!collapsed && !mobileDrawerMode && !compactMode && (
                    <div className="shrink-0 px-3 py-3">
                        <Button
                            variant="secondary"
                            onClick={() => onKnowledgeSquare?.()}
                            className="h-8 w-full gap-1 rounded-[6px] border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#212121] hover:bg-[#F4F4F4]"
                        >
                            <Outlined.BlocksAndArrows className="size-4" />
                            {localize("com_knowledge.go_to_square")}
                        </Button>
                    </div>
                )}
                {mobileDrawerMode && !compactMode ? (
                    <div className="shrink-0 border-t border-[#ececec] px-2 pb-2 pt-1">
                        <UserPopMenu variant="drawer" />
                    </div>
                ) : null}
            </div>
            {/* Resize handle — a thin invisible strip sitting on the right edge of
                the sidebar. Drag horizontally to resize; double-click to reset. */}
            {!collapsed && !mobileDrawerMode && (
                <div
                    role="separator"
                    aria-orientation="vertical"
                    aria-label="Resize sidebar"
                    onMouseDown={handleResizeStart}
                    onDoubleClick={handleResizeReset}
                    className={cn(
                        // z below NavToggle (z-40) so the collapse button keeps capturing clicks
                        // in its small area; everywhere else along the edge the resize handle wins.
                        "absolute top-0 z-[35] h-full w-[6px] -translate-x-1/2 cursor-col-resize",
                        // Subtle visual feedback: thin accent line on hover/active.
                        "after:absolute after:right-1/2 after:top-0 after:h-full after:w-px after:translate-x-1/2",
                        "after:bg-transparent hover:after:bg-[#165dff]/40",
                        isResizing && "after:bg-[#165dff]",
                    )}
                    style={{ left: sidebarWidth }}
                />
            )}
            <NavToggle
                navVisible={!collapsed}
                onToggle={() => setCollapsed(!collapsed)}
                isHovering={isToggleHovering}
                setIsHovering={setIsToggleHovering}
                className={`absolute top-1/2 left-0 z-[40] ${mobileDrawerMode ? "hidden" : ""}`}
                translateX={collapsed ? 0 : sidebarWidth}
            />
        </div>
    );
}
