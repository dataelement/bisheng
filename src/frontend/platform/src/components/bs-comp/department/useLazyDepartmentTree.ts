import {
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"
import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "react-query"

/**
 * F038: per-layer lazy department tree (browse / server search / locate), shared
 * by the platform nav tree and every "pick a department" entry. Browse keeps a
 * normalized lazy model (a node map + per-parent child ids loaded on demand);
 * search and locate render the backend's pruned tree directly. Permission scope
 * is decided by the backend — this hook is scope-agnostic.
 */

/** childIds map key for the root layer (real department ids are >= 1). */
const ROOT_KEY = -1
const SEARCH_DEBOUNCE_MS = 300

export interface UseLazyDepartmentTreeOptions {
  /** Show archived nodes (management nav tree only; pickers leave false). */
  includeArchived?: boolean
  /** Fetch the root layer on mount (default true). */
  autoLoad?: boolean
  /** After the root layer loads, also expand each root once (mirrors the old nav
   *  tree's "first level expanded"). Default false. */
  autoExpandRoots?: boolean
  /** Hide a materialized-path subtree (browse + search). Used by the "move
   *  department" picker to forbid selecting the moving dept or its descendants
   *  as the new parent (path prefix = the moving dept's own path). */
  excludeSubtreePath?: string
  // Data source (default: the platform department APIs). The authorization pickers
  // pass the grant-subject endpoints — same node shape, different (auth) scope.
  // Provide all three together; pass them memoized (stable identity) to avoid
  // re-fetch churn. ``cacheKey`` namespaces the react-query cache per source.
  fetchChildren?: (parentId: number | null) => Promise<DepartmentTreeNode[]>
  fetchSearch?: (keyword: string) => Promise<DepartmentSearchResult>
  fetchPathTree?: (deptInternalId: number) => Promise<DepartmentSearchResult>
  cacheKey?: string
}

export interface LazyDepartmentTree {
  rootIds: number[]
  getNode: (id: number) => DepartmentTreeNode | undefined
  getChildIds: (id: number) => number[] | undefined
  expanded: Set<number>
  loadingIds: Set<number>
  initialLoading: boolean
  /** Expand/collapse a node, loading its child layer on first expand. */
  toggle: (node: DepartmentTreeNode) => void
  /** Invalidate + refetch one layer after a create/move/archive (AC-05). Pass
   *  null for the root layer. */
  reloadLayer: (parentId: number | null) => Promise<void>
  /** Invalidate + refetch every currently-loaded layer (root + expanded), keeping
   *  expand state. Use after a mutation whose affected parents aren't all known
   *  (e.g. a move refreshes both old and new parent if both are loaded). */
  refreshAll: () => Promise<void>
  // search
  keyword: string
  setKeyword: (kw: string) => void
  searchMode: boolean
  searchRoots: DepartmentTreeNode[]
  searching: boolean
  truncated: boolean
  matchedIds: Set<number>
  // locate / echo a deep value
  reveal: (deptInternalId: number) => Promise<number[]>
}

function collectMatched(roots: DepartmentTreeNode[], out: Set<number>) {
  for (const n of roots) {
    if (n.matched) out.add(n.id)
    if (n.children?.length) collectMatched(n.children, out)
  }
}

/** Recursively drop nodes inside an excluded materialized-path subtree. */
function pruneExcluded(nodes: DepartmentTreeNode[], excludePath?: string): DepartmentTreeNode[] {
  if (!excludePath) return nodes
  return nodes
    .filter((n) => !(n.path && n.path.startsWith(excludePath)))
    .map((n) => (n.children?.length ? { ...n, children: pruneExcluded(n.children, excludePath) } : n))
}

/** Follow a single-path pruned tree (locate response) down to its leaf, collecting
 *  the ancestor→target id chain. */
function chainOf(roots: DepartmentTreeNode[]): number[] {
  const ids: number[] = []
  let cur: DepartmentTreeNode | undefined = roots[0]
  while (cur) {
    ids.push(cur.id)
    cur = cur.children?.[0]
  }
  return ids
}

export function useLazyDepartmentTree(
  options: UseLazyDepartmentTreeOptions = {}
): LazyDepartmentTree {
  const { includeArchived = false, autoLoad = true, autoExpandRoots = false, excludeSubtreePath } = options
  const queryClient = useQueryClient()
  const cacheKey = options.cacheKey ?? `dept:${includeArchived}`

  // Effective data source, kept in a ref so the fetch callbacks stay stable even
  // if the caller passes inline (non-memoized) fetchers. Defaults to the platform
  // department APIs; the authorization pickers inject the grant-subject endpoints.
  const sourceRef = useRef({
    children: (p: number | null) => getDepartmentChildrenApi(p, includeArchived),
    search: (kw: string) => searchDepartmentsApi(kw, includeArchived),
    pathTree: (id: number) => getDepartmentPathTreeApi(id, includeArchived),
  })
  sourceRef.current = {
    children: options.fetchChildren ?? ((p: number | null) => getDepartmentChildrenApi(p, includeArchived)),
    search: options.fetchSearch ?? ((kw: string) => searchDepartmentsApi(kw, includeArchived)),
    pathTree: options.fetchPathTree ?? ((id: number) => getDepartmentPathTreeApi(id, includeArchived)),
  }

  const [nodeMap, setNodeMap] = useState<Record<number, DepartmentTreeNode>>({})
  const [childIds, setChildIds] = useState<Record<number, number[]>>({})
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set())
  const [initialLoading, setInitialLoading] = useState(autoLoad)

  const [keyword, setKeyword] = useState("")
  const [searchResult, setSearchResult] = useState<DepartmentSearchResult | null>(null)
  const [searching, setSearching] = useState(false)

  // Refs so callbacks stay stable yet read live state (avoids re-fetch storms).
  const childIdsRef = useRef(childIds)
  childIdsRef.current = childIds

  const fetchLayer = useCallback(
    async (parentId: number | null): Promise<DepartmentTreeNode[] | null> => {
      const res = await captureAndAlertRequestErrorHoc(
        queryClient.fetchQuery(
          [cacheKey, "children", parentId],
          () => sourceRef.current.children(parentId),
          { staleTime: 30_000 }
        )
      )
      return (res as DepartmentTreeNode[] | null) ?? null
    },
    [queryClient, cacheKey]
  )

  const storeLayer = useCallback(
    (parentId: number | null, layer: DepartmentTreeNode[]) => {
      const key = parentId ?? ROOT_KEY
      const visible = excludeSubtreePath
        ? layer.filter((n) => !(n.path && n.path.startsWith(excludeSubtreePath)))
        : layer
      setNodeMap((prev) => {
        const next = { ...prev }
        for (const n of visible) next[n.id] = { ...n, children: [] }
        return next
      })
      setChildIds((prev) => ({ ...prev, [key]: visible.map((n) => n.id) }))
    },
    [excludeSubtreePath]
  )

  const loadChildren = useCallback(
    async (parentId: number): Promise<void> => {
      if (childIdsRef.current[parentId]) return // already loaded
      setLoadingIds((prev) => new Set(prev).add(parentId))
      const layer = await fetchLayer(parentId)
      if (layer) storeLayer(parentId, layer)
      setLoadingIds((prev) => {
        const next = new Set(prev)
        next.delete(parentId)
        return next
      })
    },
    [fetchLayer, storeLayer]
  )

  const toggle = useCallback(
    (node: DepartmentTreeNode) => {
      if (!node.has_children) return
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(node.id)) {
          next.delete(node.id)
        } else {
          next.add(node.id)
          void loadChildren(node.id)
        }
        return next
      })
    },
    [loadChildren]
  )

  const reloadLayer = useCallback(
    async (parentId: number | null) => {
      await queryClient.invalidateQueries([cacheKey, "children", parentId])
      const layer = await fetchLayer(parentId)
      if (layer) storeLayer(parentId, layer)
    },
    [queryClient, cacheKey, fetchLayer, storeLayer]
  )

  const refreshAll = useCallback(async () => {
    await queryClient.invalidateQueries([cacheKey, "children"])
    const keys = Object.keys(childIdsRef.current).map(Number)
    for (const key of keys) {
      const parentId = key === ROOT_KEY ? null : key
      const layer = await fetchLayer(parentId)
      if (layer) storeLayer(parentId, layer)
    }
  }, [queryClient, cacheKey, fetchLayer, storeLayer])

  // Root layer — fetched when enabled (autoLoad). Tying autoLoad to e.g. a
  // popover's open state defers the request until a picker is actually opened,
  // so closed pickers on a page cost nothing.
  useEffect(() => {
    if (!autoLoad) return
    if (childIdsRef.current[ROOT_KEY]) return // already loaded
    let cancelled = false
    setInitialLoading(true)
    ;(async () => {
      const roots = await fetchLayer(null)
      if (cancelled || !roots) {
        setInitialLoading(false)
        return
      }
      storeLayer(null, roots)
      if (autoExpandRoots) {
        setExpanded(new Set(roots.filter((n) => n.has_children).map((n) => n.id)))
        await Promise.all(roots.filter((n) => n.has_children).map((n) => loadChildren(n.id)))
      }
      setInitialLoading(false)
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad, cacheKey])

  // Debounced server-side search.
  useEffect(() => {
    const kw = keyword.trim()
    if (!kw) {
      setSearchResult(null)
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = window.setTimeout(async () => {
      const res = await captureAndAlertRequestErrorHoc(sourceRef.current.search(kw))
      setSearchResult((res as DepartmentSearchResult | null) ?? null)
      setSearching(false)
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [keyword, cacheKey])

  const reveal = useCallback(
    async (deptInternalId: number): Promise<number[]> => {
      const res = await captureAndAlertRequestErrorHoc(sourceRef.current.pathTree(deptInternalId))
      const tree = (res as DepartmentSearchResult | null) ?? null
      if (!tree || !tree.roots.length) return []
      const chain = chainOf(tree.roots)
      // Ensure the root layer + every ancestor's FULL child layer is loaded, then
      // expand the chain so the target is reachable with its real siblings.
      if (!childIdsRef.current[ROOT_KEY]) {
        const roots = await fetchLayer(null)
        if (roots) storeLayer(null, roots)
      }
      for (let i = 0; i < chain.length - 1; i++) {
        await loadChildren(chain[i])
      }
      setExpanded((prev) => {
        const next = new Set(prev)
        for (let i = 0; i < chain.length - 1; i++) next.add(chain[i])
        return next
      })
      return chain
    },
    [fetchLayer, storeLayer, loadChildren]
  )

  const matchedIds = new Set<number>()
  if (searchResult) collectMatched(searchResult.roots, matchedIds)

  return {
    rootIds: childIds[ROOT_KEY] ?? [],
    getNode: (id) => nodeMap[id],
    getChildIds: (id) => childIds[id],
    expanded,
    loadingIds,
    initialLoading,
    toggle,
    reloadLayer,
    refreshAll,
    keyword,
    setKeyword,
    searchMode: !!keyword.trim(),
    searchRoots: pruneExcluded(searchResult?.roots ?? [], excludeSubtreePath),
    searching,
    truncated: searchResult?.truncated ?? false,
    matchedIds,
    reveal,
  }
}
