import { useRef, useCallback } from "react";
import {
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_COUNT,
    DEFAULT_MAX_FILE_SIZE_MB,
    ALLOWED_EXTENSIONS,
} from "../knowledgeUtils";
import { useLocalize } from "~/hooks";

interface UseFileDragDropOptions {
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    /** Maximum single file size in MB (from env config). Falls back to DEFAULT_MAX_FILE_SIZE_MB. */
    maxFileSizeMB?: number;
}

/**
 * Manages drag-and-drop file upload interactions.
 * Extracted from SpaceDetail/index.tsx.
 */
export function useFileDragDrop({ onDragStateChange, onUploadFile, maxFileSizeMB }: UseFileDragDropOptions) {
    const localize = useLocalize();
    const dragCounter = useRef(0);
    const limitMB = maxFileSizeMB ?? DEFAULT_MAX_FILE_SIZE_MB;
    const limitBytes = limitMB * 1024 * 1024;

    const validateDragItems = useCallback((items: DataTransferItemList): string | null => {
        if (items.length > MAX_UPLOAD_COUNT) return localize("com_knowledge.max_upload_count", { 0: MAX_UPLOAD_COUNT });

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.kind === "file") {
                const type = item.type.toLowerCase();
                if (type && !(ALLOWED_MIME_TYPES as readonly string[]).includes(type)) {
                    return `包含不支持的文件格式 (${type || localize("com_knowledge.unknown_format")})`;
                }
            }
        }
        return null;
    }, []);

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
                    if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
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
        [onDragStateChange, onUploadFile, limitBytes, limitMB]
    );

    return {
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
    };
}

