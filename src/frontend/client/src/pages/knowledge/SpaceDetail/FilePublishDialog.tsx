import { useCallback, useEffect, useState, type UIEvent } from "react";
import {
    getShougangFilePublishSimilarCandidatesApi,
    getShougangFilePublishTargetSpacesApi,
    searchShougangFilePublishDocumentsApi,
    submitShougangFilePublishApprovalApi,
    type ShougangFilePublishDocumentEntry,
    type ShougangFilePublishTargetSpace,
} from "~/api/approval";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useDebounce } from "~/hooks/Input";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import { FilePublishTargetTree } from "./FilePublishTargetTree";

type VersionTarget = {
    type: "document" | "file";
    id: number;
};

type VersionOption = VersionTarget & {
    key: string;
    title: string;
    source: "推荐" | "搜索";
    docCode?: string | null;
    versionNo?: number | null;
    uploaderName?: string | null;
    uploadTime?: string | null;
};

type FilePublishDialogProps = {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    file: KnowledgeFile | null;
    onOpenChange: (open: boolean) => void;
    versionManagementEnabled?: boolean;
};

export function FilePublishDialog({
    open,
    activeSpace,
    file,
    onOpenChange,
    versionManagementEnabled = true,
}: FilePublishDialogProps) {
    const { showToast } = useToastContext();
    const [targetSpaces, setTargetSpaces] = useState<ShougangFilePublishTargetSpace[]>([]);
    const [targetSpaceId, setTargetSpaceId] = useState("");
    const [targetFolderId, setTargetFolderId] = useState<string | null>(null);
    const [reason, setReason] = useState("");
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [candidates, setCandidates] = useState<any[]>([]);
    const [candidatesLoading, setCandidatesLoading] = useState(false);
    const [candidateError, setCandidateError] = useState(false);
    const [searchKeyword, setSearchKeyword] = useState("");
    const [searchResults, setSearchResults] = useState<ShougangFilePublishDocumentEntry[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchHasMore, setSearchHasMore] = useState(false);
    const [nextSearchCursor, setNextSearchCursor] = useState<number | null>(null);
    const [versionTarget, setVersionTarget] = useState<VersionTarget | null>(null);
    const debouncedSearchKeyword = useDebounce(searchKeyword, 300);

    useEffect(() => {
        if (!open) {
            setTargetSpaces([]);
            setTargetSpaceId("");
            setTargetFolderId(null);
            setReason("");
            setCandidates([]);
            setCandidatesLoading(false);
            setCandidateError(false);
            setSearchKeyword("");
            setSearchResults([]);
            setSearchLoading(false);
            setSearchHasMore(false);
            setNextSearchCursor(null);
            setVersionTarget(null);
            return;
        }

        if (!activeSpace?.id) {
            setTargetSpaces([]);
            setTargetSpaceId("");
            setTargetFolderId(null);
            return;
        }

        let cancelled = false;
        setLoading(true);
        getShougangFilePublishTargetSpacesApi(activeSpace.id)
            .then((res) => {
                if (cancelled) return;
                setTargetSpaces(res.data || []);
                const first = res.data?.[0]?.id;
                setTargetSpaceId(first !== undefined ? String(first) : "");
                setTargetFolderId(null);
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
    }, [activeSpace?.id, open, showToast]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId || !versionManagementEnabled) {
            setCandidates([]);
            setCandidatesLoading(false);
            setCandidateError(false);
            return;
        }

        let cancelled = false;
        setCandidates([]);
        setCandidatesLoading(true);
        setCandidateError(false);
        getShougangFilePublishSimilarCandidatesApi(file.id, targetSpaceId)
            .then((res) => {
                if (!cancelled) setCandidates(res.data || []);
            })
            .catch(() => {
                if (!cancelled) {
                    setCandidates([]);
                    setCandidateError(true);
                }
            })
            .finally(() => {
                if (!cancelled) setCandidatesLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [file?.id, open, targetSpaceId, versionManagementEnabled]);

    useEffect(() => {
        if (versionManagementEnabled) return;
        setVersionTarget(null);
        setCandidates([]);
        setSearchResults([]);
        setSearchLoading(false);
        setSearchHasMore(false);
        setNextSearchCursor(null);
        setCandidatesLoading(false);
        setCandidateError(false);
    }, [versionManagementEnabled]);

    const loadSearchPage = useCallback(async (cursor: number, append: boolean) => {
        if (!file || !targetSpaceId || !versionManagementEnabled) return;
        setSearchLoading(true);
        try {
            const res = await searchShougangFilePublishDocumentsApi(
                file.id,
                targetSpaceId,
                debouncedSearchKeyword,
                cursor,
            );
            setSearchResults((previous) => append ? [...previous, ...(res.data || [])] : (res.data || []));
            setSearchHasMore(res.has_more);
            setNextSearchCursor(res.next_cursor ?? null);
        } catch {
            showToast({ message: "搜索目标文档失败", severity: NotificationSeverity.ERROR });
        } finally {
            setSearchLoading(false);
        }
    }, [debouncedSearchKeyword, file, showToast, targetSpaceId, versionManagementEnabled]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId || !versionManagementEnabled || !debouncedSearchKeyword.trim()) {
            setSearchResults([]);
            setSearchHasMore(false);
            setNextSearchCursor(null);
            return;
        }
        void loadSearchPage(0, false);
    }, [debouncedSearchKeyword, file, loadSearchPage, open, targetSpaceId, versionManagementEnabled]);

    const handleSearchResultsScroll = (event: UIEvent<HTMLDivElement>) => {
        const element = event.currentTarget;
        const reachedBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 8;
        if (reachedBottom && searchHasMore && nextSearchCursor !== null && !searchLoading) {
            void loadSearchPage(nextSearchCursor, true);
        }
    };

    const clearTargetVersionState = () => {
        setVersionTarget(null);
        setCandidates([]);
        setCandidateError(false);
        setSearchResults([]);
        setSearchHasMore(false);
        setNextSearchCursor(null);
    };

    const handleSelectTargetRoot = (spaceId: string | number) => {
        setTargetSpaceId(String(spaceId));
        setTargetFolderId(null);
        clearTargetVersionState();
    };

    const handleSelectTargetFolder = (spaceId: string | number, folderId: string | number) => {
        setTargetSpaceId(String(spaceId));
        setTargetFolderId(String(folderId));
        clearTargetVersionState();
    };

    const handleSubmit = async () => {
        if (!activeSpace || !file || !targetSpaceId) return;
        setSubmitting(true);
        try {
            const result = await submitShougangFilePublishApprovalApi({
                source_space_id: activeSpace.id,
                source_file_id: file.id,
                target_space_id: targetSpaceId,
                target_folder_id: targetFolderId ? Number(targetFolderId) : null,
                target_document_id: versionTarget?.type === "document" ? versionTarget.id : null,
                target_file_id: versionTarget?.type === "file" ? versionTarget.id : null,
                reason: reason.trim() || undefined,
            });
            if (result?.decision === "exception") {
                showToast({
                    message: result.exception_type === "route_missing"
                        ? "审批配置未匹配，请联系管理员处理后重试"
                        : "审批提交异常，请联系管理员处理后重试",
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }
            showToast({ message: "已提交发布申请", severity: NotificationSeverity.SUCCESS });
            onOpenChange(false);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "提交发布申请失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setSubmitting(false);
        }
    };

    const versionOptions: VersionOption[] = versionManagementEnabled ? [
        ...candidates.map((item) => ({
            key: `document:${item.target_document_id ?? item.document_id}`,
            type: "document" as const,
            id: item.target_document_id ?? item.document_id,
            title: item.title,
            source: "推荐" as const,
            docCode: item.doc_code,
            versionNo: item.current_primary_version_no,
            uploaderName: item.primary_uploader_name,
            uploadTime: item.primary_upload_time,
        })),
        ...searchResults.map((item) => ({
            key: item.target_file_id
                ? `file:${item.target_file_id}`
                : `document:${item.document_id ?? item.target_document_id}`,
            type: item.target_file_id ? "file" as const : "document" as const,
            id: item.target_file_id ?? item.document_id ?? item.target_document_id,
            title: item.title,
            source: "搜索" as const,
            docCode: item.doc_code,
            versionNo: item.current_primary_version_no,
            uploaderName: item.primary_uploader_name,
            uploadTime: item.primary_upload_time,
        })),
    ].filter((item, index, all) => item.id && all.findIndex((one) => one.key === item.key) === index) : [];
    const selectedVersionOption = versionTarget
        ? versionOptions.find((option) => option.type === versionTarget.type && option.id === versionTarget.id)
        : null;

    const selectVersionOption = (option: VersionOption) => {
        setVersionTarget({ type: option.type, id: option.id });
    };

    const versionEmptyText = candidatesLoading
        ? "推荐加载中..."
        : candidateError
            ? "推荐加载失败"
            : "不关联新版本";

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                data-testid="file-publish-dialog"
                className="!flex max-h-[calc(100dvh-48px)] w-[min(640px,calc(100vw-48px))] max-w-none flex-col overflow-hidden"
                onPointerDownOutside={(event) => event.preventDefault()}
            >
                <DialogHeader>
                    <DialogTitle>发布文件</DialogTitle>
                </DialogHeader>
                <div data-testid="file-publish-dialog-body" className="min-h-0 flex-1 space-y-4 overflow-y-auto py-2 pr-1">
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
                        <label className="text-sm font-medium text-[#1d2129]">发布目标位置</label>
                        <div className="max-h-64 overflow-y-auto rounded-md border border-[#dcdfe6] bg-white p-2">
                            <FilePublishTargetTree
                                loading={loading}
                                targetSpaces={targetSpaces}
                                targetSpaceId={targetSpaceId}
                                targetFolderId={targetFolderId}
                                onSelectRoot={handleSelectTargetRoot}
                                onSelectFolder={handleSelectTargetFolder}
                            />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]" htmlFor="file-publish-version-document">版本管理</label>
                        <select
                            id="file-publish-version-document"
                            className="h-9 w-full rounded-md border border-[#dcdfe6] bg-white px-3 text-sm outline-none focus:border-[#165dff]"
                            value={versionTarget ? `${versionTarget.type}:${versionTarget.id}` : ""}
                            disabled={!versionManagementEnabled || candidatesLoading}
                            onChange={(event) => {
                                const value = event.target.value;
                                if (!value) {
                                    setVersionTarget(null);
                                    return;
                                }
                                const [type, id] = value.split(":");
                                if ((type === "document" || type === "file") && id) {
                                    setVersionTarget({ type, id: Number(id) });
                                }
                            }}
                        >
                            <option value="">{versionEmptyText}</option>
                            {versionOptions.map((option) => (
                                <option key={option.key} value={option.key}>
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
                            disabled={!versionManagementEnabled}
                            onChange={(event) => setSearchKeyword(event.target.value)}
                        />
                        <Button variant="outline" type="button" disabled={!versionManagementEnabled || searchLoading}>
                            {searchLoading ? "搜索中..." : "搜索"}
                        </Button>
                    </div>
                    {debouncedSearchKeyword.trim() ? (
                        <div className="rounded-md border border-[#e5e6eb] bg-white">
                            <div className="max-h-56 overflow-y-auto" onScroll={handleSearchResultsScroll}>
                                {searchResults.map((item) => {
                                    const option: VersionOption = {
                                        key: item.target_file_id ? `file:${item.target_file_id}` : `document:${item.document_id}`,
                                        type: item.target_file_id ? "file" : "document",
                                        id: item.target_file_id ?? item.document_id ?? 0,
                                        title: item.title,
                                        source: "搜索",
                                        docCode: item.doc_code,
                                        versionNo: item.current_primary_version_no,
                                        uploaderName: item.primary_uploader_name,
                                        uploadTime: item.primary_upload_time,
                                    };
                                    const selected = versionTarget?.type === option.type && versionTarget.id === option.id;
                                    return (
                                        <button
                                            key={option.key}
                                            type="button"
                                            aria-label={option.title}
                                            className={`w-full border-b border-[#f2f3f5] px-3 py-2 text-left text-sm last:border-b-0 ${selected ? "bg-[#f2f6ff]" : "hover:bg-[#f7f8fa]"}`}
                                            onClick={() => selectVersionOption(option)}
                                        >
                                            <div className="truncate font-medium text-[#1d2129]">{option.title}</div>
                                            <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-[#86909c]">
                                                {option.docCode && <span>{option.docCode}</span>}
                                                <span>{option.type === "file" ? "待补建版本文档" : `当前版本 V${option.versionNo ?? 1}`}</span>
                                                {option.uploaderName && <span>{option.uploaderName}</span>}
                                            </div>
                                        </button>
                                    );
                                })}
                                {searchLoading && <div className="px-3 py-3 text-center text-sm text-[#86909c]">搜索中...</div>}
                                {!searchLoading && searchResults.length === 0 && <div className="px-3 py-3 text-center text-sm text-[#86909c]">未搜索到可关联文档</div>}
                            </div>
                        </div>
                    ) : null}
                    {selectedVersionOption && (
                        <div className="rounded-md border border-[#e5e6eb] bg-[#f7f8fa] px-3 py-2 text-sm text-[#4e5969]">
                            已选择：{selectedVersionOption.title}
                        </div>
                    )}
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]">申请理由</label>
                        <textarea
                            className="min-h-[96px] w-full rounded-md border border-[#dcdfe6] px-3 py-2 text-sm outline-none focus:border-[#165dff]"
                            value={reason}
                            rows={4}
                            placeholder="请输入发布原因..."
                            onChange={(event) => setReason(event.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter className="shrink-0">
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
