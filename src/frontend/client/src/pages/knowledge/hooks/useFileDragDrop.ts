import { useRef, useCallback, useMemo } from "react";
import {
    MAX_UPLOAD_COUNT,
    DEFAULT_MAX_FILE_SIZE_MB,
    getAllowedMimeTypes,
    getAllowedExtensions,
} from "../knowledgeUtils";
import { useLocalize } from "~/hooks";

interface UseFileDragDropOptions {
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    /**
     * Folder drop handler. When provided, a dropped directory is read one level
     * deep (matching the folder-picker button) and handed off here. When omitted,
     * dropped folders are ignored.
     */
    onUploadFolder?: (
        files: File[],
        options: { allowedExtensions: readonly string[]; maxSizeMB: number },
    ) => void;
    /** Maximum single file size in MB (from env config). Falls back to DEFAULT_MAX_FILE_SIZE_MB. */
    maxFileSizeMB?: number;
    /** Whether ETL4LM service is deployed; controls which extensions/MIME types are accepted. */
    enableEtl4lm?: boolean;
}

/**
 * Read the *direct child files* of a dropped directory (single-level, matching
 * the folder-picker button). Each returned File gets a synthetic
 * `webkitRelativePath` of `"<dir>/<file>"` so it flows through the existing
 * folder-upload pipeline (getRootFolderName / filterFolderUploadFiles) unchanged.
 * Sub-directories are ignored. `readEntries` returns in batches, so it must be
 * called repeatedly until it yields an empty list.
 */
function readTopLevelFolderFiles(dirEntry: FileSystemDirectoryEntry): Promise<File[]> {
    return new Promise((resolve) => {
        const reader = dirEntry.createReader();
        const filePromises: Promise<File | null>[] = [];
        const finish = () =>
            Promise.all(filePromises).then((files) =>
                resolve(files.filter((f): f is File => f != null)),
            );
        const readBatch = () => {
            reader.readEntries((batch) => {
                if (batch.length === 0) {
                    finish();
                    return;
                }
                for (const ent of batch) {
                    if (ent.isFile) {
                        const fileEntry = ent as FileSystemFileEntry;
                        filePromises.push(
                            new Promise<File | null>((res) => {
                                fileEntry.file(
                                    (f) => {
                                        try {
                                            Object.defineProperty(f, "webkitRelativePath", {
                                                value: `${dirEntry.name}/${f.name}`,
                                                configurable: true,
                                            });
                                        } catch {
                                            // Property locked on this engine; the folder filter
                                            // then falls back to file.name and drops it — safe.
                                        }
                                        res(f);
                                    },
                                    () => res(null),
                                );
                            }),
                        );
                    }
                }
                readBatch();
            }, finish);
        };
        readBatch();
    });
}

/**
 * Manages drag-and-drop file upload interactions.
 * Extracted from SpaceDetail/index.tsx.
 */
export function useFileDragDrop({
    onDragStateChange,
    onUploadFile,
    onUploadFolder,
    maxFileSizeMB,
    enableEtl4lm = false,
}: UseFileDragDropOptions) {
    const localize = useLocalize();
    const dragCounter = useRef(0);
    const limitMB = maxFileSizeMB ?? DEFAULT_MAX_FILE_SIZE_MB;
    const limitBytes = limitMB * 1024 * 1024;
    const allowedMime = useMemo(() => getAllowedMimeTypes(enableEtl4lm), [enableEtl4lm]);
    const allowedExt = useMemo(() => getAllowedExtensions(enableEtl4lm), [enableEtl4lm]);

    const validateDragItems = useCallback((items: DataTransferItemList): string | null => {
        if (items.length > MAX_UPLOAD_COUNT) return localize("com_knowledge.max_upload_count", { 0: MAX_UPLOAD_COUNT });

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.kind === "file") {
                const type = item.type.toLowerCase();
                if (type && !allowedMime.includes(type)) {
                    return `包含不支持的文件格式 (${type || localize("com_knowledge.unknown_format")})`;
                }
            }
        }
        return null;
    }, [allowedMime, localize]);

    const handleDragEnter = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            dragCounter.current += 1;
            if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
                const error = validateDragItems(e.dataTransfer.items);
                onDragStateChange?.(true, error);
            }
        },
        [onDragStateChange, validateDragItems]
    );

    const handleDragLeave = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            dragCounter.current -= 1;
            if (dragCounter.current === 0) {
                onDragStateChange?.(false);
            }
        },
        [onDragStateChange]
    );

    const handleDragOver = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
                const error = validateDragItems(e.dataTransfer.items);
                onDragStateChange?.(true, error);
            }
        },
        [onDragStateChange, validateDragItems]
    );

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            dragCounter.current = 0;

            // Folder drop: detect a dropped directory via the Entries API. The
            // entries must be read out synchronously here — the DataTransferItemList
            // is invalidated once this handler returns, though the FileSystemEntry
            // objects it yields stay valid for the async directory read.
            const items = e.dataTransfer.items;
            if (onUploadFolder && items && items.length > 0) {
                let dirEntry: FileSystemDirectoryEntry | null = null;
                for (let i = 0; i < items.length; i++) {
                    const entry = items[i].webkitGetAsEntry?.();
                    if (entry?.isDirectory) {
                        dirEntry = entry as FileSystemDirectoryEntry;
                        break;
                    }
                }
                if (dirEntry) {
                    // handleUploadFolder owns count cap / hidden / dup-name / silent
                    // filtering, so just read one level deep and hand the files over.
                    // Any loose files in the same drop are ignored (button parity: one folder).
                    onDragStateChange?.(false);
                    void readTopLevelFolderFiles(dirEntry).then((files) => {
                        if (files.length > 0) {
                            onUploadFolder(files, { allowedExtensions: allowedExt, maxSizeMB: limitMB });
                        }
                    });
                    return;
                }
            }

            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const filesList = Array.from(e.dataTransfer.files);
                if (filesList.length > MAX_UPLOAD_COUNT) {
                    onDragStateChange?.(true, localize("com_knowledge.max_upload_count", { 0: MAX_UPLOAD_COUNT }));
                    onDragStateChange?.(false);
                    return;
                }

                for (const f of filesList) {
                    if (f.size > limitBytes) {
                        onDragStateChange?.(true, localize("com_knowledge.file_exceeds_limit", { name: f.name, size: limitMB }));
                        setTimeout(() => onDragStateChange?.(false), 2000);
                        return;
                    }
                    const ext = f.name.split(".").pop()?.toLowerCase();
                    if (!ext || !allowedExt.includes(ext)) {
                        onDragStateChange?.(true, localize("com_knowledge.unsupported_file_format", { 0: f.name }));
                        onDragStateChange?.(false);
                        return;
                    }
                }

                onDragStateChange?.(false);
                onUploadFile(filesList);
            } else {
                onDragStateChange?.(false);
            }
        },
        [onDragStateChange, onUploadFile, onUploadFolder, limitBytes, limitMB, allowedExt, localize]
    );

    return {
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
    };
}

