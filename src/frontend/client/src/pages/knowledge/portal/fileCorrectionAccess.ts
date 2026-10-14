import { SpaceLevel, type KnowledgeFile, type KnowledgeSpace } from "~/api/knowledge";

const CORRECTION_LEVELS = new Set<SpaceLevel>([
    SpaceLevel.PUBLIC,
    SpaceLevel.DEPARTMENT,
    SpaceLevel.TEAM,
    SpaceLevel.TEAM_KS,
]);

/**
 * 右侧边栏是否显示纠错入口.
 * 能看这篇文档的人都能打开列表, 包括上传人.
 */
export function canOpenFileCorrection(input: {
    space: Pick<KnowledgeSpace, "spaceLevel" | "isFavorite"> | null | undefined;
    file: Pick<KnowledgeFile, "uploaderUserId"> | null | undefined;
}): boolean {
    const { space, file } = input;
    if (!space || !file || space.isFavorite) return false;
    return CORRECTION_LEVELS.has(space.spaceLevel);
}

/**
 * 右侧边栏是否显示发起纠错按钮.
 * 看当前打开文件所属库, 不看从哪个列表进来.
 */
export function canSubmitFileCorrection(input: {
    space: Pick<KnowledgeSpace, "spaceLevel" | "isFavorite"> | null | undefined;
    file: Pick<KnowledgeFile, "uploaderUserId"> | null | undefined;
    currentUserId: string | number | null | undefined;
}): boolean {
    const { space, file } = input;
    if (!space || !file || space.isFavorite) return false;
    if (!CORRECTION_LEVELS.has(space.spaceLevel)) return false;
    if (file.uploaderUserId == null) return true;
    return String(input.currentUserId ?? "") !== String(file.uploaderUserId);
}
