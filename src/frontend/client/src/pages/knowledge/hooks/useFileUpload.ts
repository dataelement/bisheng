import { useState, useCallback } from "react";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    SpaceRole,
    createFolderApi,
    renameFolderApi,
    deleteFolderApi,
    uploadFileToServerApi,
    addFilesApi,
    renameFileApi,
    deleteFileApi,
    type UploadFileResponse,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { getFileTypeFromName, MAX_FOLDER_DEPTH } from "../knowledgeUtils";
import { useLocalize } from "~/hooks";

/** A duplicate file entry detected during upload */
export interface DuplicateFileEntry {
    file: File;
    filePath: string;
    repeatFileName: string;
    repeatUpdateTime: string;
}

interface UseFileUploadOptions {
    activeSpace: KnowledgeSpace | null;
    currentFolderId: string | undefined;
    currentPath: Array<{ id?: string; name: string }>;
    files: KnowledgeFile[];
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<void>;
    currentPage: number;
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
    currentPage,
}: UseFileUploadOptions) {
    const localize = useLocalize();
    const [uploadingFiles, setUploadingFiles] = useState<KnowledgeFile[]>([]);
    const [creatingFolder, setCreatingFolder] = useState<KnowledgeFile | null>(null);
    // Duplicate file detection state
    const [duplicateFiles, setDuplicateFiles] = useState<DuplicateFileEntry[]>([]);

    const { showToast } = useToastContext();

    // ─── File upload (two-step: server upload → register) ────────────────
    const handleUploadFile = useCallback(
        async (fileList?: FileList | File[]) => {
            if (!activeSpace || !fileList || fileList.length === 0) {
                showToast({ message: localize("com_knowledge.upload_feature_dev"), severity: NotificationSeverity.INFO });
                return;
            }

            const fileArray = Array.from(fileList);

            // Create placeholder uploading entries for UI
            const placeholders: KnowledgeFile[] = fileArray.map(file => ({
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
            setUploadingFiles(prev => [...placeholders, ...prev]);


            // Upload each file and check for duplicates
            const normalPaths: string[] = [];
            const duplicates: DuplicateFileEntry[] = [];

            for (const file of fileArray) {
                try {
                    const res: UploadFileResponse = await uploadFileToServerApi(activeSpace.id, file);
                    if (res.repeat) {
                        // Duplicate detected — collect for user confirmation
                        duplicates.push({
                            file,
                            filePath: res.file_path,
                            repeatFileName: res.repeat_file_name || file.name,
                            repeatUpdateTime: res.repeat_update_time || "",
                        });
                    } else {
                        normalPaths.push(res.file_path);
                    }
                } catch {
                    showToast({ message: localize("com_knowledge.file_upload_failed", { 0: file.name }), severity: NotificationSeverity.ERROR });
                }
            }

            // If all uploads failed, clear placeholders immediately and bail out
            if (normalPaths.length === 0 && duplicates.length === 0) {
                setUploadingFiles(prev =>
                    prev.filter(f => !placeholders.some(p => p.id === f.id))
                );
                return;
            }

            // Register non-duplicate files immediately
            if (normalPaths.length > 0) {
                try {
                    await addFilesApi(activeSpace.id, {
                        file_path: normalPaths,
                        parent_id: currentFolderId ? Number(currentFolderId) : null,
                    });
                    await loadFiles(currentPage);
                } catch (e) {
                    // showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
                }
            } else {
                showToast({ message: localize("com_knowledge.processing_files", { 0: fileArray.length }), severity: NotificationSeverity.SUCCESS });
            }

            // Clear placeholders after list data has been updated
            setUploadingFiles(prev =>
                prev.filter(f => !placeholders.some(p => p.id === f.id))
            );

            // Show duplicate confirmation dialog if any
            if (duplicates.length > 0) {
                setDuplicateFiles(duplicates);
            }
        },
        [activeSpace, currentFolderId, currentPage, loadFiles, showToast]
    );

    /** User chose to overwrite duplicate files */
    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0) return;
        const paths = duplicateFiles.map(d => d.filePath);
        try {
            await addFilesApi(activeSpace.id, {
                file_path: paths,
                parent_id: currentFolderId ? Number(currentFolderId) : null,
            });
            showToast({
                message: localize("com_knowledge.upload_success_count", { 0: duplicateFiles.length }),
                severity: NotificationSeverity.SUCCESS,
            });
            await loadFiles(currentPage);
        } catch {
            showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
        } finally {
            setDuplicateFiles([]);
        }
    }, [activeSpace, duplicateFiles, currentFolderId, currentPage, loadFiles, showToast]);

    /** User chose NOT to overwrite — just discard duplicates */
    const handleDuplicateSkip = useCallback(() => {
        setDuplicateFiles([]);
    }, []);

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
                } catch {
                    showToast({ message: localize("com_knowledge.create_folder_failed"), severity: NotificationSeverity.ERROR });
                }
                return;
            }

            // ── Rename existing item ──
            const target = files.find(f => f.id === fileId);
            if (!target) return;

            try {
                if (target.type === FileType.FOLDER) {
                    await renameFolderApi(activeSpace.id, fileId, newName);
                } else {
                    await renameFileApi(activeSpace.id, fileId, newName);
                }
                setFiles(prev => prev.map(f => f.id === fileId ? { ...f, name: newName } : f));
                showToast({ message: localize("com_knowledge.rename_success"), severity: NotificationSeverity.SUCCESS } as any);
            } catch {
                showToast({ message: localize("com_knowledge.rename_failed"), severity: NotificationSeverity.ERROR });
            }
        },
        [activeSpace, creatingFolder, currentFolderId, files, setFiles, showToast]
    );

    // ─── Delete file/folder ──────────────────────────────────────────────
    const handleDeleteFile = useCallback(
        async (fileId: string) => {
            if (!activeSpace) return;

            // Empty fileId is used as a "refresh" signal — just refresh
            if (!fileId) {
                loadFiles(currentPage);
                return;
            }

            const target = files.find(f => f.id === fileId);
            if (!target) return;

            try {
                if (target.type === FileType.FOLDER) {
                    await deleteFolderApi(activeSpace.id, fileId);
                } else {
                    await deleteFileApi(activeSpace.id, fileId);
                }
                setFiles(prev => prev.filter(f => f.id !== fileId));
                setTotal(prev => Math.max(0, prev - 1));
                showToast({ message: localize("com_knowledge.deleted"), severity: NotificationSeverity.SUCCESS });
            } catch {
                showToast({ message: localize("com_knowledge.delete_failed"), severity: NotificationSeverity.ERROR });
            }
        },
        [activeSpace, currentPage, files, setFiles, loadFiles, showToast, setTotal]
    );

    const handleEditTags = useCallback(
        (_fileId: string) => {
            loadFiles(currentPage);
        },
        [currentPage, loadFiles]
    );

    return {
        uploadingFiles,
        creatingFolder,
        duplicateFiles,
        handleUploadFile,
        handleCreateFolder,
        handleCancelCreateFolder,
        handleRenameFile,
        handleDeleteFile,
        handleEditTags,
        handleDuplicateOverwrite,
        handleDuplicateSkip,
    };
}
