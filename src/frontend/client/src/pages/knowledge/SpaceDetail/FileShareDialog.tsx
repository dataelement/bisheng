import { useCallback, useEffect, useState } from "react";
import {
    getShougangFileShareTargetFoldersApi,
    getShougangFileShareTargetSpacesApi,
    listShougangFileShareEntriesApi,
    revokeShougangFileShareApi,
    submitShougangFileShareApprovalApi,
    type ShougangFileShareEntry,
    type ShougangFileShareTargetSpace,
} from "~/api/approval";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import {
    Button,
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui";
import { FilePublishTargetTree } from "./FilePublishTargetTree";

interface FileShareDialogProps {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    file: KnowledgeFile | null;
    onOpenChange: (open: boolean) => void;
}

export function FileShareDialog({
    open,
    activeSpace,
    file,
    onOpenChange,
}: FileShareDialogProps) {
    const { showToast } = useToastContext();
    const [targetSpaces, setTargetSpaces] = useState<ShougangFileShareTargetSpace[]>([]);
    const [targetSpaceId, setTargetSpaceId] = useState("");
    const [targetFolderId, setTargetFolderId] = useState<string | null>(null);
    const [reason, setReason] = useState("");
    const [allowDownload, setAllowDownload] = useState(false);
    const [entries, setEntries] = useState<ShougangFileShareEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [revokingId, setRevokingId] = useState<number | null>(null);

    useEffect(() => {
        if (!open || !activeSpace || !file) {
            setTargetSpaces([]);
            setTargetSpaceId("");
            setTargetFolderId(null);
            setReason("");
            setAllowDownload(false);
            setEntries([]);
            return;
        }

        let cancelled = false;
        setLoading(true);
        const targetsTask = getShougangFileShareTargetSpacesApi(
            activeSpace.id,
            file.id,
        );
        const entriesTask = file.entryType === "manager"
            ? listShougangFileShareEntriesApi(file.id)
            : Promise.resolve({ data: [], total: 0 });
        Promise.all([targetsTask, entriesTask])
            .then(([targets, currentEntries]) => {
                if (cancelled) return;
                setTargetSpaces(targets.data || []);
                setTargetSpaceId(
                    targets.data?.[0]?.id !== undefined
                        ? String(targets.data[0].id)
                        : "",
                );
                setTargetFolderId(null);
                setEntries(currentEntries.data || []);
            })
            .catch((error) => {
                if (cancelled) return;
                showToast({
                    message: error instanceof Error
                        ? error.message
                        : "加载分享信息失败",
                    severity: NotificationSeverity.ERROR,
                });
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [activeSpace, file, open, showToast]);

    const loadTargetFolders = useCallback(async (
        spaceId: string | number,
        parentId: string | number | null,
    ) => {
        if (!activeSpace || !file) return [];
        const result = await getShougangFileShareTargetFoldersApi(
            activeSpace.id,
            file.id,
            spaceId,
            parentId,
        );
        return result.data || [];
    }, [activeSpace, file]);

    const handleSubmit = async () => {
        const normalizedReason = reason.trim();
        if (!activeSpace || !file || !targetSpaceId || !normalizedReason) return;
        setSubmitting(true);
        try {
            const result = await submitShougangFileShareApprovalApi({
                source_space_id: activeSpace.id,
                source_file_id: file.id,
                target_space_id: targetSpaceId,
                target_folder_id: targetFolderId
                    ? Number(targetFolderId)
                    : null,
                reason: normalizedReason,
                allow_download: allowDownload,
            });
            if (result.decision === "exception") {
                throw new Error("审批流程不可用，请联系管理员");
            }
            showToast({
                message: "已提交分享申请",
                severity: NotificationSeverity.SUCCESS,
            });
            onOpenChange(false);
        } catch (error) {
            showToast({
                message: error instanceof Error
                    ? error.message
                    : "提交分享申请失败",
                severity: NotificationSeverity.ERROR,
            });
        } finally {
            setSubmitting(false);
        }
    };

    const handleRevoke = async (entry: ShougangFileShareEntry) => {
        if (!file) return;
        setRevokingId(entry.entry_id);
        try {
            await revokeShougangFileShareApi({
                source_file_id: file.id,
                share_entry_id: entry.entry_id,
            });
            setEntries((current) => current.filter(
                (item) => item.entry_id !== entry.entry_id,
            ));
            showToast({
                message: "分享已撤回",
                severity: NotificationSeverity.SUCCESS,
            });
        } catch (error) {
            showToast({
                message: error instanceof Error
                    ? error.message
                    : "撤回分享失败",
                severity: NotificationSeverity.ERROR,
            });
        } finally {
            setRevokingId(null);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="!flex max-h-[calc(100dvh-48px)] w-[min(640px,calc(100vw-48px))] max-w-none flex-col overflow-hidden">
                <DialogHeader>
                    <DialogTitle>分享文件</DialogTitle>
                </DialogHeader>

                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-2 pr-1">
                    <div className="rounded-md bg-[#f7f8fa] px-3 py-2 text-sm text-[#4e5969]">
                        {file?.name || "未选择文件"}
                    </div>

                    <div className="space-y-2 text-sm">
                        <span className="text-[#1d2129]">接收部门目标位置</span>
                        <div className="max-h-64 overflow-y-auto rounded border border-[#c9cdd4] bg-white p-2">
                            <FilePublishTargetTree
                                key={`${activeSpace?.id || ""}:${file?.id || ""}`}
                                loading={loading}
                                targetSpaces={targetSpaces}
                                targetSpaceId={targetSpaceId}
                                targetFolderId={targetFolderId}
                                onSelectRoot={(spaceId) => {
                                    setTargetSpaceId(String(spaceId));
                                    setTargetFolderId(null);
                                }}
                                onSelectFolder={(spaceId, folderId) => {
                                    setTargetSpaceId(String(spaceId));
                                    setTargetFolderId(String(folderId));
                                }}
                                loadFolders={loadTargetFolders}
                                emptyText="暂无可分享目标"
                            />
                        </div>
                    </div>

                    <label className="block space-y-2 text-sm">
                        <span className="text-[#1d2129]">分享原因</span>
                        <textarea
                            value={reason}
                            onChange={(event) => setReason(event.target.value)}
                            maxLength={2000}
                            rows={4}
                            placeholder="请输入分享原因"
                            className="w-full resize-none rounded border border-[#c9cdd4] px-3 py-2 outline-none focus:border-[#165dff]"
                        />
                    </label>

                    <label className="flex items-center gap-2 text-sm text-[#4e5969]">
                        <input
                            type="checkbox"
                            checked={allowDownload}
                            onChange={(event) => setAllowDownload(event.target.checked)}
                        />
                        允许接收方下载带水印 PDF
                    </label>

                    {entries.length > 0 && (
                        <div className="space-y-2 border-t pt-4">
                            <div className="text-sm font-medium text-[#1d2129]">
                                已分享的知识库
                            </div>
                            {entries.map((entry) => (
                                <div
                                    key={entry.entry_id}
                                    className="flex items-center justify-between rounded border px-3 py-2 text-sm"
                                >
                                    <div>
                                        <div>{entry.target_space_name || entry.target_space_id}</div>
                                        <div className="text-xs text-[#86909c]">
                                            {entry.allow_download ? "允许水印下载" : "仅查看"}
                                        </div>
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={revokingId === entry.entry_id}
                                        onClick={() => void handleRevoke(entry)}
                                    >
                                        {revokingId === entry.entry_id ? "撤回中" : "撤回"}
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        取消
                    </Button>
                    <Button
                        disabled={
                            loading
                            || submitting
                            || !targetSpaceId
                            || !reason.trim()
                        }
                        onClick={() => void handleSubmit()}
                    >
                        {submitting ? "提交中" : "提交审批"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
