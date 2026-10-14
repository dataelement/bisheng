import type { ShougangFilePublishLastTarget, ShougangFilePublishTargetSpace } from "~/api/approval";
import type { SpaceFolderTreeState, TargetFolderLoader, TargetFolderNode } from "./FilePublishTargetTree";

export interface RestoredPublishTarget {
    spaceId: string;
    folderId: string | null;
    folderTrees?: Record<string, SpaceFolderTreeState>;
    notice?: string;
}

export async function restoreFilePublishTarget(
    preference: ShougangFilePublishLastTarget,
    spaces: ShougangFilePublishTargetSpace[],
    loadFolders: TargetFolderLoader,
    isCancelled: () => boolean,
): Promise<RestoredPublishTarget | null> {
    const remembered = spaces.find((space) => String(space.id) === String(preference.target_space_id));
    const result: RestoredPublishTarget = {
        spaceId: String(remembered?.id ?? spaces[0]?.id ?? ""),
        folderId: null,
    };
    if (preference.fallback_reason === "preference_unavailable") {
        result.notice = "上次发布路径加载失败，请确认发布位置";
    } else if (preference.fallback_reason === "target_unavailable" || (preference.target_space_id && !remembered)) {
        result.notice = "上次发布的目标库已不可用，请重新选择发布位置";
    } else if (preference.fallback_reason === "folder_unavailable") {
        result.notice = "上次发布的目录已不可用，已选择目标库根目录";
    }
    if (!remembered || !preference.target_folder_id) return result;
    const path = (preference.folder_path ?? []).map(String);
    if (!path.length || path[path.length - 1] !== String(preference.target_folder_id) || new Set(path).size !== path.length) {
        result.notice = "上次发布的目录已不可用，已选择目标库根目录";
        return result;
    }
    let parentId: string | null = null;
    let siblings: TargetFolderNode[] = [];
    let ancestor: TargetFolderNode | undefined;
    const roots: TargetFolderNode[] = [];
    try {
        for (const folderId of path) {
            if (isCancelled()) return null;
            const items = await loadFolders(result.spaceId, parentId);
            if (isCancelled()) return null;
            siblings = items.map((item) => ({
                id: String(item.id), name: String(item.name ?? item.file_name ?? ""),
                children: [], expanded: false, loading: false, loaded: false,
            }));
            const selected = siblings.find((item) => item.id === folderId);
            if (!selected) throw new Error("remembered_folder_not_found");
            if (ancestor) {
                ancestor.children = siblings;
                ancestor.expanded = true;
                ancestor.loaded = true;
            } else {
                roots.push(...siblings);
            }
            ancestor = selected;
            parentId = folderId;
        }
        result.folderId = String(preference.target_folder_id);
        result.folderTrees = {
            [result.spaceId]: { expanded: true, loading: false, loaded: true, folders: roots },
        };
    } catch {
        // 偏好恢复失败仍可手动选择，只降级到已验证目标库的根目录。
        result.notice = "上次发布目录恢复失败，已选择目标库根目录，请确认发布位置";
    }
    return result;
}
