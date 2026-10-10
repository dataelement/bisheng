export type PortalScopeFileCount =
    | { kind: "file"; name: string; count: 0 }
    | { kind: "folder"; name: string; folderId: string; count: number | null }
    | { kind: "space"; name: string; spaceId: string; count: null };

interface PortalScopeFolder {
    id: string;
    name: string;
    fileNum?: number;
}

interface PortalScopeFile {
    name: string;
}

interface PortalScopeSpace {
    id: string;
    name: string;
}

/**
 * Decide which container the corner count describes.
 * The number itself is the direct file count of that directory, not files inside child folders.
 */
export function resolvePortalScopeFileCount(input: {
    space: PortalScopeSpace | null;
    folder: PortalScopeFolder | null;
    file: PortalScopeFile | null;
}): PortalScopeFileCount | null {
    if (input.file) {
        return { kind: "file", name: input.file.name, count: 0 };
    }
    if (input.folder) {
        return {
            kind: "folder",
            name: input.folder.name,
            folderId: input.folder.id,
            count: input.folder.fileNum === undefined ? null : input.folder.fileNum,
        };
    }
    if (input.space) {
        return { kind: "space", name: input.space.name, spaceId: input.space.id, count: null };
    }
    return null;
}

export function portalScopeFileCountLabel(kind: PortalScopeFileCount["kind"], count: number | null): string {
    const scopeLabel = kind === "space" ? "当前知识库" : kind === "folder" ? "当前文件夹" : "所选文件";
    if (count === null) return `${scopeLabel}下文件数统计中`;
    return `${scopeLabel}下 ${count} 个文件`;
}
