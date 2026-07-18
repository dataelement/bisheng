/**
 * 树状部门选择器（TreeDepartmentSelect）
 *
 * 用于在弹层中按组织架构树选择部门，支持服务端搜索、按层懒加载、按 id 定位回显。
 * F038：数据不再由父组件传整树，而是组件内部经 `useLazyDepartmentTree` 懒加载
 * （`GET /api/v1/departments/{children,search,{id}/path-tree}`），大组织下秒开。
 */
import { Button } from "@/components/bs-ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { getDepartmentPathTreeApi } from "@/controllers/API/department"
import { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"
import { cn } from "@/utils"
import { ChevronDown } from "lucide-react"
import type { ReactNode } from "react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { LazyDepartmentTree } from "./LazyDepartmentTree"
import { useLazyDepartmentTree } from "./useLazyDepartmentTree"

export type TreeDepartmentSelectValue = number | null

export interface TreeDepartmentSelectProps {
  value: TreeDepartmentSelectValue
  onChange: (id: TreeDepartmentSelectValue, node: DepartmentTreeNode | null) => void
  /** 为 true 时可在面板顶部选择「无部门」（value 置为 null） */
  allowNone?: boolean
  noneLabel?: ReactNode
  placeholder?: string
  disabled?: boolean
  className?: string
  triggerClassName?: string
  contentClassName?: string
  /** 无部门数据时的提示 */
  emptyText?: ReactNode
  /** 搜索框占位；默认使用部门模块文案 */
  searchPlaceholder?: string
  /**
   * Radix Popover `modal`。在 Dialog 内嵌使用时请传 `false`，避免多层焦点陷阱导致无法操作树节点。
   * @default true
   */
  modal?: boolean
  /** 物化路径前缀；隐藏该子树（移动部门时禁止选自身/后代作为新父级）。 */
  excludeSubtreePath?: string
}

/** 在树中按主键 id 查找节点（保留供仍持有整树的调用方使用）。 */
export function findDepartmentNodeById(
  nodes: DepartmentTreeNode[],
  id: number
): DepartmentTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    if (n.children?.length) {
      const hit = findDepartmentNodeById(n.children, id)
      if (hit) return hit
    }
  }
  return null
}

/** 从根到该节点的完整路径文案，例如 `总部 / 研发中心` */
export function getDepartmentDisplayPath(nodes: DepartmentTreeNode[], id: number): string {
  const dfs = (arr: DepartmentTreeNode[], stack: string[]): string | null => {
    for (const n of arr) {
      if (n.id === id) return [...stack, n.name].join(" / ")
      if (n.children?.length) {
        const hit = dfs(n.children, [...stack, n.name])
        if (hit) return hit
      }
    }
    return null
  }
  return dfs(nodes, []) ?? ""
}

/** 从根到目标节点的 id 链，用于展开祖先节点 */
export function findDepartmentAncestorIds(
  nodes: DepartmentTreeNode[],
  targetId: number,
  prefix: number[] = []
): number[] | null {
  for (const n of nodes) {
    const chain = [...prefix, n.id]
    if (n.id === targetId) return chain
    if (n.children?.length) {
      const hit = findDepartmentAncestorIds(n.children, targetId, chain)
      if (hit) return hit
    }
  }
  return null
}

/** Join a single-path pruned tree (path-tree response) into a `a / b / c` label. */
function pathLabelOf(tree: DepartmentSearchResult | null): string {
  if (!tree) return ""
  const names: string[] = []
  let cur: DepartmentTreeNode | undefined = tree.roots[0]
  while (cur) {
    names.push(cur.name)
    cur = cur.children?.[0]
  }
  return names.join(" / ")
}

export function TreeDepartmentSelect({
  value,
  onChange,
  allowNone = false,
  noneLabel,
  placeholder,
  disabled = false,
  className,
  triggerClassName,
  contentClassName,
  emptyText,
  searchPlaceholder,
  modal = true,
  excludeSubtreePath,
}: TreeDepartmentSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [labelPath, setLabelPath] = useState("")
  // Pickers never offer archived departments as new picks (the backend excludes
  // them from children/search); an archived current value can still be echoed
  // via path-tree (AC-18). Load only while the popover is open.
  const tree = useLazyDepartmentTree({ includeArchived: false, autoLoad: open, excludeSubtreePath })

  const ph = placeholder ?? t("system.treeDepartmentSelectPlaceholder")
  const searchPh = searchPlaceholder ?? t("bs:department.search")
  const noneText = noneLabel ?? t("system.scopeGlobalRole")
  const displayLabel = value == null ? (allowNone ? String(noneText) : ph) : labelPath || ph
  const selectedDeptId = value != null ? tree.getNode(value)?.dept_id ?? null : null

  // Reveal (expand + highlight) the current value each time the popover opens.
  useEffect(() => {
    if (open && value != null) void tree.reveal(value)
    if (!open) tree.setKeyword("")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, value])

  // Trigger label = the full root→value name path (one path-tree fetch, works
  // even for a deep or archived current value without loading the whole tree).
  useEffect(() => {
    if (value == null) {
      setLabelPath("")
      return
    }
    let cancelled = false
    captureAndAlertRequestErrorHoc(getDepartmentPathTreeApi(value)).then((res) => {
      if (!cancelled) setLabelPath(pathLabelOf((res as DepartmentSearchResult | null) ?? null))
    })
    return () => {
      cancelled = true
    }
  }, [value])

  const handlePick = (node: DepartmentTreeNode) => {
    onChange(node.id, node)
    setOpen(false)
  }

  const handlePickNone = () => {
    onChange(null, null)
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <div className={cn("w-full", className)}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className={cn(
              "h-9 w-full justify-between px-3 font-normal text-foreground hover:bg-background",
              !value && !allowNone && "text-muted-foreground",
              triggerClassName
            )}
            aria-expanded={open}
            aria-haspopup="listbox"
          >
            <span
              className="min-w-0 flex-1 truncate text-left"
              title={value != null ? displayLabel : undefined}
            >
              {displayLabel}
            </span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-60" />
          </Button>
        </PopoverTrigger>
      </div>
      <PopoverContent
        align="start"
        sideOffset={4}
        className={cn(
          "max-h-[min(70vh,420px)] w-[min(100vw-2rem,420px)] max-w-[min(100vw-2rem,420px)] p-2",
          contentClassName
        )}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <div className="flex max-h-[min(70vh-1rem,400px)] flex-col gap-2" role="listbox">
          {allowNone && (
            <button
              type="button"
              role="option"
              aria-selected={value == null}
              className={cn(
                "w-full shrink-0 rounded-md px-2 py-2 text-left text-sm hover:bg-accent",
                value == null && "bg-accent font-medium"
              )}
              onClick={handlePickNone}
            >
              {noneText}
            </button>
          )}
          <LazyDepartmentTree
            controller={tree}
            selectedDeptId={selectedDeptId}
            onSelect={handlePick}
            searchPlaceholder={searchPh}
            emptyHint={emptyText ?? t("system.treeDepartmentSelectEmpty")}
            wheelScrollFix
            className="min-h-0"
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}
