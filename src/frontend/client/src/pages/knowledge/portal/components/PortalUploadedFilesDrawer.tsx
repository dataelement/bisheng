import { useCallback, useEffect, useMemo, useState } from "react";
import { Folder, PencilLine } from "lucide-react";
import {
    FileStatus,
    SpaceLevel,
    listKnowledgeFolders,
    moveUploadedFileFolderApi,
    updateFileEncoding,
    type FileTag,
    type UploadedFileRecord,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import { EditTagsModal } from "../../SpaceDetail/EditTagsModal";
import TagGroup from "../../SpaceDetail/TagGroup";
import type { PortalFileCategoryGroupOption } from "../types";
import { DEFAULT_PORTAL_FILE_CATEGORY_GROUPS } from "../constants";
import { PortalFileCategoryDropdown } from "./PortalFileCategoryDropdown";
import {
    PortalUploadFolderTreeNode, createFolderTreeNode, updateFolderTreeNode, type FolderTreeNode,
} from "./PortalUploadFolderTree";
import { PortalUploadQueueStatus, usePortalUploadQueuePositions } from "./PortalUploadQueueStatus";
import { usePortalUploadedFiles } from "./usePortalUploadedFiles";
import {
    DEFAULT_ENCODING_PREFIX,
    type BusinessDomainOptionItem,
    type EncodingDraft,
    composeFileEncoding,
    filterBusinessDomainOptionsByCodes,
    fileEncodingBusinessDomainLabel,
    normalizeEncodingCode,
    parseFileEncoding,
} from "../uploadMetadata";
import s from "../PortalKnowledgeWorkbench.module.css";

const EMPTY_FIELD_PLACEHOLDER = "--";

function displayText(value?: string | null): string {
    const text = String(value ?? "").trim();
    return text || EMPTY_FIELD_PLACEHOLDER;
}

function spaceLevelLabel(spaceLevel?: SpaceLevel): string {
    switch (spaceLevel) {
        case SpaceLevel.PUBLIC:
            return "公共知识库";
        case SpaceLevel.DEPARTMENT:
            return "部门知识库";
        case SpaceLevel.TEAM:
            return "团队/科室知识库";
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

interface PortalUploadedFilesDrawerProps {
    open: boolean;
    /** Increment after each upload so the drawer reloads even when already open. */
    refreshKey?: number;
    onOpenChange: (open: boolean) => void;
    onRecordsChanged?: () => void | Promise<void>;
    showToast: (toast: { message: string; severity: NotificationSeverity }) => void;
    fileCategoryGroups: PortalFileCategoryGroupOption[];
    businessDomainOptions: BusinessDomainOptionItem[];
    encodingPrefix?: string;
}

export function PortalUploadedFilesDrawer({
    open,
    refreshKey = 0,
    onOpenChange,
    onRecordsChanged,
    showToast,
    fileCategoryGroups = DEFAULT_PORTAL_FILE_CATEGORY_GROUPS,
    businessDomainOptions,
    encodingPrefix = DEFAULT_ENCODING_PREFIX,
}: PortalUploadedFilesDrawerProps) {
    // Mount floating category menus inside the dialog layer (not document.body).
    // Body portals are treated as Radix "outside" clicks and break selection,
    // especially when the upload list has only one short row.
    const [menuPortalContainer, setMenuPortalContainer] = useState<HTMLDivElement | null>(null);
    const {
        records,
        setRecords,
        total,
        page,
        setPage,
        loading,
        totalPages,
        refreshRecords,
    } = usePortalUploadedFiles({ open, refreshKey, showToast });
    const [editingFileId, setEditingFileId] = useState<string | null>(null);
    const [folderTreeNodes, setFolderTreeNodes] = useState<FolderTreeNode[]>([]);
    const [targetFolderId, setTargetFolderId] = useState<string | null>(null);
    const [targetFolderName, setTargetFolderName] = useState("根目录");
    const [foldersLoading, setFoldersLoading] = useState(false);
    const [savingFileId, setSavingFileId] = useState<string | null>(null);
    const [savingEncodingFileId, setSavingEncodingFileId] = useState<string | null>(null);
    const [editingTagsRecord, setEditingTagsRecord] = useState<UploadedFileRecord | null>(null);
    const [encodingDrafts, setEncodingDrafts] = useState<Record<string, EncodingDraft>>({});
    useEffect(() => {
        if (!open) {
            setEditingFileId(null);
            setFolderTreeNodes([]);
            setEditingTagsRecord(null);
            setEncodingDrafts({});
        }
    }, [open]);

    const getQueuePosition = usePortalUploadQueuePositions(open, records);

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
            await refreshRecords();
            await onRecordsChanged?.();
            setEditingFileId(null);
            setFolderTreeNodes([]);
            showToast({ message: "目录已更新", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "目录修改失败", severity: NotificationSeverity.ERROR });
        } finally {
            setSavingFileId(null);
        }
    }, [editingRecord, onRecordsChanged, refreshRecords, showToast, targetFolderId]);

    const handleEncodingPartChange = useCallback(async (
        record: UploadedFileRecord,
        nextDraft: EncodingDraft,
        fileSubcategoryCode?: string | null,
    ) => {
        // Domain is part of the composed encoding; reject edits while parse is in flight.
        if (nextDraft.businessDomainCode !== undefined && record.status === FileStatus.PROCESSING) return;

        const parsed = parseFileEncoding(record.fileEncoding, encodingPrefix);
        const currentDraft = encodingDrafts[record.id] ?? {};
        const fileCategoryCode = normalizeEncodingCode(
            nextDraft.fileCategoryCode ?? currentDraft.fileCategoryCode ?? parsed.fileCategoryCode,
        );
        const businessDomainCode = normalizeEncodingCode(
            nextDraft.businessDomainCode
            ?? currentDraft.businessDomainCode
            ?? record.businessDomainCode
            ?? parsed.businessDomainCode,
        );
        const normalizedSubcategoryCode = fileSubcategoryCode === undefined
            ? currentDraft.fileSubcategoryCode
            : normalizeEncodingCode(fileSubcategoryCode);
        setEncodingDrafts((prev) => ({
            ...prev,
            [record.id]: {
                fileCategoryCode,
                fileSubcategoryCode: normalizedSubcategoryCode,
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
        const subcategoryChanged = normalizedSubcategoryCode !== undefined &&
            normalizedSubcategoryCode !== normalizeEncodingCode(record.fileSubcategoryCode);
        if (newEncoding === record.fileEncoding?.trim() && !subcategoryChanged) return;

        setEditingFileId(null);
        setFolderTreeNodes([]);
        setEditingTagsRecord(null);
        setSavingEncodingFileId(record.id);
        try {
            if (normalizedSubcategoryCode !== undefined) {
                await updateFileEncoding(record.spaceId, record.id, newEncoding, normalizedSubcategoryCode);
            } else {
                await updateFileEncoding(record.spaceId, record.id, newEncoding);
            }
            // Patch the edited row in place instead of refetching the whole list, which
            // would flicker the whole dialog. The new values are already known locally.
            // Keep businessDomainCode aligned with encoding so the domain column does not
            // fall back to the pre-edit upload-time selection after drafts clear.
            setRecords((prev) => prev.map((item) => (
                item.id === record.id
                    ? {
                        ...item,
                        fileEncoding: newEncoding,
                        businessDomainCode: businessDomainCode || item.businessDomainCode,
                        fileSubcategoryCode: normalizedSubcategoryCode !== undefined
                            ? normalizedSubcategoryCode
                            : item.fileSubcategoryCode,
                    }
                    : item
            )));
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
    }, [encodingDrafts, encodingPrefix, onRecordsChanged, showToast]);

    const handleStartTagsEdit = useCallback((record: UploadedFileRecord) => {
        setEditingFileId(null);
        setFolderTreeNodes([]);
        setEditingTagsRecord(record);
    }, []);

    const handleTagsSaved = useCallback(async () => {
        await refreshRecords();
        await onRecordsChanged?.();
        setEditingTagsRecord(null);
    }, [onRecordsChanged, refreshRecords]);

    return (
        <>
        <Dialog open={uploadRecordsDialogOpen} onOpenChange={onOpenChange}>
            <DialogContent className={s.uploadRecordsDialog} onPointerDownOutside={(event) => event.preventDefault()}>
                <div
                    ref={setMenuPortalContainer}
                    data-testid="portal-uploaded-files-drawer"
                    data-upload-records-menu-layer="true"
                    className={s.uploadRecordsInner}
                >
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
                            <button type="button" className={s.secondaryButton} onClick={() => void refreshRecords()}>
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
                            const folderPathName = record.folderPathName?.trim() || "根目录";
                            const encodingText = displayText(record.fileEncoding);
                            const parsedEncoding = parseFileEncoding(record.fileEncoding, encodingPrefix);
                            const draft = encodingDrafts[record.id] ?? {};
                            const selectedFileCategoryCode = normalizeEncodingCode(draft.fileCategoryCode ?? parsedEncoding.fileCategoryCode);
                            const selectedBusinessDomainCode = normalizeEncodingCode(
                                draft.businessDomainCode
                                ?? record.businessDomainCode
                                ?? parsedEncoding.businessDomainCode,
                            );
                            const selectedBusinessDomainText = selectedBusinessDomainCode || EMPTY_FIELD_PLACEHOLDER;
                            // Encoding is rewritten during parse; keep domain read-only until it finishes.
                            const isBusinessDomainLocked = record.status === FileStatus.PROCESSING;
                            const recordBusinessDomainOptions = filterBusinessDomainOptionsByCodes(
                                businessDomainOptions,
                                record.businessDomainCodes,
                            );
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
                                    <PortalUploadQueueStatus
                                        status={record.status}
                                        position={getQueuePosition(record)}
                                    />
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
                                    <span className={s.uploadRecordCategoryCell}>
                                        <PortalFileCategoryDropdown
                                            variant="fileTable"
                                            menuPortalContainer={menuPortalContainer}
                                            groups={fileCategoryGroups}
                                            value={draft.fileSubcategoryCode ?? record.fileSubcategoryCode}
                                            fallbackParentCode={selectedFileCategoryCode}
                                            disabled={savingEncodingFileId === record.id}
                                            ariaLabel={`修改${recordName}文件分类`}
                                            onChange={(option) => {
                                                if (!option) return;
                                                void handleEncodingPartChange(
                                                    record,
                                                    { fileCategoryCode: option.parentCode },
                                                    option.code,
                                                );
                                            }}
                                        />
                                    </span>
                                    <span
                                        // Wrap disabled select so hover tooltip still works (native title on :disabled is unreliable).
                                        className={isBusinessDomainLocked ? s.uploadRecordSelectLocked : undefined}
                                        title={isBusinessDomainLocked ? "文档解析中无法更改" : undefined}
                                    >
                                        <select
                                            className={s.uploadRecordSelect}
                                            aria-label={`修改${recordName}业务域类型 当前业务域：${selectedBusinessDomainText}`}
                                            value={selectedBusinessDomainCode}
                                            disabled={savingEncodingFileId === record.id || isBusinessDomainLocked}
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
                                        <PortalUploadFolderTreeNode
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
                initialTags={editingTagsRecord.tags ?? []}
            />
        ) : null}
        </>
    );
}
