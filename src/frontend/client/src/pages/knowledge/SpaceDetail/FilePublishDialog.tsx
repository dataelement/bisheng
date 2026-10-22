import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import {
    getShougangFilePublishSimilarCandidatesApi,
    getShougangFilePublishLastTargetApi,
    getShougangFilePublishTargetFoldersApi,
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
import { useAuthContext } from "~/hooks";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import { FilePublishTargetTree, type SpaceFolderTreeState } from "./FilePublishTargetTree";
import { restoreFilePublishTarget } from "./filePublishTargetPreference";
import { dispatchKnowledgeSpaceFilesRefresh } from "../knowledgeFileRefresh";

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

function getPublishErrorMessage(error: unknown): string {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) {
        return detail.trim();
    }
    return error instanceof Error && error.message ? error.message : "提交发布申请失败";
}

export function FilePublishDialog({
    open,
    activeSpace,
    file,
    onOpenChange,
    versionManagementEnabled = true,
}: FilePublishDialogProps) {
    const { showToast } = useToastContext();
    const { user } = useAuthContext();
    const [initialFolderTrees, setInitialFolderTrees] = useState<Record<string, SpaceFolderTreeState>>();
    const searchRequestId = useRef(0);
    const dialogSessionId = useRef(0);
    const [targetSpaces, setTargetSpaces] = useState<ShougangFilePublishTargetSpace[]>([]);
    const [targetSpaceKeyword, setTargetSpaceKeyword] = useState("");
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
    const filteredTargetSpaces = useMemo(() => {
        const keyword = targetSpaceKeyword.trim().toLocaleLowerCase();
        if (!keyword) return targetSpaces;
        return targetSpaces.filter((space) => space.name.toLocaleLowerCase().includes(keyword));
    }, [targetSpaceKeyword, targetSpaces]);
    const selectedTargetSpace = targetSpaces.find(
        (space) => String(space.id) === targetSpaceId,
    );
    const canBrowseTargetFiles = Boolean(selectedTargetSpace)
        && selectedTargetSpace?.can_browse_files !== false;
    const canUseVersionManagement = versionManagementEnabled && canBrowseTargetFiles;

    useEffect(() => {
        dialogSessionId.current += 1;
        searchRequestId.current += 1;
        setSubmitting(false);
        setInitialFolderTrees(undefined);
        setTargetSpaceKeyword("");
        if (!open) {
            setLoading(false);
            setTargetSpaces([]);
            setTargetSpaceKeyword("");
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

        if (!activeSpace?.id || !file?.id) {
            setLoading(false);
            setTargetSpaces([]);
            setTargetSpaceId("");
            setTargetFolderId(null);
            return;
        }

        let cancelled = false;
        setLoading(true);
        setTargetSpaces([]);
        setTargetSpaceId("");
        setTargetFolderId(null);
        setReason("");
        setVersionTarget(null);
        setSearchKeyword("");
        setSearchResults([]);
        setSearchLoading(false);
        setSearchHasMore(false);
        setNextSearchCursor(null);
        Promise.all([
            getShougangFilePublishTargetSpacesApi(activeSpace.id, file.id),
            getShougangFilePublishLastTargetApi(activeSpace.id, file.id)
                .catch(() => ({ fallback_reason: "preference_unavailable" })),
        ])
            .then(async ([res, preference]) => {
                if (cancelled) return;
                const visibleTargetSpaces = (res.data || []).filter(
                    (space) => space.can_browse_files !== false,
                );
                const restored = await restoreFilePublishTarget(
                    preference, visibleTargetSpaces,
                    async (spaceId, parentId) => (await getShougangFilePublishTargetFoldersApi(
                        activeSpace.id, file.id, spaceId, parentId, { timeout: 5000 },
                    )).data || [],
                    () => cancelled,
                );
                if (cancelled || !restored) return;
                setTargetSpaces(visibleTargetSpaces);
                setTargetSpaceId(restored.spaceId);
                setTargetFolderId(restored.folderId);
                setInitialFolderTrees(restored.folderTrees);
                if (restored.notice) showToast({ message: restored.notice, severity: NotificationSeverity.WARNING });
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
    }, [activeSpace?.id, file?.id, user?.id, open, showToast]);

    useEffect(() => {
        if (!targetSpaceId || filteredTargetSpaces.some(
            (space) => String(space.id) === targetSpaceId,
        )) {
            return;
        }
        setTargetSpaceId("");
        setTargetFolderId(null);
        setVersionTarget(null);
        setCandidates([]);
        setCandidatesLoading(false);
        setCandidateError(false);
        setSearchResults([]);
        setSearchLoading(false);
        setSearchHasMore(false);
        setNextSearchCursor(null);
    }, [filteredTargetSpaces, targetSpaceId]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId || !canUseVersionManagement) {
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
    }, [canUseVersionManagement, file?.id, user?.id, open, targetSpaceId]);

    useEffect(() => {
        if (canUseVersionManagement) return;
        setVersionTarget(null);
        setCandidates([]);
        setSearchResults([]);
        setSearchLoading(false);
        setSearchHasMore(false);
        setNextSearchCursor(null);
        setCandidatesLoading(false);
        setCandidateError(false);
    }, [canUseVersionManagement]);

    const loadSearchPage = useCallback(async (cursor: number, append: boolean) => {
        if (!file || !targetSpaceId || !canUseVersionManagement) return;
        const requestId = ++searchRequestId.current;
        setSearchLoading(true);
        try {
            const res = await searchShougangFilePublishDocumentsApi(
                file.id,
                targetSpaceId,
                debouncedSearchKeyword,
                cursor,
            );
            if (requestId !== searchRequestId.current) return;
            setSearchResults((previous) => append ? [...previous, ...(res.data || [])] : (res.data || []));
            setSearchHasMore(res.has_more);
            setNextSearchCursor(res.next_cursor ?? null);
        } catch {
            if (requestId === searchRequestId.current) showToast({ message: "搜索目标文档失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (requestId === searchRequestId.current) setSearchLoading(false);
        }
    }, [canUseVersionManagement, debouncedSearchKeyword, file, showToast, targetSpaceId]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId || !canUseVersionManagement || !debouncedSearchKeyword.trim()) {
            searchRequestId.current += 1;
            setSearchResults([]);
            setSearchHasMore(false);
            setNextSearchCursor(null);
            return;
        }
        void loadSearchPage(0, false);
        return () => { searchRequestId.current += 1; };
    }, [canUseVersionManagement, debouncedSearchKeyword, file, loadSearchPage, open, targetSpaceId]);

    const loadTargetFolders = useCallback(async (
        spaceId: string | number,
        parentId: string | number | null,
    ) => {
        if (!activeSpace?.id || !file?.id) return [];
        const response = await getShougangFilePublishTargetFoldersApi(
            activeSpace.id,
            file.id,
            spaceId,
            parentId,
        );
        return response.data || [];
    }, [activeSpace?.id, file?.id]);

    const handleSearchResultsScroll = (event: UIEvent<HTMLDivElement>) => {
        const element = event.currentTarget;
        const reachedBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 8;
        if (reachedBottom && searchHasMore && nextSearchCursor !== null && !searchLoading) {
            void loadSearchPage(nextSearchCursor, true);
        }
    };

    const clearTargetVersionState = () => {
        searchRequestId.current += 1;
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
        if (!activeSpace || !file || !targetSpaceId || loading) return;
        if (file.capabilities && !file.capabilities.canPublish) {
            showToast({
                message: "当前入口不能发布文件",
                severity: NotificationSeverity.ERROR,
            });
            return;
        }
        setSubmitting(true);
        const submissionSession = dialogSessionId.current;
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
                if (submissionSession !== dialogSessionId.current) return;
                showToast({
                    message: result.exception_type === "route_missing"
                        ? "审批配置未匹配，请联系管理员处理后重试"
                        : "审批提交异常，请联系管理员处理后重试",
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }
            dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            if (String(activeSpace.id) !== targetSpaceId) dispatchKnowledgeSpaceFilesRefresh(targetSpaceId);
            if (submissionSession !== dialogSessionId.current) return;
            showToast({
                message: result?.target_preference_saved === false ? "发布申请已提交，但上次发布路径保存失败" : "已提交发布申请",
                severity: result?.target_preference_saved === false ? NotificationSeverity.WARNING : NotificationSeverity.SUCCESS,
            });
            onOpenChange(false);
        } catch (error) {
            if (submissionSession !== dialogSessionId.current) return;
            const message = getPublishErrorMessage(error);
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            if (submissionSession === dialogSessionId.current) setSubmitting(false);
        }
    };

    const candidateVersionOptions: VersionOption[] = candidates.flatMap((item) => {
        if (item.can_associate === false) return [];
        const id = item.target_document_id ?? item.document_id;
        if (id == null) return [];
        return [{
            key: `document:${id}`,
            type: "document" as const,
            id,
            title: item.title,
            source: "推荐" as const,
            docCode: item.doc_code,
            versionNo: item.current_primary_version_no,
            uploaderName: item.primary_uploader_name,
            uploadTime: item.primary_upload_time,
        }];
    });
    const searchVersionOptions: VersionOption[] = searchResults.flatMap((item) => {
        const id = item.target_file_id ?? item.document_id ?? item.target_document_id;
        if (id == null) return [];
        return [{
            key: item.target_file_id
                ? `file:${item.target_file_id}`
                : `document:${id}`,
            type: item.target_file_id ? "file" as const : "document" as const,
            id,
            title: item.title,
            source: "搜索" as const,
            docCode: item.doc_code,
            versionNo: item.current_primary_version_no,
            uploaderName: item.primary_uploader_name,
            uploadTime: item.primary_upload_time,
        }];
    });
    const versionOptions: VersionOption[] = versionManagementEnabled
        ? [...candidateVersionOptions, ...searchVersionOptions].filter(
            (item, index, all) => all.findIndex((one) => one.key === item.key) === index,
        )
        : [];
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
                        <input
                            aria-label="搜索候选知识库"
                            className="h-9 w-full rounded-md border border-[#dcdfe6] px-3 text-sm outline-none focus:border-[#165dff]"
                            value={targetSpaceKeyword}
                            placeholder="搜索候选知识库"
                            onChange={(event) => setTargetSpaceKeyword(event.target.value)}
                        />
                        <div className="max-h-64 overflow-y-auto rounded-md border border-[#dcdfe6] bg-white p-2">
                            <FilePublishTargetTree
                                key={`${activeSpace?.id}:${file?.id}:${user?.id}:${open}`}
                                initialFolderTrees={initialFolderTrees}
                                loading={loading}
                                targetSpaces={filteredTargetSpaces}
                                targetSpaceId={targetSpaceId}
                                targetFolderId={targetFolderId}
                                onSelectRoot={handleSelectTargetRoot}
                                onSelectFolder={handleSelectTargetFolder}
                                loadFolders={loadTargetFolders}
                            />
                        </div>
                    </div>
                    {candidates.some((item) => item.can_associate === false) && (
                        <div className="space-y-1.5 rounded-md border border-[#ffcf8b] bg-[#fff7e8] p-3 text-sm" role="status">
                            <p className="font-medium">目标库已有相似文档（仅供参考）</p>
                            {candidates.filter((item) => item.can_associate === false).map((item) => (
                                <p key={item.primary_knowledge_file_id ?? item.target_document_id}>
                                    {item.title} · 相似度 {((item.similarity * 0.8 + (item.refined_similarity ?? item.similarity) * 0.2) * 100).toFixed(0)}%
                                </p>
                            ))}
                        </div>
                    )}
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[#1d2129]" htmlFor="file-publish-version-document">版本管理</label>
                        <select
                            id="file-publish-version-document"
                            className="h-9 w-full rounded-md border border-[#dcdfe6] bg-white px-3 text-sm outline-none focus:border-[#165dff]"
                            value={versionTarget ? `${versionTarget.type}:${versionTarget.id}` : ""}
                            disabled={!canUseVersionManagement || candidatesLoading}
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
                            disabled={!canUseVersionManagement}
                            onChange={(event) => setSearchKeyword(event.target.value)}
                        />
                        <Button variant="outline" type="button" disabled={!canUseVersionManagement || searchLoading}>
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
                    <Button className="h-8" disabled={!targetSpaceId || loading || submitting} onClick={() => void handleSubmit()}>
                        {submitting ? "提交中..." : "提交申请"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
