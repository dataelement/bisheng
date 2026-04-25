import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { getDepartmentMembersApi, getDepartmentTreeApi } from "@/controllers/API/department"
import { getUsersApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight, User as UserIcon, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"

export type DepartmentUserOption = {
  label: string
  value: number
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
}

type UserListItem = {
  user_id: number
  user_name: string
  dept_id?: number | string | null
  department_id?: number | null
}

function resolveTreeDepartmentId(
  u: UserListItem,
  deptBusinessKeyToId: Map<string, number>,
): number | null {
  const primary = u.department_id
  if (primary != null && Number.isFinite(Number(primary))) return Math.trunc(Number(primary))

  const raw = u.dept_id
  if (raw == null || raw === "") return null
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.trunc(raw)
  const s = String(raw).trim()
  const asNum = Number(s)
  if (Number.isFinite(asNum) && String(asNum) === s) return Math.trunc(asNum)
  const hit = deptBusinessKeyToId.get(s)
  return hit != null ? hit : null
}

const TREE_INDENT_PER_LEVEL = 22

export default function DepartmentUsersSelect({
  value,
  onChange,
  multiple = true,
  disabled = false,
  lockedValues = [],
  placeholder,
  searchPlaceholder,
  className = "",
}: DepartmentUsersSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [tree, setTree] = useState<DepartmentTreeNode[]>([])
  const [keyword, setKeyword] = useState("")
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [loadingTree, setLoadingTree] = useState(false)
  const [searchingUsers, setSearchingUsers] = useState(false)
  const [searchedUsers, setSearchedUsers] = useState<UserListItem[]>([])
  const [deptUsersMap, setDeptUsersMap] = useState<Record<number, DepartmentUserOption[]>>({})
  const [loadingDeptIds, setLoadingDeptIds] = useState<Set<number>>(new Set())

  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchAbortRef = useRef<AbortController | null>(null)

  const selectedMap = useMemo(() => {
    const map = new Map<number, DepartmentUserOption>()
    for (const v of value || []) map.set(Number(v.value), { ...v, value: Number(v.value) })
    return map
  }, [value])

  const lockedSet = useMemo(() => new Set(lockedValues.map((x) => Number(x))), [lockedValues])

  const loadTree = useCallback(async () => {
    setLoadingTree(true)
    try {
      const res = await captureAndAlertRequestErrorHoc(getDepartmentTreeApi())
      if (Array.isArray(res)) {
        setTree(res.filter((n) => n.status !== "archived"))
        const rootIds = new Set<number>()
        for (const n of res) rootIds.add(n.id)
        setExpanded(rootIds)
      }
    } finally {
      setLoadingTree(false)
    }
  }, [])

  const loadDeptUsers = useCallback(async (node: DepartmentTreeNode) => {
    const did = Number(node.id)
    if (!did) return
    if (loadingDeptIds.has(did)) return
    if (deptUsersMap[did]) return
    setLoadingDeptIds((prev) => new Set([...prev, did]))
    try {
      const res = await getDepartmentMembersApi(node.dept_id, {
        page: 1,
        limit: 200,
        keyword: "",
      })
      const users = (res?.data || []).map((u) => ({
        value: Number(u.user_id),
        label: u.user_name,
      }))
      setDeptUsersMap((prev) => ({ ...prev, [did]: users }))
    } finally {
      setLoadingDeptIds((prev) => {
        const next = new Set(prev)
        next.delete(did)
        return next
      })
    }
  }, [deptUsersMap, loadingDeptIds])

  useEffect(() => {
    if (!open) return
    if (tree.length === 0) void loadTree()
  }, [open, tree.length, loadTree])

  useEffect(() => {
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
      searchAbortRef.current?.abort()
    }
  }, [])

  const runUserSearch = useCallback(async (q: string) => {
    searchAbortRef.current?.abort()
    const ac = new AbortController()
    searchAbortRef.current = ac
    setSearchingUsers(true)
    try {
      const res = await getUsersApi(
        { name: q, page: 1, pageSize: 200 },
        { signal: ac.signal }
      )
      if (!ac.signal.aborted) setSearchedUsers((res?.data || []) as UserListItem[])
    } catch {
      // ignore abort/network
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
    searchTimerRef.current = setTimeout(() => {
      void runUserSearch(next.trim())
    }, 300)
  }

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const setPicked = (user: DepartmentUserOption, departmentPath: string) => {
    const id = Number(user.value)
    if (lockedSet.has(id)) return
    const pathTrim = departmentPath.trim()
    const withPath = (row: DepartmentUserOption): DepartmentUserOption => ({
      ...row,
      value: id,
      label: user.label,
      department_path: pathTrim || undefined,
    })
    if (multiple) {
      if (selectedMap.has(id)) {
        onChange((value || []).filter((x) => Number(x.value) !== id))
      } else {
        onChange([...(value || []), withPath(user)])
      }
      return
    }
    onChange([withPath(user)])
    setOpen(false)
  }

  const displayText = useMemo(() => {
    if (!value?.length) return placeholder || t("system.selectUser")
    if (value.length === 1) return value[0].label
    return `${placeholder || t("system.selectUser")} (${value.length})`
  }, [placeholder, t, value])

  const keywordTrim = keyword.trim()

  const deptBusinessKeyToId = useMemo(() => {
    const m = new Map<string, number>()
    const walk = (nodes: DepartmentTreeNode[]) => {
      for (const n of nodes) {
        m.set(String(n.dept_id), n.id)
        if (n.children?.length) walk(n.children)
      }
    }
    walk(tree)
    return m
  }, [tree])

  const searchedByDept = useMemo(() => {
    const map = new Map<number, DepartmentUserOption[]>()
    if (!keywordTrim) return map
    for (const u of searchedUsers || []) {
      const did = resolveTreeDepartmentId(u, deptBusinessKeyToId)
      if (did == null) continue
      const row = { value: Number(u.user_id), label: u.user_name }
      const arr = map.get(did) || []
      if (!arr.some((x) => x.value === row.value)) arr.push(row)
      map.set(did, arr)
    }
    return map
  }, [deptBusinessKeyToId, keywordTrim, searchedUsers])

  /** 有搜索词时：只按「用户名」命中（getUsersApi 的 name + 返回行的 department_id / dept_id 挂树），不按部门名过滤 */
  const nodeMatches = useCallback((n: DepartmentTreeNode): boolean => {
    if (!keywordTrim) return true
    const direct = (searchedByDept.get(n.id) || []).length > 0
    if (direct) return true
    return (n.children || []).some(nodeMatches)
  }, [keywordTrim, searchedByDept])

  useEffect(() => {
    if (!keywordTrim) return
    const ids = new Set<number>()
    const walk = (nodes: DepartmentTreeNode[]) => {
      for (const n of nodes) {
        if (nodeMatches(n)) {
          ids.add(n.id)
          if (n.children?.length) walk(n.children)
        }
      }
    }
    walk(tree)
    setExpanded(ids)
  }, [keywordTrim, nodeMatches, tree])

  const renderNode = (node: DepartmentTreeNode, depth: number, ancestorNames: string[]): ReactNode => {
    if (node.status === "archived") return null
    if (!nodeMatches(node)) return null

    const did = Number(node.id)
    const displayPathForNode = [...ancestorNames, node.name].filter(Boolean).join(" / ")
    const hasChildren = Boolean(node.children?.length)
    const isExpanded = expanded.has(did)
    const shouldShowRows = !hasChildren || isExpanded
    const users = keywordTrim ? (searchedByDept.get(did) || []) : (deptUsersMap[did] || [])

    if (!keywordTrim && shouldShowRows && !deptUsersMap[did] && !loadingDeptIds.has(did)) {
      void loadDeptUsers(node)
    }

    return (
      <div key={did}>
        <div
          className="group flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent"
        >
          <div className="relative shrink-0 self-stretch" style={{ width: depth * TREE_INDENT_PER_LEVEL }} aria-hidden>
            {depth > 0 && (
              <span className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-border" aria-hidden />
            )}
          </div>
          {hasChildren ? (
            <button
              className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center rounded p-0.5 hover:bg-muted"
              onClick={(e) => {
                e.stopPropagation()
                toggleExpand(did)
              }}
            >
              {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          ) : (
            <span className="mr-1 block h-4 w-4 shrink-0" />
          )}
          <Building2 className="mr-1.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{node.name}</span>
        </div>

        {shouldShowRows && (
          <>
            {(loadingDeptIds.has(did) && !keywordTrim) && (
              <div
                className="flex items-center py-1 pl-1.5 pr-2 text-xs text-muted-foreground"
              >
                <div className="relative shrink-0 self-stretch" style={{ width: (depth + 1) * TREE_INDENT_PER_LEVEL }} aria-hidden>
                  <span className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-border" aria-hidden />
                </div>
                {t("loading", { ns: "bs" })}
              </div>
            )}
            {users.map((u) => {
              const selected = selectedMap.has(Number(u.value))
              const locked = lockedSet.has(Number(u.value))
              return (
                <div
                  key={`${did}-${u.value}`}
                  className={`flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm ${locked ? "opacity-60" : "cursor-pointer hover:bg-accent"}`}
                  onClick={() => setPicked(u, displayPathForNode)}
                >
                  <div className="relative shrink-0 self-stretch" style={{ width: (depth + 1) * TREE_INDENT_PER_LEVEL }} aria-hidden>
                    <span className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-border" aria-hidden />
                  </div>
                  <Checkbox checked={selected} disabled={locked} onCheckedChange={() => setPicked(u, displayPathForNode)} />
                  <UserIcon className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="truncate">{u.label}</span>
                </div>
              )
            })}
            {hasChildren && node.children!.map((c) => renderNode(c, depth + 1, [...ancestorNames, node.name]))}
          </>
        )}
      </div>
    )
  }

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
                {v.label}
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
        className="w-[min(100vw-2rem,520px)] max-w-[min(100vw-2rem,520px)] p-2"
      >
        <div className="flex max-h-[520px] flex-col gap-2">
          <SearchInput
            placeholder={searchPlaceholder || t("system.searchUser")}
            className="mb-1"
            value={keyword}
            onChange={(e) => handleKeywordChange(e.target.value)}
          />
          <div className="min-h-[140px] max-h-[420px] overflow-y-auto rounded-md border">
            {loadingTree ? (
              <div className="py-4 text-center text-sm text-muted-foreground">{t("loading", { ns: "bs" })}</div>
            ) : tree.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">{t("system.treeDepartmentSelectEmpty")}</div>
            ) : (
              <>
                {searchingUsers && keywordTrim ? (
                  <div className="px-2 py-1 text-xs text-muted-foreground">{t("loading", { ns: "bs" })}</div>
                ) : null}
                {tree.map((n) => renderNode(n, 0, []))}
              </>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
