/**
 * 树状部门选择器（TreeDepartmentSelect）
 *
 * 用于在弹层中按组织架构树选择部门，支持搜索筛选、展开/折叠。
 * 数据源为 `GET /api/v1/departments/tree` 返回的 `DepartmentTreeNode[]`。
 */
import { SearchInput } from "@/components/bs-ui/input"
import { Button } from "@/components/bs-ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { cn } from "@/utils"
import { DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight } from "lucide-react"
import type { MouseEvent, ReactNode } from "react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

const TREE_INDENT_PER_LEVEL = 22
const DEFAULT_EXPAND_MAX_DEPTH = 1

export type TreeDepartmentSelectValue = number | null

export interface TreeDepartmentSelectProps {
  nodes: DepartmentTreeNode[]
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
  /** 列表中是否显示成员数 */
  showMemberCount?: boolean
  /**
   * Radix Popover `modal`。在 Dialog 内嵌使用时请传 `false`，避免多层焦点陷阱导致无法操作树节点。
   * @default true
   */
  modal?: boolean
}

/** 在树中按主键 id 查找节点 */
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

function collectDefaultExpandedIds(
  tree: DepartmentTreeNode[],
  maxDepth: number,
  currentDepth = 0
): number[] {
  const ids: number[] = []
  for (const n of tree) {
    if (currentDepth >= maxDepth) continue
    ids.push(n.id)
    if (n.children?.length) {
      ids.push(...collectDefaultExpandedIds(n.children, maxDepth, currentDepth + 1))
    }
  }
  return ids
}

export function TreeDepartmentSelect({
  nodes,
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
  showMemberCount = false,
  modal = true,
}: TreeDepartmentSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const ph = placeholder ?? t("system.treeDepartmentSelectPlaceholder")
  const searchPh = searchPlaceholder ?? t("bs:department.search")
  const noneText = noneLabel ?? t("system.scopeGlobalRole")

  const collectDefaultExpandedIdsCb = useCallback(
    (tree: DepartmentTreeNode[], maxDepth: number, currentDepth = 0): number[] =>
      collectDefaultExpandedIds(tree, maxDepth, currentDepth),
    []
  )

  useEffect(() => {
    if (!open || !nodes.length) return
    setExpanded(() => {
      const next = new Set<number>()
      collectDefaultExpandedIdsCb(nodes, DEFAULT_EXPAND_MAX_DEPTH).forEach((id) => next.add(id))
      if (value != null) {
        const chain = findDepartmentAncestorIds(nodes, value)
        if (chain) chain.forEach((id) => next.add(id))
      }
      return next
    })
  }, [open, value, nodes, collectDefaultExpandedIdsCb])

  useEffect(() => {
    if (!open) setKeyword("")
  }, [open])

  const matchesKeyword = useCallback(
    (node: DepartmentTreeNode): boolean => {
      if (!keyword) return true
      const lower = keyword.toLowerCase()
      if (node.name.toLowerCase().includes(lower)) return true
      return (node.children || []).some(matchesKeyword)
    },
    [keyword]
  )

  useEffect(() => {
    if (!keyword || !nodes.length) return
    const ids = new Set<number>()
    const collect = (arr: DepartmentTreeNode[]) => {
      for (const n of arr) {
        if (matchesKeyword(n) && n.children?.length) {
          ids.add(n.id)
          collect(n.children)
        }
      }
    }
    collect(nodes)
    setExpanded((prev) => new Set([...prev, ...ids]))
  }, [keyword, nodes, matchesKeyword])

  const displayLabel = useMemo(() => {
    if (value == null) {
      return allowNone ? String(noneText) : ph
    }
    const path = getDepartmentDisplayPath(nodes, value)
    return path || ph
  }, [value, nodes, allowNone, noneText, ph])

  const toggleExpand = useCallback((id: number, e: MouseEvent) => {
    e.stopPropagation()
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const handlePickNode = useCallback(
    (node: DepartmentTreeNode) => {
      onChange(node.id, node)
      setOpen(false)
    },
    [onChange]
  )

  const handlePickNone = useCallback(() => {
    onChange(null, null)
    setOpen(false)
  }, [onChange])

  const renderNode = useMemo(() => {
    const Render = ({ node, depth }: { node: DepartmentTreeNode; depth: number }) => {
      if (!matchesKeyword(node)) return null
      if (node.status === "archived") return null
      const hasChildren = Boolean(node.children?.length)
      const isExpanded = expanded.has(node.id)
      const isSelected = value != null && node.id === value
      const gutterWidth = depth * TREE_INDENT_PER_LEVEL

      return (
        <div key={node.id}>
          <div
            role="option"
            aria-selected={isSelected}
            className={cn(
              "group flex cursor-pointer items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent",
              isSelected && "bg-accent font-medium",
            )}
            onClick={() => handlePickNode(node)}
          >
            <div className="relative shrink-0 self-stretch" style={{ width: gutterWidth }} aria-hidden>
              {depth > 0 && (
                <span
                  className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-border"
                  aria-hidden
                />
              )}
            </div>
            <span
              className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center"
              onClick={(e) => hasChildren && toggleExpand(node.id, e)}
            >
              {hasChildren ? (
                isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                )
              ) : (
                <span className="block h-3.5 w-3.5" aria-hidden />
              )}
            </span>
            <Building2 className="mr-1.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{node.name}</span>
            {showMemberCount && (
              <span className="ml-1 shrink-0 text-xs tabular-nums text-muted-foreground">
                {node.member_count}
              </span>
            )}
          </div>
          {hasChildren && isExpanded && (
            <div>{node.children!.map((child) => <Render key={child.id} node={child} depth={depth + 1} />)}</div>
          )}
        </div>
      )
    }
    return Render
  }, [expanded, value, matchesKeyword, toggleExpand, showMemberCount, handlePickNode])

  const TreeNode = renderNode

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
              triggerClassName,
            )}
            aria-expanded={open}
            aria-haspopup="listbox"
          >
            <span className="min-w-0 flex-1 truncate text-left">{displayLabel}</span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-60" />
          </Button>
        </PopoverTrigger>
      </div>
      <PopoverContent
        align="start"
        sideOffset={4}
        className={cn(
          "max-h-[min(70vh,420px)] w-[min(100vw-2rem,420px)] max-w-[min(100vw-2rem,420px)] p-2",
          contentClassName,
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
                "w-full rounded-md px-2 py-2 text-left text-sm hover:bg-accent",
                value == null && "bg-accent font-medium",
              )}
              onClick={handlePickNone}
            >
              {noneText}
            </button>
          )}
          {nodes.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              {emptyText ?? t("system.treeDepartmentSelectEmpty")}
            </p>
          ) : (
            <>
              <SearchInput
                placeholder={searchPh}
                className="mb-1 shrink-0"
                onChange={(e) => setKeyword(e.target.value)}
              />
              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {nodes.map((node) => (
                  <TreeNode key={node.id} node={node} depth={0} />
                ))}
              </div>
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
