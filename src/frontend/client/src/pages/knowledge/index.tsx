import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Menu, Plus } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
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
    createSpaceApi,
    updateSpaceApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "./CreateKnowledgeSpaceDrawer";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeAiPanel } from "./SpaceDetail/AiChat/KnowledgeAiPanel";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import KnowledgeSquare from "./KnowledgeSquare";
import { useFileManager } from "./hooks/useFileManager";
import { useFileUpload } from "./hooks/useFileUpload";
import { useAiSplitPane } from "./hooks/useAiSplitPane";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useAuthContext } from "~/hooks/AuthContext";
import { KnowledgeSpaceShareDialog } from "./SpaceDetail/KnowledgeSpaceShareDialog";

export default function Knowledge() {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const MAX_USER_SPACES = 30;
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
    const mobileHeadIconBtnClassName = "inline-flex size-8 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]";

    const { showToast } = useToastContext();
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

    // Feature gate: system may disable Knowledge Space via user plugins.
    // Share links should redirect to workbench home with a clear permission toast.
    useEffect(() => {
        if (!isH5) setSpaceListDrawerOpen(false);
    }, [isH5]);

    useEffect(() => {
        if (showKnowledgeSquare) setSpaceListDrawerOpen(false);
    }, [showKnowledgeSquare]);

    useEffect(() => {
        if (!activeSpace) return;
        setSpaceListDrawerOpen(false);
    }, [activeSpace?.id]);

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
    const fileManager = useFileManager({ activeSpace, initialFolderId: urlFolderId });

    // KeepAlive: refresh the file list every time the user navigates back to /knowledge.
    useActivate(() => {
        fileManager.loadFiles(fileManager.currentPage);
        setKnowledgeTabActivateEpoch((e) => e + 1);
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
    });

    // ─── AI split-pane ──────────────────────────────────────────────────
    const aiPane = useAiSplitPane();

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

                if (effectiveCount >= MAX_USER_SPACES) {
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

                if (cachedCountMax >= MAX_USER_SPACES) {
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

            <div className="hidden h-full shrink-0 touch-desktop:block">
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
                    hideExpandToggleWhenCollapsed={!!activeSpace}
                />
            </div>

            {isH5 && spaceListDrawerOpen ? (
                <div
                    className="fixed inset-0 z-[70] flex"
                    role="dialog"
                    aria-modal="true"
                    aria-label={localize("com_knowledge.knowledge_space")}
                >
                    <div className="relative flex h-full w-[240px] max-w-[240px] shrink-0 flex-col overflow-hidden border-r border-[#e5e6eb] bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)]">
                        <div className="pointer-events-none absolute right-0 top-0 bottom-0 z-[1] w-px bg-[#e5e6eb]" />
                        <KnowledgeSpaceSidebar
                            mobileDrawerMode
                            onDrawerClose={() => setSpaceListDrawerOpen(false)}
                            activeSpaceId={activeSpace?.id}
                            onSpaceSelect={handleSpaceSelect}
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
                    <button
                        type="button"
                        className="min-w-0 flex-1 bg-[rgba(86,88,105,0.55)]"
                        aria-label={localize("com_nav_close_sidebar")}
                        onClick={() => setSpaceListDrawerOpen(false)}
                    />
                </div>
            ) : null}

            {activeSpace ? (
                <div ref={aiPane.splitContainerRef} className="flex h-full min-w-0 flex-1 overflow-hidden">
                    {(() => {
                        const showMobileAiOnly = isH5 && aiPane.showAiAssistant;
                        if (showMobileAiOnly) {
                            return (
                                <div className="h-full min-w-0 flex-1 bg-white">
                                    <KnowledgeAiPanel
                                        spaceId={String(activeSpace.id)}
                                        folderId={fileManager.currentFolderId}
                                        contextLabel={contextLabel}
                                        onClose={() => aiPane.setShowAiAssistant(false)}
                                    />
                                </div>
                            );
                        }
                        return (
                            <>
                                {/* Left: file list */}
                                <div
                                    style={{ width: aiPane.showAiAssistant ? `${aiPane.aiSplitWidth}px` : '100%' }}
                                    className="h-full min-w-0 flex-shrink-0 overflow-hidden"
                                >
                                    {isH5 ? (
                                        <div className="mt-4 flex h-8 items-center justify-between px-4">
                                            <button
                                                type="button"
                                                aria-label={localize("com_nav_open_sidebar")}
                                                onClick={() => setSpaceListDrawerOpen(true)}
                                                className={mobileHeadIconBtnClassName}
                                            >
                                                <Menu className="size-4" />
                                            </button>
                                            <button
                                                type="button"
                                                aria-label={localize("com_knowledge.create_knowledge_space")}
                                                onClick={handleCreateSpace}
                                                className={mobileHeadIconBtnClassName}
                                            >
                                                <Plus className="size-4" />
                                            </button>
                                        </div>
                                    ) : null}
                                    <KnowledgeSpaceContent
                                        space={activeSpace}
                                        files={fileManager.files}
                                        currentPage={fileManager.currentPage}
                                        pageSize={fileManager.pageSize}
                                        total={fileManager.total}
                                        onPageChange={fileManager.handlePageChange}
                                        loading={fileManager.loading}
                                        onSearch={fileManager.handleSearch}
                                        onFilterStatus={fileManager.setStatusFilter}
                                        onSort={(sortBy, direction) => {
                                            if (!sortBy || !direction) return;
                                            fileManager.handleSort(sortBy, direction);
                                        }}
                                        onNavigateFolder={fileManager.handleNavigateFolder}
                                        onUploadFile={fileUpload.handleUploadFile}
                                        onCreateFolder={fileUpload.handleCreateFolder}
                                        onDownloadFile={() => showToast({ message: localize("com_knowledge.start_download"), severity: NotificationSeverity.SUCCESS })}
                                        onRenameFile={fileUpload.handleRenameFile}
                                        onDeleteFile={fileUpload.handleDeleteFile}
                                        onEditTags={fileUpload.handleEditTags}
                                        onRetryFile={() => showToast({ message: localize("com_knowledge.retry_feature_dev"), severity: NotificationSeverity.INFO })}
                                        currentPath={fileManager.currentPath}
                                        onDragStateChange={handleDragStateChange}
                                        uploadingFiles={fileUpload.uploadingFiles}
                                        creatingFolder={fileUpload.creatingFolder}
                                        onCancelCreateFolder={fileUpload.handleCancelCreateFolder}
                                        onToggleAiAssistant={aiPane.handleToggleAiAssistant}
                                        isAiAssistantOpen={aiPane.showAiAssistant}
                                        onCreateSpace={handleCreateSpace}
                                        onGoKnowledgeSquare={() => setShowKnowledgeSquare(true)}
                                    />
                                </div>

                                {/* Splitter */}
                                {!isH5 && aiPane.showAiAssistant && (
                                    <div className="relative z-20 w-[1px] min-w-[1px] max-w-[1px] flex-none shrink-0">
                                        {/* Flex 始终 1px；线条 1px → hover/active 时 w-1（与原实现一致），视觉上加宽不占额外 flex 宽度 */}
                                        <div
                                            onMouseDown={aiPane.startSplitResize}
                                            className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                                        >
                                            <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                                        </div>
                                    </div>
                                )}

                                {/* Right: AI assistant */}
                                {!isH5 && aiPane.showAiAssistant && (
                                    <div className="flex-1 h-full min-w-[360px] bg-white border-l border-[#e5e6eb]">
                                        <KnowledgeAiPanel
                                            spaceId={String(activeSpace.id)}
                                            folderId={fileManager.currentFolderId}
                                            contextLabel={contextLabel}
                                            onClose={() => aiPane.setShowAiAssistant(false)}
                                        />
                                    </div>
                                )}
                            </>
                        );
                    })()}
                </div>
            ) : (
                /* Empty state when no space is selected */
                <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                    {isH5 ? (
                        <div className="absolute left-0 right-0 top-4 z-10 flex h-8 items-center justify-between px-4">
                            <button
                                type="button"
                                aria-label={localize("com_nav_open_sidebar")}
                                onClick={() => setSpaceListDrawerOpen(true)}
                                className={mobileHeadIconBtnClassName}
                            >
                                <Menu className="size-4" />
                            </button>
                            <button
                                type="button"
                                aria-label={localize("com_knowledge.create_knowledge_space")}
                                onClick={handleCreateSpace}
                                className={mobileHeadIconBtnClassName}
                            >
                                <Plus className="size-4" />
                            </button>
                        </div>
                    ) : null}
                    <img
                        className="size-[120px] mb-4 object-contain opacity-90"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                        alt="empty"
                    />
                    <p className="text-[14px] leading-6 text-[#4E5969]">
                        {localize("com_knowledge.no_related_content_please")}<span
                            className="ml-1.5 cursor-pointer text-[#165DFF] underline decoration-dashed underline-offset-4 transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
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
