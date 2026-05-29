import { Checkbox } from "~/components/ui/Checkbox";
import { getResourceGrantUserGroups, getUserGroups } from "~/api/permission";
import type { ResourceType, SelectedSubject } from "~/api/permission";
import { Users, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocalize } from "~/hooks";

interface UserGroup {
  id: number;
  group_name: string;
}

interface SubjectSearchUserGroupProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  disabledIds?: number[];
  grantUserGroupsApi?: typeof getResourceGrantUserGroups;
}

export function SubjectSearchUserGroup({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
  grantUserGroupsApi,
}: SubjectSearchUserGroupProps) {
  const localize = useLocalize();
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const getGrantUserGroups = grantUserGroupsApi ?? getResourceGrantUserGroups;
    const request =
      resourceType && resourceId
        ? getGrantUserGroups(resourceType, resourceId, undefined, { signal: controller.signal })
        : getUserGroups({ signal: controller.signal });

    setLoading(true);
    request
      .then((res) => {
        if (!controller.signal.aborted) {
          setGroups(Array.isArray(res) ? res : []);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [grantUserGroupsApi, resourceId, resourceType]);

  const filtered = useMemo(() => {
    if (!keyword) return groups;
    const lower = keyword.toLowerCase();
    return groups.filter((g) => g.group_name.toLowerCase().includes(lower));
  }, [groups, keyword]);

  const selectedIds = new Set(value.map((s) => s.id));
  const disabledIdSet = new Set(disabledIds);

  const toggle = (group: UserGroup) => {
    if (disabledIdSet.has(group.id)) return;
    if (selectedIds.has(group.id)) {
      onChange(value.filter((s) => s.id !== group.id));
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
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={localize("com_permission.search_user_group")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]">
        {loading && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_ui_loading")}
          </div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_permission.empty_user_groups")}
          </div>
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
