import { useEffect, useState } from "react";
import { ChevronRight, X } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { FileCard } from "./SpaceDetail/FileCard";
import {
    KnowledgeFile,
    KnowledgeSpace,
    SPACE_CHILDREN_STATUS_SUCCESS_ONLY,
    SpaceRole,
    VisibilityType,
    getJoinedSpacesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    subscribeSpaceApi,
    unsubscribeSpaceApi
} from "~/api/knowledge";
import { cn } from "~/utils";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";

interface KnowledgeSpacePreviewDrawerProps {
    spaceId: string | undefined;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Notify parent to sync square card status */
    onSquareStatusChange?: (spaceId: string, status: "join" | "joined" | "pending" | "rejected") => void;
}

export function KnowledgeSpacePreviewDrawer({
    spaceId,
    open,
    onOpenChange,
    onSquareStatusChange,
}: KnowledgeSpacePreviewDrawerProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const { showToast } = useToastContext();
    const MAX_JOINED_SPACES = 50;

    const [space, setSpace] = useState<KnowledgeSpace | null>(null);
    const [status, setStatus] = useState<"none" | "joined" | "pending" | "rejected">("none");
    const [subscribing, setSubscribing] = useState(false);
    const [filesPreview, setFilesPreview] = useState<KnowledgeFile[]>([]);
    const [childrenPage, setChildrenPage] = useState(1);
    const [childrenTotal, setChildrenTotal] = useState(0);
    const [loadingChildrenMore, setLoadingChildrenMore] = useState(false);
    const [parentStack, setParentStack] = useState<string[]>([]);
    const [parentNameStack, setParentNameStack] = useState<string[]>([]);
    const currentParentId = parentStack.length > 0 ? parentStack[parentStack.length - 1] : undefined;

    /**
     * 广场预览文件列表状态过滤（对齐 /space/{id}/info 的 user_role）：
     * - creator / admin：不限制
     * - member 与 user_role 为 null（映射为 member）：仅展示解析成功的文件
     */
    const getPreviewFileStatusFilter = (s: KnowledgeSpace): number[] | undefined => {
        if (s.role === SpaceRole.CREATOR || s.role === SpaceRole.ADMIN) {
            return undefined;
        }
        return SPACE_CHILDREN_STATUS_SUCCESS_ONLY;
    };

    useEffect(() => {
        if (!open || !spaceId) return;
        console.info("[KnowledgeSpacePreviewDrawer] open", { open, spaceId });

        setSpace(null);
        setStatus("none");
        setFilesPreview([]);
        setChildrenPage(1);
        setChildrenTotal(0);
        setParentStack([]);
        setParentNameStack([]);
        setLoadingChildrenMore(false);

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
                const sub = String(info.subscriptionStatus ?? "").toLowerCase();
                // /info may still set is_followed when subscription_status is rejected; prefer explicit status.
                if (sub === "rejected") {
                    setStatus("rejected");
                    onSquareStatusChange?.(String(info.id), "rejected");
                } else if (info.isPending) {
                    setStatus("pending");
                    onSquareStatusChange?.(String(info.id), "pending");
                } else if (info.isFollowed) {
                    setStatus("joined");
                    onSquareStatusChange?.(String(info.id), "joined");
                } else {
                    setStatus("none");
                    onSquareStatusChange?.(String(info.id), "join");
                }
            })
            .catch(() => {
                console.warn("[KnowledgeSpacePreviewDrawer] load space info failed", { spaceId });
                showToast({ message: localize("com_knowledge.space_invalid_or_deleted"), severity: NotificationSeverity.WARNING });
                onOpenChange(false);
            });
    }, [open, spaceId]);

    // Load file preview list for spaces that are visible to the current user
    useEffect(() => {
        if (!space || !canViewFiles) {
            setFilesPreview([]);
            setChildrenTotal(0);
            setChildrenPage(1);
            return;
        }

        // Reset + initial load
        setFilesPreview([]);
        setChildrenPage(1);
        setChildrenTotal(0);
        setLoadingChildrenMore(false);

        const fileStatusFilter = getPreviewFileStatusFilter(space);
        getSpaceChildrenApi({
            space_id: space.id,
            ...(currentParentId ? { parent_id: currentParentId } : {}),
            page: 1,
            page_size: 20,
            ...(fileStatusFilter ? { file_status: fileStatusFilter } : {}),
        })
            .then(res => {
                setFilesPreview(res.data);
                setChildrenTotal(res.total);
            })
            .catch(() => {
                setFilesPreview([]);
                setChildrenTotal(0);
            });
        // Include join/subscription signals so file list loads when async info maps to joined without subscription_status.
    }, [space?.id, space?.role, space?.visibility, space?.subscriptionStatus, space?.isFollowed, currentParentId, status]);

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
                page: nextPage,
                page_size: 20,
                ...(fileStatusFilter ? { file_status: fileStatusFilter } : {}),
            });
            setFilesPreview(prev => [...prev, ...res.data]);
            setChildrenTotal(res.total);
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
    const subscriptionRejected =
        String(space?.subscriptionStatus ?? "").toLowerCase() === "rejected" || status === "rejected";
    // /info sometimes omits subscription_status but still sets is_followed for already-approved members.
    const canViewFiles =
        !!space &&
        !subscriptionRejected &&
        (space.visibility === VisibilityType.PUBLIC ||
            (space.visibility === VisibilityType.APPROVAL &&
                (String(space.subscriptionStatus ?? "").toLowerCase() === "subscribed" ||
                    space.isFollowed === true ||
                    status === "joined")));

    const handleClickAction = () => {
        if (!space) return;

        if (status === "joined" || status === "pending" || status === "rejected") return;
        if (subscribing) return;

        const nextUiStatus: "joined" | "pending" = isPublic ? "joined" : "pending";
        const prevUiStatus = status;

        (async () => {
            setSubscribing(true);
            setStatus(nextUiStatus);
            onSquareStatusChange?.(String(space.id), nextUiStatus);

            const rollback = () => {
                setStatus(prevUiStatus);
                onSquareStatusChange?.(String(space.id), "join");
            };

            try {
                try {
                    const joinedSpaces = await getJoinedSpacesApi();
                    if (joinedSpaces.length >= MAX_JOINED_SPACES) {
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

                await subscribeSpaceApi(space.id);
                if (isPublic) {
                    showToast({ message: localize("com_knowledge.join_success"), severity: NotificationSeverity.SUCCESS });
                } else {
                    showToast({ message: localize("com_knowledge.subscribe_apply_sent"), severity: NotificationSeverity.SUCCESS });
                }
            } catch (e) {
                rollback();
                const rawMessage =
                    (e as any)?.message ||
                    (e as any)?.status_message ||
                    "";

                if (typeof rawMessage === "string" && rawMessage.includes("maximum of 50 knowledge spaces")) {
                    showToast({ message: localize("com_knowledge.join_space_limit_reached_50"), severity: NotificationSeverity.WARNING });
                } else {
                    const message =
                        rawMessage ||
                        localize("com_knowledge.operation_failed_retry");
                    showToast({ message, severity: NotificationSeverity.ERROR });
                }
            } finally {
                setSubscribing(false);
            }
        })();
    };

    const getButtonConfig = () => {
        if (status === "joined") return { label: localize("com_knowledge.exit_space_short"), variant: "secondary" as const, disabled: subscribing };
        if (status === "pending") return { label: localize("com_knowledge.withdraw_application"), variant: "secondary" as const, disabled: subscribing };
        if (status === "rejected") return { label: localize("com_knowledge.reapply"), variant: "outline" as const, disabled: subscribing };
        if (isPublic) return { label: localize("com_knowledge.join"), variant: "default" as const, disabled: subscribing };
        return { label: localize("com_knowledge.join"), variant: "outline" as const, disabled: subscribing };
    };

    const btn = getButtonConfig();

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className={cn(
                    "flex h-full min-h-0 flex-col overflow-hidden p-0 px-12 w-[1000px] sm:max-w-[1000px]",
                    "touch-mobile:inset-0 touch-mobile:left-0 touch-mobile:top-0 touch-mobile:h-dvh touch-mobile:w-screen touch-mobile:max-w-none touch-mobile:translate-x-0 touch-mobile:translate-y-0 touch-mobile:px-4"
                )}
                hideClose
            >
                {!isH5 ? (
                    <button
                        type="button"
                        aria-label={localize("com_knowledge.collapse_drawer")}
                        onClick={() => onOpenChange(false)}
                        className="absolute left-1 top-1/2 z-20 flex h-16 w-6 -translate-y-1/2 items-center justify-center bg-white text-[#C9CDD4] hover:text-[#B6BBC5]"
                    >
                        <ChevronRight className="size-6 stroke-[2.75]" />
                    </button>
                ) : (
                    <button
                        type="button"
                        aria-label={localize("com_knowledge.close")}
                        onClick={() => onOpenChange(false)}
                        className="absolute right-4 top-4 z-20 inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
                    >
                        <X className="size-4" />
                    </button>
                )}
                {space && (
                    <>
                        <SheetHeader className="gap-0 border-b border-gray-100 px-6 pb-4 pt-6 text-left touch-mobile:px-0 touch-mobile:pt-6">
                            <SheetTitle className="mb-1 text-[#1d2129] leading-tight font-semibold touch-mobile:pr-10">
                                {space.name}
                            </SheetTitle>
                            {space.description && (
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <p className="text-sm text-[#86909c] leading-relaxed line-clamp-2 cursor-default text-left">
                                            {space.description}
                                        </p>
                                    </TooltipTrigger>
                                    <TooltipContent className="shadow-lg py-2 max-w-md text-sm">
                                        {space.description}
                                    </TooltipContent>
                                </Tooltip>
                            )}

                            <div className="flex items-center gap-1.5 mb-3 mt-4">
                                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[#165DFF] text-white text-xs">
                                    {space.creator?.[0] || "?"}
                                </span>
                                <span className="text-sm text-[#86909c]">{space.creator}</span>
                            </div>

                            <div className="flex items-center justify-between">
                                <div className="flex items-center text-sm text-[#86909c]">
                                    <span className="mr-3">{space.fileCount ?? 0} {localize("com_knowledge.articles_count")}</span>
                                    <span>{space.memberCount ?? 0} {localize("com_knowledge.users_count")}</span>
                                </div>
                                <Button
                                    variant={btn.variant}
                                    className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${status === "joined"
                                        ? "bg-[#F2F3F5] text-[#86909C] border-[#E5E6EB]"
                                        : status === "pending"
                                            ? "bg-[#F2F3F5] text-[#C9CDD4] border-[#E5E6EB]"
                                            : ""
                                        }`}
                                    disabled={btn.disabled}
                                    onClick={handleClickAction}
                                >
                                    {btn.label}
                                </Button>
                            </div>
                        </SheetHeader>

                        <div
                            className="scrollbar-on-hover flex-1 min-h-0 overflow-y-auto px-6 py-4 touch-mobile:px-0"
                            onScroll={(e) => {
                                const el = e.currentTarget;
                                if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
                                    void loadMoreChildren();
                                }
                            }}
                        >
                            {canViewFiles ? (
                                <div className="space-y-2">
                                    <div className="mb-1 text-sm text-[#4E5969] flex items-center gap-2 flex-wrap">
                                        <button
                                            type="button"
                                            className="text-[#165DFF] hover:underline"
                                            onClick={() => goToParentDepth(0)}
                                        >
                                            {localize("com_knowledge.all_files")}</button>
                                        {parentNameStack.map((name, idx) => {
                                            const depth = idx + 1;
                                            return (
                                                <span key={`${name}-${idx}`} className="flex items-center gap-2">
                                                    <span className="text-[#86909c]">/</span>
                                                    <button
                                                        type="button"
                                                        onClick={() => goToParentDepth(depth)}
                                                        className={depth === parentNameStack.length ? "text-[#86909c] cursor-default" : "text-[#165DFF] hover:underline"}
                                                        disabled={depth === parentNameStack.length}
                                                    >
                                                        {name}
                                                    </button>
                                                </span>
                                            );
                                        })}
                                    </div>
                                    {filesPreview.length === 0 ? (
                                        <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">
                                            {localize("com_knowledge.no_files")}</div>
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
                                        <div className="py-3 text-center text-[12px] text-[#C9CDD4]">
                                            {localize("com_knowledge.loading")}</div>
                                    )}

                                    {!loadingChildrenMore && filesPreview.length > 0 && filesPreview.length >= childrenTotal && (
                                        <div className="py-3 text-center text-[12px] text-[#C9CDD4]">
                                            {localize("com_knowledge.no_more_content")}</div>
                                    )}
                                </div>
                            ) : space?.visibility === VisibilityType.APPROVAL ? (
                                <div className="flex flex-col items-center justify-center h-full min-h-[360px]">
                                    <img
                                        className="size-[140px] object-contain mb-4"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/review.png`}
                                        alt="Locked"
                                    />
                                    <div className="text-[#1d2129] text-[14px]">
                                        {localize("com_knowledge.space_view_requires_approval")}
                                    </div>
                                </div>
                            ) : null}
                        </div>
                    </>
                )}
            </SheetContent>
        </Sheet>
    );
}
