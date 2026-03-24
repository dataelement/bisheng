import { useRef, useCallback } from "react";
import {
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_COUNT,
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
} from "../knowledgeUtils";

interface UseFileDragDropOptions {
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    onUploadFile: (files?: FileList | File[]) => void;
}

/**
 * Manages drag-and-drop file upload interactions.
 * Extracted from SpaceDetail/index.tsx.
 */
export function useFileDragDrop({ onDragStateChange, onUploadFile }: UseFileDragDropOptions) {
    const dragCounter = useRef(0);

    const validateDragItems = useCallback((items: DataTransferItemList): string | null => {
        if (items.length > MAX_UPLOAD_COUNT) return `单次最多允许上传 ${MAX_UPLOAD_COUNT} 个文件`;

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.kind === "file") {
                const type = item.type.toLowerCase();
                if (type && !(ALLOWED_MIME_TYPES as readonly string[]).includes(type)) {
                    return `包含不支持的文件格式 (${type || "未知格式"})`;
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
                    onDragStateChange?.(true, `单次最多允许上传 ${MAX_UPLOAD_COUNT} 个文件`);
                    onDragStateChange?.(false);
                    return;
                }

                for (const f of filesList) {
                    if (f.size > MAX_FILE_SIZE) {
                        onDragStateChange?.(true, `文件 ${f.name} 超过 200MB 限制`);
                        setTimeout(() => onDragStateChange?.(false), 2000);
                        return;
                    }
                    const ext = f.name.split(".").pop()?.toLowerCase();
                    if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
                        onDragStateChange?.(true, `不支持文件 ${f.name} 的格式`);
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
        [onDragStateChange, onUploadFile]
    );

    return {
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
    };
}
