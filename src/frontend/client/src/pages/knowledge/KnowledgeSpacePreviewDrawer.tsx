import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { FileCard } from "./SpaceDetail/FileCard";
import { KnowledgeFile, KnowledgeSpace, SpaceRole, VisibilityType, getSpaceChildrenApi, getSpaceInfoApi, subscribeSpaceApi } from "~/api/knowledge";

interface KnowledgeSpacePreviewDrawerProps {
    spaceId: string | undefined;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function KnowledgeSpacePreviewDrawer({
    spaceId,
    open,
    onOpenChange,
}: KnowledgeSpacePreviewDrawerProps) {
    const { showToast } = useToastContext();
    const [space, setSpace] = useState<KnowledgeSpace | null>(null);
    const [status, setStatus] = useState<"none" | "joined" | "pending">("none");
    const [filesPreview, setFilesPreview] = useState<KnowledgeFile[]>([]);
    const [childrenPage, setChildrenPage] = useState(1);
    const [childrenTotal, setChildrenTotal] = useState(0);
    const [loadingChildrenMore, setLoadingChildrenMore] = useState(false);
    const [parentStack, setParentStack] = useState<string[]>([]);
    const [parentNameStack, setParentNameStack] = useState<string[]>([]);
    const currentParentId = parentStack.length > 0 ? parentStack[parentStack.length - 1] : undefined;
    useEffect(() => {
        if (!open || !spaceId) return;

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
                setSpace(info);
                if (info.isPending) setStatus("pending");
                else if (info.isFollowed) setStatus("joined");
                else setStatus("none");
            })
            .catch(() => {
                showToast({ message: "该知识空间已失效或被删除", severity: NotificationSeverity.WARNING });
                onOpenChange(false);
            });
    }, [open, spaceId]);

    // Load file preview list for public spaces
    useEffect(() => {
        if (!space) return;

        if (space.visibility !== VisibilityType.PUBLIC) {
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

        getSpaceChildrenApi({
            space_id: space.id,
            ...(currentParentId ? { parent_id: currentParentId } : {}),
            page: 1,
            page_size: 20,
        })
            .then(res => {
                setFilesPreview(res.data);
                setChildrenTotal(res.total);
            })
            .catch(() => {
                setFilesPreview([]);
                setChildrenTotal(0);
            });
    }, [space?.id, space?.visibility, currentParentId]);

    const loadMoreChildren = async () => {
        if (!space) return;
        if (space.visibility !== VisibilityType.PUBLIC) return;
        if (loadingChildrenMore) return;
        if (filesPreview.length >= childrenTotal) return;

        const nextPage = childrenPage + 1;
        setLoadingChildrenMore(true);
        try {
            const res = await getSpaceChildrenApi({
                space_id: space.id,
                ...(currentParentId ? { parent_id: currentParentId } : {}),
                page: nextPage,
                page_size: 20,
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

    if (!open) return null;

    const isPublic = space?.visibility === VisibilityType.PUBLIC;

    const handleClickAction = () => {
        if (!space) return;

        if (status === "joined" || status === "pending") return;

        (async () => {
            try {
                await subscribeSpaceApi(space.id);
                if (isPublic) {
                    setStatus("joined");
                    showToast({ message: "成功加入", severity: NotificationSeverity.SUCCESS });
                } else {
                    setStatus("pending");
                    showToast({ message: "已发送订阅申请，审批通过即可订阅。", severity: NotificationSeverity.SUCCESS });
                }
            } catch {
                showToast({ message: "操作失败，请稍后重试", severity: NotificationSeverity.ERROR });
            }
        })();
    };

    const getButtonConfig = () => {
        if (status === "joined") return { label: "已订阅", variant: "secondary" as const, disabled: true };
        if (status === "pending") return { label: "申请中", variant: "secondary" as const, disabled: true };
        if (isPublic) return { label: "订阅", variant: "default" as const, disabled: false };
        return { label: "申请", variant: "outline" as const, disabled: false };
    };

    const btn = getButtonConfig();

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className="w-[1000px] sm:max-w-[1000px] p-0 px-12 flex flex-col h-full"
            >
                <button
                    type="button"
                    aria-label="收起抽屉"
                    onClick={() => onOpenChange(false)}
                    className="absolute left-1 top-1/2 -translate-y-1/2 h-16 w-6 bg-white text-[#C9CDD4] hover:text-[#B6BBC5] flex items-center justify-center z-20"
                >
                    <ChevronRight className="size-6 stroke-[2.75]" />
                </button>
                {space && (
                    <>
                        <SheetHeader className="px-6 pt-6 pb-4 gap-0 border-b border-gray-100 text-left">
                            <SheetTitle className="font-semibold text-[#1d2129] leading-tight mb-1">
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
                                    <span className="mr-3">{space.fileCount ?? 0} 篇内容</span>
                                    <span>{space.memberCount ?? 0} 用户</span>
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
                            className="flex-1 overflow-y-auto px-6 py-4"
                            onScroll={(e) => {
                                const el = e.currentTarget;
                                if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
                                    void loadMoreChildren();
                                }
                            }}
                        >
                            {isPublic ? (
                                <div className="space-y-2">
                                    <div className="mb-1 text-sm text-[#4E5969] flex items-center gap-2 flex-wrap">
                                        <button
                                            type="button"
                                            className="text-[#165DFF] hover:underline"
                                            onClick={() => goToParentDepth(0)}
                                        >
                                            全部文件
                                        </button>
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
                                            暂无文件
                                        </div>
                                    ) : (
                                        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
                                            {filesPreview.map((f) => (
                                                <FileCard
                                                    key={f.id}
                                                    file={f}
                                                    userRole={SpaceRole.MEMBER}
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
                                                    disableClickNavigate
                                                    hideSelectionCheckbox
                                                />
                                            ))}
                                        </div>
                                    )}

                                    {loadingChildrenMore && (
                                        <div className="py-3 text-center text-[12px] text-[#C9CDD4]">
                                            加载中...
                                        </div>
                                    )}

                                    {!loadingChildrenMore && filesPreview.length > 0 && filesPreview.length >= childrenTotal && (
                                        <div className="py-3 text-center text-[12px] text-[#C9CDD4]">
                                            没有更多内容了
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center h-full min-h-[360px]">
                                    <img
                                        className="size-[140px] object-contain mb-4"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/review.png`}
                                        alt="Locked"
                                    />
                                    <div className="text-[#1d2129] text-[14px]">
                                        该知识空间内容需申请通过后方可查看
                                    </div>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </SheetContent>
        </Sheet>
    );
}
