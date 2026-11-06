import { showApiError } from "~/api/request";
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
    onRename: (newName: string) => void | Promise<void>;
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
    const pendingRef = useRef(false);
    const renameAfterMenuCloseRef = useRef(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const { showToast } = useToastContext();
    // Mirrors isRenaming so a commit can tell it already ran. An outside click
    // reaches us twice (the pointerdown listener below, then the input's own
    // blur); without this the second one would fire a duplicate onRename.
    const isRenamingRef = useRef(isCreating);

    const stopRenaming = useCallback(() => {
        isRenamingRef.current = false;
        setIsRenaming(false);
    }, []);

    // Auto-focus input and select text when entering rename mode
    useEffect(() => {
        if (isRenaming && inputRef.current) {
            const input = inputRef.current;
            // Menu actions enter this state only after their focus scope closes.
            input.focus();
            // Select text before extension for files, or select all for folders.
            const dotIndex = fileName.lastIndexOf(".");
            if (dotIndex > 0 && !isFolder) {
                input.setSelectionRange(0, dotIndex);
            } else {
                input.select();
            }
        }
    }, [isRenaming, isFolder, fileName]);

    const handleRenameSubmit = useCallback(() => {
        if (!isRenamingRef.current || pendingRef.current) return;

        const trimmed = renameValue.trim();

        // Creating mode: name must not be empty
        if (isCreating && !trimmed) {
            showToast({ message: localize("com_knowledge.folder_name_empty"), status: "warning", severity: "error" } as any);
            inputRef.current?.focus();
            return;
        }

        // Non-creating: empty name → revert
        if (!isCreating && !trimmed) {
            setRenameValue(fileName);
            stopRenaming();
            return;
        }

        // No change → close
        if (trimmed === fileName && !isCreating) {
            stopRenaming();
            return;
        }

        // Validate
        if (onValidateName) {
            const err = onValidateName(trimmed);
            if (err) {
                showToast({ message: err, status: "warning", severity: "error" } as any);
                inputRef.current?.focus();
                return;
            }
        }

        try {
            const saved = onRename(trimmed);
            if (saved && typeof saved.then === 'function') {
                pendingRef.current = true;
                void saved.then(stopRenaming).catch(error => {
                    showApiError(error);
                    inputRef.current?.focus();
                }).finally(() => { pendingRef.current = false; });
            } else stopRenaming();
        } catch (error) {
            showApiError(error);
        }
    }, [renameValue, isCreating, fileName, onRename, onValidateName, showToast, stopRenaming]);

    // Commit on a click anywhere outside the field. The input's own onBlur can't
    // carry this alone: whenever focus fails to land on it (see the effect above)
    // no blur ever fires, and the edit silently stays open. Capture phase, so the
    // commit happens before the click reaches a row / toolbar handler.
    useEffect(() => {
        if (!isRenaming) return;

        const handlePointerDownOutside = (event: PointerEvent) => {
            const input = inputRef.current;
            if (input && !input.contains(event.target as Node)) {
                handleRenameSubmit();
            }
        };

        document.addEventListener("pointerdown", handlePointerDownOutside, true);
        return () => document.removeEventListener("pointerdown", handlePointerDownOutside, true);
    }, [isRenaming, handleRenameSubmit]);

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === "Enter") {
                handleRenameSubmit();
            } else if (e.key === "Escape") {
                if (isCreating) {
                    isRenamingRef.current = false;
                    onCancelCreate?.();
                } else {
                    setRenameValue(fileName);
                    stopRenaming();
                }
            }
        },
        [handleRenameSubmit, isCreating, fileName, onCancelCreate, stopRenaming]
    );

    /** Programmatically enter rename mode (e.g. from dropdown menu) */
    const startRenaming = useCallback(() => {
        setRenameValue(fileName);
        isRenamingRef.current = true;
        setIsRenaming(true);
    }, [fileName]);

    const startRenamingFromMenu = useCallback(() => {
        renameAfterMenuCloseRef.current = true;
    }, []);

    const handleMenuCloseAutoFocus = useCallback((event: Event) => {
        if (!renameAfterMenuCloseRef.current) return;
        renameAfterMenuCloseRef.current = false;
        // The menu has finished its exit animation. Keep it from reclaiming focus.
        event.preventDefault();
        startRenaming();
    }, [startRenaming]);

    return {
        isRenaming,
        renameValue,
        setRenameValue,
        inputRef,
        handleRenameSubmit,
        handleKeyDown,
        startRenaming,
        startRenamingFromMenu,
        handleMenuCloseAutoFocus,
    };
}
