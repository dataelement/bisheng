import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useUnactivate } from "react-activation";
import {
    KnowledgeSpace,
    SpaceRole,
    VisibilityType,
    SortType,
    getSpaceInfoApi,
    getMineSpacesApi,
    createSpaceApi,
    updateSpaceApi,
    getSpaceTagsApi,
    type SpaceTag,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { KnowledgeSpaceMemberDialog } from "~/components/KnowledgeSpaceMemberDialog";
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
import { useLocalize } from "~/hooks";

export default function Knowledge() {
    const localize = useLocalize();
    const MAX_USER_SPACES = 30;
    const previewNavTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [showCreateDrawer, setShowCreateDrawer] = useState(false);
    const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
    const [showKnowledgeSquare, setShowKnowledgeSquare] = useState(false);
    const [memberDialogOpen, setMemberDialogOpen] = useState(false);
    const [memberDialogSpace, setMemberDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [isDragging, setIsDragging] = useState(false);
    const [dragError, setDragError] = useState<string | null>(null);

    const { showToast } = useToastContext();
    const navigate = useNavigate();
    const location = useLocation();
    const queryClient = useQueryClient();
    const { spaceId: previewSpaceId } = useParams<{ spaceId?: string }>();
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [squarePreviewSpaceId, setSquarePreviewSpaceId] = useState<string | undefined>();
    const [squarePreviewDrawerOpen, setSquarePreviewDrawerOpen] = useState(false);
    const [squareStatusOverride, setSquareStatusOverride] = useState<Record<string, "join" | "joined" | "pending">>({});

    // KeepAlive: when leaving /knowledge, reset square view so switching back lands on default page.
    useUnactivate(() => {
        setShowKnowledgeSquare(false);
        setSquarePreviewDrawerOpen(false);
        setSquarePreviewSpaceId(undefined);
    });

    // ─── File management (list, pagination, search, sort, navigation) ────
    const fileManager = useFileManager({ activeSpace });

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

    // ─── Space tags for AI chat ─────────────────────────────────────────
    const [spaceTags, setSpaceTags] = useState<SpaceTag[]>([]);
    useEffect(() => {
        if (!activeSpace?.id) {
            setSpaceTags([]);
            return;
        }
        getSpaceTagsApi(String(activeSpace.id))
            .then(setSpaceTags)
            .catch(() => setSpaceTags([]));
    }, [activeSpace?.id]);

    // Open preview drawer when URL has a spaceId param
    useEffect(() => {
        if (previewSpaceId) {
            setPreviewDrawerOpen(true);
        }
    }, [previewSpaceId]);

    // If navigation requests the knowledge square (e.g. via share-link error), open it.
    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.get("square") === "1") {
            setShowKnowledgeSquare(true);
        }
    }, [location.search]);

    // Share link guard: if /knowledge/share/:spaceId points to an invalid/private space,
    // or a space whose join policy changed (approval -> public), show toast and redirect to square.
    useEffect(() => {
        if (!previewSpaceId) return;
        let cancelled = false;
        (async () => {
            try {
                const info = await getSpaceInfoApi(previewSpaceId);
                if (cancelled) return;

                // If the space is now private/inaccessible, treat as invalid for share links.
                if (info.visibility === VisibilityType.PRIVATE) {
                    showToast({
                        message: localize("com_knowledge.space_invalid_or_deleted"),
                        severity: NotificationSeverity.WARNING,
                    });
                    setPreviewDrawerOpen(false);
                    navigate("/knowledge?square=1", { replace: true });
                    return;
                }

                // Space changed from approval to public while user had a pending application.
                // Product expectation: toast + redirect to square page.
                if (info.visibility === VisibilityType.PUBLIC && info.isPending) {
                    showToast({
                        message: localize("com_knowledge.space_became_public_go_square"),
                        severity: NotificationSeverity.WARNING,
                    });
                    setPreviewDrawerOpen(false);
                    navigate("/knowledge?square=1", { replace: true });
                    return;
                }
            } catch {
                if (cancelled) return;
                showToast({
                    message: localize("com_knowledge.space_invalid_or_deleted"),
                    severity: NotificationSeverity.WARNING,
                });
                setPreviewDrawerOpen(false);
                navigate("/knowledge?square=1", { replace: true });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [previewSpaceId]);

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
                const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SortType.UPDATE_TIME]);
                const cachedName = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SortType.NAME]);
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
                const cachedUpdate = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SortType.UPDATE_TIME]);
                const cachedName = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "mine", SortType.NAME]);
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
                if (activeSpace?.id === updated.id) setActiveSpace(updated);
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
                const createdKeys: Array<[string, string, SortType]> = [
                    ["knowledgeSpaces", "mine", SortType.UPDATE_TIME],
                    ["knowledgeSpaces", "mine", SortType.NAME],
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
        } catch {
            showToast({
                message: editingSpace ? localize("com_knowledge.update_space_failed") : localize("com_knowledge.create_space_failed"),
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const handleDragStateChange = (dragging: boolean, error?: string | null) => {
        setIsDragging(dragging);
        setDragError(error || null);
    };

    const locationKey = fileManager.currentFolderId || activeSpace?.id || "";
    const contextLabel = fileManager.currentFolderId ? localize("com_knowledge.folder") : localize("com_knowledge.knowledge_space");

    // Knowledge square view
    if (showKnowledgeSquare) {
        return (
            <div className="relative h-full flex">
                <KnowledgeSquare
                    onBack={() => setShowKnowledgeSquare(false)}
                    title={localize("com_knowledge.explore_square")}
                    subtitle={localize("com_knowledge.explore_more_spaces")}
                    searchPlaceholder={localize("com_knowledge.search_space_placeholder")}
                    emptyText={localize("com_knowledge.no_matched_space")}
                    joinToastPrefix={localize("com_knowledge.applied_to_join_space")}
                    onPreviewSpace={(id) => {
                        setSquarePreviewSpaceId(id);
                        setSquarePreviewDrawerOpen(true);
                    }}
                    statusOverride={squareStatusOverride}
                />
                <KnowledgeSpacePreviewDrawer
                    spaceId={squarePreviewSpaceId}
                    open={squarePreviewDrawerOpen}
                    onOpenChange={(open) => {
                        setSquarePreviewDrawerOpen(open);
                        if (!open) setSquarePreviewSpaceId(undefined);
                    }}
                    onSquareStatusChange={(id, status) => {
                        setSquareStatusOverride((prev) => ({ ...prev, [String(id)]: status }));
                    }}
                />
            </div>
        );
    }

    return (
        <div className="relative h-full flex">
            {/* Drag and Drop Overlay */}
            {isDragging && (
                <div className={`absolute inset-0.5 z-[100] rounded-[12px] bg-[rgba(255,255,255,0.7)] backdrop-blur-[16px] flex flex-col items-center justify-center pointer-events-none transition-all duration-300 ${dragError ? 'border border-dashed border-red-500' : 'border border-dashed'}`}>
                    <div className="flex flex-col items-center justify-center p-8 bg-white/50 rounded-2xl">
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

            <KnowledgeSpaceSidebar
                activeSpaceId={activeSpace?.id}
                onSpaceSelect={handleSpaceSelect}
                onCreateSpace={handleCreateSpace}
                onSpaceSettings={handleSpaceSettings}
                onManageMembers={(space) => {
                    setMemberDialogSpace(space);
                    setMemberDialogOpen(true);
                }}
                onKnowledgeSquare={() => setShowKnowledgeSquare(true)}
            />

            {activeSpace ? (
                <div ref={aiPane.splitContainerRef} className="flex-1 flex h-full overflow-hidden">
                    {/* Left: file list */}
                    <div
                        style={{ width: aiPane.showAiAssistant ? `${aiPane.aiSplitWidth}px` : '100%' }}
                        className="h-full flex-shrink-0 overflow-hidden"
                    >
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
                            onSort={fileManager.handleSort}
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
                        />
                    </div>

                    {/* Splitter */}
                    {aiPane.showAiAssistant && (
                        <div
                            onMouseDown={aiPane.startSplitResize}
                            className="group relative w-[1px] cursor-col-resize bg-[#e5e6eb] transition-all hover:w-1 hover:bg-primary active:w-1 active:bg-primary z-20 shrink-0"
                        >
                            <div className="absolute inset-y-0 -left-1.5 -right-1.5 z-10" />
                        </div>
                    )}

                    {/* Right: AI assistant */}
                    {aiPane.showAiAssistant && (
                        <div className="flex-1 h-full min-w-[360px] bg-white border-l border-[#e5e6eb]">
                            <KnowledgeAiPanel
                                spaceId={String(activeSpace.id)}
                                folderId={fileManager.currentFolderId}
                                contextLabel={contextLabel}
                                availableTags={spaceTags}
                                onClose={() => aiPane.setShowAiAssistant(false)}
                            />
                        </div>
                    )}
                </div>
            ) : (
                /* Empty state when no space is selected */
                <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
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
                    setMemberDialogSpace(activeSpace);
                    setMemberDialogOpen(true);
                }}
            />

            <KnowledgeSpaceMemberDialog
                open={memberDialogOpen}
                onOpenChange={setMemberDialogOpen}
                space={memberDialogSpace}
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
        </div>
    );
}
