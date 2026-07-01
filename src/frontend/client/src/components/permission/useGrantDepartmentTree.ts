import { useCallback, useEffect, useRef, useState } from "react";

import type { GrantDepartmentNode, GrantDepartmentSearchResult } from "~/api/permission";

/**
 * F038: per-layer lazy department tree for the client authorization picker.
 * Browse keeps a normalized model (node map + per-parent child ids loaded on
 * demand); search renders the backend's pruned tree directly. Permission scope
 * is decided by the backend — this hook is scope-agnostic. Unlike the platform
 * hook it uses plain state (no react-query): the picker is dialog-scoped, so
 * there is nothing long-lived to cache.
 */

const ROOT_KEY = -1;
const SEARCH_DEBOUNCE_MS = 300;

export interface GrantDepartmentTreeSource {
  fetchChildren: (parentId: number | null, signal?: AbortSignal) => Promise<GrantDepartmentNode[]>;
  fetchSearch: (keyword: string, signal?: AbortSignal) => Promise<GrantDepartmentSearchResult>;
}

export interface GrantDepartmentTree {
  rootIds: number[];
  getNode: (id: number) => GrantDepartmentNode | undefined;
  getChildIds: (id: number) => number[] | undefined;
  expanded: Set<number>;
  loadingIds: Set<number>;
  initialLoading: boolean;
  /** Expand/collapse a node, loading its child layer on first expand. */
  toggle: (node: GrantDepartmentNode) => void;
  keyword: string;
  setKeyword: (kw: string) => void;
  searchMode: boolean;
  searchRoots: GrantDepartmentNode[];
  searching: boolean;
  truncated: boolean;
}

export function useGrantDepartmentTree(source: GrantDepartmentTreeSource): GrantDepartmentTree {
  // Keep the (possibly inline) fetchers in a ref so callbacks stay stable.
  const sourceRef = useRef(source);
  sourceRef.current = source;

  const [nodeMap, setNodeMap] = useState<Record<number, GrantDepartmentNode>>({});
  const [childIds, setChildIds] = useState<Record<number, number[]>>({});
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());
  const [initialLoading, setInitialLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [searchResult, setSearchResult] = useState<GrantDepartmentSearchResult | null>(null);
  const [searching, setSearching] = useState(false);

  const childIdsRef = useRef(childIds);
  childIdsRef.current = childIds;

  const storeLayer = useCallback((parentId: number | null, layer: GrantDepartmentNode[]) => {
    const key = parentId ?? ROOT_KEY;
    setNodeMap((prev) => {
      const next = { ...prev };
      for (const n of layer) next[n.id] = { ...n, children: [] };
      return next;
    });
    setChildIds((prev) => ({ ...prev, [key]: layer.map((n) => n.id) }));
  }, []);

  const loadChildren = useCallback(
    async (parentId: number) => {
      if (childIdsRef.current[parentId]) return; // already loaded
      setLoadingIds((prev) => new Set(prev).add(parentId));
      try {
        const layer = await sourceRef.current.fetchChildren(parentId);
        if (layer) storeLayer(parentId, layer);
      } finally {
        setLoadingIds((prev) => {
          const next = new Set(prev);
          next.delete(parentId);
          return next;
        });
      }
    },
    [storeLayer]
  );

  const toggle = useCallback(
    (node: GrantDepartmentNode) => {
      if (!node.has_children) return;
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(node.id)) {
          next.delete(node.id);
        } else {
          next.add(node.id);
          void loadChildren(node.id);
        }
        return next;
      });
    },
    [loadChildren]
  );

  // Root layer on mount.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setInitialLoading(true);
    sourceRef.current
      .fetchChildren(null, controller.signal)
      .then((roots) => {
        if (!cancelled && roots) storeLayer(null, roots);
      })
      .finally(() => {
        if (!cancelled) setInitialLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced server-side search.
  useEffect(() => {
    const kw = keyword.trim();
    if (!kw) {
      setSearchResult(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      sourceRef.current
        .fetchSearch(kw, controller.signal)
        .then((res) => setSearchResult(res ?? null))
        .finally(() => setSearching(false));
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [keyword]);

  return {
    rootIds: childIds[ROOT_KEY] ?? [],
    getNode: (id) => nodeMap[id],
    getChildIds: (id) => childIds[id],
    expanded,
    loadingIds,
    initialLoading,
    toggle,
    keyword,
    setKeyword,
    searchMode: !!keyword.trim(),
    searchRoots: searchResult?.roots ?? [],
    searching,
    truncated: searchResult?.truncated ?? false,
  };
}
