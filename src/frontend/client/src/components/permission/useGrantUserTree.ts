import { useCallback, useEffect, useRef, useState } from "react";

import type {
  GrantDepartmentNode,
  GrantDepartmentSearchResult,
  GrantUser,
  GrantUserTreeChildrenResult,
} from "~/api/permission";

/**
 * F038: department-tree user picker. Departments are pure navigation (lazy
 * per-layer browse, like `useGrantDepartmentTree`); users are leaves attached
 * to the department they were fetched under. Browsing keeps a normalized
 * department model + a per-department user page (loaded on first expand,
 * paged further via `loadMoreUsers`); search renders the backend's pruned
 * tree directly, with each matched user already attached to its primary
 * department node. Plain state (no react-query) — the picker is dialog-scoped.
 */

const ROOT_KEY = -1;
const SEARCH_DEBOUNCE_MS = 300;

export interface GrantUserTreeSource {
  fetchChildren: (
    parentId: number | null,
    userPage: number,
    signal?: AbortSignal,
  ) => Promise<GrantUserTreeChildrenResult>;
  fetchSearch: (keyword: string, signal?: AbortSignal) => Promise<GrantDepartmentSearchResult>;
}

export interface GrantUserTree {
  rootIds: number[];
  getNode: (id: number) => GrantDepartmentNode | undefined;
  getChildIds: (id: number) => number[] | undefined;
  getUsers: (departmentId: number) => GrantUser[];
  hasMoreUsers: (departmentId: number) => boolean;
  loadingMoreUserIds: Set<number>;
  failedLayerIds: Set<number>;
  failedMoreUserIds: Set<number>;
  loadMoreUsers: (departmentId: number) => void;
  retryLayer: (departmentId: number) => void;
  retryMoreUsers: (departmentId: number) => void;
  expanded: Set<number>;
  loadingIds: Set<number>;
  initialLoading: boolean;
  rootError: boolean;
  /** Expand/collapse a department, loading its child layer + first user page on first expand. */
  toggle: (node: GrantDepartmentNode) => void;
  keyword: string;
  setKeyword: (kw: string) => void;
  searchMode: boolean;
  searchRoots: GrantDepartmentNode[];
  searching: boolean;
  searchError: boolean;
  retryRoot: () => void;
  retrySearch: () => void;
  truncated: boolean;
}

export function useGrantUserTree(source: GrantUserTreeSource): GrantUserTree {
  const sourceRef = useRef(source);
  sourceRef.current = source;

  const [nodeMap, setNodeMap] = useState<Record<number, GrantDepartmentNode>>({});
  const [childIds, setChildIds] = useState<Record<number, number[]>>({});
  const [usersByDept, setUsersByDept] = useState<Record<number, GrantUser[]>>({});
  const [hasMoreUsersByDept, setHasMoreUsersByDept] = useState<Record<number, boolean>>({});
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());
  const [loadingMoreUserIds, setLoadingMoreUserIds] = useState<Set<number>>(new Set());
  const [initialLoading, setInitialLoading] = useState(true);
  const [rootError, setRootError] = useState(false);
  const [failedLayerIds, setFailedLayerIds] = useState<Set<number>>(new Set());
  const [failedMoreUserIds, setFailedMoreUserIds] = useState<Set<number>>(new Set());
  const [keyword, setKeyword] = useState("");
  const [searchResult, setSearchResult] = useState<GrantDepartmentSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const [searchAttempt, setSearchAttempt] = useState(0);
  const [rootAttempt, setRootAttempt] = useState(0);

  const childIdsRef = useRef(childIds);
  childIdsRef.current = childIds;
  // Synced refs mirror the department tree hook's idiom: React state updates
  // are async, so a fast double-toggle/double-click could otherwise queue a
  // duplicate request while the first is still resolving.
  const userPageRef = useRef<Record<number, number>>({});
  const hasMoreUsersRef = useRef<Record<number, boolean>>({});
  hasMoreUsersRef.current = hasMoreUsersByDept;
  const loadingMoreUserIdsRef = useRef<Set<number>>(new Set());
  const searchRequestRef = useRef(0);

  const storeLayer = useCallback((parentId: number | null, layer: GrantUserTreeChildrenResult) => {
    const key = parentId ?? ROOT_KEY;
    setNodeMap((prev) => {
      const next = { ...prev };
      for (const n of layer.departments) next[n.id] = { ...n, children: [] };
      return next;
    });
    setChildIds((prev) => ({ ...prev, [key]: layer.departments.map((n) => n.id) }));
    if (parentId !== null) {
      setUsersByDept((prev) => ({ ...prev, [parentId]: layer.users }));
      setHasMoreUsersByDept((prev) => ({ ...prev, [parentId]: layer.has_more_users }));
      userPageRef.current[parentId] = 1;
    }
  }, []);

  const loadLayer = useCallback(
    async (parentId: number | null) => {
      const key = parentId ?? ROOT_KEY;
      if (childIdsRef.current[key]) return;
      if (parentId !== null) setLoadingIds((prev) => new Set(prev).add(parentId));
      try {
        const layer = await sourceRef.current.fetchChildren(parentId, 1);
        if (layer) storeLayer(parentId, layer);
        if (parentId !== null) {
          setFailedLayerIds((prev) => {
            const next = new Set(prev);
            next.delete(parentId);
            return next;
          });
        }
      } catch {
        if (parentId !== null) setFailedLayerIds((prev) => new Set(prev).add(parentId));
      } finally {
        if (parentId !== null) {
          setLoadingIds((prev) => {
            const next = new Set(prev);
            next.delete(parentId);
            return next;
          });
        }
      }
    },
    [storeLayer]
  );

  const toggle = useCallback(
    (node: GrantDepartmentNode) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(node.id)) {
          next.delete(node.id);
        } else {
          next.add(node.id);
          void loadLayer(node.id);
        }
        return next;
      });
    },
    [loadLayer]
  );

  const loadMoreUsers = useCallback((departmentId: number) => {
    if (loadingMoreUserIdsRef.current.has(departmentId)) return;
    if (!hasMoreUsersRef.current[departmentId]) return;
    loadingMoreUserIdsRef.current.add(departmentId);
    setLoadingMoreUserIds(new Set(loadingMoreUserIdsRef.current));
    const nextPage = (userPageRef.current[departmentId] ?? 1) + 1;
    sourceRef.current
      .fetchChildren(departmentId, nextPage)
      .then((layer) => {
        setUsersByDept((prev) => {
          const existing = prev[departmentId] ?? [];
          const seen = new Set(existing.map((u) => u.user_id));
          const additions = layer.users.filter((u) => !seen.has(u.user_id));
          return { ...prev, [departmentId]: [...existing, ...additions] };
        });
        setHasMoreUsersByDept((prev) => ({ ...prev, [departmentId]: layer.has_more_users }));
        userPageRef.current[departmentId] = nextPage;
        setFailedMoreUserIds((prev) => {
          const next = new Set(prev);
          next.delete(departmentId);
          return next;
        });
      })
      .catch(() => {
        setFailedMoreUserIds((prev) => new Set(prev).add(departmentId));
      })
      .finally(() => {
        loadingMoreUserIdsRef.current.delete(departmentId);
        setLoadingMoreUserIds(new Set(loadingMoreUserIdsRef.current));
      });
  }, []);

  const retryLayer = useCallback((departmentId: number) => {
    void loadLayer(departmentId);
  }, [loadLayer]);

  const retryMoreUsers = useCallback((departmentId: number) => {
    loadMoreUsers(departmentId);
  }, [loadMoreUsers]);

  const getNode = useCallback((id: number) => nodeMap[id], [nodeMap]);
  const getChildIds = useCallback((id: number) => childIds[id], [childIds]);
  const getUsers = useCallback((departmentId: number) => usersByDept[departmentId] ?? [], [usersByDept]);
  const hasMoreUsers = useCallback(
    (departmentId: number) => !!hasMoreUsersByDept[departmentId],
    [hasMoreUsersByDept]
  );

  // Root layer on mount.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setInitialLoading(true);
    setRootError(false);
    sourceRef.current
      .fetchChildren(null, 1, controller.signal)
      .then((layer) => {
        if (!cancelled && layer) storeLayer(null, layer);
      })
      .catch(() => {
        if (!cancelled && !controller.signal.aborted) setRootError(true);
      })
      .finally(() => {
        if (!cancelled) setInitialLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [rootAttempt, storeLayer]);

  // Debounced server-side search.
  useEffect(() => {
    const kw = keyword.trim();
    const requestId = searchRequestRef.current + 1;
    searchRequestRef.current = requestId;
    if (!kw) {
      setSearchResult(null);
      setSearching(false);
      setSearchError(false);
      return;
    }
    setSearching(true);
    setSearchError(false);
    setSearchResult(null);
    const controller = new AbortController();
    let cancelled = false;
    const timer = window.setTimeout(() => {
      sourceRef.current
        .fetchSearch(kw, controller.signal)
        .then((res) => {
          if (!cancelled && searchRequestRef.current === requestId) setSearchResult(res ?? null);
        })
        .catch(() => {
          if (!cancelled && !controller.signal.aborted && searchRequestRef.current === requestId) {
            setSearchError(true);
          }
        })
        .finally(() => {
          if (!cancelled && searchRequestRef.current === requestId) setSearching(false);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [keyword, searchAttempt]);

  const retryRoot = useCallback(() => setRootAttempt((attempt) => attempt + 1), []);
  const retrySearch = useCallback(() => setSearchAttempt((attempt) => attempt + 1), []);

  return {
    rootIds: childIds[ROOT_KEY] ?? [],
    getNode,
    getChildIds,
    getUsers,
    hasMoreUsers,
    loadingMoreUserIds,
    failedLayerIds,
    failedMoreUserIds,
    loadMoreUsers,
    retryLayer,
    retryMoreUsers,
    expanded,
    loadingIds,
    initialLoading,
    rootError,
    toggle,
    keyword,
    setKeyword,
    searchMode: !!keyword.trim(),
    searchRoots: searchResult?.roots ?? [],
    searching,
    searchError,
    retryRoot,
    retrySearch,
    truncated: searchResult?.truncated ?? false,
  };
}
