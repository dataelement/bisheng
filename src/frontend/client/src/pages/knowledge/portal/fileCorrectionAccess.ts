import { SpaceLevel, type KnowledgeFile, type KnowledgeSpace } from "~/api/knowledge";

const CORRECTION_LEVELS = new Set<SpaceLevel>([
    SpaceLevel.PUBLIC,
    SpaceLevel.DEPARTMENT,
    SpaceLevel.TEAM,
    SpaceLevel.TEAM_KS,
]);

/**
 * 阅读页是否显示「纠错」.
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
