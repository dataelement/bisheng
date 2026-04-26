import { useEffect, useMemo, useRef, useState } from "react";
import { checkPermission } from "~/api/permission";
import { useAuthContext } from "~/hooks";
import { SystemRoles } from "~/types/chat";

export const KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS = [
    "edit_space",
    "delete_space",
    "share_space",
    "manage_space_relation",
] as const;

export type KnowledgeSpaceActionPermission =
    typeof KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS[number];

const PERMISSION_RELATION: Record<KnowledgeSpaceActionPermission, string> = {
    edit_space: "can_edit",
    delete_space: "can_delete",
    share_space: "can_manage",
    manage_space_relation: "can_manage",
};

function isSystemAdmin(role?: string) {
    return role === SystemRoles.ADMIN || String(role ?? "").toLowerCase() === "admin";
}

export function hasKnowledgeSpacePermission(
    permissions: Record<string, KnowledgeSpaceActionPermission[]>,
    spaceId: string | number,
    permissionId: KnowledgeSpaceActionPermission,
): boolean {
    return permissions[String(spaceId)]?.includes(permissionId) ?? false;
}

export function useKnowledgeSpaceActionPermissions(spaceIds: string[]) {
    const { user } = useAuthContext();
    const [permissions, setPermissions] = useState<Record<string, KnowledgeSpaceActionPermission[]>>({});
    const [loading, setLoading] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const stableSpaceIds = useMemo(() => Array.from(new Set(spaceIds)).sort(), [spaceIds.join(",")]);

    useEffect(() => {
        if (!stableSpaceIds.length) {
            abortRef.current?.abort();
            setPermissions({});
            setLoading(false);
            return;
        }

        if (isSystemAdmin(user?.role)) {
            const nextPermissions: Record<string, KnowledgeSpaceActionPermission[]> = {};
            for (const id of stableSpaceIds) {
                nextPermissions[id] = [...KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS];
            }
            setPermissions(nextPermissions);
            setLoading(false);
            return;
        }

        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);

        const resolveSpacePermissions = async (
            spaceId: string,
        ): Promise<[string, KnowledgeSpaceActionPermission[]]> => {
            const allowedPermissions: KnowledgeSpaceActionPermission[] = [];
            for (const permissionId of KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS) {
                if (controller.signal.aborted) return [spaceId, allowedPermissions];
                try {
                    const res = await checkPermission(
                        "knowledge_space",
                        spaceId,
                        PERMISSION_RELATION[permissionId],
                        permissionId,
                        { signal: controller.signal },
                    );
                    if (res?.allowed) allowedPermissions.push(permissionId);
                } catch {
                    // UI gating is best-effort; backend endpoints still enforce permission ids.
                }
            }
            return [spaceId, allowedPermissions];
        };

        Promise.allSettled(stableSpaceIds.map(resolveSpacePermissions)).then((results) => {
            if (controller.signal.aborted) return;

            const nextPermissions: Record<string, KnowledgeSpaceActionPermission[]> = {};
            for (const result of results) {
                if (result.status !== "fulfilled") continue;
                const [id, ids] = result.value;
                if (ids.length) nextPermissions[id] = ids;
            }
            setPermissions(nextPermissions);
            setLoading(false);
        });

        return () => {
            controller.abort();
        };
    }, [stableSpaceIds.join(","), user?.role]);

    return { permissions, loading };
}
