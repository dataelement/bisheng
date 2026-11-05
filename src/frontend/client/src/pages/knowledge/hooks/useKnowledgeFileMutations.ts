import { useCallback, useRef } from "react";

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

import { isDeleteRequestUncertain, type FolderDeletionController } from "./useFolderDeletion";

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

interface UseKnowledgeFileMutationsOptions {
    currentFolderId?: string;
    folderDeletion: FolderDeletionController;
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
    currentFolderId,
    folderDeletion,
    files,
    setFiles,
    setTotal,
    loadFiles,
    localize,
    showToast,
    refreshQuota,
}: UseKnowledgeFileMutationsOptions) {
    const scope = `${activeSpace?.id}:${currentFolderId ?? ""}`;
    const scopeRef = useRef(scope);
    scopeRef.current = scope;
    const handleRenameExisting = useCallback(async (fileId: string, newName: string) => {
        if (!activeSpace) return;
        const target = files.find((file) => file.id === fileId);
        if (!target || await folderDeletion.guardItems(activeSpace.id, [target])) return;
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
            if (scopeRef.current !== scope) return;
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
    }, [activeSpace, files, folderDeletion, localize, scope, setFiles, showToast]);

    const handleDeleteFile = useCallback(async (fileId: string) => {
        if (!activeSpace) return;
        if (!fileId) { await loadFiles(1); folderDeletion.reconcile(activeSpace.id); return; }
        const target = files.find(file => file.id === fileId);
        if (!target || await folderDeletion.guardItems(activeSpace.id, [target])) return;
        const folder = target.type === FileType.FOLDER;
        if (!folderDeletion.begin(activeSpace.id, [target], currentFolderId)) return;
        const attempts = folderDeletion.captureAttempts(activeSpace.id, [fileId]);
        try {
            const result = folder
                ? await deleteFolderApi(activeSpace.id, fileId)
                : await deleteFileApi(activeSpace.id, fileId);
            if (!folderDeletion.isCurrentIdentity(attempts.identity)) return;
            folderDeletion.finish(activeSpace.id, [fileId], attempts);
            if (result.decision === "pending") {
                dispatchFileChangeApprovalRefresh(activeSpace.id);
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                return;
            }
            if (result.decision === "invalid") {
                if (folder) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                showToast({ message: folder ? localize("com_knowledge.folder_delete_failed") : result.errorMessage || localize("com_knowledge.delete_failed"), severity: NotificationSeverity.ERROR });
                return;
            }
            if (scopeRef.current === scope) {
                setFiles(previous => applyDeleteDecision(previous, fileId, result));
                setTotal(previous => Math.max(0, previous - 1));
            }
            if (folder) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            refreshQuota();
            showToast({ message: localize("com_knowledge.deleted"), severity: NotificationSeverity.SUCCESS });
        } catch (error) {
            if (!folderDeletion.isCurrentIdentity(attempts.identity)) return;
            const failure = error as { status_code?: number; operation_id?: string; response?: { data?: { data?: { operation_id?: string } } } };
            const existingOperation = failure.operation_id ?? failure.response?.data?.data?.operation_id;
            if (folder && failure.status_code === 18077) {
                folderDeletion.uncertain(activeSpace.id, [fileId], attempts, new Map([[fileId, existingOperation]]));
                folderDeletion.reconcile(activeSpace.id);
                folderDeletion.notify();
                return;
            }
            const uncertain = folder && isDeleteRequestUncertain(error);
            if (uncertain) folderDeletion.uncertain(activeSpace.id, [fileId], attempts, new Map([[fileId, existingOperation]]));
            else folderDeletion.finish(activeSpace.id, [fileId], attempts);
            if (folder) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            showToast({ message: localize(uncertain ? "com_knowledge.folder_delete_request_error" : folder ? "com_knowledge.folder_delete_failed" : "com_knowledge.delete_failed"), severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, currentFolderId, files, folderDeletion, loadFiles, localize, refreshQuota, scope, setFiles, setTotal, showToast]);

    const handleBatchDelete = useCallback(async (ids: Array<string | number>): Promise<boolean> => {
        if (!activeSpace || ids.length === 0) return false;
        const requestedIds = new Set(ids.map(String));
        const targets = files.filter(file => requestedIds.has(file.id));
        if (await folderDeletion.guardItems(activeSpace.id, targets)) return false;
        if (!folderDeletion.begin(activeSpace.id, targets, currentFolderId)) return false;
        const folderIds = targets.filter(file => file.type === FileType.FOLDER).map(file => file.id);
        const attempts = folderDeletion.captureAttempts(activeSpace.id, folderIds);
        try {
            const result = await batchDeleteApi(activeSpace.id, {
                file_ids: targets.filter(file => file.type !== FileType.FOLDER).map(file => Number(file.id)),
                folder_ids: folderIds.map(Number),
            });
            if (!folderDeletion.isCurrentIdentity(attempts.identity)) return false;
            const unknownItems = result.invalid.filter(item => item.outcomeUnknown);
            const ongoingItems = result.invalid.filter(item => !item.outcomeUnknown && item.type === "folder" && item.errorCode === 18077 && item.operationId);
            const observedItems = [...unknownItems, ...ongoingItems];
            const unknownFolders = new Set(observedItems.filter(item => item.type === "folder").map(item => String(item.id)));
            folderDeletion.finish(activeSpace.id, folderIds.filter(id => !unknownFolders.has(id)), attempts);
            folderDeletion.uncertain(activeSpace.id, [...unknownFolders], attempts, new Map(observedItems.map(item => [String(item.id), item.operationId])));
            const definiteResult = { ...result, invalid: result.invalid.filter(item => !observedItems.includes(item)) };
            if (scopeRef.current === scope) {
                setFiles(previous => applyBatchDeleteDecision(previous, result));
                if (result.completed.length) setTotal(previous => Math.max(0, previous - result.completed.length));
            }
            if (result.completed.length) refreshQuota();
            if (folderIds.length || result.pending.length) dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            if (result.pending.length) dispatchFileChangeApprovalRefresh(activeSpace.id);
            if (folderIds.length && definiteResult.invalid.length) {
                showToast({ message: localize("com_knowledge.folder_delete_failed"), severity: NotificationSeverity.ERROR });
            } else showInvalidItems(definiteResult, "com_knowledge.batch_delete_failed", localize, showToast);
            if (unknownItems.length) showToast({ message: localize("com_knowledge.folder_delete_request_error"), severity: NotificationSeverity.ERROR });
            else if (ongoingItems.length) folderDeletion.notify();
            return result.completed.length > 0 || result.pending.length > 0;
        } catch (error) {
            if (!folderDeletion.isCurrentIdentity(attempts.identity)) return false;
            const uncertain = folderIds.length > 0 && isDeleteRequestUncertain(error);
            if (uncertain) folderDeletion.uncertain(activeSpace.id, folderIds, attempts);
            else folderDeletion.finish(activeSpace.id, folderIds, attempts);
            if (folderIds.length) {
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                showToast({ message: localize(uncertain ? "com_knowledge.folder_delete_request_error" : "com_knowledge.folder_delete_failed"), severity: NotificationSeverity.ERROR });
            }
            return false;
        }
    }, [activeSpace, currentFolderId, files, folderDeletion, localize, refreshQuota, scope, setFiles, setTotal, showToast]);

    const handleBatchRename = useCallback(async (
        items: Array<{ id: string; name: string }>,
    ): Promise<boolean> => {
        if (!activeSpace || items.length === 0) return false;
        if (await folderDeletion.guardItems(activeSpace.id, files.filter(file => items.some(item => item.id === file.id)))) return false;
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
            if (scopeRef.current !== scope) return false;
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
    }, [activeSpace, files, folderDeletion, localize, scope, setFiles, showToast]);

    return { handleRenameExisting, handleDeleteFile, handleBatchDelete, handleBatchRename };
}
