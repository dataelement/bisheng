import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getMyResourcePermissions } from "~/api/permission";

export const KNOWLEDGE_SPACE_ACTIONS = [
    "edit",
    "delete",
    "share",
    "manage_permission",
] as const;

export type KnowledgeSpaceAction = typeof KNOWLEDGE_SPACE_ACTIONS[number];

export function hasKnowledgeSpaceAction(
    actions: Record<string, KnowledgeSpaceAction[]>,
    spaceId: string | number,
    action: KnowledgeSpaceAction,
): boolean {
    return actions[String(spaceId)]?.includes(action) ?? false;
}

/**
 * Per-space actions are resolved lazily with one F048 my-permissions summary.
 * The map starts empty and remains fail-closed until the selected space resolves.
 */
export function useKnowledgeSpaceActions(spaceIds: string[]) {
    const [actions, setActions] = useState<Record<string, KnowledgeSpaceAction[]>>({});
    const checkedRef = useRef<Set<string>>(new Set());
    const resetKey = useMemo(() => Array.from(new Set(spaceIds)).sort().join(","), [spaceIds.join(",")]);

    useEffect(() => {
        checkedRef.current = new Set();
        setActions({});
    }, [resetKey]);

    const ensureSpacePermissions = useCallback(
        async (spaceId: string | number) => {
            const id = String(spaceId);
            if (checkedRef.current.has(id)) return; // already resolved for this space
            checkedRef.current.add(id);

            try {
                const summary = await getMyResourcePermissions("knowledge_space", id);
                const allowed = KNOWLEDGE_SPACE_ACTIONS.filter((action) =>
                    summary.actions.includes(action),
                );
                setActions((prev) => ({ ...prev, [id]: allowed }));
            } catch {
                // Fail closed, but allow a later menu open to retry.
                checkedRef.current.delete(id);
            }
        },
        [],
    );

    return { actions, ensureSpaceActions: ensureSpacePermissions };
}
