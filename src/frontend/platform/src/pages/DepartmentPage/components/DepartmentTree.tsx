import { SearchInput } from "@/components/bs-ui/input"
import { DepartmentTreeNode } from "@/types/api/department"
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

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

      return (
        <div key={node.id}>
          <div
            className={`group flex cursor-pointer items-center rounded-md px-2 py-1.5 text-sm hover:bg-accent ${
              isSelected ? "bg-accent font-medium" : ""
            }`}
            style={{ paddingLeft: `${depth * 16 + 8}px` }}
            onClick={() => onSelect(node)}
          >
            {/* Expand/collapse */}
            <span
              className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center"
              onClick={(e) => hasChildren && toggleExpand(node.id, e)}
            >
              {hasChildren ? (
                isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )
              ) : null}
            </span>
            <Building2 className="mr-1.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="flex-1 truncate">{node.name}</span>
            <span className="mr-1 text-xs text-muted-foreground">{node.member_count}</span>
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
