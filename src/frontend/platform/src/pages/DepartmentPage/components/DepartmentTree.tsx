import { SearchInput } from "@/components/bs-ui/input"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip"
import { cn } from "@/utils"
import { DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

/** 每层缩进宽度（px），侧栏内要一眼能看出父子关系 */
const TREE_INDENT_PER_LEVEL = 22

/** 默认只展开到「第一级」（仅顶层根部门展开，子部门默认折叠），避免大树一次展开过多。 */
const DEFAULT_EXPAND_MAX_DEPTH = 1

interface DepartmentTreeProps {
  data: DepartmentTreeNode[]
  selectedDeptId: string | null
  onSelect: (node: DepartmentTreeNode) => void
  onCreateChild: (parentId: number) => void
  /** 父组件请求将某部门行滚入可视区域（如全组织搜索定位）；requestId 递增可重复定位同一部门 */
  scrollRequest?: { deptId: string; requestId: number } | null
  onScrollRequestHandled?: () => void
}

function findPathToDept(
  nodes: DepartmentTreeNode[],
  deptId: string
): DepartmentTreeNode[] | null {
  for (const n of nodes) {
    if (n.dept_id === deptId) return [n]
    if (n.children?.length) {
      const sub = findPathToDept(n.children, deptId)
      if (sub) return [n, ...sub]
    }
  }
  return null
}

export function DepartmentTree({
  data,
  selectedDeptId,
  onSelect,
  onCreateChild,
  scrollRequest,
  onScrollRequestHandled,
}: DepartmentTreeProps) {
  const { t } = useTranslation()
  const [keyword, setKeyword] = useState("")
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  /** 仅首次有数据时应用「默认只展开第一级」；后续 data 刷新（建部门、保存等）不重置，保留用户展开状态 */
  const defaultExpandAppliedRef = useRef(false)
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  useEffect(() => {
    if (!scrollRequest || !data.length) return
    const path = findPathToDept(data, scrollRequest.deptId)
    if (!path) {
      onScrollRequestHandled?.()
      return
    }
    setExpanded((prev) => {
      const next = new Set(prev)
      for (let i = 0; i < path.length - 1; i++) {
        next.add(path[i].id)
      }
      return next
    })
    const t = window.setTimeout(() => {
      const el = rowRefs.current.get(scrollRequest.deptId)
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" })
      onScrollRequestHandled?.()
    }, 80)
    return () => window.clearTimeout(t)
  }, [scrollRequest, data, onScrollRequestHandled])

  const collectDefaultExpandedIds = useCallback(
    (
      nodes: DepartmentTreeNode[],
      maxDepth: number,
      currentDepth = 0
    ): number[] => {
      const ids: number[] = []
      for (const n of nodes) {
        if (currentDepth >= maxDepth) continue
        ids.push(n.id)
        if (n.children?.length) {
          ids.push(
            ...collectDefaultExpandedIds(n.children, maxDepth, currentDepth + 1)
          )
        }
      }
      return ids
    },
    []
  )

  // 进入页面后首次拿到树数据时：默认仅展开第一级；之后不因 refetch 重置展开
  useEffect(() => {
    if (data.length === 0) return
    if (defaultExpandAppliedRef.current) return
    setExpanded(new Set(collectDefaultExpandedIds(data, DEFAULT_EXPAND_MAX_DEPTH)))
    defaultExpandAppliedRef.current = true
  }, [data, collectDefaultExpandedIds])

  const toggleExpand = useCallback((id: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Filter by keyword
  const matchesKeyword = useCallback(
    (node: DepartmentTreeNode): boolean => {
      if (!keyword) return true
      const lower = keyword.toLowerCase()
      if (node.name.toLowerCase().includes(lower)) return true
      return (node.children || []).some(matchesKeyword)
    },
    [keyword]
  )

  // Auto-expand matching nodes
  useEffect(() => {
    if (!keyword) return
    const ids = new Set<number>()
    const collect = (nodes: DepartmentTreeNode[]) => {
      for (const n of nodes) {
        if (matchesKeyword(n) && n.children?.length) {
          ids.add(n.id)
          collect(n.children)
        }
      }
    }
    collect(data)
    setExpanded((prev) => new Set([...prev, ...ids]))
  }, [keyword, data, matchesKeyword])

  const renderNode = useMemo(() => {
    const Render = ({ node, depth }: { node: DepartmentTreeNode; depth: number }) => {
      if (!matchesKeyword(node)) return null
      const hasChildren = node.children && node.children.length > 0
      const isExpanded = expanded.has(node.id)
      const isSelected = node.dept_id === selectedDeptId
      const isArchived = node.status === "archived"
      const gutterWidth = depth * TREE_INDENT_PER_LEVEL

      return (
        <div key={node.id}>
          <div
            ref={(el) => {
              if (el) rowRefs.current.set(node.dept_id, el)
              else rowRefs.current.delete(node.dept_id)
            }}
            className={cn(
              "group flex cursor-pointer items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent",
              isSelected && "bg-accent font-medium",
              isArchived && "opacity-50",
            )}
            onClick={() => onSelect(node)}
          >
            {/* 层级缩进：占位宽度 + 竖线提示从属关系（不依赖仅靠 padding 的微弱差异） */}
            <div
              className="relative shrink-0 self-stretch"
              style={{ width: gutterWidth }}
              aria-hidden
            >
              {depth > 0 && (
                <span
                  className="pointer-events-none absolute right-0 top-1 bottom-1 w-px bg-border"
                  aria-hidden
                />
              )}
            </div>
            {/* Expand/collapse */}
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
            <TooltipProvider delayDuration={250}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="flex-1 truncate">
                    {node.name}
                    {isArchived ? ` ${t("bs:department.archivedTag")}` : ""}
                  </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-md break-all">
                  {node.name}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <span className="mr-1 text-xs text-muted-foreground tabular-nums">{node.member_count}</span>
            {/* Quick create child button — hidden for archived departments */}
            {!isArchived && (
              <button
                className="hidden h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-gray-200 group-hover:flex"
                onClick={(e) => {
                  e.stopPropagation()
                  onCreateChild(node.id)
                }}
                title={t("bs:department.create")}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          {hasChildren && isExpanded && (
            <div>
              {node.children.map((child) => (
                <Render key={child.id} node={child} depth={depth + 1} />
              ))}
            </div>
          )}
        </div>
      )
    }
    return Render
  }, [expanded, selectedDeptId, matchesKeyword, onSelect, onCreateChild, toggleExpand, t])

  const TreeNode = renderNode

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <SearchInput
        placeholder={t("bs:department.search")}
        className="mb-2"
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="flex-1 overflow-y-auto">
        {data.map((node) => (
          <TreeNode key={node.id} node={node} depth={0} />
        ))}
      </div>
    </div>
  )
}
