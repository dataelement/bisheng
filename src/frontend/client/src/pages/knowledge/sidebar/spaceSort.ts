import { KnowledgeSpace, SpaceSortType } from "~/api/knowledge";

export function sortKnowledgeSpacesForSection(
    spaces: KnowledgeSpace[],
    sortBy: SpaceSortType,
): KnowledgeSpace[] {
    return [...spaces].sort((a, b) => {
        if (a.isPinned !== b.isPinned) {
            return a.isPinned ? -1 : 1;
        }
        // Preserve API / optimistic pin-recency order within the pinned block.
        if (a.isPinned && b.isPinned) {
            return 0;
        }
        if (sortBy === SpaceSortType.NAME) {
            return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
        }
        const timeA = Date.parse(a.updatedAt || "") || 0;
        const timeB = Date.parse(b.updatedAt || "") || 0;
        return timeB - timeA;
    });
}

/** Move a space to the front of its list when pinning; keep relative order otherwise. */
export function applyPinOrderToSpaceList(
    list: KnowledgeSpace[],
    spaceId: string,
    pinned: boolean,
): KnowledgeSpace[] {
    const target = list.find((space) => space.id === spaceId);
    if (!target) {
        return list;
    }
    const updated = { ...target, isPinned: pinned };
    const others = list.filter((space) => space.id !== spaceId);
    if (pinned) {
        return [updated, ...others];
    }
    const pinnedItems = others.filter((space) => space.isPinned);
    const unpinnedItems = others.filter((space) => !space.isPinned);
    return [...pinnedItems, updated, ...unpinnedItems];
}
