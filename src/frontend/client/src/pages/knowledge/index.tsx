// @ts-strict-ignore
import { knowledgePathWithTab } from "./knowledgeListNavigation";
import { useKnowledgeSpaceLists } from "./hooks/useKnowledgeSpaceLists";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSetRecoilState, useRecoilValue } from "recoil";
import { useQueryClient } from "@tanstack/react-query";
import store from "~/store";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useActivate, useUnactivate } from "react-activation";
import {
  KnowledgeSpace,
  SpaceRole,
  SpaceSortType,
  getSpaceInfoApi,
  getMineSpacesApi,
  deleteSpaceApi,
  unsubscribeSpaceApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import {
  createApiStatusError,
  extractApiErrorMessage,
  extractApiStatusCode,
} from "~/utils/apiStatusError";
import { squareTypePath } from "~/pages/square/squarePaths";
import { isDemoId } from "~/mock/demo/ids";
import { useFileManager } from "./hooks/useFileManager";
import { useFileUpload } from "./hooks/useFileUpload";
import {
  useLocalize,
  usePrefersMobileLayout,
  useWorkbenchMenuNames,
} from "~/hooks";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { useAuthContext } from "~/hooks/AuthContext";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import {
  SETTINGS_RETURN_STATE_KEY,
  resolveUploadSizeLimits,
  shouldNavigateOnSpaceSelect,
} from "./knowledgeUtils";
import { KnowledgePageContent } from "./KnowledgePageContent";
import { useKnowledgePageRoutes } from "./hooks/useKnowledgePageRoutes";
interface KnowledgePagePorts {
  localize: ReturnType<typeof useLocalize>;
  showToast: ReturnType<typeof useToastContext>["showToast"];
  confirm: ReturnType<typeof useConfirm>;
}

function useKnowledgePage({
  localize,
  showToast,
  confirm,
}: KnowledgePagePorts) {
  const menuNames = useWorkbenchMenuNames();
  const bishengConfig = useRecoilValue(bishengConfState);
  const uploadSizeLimits = useMemo(
    () => resolveUploadSizeLimits(bishengConfig),
    [bishengConfig],
  );
  const isH5 = usePrefersMobileLayout();
  const { isOverQuota } = useEffectiveQuota();
  const previewNavTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
  const [showKnowledgeSquare, setShowKnowledgeSquare] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [dragError, setDragError] = useState<string | null>(null);
  const [spaceListDrawerOpen, setSpaceListDrawerOpen] = useState(false);
  // Mobile: a batch selection in the file list hides the AI dock and shows the action bar.
  const [fileSelectionActive, setFileSelectionActive] = useState(false);
  // Mobile: full-page file search (opened from the file-page top-bar search icon).
  const [knowledgeSearchMode, setKnowledgeSearchMode] = useState(false);
  const mobileHeadIconBtnClassName =
    "inline-flex size-5 shrink-0 items-center justify-center text-text-1";
  const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);

  const { user, isUserLoading } = useAuthContext();
  const navigate = useNavigate();

  // Stable refs for functions used in effects — avoids infinite loops caused
  // by unstable references (e.g. localize returns a new fn every render).
  const localizeRef = useRef(localize);
  localizeRef.current = localize;
  const showToastRef = useRef(showToast);
  showToastRef.current = showToast;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const location = useLocation();
  const queryClient = useQueryClient();
  const { spaceId, folderId: urlFolderId } = useParams<{
    spaceId?: string;
    folderId?: string;
  }>();
  const path = location.pathname || "";
  const isShareRoute = /\/knowledge\/share\//.test(path);
  const isDetailRoute = /\/knowledge\/space\//.test(path);
  const previewSpaceId = isShareRoute ? spaceId : undefined;
  const detailSpaceId = isDetailRoute ? spaceId : undefined;
  const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
  const [squarePreviewSpaceId, setSquarePreviewSpaceId] = useState<
    string | undefined
  >();
  const [squarePreviewSpace, setSquarePreviewSpace] =
    useState<KnowledgeSpace | null>(null);
  const [squarePreviewDrawerOpen, setSquarePreviewDrawerOpen] = useState(false);
  const previewQueryCleanupTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const [knowledgeTabActivateEpoch, setKnowledgeTabActivateEpoch] = useState(0);
  const [squareStatusOverride, setSquareStatusOverride] = useState<
    Record<string, "join" | "joined" | "pending" | "rejected">
  >({});

  /** Wait for user fetch before applying plugin gate; avoid share routes firing APIs then bouncing wrong. */
  const knowledgePluginGate = useMemo(():
    "loading" | "enabled" | "disabled" => {
    if (isUserLoading) return "loading";
    if (!user) return "enabled";
    const plugins = (user as { plugins?: unknown }).plugins;
    if (!Array.isArray(plugins)) return "enabled";
    return plugins.includes("knowledge_space") ? "enabled" : "disabled";
  }, [user, isUserLoading]);
  const knowledgePluginEnabled = knowledgePluginGate === "enabled";

  // Mirror the sidebar's space-list queries (same keys → react-query dedupes,
  // no extra requests) purely to know when the first fetch has settled. The
  // sidebar owns auto-select, so activeSpace stays null until those lists load;
  // this lets the PC view show a loading state instead of flashing the "no
  // space, create one" empty state before auto-select can land.
  const {
    mine: { isFetched: mineSpacesFetched, data: mineSpaces = [] },
    joined: { isFetched: joinedSpacesFetched, data: joinedSpaces = [] },
    department: {
      isFetched: departmentSpacesFetched,
      data: departmentSpaces = [],
    },
    error: spacesError,
    retry: retrySpaces,
  } = useKnowledgeSpaceLists({ enabled: knowledgePluginEnabled });

  // True while we still can't tell whether the user has any space: the plugin
  // gate is resolving, or the space lists haven't finished their first fetch.
  const spacesResolving =
    knowledgePluginGate === "loading" ||
    (knowledgePluginEnabled &&
      (!mineSpacesFetched || !joinedSpacesFetched || !departmentSpacesFetched));

  // No space in any section — drives the mobile full-page empty state.
  const hasNoSpace =
    !spacesError &&
    !spacesResolving &&
    mineSpaces.length === 0 &&
    joinedSpaces.length === 0 &&
    departmentSpaces.length === 0;

  useEffect(() => {
    if (!isH5) setSpaceListDrawerOpen(false);
  }, [isH5]);

  useEffect(() => {
    if (showKnowledgeSquare) setSpaceListDrawerOpen(false);
  }, [showKnowledgeSquare]);

  useEffect(() => {
    if (!activeSpace) return;
    setSpaceListDrawerOpen(false);
    // Reset full-page search when switching spaces, otherwise a space entered
    // after leaving search mode would render the search page instead of its file list.
    setKnowledgeSearchMode(false);
  }, [activeSpace?.id]);

  // The space list is a standalone page at /knowledge on every shell (mobile list page,
  // desktop home). When the URL leaves a space detail route (browser Back, or in-app
  // navigation to /knowledge), drop the active space so that page shows again.
  useEffect(() => {
    if (detailSpaceId || isShareRoute) return;
    setActiveSpace(null);
  }, [detailSpaceId, isShareRoute]);

  // Browser Back/Forward: this tab is cached (react-activation), so the router hooks may
  // not re-run inside it. Re-sync activeSpace with the live URL on popstate.
  useEffect(() => {
    const onPop = () => {
      if (!/\/knowledge\/space\//.test(window.location.pathname)) {
        setActiveSpace(null);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Feature gate: system may disable Knowledge Space via user plugins.
  // Share links should redirect to workbench home with a clear permission toast.
  useEffect(() => {
    if (knowledgePluginGate !== "disabled") return;
    showToastRef.current({
      message: localizeRef.current("com_plugin_feature_no_access_toast"),
      severity: NotificationSeverity.WARNING,
    });
    navigateRef.current("/c/new", { replace: true });
  }, [knowledgePluginGate]);

  // KeepAlive: when leaving /knowledge, reset square view so switching back lands on default page.
  useUnactivate(() => {
    setShowKnowledgeSquare(false);
    setSquarePreviewDrawerOpen(false);
    setSquarePreviewSpaceId(undefined);
    if (previewQueryCleanupTimerRef.current) {
      clearTimeout(previewQueryCleanupTimerRef.current);
      previewQueryCleanupTimerRef.current = null;
    }
  });

  // ─── File management (list, pagination, search, sort, navigation) ────
  const fileManager = useFileManager({
    activeSpace,
    initialFolderId: urlFolderId,
    enabled: !showKnowledgeSquare,
  });

  // KeepAlive: refresh the file list every time the user navigates back to /knowledge.
  useActivate(() => {
    fileManager.loadFiles(fileManager.currentPage);
    setKnowledgeTabActivateEpoch((e) => e + 1);
    // This tab is cached (react-activation) — re-syncing with the live URL is required,
    // otherwise re-entering the Knowledge menu shows the previously-open space (stale
    // activeSpace) instead of the space list. Read window.location directly because the
    // router hooks can lag a cached re-activation.
    if (
      typeof window !== "undefined" &&
      !/\/knowledge\/space\//.test(window.location.pathname)
    ) {
      setActiveSpace(null);
    }
  });

  const fileUpload = useFileUpload({
    activeSpace,
    currentFolderId: fileManager.currentFolderId,
    currentPath: fileManager.currentPath,
    files: fileManager.files,
    setFiles: fileManager.setFiles,
    setTotal: fileManager.setTotal,
    loadFiles: fileManager.loadFiles,
    currentPage: fileManager.currentPage,
    markPendingDeletion: fileManager.markPendingDeletion,
    clearPendingDeletion: fileManager.clearPendingDeletion,
  });

  useKnowledgePageRoutes({
    setActiveSpace,
    setShowKnowledgeSquare,
    navigate,
    localizeRef,
    showToastRef,
    navigateRef,
    location,
    spaceId,
    path,
    previewSpaceId,
    detailSpaceId,
    setPreviewDrawerOpen,
    setSquarePreviewSpaceId,
    setSquarePreviewSpace,
    setSquarePreviewDrawerOpen,
    previewQueryCleanupTimerRef,
    knowledgeTabActivateEpoch,
    knowledgePluginGate,
    mineSpaces,
  });

  // ─── Space actions ──────────────────────────────────────────────────
  const handleSpaceSelect = async (space: KnowledgeSpace | null) => {
    if (!space) {
      setActiveSpace(null);
      return;
    }
    // DEV sample rows (~/mock/demo) exist only in the list response.
    if (isDemoId(space.id)) {
      showToast({
        message: localize("com_demo_data.readonly_toast"),
        severity: NotificationSeverity.INFO,
      });
      return;
    }
    // Clear folder context from URL so the file list re-fetches the space root.
    // Without this, clicking a space while the URL is on /folder/<id> leaves the
    // file list stuck on the folder's contents and the tree's folder highlight
    // pointing at the wrong space (Bug A + Bug B).
    // Never on a share route — see shouldNavigateOnSpaceSelect.
    if (
      shouldNavigateOnSpaceSelect({
        isShareRoute,
        urlFolderId,
        urlSpaceId: spaceId,
        targetSpaceId: space.id,
      })
    ) {
      navigate(
        knowledgePathWithTab(`/knowledge/space/${space.id}`, location.search),
      );
    }
    // Set list-level data immediately for fast UI switch
    setActiveSpace(space);
    // Then fetch full detail from info API
    try {
      const detail = await getSpaceInfoApi(space.id);
      // Preserve the role from the list API (which has user_role).
      // The /info endpoint may not return user_role, so mapSpace defaults to MEMBER.
      // Only update role if detail explicitly provides a non-MEMBER role.
      const mergedRole =
        detail.role !== SpaceRole.MEMBER ? detail.role : space.role;
      setActiveSpace((prev) =>
        prev?.id === space.id
          ? { ...space, ...detail, id: space.id, role: mergedRole }
          : prev,
      );
    } catch {
      // Keep list-level data if info fetch fails
    }
  };

  // Pin / rename of the active space: merge the new fields, keep space + folder.
  const handleActiveSpaceUpdate = (space: KnowledgeSpace) => {
    setActiveSpace((prev) =>
      prev?.id === space.id ? { ...prev, ...space, role: prev.role } : prev,
    );
  };

  // Hand the settings page the location being browsed, so leaving it resumes
  // this space and folder instead of the settings' own space root.
  const settingsEntryState = () => ({
    [SETTINGS_RETURN_STATE_KEY]: `${location.pathname}${location.search}`,
  });

  const handleCreateSpace = () => {
    (async () => {
      try {
        // Prefer cached "mine created" count (sidebar uses react-query) to avoid backend eventual consistency
        // causing an off-by-one where the 31st is allowed and only the 32nd is blocked.
        const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>([
          "knowledgeSpaces",
          "mine",
          SpaceSortType.UPDATE_TIME,
        ]);
        const cachedName = queryClient.getQueryData<KnowledgeSpace[]>([
          "knowledgeSpaces",
          "mine",
          SpaceSortType.NAME,
        ]);
        const cachedCountMax = Math.max(
          cachedUpdate?.length ?? 0,
          cachedName?.length ?? 0,
        );

        const mineSpaces = await getMineSpacesApi();
        const effectiveCount = Math.max(mineSpaces.length, cachedCountMax);

        if (isOverQuota("knowledge_space", effectiveCount)) {
          showToast({
            message: localize("com_knowledge.create_space_limit_reached"),
            severity: NotificationSeverity.WARNING,
          });
          return;
        }
        navigate("/knowledge/create", { state: settingsEntryState() });
      } catch {
        // Fall back to cached count when possible; otherwise keep the original behavior.
        const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>([
          "knowledgeSpaces",
          "mine",
          SpaceSortType.UPDATE_TIME,
        ]);
        const cachedName = queryClient.getQueryData<KnowledgeSpace[]>([
          "knowledgeSpaces",
          "mine",
          SpaceSortType.NAME,
        ]);
        const cachedCountMax = Math.max(
          cachedUpdate?.length ?? 0,
          cachedName?.length ?? 0,
        );

        if (isOverQuota("knowledge_space", cachedCountMax)) {
          showToast({
            message: localize("com_knowledge.create_space_limit_reached"),
            severity: NotificationSeverity.WARNING,
          });
          return;
        }

        navigate("/knowledge/create", { state: settingsEntryState() });
      }
    })();
  };

  const handleSpaceSettings = (space: KnowledgeSpace) => {
    navigate(`/knowledge/space/${space.id}/settings`, {
      state: settingsEntryState(),
    });
  };

  // Delete the current space from the file-page top-bar menu, then return to the list.
  const handleDeleteActiveSpace = async (sp: KnowledgeSpace | null) => {
    if (!sp) return;

    const ok = await confirm({
      description: `${localize("com_knowledge.confirm_delete_space")}${localize("com_knowledge.delete_irreversible_warning")}`,
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await deleteSpaceApi(sp.id);
      queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
      showToast({
        message: localize("com_knowledge.space_deleted"),
        severity: NotificationSeverity.SUCCESS,
      });
      setActiveSpace(null);
      navigate(knowledgePathWithTab("/knowledge", location.search));
    } catch {
      showToast({
        message: localize("com_knowledge.delete_space_failed"),
        severity: NotificationSeverity.WARNING,
      });
    }
  };

  // Leave the current joined space from the space page, then return to the list.
  // Mirrors useSpaceActions.handleLeaveSpace, including the organization-grant
  // refusal (18071) that must not be reported as a generic failure.
  // Unsubscribe refusal for a space granted through an organization: the user
  // cannot leave on their own, so it is not reported as a generic failure.
  const ORGANIZATION_GRANT_EXIT_DENIED_CODE = 18071;

  const handleLeaveActiveSpace = async (sp: KnowledgeSpace | null) => {
    if (!sp) return;
    const ok = await confirm({
      title: localize("com_knowledge.prompt"),
      description: localize("com_knowledge.confirm_exit_space"),
      confirmText: localize("com_knowledge.exit"),
      cancelText: localize("com_knowledge.cancel"),
    });
    if (!ok) return;
    try {
      const response = await unsubscribeSpaceApi(sp.id);
      const exitCode = extractApiStatusCode(response);
      if (exitCode && exitCode !== 200) {
        throw createApiStatusError(response);
      }
      queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
      showToast({
        message: localize("com_knowledge.exited_space"),
        severity: NotificationSeverity.SUCCESS,
      });
      setActiveSpace(null);
      navigate(knowledgePathWithTab("/knowledge", location.search));
    } catch (e) {
      const errorCode = extractApiStatusCode(e);
      const message =
        errorCode === ORGANIZATION_GRANT_EXIT_DENIED_CODE
          ? localize("com_knowledge.organization_grant_exit_blocked")
          : extractApiErrorMessage(e) ||
            localize("com_knowledge.exit_space_failed");
      showToast({ message, severity: NotificationSeverity.WARNING });
    }
  };

  const handleDragStateChange = (dragging: boolean, error?: string | null) => {
    setIsDragging(dragging);
    setDragError(error || null);
  };

  // the in-page square below remains for mobile and for the deep links that open it
  // (`?square=1`, `?previewSpace=`, notification events) — those keep a back arrow.
  const handleLeaveSquare = () => {
    setShowKnowledgeSquare(false);
    navigate(knowledgePathWithTab("/knowledge", location.search), {
      replace: true,
    });
  };
  const handleOpenSquare = () => {
    if (isH5) setShowKnowledgeSquare(true);
    else navigate(squareTypePath("knowledge"));
  };

  return {
    setActiveSpace,
    showKnowledgeSquare,
    setShowKnowledgeSquare,
    navigate,
    localizeRef,
    showToastRef,
    navigateRef,
    location,
    spaceId,
    path,
    previewSpaceId,
    detailSpaceId,
    setPreviewDrawerOpen,
    squarePreviewSpaceId,
    setSquarePreviewSpaceId,
    setSquarePreviewSpace,
    squarePreviewDrawerOpen,
    setSquarePreviewDrawerOpen,
    previewQueryCleanupTimerRef,
    knowledgeTabActivateEpoch,
    knowledgePluginGate,
    mineSpaces,
    localize,
    menuNames,
    bishengConfig,
    uploadSizeLimits,
    isH5,
    previewNavTimerRef,
    activeSpace,
    isDragging,
    dragError,
    spaceListDrawerOpen,
    setSpaceListDrawerOpen,
    fileSelectionActive,
    setFileSelectionActive,
    knowledgeSearchMode,
    setKnowledgeSearchMode,
    mobileHeadIconBtnClassName,
    setSystemMenuOpen,
    showToast,
    previewDrawerOpen,
    squarePreviewSpace,
    squareStatusOverride,
    setSquareStatusOverride,
    knowledgePluginEnabled,
    spacesError,
    retrySpaces,
    hasNoSpace,
    fileManager,
    fileUpload,
    handleSpaceSelect,
    handleActiveSpaceUpdate,
    handleCreateSpace,
    handleSpaceSettings,
    handleDeleteActiveSpace,
    handleLeaveActiveSpace,
    handleDragStateChange,
    handleLeaveSquare,
    handleOpenSquare,
  };
}

export type KnowledgePageModel = ReturnType<typeof useKnowledgePage>;

export function Knowledge() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const model = useKnowledgePage({ localize, showToast, confirm });
  return <KnowledgePageContent model={model} />;
}

export default Knowledge;
