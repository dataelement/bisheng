import { useCallback } from "react";

import {
    FileType,
    batchDeleteApi,
    batchRenameApi,
    deleteFileApi,
    deleteFolderApi,
    renameFileApi,
    renameFolderApi,
    type FileBatchMutationResult,
    type KnowledgeFile,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";

import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";
import { type RefreshQuota } from "./fileUploadUtils";
import {
    applyBatchDeleteDecision,
    applyBatchRenameDecision,
    applyDeleteDecision,
    applyRenameDecision,
    dispatchFileChangeApprovalRefresh,
} from "./fileMutationUtils";

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

interface UseKnowledgeFileMutationsOptions {
    activeSpace: KnowledgeSpace | null;
    files: KnowledgeFile[];
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<void>;
    localize: Localize;
    showToast: ShowToast;
    refreshQuota: RefreshQuota;
}

function showInvalidItems(
    result: FileBatchMutationResult,
    fallbackKey: string,
    localize: Localize,
    showToast: ShowToast,
): void {
    result.invalid.forEach((item) => {
        showToast({
            message: item.errorMessage || localize(fallbackKey),
            severity: NotificationSeverity.ERROR,
        });
    });
}

export function useKnowledgeFileMutations({
    activeSpace,
    files,
    setFiles,
    setTotal,
    loadFiles,
    localize,
    showToast,
    refreshQuota,
}: UseKnowledgeFileMutationsOptions) {
    const handleRenameExisting = useCallback(async (fileId: string, newName: string) => {
        if (!activeSpace) return;
        const target = files.find((file) => file.id === fileId);
        if (!target) return;
        try {
            const result = target.type === FileType.FOLDER
                ? await renameFolderApi(activeSpace.id, fileId, newName)
                : await renameFileApi(activeSpace.id, fileId, newName);
            if (result.decision === "pending") {
                dispatchFileChangeApprovalRefresh(activeSpace.id);
                // Also refresh the file listing so the just-renamed row gets its
                // "待审核" pending-change badge without requiring a manual reload.
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                return;
            }
            if (result.decision === "invalid") {
                showToast({
                    message: result.errorMessage || localize("com_knowledge.rename_failed"),
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }
            setFiles((previous) => applyRenameDecision(previous, fileId, newName, result));
            if (target.type === FileType.FOLDER) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            showToast({
                message: localize("com_knowledge.rename_success"),
                severity: NotificationSeverity.SUCCESS,
            });
        } catch {
            showToast({
                message: localize("com_knowledge.rename_failed"),
                severity: NotificationSeverity.ERROR,
            });
        }
    }, [activeSpace, files, localize, setFiles, showToast]);

    const handleDeleteFile = useCallback(async (fileId: string) => {
        if (!activeSpace) return;
        if (!fileId) {
            await loadFiles(1);
            return;
        }
        const target = files.find((file) => file.id === fileId);
        if (!target) return;
        try {
            const result = target.type === FileType.FOLDER
                ? await deleteFolderApi(activeSpace.id, fileId)
                : await deleteFileApi(activeSpace.id, fileId);
            if (result.decision === "pending") {
                dispatchFileChangeApprovalRefresh(activeSpace.id);
                // Also refresh the file listing so the row gets its pending-
                // change badge without requiring a manual reload.
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                return;
            }
            if (result.decision === "invalid") {
                showToast({
                    message: result.errorMessage || localize("com_knowledge.delete_failed"),
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }
            setFiles((previous) => applyDeleteDecision(previous, fileId, result));
            setTotal((previous) => Math.max(0, previous - 1));
            if (target.type === FileType.FOLDER) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            refreshQuota();
            showToast({
                message: localize("com_knowledge.deleted"),
                severity: NotificationSeverity.SUCCESS,
            });
        } catch {
            showToast({
                message: localize("com_knowledge.delete_failed"),
                severity: NotificationSeverity.ERROR,
            });
        }
    }, [activeSpace, files, loadFiles, localize, refreshQuota, setFiles, setTotal, showToast]);

    const handleBatchDelete = useCallback(async (ids: Array<string | number>): Promise<boolean> => {
        if (!activeSpace || ids.length === 0) return false;
        const requestedIds = new Set(ids.map(String));
        const targets = files.filter((file) => requestedIds.has(file.id));
        try {
            const result = await batchDeleteApi(activeSpace.id, {
                file_ids: targets.filter((file) => file.type !== FileType.FOLDER).map((file) => Number(file.id)),
                folder_ids: targets.filter((file) => file.type === FileType.FOLDER).map((file) => Number(file.id)),
            });
            setFiles((previous) => applyBatchDeleteDecision(previous, result));
            if (result.completed.length > 0) {
                setTotal((previous) => Math.max(0, previous - result.completed.length));
                refreshQuota();
            }
            if (result.completed.some((item) => item.type === "folder")) {
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            }
            if (result.pending.length > 0) {
                dispatchFileChangeApprovalRefresh(activeSpace.id);
                // Refresh the file listing so pending rows get their badge.
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            }
            showInvalidItems(result, "com_knowledge.batch_delete_failed", localize, showToast);
            return result.completed.length > 0 || result.pending.length > 0;
        } catch {
            return false;
        }
    }, [activeSpace, files, localize, refreshQuota, setFiles, setTotal, showToast]);

    const handleBatchRename = useCallback(async (
        items: Array<{ id: string; name: string }>,
    ): Promise<boolean> => {
        if (!activeSpace || items.length === 0) return false;
        const sourceById = new Map(files.map((file) => [file.id, file]));
        const requestedNames = new Map(items.map((item) => [item.id, item.name]));
        try {
            const result = await batchRenameApi(activeSpace.id, {
                items: items.flatMap((item) => {
                    const source = sourceById.get(item.id);
                    return source ? [{
                        id: Number(item.id),
                        type: source.type === FileType.FOLDER ? "folder" as const : "file" as const,
                        name: item.name,
                    }] : [];
                }),
            });
            setFiles((previous) => applyBatchRenameDecision(previous, requestedNames, result));
            if (result.completed.some((item) => item.type === "folder")) {
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            }
            if (result.pending.length > 0) {
                dispatchFileChangeApprovalRefresh(activeSpace.id);
                // Refresh the file listing so pending rows get their badge.
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            }
            showInvalidItems(result, "com_knowledge.rename_failed", localize, showToast);
            return result.completed.length > 0 || result.pending.length > 0;
        } catch {
            return false;
        }
    }, [activeSpace, files, localize, setFiles, showToast]);

    return { handleRenameExisting, handleDeleteFile, handleBatchDelete, handleBatchRename };
}
