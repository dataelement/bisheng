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
    const { activeSpace, loadFiles, localize, showToast, isStorageBlocked, refreshQuota } = options;
    const [duplicateFiles, setDuplicateFiles] = useState<DuplicateFileEntry[]>([]);
    const fileUpload = useFileStageUpload({ ...options, setDuplicateFiles });
    const folderUpload = useFolderStageUpload({ ...options, setDuplicateFiles });

    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0) return;
        // Overwriting registers the staged copy, so exhausted storage blocks it.
        // The prompt stays open so the user can still choose to skip.
        if (isStorageBlocked()) return;
        try {
            await retryDuplicateFilesApi(activeSpace.id, duplicateFiles.map((entry) => entry.rawObj));
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
    }, [activeSpace, duplicateFiles, isStorageBlocked, loadFiles, localize, refreshQuota, showToast]);

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
