import { useLazyDepartmentTree } from "@/components/bs-comp/department"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import {
  getDepartmentChildrenApi,
  getDepartmentMembersApi,
  getDepartmentPathTreeApi,
} from "@/controllers/API/department"
import { getUsersApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight, Loader2, User as UserIcon, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

export type DepartmentUserOption = {
  label: string
  value: number
  /** Login credential (external_id). Falls back to value (user_id) when absent. */
  external_id?: string | null
  /** 选人时由组织树节点解析，供编辑页即时展示部门路径 */
  department_path?: string
}

interface DepartmentUsersSelectProps {
  value: DepartmentUserOption[]
  onChange: (v: DepartmentUserOption[]) => void
  multiple?: boolean
  disabled?: boolean
  lockedValues?: number[]
  placeholder?: string
  searchPlaceholder?: string
  className?: string
  /** When set, the picker only renders the subtree rooted at this department's
   * internal id (Tenant admin/member pickers). F038: the lazy tree is rooted at
   * this id instead of the scope root. */
  rootDeptId?: number | null
  /** Optional message shown when the (sub)tree has no selectable members. */
  emptyMessage?: string
}

type UserListItem = {
  user_id: number
  user_name: string
  external_id?: string | null
  dept_id?: number | string | null
  department_id?: number | null
}

const TREE_INDENT_PER_LEVEL = 22

/** Follow a single-path pruned tree down to its leaf, joining names as a label. */
function pathLabelOf(tree: DepartmentSearchResult | null): { id: number | null; label: string } {
  const names: string[] = []
  let cur = tree?.roots?.[0]
  let id: number | null = null
  while (cur) {
    names.push(cur.name)
    id = cur.id
    cur = cur.children?.[0]
  }
  return { id, label: names.join(" / ") }
}

export default function DepartmentUsersSelect({
  value,
  onChange,
  multiple = true,
  disabled = false,
  lockedValues = [],
  placeholder,
  searchPlaceholder,
  className = "",
  rootDeptId,
  emptyMessage,
}: DepartmentUsersSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [searchingUsers, setSearchingUsers] = useState(false)
  const [searchedUsers, setSearchedUsers] = useState<UserListItem[]>([])
  const [deptUsersMap, setDeptUsersMap] = useState<Record<number, DepartmentUserOption[]>>({})
  const [loadingDeptIds, setLoadingDeptIds] = useState<Set<number>>(new Set())
  // Resolved path label (父 / 子) per department id, for the flat user-search results.
  const [deptLabelById, setDeptLabelById] = useState<Map<number, string>>(new Map())

  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchAbortRef = useRef<AbortController | null>(null)

  // F038: lazy department tree (browse). When rootDeptId is set, the root layer
  // is that department itself (resolved via path-tree), so the picker is scoped
  // to its subtree without slicing a full client-side tree.
  const tree = useLazyDepartmentTree(
    rootDeptId != null
      ? {
          autoLoad: open,
          autoExpandRoots: true,
          cacheKey: `dept-users:${rootDeptId}`,
          fetchChildren: async (parentId) => {
            if (parentId === null) {
              const pt = await getDepartmentPathTreeApi(rootDeptId, false)
              let cur = (pt as DepartmentSearchResult | null)?.roots?.[0]
              while (cur?.children?.[0]) cur = cur.children[0]
              return cur ? [cur] : []
            }
            return getDepartmentChildrenApi(parentId, false)
          },
          // The hook's own (department-name) search is unused here — this picker
          // runs its own user-name search — so this is a never-called no-op.
          fetchSearch: () => Promise.resolve({ roots: [], total_matches: 0, truncated: false }),
          fetchPathTree: (id) => getDepartmentPathTreeApi(id, false),
        }
      : { autoLoad: open, autoExpandRoots: true, cacheKey: "dept-users" }
  )

  const selectedMap = useMemo(() => {
    const map = new Map<number, DepartmentUserOption>()
    for (const v of value || []) map.set(Number(v.value), { ...v, value: Number(v.value) })
    return map
  }, [value])

  const lockedSet = useMemo(() => new Set(lockedValues.map((x) => Number(x))), [lockedValues])

  const loadDeptUsers = useCallback(
    async (node: DepartmentTreeNode) => {
      const did = Number(node.id)
      if (!did || loadingDeptIds.has(did) || deptUsersMap[did]) return
      setLoadingDeptIds((prev) => new Set(prev).add(did))
      try {
        const res = await getDepartmentMembersApi(node.dept_id, { page: 1, limit: 200, keyword: "" })
        const users = (res?.data || []).map((u) => ({
          value: Number(u.user_id),
          label: u.user_name,
          external_id: u.person_id ?? null,
        }))
        setDeptUsersMap((prev) => ({ ...prev, [did]: users }))
      } finally {
        setLoadingDeptIds((prev) => {
          const next = new Set(prev)
          next.delete(did)
          return next
        })
      }
    },
    [deptUsersMap, loadingDeptIds],
  )

  const runUserSearch = useCallback(async (q: string) => {
    searchAbortRef.current?.abort()
    const ac = new AbortController()
    searchAbortRef.current = ac
    setSearchingUsers(true)
    try {
      const res = await getUsersApi({ name: q, page: 1, pageSize: 200 }, { signal: ac.signal })
      if (!ac.signal.aborted) setSearchedUsers((res?.data || []) as UserListItem[])
    } catch {
      // ignore abort / network
    } finally {
      if (!ac.signal.aborted) setSearchingUsers(false)
    }
  }, [])

  const handleKeywordChange = (next: string) => {
    setKeyword(next)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!next.trim()) {
      setSearchedUsers([])
      setSearchingUsers(false)
      return
    }
    searchTimerRef.current = setTimeout(() => void runUserSearch(next.trim()), 300)
  }

  useEffect(() => {
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
      searchAbortRef.current?.abort()
    }
  }, [])

  // Resolve department path labels for the (flat) user-search results lazily —
  // one path-tree per distinct department in the result page.
  useEffect(() => {
    const ids = Array.from(
      new Set(
        searchedUsers
          .map((u) => (u.department_id != null ? Number(u.department_id) : null))
          .filter((id): id is number => id != null),
      ),
    ).filter((id) => !deptLabelById.has(id))
    if (!ids.length) return
    let cancelled = false
    Promise.all(
      ids.map((id) =>
        captureAndAlertRequestErrorHoc(getDepartmentPathTreeApi(id, false)).then(
          (res) => [id, pathLabelOf((res as DepartmentSearchResult | null) ?? null).label] as const,
        ),
      ),
    ).then((pairs) => {
      if (cancelled) return
      setDeptLabelById((prev) => {
        const next = new Map(prev)
        for (const [id, label] of pairs) next.set(id, label)
        return next
      })
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchedUsers])

  const setPicked = (user: DepartmentUserOption, departmentPath: string) => {
    const id = Number(user.value)
    if (lockedSet.has(id)) return
    const row: DepartmentUserOption = {
      value: id,
      label: user.label,
      external_id: user.external_id ?? null,
      department_path: departmentPath.trim() || undefined,
    }
    if (multiple) {
      if (selectedMap.has(id)) onChange((value || []).filter((x) => Number(x.value) !== id))
      else onChange([...(value || []), row])
      return
    }
    onChange([row])
    setOpen(false)
  }

  const handleExpand = (node: DepartmentTreeNode) => {
    tree.toggle(node)
    void loadDeptUsers(node)
  }

  const displayText = useMemo(() => {
    if (!value?.length) return placeholder || t("system.selectUser")
    if (value.length === 1) return value[0].label
    return `${placeholder || t("system.selectUser")} (${value.length})`
  }, [placeholder, t, value])

  const keywordTrim = keyword.trim()

  const renderUserRow = (u: DepartmentUserOption, depth: number, departmentPath: string) => {
    const selected = selectedMap.has(Number(u.value))
    const locked = lockedSet.has(Number(u.value))
    return (
      <div
        key={`u-${u.value}-${departmentPath}`}
        className={`flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm ${
          locked ? "opacity-60" : "cursor-pointer hover:bg-accent"
        }`}
        onClick={() => setPicked(u, departmentPath)}
      >
        <div className="relative shrink-0 self-stretch" style={{ width: depth * TREE_INDENT_PER_LEVEL }} aria-hidden />
        <Checkbox checked={selected} disabled={locked} onClick={(e) => e.stopPropagation()} onCheckedChange={() => setPicked(u, departmentPath)} />
        <UserIcon className="mx-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate">{u.label}</span>
        <span className="ml-1 shrink-0 text-xs text-muted-foreground">（{u.external_id ?? u.value}）</span>
      </div>
    )
  }

  // Browse render: a dept node + (when expanded) its users and child depts.
  const renderDeptNode = (node: DepartmentTreeNode, depth: number, ancestorNames: string[]) => {
    const did = Number(node.id)
    const isExpanded = tree.expanded.has(did)
    const pathLabel = [...ancestorNames, node.name].filter(Boolean).join(" / ")
    const childIds = tree.getChildIds(did)
    const childNodes = (childIds ?? [])
      .map((id) => tree.getNode(id))
      .filter((n): n is DepartmentTreeNode => !!n)
    const users = deptUsersMap[did] || []
    if (isExpanded && !deptUsersMap[did] && !loadingDeptIds.has(did)) void loadDeptUsers(node)

    return (
      <div key={`d-${did}`}>
        <div className="group flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent">
          <div className="relative shrink-0 self-stretch" style={{ width: depth * TREE_INDENT_PER_LEVEL }} aria-hidden />
          {node.has_children ? (
            <button
              className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center rounded p-0.5 hover:bg-muted"
              onClick={(e) => {
                e.stopPropagation()
                handleExpand(node)
              }}
            >
              {tree.loadingIds.has(did) ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
          ) : (
            <span className="mr-1 block h-4 w-4 shrink-0" />
          )}
          <Building2 className="mr-1.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{node.name}</span>
        </div>
        {isExpanded && (
          <>
            {loadingDeptIds.has(did) && (
              <div className="flex items-center py-1 pl-1.5 text-xs text-muted-foreground">
                <div className="shrink-0" style={{ width: (depth + 1) * TREE_INDENT_PER_LEVEL }} aria-hidden />
                {t("loading", { ns: "bs" })}
              </div>
            )}
            {users.map((u) => renderUserRow(u, depth + 1, pathLabel))}
            {childNodes.map((c) => renderDeptNode(c, depth + 1, [...ancestorNames, node.name]))}
          </>
        )}
      </div>
    )
  }

  const browseRoots = tree.rootIds
    .map((id) => tree.getNode(id))
    .filter((n): n is DepartmentTreeNode => !!n)

  return (
    <Popover open={open} onOpenChange={setOpen} modal={false}>
      <div className={`w-full ${className}`.trim()}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className="h-auto min-h-9 w-full justify-between px-3 py-1.5 font-normal"
          >
            <span className="min-w-0 flex-1 truncate text-left">{displayText}</span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-60" />
          </Button>
        </PopoverTrigger>
        {value?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {value.map((v) => (
              <span
                key={v.value}
                className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 text-xs text-foreground"
              >
                {v.label}（{v.external_id ?? v.value}）
                {!disabled && !lockedSet.has(Number(v.value)) && (
                  <X
                    className="h-3 w-3 cursor-pointer text-muted-foreground hover:text-foreground"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      onChange((value || []).filter((x) => Number(x.value) !== Number(v.value)))
                    }}
                  />
                )}
              </span>
            ))}
          </div>
        )}
      </div>
      <PopoverContent
        align="start"
        sideOffset={4}
        collisionPadding={12}
        className="w-[var(--radix-popover-trigger-width)] min-w-[260px] max-w-[calc(100vw_-_2rem)] overflow-hidden p-2"
        style={{ maxHeight: "min(520px, var(--radix-popover-content-available-height, 520px))" }}
      >
        <div
          className="flex min-h-0 flex-col gap-2 overflow-hidden"
          style={{ maxHeight: "min(504px, calc(var(--radix-popover-content-available-height, 520px) - 1rem))" }}
        >
          <SearchInput
            placeholder={searchPlaceholder || t("system.searchUser")}
            className="mb-1 shrink-0"
            value={keyword}
            onChange={(e) => handleKeywordChange(e.target.value)}
          />
          <div
            className="min-h-0 flex-1 overflow-y-auto rounded-md border"
            // Radix popover portaled outside the Dialog's react-remove-scroll
            // shard preventDefaults wheel; drive scrollTop manually.
            onWheel={(e) => {
              e.currentTarget.scrollTop += e.deltaY
            }}
          >
            {keywordTrim ? (
              // Search mode: a flat list of matched users (by name), each labeled
              // with its resolved department path (lazy, no full tree to bucket into).
              searchingUsers ? (
                <div className="px-2 py-4 text-center text-sm text-muted-foreground">{t("loading", { ns: "bs" })}</div>
              ) : searchedUsers.length === 0 ? (
                <div className="py-4 text-center text-sm text-muted-foreground">
                  {emptyMessage || t("system.treeDepartmentSelectEmpty")}
                </div>
              ) : (
                searchedUsers.map((u) => {
                  const deptId = u.department_id != null ? Number(u.department_id) : null
                  const deptLabel = deptId != null ? deptLabelById.get(deptId) ?? "" : ""
                  return (
                    <div
                      key={`su-${u.user_id}`}
                      className={`flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm ${
                        lockedSet.has(Number(u.user_id)) ? "opacity-60" : "cursor-pointer hover:bg-accent"
                      }`}
                      onClick={() =>
                        setPicked({ value: u.user_id, label: u.user_name, external_id: u.external_id }, deptLabel)
                      }
                    >
                      <Checkbox
                        checked={selectedMap.has(Number(u.user_id))}
                        disabled={lockedSet.has(Number(u.user_id))}
                        onClick={(e) => e.stopPropagation()}
                        onCheckedChange={() =>
                          setPicked({ value: u.user_id, label: u.user_name, external_id: u.external_id }, deptLabel)
                        }
                      />
                      <UserIcon className="mx-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{u.user_name}</span>
                      <span className="ml-1 shrink-0 text-xs text-muted-foreground">（{u.external_id ?? u.user_id}）</span>
                      {deptLabel && <span className="ml-auto truncate pl-2 text-xs text-muted-foreground">{deptLabel}</span>}
                    </div>
                  )
                })
              )
            ) : tree.initialLoading ? (
              <div className="py-4 text-center text-sm text-muted-foreground">{t("loading", { ns: "bs" })}</div>
            ) : browseRoots.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">
                {emptyMessage || t("system.treeDepartmentSelectEmpty")}
              </div>
            ) : (
              browseRoots.map((n) => renderDeptNode(n, 0, []))
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
