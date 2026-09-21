import type { SpaceLevel } from "~/api/knowledge";

export function shouldShowFileEntryBadge(
    entryType: string | undefined,
    spaceLevel?: SpaceLevel,
    entryStatus?: string,
): boolean {
    if (!entryType || entryType === "normal") return false;
    // 个人库的内部管理身份不展示，但保留失效提示。
    return entryType !== "manager" || spaceLevel !== "personal" || entryStatus === "invalid";
}
