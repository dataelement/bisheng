import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ChevronDown, ChevronRight, Building2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { SelectedSubject } from "./types"

interface DepartmentNode {
  id: number
  dept_id: string
  name: string
  parent_id: number | null
  member_count?: number
  children?: DepartmentNode[]
}

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
  includeChildren?: boolean
  onIncludeChildrenChange?: (v: boolean) => void
  showIncludeChildrenToggle?: boolean
  disabledIds?: number[]
  disabledLabel?: string
}

export function SubjectSearchDepartment({
  value,
  onChange,
  includeChildren = false,
  onIncludeChildrenChange = () => undefined,
  showIncludeChildrenToggle = true,
  disabledIds = [],
  disabledLabel,
}: SubjectSearchDepartmentProps) {
  const { t } = useTranslation('permission')
  const [tree, setTree] = useState<DepartmentNode[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const disabledIdSet = new Set(disabledIds)

  useEffect(() => {
    setLoading(true)
    captureAndAlertRequestErrorHoc(getDepartmentTreeApi()).then((res) => {
      if (res) setTree(res)
      setLoading(false)
    })
  }, [])

  const selectedIds = new Set(value.map((s) => s.id))

  const toggle = (node: DepartmentNode) => {
    if (disabledIdSet.has(node.id)) return
    if (selectedIds.has(node.id)) {
      onChange(value.filter((s) => s.id !== node.id))
    } else {
      onChange([...value, {
        type: 'department',
        id: node.id,
        name: node.name,
        include_children: includeChildren,
      }])
    }
  }

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Filter tree nodes by keyword (flat match on name)
  const matchesKeyword = useCallback((node: DepartmentNode): boolean => {
    if (!keyword) return true
    const lower = keyword.toLowerCase()
    if (node.name.toLowerCase().includes(lower)) return true
    return (node.children || []).some(matchesKeyword)
  }, [keyword])

  // Auto-expand nodes that match keyword
  useEffect(() => {
    if (!keyword) return
    const ids = new Set<number>()
    const collect = (nodes: DepartmentNode[]) => {
      for (const n of nodes) {
        if (matchesKeyword(n)) {
          ids.add(n.id)
          if (n.children) collect(n.children)
        }
      }
    }
    collect(tree)
    setExpanded(ids)
  }, [tree, keyword, matchesKeyword])

  return (
    <div className="flex flex-col gap-2">
      <SearchInput
        placeholder={t('search.department')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="max-h-[200px] overflow-y-auto border rounded-md">
        {loading && (
          <div className="py-4 text-center text-sm text-muted-foreground">{t('loading', { ns: 'bs' })}</div>
        )}
        {!loading && tree.length === 0 && (
          <div className="py-4 text-center text-sm text-muted-foreground">
            {t('empty.departments')}
          </div>
        )}
        {!loading &&
          tree.map((node) => (
            <TreeNode
              key={node.id}
              node={node}
              depth={0}
              expanded={expanded}
              selectedIds={selectedIds}
              disabledIds={disabledIdSet}
              disabledLabel={disabledLabel}
              matchesKeyword={matchesKeyword}
              onToggle={toggle}
              onExpand={toggleExpand}
            />
          ))}
      </div>
      {showIncludeChildrenToggle && (
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={includeChildren}
            onCheckedChange={(v) => onIncludeChildrenChange(v === true)}
          />
          {t('includeChildren')}
        </label>
      )}
    </div>
  )
}

function TreeNode({
  node,
  depth,
  expanded,
  selectedIds,
  disabledIds,
  disabledLabel,
  matchesKeyword,
  onToggle,
  onExpand,
}: {
  node: DepartmentNode
  depth: number
  expanded: Set<number>
  selectedIds: Set<number>
  disabledIds: Set<number>
  disabledLabel?: string
  matchesKeyword: (n: DepartmentNode) => boolean
  onToggle: (n: DepartmentNode) => void
  onExpand: (id: number) => void
}) {
  if (!matchesKeyword(node)) return null

  const hasChildren = node.children && node.children.length > 0
  const isExpanded = expanded.has(node.id)
  const isDisabled = disabledIds.has(node.id)

  return (
    <>
      <div
        className={`flex items-center gap-1 px-2 py-1.5 ${
          isDisabled ? "opacity-60" : "cursor-pointer hover:bg-accent"
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <button
            className="p-0.5 rounded hover:bg-muted"
            onClick={(e) => { e.stopPropagation(); onExpand(node.id) }}
          >
            {isExpanded
              ? <ChevronDown className="h-3.5 w-3.5" />
              : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-5" />
        )}
        <Checkbox
          checked={selectedIds.has(node.id)}
          disabled={isDisabled}
          onCheckedChange={() => onToggle(node)}
        />
        <Building2 className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm truncate">{node.name}</span>
        {node.member_count != null && (
          <span className="text-xs text-muted-foreground ml-1">({node.member_count})</span>
        )}
        {isDisabled && disabledLabel && (
          <span className="ml-auto text-xs text-muted-foreground">{disabledLabel}</span>
        )}
      </div>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          selectedIds={selectedIds}
          disabledIds={disabledIds}
          disabledLabel={disabledLabel}
          matchesKeyword={matchesKeyword}
          onToggle={onToggle}
          onExpand={onExpand}
        />
      ))}
    </>
  )
}
