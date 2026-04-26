import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
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
}

export function SubjectSearchUserGroup({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
}: SubjectSearchUserGroupProps) {
  const localize = useLocalize();
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const request =
      resourceType && resourceId
        ? getResourceGrantUserGroups(resourceType, resourceId, undefined, { signal: controller.signal })
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
  }, [resourceId, resourceType]);

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
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="relative shrink-0">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
        <Input
          placeholder={localize("com_permission.search_user_group")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 pl-8"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
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
          filtered.map((group) => (
            <div
              key={group.id}
              className={`flex items-center gap-2 px-3 py-2 ${
                disabledIdSet.has(group.id)
                  ? "cursor-not-allowed opacity-60"
                  : "cursor-pointer hover:bg-gray-50"
              }`}
              onClick={() => toggle(group)}
            >
              <Checkbox
                checked={selectedIds.has(group.id) || disabledIdSet.has(group.id)}
                disabled={disabledIdSet.has(group.id)}
              />
              <Users className="h-4 w-4 text-gray-400" />
              <span className="truncate text-sm">{group.group_name}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
