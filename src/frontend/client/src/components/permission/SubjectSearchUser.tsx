import { Checkbox } from "~/components/ui/Checkbox";
import { getResourceGrantUsers, searchUsers } from "~/api/permission";
import type { ResourceType, SelectedSubject } from "~/api/permission";
import { User as UserIcon, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocalize } from "~/hooks";

interface SubjectSearchUserProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  disabledIds?: number[];
  grantUsersApi?: typeof getResourceGrantUsers;
}

type UserRow = { user_id: number; user_name: string };

const PAGE_SIZE = 50;

export function SubjectSearchUser({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
  grantUsersApi,
}: SubjectSearchUserProps) {
  const localize = useLocalize();
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<UserRow[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Latest keyword captured for the in-flight fetch chain — guards against
  // races where a new search starts while an older page is still resolving.
  const activeKeywordRef = useRef("");
  // IntersectionObserver can fire several `isIntersecting` callbacks while a
  // page is still in flight; React state updates are async, so a `useState`
  // gate isn't tight enough. The refs below are written synchronously, which
  // closes that race and keeps loadNext idempotent.
  const pageRef = useRef(1);
  const hasMoreRef = useRef(true);
  const loadingRef = useRef(false);
  const loadingMoreRef = useRef(false);

  const fetchPage = useCallback(
    async (
      name: string,
      pageNum: number,
      signal: AbortSignal,
    ): Promise<UserRow[]> => {
      if (resourceType && resourceId) {
        const getGrantUsers = grantUsersApi ?? getResourceGrantUsers;
        const rows = await getGrantUsers(
          resourceType,
          resourceId,
          { keyword: name, page: pageNum, page_size: PAGE_SIZE },
          { signal },
        );
        if (signal.aborted) return [];
        return Array.isArray(rows) ? rows : [];
      }
      const res = await searchUsers(
        name,
        { page: pageNum, pageSize: PAGE_SIZE },
        { signal },
      );
      if (signal.aborted) return [];
      return res.data || [];
    },
    [grantUsersApi, resourceId, resourceType],
  );

  const resetAndLoad = useCallback(
    async (name: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      activeKeywordRef.current = name;

      loadingRef.current = true;
      pageRef.current = 1;
      hasMoreRef.current = true;
      setLoading(true);
      setResults([]);
      setHasMore(true);
      try {
        const rows = await fetchPage(name, 1, controller.signal);
        if (controller.signal.aborted || activeKeywordRef.current !== name) return;
        setResults(rows);
        // Backend `_list_knowledge_space_grant_users` filters soft-deleted
        // users AFTER paginating, so a page may legitimately return fewer
        // than PAGE_SIZE rows while more pages still exist. Treat any
        // non-empty response as "keep trying" — only stop when a fetch
        // returns zero.
        hasMoreRef.current = rows.length > 0;
        setHasMore(hasMoreRef.current);
      } catch {
        // ignore
      } finally {
        if (!controller.signal.aborted) {
          loadingRef.current = false;
          setLoading(false);
        }
      }
    },
    [fetchPage],
  );

  const loadNext = useCallback(async () => {
    // Sync gate: refs flip synchronously so back-to-back observer fires can't
    // queue duplicate page requests while an earlier one is still resolving.
    if (loadingMoreRef.current || loadingRef.current || !hasMoreRef.current) return;
    const controller = abortRef.current;
    if (!controller || controller.signal.aborted) return;
    const name = activeKeywordRef.current;
    const nextPage = pageRef.current + 1;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const rows = await fetchPage(name, nextPage, controller.signal);
      if (controller.signal.aborted || activeKeywordRef.current !== name) return;
      setResults((prev) => {
        const seen = new Set(prev.map((r) => r.user_id));
        const additions = rows.filter((r) => !seen.has(r.user_id));
        return [...prev, ...additions];
      });
      pageRef.current = nextPage;
      hasMoreRef.current = rows.length > 0;
      setHasMore(hasMoreRef.current);
    } catch {
      // ignore
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [fetchPage]);

  useEffect(() => {
    resetAndLoad("");
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, [resetAndLoad]);

  // Infinite-scroll sentinel: callback ref rebinds observer cleanly when
  // sentinel mounts/unmounts (e.g., across loading state flips), so we don't
  // chase stale DOM nodes through useEffect deps. The 100px rootMargin
  // pre-fetches just before the user hits the bottom for a smoother feel.
  const observerRef = useRef<IntersectionObserver | null>(null);
  const sentinelCallback = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    const root = scrollRef.current;
    if (!node || !root) return;
    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadNext();
      },
      { root, rootMargin: "100px" },
    );
    observerRef.current.observe(node);
  }, [loadNext]);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setKeyword(val);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => resetAndLoad(val), 300);
  };

  const selectedIds = new Set(value.map((s) => s.id));
  const disabledIdSet = new Set(disabledIds);

  const toggle = (user: UserRow) => {
    if (disabledIdSet.has(user.user_id)) return;
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
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={localize("com_permission.search_user")}
          value={keyword}
          onChange={handleInput}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]"
      >
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
          results.map((user) => {
            const isDisabled = disabledIdSet.has(user.user_id);
            return (
              <div
                key={user.user_id}
                className={`flex items-center gap-2 px-3 py-2 ${
                  isDisabled
                    ? "cursor-not-allowed opacity-60"
                    : "cursor-pointer hover:bg-gray-50"
                }`}
                onClick={() => toggle(user)}
              >
                <Checkbox
                  className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                  checked={selectedIds.has(user.user_id)}
                  disabled={isDisabled}
                />
                <UserIcon className="h-4 w-4 text-gray-400" />
                <span className="min-w-0 flex-1 truncate text-sm">{user.user_name}</span>
                {isDisabled && (
                  <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                    {localize("com_permission.already_granted")}
                  </span>
                )}
              </div>
            );
          })}
        {!loading && hasMore && (
          <div ref={sentinelCallback} className="py-2 text-center text-xs text-gray-500">
            {loadingMore ? localize("com_ui_loading") : ""}
          </div>
        )}
      </div>
    </div>
  );
}
