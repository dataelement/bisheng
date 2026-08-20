import { useCallback, useRef, useState } from "react";

import {
    FileStatus,
    FileType,
    listKnowledgeFolders,
    type FolderUploadItemPayload,
    type KnowledgeFile,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    filterFolderUploadFiles,
    getRootFolderName,
    isHiddenName,
    MAX_FOLDER_UPLOAD_COUNT,
    type UploadSizeLimits,
} from "../knowledgeUtils";
import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";
import {
    buildUploadFailureMessage,
    extractDuplicateFileEntries,
    partitionUploadMutationResults,
    registerFolderStagesWithRetry,
    sumFileSizes,
    uploadFilesSequential,
    type DuplicateFileEntry,
    type RefreshQuota,
    type StorageQuotaGuard,
} from "./fileUploadUtils";
import { handleUploadMutationFeedback } from "./stageUploadFeedback";

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

interface UseFolderStageUploadOptions {
    activeSpace: KnowledgeSpace | null;
    currentFolderId?: string;
    loadFiles: (page?: number) => Promise<void>;
    localize: Localize;
    showToast: ShowToast;
    setDuplicateFiles: React.Dispatch<React.SetStateAction<DuplicateFileEntry[]>>;
    isStorageBlocked: StorageQuotaGuard;
    refreshQuota: RefreshQuota;
}

export function useFolderStageUpload(options: UseFolderStageUploadOptions) {
    const {
        activeSpace, currentFolderId, loadFiles, localize, showToast,
        setDuplicateFiles, isStorageBlocked, refreshQuota,
    } = options;
    const [uploadingFolder, setUploadingFolder] = useState<KnowledgeFile | null>(null);
    const folderUploadInFlightRef = useRef(false);

    const handleUploadFolder = useCallback(async (
        fileList: FileList | File[],
        uploadOptions: { allowedExtensions: readonly string[]; maxSizeMB: number; limits?: UploadSizeLimits },
    ) => {
        if (!activeSpace || !fileList || fileList.length === 0 || folderUploadInFlightRef.current) return;
        if (isStorageBlocked()) return;
        folderUploadInFlightRef.current = true;
        let placeholderShown = false;
        try {
            const allFiles = Array.from(fileList);
            const rootName = getRootFolderName(allFiles[0]?.webkitRelativePath || "");
            if (!rootName || isHiddenName(rootName)) return;
            if (allFiles.length > MAX_FOLDER_UPLOAD_COUNT) {
                showToast({
                    message: localize("com_knowledge.folder_upload_exceed_limit", { 0: MAX_FOLDER_UPLOAD_COUNT }),
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }
            setUploadingFolder({
                id: `upload_folder_${Date.now()}`,
                name: rootName,
                type: FileType.FOLDER,
                tags: [],
                path: rootName,
                parentId: currentFolderId,
                spaceId: activeSpace.id,
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
                status: FileStatus.UPLOADING,
            });
            placeholderShown = true;
            try {
                const { items } = await listKnowledgeFolders({
                    space_id: activeSpace.id,
                    parent_id: currentFolderId ? Number(currentFolderId) : null,
                });
                if (items.some((folder) => folder.file_name === rootName)) {
                    showToast({
                        message: localize("com_knowledge.folder_already_exists", { 0: rootName }),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }
            } catch {
                // The registration endpoint remains authoritative for name conflicts.
            }

            const { valid, oversizeCount, unsupportedCount } = filterFolderUploadFiles(allFiles, uploadOptions);
            const skippedMessages: string[] = [];
            if (oversizeCount > 0) {
                skippedMessages.push(localize("com_knowledge.folder_upload_skipped_oversize", { 0: oversizeCount }));
            }
            if (unsupportedCount > 0) {
                skippedMessages.push(localize("com_knowledge.folder_upload_skipped_unsupported", { 0: unsupportedCount }));
            }
            if (skippedMessages.length > 0) {
                showToast({ message: skippedMessages.join("\n"), severity: NotificationSeverity.WARNING });
            }
            if (valid.length === 0) {
                showToast({
                    message: localize("com_knowledge.folder_upload_no_valid_files"),
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }
            // Capacity pre-check on what will actually be stored, so filtered-out
            // files do not count against the remaining space.
            if (isStorageBlocked(sumFileSizes(valid))) return;

            const uploadedItems: FolderUploadItemPayload[] = [];
            const { failures, earlyStop } = await uploadFilesSequential(
                activeSpace.id,
                valid,
                (response, file) => uploadedItems.push({
                    // Always present on a resolved upload (see useFileStageUpload).
                    upload_id: response.upload_id as string,
                    relative_path: file.webkitRelativePath || file.name,
                }),
                (file) => file.name,
            );
            const failureMessage = buildUploadFailureMessage(failures, earlyStop, localize);
            if (failureMessage) showToast({ message: failureMessage, severity: NotificationSeverity.ERROR });
            if (uploadedItems.length === 0) {
                // A quota rejection means the cached numbers are already stale.
                refreshQuota();
                return;
            }

            const mutationResults = partitionUploadMutationResults(await registerFolderStagesWithRetry({
                spaceId: activeSpace.id,
                parentId: currentFolderId ? Number(currentFolderId) : null,
                items: uploadedItems,
            }));
            // Usage counts registered files only, so this is where it moved.
            refreshQuota();
            const duplicates = extractDuplicateFileEntries(mutationResults.directFiles);
            if (duplicates.length > 0) setDuplicateFiles(duplicates);
            handleUploadMutationFeedback(activeSpace.id, mutationResults, localize, showToast);
            if (mutationResults.directFiles.length === 0) return;
            dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            await loadFiles(1);
        } catch {
            return;
        } finally {
            folderUploadInFlightRef.current = false;
            if (placeholderShown) setUploadingFolder(null);
        }
    }, [activeSpace, currentFolderId, isStorageBlocked, loadFiles, localize, refreshQuota, setDuplicateFiles, showToast]);

    return { uploadingFolder, handleUploadFolder };
}
