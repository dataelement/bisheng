import { SubjectBusinessId } from "../selectComponent/SubjectSearchStatus"
import { LazyDepartmentTree, useLazyDepartmentTree } from "@/components/bs-comp/department"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "@/controllers/API/department"
import {
  getGrantSubjectDepartmentChildrenApi,
  getGrantSubjectDepartmentPathTreeApi,
  searchGrantSubjectDepartmentsApi,
} from "@/controllers/API/permission"
import type { DepartmentTreeNode } from "@/types/api/department"
import { useEffect, useRef } from "react"
import { useTranslation } from "react-i18next"
import { ResourceType, SelectedSubject } from "./types"

/**
 * F038: department subject picker for authorization (knowledge space / channel)
 * and the org tree. Lazy browse/search/locate; multi-select with implicit
 * selection determined by materialized `path` (decision 9) and "include children"
 * applied as all-or-nothing — the grant truth is the explicit picks + the global
 * include-children flag, the backend expands subtrees (decision 10). No
 * client-side subtree materialization.
 */

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
  resourceType?: ResourceType
  resourceId?: string
  allowOrganizationTree?: boolean
  includeChildren?: boolean
  onIncludeChildrenChange?: (v: boolean) => void
  onSelectionSummaryChange?: (v: SelectedSubject[]) => void
  showIncludeChildrenToggle?: boolean
  disabledIds?: number[]
  disabledLabel?: string
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  allowOrganizationTree = false,
  includeChildren = false,
  onIncludeChildrenChange = () => undefined,
  onSelectionSummaryChange,
  showIncludeChildrenToggle = true,
  disabledIds = [],
  disabledLabel,
}: SubjectSearchDepartmentProps) {
  const { t } = useTranslation("permission")
  const disabledIdSet = new Set(disabledIds)

  // Scoped to the resource: the org-management tree answers "which departments
  // do I administer", which a space manager may administer none of — it replied
  // "no permission" and the picker stayed empty. These ask who may be granted
  // THIS resource, and narrow to the bound department for a department space.
  const scoped = Boolean(resourceType && resourceId)
  const tree = useLazyDepartmentTree(
    {
      autoLoad: scoped || allowOrganizationTree,
      cacheKey: scoped
        ? `permission-subject-departments:${resourceType}:${resourceId}`
        : "permission-subject-departments",
      fetchChildren: (p) =>
        scoped
          ? getGrantSubjectDepartmentChildrenApi(resourceType!, resourceId!, p)
          : getDepartmentChildrenApi(p, false),
      fetchSearch: (kw) =>
        scoped
          ? searchGrantSubjectDepartmentsApi(resourceType!, resourceId!, kw)
          : searchDepartmentsApi(kw, false),
      fetchPathTree: (id) =>
        scoped
          ? getGrantSubjectDepartmentPathTreeApi(resourceType!, resourceId!, id)
          : getDepartmentPathTreeApi(id, false),
    }
  )

  // Remember each selected dept's path at pick time so implicit selection can be
  // computed by path even after a search swaps the rendered nodes.
  const selectedPathRef = useRef<Map<number, string>>(new Map())

  const departmentSubjects = value.filter((s) => s.type === "department")
  const selectedIdSet = new Set(departmentSubjects.map((s) => s.id))
  const selectedPaths = departmentSubjects
    .map((s) => s.departmentTreePath ?? tree.getNode(s.id)?.path ?? selectedPathRef.current.get(s.id))
    .filter((p): p is string => !!p)

  // A node is implicitly selected when "include children" is on and one of the
  // explicitly-selected departments is its ancestor (path prefix). Decision 9.
  const isImplicit = (node: DepartmentTreeNode): boolean =>
    includeChildren &&
    !selectedIdSet.has(node.id) &&
    !!node.path &&
    selectedPaths.some((sp) => node.path !== sp && node.path.startsWith(sp))

  // Return every explicit pick so summary consumers preserve other subject types.
  // Subtree coverage remains a flag rather than enumerated descendant picks.
  useEffect(() => {
    onSelectionSummaryChange?.(value)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, onSelectionSummaryChange])

  const displayPath = (node: DepartmentTreeNode): string => {
    const findPath = (nodes: DepartmentTreeNode[], ancestors: string[]): string | undefined => {
      for (const current of nodes) {
        const names = [...ancestors, current.name]
        if (current.id === node.id) return names.join(" / ")
        const found = findPath(current.children || [], names)
        if (found) return found
      }
      return undefined
    }
    return findPath(tree.searchRoots, []) || node.path.split("/").filter(Boolean).map(id => tree.getNode(Number(id))?.name).filter(Boolean).join(" / ") || node.name
  }

  const handleToggle = (node: DepartmentTreeNode) => {
    if (tree.searching || tree.searchFailed || tree.searchTooLong || disabledIdSet.has(node.id)) return
    if (selectedIdSet.has(node.id)) {
      onChange(value.filter((s) => s.type !== "department" || s.id !== node.id))
      return
    }
    // Implicitly-selected children can't be picked/unpicked individually; the
    // user toggles coverage via the parent's include-children (decision 10).
    if (isImplicit(node)) return
    selectedPathRef.current.set(node.id, node.path)
    onChange([
      ...value,
      { type: "department", id: node.id, name: node.name, externalId: node.external_id, departmentPath: displayPath(node), departmentTreePath: node.path, include_children: includeChildren },
    ])
  }

  const renderRowPrefix = (node: DepartmentTreeNode) => {
    const explicit = selectedIdSet.has(node.id)
    const disabled = disabledIdSet.has(node.id)
    const implicit = !explicit && !disabled && isImplicit(node)
    return (
      <Checkbox
        className="mr-1.5 shrink-0"
        checked={explicit || implicit || disabled}
        disabled={disabled || implicit}
        onClick={(e) => e.stopPropagation()}
        onCheckedChange={() => handleToggle(node)}
      />
    )
  }

  const renderRowSuffix = (node: DepartmentTreeNode) => <><SubjectBusinessId kind="department" value={node.external_id} />{
    disabledIdSet.has(node.id) && disabledLabel ? (
      <span
        className="ml-auto max-w-[8rem] shrink-0 truncate text-xs text-muted-foreground"
        title={disabledLabel}
      >
        {disabledLabel}
      </span>
    ) : null}</>

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Must be ``flex flex-col`` so LazyDepartmentTree's ``flex-1`` resolves to a
          bounded height and its inner list actually scrolls (a plain block here
          lets the tree size to content, so it overflows + can't scroll). */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[6px] border border-[#EBECF0]">
        <LazyDepartmentTree
          controller={tree}
          onSelect={handleToggle}
          renderRowPrefix={renderRowPrefix}
          renderRowSuffix={renderRowSuffix}
          isRowDisabled={(n) => disabledIdSet.has(n.id)}
          searchPlaceholder={t("search.department")}
          emptyHint={t("empty.departments")}
          wheelScrollFix
          className="p-1"
        />
      </div>
      {showIncludeChildrenToggle && (
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={includeChildren} onCheckedChange={(v) => onIncludeChildrenChange(v === true)} />
          {t("includeChildren")}
        </label>
      )}
    </div>
  )
}
