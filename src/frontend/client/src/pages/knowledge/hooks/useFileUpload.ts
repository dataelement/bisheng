import { useState, useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import i18next from "i18next";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    createFolderApi,
    renameFolderApi,
    deleteFolderApi,
    moveFileApi,
    moveFolderApi,
    uploadFileToServerApi,
    addFilesApi,
    renameFileApi,
    deleteFileApi,
    retryDuplicateFilesApi,
    listKnowledgeFolders,
    checkSensitiveWordsApi,
    type UploadFileResponse,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import {
    filterNestedFolderUploadFiles,
    extractSortedDirPaths,
    getFileTypeFromName,
    getRootFolderName,
    isHiddenName,
    isKnowledgeItemPending,
    isWebLinkKnowledgeFile,
    MAX_FOLDER_DEPTH,
    MAX_FOLDER_UPLOAD_COUNT,
    resolveWebLinkDisplayName,
    toWebLinkFileName,
    type UploadSizeLimits,
} from "../knowledgeUtils";
import { useLocalize } from "~/hooks";
import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";
import {
    extractDuplicateFileEntries,
    type DuplicateFileEntry,
} from "./duplicateFiles";

export {
    extractDuplicateFileEntries,
    type DuplicateFileEntry,
} from "./duplicateFiles";

/**
 * Resolve a human-friendly reason from an upload error.
 * Prefers the localized api_errors.{code} template (so 19403 renders as
 * "当前企业存储配额已耗尽（X/Y GB）..." with backend-provided used_gb/quota_gb)
 * and only falls back to the raw status_message when no template exists.
 * Returns "" when the error carries no actionable info — caller may then
 * append the generic browser-upload hint as a last-resort fallback.
 */
function resolveUploadErrorReason(err: any): string {
    const statusCode = err?.statusCode;
    if (statusCode != null) {
        const codeKey = `api_errors.${statusCode}`;
        if (i18next.exists(codeKey)) {
            return String(i18next.t(codeKey, err?.errorData ?? {}));
        }
    }
    if (typeof err?.message === "string" && err.message && err.message !== "upload file failed") {
        return err.message;
    }
    return "";
}

const PENDING_REGISTERED_FILE_STATUSES = new Set<FileStatus>([
    FileStatus.UPLOADING,
    FileStatus.WAITING,
    FileStatus.PROCESSING,
    FileStatus.REBUILDING,
]);

export function mergeVisibleRegisteredFiles(
    existingFiles: KnowledgeFile[],
    registeredFiles: KnowledgeFile[],
): { files: KnowledgeFile[]; addedCount: number } {
    if (registeredFiles.length === 0) {
        return { files: existingFiles, addedCount: 0 };
    }

    const existingIds = new Set(existingFiles.map((file) => file.id));
    const uniqueRegisteredFiles = registeredFiles.filter((file) => !existingIds.has(file.id));

    return {
        files: [...uniqueRegisteredFiles, ...existingFiles],
        addedCount: uniqueRegisteredFiles.length,
    };
}

interface UseFileUploadOptions {
    activeSpace: KnowledgeSpace | null;
    currentFolderId: string | undefined;
    currentPath: Array<{ id?: string; name: string }>;
    files: KnowledgeFile[];
    setFiles: Dispatch<SetStateAction<KnowledgeFile[]>>;
    setTotal: Dispatch<SetStateAction<number>>;
    loadFiles: (page?: number) => Promise<unknown>;
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
    currentPage,
    markPendingDeletion,
    clearPendingDeletion,
}: UseFileUploadOptions) {
    const localize = useLocalize();
    const [uploadingFiles, setUploadingFiles] = useState<KnowledgeFile[]>([]);
    const [creatingFolder, setCreatingFolder] = useState<KnowledgeFile | null>(null);
    // Duplicate file detection state
    const [duplicateFiles, setDuplicateFiles] = useState<DuplicateFileEntry[]>([]);

    const { showToast } = useToastContext();
    const activeSpaceIdRef = useRef<string | null>(activeSpace?.id ? String(activeSpace.id) : null);
    activeSpaceIdRef.current = activeSpace?.id ? String(activeSpace.id) : null;
    /** Guard against re-entry of handleUploadFolder while one batch is in flight. */
    const folderUploadInFlightRef = useRef(false);

    useEffect(() => {
        setUploadingFiles([]);
        setCreatingFolder(null);
        setDuplicateFiles([]);
    }, [activeSpace?.id]);

    // ─── File upload (two-step: server upload → register) ────────────────
    const handleUploadFile = useCallback(
        async (fileList?: FileList | File[]) => {
            if (!activeSpace || !fileList || fileList.length === 0) {
                showToast({ message: localize("com_knowledge.upload_feature_dev"), severity: NotificationSeverity.INFO });
                return;
            }

            const requestSpaceId = String(activeSpace.id);
            const isCurrentSpace = () => activeSpaceIdRef.current === requestSpaceId;
            const fileArray = Array.from(fileList);

            // Create placeholder uploading entries for UI
            const placeholders: KnowledgeFile[] = fileArray.map(file => ({
                id: `upload_${Date.now()}_${Math.random().toString(36).substring(7)}`,
                name: file.name,
                type: getFileTypeFromName(file.name),
                size: file.size,
                status: FileStatus.UPLOADING,
                uploadPhase: "uploading",
                uploadProgress: 0,
                tags: [],
                path: file.name,
                parentId: currentFolderId,
                spaceId: activeSpace.id,
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
            }));
            setUploadingFiles(prev => [...placeholders, ...prev]);

            const updatePlaceholder = (placeholderId: string, patch: Partial<KnowledgeFile>) => {
                if (!isCurrentSpace()) {
                    return;
                }
                setUploadingFiles(prev =>
                    prev.map(f => (f.id === placeholderId ? { ...f, ...patch } : f))
                );
            };

            // Upload each file to server
            const uploadedPaths: string[] = [];
            const placeholderByName = new Map(placeholders.map((p, index) => [fileArray[index].name, p]));

            const failures: { name: string; reason: string }[] = [];
            try {
                for (const file of fileArray) {
                    const placeholder = placeholderByName.get(file.name);
                    try {
                        const res: UploadFileResponse = await uploadFileToServerApi(
                            activeSpace.id,
                            file,
                            undefined,
                            {
                                onProgress: (percent) => {
                                    if (placeholder) {
                                        updatePlaceholder(placeholder.id, { uploadProgress: percent });
                                    }
                                },
                            },
                        );
                        uploadedPaths.push(res.file_path);
                        if (placeholder) {
                            updatePlaceholder(placeholder.id, { uploadProgress: 100 });
                        }
                    } catch (err) {
                        failures.push({
                            name: file.name,
                            reason: resolveUploadErrorReason(err),
                        });
                    }
                }
                if (!isCurrentSpace()) {
                    return;
                }
                if (failures.length > 0) {
                    const lines = failures.map(({ name, reason }) =>
                        reason
                            ? localize("com_knowledge.file_upload_failed_with_reason", { 0: name, 1: reason })
                            : localize("com_knowledge.file_upload_failed", { 0: name })
                    );
                    const everyReasonMissing = failures.every((f) => !f.reason);
                    const message = everyReasonMissing
                        ? [...lines, localize("com_knowledge.upload_browser_hint")].join("\n")
                        : lines.join("\n");
                    showToast({
                        message,
                        severity: NotificationSeverity.ERROR,
                    });
                }

                if (uploadedPaths.length === 0) {
                    return;
                }

                // Large duplicate overwrites can block here while the backend
                // copies the file into MinIO — surface a distinct UI phase.
                setUploadingFiles(prev =>
                    prev.map(f =>
                        placeholders.some(p => p.id === f.id)
                            ? { ...f, uploadPhase: "registering", uploadProgress: undefined }
                            : f
                    )
                );

                const registeredFiles = await addFilesApi(activeSpace.id, {
                    file_path: uploadedPaths,
                    parent_id: currentFolderId ? Number(currentFolderId) : null,
                });
                if (!isCurrentSpace()) {
                    return;
                }
                const dupes = extractDuplicateFileEntries(registeredFiles);
                if (dupes.length > 0) {
                    setDuplicateFiles(dupes);
                }

                const duplicateIds = new Set(dupes.map((file) => file.fileId));
                const visibleRegisteredFiles = registeredFiles.filter((file) => !duplicateIds.has(file.id));
                const { files: mergedFiles, addedCount } = mergeVisibleRegisteredFiles(files, visibleRegisteredFiles);

                if (visibleRegisteredFiles.length > 0) {
                    setFiles(mergedFiles);
                    if (addedCount > 0) {
                        setTotal((prev) => prev + addedCount);
                    }
                }

                const hasPendingRegisteredFiles = visibleRegisteredFiles.some((file) =>
                    isKnowledgeItemPending(file) ||
                    Boolean(file.status && PENDING_REGISTERED_FILE_STATUSES.has(file.status))
                );
                if (!hasPendingRegisteredFiles) {
                    await loadFiles(currentPage);
                }
            } catch {
                // addFiles errors are surfaced by the request interceptor
            } finally {
                if (isCurrentSpace()) {
                    setUploadingFiles(prev =>
                        prev.filter(f => !placeholders.some(p => p.id === f.id))
                    );
                }
            }
        },
        [activeSpace, currentFolderId, currentPage, files, loadFiles, localize, setFiles, setTotal, showToast]
    );

    /** User chose to replace duplicate files */
    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0) return;
        const requestSpaceId = String(activeSpace.id);
        const fileObjs = duplicateFiles.map(d => d.rawObj).filter(Boolean);
        try {
            await retryDuplicateFilesApi(activeSpace.id, fileObjs);
            if (activeSpaceIdRef.current !== requestSpaceId) {
                return;
            }
            await loadFiles(currentPage);
        } catch {
            showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
        } finally {
            if (activeSpaceIdRef.current === requestSpaceId) {
                setDuplicateFiles([]);
            }
        }
    }, [activeSpace, duplicateFiles, currentPage, loadFiles, localize, showToast]);

    /** User chose NOT to overwrite — just discard duplicates */
    const handleDuplicateSkip = useCallback(() => {
        setDuplicateFiles([]);
    }, []);

    // ─── Folder upload (pick a local folder; preserves nested structure) ────
    /**
     * Upload a picked folder, preserving its full directory tree. The browser
     * populates `File.webkitRelativePath` like "Docs/Sub/a.pdf". We:
     *   1. Reject if the root folder name collides at the current location,
     *      is hidden, or the raw file count exceeds MAX_FOLDER_UPLOAD_COUNT.
     *   2. Filter valid files (all depths, supported extensions, within size limit).
     *   3. Create all required folders top-down (BFS order), tracking path → id.
     *   4. Upload and register files grouped by their parent folder.
     */
    const handleUploadFolder = useCallback(
        async (
            fileList: FileList | File[],
            options: { allowedExtensions: readonly string[]; limits: UploadSizeLimits },
        ) => {
            if (!activeSpace || !fileList || fileList.length === 0) return;
            if (folderUploadInFlightRef.current) return;
            folderUploadInFlightRef.current = true;
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

                try {
                    const { items } = await listKnowledgeFolders({
                        space_id: activeSpace.id,
                        parent_id: currentFolderId ? Number(currentFolderId) : null,
                    });
                    if (items.some((f) => f.file_name === rootName)) {
                        showToast({
                            message: localize("com_knowledge.folder_already_exists", { 0: rootName }),
                            severity: NotificationSeverity.WARNING,
                        });
                        return;
                    }
                } catch {
                    // Fall through — backend will surface dup error if it collides
                }

                const validFiles = filterNestedFolderUploadFiles(allFiles, options);
                if (validFiles.length === 0) return;

                // Build all directory paths sorted by depth (parent always before child)
                const dirPaths = extractSortedDirPaths(validFiles);

                // Create folders top-down; track dirPath → created folder id
                const folderIdMap = new Map<string, string>();
                const folderFailures: { path: string; name: string; reason: string }[] = [];

                for (const dirPath of dirPaths) {
                    const parts = dirPath.split("/");
                    const name = parts[parts.length - 1];
                    const parentPath = parts.slice(0, -1).join("/");
                    const isRootLevel = parts.length === 1;

                    // Skip this folder if its parent creation already failed
                    if (!isRootLevel && !folderIdMap.has(parentPath)) continue;

                    const parentFolderId = isRootLevel
                        ? (currentFolderId || null)
                        : (folderIdMap.get(parentPath) ?? null);

                    try {
                        const folder = await createFolderApi(activeSpace.id, {
                            name,
                            parent_id: parentFolderId,
                        });
                        folderIdMap.set(dirPath, folder.id);

                        // Show root-level folder in the current listing immediately
                        if (isRootLevel) {
                            setFiles((prev) => [folder, ...prev]);
                            setTotal((prev) => prev + 1);
                        }
                    } catch (err: unknown) {
                        const reason = err instanceof Error ? err.message : String(err);
                        folderFailures.push({ path: dirPath, name, reason });
                    }
                }

                if (folderFailures.length > 0) {
                    const lines = folderFailures.map(({ path, reason }) =>
                        `[${path}] ${reason}`
                    );
                    showToast({ message: localize("com_knowledge.create_folder_failed") + "\n" + lines.join("\n"), severity: NotificationSeverity.ERROR });
                }

                // Group valid files by their parent directory path
                const filesByDir = new Map<string, File[]>();
                for (const file of validFiles) {
                    const rel = file.webkitRelativePath;
                    const parentPath = rel.split("/").slice(0, -1).join("/");
                    const arr = filesByDir.get(parentPath) ?? [];
                    arr.push(file);
                    filesByDir.set(parentPath, arr);
                }

                const failures: { name: string; reason: string }[] = [];

                for (const [dirPath, dirFiles] of filesByDir) {
                    const parentFolderId = folderIdMap.get(dirPath);
                    if (!parentFolderId) {
                        for (const f of dirFiles) {
                            failures.push({ name: f.name, reason: localize("com_knowledge.create_folder_failed") });
                        }
                        continue;
                    }

                    const uploadedPaths: string[] = [];
                    for (const file of dirFiles) {
                        try {
                            const res: UploadFileResponse = await uploadFileToServerApi(activeSpace.id, file, file.name);
                            uploadedPaths.push(res.file_path);
                        } catch (err) {
                            failures.push({ name: file.name, reason: resolveUploadErrorReason(err) });
                        }
                    }

                    if (uploadedPaths.length > 0) {
                        try {
                            const registeredFiles = await addFilesApi(activeSpace.id, {
                                file_path: uploadedPaths,
                                parent_id: Number(parentFolderId),
                            });
                            const dupes = extractDuplicateFileEntries(registeredFiles);
                            if (dupes.length > 0) {
                                setDuplicateFiles(dupes);
                            }
                        } catch {
                            // Swallow — refresh will reflect whatever made it in
                        }
                    }
                }

                if (failures.length > 0) {
                    const lines = failures.map(({ name, reason }) =>
                        reason
                            ? localize("com_knowledge.file_upload_failed_with_reason", { 0: name, 1: reason })
                            : localize("com_knowledge.file_upload_failed", { 0: name })
                    );
                    showToast({ message: lines.join("\n"), severity: NotificationSeverity.ERROR });
                }

                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                await loadFiles(currentPage);
            } finally {
                folderUploadInFlightRef.current = false;
            }
        },
        [activeSpace, currentFolderId, currentPage, loadFiles, localize, setDuplicateFiles, setFiles, setTotal, showToast],
    );

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
    }, [currentPath.length, currentFolderId, activeSpace?.id, localize, showToast]);

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
                const requestSpaceId = String(activeSpace.id);
                try {
                    const sensitiveCheck = await checkSensitiveWordsApi(activeSpace.id, [newName]);
                    if (sensitiveCheck.has_violation) {
                        showToast({ message: localize("com_knowledge.name_contains_sensitive_words"), severity: NotificationSeverity.ERROR });
                        return;
                    }
                    const created = await createFolderApi(activeSpace.id, {
                        name: newName,
                        parent_id: currentFolderId || null,
                    });
                    if (activeSpaceIdRef.current !== requestSpaceId) {
                        return;
                    }
                    setFiles(prev => [created, ...prev]);
                    setTotal(prev => prev + 1);
                    setCreatingFolder(null);
                    // Keep the left-side folder tree in sync.
                    dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                } catch {
                    if (activeSpaceIdRef.current !== requestSpaceId) {
                        return;
                    }
                    showToast({ message: localize("com_knowledge.create_folder_failed"), severity: NotificationSeverity.ERROR });
                }
                return;
            }

            // ── Rename existing item ──
            const target = files.find(f => f.id === fileId);
            if (!target) return;

            try {
                const sensitiveCheck = await checkSensitiveWordsApi(activeSpace.id, [newName]);
                if (sensitiveCheck.has_violation) {
                    showToast({ message: localize("com_knowledge.name_contains_sensitive_words"), severity: NotificationSeverity.ERROR });
                    return;
                }
                if (target.type === FileType.FOLDER) {
                    await renameFolderApi(activeSpace.id, fileId, newName);
                } else {
                    const isWebLink = isWebLinkKnowledgeFile(target);
                    const apiName = isWebLink ? toWebLinkFileName(newName) : newName;
                    const displayName = isWebLink ? resolveWebLinkDisplayName(apiName) : newName;
                    await renameFileApi(activeSpace.id, fileId, apiName);
                    setFiles(prev => prev.map(f => {
                        if (f.id !== fileId) return f;
                        if (!isWebLink) return { ...f, name: displayName };
                        return {
                            ...f,
                            name: displayName,
                            userMetadata: {
                                ...f.userMetadata,
                                web_title: displayName,
                            },
                        };
                    }));
                    showToast({ message: localize("com_knowledge.rename_success"), severity: NotificationSeverity.SUCCESS } as any);
                    return;
                }
                setFiles(prev => prev.map(f => f.id === fileId ? { ...f, name: newName } : f));
                if (target.type === FileType.FOLDER) {
                    // Folder rename changes a tree node label — sync the left tree.
                    dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                }
                showToast({ message: localize("com_knowledge.rename_success"), severity: NotificationSeverity.SUCCESS } as any);
            } catch {
                showToast({ message: localize("com_knowledge.rename_failed"), severity: NotificationSeverity.ERROR });
            }
        },
        [activeSpace, creatingFolder, currentFolderId, files, localize, setFiles, setTotal, showToast]
    );

    // ─── Delete file/folder ──────────────────────────────────────────────
    // Optimistic: drop the row from UI immediately, fire the backend API in
    // the background, and surface a success toast right away. Folders with
    // many files can take a long time on the server — there's no reason to
    // freeze the UI while that runs. On failure we roll back by re-fetching.
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

            const isFolder = target.type === FileType.FOLDER;

            // 1) Optimistically remove from UI + mark so the poll won't revive it.
            markPendingDeletion([fileId]);
            setFiles(prev => prev.filter(f => f.id !== fileId));
            setTotal(prev => Math.max(0, prev - 1));
            showToast({ message: localize("com_knowledge.deleted"), severity: NotificationSeverity.SUCCESS });
            if (isFolder) {
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            }

            // 2) Fire the backend API; on failure roll back via a reload.
            try {
                if (isFolder) {
                    await deleteFolderApi(activeSpace.id, fileId);
                } else {
                    await deleteFileApi(activeSpace.id, fileId);
                }
            } catch {
                showToast({ message: localize("com_knowledge.delete_failed"), severity: NotificationSeverity.ERROR });
                clearPendingDeletion([fileId]);
                loadFiles(currentPage);
                return;
            }
            clearPendingDeletion([fileId]);
        },
        [activeSpace, currentPage, files, setFiles, loadFiles, showToast, setTotal, markPendingDeletion, clearPendingDeletion, localize]
    );

    const handleEditTags = useCallback(
        (_fileId: string) => {
            loadFiles(currentPage);
        },
        [currentPage, loadFiles]
    );

    // ─── Move file/folder ────────────────────────────────────────────────
    const handleMoveFile = useCallback(
        async (fileId: string, targetFolderId: number | null) => {
            if (!activeSpace) return;
            const target = files.find(f => f.id === fileId);
            if (!target) return;
            try {
                if (target.type === FileType.FOLDER) {
                    await moveFolderApi(activeSpace.id, fileId, targetFolderId);
                } else {
                    await moveFileApi(activeSpace.id, fileId, targetFolderId);
                }
                // Remove from current folder list and refresh tree.
                setFiles(prev => prev.filter(f => f.id !== fileId));
                setTotal(prev => Math.max(0, prev - 1));
                dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                showToast({ message: localize("com_knowledge.move_success"), severity: NotificationSeverity.SUCCESS } as any);
            } catch {
                showToast({ message: localize("com_knowledge.move_failed"), severity: NotificationSeverity.ERROR });
            }
        },
        [activeSpace, files, setFiles, setTotal, showToast, localize]
    );

    return {
        uploadingFiles,
        creatingFolder,
        duplicateFiles,
        handleUploadFile,
        handleUploadFolder,
        handleCreateFolder,
        handleCancelCreateFolder,
        handleRenameFile,
        handleDeleteFile,
        handleMoveFile,
        handleEditTags,
        handleDuplicateOverwrite,
        handleDuplicateSkip,
    };
}
