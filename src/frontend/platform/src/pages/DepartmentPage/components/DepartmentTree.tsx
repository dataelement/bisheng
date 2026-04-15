import { SearchInput } from "@/components/bs-ui/input"
import { cn } from "@/utils"
import { DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

/** 每层缩进宽度（px），侧栏内要一眼能看出父子关系 */
const TREE_INDENT_PER_LEVEL = 22

interface DepartmentTreeProps {
  data: DepartmentTreeNode[]
  selectedDeptId: string | null
  onSelect: (node: DepartmentTreeNode) => void
  onCreateChild: (parentId: number) => void
}

export function DepartmentTree({ data, selectedDeptId, onSelect, onCreateChild }: DepartmentTreeProps) {
  const { t } = useTranslation()
  const [keyword, setKeyword] = useState("")
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  // Auto-expand root nodes on mount
  useEffect(() => {
    if (data.length > 0) {
      setExpanded((prev) => {
        const next = new Set(prev)
        for (const n of data) next.add(n.id)
        return next
      })
    }
  }, [data])

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
      const gutterWidth = depth * TREE_INDENT_PER_LEVEL

      return (
        <div key={node.id}>
          <div
            className={cn(
              "group flex cursor-pointer items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent",
              isSelected && "bg-accent font-medium",
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
            <span className="flex-1 truncate">{node.name}</span>
            <span className="mr-1 text-xs text-muted-foreground tabular-nums">{node.member_count}</span>
            {/* Quick create child button */}
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
