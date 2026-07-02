import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Folder, PencilLine } from "lucide-react";
import {
    FileStatus,
    SpaceLevel,
    listKnowledgeFolders,
    listMyUploadedFilesApi,
    moveUploadedFileFolderApi,
    updateFileEncoding,
    type FileTag,
    type UploadedFileRecord,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import { EditTagsModal } from "../../SpaceDetail/EditTagsModal";
import TagGroup from "../../SpaceDetail/TagGroup";
import { isKnowledgeItemPending } from "../../knowledgeUtils";
import type { PortalFileCategoryOption } from "../types";
import {
    DEFAULT_ENCODING_PREFIX,
    type BusinessDomainOptionItem,
    type EncodingDraft,
    composeFileEncoding,
    filterBusinessDomainOptionsByCodes,
    fileEncodingBusinessDomainLabel,
    fileEncodingCategoryLabel,
    normalizeEncodingCode,
    parseFileEncoding,
} from "../uploadMetadata";
import s from "../PortalKnowledgeWorkbench.module.css";

const PAGE_SIZE = 20;
const EMPTY_FIELD_PLACEHOLDER = "--";

function displayText(value?: string | null): string {
    const text = String(value ?? "").trim();
    return text || EMPTY_FIELD_PLACEHOLDER;
}

function uploadStatusLabel(status?: FileStatus): string {
    switch (status) {
        case FileStatus.PROCESSING:
            return "解析中";
        case FileStatus.SUCCESS:
            return "解析完成";
        case FileStatus.WAITING:
            return "等待解析";
        case FileStatus.FAILED:
            return "解析失败";
        case FileStatus.REBUILDING:
            return "重新解析";
        case FileStatus.TIMEOUT:
            return "解析超时";
        case FileStatus.VIOLATION:
            return "内容违规";
        default:
            return EMPTY_FIELD_PLACEHOLDER;
    }
}

function uploadStatusClassName(status?: FileStatus): string {
    switch (status) {
        case FileStatus.SUCCESS:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusSuccess}`;
        case FileStatus.FAILED:
        case FileStatus.TIMEOUT:
        case FileStatus.VIOLATION:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusDanger}`;
        case FileStatus.UPLOADING:
        case FileStatus.PROCESSING:
        case FileStatus.WAITING:
        case FileStatus.REBUILDING:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusInfo}`;
        default:
            return s.uploadRecordStatusBadge;
    }
}

function spaceLevelLabel(spaceLevel?: SpaceLevel): string {
    switch (spaceLevel) {
        case SpaceLevel.PUBLIC:
            return "公共知识库";
        case SpaceLevel.DEPARTMENT:
            return "部门知识库";
        case SpaceLevel.TEAM:
            return "团队知识库";
        case SpaceLevel.PERSONAL:
            return "个人知识库";
        default:
            return "知识库";
    }
}

function uploadRecordSpaceName(record: UploadedFileRecord): string {
    const spaceName = displayText(record.spaceName);
    if (spaceName === EMPTY_FIELD_PLACEHOLDER) return EMPTY_FIELD_PLACEHOLDER;
    return `${spaceLevelLabel(record.spaceLevel)}:${spaceName}`;
}

function uploadRecordTagText(record: UploadedFileRecord): string {
    const tagNames = uploadRecordTags(record)
        .map((tag) => String(tag.name ?? "").trim());
    return tagNames.length ? tagNames.join("、") : EMPTY_FIELD_PLACEHOLDER;
}

function uploadRecordTags(record: UploadedFileRecord): FileTag[] {
    return (record.tags ?? []).filter((tag) => String(tag.name ?? "").trim());
}

type FolderTreeNode = {
    id: string;
    name: string;
    children: FolderTreeNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
};

function createFolderTreeNode(item: any): FolderTreeNode {
    return {
        id: String(item.id),
        name: String(item.file_name ?? item.name ?? ""),
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
    };
}

function updateFolderTreeNode(
    nodes: FolderTreeNode[],
    nodeId: string,
    updater: (node: FolderTreeNode) => FolderTreeNode,
): FolderTreeNode[] {
    return nodes.map((node) => {
        if (node.id === nodeId) return updater(node);
        if (!node.children.length) return node;
        return { ...node, children: updateFolderTreeNode(node.children, nodeId, updater) };
    });
}

function FolderPickerNode({
    node,
    depth,
    recordName,
    targetFolderId,
    onToggle,
    onSelect,
}: {
    node: FolderTreeNode;
    depth: number;
    recordName: string;
    targetFolderId: string | null;
    onToggle: (node: FolderTreeNode) => void;
    onSelect: (folderId: string, folderName: string) => void;
}): ReactNode {
    return (
        <div key={node.id}>
            <div className={s.uploadRecordFolderRow} style={{ paddingLeft: `${8 + depth * 16}px` }}>
                <button
                    type="button"
                    className={s.uploadRecordFolderExpandButton}
                    aria-label={`${node.expanded ? "收起" : "展开"}${recordName}目标目录${node.name}`}
                    onClick={() => onToggle(node)}
                >
                    {node.expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                <button
                    type="button"
                    className={`${s.uploadRecordFolderSelectButton} ${targetFolderId === node.id ? s.uploadRecordFolderSelectButtonActive : ""}`}
                    aria-label={`选择${recordName}目标目录${node.name}`}
                    onClick={() => onSelect(node.id, node.name)}
                >
                    <Folder size={14} />
                    <span>{node.name}</span>
                </button>
            </div>
            {node.expanded && node.loading ? (
                <div className={s.uploadRecordFolderLoading} style={{ paddingLeft: `${30 + (depth + 1) * 16}px` }}>
                    加载中...
                </div>
            ) : null}
            {node.expanded ? node.children.map((child) => (
                <FolderPickerNode
                    key={child.id}
                    node={child}
                    depth={depth + 1}
                    recordName={recordName}
                    targetFolderId={targetFolderId}
                    onToggle={onToggle}
                    onSelect={onSelect}
                />
            )) : null}
        </div>
    );
}

interface PortalUploadedFilesDrawerProps {
    open: boolean;
    /** Increment after each upload so the drawer reloads even when already open. */
    refreshKey?: number;
    onOpenChange: (open: boolean) => void;
    onRecordsChanged?: () => void | Promise<void>;
    showToast: (toast: { message: string; severity: NotificationSeverity }) => void;
    fileCategoryOptions: PortalFileCategoryOption[];
    businessDomainOptions: BusinessDomainOptionItem[];
    encodingPrefix?: string;
}

export function PortalUploadedFilesDrawer({
    open,
    refreshKey = 0,
    onOpenChange,
    onRecordsChanged,
    showToast,
    fileCategoryOptions,
    businessDomainOptions,
    encodingPrefix = DEFAULT_ENCODING_PREFIX,
}: PortalUploadedFilesDrawerProps) {
    const [records, setRecords] = useState<UploadedFileRecord[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [editingFileId, setEditingFileId] = useState<string | null>(null);
    const [folderTreeNodes, setFolderTreeNodes] = useState<FolderTreeNode[]>([]);
    const [targetFolderId, setTargetFolderId] = useState<string | null>(null);
    const [targetFolderName, setTargetFolderName] = useState("根目录");
    const [foldersLoading, setFoldersLoading] = useState(false);
    const [savingFileId, setSavingFileId] = useState<string | null>(null);
    const [savingEncodingFileId, setSavingEncodingFileId] = useState<string | null>(null);
    const [editingTagsRecord, setEditingTagsRecord] = useState<UploadedFileRecord | null>(null);
    const [encodingDrafts, setEncodingDrafts] = useState<Record<string, EncodingDraft>>({});
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const loadRecords = useCallback(async (pageToLoad: number) => {
        if (!open) return;
        setLoading(true);
        try {
            const res = await listMyUploadedFilesApi({ page: pageToLoad, pageSize: PAGE_SIZE });
            setRecords(res.data);
            setTotal(res.total);
            setPage(pageToLoad);
        } catch {
            setRecords([]);
            setTotal(0);
            showToast({ message: "上传记录加载失败", severity: NotificationSeverity.ERROR });
        } finally {
            setLoading(false);
        }
    }, [open, showToast]);

    useEffect(() => {
        if (!open) {
            setPage(1);
            setEditingFileId(null);
            setFolderTreeNodes([]);
            setEditingTagsRecord(null);
            setEncodingDrafts({});
            return;
        }
        void loadRecords(page);
    }, [loadRecords, open, page, refreshKey]);

    useEffect(() => {
        if (!open) return;
        const hasPending = records.some((record) => isKnowledgeItemPending(record));
        if (!hasPending) return;

        const timer = setInterval(() => {
            void loadRecords(page);
        }, 5000);

        return () => clearInterval(timer);
    }, [loadRecords, open, page, records]);

    const editingRecord = useMemo(
        () => records.find((record) => record.id === editingFileId) ?? null,
        [editingFileId, records],
    );
    const uploadRecordsDialogOpen = open && !editingTagsRecord;

    const handleStartEdit = useCallback(async (record: UploadedFileRecord) => {
        setEditingTagsRecord(null);
        setEditingFileId(record.id);
        setTargetFolderId(record.parentId ?? null);
        setTargetFolderName(record.folderPathName || "根目录");
        setFoldersLoading(true);
        try {
            const res = await listKnowledgeFolders({
                space_id: record.spaceId,
                parent_id: null,
            });
            setFolderTreeNodes(res.items.map(createFolderTreeNode));
        } catch {
            setFolderTreeNodes([]);
            showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
        } finally {
            setFoldersLoading(false);
        }
    }, [showToast]);

    const handleSelectFolder = useCallback((folderId: string | null, folderName: string) => {
        setTargetFolderId(folderId);
        setTargetFolderName(folderName);
    }, []);

    const handleToggleFolder = useCallback(async (node: FolderTreeNode) => {
        if (!editingRecord) return;
        if (node.expanded) {
            setFolderTreeNodes((prev) => updateFolderTreeNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
            })));
            return;
        }
        if (node.loaded) {
            setFolderTreeNodes((prev) => updateFolderTreeNode(prev, node.id, (item) => ({
                ...item,
                expanded: true,
            })));
            return;
        }
        setFolderTreeNodes((prev) => updateFolderTreeNode(prev, node.id, (item) => ({
            ...item,
            expanded: true,
            loading: true,
        })));
        const parentId = Number(node.id);
        try {
            const res = await listKnowledgeFolders({
                space_id: editingRecord.spaceId,
                parent_id: Number.isFinite(parentId) ? parentId : node.id,
            });
            setFolderTreeNodes((prev) => updateFolderTreeNode(prev, node.id, (item) => ({
                ...item,
                children: res.items.map(createFolderTreeNode),
                expanded: true,
                loaded: true,
                loading: false,
            })));
        } catch {
            setFolderTreeNodes((prev) => updateFolderTreeNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
                loading: false,
            })));
            showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [editingRecord, showToast]);

    const handleSaveFolder = useCallback(async () => {
        if (!editingRecord) return;
        setSavingFileId(editingRecord.id);
        try {
            await moveUploadedFileFolderApi(editingRecord.spaceId, editingRecord.id, targetFolderId);
            await loadRecords(page);
            await onRecordsChanged?.();
            setEditingFileId(null);
            setFolderTreeNodes([]);
            showToast({ message: "目录已更新", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "目录修改失败", severity: NotificationSeverity.ERROR });
        } finally {
            setSavingFileId(null);
        }
    }, [editingRecord, loadRecords, onRecordsChanged, page, showToast, targetFolderId]);

    const handleEncodingPartChange = useCallback(async (
        record: UploadedFileRecord,
        nextDraft: EncodingDraft,
    ) => {
        const parsed = parseFileEncoding(record.fileEncoding, encodingPrefix);
        const currentDraft = encodingDrafts[record.id] ?? {};
        const fileCategoryCode = normalizeEncodingCode(
            nextDraft.fileCategoryCode ?? currentDraft.fileCategoryCode ?? parsed.fileCategoryCode,
        );
        const businessDomainCode = normalizeEncodingCode(
            nextDraft.businessDomainCode ?? currentDraft.businessDomainCode ?? parsed.businessDomainCode,
        );
        setEncodingDrafts((prev) => ({
            ...prev,
            [record.id]: {
                fileCategoryCode,
                businessDomainCode,
            },
        }));
        if (!fileCategoryCode || !businessDomainCode) return;

        const newEncoding = composeFileEncoding(
            record.fileEncoding,
            fileCategoryCode,
            businessDomainCode,
            encodingPrefix,
        );
        if (newEncoding === record.fileEncoding?.trim()) return;

        setEditingFileId(null);
        setFolderTreeNodes([]);
        setEditingTagsRecord(null);
        setSavingEncodingFileId(record.id);
        try {
            await updateFileEncoding(record.spaceId, record.id, newEncoding);
            await loadRecords(page);
            await onRecordsChanged?.();
            setEncodingDrafts((prev) => {
                const { [record.id]: _, ...rest } = prev;
                return rest;
            });
            showToast({ message: "编码已更新", severity: NotificationSeverity.SUCCESS });
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "编码更新失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setSavingEncodingFileId(null);
        }
    }, [encodingDrafts, encodingPrefix, loadRecords, onRecordsChanged, page, showToast]);

    const handleStartTagsEdit = useCallback((record: UploadedFileRecord) => {
        setEditingFileId(null);
        setFolderTreeNodes([]);
        setEditingTagsRecord(record);
    }, []);

    const handleTagsSaved = useCallback(async () => {
        await loadRecords(page);
        await onRecordsChanged?.();
        setEditingTagsRecord(null);
    }, [loadRecords, onRecordsChanged, page]);

    return (
        <>
        <Dialog open={uploadRecordsDialogOpen} onOpenChange={onOpenChange}>
            <DialogContent className={s.uploadRecordsDialog} onPointerDownOutside={(event) => event.preventDefault()}>
                <div data-testid="portal-uploaded-files-drawer" className={s.uploadRecordsInner}>
                    <DialogHeader>
                        <DialogTitle>上传记录</DialogTitle>
                    </DialogHeader>
                    <div className={s.uploadRecordsToolbar}>
                        <span>共 {total} 条</span>
                        <div className={s.uploadRecordsPager}>
                            <button
                                type="button"
                                className={s.secondaryButton}
                                onClick={() => setPage((current) => Math.max(1, current - 1))}
                                disabled={loading || page <= 1}
                            >
                                上一页
                            </button>
                            <span>{page} / {totalPages}</span>
                            <button
                                type="button"
                                className={s.secondaryButton}
                                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                                disabled={loading || page >= totalPages}
                            >
                                下一页
                            </button>
                            <button type="button" className={s.secondaryButton} onClick={() => void loadRecords(page)}>
                                刷新
                            </button>
                        </div>
                    </div>
                    <div className={s.uploadRecordsTable}>
                        <div className={s.uploadRecordsHead}>
                            <span>文件名称</span>
                            <span>知识库</span>
                            <span>状态</span>
                            <span>上传目录</span>
                            <span>文件分类</span>
                            <span>业务域类型</span>
                            <span>标签</span>
                            <span>文件编码</span>
                        </div>
                        {loading ? (
                            <div className={s.uploadRecordsEmpty}>正在加载上传记录...</div>
                        ) : records.length ? records.map((record) => {
                            const recordName = displayText(record.name);
                            const spaceName = uploadRecordSpaceName(record);
                            const statusText = uploadStatusLabel(record.status);
                            const folderPathName = record.folderPathName?.trim() || "根目录";
                            const encodingText = displayText(record.fileEncoding);
                            const parsedEncoding = parseFileEncoding(record.fileEncoding, encodingPrefix);
                            const draft = encodingDrafts[record.id] ?? {};
                            const selectedFileCategoryCode = normalizeEncodingCode(draft.fileCategoryCode ?? parsedEncoding.fileCategoryCode);
                            const selectedBusinessDomainCode = normalizeEncodingCode(draft.businessDomainCode ?? parsedEncoding.businessDomainCode);
                            const selectedFileCategoryText = selectedFileCategoryCode || EMPTY_FIELD_PLACEHOLDER;
                            const selectedBusinessDomainText = selectedBusinessDomainCode || EMPTY_FIELD_PLACEHOLDER;
                            const recordBusinessDomainOptions = filterBusinessDomainOptionsByCodes(
                                businessDomainOptions,
                                record.businessDomainCodes,
                            );
                            const hasCurrentCategoryOption = fileCategoryOptions.some((option) => option.code === selectedFileCategoryCode);
                            const tagText = uploadRecordTagText(record);
                            const recordTags = uploadRecordTags(record);
                            const editTagsButton = (
                                <button
                                    type="button"
                                    className={s.uploadRecordTagEditButton}
                                    title="编辑标签"
                                    aria-label={`修改${recordName}标签 当前标签：${tagText}`}
                                    onClick={() => handleStartTagsEdit(record)}
                                >
                                    <PencilLine size={14} />
                                </button>
                            );
                            return (
                                <div key={record.id} className={s.uploadRecordsRow}>
                                    <span title={recordName}>{recordName}</span>
                                    <span title={spaceName}>{spaceName}</span>
                                    <span className={uploadStatusClassName(record.status)}>{statusText}</span>
                                    <span>
                                        <button
                                            type="button"
                                            className={s.uploadRecordFolderButton}
                                            title={folderPathName}
                                            aria-label={`修改${recordName}上传目录 当前目录：${folderPathName}`}
                                            onClick={() => void handleStartEdit(record)}
                                        >
                                            {folderPathName}
                                        </button>
                                    </span>
                                    <span>
                                        <select
                                            className={s.uploadRecordSelect}
                                            aria-label={`修改${recordName}文件分类 当前分类：${selectedFileCategoryText}`}
                                            value={selectedFileCategoryCode}
                                            disabled={savingEncodingFileId === record.id}
                                            onChange={(event) => void handleEncodingPartChange(record, { fileCategoryCode: event.currentTarget.value })}
                                        >
                                            <option value="">{EMPTY_FIELD_PLACEHOLDER}</option>
                                            {selectedFileCategoryCode && !hasCurrentCategoryOption ? (
                                                <option value={selectedFileCategoryCode}>
                                                    {fileEncodingCategoryLabel(selectedFileCategoryCode, fileCategoryOptions)}
                                                </option>
                                            ) : null}
                                            {fileCategoryOptions.map((option) => (
                                                <option key={option.code} value={option.code}>
                                                    {option.code} / {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    </span>
                                    <span>
                                        <select
                                            className={s.uploadRecordSelect}
                                            aria-label={`修改${recordName}业务域类型 当前业务域：${selectedBusinessDomainText}`}
                                            value={selectedBusinessDomainCode}
                                            disabled={savingEncodingFileId === record.id}
                                            onChange={(event) => void handleEncodingPartChange(record, { businessDomainCode: event.currentTarget.value })}
                                        >
                                            <option value="">{EMPTY_FIELD_PLACEHOLDER}</option>
                                            {selectedBusinessDomainCode && !recordBusinessDomainOptions.some((option) => option.code === selectedBusinessDomainCode) ? (
                                                <option value={selectedBusinessDomainCode}>
                                                    {fileEncodingBusinessDomainLabel(selectedBusinessDomainCode, recordBusinessDomainOptions)}
                                                </option>
                                            ) : null}
                                            {recordBusinessDomainOptions.map((option) => (
                                                <option key={option.code} value={option.code}>
                                                    {option.code} / {option.name}
                                                </option>
                                            ))}
                                        </select>
                                    </span>
                                    <span className={s.uploadRecordTagCell} title={tagText}>
                                        {recordTags.length ? (
                                            <TagGroup tags={recordTags} actionButton={editTagsButton} />
                                        ) : (
                                            <>
                                                <span className={s.uploadRecordTagEmpty}>{EMPTY_FIELD_PLACEHOLDER}</span>
                                                {editTagsButton}
                                            </>
                                        )}
                                    </span>
                                    <span className={s.uploadRecordReadonlyText} title={encodingText}>
                                        {encodingText}
                                    </span>
                                </div>
                            );
                        }) : (
                            <div className={s.uploadRecordsEmpty}>暂无上传记录</div>
                        )}
                    </div>
                    {editingRecord ? (
                        <div className={s.uploadRecordFolderPicker} data-testid="upload-record-folder-picker">
                            <div className={s.uploadRecordFolderPickerHeader}>
                                <strong>选择上传目录</strong>
                                <span>已选择：{targetFolderName}</span>
                            </div>
                            <div className={s.uploadRecordFolderTree}>
                                <div className={s.uploadRecordFolderRow}>
                                    <span className={s.uploadRecordFolderExpandPlaceholder} />
                                    <button
                                        type="button"
                                        className={`${s.uploadRecordFolderSelectButton} ${targetFolderId === null ? s.uploadRecordFolderSelectButtonActive : ""}`}
                                        aria-label={`选择${editingRecord.name}目标目录根目录`}
                                        onClick={() => handleSelectFolder(null, "根目录")}
                                    >
                                        <Folder size={14} />
                                        <span>根目录</span>
                                    </button>
                                </div>
                                {foldersLoading ? (
                                    <div className={s.uploadRecordFolderLoading}>目录加载中...</div>
                                ) : folderTreeNodes.length ? (
                                    folderTreeNodes.map((node) => (
                                        <FolderPickerNode
                                            key={node.id}
                                            node={node}
                                            depth={0}
                                            recordName={editingRecord.name}
                                            targetFolderId={targetFolderId}
                                            onToggle={handleToggleFolder}
                                            onSelect={handleSelectFolder}
                                        />
                                    ))
                                ) : (
                                    <div className={s.uploadRecordFolderEmpty}>暂无子目录</div>
                                )}
                            </div>
                            <button
                                type="button"
                                className={s.secondaryButton}
                                onClick={() => {
                                    setEditingFileId(null);
                                    setFolderTreeNodes([]);
                                }}
                                disabled={savingFileId === editingRecord.id}
                            >
                                取消
                            </button>
                            <button
                                type="button"
                                className={s.primaryButton}
                                onClick={() => void handleSaveFolder()}
                                disabled={savingFileId === editingRecord.id || foldersLoading}
                                aria-label={`保存${editingRecord.name}目录`}
                            >
                                {savingFileId === editingRecord.id ? "保存中..." : "保存"}
                            </button>
                        </div>
                    ) : null}
                    <DialogFooter>
                        <Button variant="outline" className="h-8" onClick={() => onOpenChange(false)}>
                            关闭
                        </Button>
                    </DialogFooter>
                </div>
            </DialogContent>
        </Dialog>
        {editingTagsRecord ? (
            <EditTagsModal
                isOpen={Boolean(editingTagsRecord)}
                onClose={() => setEditingTagsRecord(null)}
                onSaved={handleTagsSaved}
                spaceId={editingTagsRecord.spaceId}
                fileId={editingTagsRecord.id}
                initialTagIds={(editingTagsRecord.tags ?? []).map((tag) => tag.id).filter((id) => id >= 0)}
            />
        ) : null}
        </>
    );
}
