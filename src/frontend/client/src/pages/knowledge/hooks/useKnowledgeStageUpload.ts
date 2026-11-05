import { type FolderDeletionGuard } from "./useFolderDeletion";
import { useCallback, useState } from "react";

import { retryDuplicateFilesApi, type KnowledgeFile, type KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    type DuplicateFileEntry,
    type RefreshQuota,
    type StorageQuotaGuard,
} from "./fileUploadUtils";
import { useFileStageUpload } from "./useFileStageUpload";
import { useFolderStageUpload } from "./useFolderStageUpload";

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

interface UseKnowledgeStageUploadOptions {
    guardFolder?: FolderDeletionGuard;
    activeSpace: KnowledgeSpace | null;
    currentFolderId?: string;
    files: KnowledgeFile[];
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<void>;
    localize: Localize;
    showToast: ShowToast;
    isStorageBlocked: StorageQuotaGuard;
    refreshQuota: RefreshQuota;
}

/** Combines the independent single-file and folder stage upload concerns. */
export function useKnowledgeStageUpload(options: UseKnowledgeStageUploadOptions) {
    const { activeSpace, loadFiles, localize, showToast, isStorageBlocked, refreshQuota, guardFolder } = options;
    const [duplicateFiles, setDuplicateFiles] = useState<DuplicateFileEntry[]>([]);
    const fileUpload = useFileStageUpload({ ...options, setDuplicateFiles });
    const folderUpload = useFolderStageUpload({ ...options, setDuplicateFiles });

    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0) return;
        for (const entry of duplicateFiles) {
            if (await guardFolder?.(entry.spaceId || activeSpace.id, entry.parentId)) return;
        }
        // Overwriting registers the staged copy, so exhausted storage blocks it.
        // The prompt stays open so the user can still choose to skip.
        if (isStorageBlocked()) return;
        try {
            const groups = new Map<string, DuplicateFileEntry[]>();
            duplicateFiles.forEach(entry => {
                const spaceId = entry.spaceId || activeSpace.id;
                groups.set(spaceId, [...(groups.get(spaceId) || []), entry]);
            });
            for (const [spaceId, entries] of groups) {
                await retryDuplicateFilesApi(spaceId, entries.map(entry => entry.rawObj));
            }
            refreshQuota();
            await loadFiles(1);
        } catch {
            showToast({
                message: localize("com_knowledge.file_register_failed"),
                severity: NotificationSeverity.ERROR,
            });
        } finally {
            setDuplicateFiles([]);
        }
    }, [activeSpace, guardFolder, duplicateFiles, isStorageBlocked, loadFiles, localize, refreshQuota, showToast]);

    const handleDuplicateSkip = useCallback(() => setDuplicateFiles([]), []);

    return {
        uploadingFiles: fileUpload.uploadingFiles,
        uploadingFolder: folderUpload.uploadingFolder,
        duplicateFiles,
        handleUploadFile: fileUpload.handleUploadFile,
        handleUploadFolder: folderUpload.handleUploadFolder,
        handleDuplicateOverwrite,
        handleDuplicateSkip,
    };
}
