import { Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GroupedKnowledgeSpaces, KnowledgeSpace, SpaceLevel, SpaceRole, SpaceSortType, getGroupedSpacesApi } from "~/api/knowledge";
import { Button } from "~/components/ui/Button";
import NavToggle from "~/components/Nav/NavToggle";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";
import { SectionHeader } from "./SectionHeader";
import { useSpaceActions } from "../hooks/useSpaceActions";
import { useLocalize } from "~/hooks";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";
import { cn } from "~/utils";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { UserPopMenu } from "~/layouts/UserPopMenu";
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
}

// Sort cycle: update_time → name → update_time
const SORT_CYCLE = [SpaceSortType.UPDATE_TIME, SpaceSortType.NAME];
const DEFAULT_SECTION_SORTS: Record<SpaceLevel, SpaceSortType> = {
    [SpaceLevel.PUBLIC]: SpaceSortType.UPDATE_TIME,
    [SpaceLevel.DEPARTMENT]: SpaceSortType.UPDATE_TIME,
    [SpaceLevel.TEAM]: SpaceSortType.UPDATE_TIME,
    [SpaceLevel.PERSONAL]: SpaceSortType.UPDATE_TIME,
};

function getSortLabel(sort: SpaceSortType, localize: any) {
    return sort === SpaceSortType.NAME ? localize("com_knowledge.name") : localize("com_knowledge.recently_updated");
}

export function sortKnowledgeSpacesForSection(
    spaces: KnowledgeSpace[],
    sortBy: SpaceSortType,
): KnowledgeSpace[] {
    return [...spaces].sort((a, b) => {
        if (a.isPinned !== b.isPinned) {
            return a.isPinned ? -1 : 1;
        }
        if (sortBy === SpaceSortType.NAME) {
            return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
        }
        const timeA = Date.parse(a.updatedAt || "") || 0;
        const timeB = Date.parse(b.updatedAt || "") || 0;
        return timeB - timeA;
    });
}

export function getNextSectionSorts(
    currentSorts: Record<SpaceLevel, SpaceSortType>,
    level: SpaceLevel,
): Record<SpaceLevel, SpaceSortType> {
    const current = currentSorts[level];
    const next = SORT_CYCLE[(SORT_CYCLE.indexOf(current) + 1) % SORT_CYCLE.length];
    return { ...currentSorts, [level]: next };
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
    const [publicCollapsed, setPublicCollapsed] = useState(false);
    const [departmentCollapsed, setDepartmentCollapsed] = useState(false);
    const [teamCollapsed, setTeamCollapsed] = useState(false);
    const [personalCollapsed, setPersonalCollapsed] = useState(false);
    const [sectionSortBy, setSectionSortBy] = useState<Record<SpaceLevel, SpaceSortType>>(DEFAULT_SECTION_SORTS);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [isToggleHovering, setIsToggleHovering] = useState(false);

    const { data: groupedSpaces = {
        publicSpaces: [],
        departmentSpaces: [],
        teamSpaces: [],
        personalSpaces: [],
    }, isLoading } = useQuery({
        queryKey: ["knowledgeSpaces", "grouped"],
        queryFn: () => getGroupedSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
        placeholderData: (prev) => prev,
    });

    const sortedGroupedSpaces: GroupedKnowledgeSpaces = useMemo(() => ({
        publicSpaces: sortKnowledgeSpacesForSection(groupedSpaces.publicSpaces, sectionSortBy[SpaceLevel.PUBLIC]),
        departmentSpaces: sortKnowledgeSpacesForSection(groupedSpaces.departmentSpaces, sectionSortBy[SpaceLevel.DEPARTMENT]),
        teamSpaces: sortKnowledgeSpacesForSection(groupedSpaces.teamSpaces, sectionSortBy[SpaceLevel.TEAM]),
        personalSpaces: sortKnowledgeSpacesForSection(groupedSpaces.personalSpaces, sectionSortBy[SpaceLevel.PERSONAL]),
    }), [groupedSpaces, sectionSortBy]);

    const { publicSpaces, departmentSpaces, teamSpaces, personalSpaces } = sortedGroupedSpaces;
    const permissionSpaceIds = useMemo(
        () => Array.from(new Set([
            ...publicSpaces.map(s => s.id),
            ...departmentSpaces.map(s => s.id),
            ...teamSpaces.map(s => s.id),
            ...personalSpaces.map(s => s.id),
        ])),
        [publicSpaces, departmentSpaces, teamSpaces, personalSpaces],
    );
    const fullAccessSpaceIds = useMemo(
        () => [
            ...publicSpaces,
            ...departmentSpaces,
            ...teamSpaces,
            ...personalSpaces,
        ]
            .filter((space) => space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN)
            .map((space) => space.id),
        [publicSpaces, departmentSpaces, teamSpaces, personalSpaces],
    );
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(
        permissionSpaceIds,
        { fullAccessSpaceIds },
    );

    const getItemPermissions = (space: KnowledgeSpace) => {
        const isCreator = space.role === SpaceRole.CREATOR;
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
        groupedSpaces: sortedGroupedSpaces,
        onSpaceSelect,
    });

    // Auto-select first space when no space is active (mirrors ChannelSidebar)
    useEffect(() => {
        if (!activeSpaceId) {
            if (isLoading) return;

            if (departmentSpaces.length > 0) {
                onSpaceSelect(departmentSpaces[0]);
            } else if (publicSpaces.length > 0) {
                onSpaceSelect(publicSpaces[0]);
            } else if (teamSpaces.length > 0) {
                onSpaceSelect(teamSpaces[0]);
            } else if (personalSpaces.length > 0) {
                onSpaceSelect(personalSpaces[0]);
            }
        }
    }, [activeSpaceId, publicSpaces, departmentSpaces, teamSpaces, personalSpaces, isLoading, onSpaceSelect]);

    const toggleSort = (level: SpaceLevel) => {
        setSectionSortBy((prev) => getNextSectionSorts(prev, level));
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
                    `h-full bg-white flex flex-col overflow-hidden ${collapsed || mobileDrawerMode ? "" : "border-r border-[#e5e6eb]"}`,
                    mobileDrawerMode ? "w-full" : collapsed ? "w-0" : "w-60",
                ].join(" ")}
                style={mobileDrawerMode ? undefined : {
                    transitionProperty: 'width',
                    transitionDuration: '300ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
            >
                {mobileDrawerMode ? (
                    <MobileSidebarHeaderTabs
                        logoSrc={bsConfig?.sidebarIcon?.image}
                        onClose={onDrawerClose}
                        onLinkClick={(link) => {
                            if (link.closeDrawerOnNavigate) onDrawerClose?.();
                        }}
                    />
                ) : null}
                {/* Top actions */}
                <div className={collapsed ? "px-0 py-5" : mobileDrawerMode ? "px-3 pt-4 pb-6" : "px-3 py-5"}>
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
                        className="h-full overflow-y-auto overscroll-y-contain scroll-on-scroll space-y-4 px-3 pb-5"
                        onScroll={handleListScroll}
                        data-scrolling={isListScrolling ? "true" : "false"}
                    >
                        {[
                            {
                                title: localize("com_knowledge.department_spaces"),
                                spaces: departmentSpaces,
                                level: SpaceLevel.DEPARTMENT,
                                collapsed: departmentCollapsed,
                                setCollapsed: setDepartmentCollapsed,
                            },
                            {
                                title: localize("com_knowledge.public_spaces"),
                                spaces: publicSpaces,
                                level: SpaceLevel.PUBLIC,
                                collapsed: publicCollapsed,
                                setCollapsed: setPublicCollapsed,
                            },
                            {
                                title: localize("com_knowledge.team_spaces"),
                                spaces: teamSpaces,
                                level: SpaceLevel.TEAM,
                                collapsed: teamCollapsed,
                                setCollapsed: setTeamCollapsed,
                            },
                            {
                                title: localize("com_knowledge.personal_spaces"),
                                spaces: personalSpaces,
                                level: SpaceLevel.PERSONAL,
                                collapsed: personalCollapsed,
                                setCollapsed: setPersonalCollapsed,
                            },
                        ].map((section) => (
                            <div key={section.level}>
                                <SectionHeader
                                    title={section.title}
                                    collapsed={section.collapsed}
                                    onToggle={() => section.setCollapsed(!section.collapsed)}
                                    sortText={getSortLabel(sectionSortBy[section.level], localize)}
                                    onSort={() => toggleSort(section.level)}
                                />
                                {!section.collapsed && (
                                    <div className="space-y-1">
                                        {section.spaces.map(s => (
                                            <KnowledgeSpaceItem
                                                key={s.id}
                                                space={s}
                                                type={section.level}
                                                isActive={s.id === activeSpaceId}
                                                onSelect={onSpaceSelect}
                                                onUpdate={handleUpdateSpace}
                                                onDelete={handleDeleteSpace}
                                                onLeave={handleLeaveSpace}
                                                onPin={(id, pinned) => handlePinSpace(id, pinned, section.level)}
                                                onSettings={onSpaceSettings}
                                                onManageMembers={onManageMembers}
                                                {...getItemPermissions(s)}
                                            />
                                        ))}
                                        {!section.spaces.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_knowledge.no_data")}</div>}
                                    </div>
                                )}
                            </div>
                        ))}
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
                translateX={240}
            />
        </div>
    );
}
