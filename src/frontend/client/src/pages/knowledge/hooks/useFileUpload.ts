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
    uploadFileToServerApi,
    addFilesApi,
    renameFileApi,
    deleteFileApi,
    retryDuplicateFilesApi,
    listKnowledgeFolders,
    type UploadFileResponse,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import {
    filterFolderUploadFiles,
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

    // ─── Folder upload (pick a local folder; one-level only) ─────────────
    /**
     * Upload a single picked folder. The browser populates
     * `File.webkitRelativePath` like "Docs/a.pdf" (root file) or
     * "Docs/Sub/b.pdf" (nested). We:
     *   1. Reject the whole batch if the picked folder is hidden,
     *      has a name already used at the current location, or the raw
     *      file count exceeds MAX_FOLDER_UPLOAD_COUNT.
     *   2. Silently filter to root-level + supported + size-ok files.
     *   3. Create one folder on the backend and register the kept files
     *      under it, reusing the existing upload + register pipeline.
     */
    const handleUploadFolder = useCallback(
        async (
            fileList: FileList | File[],
            options: { allowedExtensions: readonly string[]; limits: UploadSizeLimits },
        ) => {
            if (!activeSpace || !fileList || fileList.length === 0) return;
            // Re-entry guard. Ignore a second call while the first is still
            // running (a stray double-fire from the input would otherwise
            // upload every file twice and trigger spurious dup warnings).
            if (folderUploadInFlightRef.current) return;
            folderUploadInFlightRef.current = true;
            try {
            const allFiles = Array.from(fileList);

            const rootName = getRootFolderName(allFiles[0]?.webkitRelativePath || "");
            if (!rootName) return;

            // Hidden folder (e.g. `.git`) — silently reject the whole batch.
            if (isHiddenName(rootName)) return;

            // Raw count cap. Counts every file the user picked, including ones
            // that would later be filtered out — matches what the user sees.
            if (allFiles.length > MAX_FOLDER_UPLOAD_COUNT) {
                showToast({
                    message: localize("com_knowledge.folder_upload_exceed_limit", { 0: MAX_FOLDER_UPLOAD_COUNT }),
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }

            // Reject if the picked folder name is already used at the current
            // location. Use the same listing API the left tree uses so admin
            // and member roles see the same set.
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
                // Pre-check failed — fall through; backend will surface dup error
                // via createFolderApi if it really collides.
            }

            const validFiles = filterFolderUploadFiles(allFiles, options);
            if (validFiles.length === 0) return;

            // Create the destination folder first so we have a parent_id to
            // register the uploaded files against.
            let folder: KnowledgeFile;
            try {
                folder = await createFolderApi(activeSpace.id, {
                    name: rootName,
                    parent_id: currentFolderId || null,
                });
            } catch {
                showToast({ message: localize("com_knowledge.create_folder_failed"), severity: NotificationSeverity.ERROR });
                return;
            }

            // Show the new folder in the current listing immediately.
            setFiles((prev) => [folder, ...prev]);
            setTotal((prev) => prev + 1);
            dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);

            // Upload each file to object storage (sequential, mirrors existing
            // single-file upload — keeps load predictable for 1k batches).
            const uploadedPaths: string[] = [];
            const failures: { name: string; reason: string }[] = [];
            for (const file of validFiles) {
                try {
                    // Pass `file.name` explicitly to strip the folder prefix
                    // Chromium would otherwise put in the multipart filename.
                    const res: UploadFileResponse = await uploadFileToServerApi(activeSpace.id, file, file.name);
                    uploadedPaths.push(res.file_path);
                } catch (err) {
                    failures.push({
                        name: file.name,
                        reason: resolveUploadErrorReason(err),
                    });
                }
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
                showToast({ message, severity: NotificationSeverity.ERROR });
            }

            if (uploadedPaths.length === 0) {
                // Folder created but every file upload failed — list refresh
                // ensures the empty folder shows up with the correct counts.
                await loadFiles(currentPage);
                return;
            }

            // Register files under the new folder. Duplicates inside this new
            // folder shouldn't be possible (a fresh folder is empty), but the
            // backend may still flag global duplicates by md5; reuse the
            // existing duplicate-overwrite flow.
            try {
                const registeredFiles = await addFilesApi(activeSpace.id, {
                    file_path: uploadedPaths,
                    parent_id: Number(folder.id),
                });
                const dupes = extractDuplicateFileEntries(registeredFiles);
                if (dupes.length > 0) {
                    setDuplicateFiles(dupes);
                }
            } catch {
                // Swallow — the refresh below will reflect whatever made it in.
            }

            await loadFiles(currentPage);
            } finally {
                folderUploadInFlightRef.current = false;
            }
        },
        [activeSpace, currentFolderId, currentPage, loadFiles, localize, setFiles, setTotal, showToast],
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
        handleEditTags,
        handleDuplicateOverwrite,
        handleDuplicateSkip,
    };
}
