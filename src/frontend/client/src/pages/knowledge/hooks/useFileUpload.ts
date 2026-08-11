import { useState, useCallback } from "react";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    createFolderApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import {
    MAX_FOLDER_DEPTH,
} from "../knowledgeUtils";
import { useLocalize } from "~/hooks";
import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";
import { useKnowledgeStageUpload } from "./useKnowledgeStageUpload";
import { useKnowledgeFileMutations } from "./useKnowledgeFileMutations";

interface UseFileUploadOptions {
    activeSpace: KnowledgeSpace | null;
    currentFolderId: string | undefined;
    currentPath: Array<{ id?: string; name: string }>;
    files: KnowledgeFile[];
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<void>;
    currentPage: number;
    markPendingDeletion: (ids: Array<string | number>) => void;
    clearPendingDeletion: (ids: Array<string | number>) => void;
}

/**
 * Manages file upload, folder creation, and file CRUD operations.
 * Extracted from the root Knowledge component.
 */
export function useFileUpload({
    activeSpace,
    currentFolderId,
    currentPath,
    files,
    setFiles,
    setTotal,
    loadFiles,
}: UseFileUploadOptions) {
    const localize = useLocalize();
    const [creatingFolder, setCreatingFolder] = useState<KnowledgeFile | null>(null);
    const { showToast } = useToastContext();
    const stageUpload = useKnowledgeStageUpload({
        activeSpace,
        currentFolderId,
        files,
        setFiles,
        setTotal,
        loadFiles,
        localize,
        showToast,
    });
    const fileMutations = useKnowledgeFileMutations({
        activeSpace,
        files,
        setFiles,
        setTotal,
        loadFiles,
        localize,
        showToast,
    });

    // ─── Folder creation ─────────────────────────────────────────────────
    const handleCreateFolder = useCallback(() => {
        if (currentPath.length >= MAX_FOLDER_DEPTH) {
            showToast({ message: localize("com_knowledge.max_folder_depth_reached", { 0: MAX_FOLDER_DEPTH }), severity: NotificationSeverity.WARNING } as any);
            return;
        }

        const genRandomStr = () =>
            Math.random().toString(36).substring(2, 8).toUpperCase() +
            Math.random().toString(36).substring(2, 8).toUpperCase();
        const randomStr = genRandomStr().substring(0, 12);

        const newFolder: KnowledgeFile = {
            id: `temp_folder_${Date.now()}`,
            name: localize("com_knowledge.unnamed_folder_random", { 0: randomStr }),
            type: FileType.FOLDER,
            tags: [],
            path: localize("com_knowledge.unnamed_folder_random", { 0: randomStr }),
            parentId: currentFolderId,
            spaceId: activeSpace?.id || "",
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            status: FileStatus.SUCCESS,
            isCreating: true,
        };

        setCreatingFolder(newFolder);
    }, [currentPath.length, currentFolderId, activeSpace?.id, showToast]);

    const handleCancelCreateFolder = useCallback(() => {
        setCreatingFolder(null);
    }, []);

    // ─── Rename file/folder ──────────────────────────────────────────────
    /** Called when the inline-rename input is confirmed (new name submitted) */
    const handleRenameFile = useCallback(
        async (fileId: string, newName: string) => {
            if (!activeSpace) return;

            // ── Confirm in-progress folder creation ──
            if (creatingFolder && fileId === creatingFolder.id) {
                try {
                    const created = await createFolderApi(activeSpace.id, {
                        name: newName,
                        parent_id: currentFolderId || null,
                    });
                    setFiles(prev => [created, ...prev]);
                    setTotal(prev => prev + 1);
                    setCreatingFolder(null);
                    // Keep the left-side folder tree in sync.
                    dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                } catch (e: any) {
                    // Server-authoritative depth check: the breadcrumb-based
                    // pre-check in handleCreateFolder can race a navigation
                    // (async currentPath), so 18011 can still come back here.
                    if (e?.status_code === 18011) {
                        showToast({ message: localize("com_knowledge.max_folder_depth_reached", { 0: MAX_FOLDER_DEPTH }), severity: NotificationSeverity.WARNING } as any);
                        setCreatingFolder(null);
                    } else {
                        showToast({ message: localize("com_knowledge.create_folder_failed"), severity: NotificationSeverity.ERROR });
                    }
                }
                return;
            }

            await fileMutations.handleRenameExisting(fileId, newName);
        },
        [activeSpace, creatingFolder, currentFolderId, fileMutations, setFiles, showToast]
    );

    const handleEditTags = useCallback(
        (_fileId: string) => {
            loadFiles(1); // refresh from page 1 (cursor mode: page>1 = append, not refresh)
        },
        [loadFiles]
    );

    return {
        uploadingFiles: stageUpload.uploadingFiles,
        creatingFolder,
        uploadingFolder: stageUpload.uploadingFolder,
        duplicateFiles: stageUpload.duplicateFiles,
        handleUploadFile: stageUpload.handleUploadFile,
        handleUploadFolder: stageUpload.handleUploadFolder,
        handleCreateFolder,
        handleCancelCreateFolder,
        handleRenameFile,
        handleDeleteFile: fileMutations.handleDeleteFile,
        handleBatchDelete: fileMutations.handleBatchDelete,
        handleBatchRename: fileMutations.handleBatchRename,
        handleEditTags,
        handleDuplicateOverwrite: stageUpload.handleDuplicateOverwrite,
        handleDuplicateSkip: stageUpload.handleDuplicateSkip,
    };
}
