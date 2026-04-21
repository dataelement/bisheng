import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { searchUsers } from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
import { User as UserIcon, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocalize } from "~/hooks";

interface SubjectSearchUserProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
}

export function SubjectSearchUser({ value, onChange }: SubjectSearchUserProps) {
  const localize = useLocalize();
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<
    { user_id: number; user_name: string }[]
  >([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const search = useCallback(async (name: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    try {
      const res = await searchUsers(name, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setResults(res.data || []);
      }
    } catch {
      // ignore
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    search("");
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, [search]);

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setKeyword(val);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(val), 300);
  };

  const selectedIds = new Set(value.map((s) => s.id));

  const toggle = (user: { user_id: number; user_name: string }) => {
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((s) => s.id !== user.user_id));
    } else {
      onChange([
        ...value,
        { type: "user", id: user.user_id, name: user.user_name },
      ]);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400" />
        <Input
          placeholder={localize("com_permission.search_user")}
          value={keyword}
          onChange={handleInput}
          className="pl-8"
        />
      </div>
      <div className="max-h-[min(320px,50vh)] min-h-[120px] overflow-y-auto rounded-md border">
        {loading && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_ui_loading")}
          </div>
        )}
        {!loading && results.length === 0 && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_permission.empty_search")}
          </div>
        )}
        {!loading &&
          results.map((user) => (
            <div
              key={user.user_id}
              className="flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-gray-50"
              onClick={() => toggle(user)}
            >
              <Checkbox checked={selectedIds.has(user.user_id)} />
              <UserIcon className="h-4 w-4 text-gray-400" />
              <span className="truncate text-sm">{user.user_name}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
