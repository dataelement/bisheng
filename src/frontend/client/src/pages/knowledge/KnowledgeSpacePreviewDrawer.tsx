import { Tooltip as SharedTooltip } from '@bisheng/ui';
import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyStateIllustration, NoPermissionIllustration } from "~/components/illustrations";
import { KnowledgePreviewNavigation } from "./KnowledgePreviewNavigation";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "~/components/ui/Sheet";

import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { FileCard } from "./SpaceDetail/FileCard";
import {
    KnowledgeFile,
    KnowledgeSpace,
    SpaceRole,
    VisibilityType,
    getJoinedSpacesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    subscribeSpaceApi,
    unsubscribeSpaceApi
} from "~/api/knowledge";
import { checkResourceAction } from "~/api/permission";
import { cn } from "~/utils";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useLocalize, usePrefersMobileLayout, useScrollRevealRef } from "~/hooks";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { getPreviewFileStatusFilter, getSpaceJoinButton, resolveSpaceJoinStatus, type SpaceJoinStatus } from "./spaceSubscriptionState";

interface KnowledgeSpacePreviewDrawerProps {
    spaceId: string | undefined;
    initialSpace?: KnowledgeSpace | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Notify parent to sync square card status */
    onSquareStatusChange?: (spaceId: string, status: "join" | "joined" | "pending" | "rejected") => void;
}

export function KnowledgeSpacePreviewDrawer({
    spaceId,
    initialSpace = null,
    open,
    onOpenChange,
    onSquareStatusChange,
}: KnowledgeSpacePreviewDrawerProps) {
    const localize = useLocalize();
    const isMobileLayout = usePrefersMobileLayout();
    const spacePreviewScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const { showToast } = useToastContext();
    const { isOverQuota } = useEffectiveQuota();

    const [space, setSpace] = useState<KnowledgeSpace | null>(null);
    const [status, setStatus] = useState<SpaceJoinStatus>("none");
    const [subscribing, setSubscribing] = useState(false);
    const [filesPreview, setFilesPreview] = useState<KnowledgeFile[]>([]);
    // Bumped on every drawer open. The file-list effect below keys on values derived from
    // `space`/`status`; reopening the SAME space leaves those primitives unchanged, so the
    // effect would not re-run and the cleared list would never reload. This token forces a
    // fresh fetch on each open.
    const [filesReloadKey, setFilesReloadKey] = useState(0);
    const [childrenPage, setChildrenPage] = useState(1);
    const [childrenTotal, setChildrenTotal] = useState(0);
    const [loadingChildrenMore, setLoadingChildrenMore] = useState(false);
    // True while the FIRST page of the file list is in flight, so the empty
    // state is not flashed before data arrives.
    const [loadingFiles, setLoadingFiles] = useState(false);
    // Guards against out-of-order responses when the effect re-fires (space /
    // folder switch) while a previous first-page request is still pending.
    const filesRequestSeqRef = useRef(0);
    // F027: cursor for the next page of `getSpaceChildrenApi`. null on first
    // page (and after a parent/space switch). Backend `next_cursor` advances
    // it as the user scrolls.
    const preview_next_cursor_ref = useRef<string | null>(null);
    const [loadingSpace, setLoadingSpace] = useState(false);
    const [canViewApprovalContent, setCanViewApprovalContent] = useState<boolean | null>(null);
    const [parentStack, setParentStack] = useState<string[]>([]);
    const [parentNameStack, setParentNameStack] = useState<string[]>([]);
    const currentParentId = parentStack.length > 0 ? parentStack[parentStack.length - 1] : undefined;
    const initialSpaceRef = useRef<KnowledgeSpace | null>(initialSpace);
    const onOpenChangeRef = useRef(onOpenChange);
    const onSquareStatusChangeRef = useRef(onSquareStatusChange);
    const lastSyncedSquareStatusRef = useRef<string | null>(null);
    const localizeRef = useRef(localize);
    const showToastRef = useRef(showToast);

    useEffect(() => {
        initialSpaceRef.current = initialSpace;
    }, [initialSpace]);

    useEffect(() => {
        onOpenChangeRef.current = onOpenChange;
    }, [onOpenChange]);

    useEffect(() => {
        onSquareStatusChangeRef.current = onSquareStatusChange;
    }, [onSquareStatusChange]);

    useEffect(() => {
        localizeRef.current = localize;
    }, [localize]);

    useEffect(() => {
        showToastRef.current = showToast;
    }, [showToast]);

    const syncPreviewStatus = useCallback((info: KnowledgeSpace) => {
        const nextStatus = resolveSpaceJoinStatus(info);
        setStatus(nextStatus);
        const squareStatus = nextStatus === "none" ? "join" : nextStatus;
        const syncKey = `${String(info.id)}:${squareStatus}`;
        if (lastSyncedSquareStatusRef.current === syncKey) return;
            lastSyncedSquareStatusRef.current = syncKey;
        onSquareStatusChangeRef.current?.(String(info.id), squareStatus);
    }, []);

    useEffect(() => {
        if (!open || !spaceId) return;
        console.info("[KnowledgeSpacePreviewDrawer] open", { open, spaceId });

        const fallbackSpace = initialSpaceRef.current;

        setLoadingSpace(true);
        setSpace(fallbackSpace ?? null);
        setStatus("none");
        setFilesPreview([]);
        setChildrenPage(1);
        setChildrenTotal(0);
        setCanViewApprovalContent(null);
        setParentStack([]);
        setParentNameStack([]);
        setLoadingChildrenMore(false);
        setFilesReloadKey(k => k + 1);
        lastSyncedSquareStatusRef.current = null;

        if (fallbackSpace) {
            syncPreviewStatus(fallbackSpace);
        }

        // 1) Top detail: GET /api/v1/knowledge/space/{space_id}/info
        getSpaceInfoApi(spaceId)
            .then(info => {
                console.info("[KnowledgeSpacePreviewDrawer] loaded space info", {
                    spaceId,
                    visibility: info.visibility,
                    subscriptionStatus: info.subscriptionStatus,
                    isFollowed: info.isFollowed,
                    isPending: info.isPending,
                });
                setSpace(info);
                syncPreviewStatus(info);
            })
            .catch(() => {
                console.warn("[KnowledgeSpacePreviewDrawer] load space info failed", { spaceId });
                if (fallbackSpace) {
                    setSpace(fallbackSpace);
                    syncPreviewStatus(fallbackSpace);
                    return;
                }
                showToastRef.current({
                    message: localizeRef.current("com_knowledge.space_invalid_or_deleted"),
                    severity: NotificationSeverity.WARNING,
                });
                onOpenChangeRef.current(false);
            })
            .finally(() => {
                setLoadingSpace(false);
            });
    }, [open, spaceId, syncPreviewStatus]);

    // Load file preview list for spaces that are visible to the current user
    useEffect(() => {
        if (!space || !canViewFiles) {
            filesRequestSeqRef.current += 1;
            setFilesPreview([]);
            setChildrenTotal(0);
            setChildrenPage(1);
            setLoadingFiles(false);
            return;
        }

        // Reset + initial load
        const requestSeq = ++filesRequestSeqRef.current;
        setFilesPreview([]);
        setChildrenPage(1);
        setChildrenTotal(0);
        setLoadingChildrenMore(false);
        setLoadingFiles(true);
        // F027: reset cursor so the first request after a parent/space switch
        // fetches page 1 (cursor=null) instead of inheriting a stale token.
        preview_next_cursor_ref.current = null;

        const fileStatusFilter = getPreviewFileStatusFilter(space);
        getSpaceChildrenApi({
            space_id: space.id,
            ...(currentParentId ? { parent_id: currentParentId } : {}),
            // F027: first page = no cursor.
            page_size: 20,
            ...(fileStatusFilter ? { file_status: fileStatusFilter } : {}),
        })
            .then(res => {
                if (requestSeq !== filesRequestSeqRef.current) return;
                setFilesPreview(res.data);
                // F027: derive a count surrogate from `has_more` since `total`
                // is gone (used only to decide "load more" visibility).
                setChildrenTotal(res.has_more ? res.data.length + 1 : res.data.length);
                preview_next_cursor_ref.current = res.next_cursor ?? null;
            })
            .catch(() => {
                if (requestSeq !== filesRequestSeqRef.current) return;
                setFilesPreview([]);
                setChildrenTotal(0);
            })
            .finally(() => {
                if (requestSeq !== filesRequestSeqRef.current) return;
                setLoadingFiles(false);
            });
        // Include join/subscription signals so file list loads when async info maps to joined without subscription_status.
        // canViewApprovalContent is resolved asynchronously (visible) for APPROVAL spaces; without it as a
        // dependency the effect would have already bailed (canViewFiles=false) and never refetch once access is granted.
    }, [space?.id, space?.role, space?.visibility, space?.subscriptionStatus, space?.isFollowed, currentParentId, status, filesReloadKey, canViewApprovalContent]);

    const loadMoreChildren = async () => {
        if (!space || !canViewFiles) return;
        if (loadingChildrenMore) return;
        if (filesPreview.length >= childrenTotal) return;

        const nextPage = childrenPage + 1;
        setLoadingChildrenMore(true);
        try {
            const fileStatusFilter = getPreviewFileStatusFilter(space);
            const res = await getSpaceChildrenApi({
                space_id: space.id,
                ...(currentParentId ? { parent_id: currentParentId } : {}),
                // F027: page-number replaced by `cursor` from previous response.
                cursor: preview_next_cursor_ref.current,
                page_size: 20,
                ...(fileStatusFilter ? { file_status: fileStatusFilter } : {}),
            });
            setFilesPreview(prev => [...prev, ...res.data]);
            // F027: surrogate total derived from accumulated rows + has_more
            // (1-row sentinel so the "load more" UI stays visible).
            const newRowCount = filesPreview.length + res.data.length;
            setChildrenTotal(res.has_more ? newRowCount + 1 : newRowCount);
            preview_next_cursor_ref.current = res.next_cursor ?? null;
            setChildrenPage(nextPage);
        } catch {
            // ignore
        } finally {
            setLoadingChildrenMore(false);
        }
    };

    const goToParentDepth = (depth: number) => {
        // depth=0 => 全部文件（根目录/未传 parent_id）
        setParentStack((prev) => prev.slice(0, depth));
        setParentNameStack((prev) => prev.slice(0, depth));
    };

    const handlePreviewFile = (fileId: string) => {
        if (!space) return;
        const file = filesPreview.find((f) => f.id === fileId);
        const fileName = file?.name || localize("com_knowledge.unknown_file");
        const ext = fileName.split(".").pop()?.toLowerCase() || "";
        const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${fileId}?name=${encodeURIComponent(fileName)}&type=${encodeURIComponent(ext)}&spaceId=${encodeURIComponent(space.id)}`;
        window.open(url, "_blank");
    };

    const isPublic = space?.visibility === VisibilityType.PUBLIC;
    const isOwnerOrAdmin = space?.role === SpaceRole.CREATOR || space?.role === SpaceRole.ADMIN;
    const subscriptionRejected =
        String(space?.subscriptionStatus ?? "").toLowerCase() === "rejected" || status === "rejected";
    const hasReadableGrant =
        !!space &&
        !subscriptionRejected &&
        (
            isOwnerOrAdmin ||
            String(space.subscriptionStatus ?? "").toLowerCase() === "subscribed" ||
            space.isFollowed === true ||
            status === "joined"
        );
    const canViewFiles =
        isPublic ||
        isOwnerOrAdmin ||
        (
            hasReadableGrant &&
            (
                space?.visibility !== VisibilityType.APPROVAL ||
                canViewApprovalContent === true
            )
        );

    useEffect(() => {
        if (!space || space.visibility !== VisibilityType.APPROVAL || isOwnerOrAdmin || !hasReadableGrant) {
            setCanViewApprovalContent(null);
            return;
        }

        let cancelled = false;
        const controller = new AbortController();

        checkResourceAction(
            {
                resource_type: "knowledge_space",
                resource_id: String(space.id),
                action: "visible",
            },
            { signal: controller.signal },
        )
            .then((res) => {
                if (!cancelled) {
                    setCanViewApprovalContent(Boolean(res?.allowed));
                    if (res?.allowed === false && status === "joined") {
                        const nextSpace: KnowledgeSpace = {
                            ...space,
                            isFollowed: false,
                            subscriptionStatus: "not_subscribed",
                            squareStatus: "join",
                        };
                        setSpace(nextSpace);
                        syncPreviewStatus(nextSpace);
                    }
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setCanViewApprovalContent(false);
                }
            });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [space, isOwnerOrAdmin, hasReadableGrant, status, syncPreviewStatus]);

    const handleClickAction = () => {
        if (!space) return;

        if (status === "joined" || status === "pending") return;
        if (subscribing) return;

        const prevUiStatus = status;
        const prevSquareStatus = prevUiStatus === "none" ? "join" : prevUiStatus;

        (async () => {
            setSubscribing(true);

            const rollback = () => {
                setStatus(prevUiStatus);
                onSquareStatusChange?.(String(space.id), prevSquareStatus);
            };

            try {
                try {
                    const joinedSpaces = await getJoinedSpacesApi();
                    if (isOverQuota("knowledge_space_subscribe", joinedSpaces.length)) {
                        rollback();
                        showToast({
                            message: localize("com_knowledge.join_space_limit_reached_50"),
                            severity: NotificationSeverity.WARNING,
                        });
                        return;
                    }
                } catch {
                    // If the limit check fails, fall back to existing behavior.
                }

                const result = await subscribeSpaceApi(space.id);
                const nextUiStatus: "joined" | "pending" = result.status === "subscribed" ? "joined" : "pending";
                setStatus(nextUiStatus);
                setSpace((prev) =>
                    prev
                        ? {
                              ...prev,
                              squareStatus: nextUiStatus,
                              subscriptionStatus: result.status,
                              isFollowed: nextUiStatus === "joined",
                              isPending: nextUiStatus === "pending",
                          }
                        : prev
                );
                onSquareStatusChange?.(String(space.id), nextUiStatus);
                if (nextUiStatus === "joined") {
                    showToast({ message: localize("com_knowledge.join_success"), severity: NotificationSeverity.SUCCESS });
                } else {
                    showToast({ message: localize("com_knowledge.subscribe_apply_sent"), severity: NotificationSeverity.SUCCESS });
                }
            } catch (e) {
                rollback();
                const code = (e as any)?.status_code;
                const rawMessage =
                    (e as any)?.message ||
                    (e as any)?.status_message ||
                    "";

                // Backend errcode 18032: SpaceSubscribeLimitError (join limit reached)
                if (code === 18032) {
                    showToast({ message: localize("com_knowledge.join_space_limit_reached_50"), severity: NotificationSeverity.WARNING });
                } else {
                    const message =
                        rawMessage ||
                        localize("com_knowledge.operation_failed_retry");
                    showToast({ message, severity: NotificationSeverity.WARNING });
                }
            } finally {
                setSubscribing(false);
            }
        })();
    };

    const btn = getSpaceJoinButton(status, isPublic, subscribing);

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className={cn(
                    "flex h-full min-h-0 flex-col gap-0 overflow-hidden p-0 px-6 w-full sm:max-w-[1000px]",
                    "touch-mobile:inset-0 touch-mobile:left-0 touch-mobile:top-0 touch-mobile:h-dvh touch-mobile:w-screen touch-mobile:max-w-none touch-mobile:translate-x-0 touch-mobile:translate-y-0 touch-mobile:px-4"
                )}
                hideClose
            >
                <KnowledgePreviewNavigation onClose={() => onOpenChange(false)} />
                {space ? (
                    <>
                        <SheetHeader className={cn("gap-0 border-b border-border-base px-0 py-4 text-left", isMobileLayout && "pt-14")}>
                            <div className="flex items-start justify-between gap-4">
                                <SheetTitle className="min-w-0 flex-1 break-words text-text-1 leading-tight font-semibold">
                                    {space.name}
                                </SheetTitle>
                                <Button
                                    variant={btn.variant}
                                    size="medium"
                                    className="shrink-0"
                                    disabled={btn.disabled}
                                    onClick={handleClickAction}
                                >
                                    {localize(btn.label)}
                                </Button>
                            </div>
                            {space.description && (
                                <SharedTooltip  content={space.description} ><p className="text-sm text-text-3 leading-relaxed line-clamp-2 cursor-default text-left">
                                            {space.description}
                                        </p></SharedTooltip>
                            )}

                            <div className="flex items-center gap-1.5 mb-3 mt-4">
                                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-xs">
                                    {space.creator?.[0] || "?"}
                                </span>
                                <span className="text-sm text-text-3">{space.creator}</span>
                            </div>

                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-body text-text-3">
                                <span>{space.fileCount ?? 0} {localize("com_knowledge.articles_count")}</span>
                                <span>{space.memberCount ?? 0} {localize("com_knowledge.users_count")}</span>
                            </div>
                        </SheetHeader>

                        <div
                            ref={spacePreviewScrollRevealRef}
                            className="scrollbar-on-scroll flex-1 min-h-0 overflow-y-auto py-4"
                            onScroll={(e) => {
                                const el = e.currentTarget;
                                if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
                                    void loadMoreChildren();
                                }
                            }}
                        >
                            {canViewFiles ? (
                                <div className="flex min-h-full flex-col space-y-2">
                                    <div className="mb-1 text-sm text-text-2 flex items-center gap-2 flex-wrap">
                                        <button
                                            type="button"
                                            className="text-blue-500 hover:underline"
                                            onClick={() => goToParentDepth(0)}
                                        >
                                            {localize("com_knowledge.all_files")}</button>
                                        {parentNameStack.map((name, idx) => {
                                            const depth = idx + 1;
                                            return (
                                                <span key={`${name}-${idx}`} className="flex items-center gap-2">
                                                    <span className="text-text-3">/</span>
                                                    <button
                                                        type="button"
                                                        onClick={() => goToParentDepth(depth)}
                                                        className={depth === parentNameStack.length ? "text-text-3 cursor-default" : "text-blue-500 hover:underline"}
                                                        disabled={depth === parentNameStack.length}
                                                    >
                                                        {name}
                                                    </button>
                                                </span>
                                            );
                                        })}
                                    </div>
                                    {loadingFiles ? (
                                        <div className="flex flex-1 items-center justify-center">
                                            <LoadingIcon className="size-20 text-primary" />
                                        </div>
                                    ) : filesPreview.length === 0 ? (
                                        <div className="flex flex-1 flex-col items-center justify-center text-center">
                                            <EmptyStateIllustration className="size-[120px] mb-4" />
                                            <p className="text-[14px] font-normal text-text-3">
                                                {localize("com_knowledge.no_files")}
                                            </p>
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-2 gap-3 min-[768px]:grid-cols-3">
                                            {filesPreview.map((f) => (
                                                <FileCard
                                                    key={f.id}
                                                    file={f}
                                                    userRole={space?.role ?? SpaceRole.MEMBER}
                                                    isSelected={false}
                                                    onSelect={() => { }}
                                                    onDownload={() => { }}
                                                    onRename={() => { }}
                                                    onDelete={() => { }}
                                                    onEditTags={() => { }}
                                                    onNavigateFolder={(folderId) => {
                                                        if (!folderId) return;
                                                        setParentStack((prev) => [...prev, folderId]);
                                                        setParentNameStack((prev) => [...prev, f.name]);
                                                    }}
                                                    onPreview={handlePreviewFile}
                                                    disableClickNavigate
                                                    hideSelectionCheckbox
                                                    hideDownloadActions
                                                />
                                            ))}
                                        </div>
                                    )}

                                    {loadingChildrenMore && (
                                        <div className="py-3 text-center text-[12px] text-text-4">
                                            {localize("com_knowledge.loading")}</div>
                                    )}

                                    {!loadingChildrenMore && filesPreview.length > 0 && filesPreview.length >= childrenTotal && (
                                        <div className="py-3 text-center text-[12px] text-text-4">
                                            {localize("com_knowledge.no_more_content")}</div>
                                    )}
                                </div>
                            ) : space?.visibility === VisibilityType.APPROVAL ? (
                                <div className="flex flex-col items-center justify-center h-full min-h-[360px]">
                                    <NoPermissionIllustration className="size-[120px] mb-4" />
                                    <div className="text-[14px] font-normal text-text-3">
                                        {localize("com_knowledge.space_view_requires_approval")}
                                    </div>
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center h-full min-h-[360px]">
                                    <NoPermissionIllustration className="size-[120px] mb-4" />
                                    <div className="text-[14px] font-normal text-text-3">
                                        {localize("com_knowledge.space_view_requires_join")}
                                    </div>
                                </div>
                            )}
                        </div>
                    </>
                ) : (
                    <div className="flex flex-1 items-center justify-center py-4 text-sm text-text-3">
                        {loadingSpace ? (
                            <LoadingIcon className="size-20 text-primary" />
                        ) : (
                            localize("com_knowledge.space_invalid_or_deleted")
                        )}
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}
