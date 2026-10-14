import { useEffect, useMemo, useState } from "react";
import {
  getCreationDepartmentChildren,
  getCreationUserGroups,
  getCreationUserTreeChildren,
  getResourcePendingInvites,
  searchCreationDepartments,
  searchCreationUserTree,
  type PendingInviteItem,
} from "~/api/permission";
import type { PermissionDraftSearchApi } from "~/components/permission/PermissionDraftPickerDialog";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

export function useKnowledgeSpacePermissionPicker(
  mode: "create" | "edit",
  spaceId: string | undefined,
  permissionRows: PermissionDraftRow[],
) {
  // Pending users hold no permission until they confirm; load them separately.
  const [pendingInvites, setPendingInvites] = useState<PendingInviteItem[]>([]);
  useEffect(() => {
    if (!spaceId) {
      setPendingInvites([]);
      return;
    }
    let cancelled = false;
    void getResourcePendingInvites("knowledge_space", spaceId)
      .then((items) => {
        if (!cancelled) setPendingInvites(items);
      })
      // Confirmation-disabled tenants have no list, so preserve the empty fallback.
      .catch(() => {
        if (!cancelled) setPendingInvites([]);
      });
    return () => {
      cancelled = true;
    };
  }, [spaceId, permissionRows]);

  const permissionSearchApi = useMemo<PermissionDraftSearchApi | undefined>(
    () =>
      mode === "create"
        ? {
            userTreeChildrenApi: (_type, _id, parentId, params, config) =>
              getCreationUserTreeChildren(
                "knowledge_space",
                parentId,
                params,
                config,
              ),
            userTreeSearchApi: (_type, _id, keyword, limit, config) =>
              searchCreationUserTree("knowledge_space", keyword, limit, config),
            departmentChildrenApi: (_type, _id, parentId, config) =>
              getCreationDepartmentChildren(
                "knowledge_space",
                parentId,
                config,
              ),
            departmentSearchApi: (_type, _id, keyword, limit, config) =>
              searchCreationDepartments(
                "knowledge_space",
                keyword,
                limit,
                config,
              ),
            userGroupsApi: (_type, _id, config) =>
              getCreationUserGroups("knowledge_space", config),
          }
        : undefined,
    [mode],
  );
  return { pendingInvites, permissionSearchApi };
}
