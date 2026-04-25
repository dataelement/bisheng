import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { getUserGroups } from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
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
}

export function SubjectSearchUserGroup({
  value,
  onChange,
}: SubjectSearchUserGroupProps) {
  const localize = useLocalize();
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    setLoading(true);
    getUserGroups()
      .then((res) => setGroups(Array.isArray(res) ? res : []))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!keyword) return groups;
    const lower = keyword.toLowerCase();
    return groups.filter((g) => g.group_name.toLowerCase().includes(lower));
  }, [groups, keyword]);

  const selectedIds = new Set(value.map((s) => s.id));

  const toggle = (group: UserGroup) => {
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
              className="flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-gray-50"
              onClick={() => toggle(group)}
            >
              <Checkbox checked={selectedIds.has(group.id)} />
              <Users className="h-4 w-4 text-gray-400" />
              <span className="truncate text-sm">{group.group_name}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
