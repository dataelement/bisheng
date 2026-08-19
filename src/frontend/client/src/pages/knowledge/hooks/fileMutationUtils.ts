import type {
    FileBatchMutationResult,
    FileMutationResult,
    InvalidEntry,
    KnowledgeFile,
    MovedEntry,
    MoveResult,
} from "~/api/knowledge";
export {
    dispatchFileChangeApprovalRefresh,
    FILE_CHANGE_APPROVAL_REFRESH_EVENT,
} from "~/events/fileChangeApprovalEvents";

export function isFileChangeMutationLocked(file: KnowledgeFile): boolean {
    return Boolean(file.fileChangeApproval);
}

export function applyRenameDecision(
    files: KnowledgeFile[],
    fileId: string,
    requestedName: string,
    result: FileMutationResult,
): KnowledgeFile[] {
    if (result.decision !== "direct") return files;
    const resolvedName = result.resource?.name || requestedName;
    return files.map((file) => file.id === fileId ? { ...file, name: resolvedName } : file);
}

export function applyDeleteDecision(
    files: KnowledgeFile[],
    fileId: string,
    result: FileMutationResult,
): KnowledgeFile[] {
    return result.decision === "direct" ? files.filter((file) => file.id !== fileId) : files;
}

export function applyBatchDeleteDecision(
    files: KnowledgeFile[],
    result: FileBatchMutationResult,
): KnowledgeFile[] {
    const deletedIds = new Set(result.completed.map((item) => String(item.id)));
    return deletedIds.size > 0 ? files.filter((file) => !deletedIds.has(file.id)) : files;
}

export function applyBatchRenameDecision(
    files: KnowledgeFile[],
    requestedNames: ReadonlyMap<string, string>,
    result: FileBatchMutationResult,
): KnowledgeFile[] {
    const renamed = new Map(result.completed.map((item) => [
        String(item.id),
        item.resource?.name || requestedNames.get(String(item.id)),
    ]));
    return renamed.size > 0
        ? files.map((file) => {
            const name = renamed.get(file.id);
            return name ? { ...file, name } : file;
        })
        : files;
}

export function buildDirectMoveUndoEntries(
    moved: MovedEntry[],
    sourceItems: KnowledgeFile[],
    crossSpace: boolean,
): MovedEntry[] {
    if (crossSpace) return [];
    const sourceById = new Map(sourceItems.map((item) => [String(item.id), item]));
    return moved.map((entry) => {
        const source = sourceById.get(String(entry.id));
        return {
            ...entry,
            old_parent_id: entry.old_parent_id !== undefined
                ? entry.old_parent_id
                : source?.parentId != null ? Number(source.parentId) : null,
            cross_space: entry.cross_space ?? false,
        };
    });
}

/** Old F034 rejected the whole request before skip_invalid; F046 commits each item independently. */
export function shouldRetryLegacyPartialMove(result: MoveResult): boolean {
    return result.moved.length === 0
        && result.pending.length === 0
        && result.invalid.length > 0
        && result.invalid.every((item: InvalidEntry) => Boolean(item.reason));
}
