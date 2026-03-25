import { useState, useRef, useEffect, useCallback } from "react";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

interface UseInlineRenameOptions {
    /** Initial file/folder name */
    fileName: string;
    /** Whether the item is a folder */
    isFolder: boolean;
    /** Whether this is a brand-new folder being created inline */
    isCreating: boolean;
    /** Commit rename to parent */
    onRename: (newName: string) => void;
    /** Optional name validator — returns error message or null */
    onValidateName?: (newName: string) => string | null;
    /** Called when an in-progress creation is cancelled (Escape on new folder) */
    onCancelCreate?: () => void;
}

/**
 * Shared inline-rename logic used by both FileCard and FileRow.
 *
 * Manages renaming state, input ref auto-focus/selection, submit
 * with validation, and keyboard handling (Enter / Escape).
 */
export function useInlineRename({
    fileName,
    isFolder,
    isCreating,
    onRename,
    onValidateName,
    onCancelCreate,
}: UseInlineRenameOptions) {
    const localize = useLocalize();
    const [isRenaming, setIsRenaming] = useState(isCreating);
    const [renameValue, setRenameValue] = useState(fileName);
    const inputRef = useRef<HTMLInputElement>(null);
    const { showToast } = useToastContext();

    // Auto-focus input and select text when entering rename mode
    useEffect(() => {
        if (isRenaming && inputRef.current) {
            inputRef.current.focus();
            // Select text before extension for files, or select all for folders
            const dotIndex = fileName.lastIndexOf(".");
            if (dotIndex > 0 && !isFolder) {
                inputRef.current.setSelectionRange(0, dotIndex);
            } else {
                inputRef.current.select();
            }
        }
    }, [isRenaming, isFolder, fileName]);

    const handleRenameSubmit = useCallback(() => {
        const trimmed = renameValue.trim();

        // Creating mode: name must not be empty
        if (isCreating && !trimmed) {
            showToast({ message: localize("com_knowledge.folder_name_empty"), status: "error", severity: "error" } as any);
            inputRef.current?.focus();
            return;
        }

        // Non-creating: empty name → revert
        if (!isCreating && !trimmed) {
            setRenameValue(fileName);
            setIsRenaming(false);
            return;
        }

        // No change → close
        if (trimmed === fileName && !isCreating) {
            setIsRenaming(false);
            return;
        }

        // Validate
        if (onValidateName) {
            const err = onValidateName(trimmed);
            if (err) {
                showToast({ message: err, status: "error", severity: "error" } as any);
                inputRef.current?.focus();
                return;
            }
        }

        onRename(trimmed);
        setIsRenaming(false);
    }, [renameValue, isCreating, fileName, onRename, onValidateName, showToast]);

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === "Enter") {
                handleRenameSubmit();
            } else if (e.key === "Escape") {
                if (isCreating) {
                    onCancelCreate?.();
                } else {
                    setRenameValue(fileName);
                    setIsRenaming(false);
                }
            }
        },
        [handleRenameSubmit, isCreating, fileName, onCancelCreate]
    );

    /** Programmatically enter rename mode (e.g. from dropdown menu) */
    const startRenaming = useCallback(() => {
        setRenameValue(fileName);
        setIsRenaming(true);
    }, [fileName]);

    return {
        isRenaming,
        renameValue,
        setRenameValue,
        inputRef,
        handleRenameSubmit,
        handleKeyDown,
        startRenaming,
    };
}
