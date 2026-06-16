import { useState, useCallback, useRef } from "react";
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
    uploadFolderApi,
    addFilesApi,
    type FolderUploadItemPayload,
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
    MAX_FOLDER_DEPTH,
    MAX_FOLDER_UPLOAD_COUNT,
} from "../knowledgeUtils";
import { useLocalize } from "~/hooks";
import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";

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

/** A duplicate file entry detected from addFiles response (status === 3) */
export interface DuplicateFileEntry {
    fileId: string;
    fileName: string;
    oldFileLevelPath: string;
    /** Raw object from addFiles response, passed to retry API as-is */
    rawObj: any;
}

const PENDING_REGISTERED_FILE_STATUSES = new Set<FileStatus>([
    FileStatus.UPLOADING,
    FileStatus.WAITING,
    FileStatus.PROCESSING,
    FileStatus.REBUILDING,
]);

export function extractDuplicateFileEntries(registeredFiles: KnowledgeFile[]): DuplicateFileEntry[] {
    // Backend marks duplicates by setting `old_file_level_path` to a string (possibly empty
    // when the existing file lives at the space root). Real parse failures leave the field
    // unset (None → undefined). Use type check, not truthiness, to keep root-level duplicates.
    return registeredFiles
        .filter((file) => (
            file.status === FileStatus.FAILED &&
            typeof file.oldFileLevelPath === "string" &&
            Boolean((file as any)._raw)
        ))
        .map((file) => ({
            fileId: file.id,
            fileName: file.name,
            oldFileLevelPath: file.oldFileLevelPath || "",
            rawObj: (file as any)._raw,
        }));
}

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
    /** Guard against re-entry of handleUploadFolder while one batch is in flight. */
    const folderUploadInFlightRef = useRef(false);

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


            // Upload each file to server
            const uploadedPaths: string[] = [];

            const failures: { name: string; reason: string }[] = [];
            for (const file of fileArray) {
                try {
                    const res: UploadFileResponse = await uploadFileToServerApi(activeSpace.id, file);
                    uploadedPaths.push(res.file_path);
                } catch (err) {
                    failures.push({
                        name: file.name,
                        reason: resolveUploadErrorReason(err),
                    });
                }
            }
            if (failures.length > 0) {
                // Render each failure with the backend reason inline (quota / dup /
                // permission etc). The browser-upload hint is now strictly a
                // last-resort fallback — only appended when *every* failure has
                // no actionable reason (i.e. likely a client-wide network /
                // timeout case, the scenario the hint was originally written for).
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

            // If all uploads failed, clear placeholders and bail out
            if (uploadedPaths.length === 0) {
                setUploadingFiles(prev =>
                    prev.filter(f => !placeholders.some(p => p.id === f.id))
                );
                return;
            }

            // Register all uploaded files and check for duplicates from response
            try {
                const registeredFiles = await addFilesApi(activeSpace.id, {
                    file_path: uploadedPaths,
                    parent_id: currentFolderId ? Number(currentFolderId) : null,
                });
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
            } catch (e) {
                // showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
            }

            // Clear placeholders after list data has been updated
            setUploadingFiles(prev =>
                prev.filter(f => !placeholders.some(p => p.id === f.id))
            );
        },
        [activeSpace, currentFolderId, currentPage, files, loadFiles, localize, setFiles, setTotal, showToast]
    );

    /** User chose to replace duplicate files */
    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0) return;
        const fileObjs = duplicateFiles.map(d => d.rawObj).filter(Boolean);
        try {
            await retryDuplicateFilesApi(activeSpace.id, fileObjs);
            await loadFiles(currentPage);
        } catch {
            showToast({ message: localize("com_knowledge.file_register_failed"), severity: NotificationSeverity.ERROR });
        } finally {
            setDuplicateFiles([]);
        }
    }, [activeSpace, duplicateFiles, currentPage, loadFiles, showToast]);

    /** User chose NOT to overwrite — just discard duplicates */
    const handleDuplicateSkip = useCallback(() => {
        setDuplicateFiles([]);
    }, []);

    // ─── Folder upload (pick a local folder; nested, F034 §5.5) ──────────
    /**
     * Upload a single picked folder, keeping its whole nested structure. The
     * browser populates `File.webkitRelativePath` like "Docs/a.pdf" (root
     * file) or "Docs/Sub/b.pdf" (nested). We:
     *   1. Reject the whole batch if the picked folder is hidden, has a name
     *      already used at the current location, or the raw (pre-filter) file
     *      count exceeds MAX_FOLDER_UPLOAD_COUNT — each with a toast (AC-32).
     *   2. Silently filter out hidden / unsupported / oversize files at every
     *      nesting level (AC-27).
     *   3. Upload each file body, then register the batch via
     *      uploadFolderApi — the backend rebuilds the directory tree and runs
     *      the regular parse pipeline; batch rejections toast via
     *      api_errors.<code>.
     */
    const handleUploadFolder = useCallback(
        async (
            fileList: FileList | File[],
            options: { allowedExtensions: readonly string[]; maxSizeMB: number },
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

            const { valid: validFiles, oversizeCount, unsupportedCount } =
                filterFolderUploadFiles(allFiles, options);
            // ⑦: tell the user which files were dropped (oversize / unsupported
            // format) instead of silently skipping them; hidden files stay
            // silent. Shown even when some valid files still upload.
            if (oversizeCount > 0 || unsupportedCount > 0) {
                const parts: string[] = [];
                if (oversizeCount > 0) {
                    parts.push(localize("com_knowledge.folder_upload_skipped_oversize", { 0: oversizeCount }));
                }
                if (unsupportedCount > 0) {
                    parts.push(localize("com_knowledge.folder_upload_skipped_unsupported", { 0: unsupportedCount }));
                }
                showToast({ message: parts.join("\n"), severity: NotificationSeverity.WARNING });
            }
            if (validFiles.length === 0) {
                // Every file was silently filtered (format / hidden / oversize):
                // nothing to upload, and no empty tree is created (AC-27 edge).
                showToast({
                    message: localize("com_knowledge.folder_upload_no_valid_files"),
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }

            // Upload each file body to object storage (sequential, mirrors the
            // existing single-file upload — keeps load predictable for 1k
            // batches), keeping its relative path + size for the tree rebuild.
            const uploadedItems: FolderUploadItemPayload[] = [];
            const failures: { name: string; reason: string }[] = [];
            for (const file of validFiles) {
                try {
                    // Pass `file.name` explicitly to strip the folder prefix
                    // Chromium would otherwise put in the multipart filename.
                    const res: UploadFileResponse = await uploadFileToServerApi(activeSpace.id, file, file.name);
                    uploadedItems.push({
                        file_path: res.file_path,
                        relative_path: file.webkitRelativePath || file.name,
                        size: file.size,
                    });
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

            if (uploadedItems.length === 0) return;

            // Register the whole batch: the backend rebuilds the directory tree
            // from each item's relative_path, then runs the regular pipeline.
            // Batch rejections (depth / dup folder / quota / count) are toasted
            // by the interceptor via api_errors.<code> (AC-32).
            try {
                const registeredFiles = await uploadFolderApi(activeSpace.id, {
                    parent_id: currentFolderId ? Number(currentFolderId) : null,
                    items: uploadedItems,
                });
                const dupes = extractDuplicateFileEntries(registeredFiles);
                if (dupes.length > 0) {
                    setDuplicateFiles(dupes);
                }
            } catch {
                // Whole batch rejected before any row was created; the toast
                // already fired in the interceptor. Nothing to refresh.
                return;
            }

            dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
            await loadFiles(currentPage);
            } finally {
                folderUploadInFlightRef.current = false;
            }
        },
        [activeSpace, currentFolderId, currentPage, loadFiles, localize, showToast],
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
                if (target.type === FileType.FOLDER) {
                    // Folder rename changes a tree node label — sync the left tree.
                    dispatchKnowledgeSpaceFilesRefresh(activeSpace.id);
                }
                showToast({ message: localize("com_knowledge.rename_success"), severity: NotificationSeverity.SUCCESS } as any);
            } catch {
                showToast({ message: localize("com_knowledge.rename_failed"), severity: NotificationSeverity.ERROR });
            }
        },
        [activeSpace, creatingFolder, currentFolderId, files, setFiles, showToast]
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
