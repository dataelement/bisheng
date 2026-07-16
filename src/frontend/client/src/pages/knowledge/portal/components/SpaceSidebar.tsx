import type { MutableRefObject } from "react";
import { useCallback, useRef, useState } from "react";
import {
    LogOut,
    MoreHorizontal,
    Pin,
    PinOff,
    Plus,
    Settings,
    UsersRound,
    X,
} from "lucide-react";
import { GlobalSearchPanel } from "./GlobalSearchPanel";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    SidebarListMoreMenuContent,
    SidebarListMoreMenuDivider,
    sidebarListMoreMenuDangerIconClassName,
    sidebarListMoreMenuDangerItemClassName,
    sidebarListMoreMenuDangerLabelClassName,
    sidebarListMoreMenuIconClassName,
    sidebarListMoreMenuItemClassName,
    sidebarListMoreMenuLabelClassName,
} from "~/components/SidebarListMoreMenu";
import { SpaceLevel } from "~/api/knowledge";
import type { KnowledgeSpace } from "~/api/knowledge";
import {
    PORTAL_SIDEBAR_TITLE_ICON_SRC,
} from "../constants";
import {
    DepartmentSpaceGroupIcon,
    KnowledgeSpaceIcon,
    NewKnowledgeSpaceIcon,
    PersonalSpaceGroupIcon,
    PublicSpaceGroupIcon,
    SidebarCollapseIcon,
    TeamSpaceGroupIcon,
} from "./SpaceIcons";
import type { SpaceGroup, SpaceGroupKey } from "../types";
import { isFavoriteSpace } from "../favoriteView";
import { resolveAssetUrl } from "../utils";
import s from "../PortalKnowledgeWorkbench.module.css";

const SPACE_GROUP_ICONS = {
    public: PublicSpaceGroupIcon,
    department: DepartmentSpaceGroupIcon,
    team: TeamSpaceGroupIcon,
    personal: PersonalSpaceGroupIcon,
} satisfies Record<SpaceGroupKey, React.ComponentType<React.SVGProps<SVGSVGElement>>>;

interface SpacePermissions {
    canEditSpace: boolean;
    canDeleteSpace: boolean;
    canManageMembers: boolean;
}

interface SpaceSidebarProps {
    groups: SpaceGroup[];
    activeSpaceId?: string;
    collapsed: boolean;
    expandedGroups: Record<SpaceGroupKey, boolean>;
    groupRefs: MutableRefObject<Record<SpaceGroupKey, HTMLDivElement | null>>;
    createOptionsLoading: boolean;
    createPermissionByLevel: Record<SpaceLevel, boolean>;
    spaceLoading: boolean;
    spaceMenuOpenId: string | null;
    getSpacePermissions: (space: KnowledgeSpace) => SpacePermissions;
    onRestoreSidebar: (groupKey?: SpaceGroupKey) => void;
    onCollapseSidebar: () => void;
    onToggleGroup: (groupKey: SpaceGroupKey) => void;
    onOpenCreateSpace: (group: SpaceGroup) => void;
    onSelectSpace: (space: KnowledgeSpace) => void;
    onSpaceMenuOpenChange: (spaceId: string, open: boolean) => void;
    onOpenSpaceSettings: (space: KnowledgeSpace) => void;
    onOpenSpaceMembers: (space: KnowledgeSpace) => void;
    onPinSpace: (space: KnowledgeSpace, pinned: boolean, group: SpaceGroup) => void;
    /** System admins may drag to define the shared order of non-personal levels. */
    canReorderSpaces?: boolean;
    onReorderSpace?: (
        space: KnowledgeSpace,
        prevSpaceId: string | null,
        nextSpaceId: string | null,
        group: SpaceGroup,
    ) => void;
    onDeleteSpace: (space: KnowledgeSpace) => void;
    onLeaveSpace: (space: KnowledgeSpace) => void;
    onGlobalSearchSelectFile: (spaceId: number, fileId: number, fileName: string) => void;
}

/** Where a dragged space would land relative to the row under the pointer. */
type DropPosition = "before" | "after";

interface SpaceDragState {
    groupKey: SpaceGroupKey;
    spaceId: string;
}

interface SpaceDropTarget {
    spaceId: string;
    position: DropPosition;
}

function SpaceMenu({
    space,
    group,
    open,
    permissions,
    onOpenChange,
    onOpenSpaceSettings,
    onOpenSpaceMembers,
    onPinSpace,
    onDeleteSpace,
    onLeaveSpace,
}: {
    space: KnowledgeSpace;
    group: SpaceGroup;
    open: boolean;
    permissions: SpacePermissions;
    onOpenChange: (open: boolean) => void;
    onOpenSpaceSettings: (space: KnowledgeSpace) => void;
    onOpenSpaceMembers: (space: KnowledgeSpace) => void;
    onPinSpace: (space: KnowledgeSpace, pinned: boolean, group: SpaceGroup) => void;
    onDeleteSpace: (space: KnowledgeSpace) => void;
    onLeaveSpace: (space: KnowledgeSpace) => void;
}) {
    // 『我的收藏』为系统库：隐藏 空间设置/成员管理/删除 等操作。
    // 所有个人知识库均不支持置顶。
    const isFavorite = isFavoriteSpace(space);
    const canPin = group.level !== SpaceLevel.PERSONAL;
    const showDangerAction = (permissions.canDeleteSpace || Boolean(space.canUnsubscribe)) && !isFavorite;
    return (
        <DropdownMenu onOpenChange={onOpenChange}>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    className={`${s.spaceMenuButton} ${open ? s.spaceMenuButtonOpen : ""}`}
                    aria-label={`更多${space.name}操作`}
                    title="更多操作"
                    onClick={(event) => event.stopPropagation()}
                >
                    <MoreHorizontal size={14} />
                </button>
            </DropdownMenuTrigger>
            <SidebarListMoreMenuContent onClick={(event) => event.stopPropagation()}>
                {permissions.canEditSpace && !isFavorite ? (
                    <DropdownMenuItem
                        className={sidebarListMoreMenuItemClassName}
                        onClick={() => onOpenSpaceSettings(space)}
                    >
                        <Settings className={sidebarListMoreMenuIconClassName} />
                        <span className={sidebarListMoreMenuLabelClassName}>空间设置</span>
                    </DropdownMenuItem>
                ) : null}
                {permissions.canManageMembers && !isFavorite ? (
                    <DropdownMenuItem
                        className={sidebarListMoreMenuItemClassName}
                        onClick={() => onOpenSpaceMembers(space)}
                    >
                        <UsersRound className={sidebarListMoreMenuIconClassName} />
                        <span className={sidebarListMoreMenuLabelClassName}>成员管理</span>
                    </DropdownMenuItem>
                ) : null}
                {canPin ? (
                    <DropdownMenuItem
                        className={sidebarListMoreMenuItemClassName}
                        onClick={() => onPinSpace(space, !space.isPinned, group)}
                    >
                        {space.isPinned ? (
                            <>
                                <PinOff className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>取消置顶</span>
                            </>
                        ) : (
                            <>
                                <Pin className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>置顶空间</span>
                            </>
                        )}
                    </DropdownMenuItem>
                ) : null}
                {showDangerAction ? (
                    <>
                        <SidebarListMoreMenuDivider />
                        <DropdownMenuItem
                            className={sidebarListMoreMenuDangerItemClassName}
                            onClick={() => {
                                if (permissions.canDeleteSpace) {
                                    onDeleteSpace(space);
                                    return;
                                }
                                onLeaveSpace(space);
                            }}
                        >
                            {permissions.canDeleteSpace ? (
                                <X className={sidebarListMoreMenuDangerIconClassName} />
                            ) : (
                                <LogOut className={sidebarListMoreMenuDangerIconClassName} />
                            )}
                            <span className={sidebarListMoreMenuDangerLabelClassName}>
                                {permissions.canDeleteSpace ? "删除空间" : "退出空间"}
                            </span>
                        </DropdownMenuItem>
                    </>
                ) : null}
            </SidebarListMoreMenuContent>
        </DropdownMenu>
    );
}

const SIDEBAR_WIDTH_KEY = "portal_knowledge_sidebar_width";
const SIDEBAR_MIN_WIDTH = 160;
const SIDEBAR_MAX_WIDTH = 480;
const SIDEBAR_DEFAULT_WIDTH = 280;

function getSavedWidth(): number {
    try {
        const v = localStorage.getItem(SIDEBAR_WIDTH_KEY);
        if (v) {
            const n = parseInt(v, 10);
            if (n >= SIDEBAR_MIN_WIDTH && n <= SIDEBAR_MAX_WIDTH) return n;
        }
    } catch { /* ignore */ }
    return SIDEBAR_DEFAULT_WIDTH;
}

export function SpaceSidebar({
    groups,
    activeSpaceId,
    collapsed,
    expandedGroups,
    groupRefs,
    createOptionsLoading,
    createPermissionByLevel,
    spaceLoading,
    spaceMenuOpenId,
    getSpacePermissions,
    onRestoreSidebar,
    onCollapseSidebar,
    onToggleGroup,
    onOpenCreateSpace,
    onSelectSpace,
    onSpaceMenuOpenChange,
    onOpenSpaceSettings,
    onOpenSpaceMembers,
    onPinSpace,
    canReorderSpaces = false,
    onReorderSpace,
    onDeleteSpace,
    onLeaveSpace,
    onGlobalSearchSelectFile,
}: SpaceSidebarProps) {
    const [sidebarWidth, setSidebarWidth] = useState(getSavedWidth);
    const [spaceDrag, setSpaceDrag] = useState<SpaceDragState | null>(null);
    const [spaceDropTarget, setSpaceDropTarget] = useState<SpaceDropTarget | null>(null);
    const isDraggingRef = useRef(false);
    const dragStartXRef = useRef(0);
    const dragStartWidthRef = useRef(0);

    const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        isDraggingRef.current = true;
        dragStartXRef.current = e.clientX;
        dragStartWidthRef.current = sidebarWidth;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";

        const onMouseMove = (ev: MouseEvent) => {
            if (!isDraggingRef.current) return;
            const delta = ev.clientX - dragStartXRef.current;
            const next = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, dragStartWidthRef.current + delta));
            setSidebarWidth(next);
        };
        const onMouseUp = () => {
            isDraggingRef.current = false;
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            setSidebarWidth(prev => {
                try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(prev)); } catch { /* ignore */ }
                return prev;
            });
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);
        };
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    }, [sidebarWidth]);

    // Personal spaces are per-user, so there is no shared order to define for them.
    const isGroupReorderable = useCallback((group: SpaceGroup) => (
        canReorderSpaces && Boolean(onReorderSpace) && group.level !== SpaceLevel.PERSONAL
    ), [canReorderSpaces, onReorderSpace]);

    const handleSpaceDragStart = useCallback((group: SpaceGroup, space: KnowledgeSpace) => {
        setSpaceDrag({ groupKey: group.key, spaceId: space.id });
    }, []);

    const handleSpaceDragEnd = useCallback(() => {
        setSpaceDrag(null);
        setSpaceDropTarget(null);
    }, []);

    const handleSpaceDragOver = useCallback((
        event: React.DragEvent<HTMLDivElement>,
        group: SpaceGroup,
        space: KnowledgeSpace,
    ) => {
        // Only a drag started in this same group can be dropped here.
        if (!spaceDrag || spaceDrag.groupKey !== group.key || spaceDrag.spaceId === space.id) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const bounds = event.currentTarget.getBoundingClientRect();
        const position: DropPosition = event.clientY < bounds.top + bounds.height / 2 ? "before" : "after";
        setSpaceDropTarget((prev) => (
            prev && prev.spaceId === space.id && prev.position === position
                ? prev
                : { spaceId: space.id, position }
        ));
    }, [spaceDrag]);

    const handleSpaceDrop = useCallback((
        event: React.DragEvent<HTMLDivElement>,
        group: SpaceGroup,
        target: KnowledgeSpace,
    ) => {
        event.preventDefault();
        const dropPosition = spaceDropTarget?.spaceId === target.id ? spaceDropTarget.position : "before";
        const dragged = spaceDrag && spaceDrag.groupKey === group.key
            ? group.spaces.find((item) => item.id === spaceDrag.spaceId)
            : undefined;
        handleSpaceDragEnd();
        if (!dragged || dragged.id === target.id || !onReorderSpace) return;

        // Resolve the neighbours the row lands between, ignoring the dragged row itself
        // — that pair is exactly what the backend needs to place it.
        const remaining = group.spaces.filter((item) => item.id !== dragged.id);
        const targetIndex = remaining.findIndex((item) => item.id === target.id);
        if (targetIndex < 0) return;
        const insertAt = dropPosition === "before" ? targetIndex : targetIndex + 1;
        const prevSpace = remaining[insertAt - 1] ?? null;
        const nextSpace = remaining[insertAt] ?? null;
        onReorderSpace(dragged, prevSpace?.id ?? null, nextSpace?.id ?? null, group);
    }, [handleSpaceDragEnd, onReorderSpace, spaceDrag, spaceDropTarget]);

    return (
        <aside
            className={`${s.spaceSidebar} ${collapsed ? s.spaceSidebarCollapsed : ""}`}
            style={collapsed ? undefined : { width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
        >
            {collapsed ? (
                <div className={s.collapsedSidebar} aria-label="知识库分组快捷栏">
                    <div className={s.collapsedHeader}>
                        <button
                            type="button"
                            className={s.spaceHeaderCollapse}
                            aria-label="展开知识库侧栏"
                            title="展开"
                            onClick={() => onRestoreSidebar()}
                        >
                            <SidebarCollapseIcon
                                className={s.spaceHeaderCollapseIcon}
                                style={{ transform: "scaleX(-1)" }}
                                aria-hidden="true"
                                data-testid="space-sidebar-expand-icon"
                            />
                        </button>
                    </div>
                    <div className={s.collapsedGroupList}>
                        {groups.map((group) => (
                            <button
                                key={group.key}
                                type="button"
                                className={s.collapsedGroupButton}
                                title={group.title}
                                aria-label={`打开${group.title}分组`}
                                data-testid={`collapsed-space-group-${group.key}`}
                                onClick={() => onRestoreSidebar(group.key)}
                            >
                                {(() => { const Icon = SPACE_GROUP_ICONS[group.key]; return <Icon className={s.collapsedGroupIcon} aria-hidden="true" />; })()}
                            </button>
                        ))}
                    </div>
                </div>
            ) : (
                <>
                    <div className={s.spaceHeader}>
                        <span className={s.spaceHeaderIcon}>
                            <img
                                src={resolveAssetUrl(PORTAL_SIDEBAR_TITLE_ICON_SRC)}
                                alt=""
                                aria-hidden="true"
                                data-testid="space-sidebar-title-icon"
                            />
                        </span>
                        <span className={s.spaceHeaderTitle}>我的知识库</span>
                        <button
                            type="button"
                            className={s.spaceHeaderCollapse}
                            aria-label="收起知识库侧栏"
                            title="收起"
                            onClick={onCollapseSidebar}
                        >
                            <SidebarCollapseIcon
                                className={s.spaceHeaderCollapseIcon}
                                aria-hidden="true"
                                data-testid="space-sidebar-collapse-icon"
                            />
                        </button>
                    </div>
                    <GlobalSearchPanel onSelectFile={onGlobalSearchSelectFile} />
                    <div className={s.spaceList}>
                        {groups.map((group) => {
                            const expanded = expandedGroups[group.key];
                            const canCreate = !createOptionsLoading && createPermissionByLevel[group.level];
                            return (
                                <div
                                    key={group.key}
                                    data-testid={`space-group-${group.key}`}
                                    ref={(node) => {
                                        groupRefs.current[group.key] = node;
                                    }}
                                >
                                    <div className={s.groupRow}>
                                        <button
                                            type="button"
                                            className={s.groupExpandButton}
                                            aria-label={`${expanded ? "收起" : "展开"}${group.title}`}
                                            onClick={() => onToggleGroup(group.key)}
                                        >
                                            <span
                                                className={`${s.groupCaret} ${expanded ? s.groupCaretExpanded : ""}`}
                                                aria-hidden="true"
                                            />
                                        </button>
                                        <button
                                            type="button"
                                            className={`${s.groupToggleButton} ${expanded ? s.groupToggleButtonExpanded : ""}`}
                                            onClick={() => onToggleGroup(group.key)}
                                        >
                                            {(() => { const Icon = SPACE_GROUP_ICONS[group.key]; return <Icon className={`${s.groupIcon} ${expanded ? s.groupIconExpanded : ""}`} aria-hidden="true" data-testid={`space-group-icon-${group.key}`} />; })()}
                                            <strong>{group.title}</strong>
                                        </button>
                                        {group.level !== SpaceLevel.PERSONAL ? (
                                            <button
                                                type="button"
                                                className={s.groupCreateButton}
                                                aria-label={`新增${group.title}`}
                                                title={canCreate ? `新增${group.title}` : "无创建权限"}
                                                disabled={!canCreate}
                                                onClick={(event) => {
                                                    event.stopPropagation();
                                                    onOpenCreateSpace(group);
                                                }}
                                            >
                                                <Plus size={14} />
                                            </button>
                                        ) : null}
                                    </div>
                                    {expanded ? (
                                        <>
                                            {group.spaces.length ? (
                                                group.spaces.map((space) => (
                                                    <div
                                                        key={`${group.key}-${space.id}`}
                                                        data-testid={`space-row-${space.id}`}
                                                        className={[
                                                            s.spaceRow,
                                                            activeSpaceId === space.id ? s.spaceRowActive : "",
                                                            spaceDrag?.spaceId === space.id ? s.spaceRowDragging : "",
                                                            spaceDropTarget?.spaceId === space.id && spaceDropTarget.position === "before"
                                                                ? s.spaceRowDropBefore : "",
                                                            spaceDropTarget?.spaceId === space.id && spaceDropTarget.position === "after"
                                                                ? s.spaceRowDropAfter : "",
                                                        ].filter(Boolean).join(" ")}
                                                        draggable={isGroupReorderable(group)}
                                                        onDragStart={isGroupReorderable(group)
                                                            ? () => handleSpaceDragStart(group, space)
                                                            : undefined}
                                                        onDragEnd={isGroupReorderable(group) ? handleSpaceDragEnd : undefined}
                                                        onDragOver={isGroupReorderable(group)
                                                            ? (event) => handleSpaceDragOver(event, group, space)
                                                            : undefined}
                                                        onDragLeave={isGroupReorderable(group)
                                                            ? () => setSpaceDropTarget((prev) => (prev?.spaceId === space.id ? null : prev))
                                                            : undefined}
                                                        onDrop={isGroupReorderable(group)
                                                            ? (event) => handleSpaceDrop(event, group, space)
                                                            : undefined}
                                                    >
                                                        <button
                                                            type="button"
                                                            className={s.spaceSelectButton}
                                                            onClick={() => onSelectSpace(space)}
                                                        >
                                                            <KnowledgeSpaceIcon className={s.spaceIcon} aria-hidden="true" data-testid={`space-row-icon-${space.id}`} />
                                                            <span className={s.spaceName} title={space.name}>{space.name}</span>
                                                            {space.isPinned && group.level !== SpaceLevel.PERSONAL ? (
                                                                <Pin
                                                                    className={s.spacePinIcon}
                                                                    aria-hidden="true"
                                                                    data-testid={`space-pin-icon-${space.id}`}
                                                                />
                                                            ) : null}
                                                        </button>
                                                        {!isFavoriteSpace(space) ? (
                                                            <div className={s.spaceMenuArea}>
                                                                <SpaceMenu
                                                                    space={space}
                                                                    group={group}
                                                                    open={spaceMenuOpenId === space.id}
                                                                    permissions={getSpacePermissions(space)}
                                                                    onOpenChange={(open) => onSpaceMenuOpenChange(space.id, open)}
                                                                    onOpenSpaceSettings={onOpenSpaceSettings}
                                                                    onOpenSpaceMembers={onOpenSpaceMembers}
                                                                    onPinSpace={onPinSpace}
                                                                    onDeleteSpace={onDeleteSpace}
                                                                    onLeaveSpace={onLeaveSpace}
                                                                />
                                                            </div>
                                                        ) : null}
                                                    </div>
                                                ))
                                            ) : (
                                                <div className={s.emptySpace}>{(group.loading ?? spaceLoading) ? "加载中..." : "暂无知识库"}</div>
                                            )}
                                            {canCreate ? (
                                                <button
                                                    type="button"
                                                    className={s.createSpaceRow}
                                                    onClick={() => onOpenCreateSpace(group)}
                                                >
                                                    <NewKnowledgeSpaceIcon className={s.spaceIcon} aria-hidden="true" />
                                                    <span className={s.spaceName}>新建知识库</span>
                                                </button>
                                            ) : null}
                                        </>
                                    ) : null}
                                </div>
                            );
                        })}
                    </div>
                </>
            )}
            {!collapsed && (
                <div
                    style={{
                        position: "absolute",
                        top: 0,
                        right: 0,
                        width: "8px",
                        height: "100%",
                        cursor: "col-resize",
                        zIndex: 50,
                    }}
                    onMouseDown={handleResizeMouseDown}
                />
            )}
        </aside>
    );
}
