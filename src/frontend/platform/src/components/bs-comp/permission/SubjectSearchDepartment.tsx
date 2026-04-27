import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getResourceGrantDepartmentsApi } from "@/controllers/API/permission"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentTreeNode } from "@/types/api/department"
import { ChevronDown, ChevronRight, Building2 } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { ResourceType, SelectedSubject } from "./types"

const INDENT_PX = 20

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
  resourceType?: ResourceType
  resourceId?: string
  allowOrganizationTree?: boolean
  includeChildren?: boolean
  onIncludeChildrenChange?: (v: boolean) => void
  showIncludeChildrenToggle?: boolean
  disabledIds?: number[]
  disabledLabel?: string
}

function collectExplicitDepartmentSelections(
  nodes: DepartmentTreeNode[],
  selectedDepartmentsById: Map<number, SelectedSubject>,
  prefix: string[] = [],
  inherited = false,
): SelectedSubject[] {
  const out: SelectedSubject[] = []
  const visited = new Set<number>()

  for (const node of nodes) {
    const explicitSelection = selectedDepartmentsById.get(node.id)
    const isSelected = inherited || Boolean(explicitSelection)
    const pathSegments = [...prefix, node.name]
    if (isSelected && !visited.has(node.id)) {
      visited.add(node.id)
      out.push({
        type: 'department',
        id: node.id,
        name: pathSegments.join('/'),
        include_children: false,
      })
    }

    if (node.children?.length) {
      const childSelections = collectExplicitDepartmentSelections(
        node.children,
        selectedDepartmentsById,
        pathSegments,
        inherited || Boolean(explicitSelection?.include_children),
      )
      for (const child of childSelections) {
        if (!visited.has(child.id)) {
          visited.add(child.id)
          out.push(child)
        }
      }
    }
  }

  return out
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  allowOrganizationTree = false,
  includeChildren = false,
  onIncludeChildrenChange = () => undefined,
  showIncludeChildrenToggle = true,
  disabledIds = [],
  disabledLabel,
}: SubjectSearchDepartmentProps) {
  const { t } = useTranslation('permission')
  const [tree, setTree] = useState<DepartmentTreeNode[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const disabledIdSet = new Set(disabledIds)

  useEffect(() => {
    const request = resourceType && resourceId
      ? getResourceGrantDepartmentsApi(resourceType, resourceId)
      : allowOrganizationTree
        ? getDepartmentTreeApi()
        : null

    if (!request) {
      setTree([])
      setLoading(false)
      return
    }

    setLoading(true)
    captureAndAlertRequestErrorHoc(request).then((res) => {
      if (res) setTree(res)
      setLoading(false)
    })
  }, [allowOrganizationTree, resourceId, resourceType])

  const selectedIds = new Set(value.map((s) => s.id))
  const selectedDepartmentsById = useMemo(
    () =>
      new Map(
        value
          .filter((subject) => subject.type === 'department')
          .map((subject) => [subject.id, subject] as const),
      ),
    [value],
  )

  const toggle = (node: DepartmentTreeNode, pathLabel: string) => {
    if (disabledIdSet.has(node.id)) return
    if (selectedIds.has(node.id)) {
      onChange(value.filter((s) => s.id !== node.id))
    } else {
      onChange([...value, {
        type: 'department',
        id: node.id,
        name: pathLabel,
        include_children: includeChildren,
      }])
    }
  }

  const materializeInheritedSelection = useCallback(() => {
    const explicitDepartments = collectExplicitDepartmentSelections(
      tree,
      selectedDepartmentsById,
    )
    const nonDepartmentSubjects = value.filter((subject) => subject.type !== 'department')
    onIncludeChildrenChange(false)
    onChange([...nonDepartmentSubjects, ...explicitDepartments])
  }, [onChange, onIncludeChildrenChange, selectedDepartmentsById, tree, value])

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const matchesKeyword = useCallback((node: DepartmentTreeNode): boolean => {
    if (!keyword) return true
    const lower = keyword.toLowerCase()
    if (node.name.toLowerCase().includes(lower)) return true
    return (node.children || []).some(matchesKeyword)
  }, [keyword])

  useEffect(() => {
    if (!keyword) return
    const ids = new Set<number>()
    const collect = (nodes: DepartmentTreeNode[]) => {
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
    <div className="flex min-h-0 flex-col gap-2">
      <SearchInput
        placeholder={t('search.department')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="min-h-[120px] max-h-[clamp(120px,calc(100vh-24rem),260px)] overflow-y-auto rounded-md border">
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
              pathSegments={[node.name]}
              expanded={expanded}
              selectedIds={selectedIds}
              selectedDepartmentsById={selectedDepartmentsById}
              ancestorIncluded={false}
              disabledIds={disabledIdSet}
              disabledLabel={disabledLabel}
              matchesKeyword={matchesKeyword}
              onMaterializeInheritedSelection={materializeInheritedSelection}
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
  pathSegments,
  expanded,
  selectedIds,
  selectedDepartmentsById,
  ancestorIncluded,
  disabledIds,
  disabledLabel,
  matchesKeyword,
  onMaterializeInheritedSelection,
  onToggle,
  onExpand,
}: {
  node: DepartmentTreeNode
  depth: number
  pathSegments: string[]
  expanded: Set<number>
  selectedIds: Set<number>
  selectedDepartmentsById: Map<number, SelectedSubject>
  ancestorIncluded: boolean
  disabledIds: Set<number>
  disabledLabel?: string
  matchesKeyword: (n: DepartmentTreeNode) => boolean
  onMaterializeInheritedSelection: () => void
  onToggle: (n: DepartmentTreeNode, pathLabel: string) => void
  onExpand: (id: number) => void
}) {
  if (!matchesKeyword(node)) return null

  const hasChildren = node.children && node.children.length > 0
  const isExpanded = expanded.has(node.id)
  const explicitSelection = selectedDepartmentsById.get(node.id)
  const isExplicitlySelected = selectedIds.has(node.id)
  const isImplicitlySelected = ancestorIncluded && !isExplicitlySelected
  const isDisabled = disabledIds.has(node.id)
  const isChecked = isExplicitlySelected || isImplicitlySelected || isDisabled
  const nextAncestorIncluded = ancestorIncluded || Boolean(explicitSelection?.include_children)
  const pathLabel = pathSegments.join('/')

  return (
    <>
      <div
        className={`flex items-stretch gap-0 pr-2 ${
          isDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-accent"
        }`}
        onClick={() => {
          if (isDisabled) return
          if (isImplicitlySelected) {
            onMaterializeInheritedSelection()
            return
          }
          onToggle(node, pathLabel)
        }}
      >
        <div
          className="shrink-0"
          style={{ width: depth * INDENT_PX }}
          aria-hidden
        />
        <div className="flex min-w-0 flex-1 items-center gap-1 py-1.5 pl-1">
          {hasChildren ? (
            <button
              type="button"
              className="shrink-0 rounded p-0.5 hover:bg-muted"
              onClick={(e) => { e.stopPropagation(); onExpand(node.id) }}
            >
              {isExpanded
                ? <ChevronDown className="h-3.5 w-3.5" />
                : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          ) : (
            <span className="inline-flex w-5 shrink-0 justify-center" />
          )}
          <Checkbox
            checked={isChecked}
            disabled={isDisabled}
            onClick={(e) => e.stopPropagation()}
            onCheckedChange={() => {
              if (isDisabled) return
              if (isImplicitlySelected) {
                onMaterializeInheritedSelection()
                return
              }
              onToggle(node, pathLabel)
            }}
          />
          <Building2 className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 truncate text-sm" title={pathLabel}>
            {node.name}
          </span>
          {node.member_count != null && (
            <span className="shrink-0 text-xs text-muted-foreground">({node.member_count})</span>
          )}
          {isDisabled && disabledLabel && (
            <span className="ml-auto max-w-[8rem] shrink-0 truncate text-xs text-muted-foreground" title={disabledLabel}>{disabledLabel}</span>
          )}
        </div>
      </div>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          pathSegments={[...pathSegments, child.name]}
          expanded={expanded}
          selectedIds={selectedIds}
          selectedDepartmentsById={selectedDepartmentsById}
          ancestorIncluded={nextAncestorIncluded}
          disabledIds={disabledIds}
          disabledLabel={disabledLabel}
          matchesKeyword={matchesKeyword}
          onMaterializeInheritedSelection={onMaterializeInheritedSelection}
          onToggle={onToggle}
          onExpand={onExpand}
        />
      ))}
    </>
  )
}
