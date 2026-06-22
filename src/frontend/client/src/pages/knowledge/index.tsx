import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Outlined } from "bisheng-icons";
import { useSetRecoilState } from "recoil";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import store from "~/store";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useActivate, useUnactivate } from "react-activation";
import {
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui";
import {
    KnowledgeSpace,
    SpaceRole,
    VisibilityType,
    SpaceSortType,
    getSpaceInfoApi,
    getMineSpacesApi,
    getJoinedSpacesApi,
    getDepartmentSpacesApi,
    createSpaceApi,
    updateSpaceApi,
    deleteSpaceApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "./CreateKnowledgeSpaceDrawer";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeAiBottomDock } from "./SpaceDetail/AiChat/KnowledgeAiBottomDock";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import KnowledgeSquare from "./KnowledgeSquare";
import { useFileManager } from "./hooks/useFileManager";
import { useFileUpload } from "./hooks/useFileUpload";
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from "~/hooks";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { useAuthContext } from "~/hooks/AuthContext";
import { cn } from "~/utils";
import { KnowledgeSpaceShareDialog } from "./SpaceDetail/KnowledgeSpaceShareDialog";
import { LoadingIcon } from "~/components/ui/icon/Loading";

export default function Knowledge() {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    // ≥1024 = desktop (sidebar expanded by default). 768–1023 = tablet: sidebar starts
    // collapsed but keeps its expand toggle (the mobile flow only kicks in below 768).
    const isDesktop = useMediaQuery("(min-width: 1024px)");
    const { isOverQuota } = useEffectiveQuota();
    const previewNavTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [showCreateDrawer, setShowCreateDrawer] = useState(false);
    const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
    const [showKnowledgeSquare, setShowKnowledgeSquare] = useState(false);
    const [spacePermissionDialogOpen, setSpacePermissionDialogOpen] = useState(false);
    const [spacePermissionDialogSpace, setSpacePermissionDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [isDragging, setIsDragging] = useState(false);
    const [dragError, setDragError] = useState<string | null>(null);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [spaceListDrawerOpen, setSpaceListDrawerOpen] = useState(false);
    // Mobile: a batch selection in the file list hides the AI dock and shows the action bar.
    const [fileSelectionActive, setFileSelectionActive] = useState(false);
    // Mobile: full-page file search (opened from the file-page top-bar search icon).
    const [knowledgeSearchMode, setKnowledgeSearchMode] = useState(false);
    const mobileHeadIconBtnClassName = "inline-flex size-5 shrink-0 items-center justify-center text-[#212121]";
    const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);

    const { showToast } = useToastContext();
    const confirm = useConfirm();
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
    const { spaceId, folderId: urlFolderId } = useParams<{ spaceId?: string; folderId?: string }>();
    const path = location.pathname || "";
    const isShareRoute = /\/knowledge\/share\//.test(path);
    const isDetailRoute = /\/knowledge\/space\//.test(path);
    const previewSpaceId = isShareRoute ? spaceId : undefined;
    const detailSpaceId = isDetailRoute ? spaceId : undefined;
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [squarePreviewSpaceId, setSquarePreviewSpaceId] = useState<string | undefined>();
    const [squarePreviewSpace, setSquarePreviewSpace] = useState<KnowledgeSpace | null>(null);
    const [squarePreviewDrawerOpen, setSquarePreviewDrawerOpen] = useState(false);
    const previewQueryCleanupTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [knowledgeTabActivateEpoch, setKnowledgeTabActivateEpoch] = useState(0);
    const [squareStatusOverride, setSquareStatusOverride] = useState<
        Record<string, "join" | "joined" | "pending" | "rejected">
    >({});

    const openSpacePermissionDialog = (space: KnowledgeSpace) => {
        setSpacePermissionDialogSpace(space);
        setSpacePermissionDialogOpen(true);
    };

    /** Wait for user fetch before applying plugin gate; avoid share routes firing APIs then bouncing wrong. */
    const knowledgePluginGate = useMemo((): "loading" | "enabled" | "disabled" => {
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
    const { isFetched: mineSpacesFetched } = useQuery({
        queryKey: ["knowledgeSpaces", "mine", SpaceSortType.UPDATE_TIME],
        queryFn: () => getMineSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
        enabled: knowledgePluginEnabled,
        placeholderData: (prev) => prev,
    });
    const { isFetched: joinedSpacesFetched } = useQuery({
        queryKey: ["knowledgeSpaces", "joined", SpaceSortType.UPDATE_TIME],
        queryFn: () => getJoinedSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
        enabled: knowledgePluginEnabled,
        placeholderData: (prev) => prev,
    });
    const { isFetched: departmentSpacesFetched } = useQuery({
        queryKey: ["knowledgeSpaces", "department", SpaceSortType.UPDATE_TIME],
        queryFn: () => getDepartmentSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
        enabled: knowledgePluginEnabled,
        placeholderData: (prev) => prev,
    });

    // True while we still can't tell whether the user has any space: the plugin
    // gate is resolving, or the space lists haven't finished their first fetch.
    const spacesResolving =
        knowledgePluginGate === "loading" ||
        (knowledgePluginEnabled && (!mineSpacesFetched || !joinedSpacesFetched || !departmentSpacesFetched));

    useEffect(() => {
        if (!isH5) setSpaceListDrawerOpen(false);
    }, [isH5]);

    // Tablet (768–1023): collapse the sidebar by default so the file area gets the room,
    // while the NavToggle stays available to expand it. Desktop keeps the user's choice.
    useEffect(() => {
        if (!isH5 && !isDesktop) setSidebarCollapsed(true);
    }, [isH5, isDesktop]);

    useEffect(() => {
        if (showKnowledgeSquare) setSpaceListDrawerOpen(false);
    }, [showKnowledgeSquare]);

    useEffect(() => {
        if (!activeSpace) return;
        setSpaceListDrawerOpen(false);
    }, [activeSpace?.id]);

    // Mobile: the space list is a standalone page at /knowledge. When the URL leaves a
    // space detail route (browser Back, or in-app navigation to /knowledge), drop the
    // active space so the full-page list shows again. PC keeps its auto-selected space.
    useEffect(() => {
        if (!isH5) return;
        if (detailSpaceId || isShareRoute) return;
        setActiveSpace(null);
    }, [isH5, detailSpaceId, isShareRoute]);

    // Browser Back/Forward: this tab is cached (react-activation), so the router hooks may
    // not re-run inside it. Re-sync activeSpace with the live URL on popstate. Mobile only —
    // desktop keeps its combined list+detail view (and auto-selects the first space).
    useEffect(() => {
        const onPop = () => {
            if (!window.matchMedia("(max-width: 767px)").matches) return;
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
            severity: NotificationSeverity.ERROR,
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
        if (typeof window !== "undefined" && !/\/knowledge\/space\//.test(window.location.pathname)) {
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

    // Share route: close drawer when leaving /knowledge/share/:spaceId
    useEffect(() => {
        if (!previewSpaceId) {
            setPreviewDrawerOpen(false);
        }
    }, [previewSpaceId]);

    // Deep link to space detail: /knowledge/space/:spaceId or /knowledge/space/:spaceId/folder/:folderId
    useEffect(() => {
        if (!detailSpaceId) return;
        if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled") return;

        // Immediately claim the space ID so the sidebar auto-select won't
        // race ahead and pick a different space while the info fetch is in-flight.
        setActiveSpace((prev) => prev?.id === detailSpaceId ? prev : { id: detailSpaceId } as KnowledgeSpace);
        setShowKnowledgeSquare(false);
        setSquarePreviewDrawerOpen(false);
        setSquarePreviewSpaceId(undefined);

        let cancelled = false;
        (async () => {
            try {
                const detail = await getSpaceInfoApi(detailSpaceId);
                if (cancelled) return;
                setActiveSpace({ ...detail, id: detailSpaceId });
            } catch {
                if (cancelled) return;
                showToastRef.current({
                    message: localizeRef.current("com_knowledge.space_invalid_or_deleted"),
                    severity: NotificationSeverity.WARNING,
                });
                navigateRef.current("/knowledge?square=1", { replace: true });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [detailSpaceId, knowledgePluginGate, knowledgeTabActivateEpoch]);

    // 广场：?square=1；从消息提醒「拒绝加入知识空间」进入时带 previewSpace=，打开广场上的预览抽屉
    useEffect(() => {
        if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled") return;
        const path = location.pathname || "";
        const isSpaceDetailPath = /\/knowledge\/space\//.test(path);

        // 深链在空间内时不要被历史遗留的 ?square=1 拉回广场（侧边选空间常不更新 URL）
        if (isSpaceDetailPath) {
            setShowKnowledgeSquare(false);
            const params = new URLSearchParams(location.search);
            if (params.get("square") === "1") {
                params.delete("square");
                const nextSearch = params.toString();
                navigate(nextSearch ? `${path}?${nextSearch}` : path, { replace: true });
            }
            return;
        }

        const params = new URLSearchParams(location.search);
        if (params.get("square") === "1") {
            setShowKnowledgeSquare(true);
        }
        const previewFromQuery = params.get("previewSpace");
        if (previewFromQuery) {
            console.info("[Knowledge] previewSpace query detected", {
                pathname: path,
                search: location.search,
                previewFromQuery,
            });
            setShowKnowledgeSquare(true);
            setSquarePreviewSpaceId(previewFromQuery);
            setSquarePreviewDrawerOpen(true);
            if (previewQueryCleanupTimerRef.current) {
                clearTimeout(previewQueryCleanupTimerRef.current);
            }
            // Delay URL cleanup so state updates (open drawer + target id) land first.
            previewQueryCleanupTimerRef.current = setTimeout(() => {
                const cleanupParams = new URLSearchParams(location.search);
                cleanupParams.delete("previewSpace");
                const nextSearch = cleanupParams.toString();
                const basePath = path || "/knowledge";
                console.info("[Knowledge] cleanup previewSpace query", {
                    from: location.search,
                    to: nextSearch ? `${basePath}?${nextSearch}` : basePath,
                    squarePreviewSpaceId: previewFromQuery,
                    squarePreviewDrawerOpen: true,
                });
                navigate(nextSearch ? `${basePath}?${nextSearch}` : basePath, { replace: true });
                previewQueryCleanupTimerRef.current = null;
            }, 0);
        }
    }, [location.search, location.pathname, navigate, knowledgePluginGate, knowledgeTabActivateEpoch]);

    // Fallback for consecutive notification clicks in the same tab/session:
    // update square preview drawer immediately even when route diff is swallowed.
    useEffect(() => {
        const onPreviewFromNotification = (evt: Event) => {
            const customEvt = evt as CustomEvent<{ spaceId?: string }>;
            const sid = customEvt?.detail?.spaceId;
            if (!sid) return;
            setShowKnowledgeSquare(true);
            setSquarePreviewSpaceId(String(sid));
            setSquarePreviewSpace(null);
            setSquarePreviewDrawerOpen(true);
        };
        window.addEventListener("knowledge-square-preview", onPreviewFromNotification as EventListener);
        return () => {
            window.removeEventListener("knowledge-square-preview", onPreviewFromNotification as EventListener);
        };
    }, []);

    useEffect(() => {
        console.info("[Knowledge] square preview state", {
            showKnowledgeSquare,
            squarePreviewSpaceId,
            squarePreviewDrawerOpen,
            pathname: location.pathname,
            search: location.search,
        });
    }, [showKnowledgeSquare, squarePreviewSpaceId, squarePreviewDrawerOpen, location.pathname, location.search]);

    // Share link guard: if /knowledge/share/:spaceId points to an invalid/private space,
    // or a space whose join policy changed (approval -> public), show toast and redirect to square.
    // Space creator opens their own share link → go to space detail (same as sidebar entry).
    useEffect(() => {
        if (!previewSpaceId) return;
        if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled") return;
        let cancelled = false;
        setPreviewDrawerOpen(false);
        (async () => {
            try {
                const info = await getSpaceInfoApi(previewSpaceId);
                if (cancelled) return;

                if (info.role === SpaceRole.CREATOR) {
                    navigateRef.current(`/knowledge/space/${previewSpaceId}`, { replace: true });
                    return;
                }

                // Frontend fallback: in some scenarios (e.g. creator share link),
                // `/info` may not provide `role/user_role`.
                // If the space exists in "mine created" list, treat as creator and go to detail page.
                try {
                    const mineSpaces = await getMineSpacesApi();
                    const previewId = String(previewSpaceId);
                    const isMineCreator = mineSpaces.some(
                        (s) => s.id === previewId && s.role === SpaceRole.CREATOR
                    );
                    if (isMineCreator) {
                        navigateRef.current(`/knowledge/space/${previewSpaceId}`, { replace: true });
                        return;
                    }
                } catch {
                    // ignore fallback error, keep existing guard behavior
                }

                // If the space is now private/inaccessible, treat as invalid for share links.
                if (info.visibility === VisibilityType.PRIVATE) {
                    showToastRef.current({
                        message: localizeRef.current("com_knowledge.space_invalid_or_deleted"),
                        severity: NotificationSeverity.WARNING,
                    });
                    setPreviewDrawerOpen(false);
                    navigateRef.current("/knowledge?square=1", { replace: true });
                    return;
                }

                // Space changed from approval to public while user had a pending application.
                // Product expectation: toast + redirect to square page.
                if (info.visibility === VisibilityType.PUBLIC && info.isPending) {
                    showToastRef.current({
                        message: localizeRef.current("com_knowledge.space_became_public_go_square"),
                        severity: NotificationSeverity.WARNING,
                    });
                    setPreviewDrawerOpen(false);
                    navigateRef.current("/knowledge?square=1", { replace: true });
                    return;
                }

                setPreviewDrawerOpen(true);
            } catch {
                if (cancelled) return;
                showToastRef.current({
                    message: localizeRef.current("com_knowledge.space_invalid_or_deleted"),
                    severity: NotificationSeverity.WARNING,
                });
                setPreviewDrawerOpen(false);
                navigateRef.current("/knowledge?square=1", { replace: true });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [previewSpaceId, knowledgePluginGate, knowledgeTabActivateEpoch]);

    // ─── Space actions ──────────────────────────────────────────────────
    const handleSpaceSelect = async (space: KnowledgeSpace | null) => {
        if (!space) {
            setActiveSpace(null);
            return;
        }
        // Clear folder context from URL so the file list re-fetches the space root.
        // Without this, clicking a space while the URL is on /folder/<id> leaves the
        // file list stuck on the folder's contents and the tree's folder highlight
        // pointing at the wrong space (Bug A + Bug B).
        if (urlFolderId || spaceId !== space.id) {
            navigate(`/knowledge/space/${space.id}`);
        }
        // Set list-level data immediately for fast UI switch
        setActiveSpace(space);
        // Then fetch full detail from info API
        try {
            const detail = await getSpaceInfoApi(space.id);
            // Preserve the role from the list API (which has user_role).
            // The /info endpoint may not return user_role, so mapSpace defaults to MEMBER.
            // Only update role if detail explicitly provides a non-MEMBER role.
            const mergedRole = detail.role !== SpaceRole.MEMBER ? detail.role : space.role;
            setActiveSpace(prev => prev?.id === space.id ? { ...space, ...detail, id: space.id, role: mergedRole } : prev);
        } catch {
            // Keep list-level data if info fetch fails
        }
    };

    const handleCreateSpace = () => {
        (async () => {
            try {
                // Prefer cached "mine created" count (sidebar uses react-query) to avoid backend eventual consistency
                // causing an off-by-one where the 31st is allowed and only the 32nd is blocked.
                const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SpaceSortType.UPDATE_TIME]);
                const cachedName = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SpaceSortType.NAME]);
                const cachedCountMax = Math.max(cachedUpdate?.length ?? 0, cachedName?.length ?? 0);

                const mineSpaces = await getMineSpacesApi();
                const effectiveCount = Math.max(mineSpaces.length, cachedCountMax);

                if (isOverQuota("knowledge_space", effectiveCount)) {
                    showToast({
                        message: localize("com_knowledge.create_space_limit_reached"),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }
                setEditingSpace(null);
                setShowCreateDrawer(true);
            } catch {
                // 如果校验接口失败，为避免阻塞用户操作，仍允许打开创建抽屉
                // （可根据需要改成硬拦截）
                // Fall back to cached count when possible; otherwise keep the original behavior.
                const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SpaceSortType.UPDATE_TIME]);
                const cachedName = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SpaceSortType.NAME]);
                const cachedCountMax = Math.max(cachedUpdate?.length ?? 0, cachedName?.length ?? 0);

                if (isOverQuota("knowledge_space", cachedCountMax)) {
                    showToast({
                        message: localize("com_knowledge.create_space_limit_reached"),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }

                setEditingSpace(null);
                setShowCreateDrawer(true);
            }
        })();
    };

    // Open space settings drawer — fetch detail first, then open
    const handleSpaceSettings = async (space: KnowledgeSpace) => {
        try {
            const detail = await getSpaceInfoApi(space.id);
            setEditingSpace({ ...space, ...detail, id: space.id });
        } catch {
            // Fallback to list-level data if detail fetch fails
            setEditingSpace(space);
        }
        setShowCreateDrawer(true);
    };

    const handleConfirmCreateSpace = async (form: CreateKnowledgeSpaceFormData) => {
        try {
            // Map joinPolicy → auth_type
            const auth_type =
                form.joinPolicy === "public"
                    ? VisibilityType.PUBLIC
                    : form.joinPolicy === "review"
                        ? VisibilityType.APPROVAL
                        : VisibilityType.PRIVATE;
            const is_released = form.publishToSquare === "yes";

            if (editingSpace) {
                // ── Edit mode ──
                const updated = await updateSpaceApi(editingSpace.id, {
                    name: form.name,
                    description: form.description,
                    auth_type,
                    is_released,
                });
                if (activeSpace?.id === updated.id) setActiveSpace({ ...updated, role: activeSpace.role });
                queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
                showToast({ message: localize("com_knowledge.space_updated"), severity: NotificationSeverity.SUCCESS });
            } else {
                // ── Create mode ──
                const newSpace = await createSpaceApi({
                    name: form.name,
                    description: form.description,
                    auth_type,
                    is_released,
                });
                setActiveSpace(newSpace);

                // Optimistically update cached "mine created" lists so subsequent "create limit check"
                // doesn't rely on backend propagation timing.
                const createdKeys: Array<[string, string, SpaceSortType]> = [
                    ["knowledgeSpaces", "mine", SpaceSortType.UPDATE_TIME],
                    ["knowledgeSpaces", "mine", SpaceSortType.NAME],
                ];
                for (const key of createdKeys) {
                    queryClient.setQueryData<KnowledgeSpace[]>(key, (prev) => {
                        if (!prev) return [newSpace];
                        if (prev.some((s) => s.id === newSpace.id)) return prev;
                        return [newSpace, ...prev];
                    });
                }

                queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces", "mine"] });
                showToast({ message: localize("com_knowledge.space_create_success"), severity: NotificationSeverity.SUCCESS });
            }
            return true;
        } catch (error) {
            const message = error instanceof Error && error.message
                ? error.message
                : (editingSpace
                    ? localize("com_knowledge.update_space_failed")
                    : localize("com_knowledge.create_space_failed"));
            showToast({
                message,
                severity: NotificationSeverity.ERROR
            });
            return false;
        }
    };

    // Delete the current space from the file-page top-bar menu, then return to the list.
    const handleDeleteActiveSpace = async (sp: KnowledgeSpace | null) => {
        if (!sp) return;
        // Align with file-delete confirm (Figma "删除操作确认"): destructive variant.
        const ok = await confirm({
            description: `${localize("com_knowledge.confirm_delete_space")}${localize("com_knowledge.delete_irreversible_warning")}`,
            variant: "destructive",
        });
        if (!ok) return;
        try {
            await deleteSpaceApi(sp.id);
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: localize("com_knowledge.space_deleted"), severity: NotificationSeverity.SUCCESS });
            setActiveSpace(null);
            navigate("/knowledge");
        } catch {
            showToast({ message: localize("com_knowledge.delete_space_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    const handleDragStateChange = (dragging: boolean, error?: string | null) => {
        setIsDragging(dragging);
        setDragError(error || null);
    };

    const locationKey = fileManager.currentFolderId || activeSpace?.id || "";
    const contextLabel = fileManager.currentFolderId ? localize("com_knowledge.folder") : localize("com_knowledge.knowledge_space");

    if (knowledgePluginGate === "disabled") {
        return null;
    }

    // Knowledge square view
    if (showKnowledgeSquare) {
        return (
            <div className="relative flex h-full min-h-0">
                <KnowledgeSquare
                    onBack={() => {
                        setShowKnowledgeSquare(false);
                        navigate("/knowledge", { replace: true });
                    }}
                    title={localize("com_knowledge.explore_square")}
                    subtitle={localize("com_knowledge.explore_more_spaces")}
                    searchPlaceholder={localize("com_knowledge.search_space_placeholder")}
                    emptyText={localize("com_knowledge.no_matched_space")}
                    joinToastPrefix={localize("com_knowledge.applied_to_join_space")}
                    onPreviewSpace={(space) => {
                        setSquarePreviewSpaceId(space.id);
                        setSquarePreviewSpace(space);
                        setSquarePreviewDrawerOpen(true);
                    }}
                    statusOverride={squareStatusOverride}
                    onSquareStatusChange={(id, status) => {
                        setSquareStatusOverride((prev) => {
                            if (prev[String(id)] === status) {
                                return prev;
                            }
                            return { ...prev, [String(id)]: status };
                        });
                    }}
                />
                <KnowledgeSpacePreviewDrawer
                    spaceId={squarePreviewSpaceId}
                    initialSpace={
                        squarePreviewSpace
                            ? {
                                ...squarePreviewSpace,
                                squareStatus:
                                    squareStatusOverride[String(squarePreviewSpace.id)] ??
                                    squarePreviewSpace.squareStatus,
                            }
                            : null
                    }
                    open={squarePreviewDrawerOpen}
                    onOpenChange={(open) => {
                        setSquarePreviewDrawerOpen(open);
                        if (!open) {
                            setSquarePreviewSpaceId(undefined);
                            setSquarePreviewSpace(null);
                        }
                    }}
                    onSquareStatusChange={(id, status) => {
                        setSquareStatusOverride((prev) => {
                            if (prev[String(id)] === status) {
                                return prev;
                            }
                            return { ...prev, [String(id)]: status };
                        });
                    }}
                />
            </div>
        );
    }

    return (
        <div className="relative flex h-full min-h-0">
            {/* Drag and Drop Overlay */}
            {isDragging && (
                <div
                    className={`absolute inset-0.5 z-[100] rounded-[12px] backdrop-blur-[16px] flex flex-col items-center justify-center pointer-events-none transition-all duration-300 ${dragError ? "border border-dashed border-red-500 bg-[rgba(255,236,232,0.7)]" : "border border-dashed bg-[rgba(255,255,255,0.7)]"}`}
                >
                    <div className={`flex flex-col items-center justify-center p-8 rounded-2xl ${dragError ? "bg-transparent" : "bg-white/50"}`}>
                        {dragError ? (
                            <p className="text-xl font-medium text-red-500 mb-2">{dragError}</p>
                        ) : (
                            <p className="text-xl font-medium text-[#161616] mb-2">{localize("com_knowledge.drop_to_upload")}</p>
                        )}
                        <div className="text-center text-xs text-gray-400 leading-5">
                            <p>{localize("com_knowledge.supported_formats")}</p>
                            <p>{localize("com_knowledge.format_list")}</p>
                            <p>{localize("com_knowledge.max_file_size_200m")}</p>
                            <p>{localize("com_knowledge.max_upload_50_short")}</p>
                        </div>
                    </div>
                </div>
            )}

            {/* Sidebar — shown ≥768px. Must NOT mount on mobile (<768): its auto-select-first
                effect would jump straight into a space and bypass the mobile list page.
                Tablet (768–1023) keeps it (collapsed by default) so the expand toggle stays. */}
            {!isH5 && (
                <div className="h-full shrink-0">
                    <KnowledgeSpaceSidebar
                        activeSpaceId={activeSpace?.id}
                        onSpaceSelect={handleSpaceSelect}
                        onCreateSpace={handleCreateSpace}
                        onSpaceSettings={handleSpaceSettings}
                        onManageMembers={(space) => {
                            openSpacePermissionDialog(space);
                        }}
                        onKnowledgeSquare={() => setShowKnowledgeSquare(true)}
                        collapsed={sidebarCollapsed}
                        onCollapsedChange={setSidebarCollapsed}
                        hideExpandToggleWhenCollapsed={isDesktop && !!activeSpace}
                    />
                </div>
            )}

            {/* File page: the top Title ▾ opens this drawer to switch spaces (unchanged behaviour). */}
            {/* Kept mounted while a space is active and toggled via `hidden` (not unmounted) so
                the dropdown preserves its last state — cycled type / scroll — across re-opens. */}
            {isH5 && activeSpace && typeof document !== "undefined"
                ? createPortal(
                    <div
                        className={cn(
                            "fixed inset-x-0 bottom-0 z-[80] flex flex-col bg-white",
                            !spaceListDrawerOpen && "hidden",
                        )}
                        style={{ top: "calc(env(safe-area-inset-top, 0px) + 52px)" }}
                        role="dialog"
                        aria-modal="true"
                        aria-hidden={!spaceListDrawerOpen}
                        aria-label={localize("com_knowledge.knowledge_space")}
                    >
                        <div className="min-h-0 flex-1 overflow-hidden">
                            <KnowledgeSpaceSidebar
                                mobileDrawerMode
                                compactMode
                                onDrawerClose={() => setSpaceListDrawerOpen(false)}
                                onNavigateAway={() => setSpaceListDrawerOpen(false)}
                                activeSpaceId={activeSpace?.id}
                                onSpaceSelect={(space) => {
                                    handleSpaceSelect(space);
                                    setSpaceListDrawerOpen(false);
                                }}
                                onCreateSpace={() => {
                                    handleCreateSpace();
                                    setSpaceListDrawerOpen(false);
                                }}
                                onSpaceSettings={(space) => {
                                    handleSpaceSettings(space);
                                    setSpaceListDrawerOpen(false);
                                }}
                                onManageMembers={(space) => {
                                    openSpacePermissionDialog(space);
                                    setSpaceListDrawerOpen(false);
                                }}
                                onKnowledgeSquare={() => {
                                    setShowKnowledgeSquare(true);
                                    setSpaceListDrawerOpen(false);
                                }}
                            />
                        </div>
                        {/* Fixed bottom go-to-square — same as the mobile homepage */}
                        <div className="shrink-0 bg-white px-3 pt-2 pb-[calc(env(safe-area-inset-bottom,0px)+8px)]">
                            <Button
                                variant="secondary"
                                onClick={() => {
                                    setShowKnowledgeSquare(true);
                                    setSpaceListDrawerOpen(false);
                                }}
                                className="h-8 w-full gap-1 rounded-[6px] border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#666666] hover:bg-[#F4F4F4]"
                            >
                                <Outlined.BlocksAndArrows className="size-4" />
                                {localize("com_knowledge.go_to_square")}
                            </Button>
                        </div>
                    </div>,
                    document.body,
                )
                : null}

            {activeSpace ? (
                <div
                    className={cn(
                        "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
                        // Mobile needs a DEFINITE viewport height (the KeepAlive shell is h-auto,
                        // so percentage chains collapse): without it the content grows with the
                        // file count and the absolute-bottom AI dock drifts / the layout cramps.
                        isH5 ? "h-[100dvh]" : "h-full",
                    )}
                >
                    {/* Mobile top bar now lives inside KnowledgeSpaceContent (it owns search/sort/upload). */}
                    {/* `relative` anchors the bottom AI dock; the content scrolls within its own container while the dock overlays the bottom. */}
                    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white shadow-[0px_4px_20px_0px_rgba(0,17,147,0.05)]">
                        <KnowledgeSpaceContent
                            space={activeSpace}
                            files={fileManager.files}
                            total={fileManager.total}
                            onLoadMore={fileManager.loadMore}
                            hasMore={fileManager.hasMore}
                            loading={fileManager.loading}
                            onSearch={fileManager.handleSearch}
                            onFilterStatus={fileManager.setStatusFilter}
                            onSort={(sortBy, direction) => {
                                if (!sortBy || !direction) return;
                                fileManager.handleSort(sortBy, direction);
                            }}
                            onNavigateFolder={(folderId?: string) => {
                                // Drive folder navigation through the URL (like the sidebar tree
                                // does) so the URL stays the single source of truth: useFileManager's
                                // initialFolderId watcher syncs the content pane, and the sidebar
                                // tree auto-expands/highlights to the same folder. Setting folder
                                // state directly would leave the sidebar out of sync.
                                const base = `/knowledge/space/${activeSpace.id}`;
                                navigate(folderId ? `${base}/folder/${folderId}` : base);
                            }}
                            onUploadFile={fileUpload.handleUploadFile}
                            onUploadFolder={fileUpload.handleUploadFolder}
                            onCreateFolder={fileUpload.handleCreateFolder}
                            onDownloadFile={() => showToast({ message: localize("com_knowledge.start_download"), severity: NotificationSeverity.SUCCESS })}
                            onRenameFile={fileUpload.handleRenameFile}
                            onDeleteFile={fileUpload.handleDeleteFile}
                            onEditTags={fileUpload.handleEditTags}
                            onRetryFile={() => showToast({ message: localize("com_knowledge.retry_feature_dev"), severity: NotificationSeverity.INFO })}
                            currentPath={fileManager.currentPath}
                            currentFolderId={fileManager.currentFolderId}
                            onDragStateChange={handleDragStateChange}
                            uploadingFiles={fileUpload.uploadingFiles}
                            creatingFolder={fileUpload.creatingFolder}
                            onCancelCreateFolder={fileUpload.handleCancelCreateFolder}
                            onCreateSpace={handleCreateSpace}
                            onGoKnowledgeSquare={() => setShowKnowledgeSquare(true)}
                            onOpenSystemMenu={() => setSystemMenuOpen(true)}
                            onToggleSpaceList={() => setSpaceListDrawerOpen((o) => !o)}
                            spaceListOpen={spaceListDrawerOpen}
                            onDeleteSpace={() => handleDeleteActiveSpace(activeSpace)}
                            onOpenSearch={() => setKnowledgeSearchMode(true)}
                            searchMode={knowledgeSearchMode}
                            onCloseSearch={() => setKnowledgeSearchMode(false)}
                            onSelectionActiveChange={setFileSelectionActive}
                        />
                        {/* Hide the AI dock during a mobile batch selection (the batch action bar
                            takes the bottom slot) and in search mode (the search page has no dock). */}
                        {!fileSelectionActive && !knowledgeSearchMode && (
                            <KnowledgeAiBottomDock
                                key={String(activeSpace.id)}
                                spaceId={String(activeSpace.id)}
                                folderId={fileManager.currentFolderId}
                                contextLabel={contextLabel}
                            />
                        )}
                    </div>
                </div>
            ) : isH5 ? (
                /* Mobile: standalone full-page space list. Tapping a space navigates to
                   /knowledge/space/:id (handled by handleSpaceSelect) → the file page. */
                <div className="flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden bg-white">
                    <div className="shrink-0 rounded-t-xl bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                        <div className="flex h-11 w-full min-w-0 items-center justify-between gap-3 px-4">
                            <button
                                type="button"
                                aria-label={localize("com_nav_open_sidebar")}
                                onClick={() => setSystemMenuOpen(true)}
                                className={mobileHeadIconBtnClassName}
                            >
                                <Outlined.SidebarMenu className="size-5" />
                            </button>
                            <span className="min-w-0 flex-1 truncate text-center text-base font-medium leading-6 text-[#212121]">
                                {localize("com_knowledge.knowledge_space")}
                            </span>
                            <span className="size-5 shrink-0" aria-hidden />
                        </div>
                    </div>
                    <div className="min-h-0 flex-1 overflow-hidden">
                        <KnowledgeSpaceSidebar
                            mobilePageMode
                            onSpaceSelect={handleSpaceSelect}
                            onCreateSpace={handleCreateSpace}
                            onSpaceSettings={handleSpaceSettings}
                            onManageMembers={(space) => openSpacePermissionDialog(space)}
                            onKnowledgeSquare={() => setShowKnowledgeSquare(true)}
                        />
                    </div>
                    {/* Fixed bottom go-to-square — reuses the PC sidebar button style */}
                    <div className="shrink-0 bg-white px-3 pt-2 pb-[calc(env(safe-area-inset-bottom,0px)+8px)]">
                        <Button
                            variant="secondary"
                            onClick={() => setShowKnowledgeSquare(true)}
                            className="h-8 w-full gap-1 rounded-[6px] border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#666666] hover:bg-[#F4F4F4]"
                        >
                            <Outlined.BlocksAndArrows className="size-4" />
                            {localize("com_knowledge.go_to_square")}
                        </Button>
                    </div>
                </div>
            ) : spacesResolving ? (
                /* PC loading state — keep the loading view up until the space lists
                   settle so the empty state never flashes before auto-select. */
                <div className="flex flex-1 flex-col items-center justify-center py-10 text-center text-[#86909c]">
                    <LoadingIcon className="size-20 text-primary" />
                </div>
            ) : (
                /* PC empty state when no space is selected */
                <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                    <img
                        className="size-[120px] mb-4 object-contain opacity-90"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                        alt="empty"
                    />
                    <p className="text-[14px] leading-6 text-[#4E5969]">
                        {localize("com_knowledge.no_related_content_please")}<span
                            className="ml-1.5 cursor-pointer text-blue-500 transition-colors hover:text-blue-400 active:text-blue-700"
                            onClick={handleCreateSpace}
                        >
                            {localize("com_knowledge.create_knowledge_space")}</span>
                    </p>
                </div>
            )}

            <CreateKnowledgeSpaceDrawer
                open={showCreateDrawer}
                onOpenChange={setShowCreateDrawer}
                onConfirm={handleConfirmCreateSpace}
                mode={editingSpace ? "edit" : "create"}
                editingSpace={editingSpace}
                onViewSpace={() => setShowCreateDrawer(false)}
                onManageMembers={() => {
                    setShowCreateDrawer(false);
                    if (activeSpace) openSpacePermissionDialog(activeSpace);
                }}
            />

            <KnowledgeSpaceShareDialog
                open={spacePermissionDialogOpen}
                onOpenChange={setSpacePermissionDialogOpen}
                resourceId={spacePermissionDialogSpace?.id || ""}
                resourceName={spacePermissionDialogSpace?.name || ""}
                currentUserRole={spacePermissionDialogSpace?.role || null}
                showShareTab={false}
                showMembersTab={false}
                showPermissionTab
                isDepartmentSpace={spacePermissionDialogSpace?.spaceKind === "department"}
            />

            <KnowledgeSpacePreviewDrawer
                spaceId={previewSpaceId}
                open={previewDrawerOpen}
                onOpenChange={(open) => {
                    setPreviewDrawerOpen(open);
                    if (previewNavTimerRef.current) {
                        clearTimeout(previewNavTimerRef.current);
                        previewNavTimerRef.current = null;
                    }

                    // 给 Sheet 的 slide-out 动画留出时间，避免立刻 navigate 导致动画被中断
                    if (!open) {
                        previewNavTimerRef.current = setTimeout(() => {
                            navigate("/knowledge", { replace: true });
                        }, 400);
                    }
                }}
            />

            {/* Duplicate file overwrite confirmation dialog */}
            <Dialog
                open={fileUpload.duplicateFiles.length > 0}
                onOpenChange={(open) => !open && fileUpload.handleDuplicateSkip()}
            >
                <DialogContent className="sm:max-w-[460px]" onPointerDownOutside={(e) => e.preventDefault()}>
                    <DialogHeader>
                        <DialogTitle>{localize("com_knowledge.duplicate_file_title")}</DialogTitle>
                    </DialogHeader>
                    <ul className="overflow-y-auto max-h-[300px] py-2 space-y-1.5">
                        {fileUpload.duplicateFiles.map((entry, idx) => {
                            const name = entry.fileName;
                            const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')) : '';
                            const base = name.includes('.') ? name.slice(0, name.lastIndexOf('.')) : name;
                            const truncatedName = base.length > 10 ? base.slice(0, 10) + '....' + ext : name;
                            const path = entry.oldFileLevelPath || '';
                            return (
                                <li key={idx} className="py-1 text-sm text-gray-700">
                                    <span title={name}>{truncatedName}</span>
                                    {path && <span className="ml-1 text-gray-400">({path})</span>}
                                </li>
                            );
                        })}
                    </ul>
                    <DialogFooter>
                        <Button variant="outline" className="h-8" onClick={fileUpload.handleDuplicateSkip}>
                            {localize("com_knowledge.duplicate_cancel")}
                        </Button>
                        <Button className="h-8" onClick={fileUpload.handleDuplicateOverwrite}>
                            {localize("com_knowledge.duplicate_replace")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
