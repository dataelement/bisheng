import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

/**
 * F040: per-space action permissions are resolved LAZILY — instead of probing every
 * sidebar space's edit/delete/share/manage permission on mount (N spaces x 4 checks =
 * dozens of `permissions/check` on page load), `ensureSpacePermissions(spaceId)` is
 * called when the user opens a space's "⋯" menu, checking only that one space. The
 * `permissions` map starts empty and fills on demand; menu items gate on it (fail-closed
 * until resolved). System admins short-circuit to all-granted without any request.
 */
export function useKnowledgeSpaceActionPermissions(spaceIds: string[]) {
    const { user } = useAuthContext();
    const [permissions, setPermissions] = useState<Record<string, KnowledgeSpaceActionPermission[]>>({});
    const checkedRef = useRef<Set<string>>(new Set());
    const admin = isSystemAdmin(user?.role);
    // Reset key: when the listed spaces or the role change, drop resolved grants so a
    // re-opened menu re-checks against the new context.
    const resetKey = useMemo(() => Array.from(new Set(spaceIds)).sort().join(","), [spaceIds.join(",")]);

    useEffect(() => {
        checkedRef.current = new Set();
        setPermissions({});
    }, [resetKey, user?.role]);

    const ensureSpacePermissions = useCallback(
        async (spaceId: string | number) => {
            const id = String(spaceId);
            if (checkedRef.current.has(id)) return; // already resolved for this space
            checkedRef.current.add(id);

            if (admin) {
                setPermissions((prev) => ({ ...prev, [id]: [...KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS] }));
                return;
            }

            const allowed: KnowledgeSpaceActionPermission[] = [];
            for (const permissionId of KNOWLEDGE_SPACE_ACTION_PERMISSION_IDS) {
                try {
                    const res = await checkPermission(
                        "knowledge_space",
                        id,
                        PERMISSION_RELATION[permissionId],
                        permissionId,
                    );
                    if (res?.allowed) allowed.push(permissionId);
                } catch {
                    // UI gating is best-effort; backend endpoints still enforce permission ids.
                }
            }
            setPermissions((prev) => ({ ...prev, [id]: allowed }));
        },
        [admin],
    );

    return { permissions, ensureSpacePermissions };
}
