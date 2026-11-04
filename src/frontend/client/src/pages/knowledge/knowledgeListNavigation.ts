export type KnowledgeListTab = "department" | "created" | "joined";

/** The list tab is navigation state, so it survives list unmounts and history traversal. */
export function getKnowledgeListTab(search: string): KnowledgeListTab {
    const tab = new URLSearchParams(search).get("tab");
    return tab === "created" || tab === "joined" ? tab : "department";
}

/** Carry only the list selection into a new knowledge route. */
export function knowledgePathWithTab(pathname: string, search: string): string {
    const tab = new URLSearchParams(search).get("tab");
    if (tab === "department" || tab === "created" || tab === "joined") {
        return `${pathname}?tab=${tab}`;
    }
    return pathname;
}
