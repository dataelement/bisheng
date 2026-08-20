import { Checkbox } from "~/components/ui/Checkbox";
import {
  getCreationGrantSubjects,
  getResourceGrantUserGroups,
  getUserGroups,
} from "~/api/permission";
import type {
  GrantUserGroup,
  ResourceType,
  SelectedSubject,
} from "~/api/permission";
import { Users, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocalize } from "~/hooks";
import { PermissionEmptyState } from "./PermissionEmptyState";

interface SubjectSearchUserGroupProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  mode?: "create" | "resource";
  disabledIds?: number[];
  grantUserGroupsApi?: typeof getResourceGrantUserGroups;
  creationGrantSubjectsApi?: typeof getCreationGrantSubjects;
}

export function SubjectSearchUserGroup({
  value,
  onChange,
  resourceType,
  resourceId,
  mode = "resource",
  disabledIds = [],
  grantUserGroupsApi,
  creationGrantSubjectsApi,
}: SubjectSearchUserGroupProps) {
  const localize = useLocalize();
  const [groups, setGroups] = useState<GrantUserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const requestKeyword = mode === "create" ? keyword : "";

  useEffect(() => {
    const controller = new AbortController();
    const getGrantUserGroups = grantUserGroupsApi ?? getResourceGrantUserGroups;
    let request: Promise<GrantUserGroup[]>;
    if (mode === "create") {
      if (resourceType !== "knowledge_space" && resourceType !== "channel") {
        request = Promise.resolve([]);
      } else {
        const getCreationSubjects = creationGrantSubjectsApi ?? getCreationGrantSubjects;
        request = getCreationSubjects({
          resourceType,
          subjectType: "user_group",
          operation: "list",
          keyword: requestKeyword,
        }, { signal: controller.signal });
      }
    } else if (resourceType && resourceId) {
      request = getGrantUserGroups(
        resourceType,
        resourceId,
        undefined,
        { signal: controller.signal },
      );
    } else {
      request = getUserGroups({ signal: controller.signal });
    }

    setLoading(true);
    request
      .then((res) => {
        if (!controller.signal.aborted) {
          setGroups(Array.isArray(res) ? res : []);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setGroups([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [creationGrantSubjectsApi, grantUserGroupsApi, mode, requestKeyword, resourceId, resourceType]);

  const filtered = useMemo(() => {
    if (!keyword) return groups;
    const lower = keyword.toLowerCase();
    return groups.filter((g) => g.group_name.toLowerCase().includes(lower));
  }, [groups, keyword]);

  const selectedIds = new Set(value.filter((s) => s.type === "user_group").map((s) => s.id));
  const disabledIdSet = new Set(disabledIds);

  const toggle = (group: GrantUserGroup) => {
    if (disabledIdSet.has(group.id)) return;
    if (selectedIds.has(group.id)) {
      onChange(value.filter((s) => s.type !== "user_group" || s.id !== group.id));
    } else {
      onChange([
        ...value,
        { type: "user_group", id: group.id, name: group.group_name },
      ]);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-3" />
        <input
          type="text"
          placeholder={localize("com_permission.search_user_group")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 w-full rounded-md border border-border-base bg-white pl-9 pr-3 text-[14px] text-text-1 outline-none transition-colors placeholder:text-text-3 focus:border-border-deep"
        />
      </div>
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto rounded-md border border-border-base">
        {loading && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_ui_loading")}
          </div>
        )}
        {!loading && filtered.length === 0 && (
          <PermissionEmptyState message={localize("com_permission.empty_user_groups")} />
        )}
        {!loading &&
          filtered.map((group) => {
            const isDisabled = disabledIdSet.has(group.id);
            return (
              <div
                key={group.id}
                className={`flex items-center gap-2 px-3 py-2 ${
                  isDisabled
                    ? "cursor-not-allowed opacity-60"
                    : "cursor-pointer hover:bg-gray-50"
                }`}
                onClick={() => toggle(group)}
              >
                <Checkbox
                  className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                  checked={selectedIds.has(group.id)}
                  disabled={isDisabled}
                />
                <Users className="h-4 w-4 text-gray-400" />
                <span className="min-w-0 flex-1 truncate text-sm">{group.group_name}</span>
                {isDisabled && (
                  <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                    {localize("com_permission.already_granted")}
                  </span>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}
