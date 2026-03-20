import { useEffect, useMemo, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { KnowledgeSpace, VisibilityType, getSquareSpacesApi, getSpaceChildrenApi } from "~/api/knowledge";
import { FileType } from "~/api/knowledge";

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
    const [filesPreview, setFilesPreview] = useState<{ id: string; name: string; type: string }[]>([]);

    useEffect(() => {
        if (!open || !spaceId) return;

        // Fetch space info from the square list — no single-space detail endpoint yet
        getSquareSpacesApi({ page: 1, page_size: 100 })
            .then(res => {
                const found = res.data.find(s => s.id === spaceId) || null;
                if (!found) {
                    showToast({
                        message: "该知识空间已失效或被删除",
                        severity: NotificationSeverity.WARNING,
                    });
                    onOpenChange(false);
                    return;
                }
                setSpace(found);
                setStatus("none");
            })
            .catch(() => {
                showToast({ message: "加载知识空间信息失败", severity: NotificationSeverity.ERROR });
                onOpenChange(false);
            });
    }, [open, spaceId]);

    // Load file preview list for public spaces
    useEffect(() => {
        if (!space || space.visibility !== VisibilityType.PUBLIC) {
            setFilesPreview([]);
            return;
        }
        getSpaceChildrenApi({ space_id: space.id, page: 1, page_size: 20 })
            .then(res => {
                setFilesPreview(res.data.map(f => ({ id: f.id, name: f.name, type: f.type })));
            })
            .catch(() => setFilesPreview([]));
    }, [space?.id]);

    if (!open) return null;

    const isPublic = space?.visibility === VisibilityType.PUBLIC;

    const handleClickAction = () => {
        if (!space) return;

        if (status === "joined" || status === "pending") return;

        if (isPublic) {
            setStatus("joined");
            showToast({ message: "成功加入", severity: NotificationSeverity.SUCCESS });
        } else {
            setStatus("pending");
            showToast({ message: "已发送订阅申请，审批通过即可订阅。", severity: NotificationSeverity.SUCCESS });
        }
    };

    const getButtonConfig = () => {
        if (status === "joined") return { label: "已加入", variant: "secondary" as const, disabled: true };
        if (status === "pending") return { label: "申请中", variant: "secondary" as const, disabled: true };
        if (isPublic) return { label: "加入", variant: "default" as const, disabled: false };
        return { label: "申请", variant: "outline" as const, disabled: false };
    };

    const btn = getButtonConfig();

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                hideClose
                side="right"
                className="w-[960px] sm:max-w-[960px] p-0 px-12 flex flex-col"
            >
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
                                    className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${btn.label === "已加入"
                                        ? "bg-[#F2F3F5] text-[#86909C] border-[#E5E6EB]"
                                        : btn.label === "申请中"
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

                        <div className="flex-1 overflow-y-auto px-6 py-4">
                            {isPublic ? (
                                <div className="space-y-2">
                                    {filesPreview.length === 0 ? (
                                        <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">
                                            暂无文件
                                        </div>
                                    ) : (
                                        filesPreview.map((f) => (
                                            <div
                                                key={f.id}
                                                className="flex items-center justify-between h-10 px-2 border-b border-[#F2F3F5] last:border-0"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span className="inline-flex items-center justify-center w-6 h-6 rounded bg-[#F2F3F5] text-xs text-[#4E5969]">
                                                        {f.type === FileType.FOLDER ? "夹" : "文"}
                                                    </span>
                                                    <span className="text-[13px] text-[#1D2129] truncate max-w-[420px]">
                                                        {f.name}
                                                    </span>
                                                </div>
                                            </div>
                                        ))
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
