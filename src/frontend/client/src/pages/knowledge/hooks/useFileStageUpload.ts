import { useCallback, useState } from "react";

import { FileStatus, type KnowledgeFile, type KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { isKnowledgeItemPending } from "../knowledgeUtils";
import {
    buildUploadFailureMessage,
    extractDuplicateFileEntries,
    mergeVisibleRegisteredFiles,
    partitionUploadMutationResults,
    registerUploadedStagesWithRetry,
    uploadFilesSequential,
    type DuplicateFileEntry,
} from "./fileUploadUtils";
import { getFileTypeFromName } from "../knowledgeUtils";
import { handleUploadMutationFeedback, REGISTERED_PROCESSING_STATUSES } from "./stageUploadFeedback";

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

interface UseFileStageUploadOptions {
    activeSpace: KnowledgeSpace | null;
    currentFolderId?: string;
    files: KnowledgeFile[];
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<void>;
    localize: Localize;
    showToast: ShowToast;
    setDuplicateFiles: React.Dispatch<React.SetStateAction<DuplicateFileEntry[]>>;
}

export function useFileStageUpload(options: UseFileStageUploadOptions) {
    const {
        activeSpace, currentFolderId, files, setFiles, setTotal, loadFiles,
        localize, showToast, setDuplicateFiles,
    } = options;
    const [uploadingFiles, setUploadingFiles] = useState<KnowledgeFile[]>([]);

    const handleUploadFile = useCallback(async (fileList?: FileList | File[]) => {
        if (!activeSpace || !fileList || fileList.length === 0) {
            showToast({ message: localize("com_knowledge.upload_feature_dev"), severity: NotificationSeverity.INFO });
            return;
        }
        const fileArray = Array.from(fileList);
        const placeholders: KnowledgeFile[] = fileArray.map((file) => ({
            id: `upload_${Date.now()}_${Math.random().toString(36).substring(7)}`,
            name: file.name,
            type: getFileTypeFromName(file.name),
            size: file.size,
            status: FileStatus.UPLOADING,
            tags: [],
            path: file.name,
            parentId: currentFolderId,
            spaceId: activeSpace.id,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
        }));
        setUploadingFiles((previous) => [...placeholders, ...previous]);

        const uploadIds: string[] = [];
        const { failures, earlyStop } = await uploadFilesSequential(
            activeSpace.id,
            fileArray,
            // uploadFileToServerApi throws when upload_id is missing, so a
            // resolved response always carries it — the field is optional only
            // because the legacy (pre-stage) response shape shares this type.
            (response) => { if (response.upload_id) uploadIds.push(response.upload_id); },
        );
        const failureMessage = buildUploadFailureMessage(failures, earlyStop, localize);
        if (failureMessage) showToast({ message: failureMessage, severity: NotificationSeverity.ERROR });
        if (uploadIds.length === 0) {
            setUploadingFiles((previous) => previous.filter(
                (file) => !placeholders.some((placeholder) => placeholder.id === file.id),
            ));
            return;
        }

        try {
            const mutationResults = partitionUploadMutationResults(await registerUploadedStagesWithRetry({
                spaceId: activeSpace.id,
                uploadIds,
                parentId: currentFolderId ? Number(currentFolderId) : null,
            }));
            const duplicates = extractDuplicateFileEntries(mutationResults.directFiles);
            if (duplicates.length > 0) setDuplicateFiles(duplicates);
            handleUploadMutationFeedback(activeSpace.id, mutationResults, localize, showToast);
            const duplicateIds = new Set(duplicates.map((file) => file.fileId));
            const visibleDirectFiles = mutationResults.directFiles.filter((file) => !duplicateIds.has(file.id));
            const merged = mergeVisibleRegisteredFiles(files, visibleDirectFiles);
            if (visibleDirectFiles.length > 0) {
                setFiles(merged.files);
                if (merged.addedCount > 0) setTotal((previous) => previous + merged.addedCount);
            }
            const isStillProcessing = visibleDirectFiles.some((file) =>
                isKnowledgeItemPending(file)
                || Boolean(file.status && REGISTERED_PROCESSING_STATUSES.has(file.status)),
            );
            if (visibleDirectFiles.length > 0 && !isStillProcessing) await loadFiles(1);
        } catch (error) {
            console.error("[useFileUpload] file registration failed:", error);
            showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
        } finally {
            setUploadingFiles((previous) => previous.filter(
                (file) => !placeholders.some((placeholder) => placeholder.id === file.id),
            ));
        }
    }, [activeSpace, currentFolderId, files, loadFiles, localize, setDuplicateFiles, setFiles, setTotal, showToast]);

    return { uploadingFiles, handleUploadFile };
}
