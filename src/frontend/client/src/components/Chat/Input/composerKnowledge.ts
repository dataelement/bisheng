/** A configured knowledge base as the workbench config sends it (F005). */
export interface ConfiguredKnowledge {
    id: string | number;
    name: string;
    show_in_composer?: boolean;
}

/**
 * A new chat starts with every configured knowledge base the user can see
 * (the server already dropped the rest), unless the knowledge-base feature is off.
 */
export function configuredKnowledgeDefaults(
    config: { orgKbs?: ConfiguredKnowledge[]; knowledgeBase?: { enabled?: boolean } } | undefined,
): Array<{ id: string; name: string; type: 'org' }> {
    if (config?.knowledgeBase?.enabled === false) return [];
    return (config?.orgKbs ?? []).map((kb) => ({ id: String(kb.id), name: kb.name, type: 'org' }));
}

interface Selection {
    id: string | number;
    type?: string;
}

/**
 * Split the selected knowledge bases into the ones the composer shows as tags and
 * the configured ones the admin hid from it. Hidden ones stay selected and are sent;
 * they still appear checked in the "+" menu. The rule comes from the current config
 * only, so the stored selection never carries a display flag (design decision 10).
 * Configured defaults are seeded with type `org`, so only `org` entries can be hidden.
 */
export function splitComposerKnowledge<T extends Selection>(
    selected: T[],
    configured: ConfiguredKnowledge[] | undefined,
): { visible: T[]; hidden: T[] } {
    const hiddenIds = new Set(
        (configured ?? []).filter((kb) => kb.show_in_composer === false).map((kb) => String(kb.id)),
    );
    if (!hiddenIds.size) return { visible: selected, hidden: [] };
    const visible: T[] = [];
    const hidden: T[] = [];
    selected.forEach((item) => {
        (item.type === 'org' && hiddenIds.has(String(item.id)) ? hidden : visible).push(item);
    });
    return { visible, hidden };
}
