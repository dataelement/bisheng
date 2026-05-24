import { useEffect, useState } from "react";
import {
    getShougangFilePublishSimilarCandidatesApi,
    getShougangFilePublishTargetSpacesApi,
    searchShougangFilePublishDocumentsApi,
    submitShougangFilePublishApprovalApi,
    type ShougangFilePublishTargetSpace,
} from "~/api/approval";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";

type FilePublishDialogProps = {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    file: KnowledgeFile | null;
    onOpenChange: (open: boolean) => void;
};

export function FilePublishDialog({
    open,
    activeSpace,
    file,
    onOpenChange,
}: FilePublishDialogProps) {
    const { showToast } = useToastContext();
    const [targetSpaces, setTargetSpaces] = useState<ShougangFilePublishTargetSpace[]>([]);
    const [targetSpaceId, setTargetSpaceId] = useState("");
    const [reason, setReason] = useState("");
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [candidates, setCandidates] = useState<any[]>([]);
    const [searchKeyword, setSearchKeyword] = useState("");
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [targetDocumentId, setTargetDocumentId] = useState<number | null>(null);

    useEffect(() => {
        if (!open) {
            setTargetSpaces([]);
            setTargetSpaceId("");
            setReason("");
            setCandidates([]);
            setSearchKeyword("");
            setSearchResults([]);
            setTargetDocumentId(null);
            return;
        }

        let cancelled = false;
        setLoading(true);
        getShougangFilePublishTargetSpacesApi()
            .then((res) => {
                if (cancelled) return;
                setTargetSpaces(res.data || []);
                const first = res.data?.[0]?.id;
                setTargetSpaceId(first !== undefined ? String(first) : "");
            })
            .catch(() => {
                if (!cancelled) {
                    showToast({ message: "加载发布目标失败", severity: NotificationSeverity.ERROR });
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [open, showToast]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId) {
            setCandidates([]);
            return;
        }

        let cancelled = false;
        getShougangFilePublishSimilarCandidatesApi(file.id, targetSpaceId)
            .then((res) => {
                if (!cancelled) setCandidates(res.data || []);
            })
            .catch(() => {
                if (!cancelled) setCandidates([]);
            });

        return () => {
            cancelled = true;
        };
    }, [file?.id, open, targetSpaceId]);

    const handleSearchDocuments = async () => {
        if (!file || !targetSpaceId) return;
        try {
            const res = await searchShougangFilePublishDocumentsApi(file.id, targetSpaceId, searchKeyword);
            setSearchResults(res.data || []);
        } catch {
            showToast({ message: "搜索目标文档失败", severity: NotificationSeverity.ERROR });
        }
    };

    const handleSubmit = async () => {
        if (!activeSpace || !file || !targetSpaceId) return;
        setSubmitting(true);
        try {
            await submitShougangFilePublishApprovalApi({
                source_space_id: activeSpace.id,
                source_file_id: file.id,
                target_space_id: targetSpaceId,
                target_document_id: targetDocumentId,
                reason: reason.trim() || undefined,
            });
            showToast({ message: "已提交发布申请", severity: NotificationSeverity.SUCCESS });
            onOpenChange(false);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "提交发布申请失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setSubmitting(false);
        }
    };

    const versionOptions = [
        ...candidates.map((item) => ({
            id: item.target_document_id ?? item.document_id,
            title: item.title,
            source: "推荐",
        })),
        ...searchResults.map((item) => ({
            id: item.document_id ?? item.target_document_id,
            title: item.title,
            source: "搜索",
        })),
    ].filter((item, index, all) => item.id && all.findIndex((one) => one.id === item.id) === index);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="w-[min(640px,calc(100vw-48px))] max-w-none"
                onPointerDownOutside={(event) => event.preventDefault()}
            >
                <DialogHeader>
                    <DialogTitle>发布文件</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-2">
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">源文件</label>
                        <div className="rounded-md border border-[#e5e6eb] bg-[#f7f8fa] px-3 py-2 text-sm text-[#1d2129]">
                            {file?.name || "--"}
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">源知识库</label>
                        <div className="rounded-md border border-[#e5e6eb] bg-[#f7f8fa] px-3 py-2 text-sm text-[#1d2129]">
                            {activeSpace?.name || "--"}
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">发布目标知识库</label>
                        <select
                            className="h-9 w-full rounded-md border border-[#dcdfe6] bg-white px-3 text-sm outline-none focus:border-[#165dff]"
                            value={targetSpaceId}
                            disabled={loading}
                            onChange={(event) => {
                                setTargetSpaceId(event.target.value);
                                setTargetDocumentId(null);
                                setSearchResults([]);
                            }}
                        >
                            <option value="">{loading ? "加载中..." : "请选择目标知识库"}</option>
                            {targetSpaces.map((space) => (
                                <option key={space.id} value={String(space.id)}>
                                    {space.name}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">版本管理</label>
                        <select
                            className="h-9 w-full rounded-md border border-[#dcdfe6] bg-white px-3 text-sm outline-none focus:border-[#165dff]"
                            value={targetDocumentId ?? ""}
                            onChange={(event) => setTargetDocumentId(event.target.value ? Number(event.target.value) : null)}
                        >
                            <option value="">不关联新版本</option>
                            {versionOptions.map((option) => (
                                <option key={option.id} value={option.id}>
                                    {option.source}：{option.title}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="flex gap-2">
                        <input
                            className="h-9 min-w-0 flex-1 rounded-md border border-[#dcdfe6] px-3 text-sm outline-none focus:border-[#165dff]"
                            value={searchKeyword}
                            placeholder="搜索目标空间文档..."
                            onChange={(event) => setSearchKeyword(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") void handleSearchDocuments();
                            }}
                        />
                        <Button variant="outline" type="button" onClick={() => void handleSearchDocuments()}>
                            搜索
                        </Button>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">申请意见</label>
                        <textarea
                            className="min-h-[96px] w-full rounded-md border border-[#dcdfe6] px-3 py-2 text-sm outline-none focus:border-[#165dff]"
                            value={reason}
                            rows={4}
                            placeholder="请输入发布原因..."
                            onChange={(event) => setReason(event.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" className="h-8" onClick={() => onOpenChange(false)}>
                        取消
                    </Button>
                    <Button className="h-8" disabled={!targetSpaceId || submitting} onClick={() => void handleSubmit()}>
                        {submitting ? "提交中..." : "提交申请"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
