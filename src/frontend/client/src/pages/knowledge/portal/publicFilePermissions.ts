export interface PublicFileActionPermissions {
    permissionEntryIds: Set<string>;
    renameEntryIds: Set<string>;
    deleteEntryIds: Set<string>;
    downloadEntryIds: Set<string>;
    moveEntryIds: Set<string>;
}

export function buildPublicFileActionPermissions(
    permissionIdsByFileId: Record<string, string[]>,
    grantAllEntryIds?: readonly string[],
): PublicFileActionPermissions {
    const idsWithPermission = (...permissionIds: string[]) => new Set(
        grantAllEntryIds
            ?? Object.entries(permissionIdsByFileId)
                .filter(([, resolvedIds]) => permissionIds.some((permissionId) => resolvedIds.includes(permissionId)))
                .map(([fileId]) => fileId),
    );

    return {
        permissionEntryIds: idsWithPermission("manage_file_relation", "manage_folder_relation"),
        renameEntryIds: idsWithPermission("rename_file", "rename_folder"),
        deleteEntryIds: idsWithPermission("delete_file", "delete_folder"),
        downloadEntryIds: idsWithPermission("download_file", "download_folder"),
        moveEntryIds: idsWithPermission("move_file", "move_folder"),
    };
}
