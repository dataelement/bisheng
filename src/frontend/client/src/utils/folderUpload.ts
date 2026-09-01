/**
 * Folder-upload plumbing shared by the knowledge space (F034) and the task-mode
 * chat input.
 *
 * Both surfaces need the same two primitives: turn a *dropped* directory into a
 * flat `File[]` whose entries still remember where they came from, and agree on
 * how large a folder may be. The `webkitdirectory` picker already stamps
 * `webkitRelativePath` on every File; the Entries API used for drag-and-drop does
 * not, so the reader below synthesizes one. That way a dropped folder and a
 * picked folder flow through the exact same downstream code.
 */

/** Spread onto an `<input type="file">` to turn it into a directory picker. */
export const FOLDER_INPUT_PROPS = { webkitdirectory: '', directory: '' } as Record<string, string>;

/**
 * Task-mode folder caps. Mirrored server-side in `workbench_impl.py`
 * (`_FOLDER_MAX_FILES` / `_FOLDER_MAX_TOTAL_BYTES` / `_FOLDER_MAX_DEPTH`) — these
 * exist for instant feedback before a byte is uploaded, the server-side copy is
 * the one that actually guarantees anything.
 */
export const TASK_MODE_MAX_FOLDER_FILES = 100;
export const TASK_MODE_MAX_FOLDER_TOTAL_BYTES = 500 * 1024 * 1024;
export const TASK_MODE_MAX_FOLDER_DEPTH = 10;

/** The folder-relative path of a File, or its bare name for a loose file. */
export function getFileRelativePath(file: File): string {
    return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

/** Number of DIRECTORY levels in a relative path; the file name is not a level. */
export function getFolderDepth(relativePath: string): number {
    return Math.max(relativePath.split('/').length - 1, 0);
}

/**
 * Recursively read every file under a dropped directory. Each returned File gets
 * a synthetic `webkitRelativePath` of `"<dir>/<sub>/<file>"`.
 * `readEntries` returns in batches, so it must be called repeatedly until it
 * yields an empty list.
 */
export function readFolderFilesRecursive(
    dirEntry: FileSystemDirectoryEntry,
    pathPrefix: string,
): Promise<File[]> {
    const prefix = pathPrefix ? `${pathPrefix}/${dirEntry.name}` : dirEntry.name;
    return new Promise((resolve) => {
        const reader = dirEntry.createReader();
        const collected: Promise<File[] | File | null>[] = [];
        const finish = () =>
            Promise.all(collected).then((parts) =>
                resolve(parts.flat().filter((f): f is File => f != null)),
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
                        collected.push(
                            new Promise<File | null>((res) => {
                                fileEntry.file(
                                    (f) => {
                                        try {
                                            Object.defineProperty(f, 'webkitRelativePath', {
                                                value: `${prefix}/${f.name}`,
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
                    } else if (ent.isDirectory) {
                        collected.push(
                            readFolderFilesRecursive(ent as FileSystemDirectoryEntry, prefix),
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
 * Pull the directory entries out of a drop event.
 *
 * MUST be called synchronously inside the drop handler: the `DataTransferItemList`
 * is invalidated as soon as the handler returns, though the `FileSystemEntry`
 * objects it yields stay valid for the async directory read that follows.
 */
export function extractDroppedDirectories(dataTransfer: DataTransfer | null): FileSystemDirectoryEntry[] {
    const items = dataTransfer?.items;
    if (!items || items.length === 0) return [];
    const dirs: FileSystemDirectoryEntry[] = [];
    for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.();
        if (entry?.isDirectory) {
            dirs.push(entry as FileSystemDirectoryEntry);
        }
    }
    return dirs;
}

export type FolderBatchRejection = 'count' | 'size' | 'depth';

export interface FolderBatchCheck {
    /** Set when the batch must be rejected as a whole. */
    rejection?: FolderBatchRejection;
    fileCount: number;
    totalBytes: number;
    maxDepth: number;
}

/**
 * All-or-nothing gate on a picked/dropped folder.
 *
 * Truncating to the first N files would hand the user a workspace that looks
 * complete and is not — the agent would then summarize a partial folder with
 * nobody the wiser. Rejecting the batch makes the user pick a smaller folder,
 * which is the only outcome they can actually reason about.
 */
export function checkFolderBatch(files: File[]): FolderBatchCheck {
    const totalBytes = files.reduce((sum, f) => sum + (f.size || 0), 0);
    const maxDepth = files.reduce((deepest, f) => Math.max(deepest, getFolderDepth(getFileRelativePath(f))), 0);
    const result: FolderBatchCheck = { fileCount: files.length, totalBytes, maxDepth };

    if (files.length > TASK_MODE_MAX_FOLDER_FILES) {
        result.rejection = 'count';
    } else if (totalBytes > TASK_MODE_MAX_FOLDER_TOTAL_BYTES) {
        result.rejection = 'size';
    } else if (maxDepth > TASK_MODE_MAX_FOLDER_DEPTH) {
        result.rejection = 'depth';
    }
    return result;
}
