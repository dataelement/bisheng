import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { useKnowledgeSpaceLists } from "../hooks/useKnowledgeSpaceLists";
import { ChevronDown, Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KnowledgeSpace, SpaceSortType } from "~/api/knowledge";
import { Button } from "~/components/ui/Button";
import NavToggle from "~/components/Nav/NavToggle";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";
import KnowledgeSpaceCardItem from "./KnowledgeSpaceCardItem";
import { KnowledgeSpaceSections, type KnowledgeSpaceSection } from "./KnowledgeSpaceSections";
import { useSpaceActions } from "../hooks/useSpaceActions";
import { useAuthContext, useLocalize, useWorkbenchMenuNames } from "~/hooks";
import { usePersonalTokenEnabled } from "~/hooks/useVersionManagementEnabled";
import { getPersonalTokenStatusApi } from "~/api/personalToken";
import { PersonalTokenDialog } from "~/components/PersonalTokenDialog";
import { shouldShowPersonalTokenEntry } from "~/pages/settings/sections/personalTokenEntry";
import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { UserPopMenu } from "~/layouts/UserPopMenu";
import { MobileSidebarHeaderTabs } from "~/components/Nav/MobileSidebarHeaderTabs";
import { hasKnowledgeSpaceAction, useKnowledgeSpaceActions } from "../hooks/useKnowledgeSpacePermissions";
import { useDynamicEllipsis } from "../hooks/useDynamicEllipsis";

interface KnowledgeSpaceSidebarProps {
  activeSpaceId?: string;
  onSpaceSelect: (space: KnowledgeSpace | null) => void;
  /** Pin / rename of the active space: update it in place, never re-select it
   *  (re-selecting navigates to the space root and drops the open folder). */
  onActiveSpaceUpdate: (space: KnowledgeSpace) => void;
  onCreateSpace: () => void;
  onSpaceSettings: (space: KnowledgeSpace) => void;
  onKnowledgeSquare?: () => void;
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  /** When true, hide ONLY the expand toggle in collapsed mode (expand is provided elsewhere). */
  hideExpandToggleWhenCollapsed?: boolean;
  /** Mobile drawer: fill the parent width and hide the desktop collapse handle. */
  mobileDrawerMode?: boolean;
  /** Close the mobile drawer from its top-right action. */
  onDrawerClose?: () => void;
  /** Mobile title dropdown: render only the space tree, without module tabs or create action. */
  compactMode?: boolean;
  /** Mobile list page: full width, card rows, no resizing/collapse or automatic selection. */
  mobilePageMode?: boolean;
  /** With mobilePageMode: show the selected category as a card grid on the desktop home. */
  pageGrid?: boolean;
  /** The URL already names a space, so there is nothing to choose a default for.
   *  Auto-select must stand down until the host's own route effect lands, or it
   *  navigates to the first space in the list and takes the URL with it. */
  suppressAutoSelect?: boolean;
  /** Fired when a tree row navigates the page (e.g. folder click in compactMode),
   *  so the host drawer can close itself. */
  onNavigateAway?: () => void;
}

export function KnowledgeSpaceSidebar({
  activeSpaceId,
  onSpaceSelect,
  onActiveSpaceUpdate,
  onCreateSpace,
  onSpaceSettings,
  onKnowledgeSquare,
  collapsed: collapsedProp,
  onCollapsedChange,
  hideExpandToggleWhenCollapsed,
  mobileDrawerMode = false,
  onDrawerClose,
  compactMode = false,
  mobilePageMode = false,
  pageGrid = false,
  suppressAutoSelect = false,
  onNavigateAway,
}: KnowledgeSpaceSidebarProps) {
  const localize = useLocalize();
  // F066 primary entry: the key sits next to the knowledge it unlocks.
  // Both gates must be on — the settings section is the stable home while
  // the tenant switch is off.
  const { user: authUser } = useAuthContext();
  const aiAccessDeploymentEnabled = usePersonalTokenEnabled();
  const { data: aiAccessStatus } = useQuery({
    queryKey: ["personal-token-status", authUser?.id],
    queryFn: getPersonalTokenStatusApi,
    enabled: aiAccessDeploymentEnabled && !!authUser?.id,
    retry: false,
  });
  const aiAccessEntryVisible = shouldShowPersonalTokenEntry(
    aiAccessDeploymentEnabled,
    aiAccessStatus?.enabled,
  );
  const [aiAccessDialogOpen, setAiAccessDialogOpen] = useState(false);
  // Module titles follow the menu display names configured by the administrator.
  const menuNames = useWorkbenchMenuNames();
  // Drawer and full-page list both occupy the full parent width (no resize/toggle).
  const fullWidthMode = mobileDrawerMode || mobilePageMode;
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
  // Scrolling container ref — drives the dynamic, scroll-following name ellipsis.
  const listScrollRef = useRef<HTMLDivElement>(null);
  useDynamicEllipsis(listScrollRef);
  const [isToggleHovering, setIsToggleHovering] = useState(false);

  const queryClient = useQueryClient();

  // Fetch "my created" space list — re-fetched whenever sort changes
  const {
    mine: { data: createdSpaces = [], isLoading: isCreatedLoading },
    joined: { data: joinedSpaces = [], isLoading: isJoinedLoading },
    department: { data: departmentSpaces = [], isLoading: isDepartmentLoading },
    error: spacesError,
    retry: retrySpaces,
  } = useKnowledgeSpaceLists({
    mineOrder: createdSortBy,
    joinedOrder: joinedSortBy,
    departmentOrder: departmentSortBy,
  });

  // Filter department spaces out of other sections to avoid duplication
  const departmentSpaceIds = new Set(departmentSpaces.map((s) => s.id));
  const filteredCreatedSpaces = createdSpaces.filter((s) => !departmentSpaceIds.has(s.id));
  const filteredJoinedSpaces = joinedSpaces.filter((s) => !departmentSpaceIds.has(s.id));
  const fillListHeight = !compactMode && !pageGrid;
  const permissionSpaceIds = useMemo(
    () =>
      Array.from(
        new Set([
          ...departmentSpaces.map((s) => s.id),
          ...filteredCreatedSpaces.map((s) => s.id),
          ...filteredJoinedSpaces.map((s) => s.id),
        ]),
      ),
    [departmentSpaces, filteredCreatedSpaces, filteredJoinedSpaces],
  );
  const {
    actions: spaceActions,
    ensureSpaceActions,
    isSpaceActionsPending,
  } = useKnowledgeSpaceActions(permissionSpaceIds);

  const getItemPermissions = (space: KnowledgeSpace) => {
    const canEditSpace = hasKnowledgeSpaceAction(spaceActions, space.id, "edit");
    const canDeleteSpace = hasKnowledgeSpaceAction(spaceActions, space.id, "delete");
    const canManageMembers = hasKnowledgeSpaceAction(spaceActions, space.id, "manage_permission");
    const permissionsLoading = isSpaceActionsPending(space.id);
    return { canEditSpace, canDeleteSpace, canManageMembers, permissionsLoading };
  };

  // CRUD operations with optimistic updates (mirrors useChannelActions)
  const { handleUpdateSpace, handleDeleteSpace, handleLeaveSpace, handlePinSpace } = useSpaceActions({
    activeSpaceId,
    createdSortBy,
    joinedSortBy,
    departmentSortBy,
    createdSpaces: filteredCreatedSpaces,
    joinedSpaces: filteredJoinedSpaces,
    departmentSpaces,
    onSpaceSelect,
    onActiveSpaceUpdate,
  });

  // Auto-select first space when no space is active (mirrors ChannelSidebar).
  // On the mobile full-page list we must NOT auto-select — the list is a standalone
  // page; selecting a space is an explicit tap that navigates to the file page.
  useEffect(() => {
    if (mobilePageMode) return;
    // A space named in the URL is already a choice. Auto-select used to fire
    // anyway on the render after a route change — the page component is
    // remounted when the route pattern changes, so nothing was active yet —
    // and navigated to the first space in the list, which is how a share
    // link for one space landed on a different one entirely.
    if (suppressAutoSelect) return;
    if (!activeSpaceId) {
      if (spacesError || isCreatedLoading || isJoinedLoading || isDepartmentLoading) return;

      if (departmentSpaces.length > 0) {
        onSpaceSelect(departmentSpaces[0]);
      } else if (filteredCreatedSpaces.length > 0) {
        onSpaceSelect(filteredCreatedSpaces[0]);
      } else if (filteredJoinedSpaces.length > 0) {
        onSpaceSelect(filteredJoinedSpaces[0]);
      }
    }
  }, [
    activeSpaceId,
    suppressAutoSelect,
    departmentSpaces,
    filteredCreatedSpaces,
    filteredJoinedSpaces,
    isCreatedLoading,
    isJoinedLoading,
    isDepartmentLoading,
    spacesError,
    onSpaceSelect,
  ]);

  // Set a section's sort field to a specific value (chosen from the sort dropdown).
  const setSort = (type: "created" | "joined" | "department", value: SpaceSortType) => {
    if (type === "created") {
      if (value === createdSortBy) return;
      queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "mine", createdSortBy] });
      setCreatedSortBy(value);
    } else if (type === "department") {
      if (value === departmentSortBy) return;
      queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "department", departmentSortBy] });
      setDepartmentSortBy(value);
    } else {
      if (value === joinedSortBy) return;
      queryClient.removeQueries({ queryKey: ["knowledgeSpaces", "joined", joinedSortBy] });
      setJoinedSortBy(value);
    }
  };

  // Sort options shown in every section header's sort dropdown.
  const sortOptions = [
    { value: SpaceSortType.UPDATE_TIME, label: localize("com_knowledge.recently_updated") },
    { value: SpaceSortType.NAME, label: localize("com_knowledge.name") },
  ];

  // Render a single space row. Mobile full-page list uses the card layout; everywhere
  // else uses the desktop tree row. Both share identical data/actions.
  const renderSpaceItem = (s: KnowledgeSpace, sectionType: "created" | "joined" | "department") =>
    mobilePageMode ? (
      <KnowledgeSpaceCardItem
        key={s.id}
        space={s}
        type={sectionType}
        isActive={s.id === activeSpaceId}
        card={pageGrid}
        onSelect={onSpaceSelect}
        onDelete={handleDeleteSpace}
        onLeave={handleLeaveSpace}
        onPin={(id, pinned) => handlePinSpace(id, pinned, sectionType)}
        onSettings={onSpaceSettings}
        onMenuOpen={() => ensureSpaceActions(s.id)}
        {...getItemPermissions(s)}
      />
    ) : (
      <KnowledgeSpaceItem
        key={s.id}
        space={s}
        type={sectionType}
        isActive={s.id === activeSpaceId}
        onSelect={onSpaceSelect}
        onUpdate={handleUpdateSpace}
        onDelete={handleDeleteSpace}
        onLeave={handleLeaveSpace}
        onPin={(id, pinned) => handlePinSpace(id, pinned, sectionType)}
        onSettings={onSpaceSettings}
        onMenuOpen={() => ensureSpaceActions(s.id)}
        hideMoreMenu={compactMode}
        compact={compactMode}
        onAfterNavigate={compactMode ? onNavigateAway : undefined}
        {...getItemPermissions(s)}
      />
    );

  const sections: KnowledgeSpaceSection[] = [
    {
      type: "department",
      title: localize("com_knowledge.department_spaces"),
      spaces: departmentSpaces,
      collapsed: departmentCollapsed,
      onToggle: () => setDepartmentCollapsed(!departmentCollapsed),
      sortValue: departmentSortBy,
    },
    {
      type: "created",
      title: localize("com_knowledge.created_by_me"),
      spaces: filteredCreatedSpaces,
      collapsed: createdCollapsed,
      onToggle: () => setCreatedCollapsed(!createdCollapsed),
      sortValue: createdSortBy,
    },
    {
      type: "joined",
      title: localize("com_knowledge.joined_by_me"),
      spaces: filteredJoinedSpaces,
      collapsed: joinedCollapsed,
      onToggle: () => setJoinedCollapsed(!joinedCollapsed),
      sortValue: joinedSortBy,
    },
  ];

  const handleListScroll = () => {
    setIsListScrolling(true);
    if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
    listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
  };

  useEffect(() => {
    if (fullWidthMode) setCollapsed(false);
  }, [fullWidthMode]);

  return (
    <div className={cn("relative h-full min-h-0 shrink-0", fullWidthMode && "w-full")}>
      <div
        className={[
          `h-full ${mobilePageMode || compactMode ? "bg-white" : "bg-[#FBFBFB]"} flex flex-col overflow-hidden ${collapsed || fullWidthMode ? "" : "border-r-[0.5px] border-border-base"}`,
          fullWidthMode ? "w-full" : collapsed ? "w-0" : "",
        ].join(" ")}
        style={
          fullWidthMode
            ? undefined
            : {
                width: collapsed ? 0 : sidebarWidth,
                // Disable the width transition while the user is actively dragging,
                // otherwise the resize feels laggy and rubber-bandy.
                transitionProperty: isResizing ? "none" : "width",
                transitionDuration: "300ms",
                transitionTimingFunction: "ease-in-out",
              }
        }
      >
        {mobileDrawerMode && !compactMode ? (
          <MobileSidebarHeaderTabs
            logoSrc={
              bsConfig?.sidebarIcon?.image ? __APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image : undefined
            }
            onClose={onDrawerClose}
            onLinkClick={(link) => {
              if (link.closeDrawerOnNavigate) onDrawerClose?.();
            }}
          />
        ) : null}
        {/* Top actions */}
        <div
          className={cn(
            collapsed ? "px-0 py-5" : mobileDrawerMode ? "px-3 pt-4 pb-6" : "px-3 pt-4 pb-4",
            (compactMode || mobilePageMode) && "hidden",
          )}
        >
          {mobileDrawerMode ? (
            <div>
              <Button
                variant="secondary"
                onClick={onCreateSpace}
                className="h-9 w-full gap-1 border border-border-base bg-white text-[13px] text-[#666666] hover:bg-fill-1"
              >
                <Plus className="size-4" />
                {localize("com_knowledge.create")}
              </Button>
            </div>
          ) : null}
          <div
            className={cn(
              collapsed ? "flex items-center justify-center h-7" : "",
              mobileDrawerMode && "hidden",
            )}
          >
            {!collapsed && !mobileDrawerMode && (
              <div className="flex justify-between items-center pl-3">
                <span className="text-base font-bold leading-8 text-[#1A1A1A]">{menuNames.knowledge}</span>
              </div>
            )}
          </div>
        </div>

        <div
          className={["flex-1 min-h-0", collapsed ? "opacity-0 pointer-events-none" : "opacity-100"].join(
            " ",
          )}
          style={{
            transitionProperty: "background-color",
            transitionDuration: "350ms",
            transitionTimingFunction: "ease-in-out",
          }}
        >
          <div
            ref={listScrollRef}
            className={cn(
              "h-full overflow-auto overscroll-y-contain scroll-on-scroll pb-5",
              // Desktop home: this container spans the whole page so its scrollbar sits on
              // the page edge; the query container moves to the centred column below, and
              // the gutter is reserved on both edges so that column stays truly centred.
              pageGrid ? "![scrollbar-gutter:stable_both-edges]" : "[container-type:inline-size]",
            )}
            onScroll={handleListScroll}
            data-scrolling={isListScrolling ? "true" : "false"}
          >
            {/* Single shared w-max wrapper around ALL sections so every item
                            (regardless of section) aligns to the global widest. Section
                            headers inside this wrapper use width: 100cqi to stay at the
                            scroll container's visible width — that lets sticky-left/top
                            keep them pinned to the viewport edges even while items
                            horizontally overflow. */}
            <div className={cn(pageGrid ? "mx-auto w-[min(1000px,calc(100%_-_8px))] [container-type:inline-size]" : "w-max min-w-full", fillListHeight && "flex min-h-full flex-col")}>
              {spacesError ? <ApiRequestFailure error={spacesError} onRetry={retrySpaces} /> : (
              <KnowledgeSpaceSections
                sections={sections}
                sortOptions={sortOptions}
                onSortChange={setSort}
                renderSpaceItem={renderSpaceItem}
                onCreateSpace={onCreateSpace}
                onKnowledgeSquare={onKnowledgeSquare}
                compactMode={compactMode}
                mobilePageMode={mobilePageMode}
                pageGrid={pageGrid}
              />
              )}
            </div>
          </div>
        </div>
        {!collapsed && !mobileDrawerMode && !compactMode && !mobilePageMode && (
          <div className="flex shrink-0 flex-col gap-2 px-3 py-3">
            <Button
              variant="secondary"
              onClick={() => onKnowledgeSquare?.()}
              className="h-8 w-full gap-1 rounded-md border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#666666] hover:bg-[#F4F4F4]"
            >
              <Outlined.BlocksAndArrows className="size-4" />
              {localize("com_knowledge.go_to_knowledge_square")}
            </Button>
            <Button
              color="primary"
              variant="filled"
              icon={<Outlined.Plus />}
              onClick={onCreateSpace}
              className="w-full"
            >
              {localize("com_knowledge.create_knowledge_space")}
            </Button>
          </div>
        )}
        {aiAccessEntryVisible && !collapsed && !mobileDrawerMode && !compactMode && !mobilePageMode && (
          <div className="shrink-0 border-t border-border-base px-3 py-3">
            <button
              type="button"
              onClick={() => setAiAccessDialogOpen(true)}
              className="w-full rounded-lg border border-border-base bg-white px-3 py-2 text-left hover:bg-fill-1"
            >
              <span className="flex items-center gap-1.5 text-sm font-medium text-blue-500">
                <Outlined.Send className="size-4 shrink-0" />
                {localize("com_ai_access.guide_title")}
              </span>
              <span className="mt-0.5 block text-xs text-text-3">{localize("com_ai_access.entry_hint")}</span>
            </button>
            <PersonalTokenDialog open={aiAccessDialogOpen} onOpenChange={setAiAccessDialogOpen} />
          </div>
        )}
        {mobileDrawerMode && !compactMode ? (
          <div className="shrink-0 border-t border-border-base px-2 pb-2 pt-1">
            <UserPopMenu variant="drawer" />
          </div>
        ) : null}
      </div>
      {/* Resize handle — a thin invisible strip sitting on the right edge of
                the sidebar. Drag horizontally to resize; double-click to reset. */}
      {!collapsed && !fullWidthMode && (
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
            "after:bg-transparent hover:after:w-[2px] hover:after:bg-[#999999]",
            isResizing && "after:w-[2px] after:bg-[#999999]",
          )}
          style={{ left: sidebarWidth }}
        />
      )}
      <NavToggle
        navVisible={!collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        isHovering={isToggleHovering}
        setIsHovering={setIsToggleHovering}
        className={`absolute top-1/2 left-0 z-[40] ${fullWidthMode ? "hidden" : ""}`}
        translateX={collapsed ? 0 : sidebarWidth}
        disableTransition={isResizing}
      />
    </div>
  );
}
