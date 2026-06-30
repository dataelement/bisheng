import { SearchInput } from "@/components/bs-ui/input"
import { DepartmentTreeNode } from "@/types/api/department"
import { cn } from "@/utils"
import { Building2, ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { ReactNode, useMemo } from "react"
import { useTranslation } from "react-i18next"
import { LazyDepartmentTree as LazyTreeController } from "./useLazyDepartmentTree"

/** Per-level indent (px), so parent/child nesting reads at a glance. */
const TREE_INDENT_PER_LEVEL = 22

interface LazyDepartmentTreeProps {
  controller: LazyTreeController
  /** dept_id of the currently selected row (for the highlight). */
  selectedDeptId?: string | null
  onSelect?: (node: DepartmentTreeNode) => void
  /** Show the built-in search box (default true). */
  showSearch?: boolean
  searchPlaceholder?: string
  /** Leading slot per row (e.g. a checkbox/radio in pickers). */
  renderRowPrefix?: (node: DepartmentTreeNode) => ReactNode
  /** Trailing slot per row (e.g. create-child button, mount badge in the nav tree). */
  renderRowSuffix?: (node: DepartmentTreeNode) => ReactNode
  /** Rows whose label is rendered disabled (e.g. archived in pickers, already-granted). */
  isRowDisabled?: (node: DepartmentTreeNode) => boolean
  /** Assign each row a ref so callers can scrollIntoView after reveal(). */
  rowRef?: (deptId: string, el: HTMLDivElement | null) => void
  className?: string
  emptyHint?: ReactNode
  /** Drive scrollTop from wheel deltas. Needed when nested in a Radix Popover/
   *  Dialog whose react-remove-scroll preventDefaults native wheel scrolling. */
  wheelScrollFix?: boolean
}

interface RowProps {
  node: DepartmentTreeNode
  depth: number
  searchMode: boolean
  props: LazyDepartmentTreeProps
}

function Row({ node, depth, searchMode, props }: RowProps) {
  const { controller, selectedDeptId, onSelect, renderRowPrefix, renderRowSuffix, isRowDisabled, rowRef } =
    props
  const { t } = useTranslation()

  // Children + expand state differ between browse (normalized, lazy) and search
  // (the backend's pruned tree, rendered fully expanded).
  const childNodes: DepartmentTreeNode[] = searchMode
    ? node.children ?? []
    : (controller.getChildIds(node.id) ?? [])
        .map((id) => controller.getNode(id))
        .filter((n): n is DepartmentTreeNode => !!n)
  const isExpanded = searchMode ? true : controller.expanded.has(node.id)
  const isLoading = controller.loadingIds.has(node.id)
  const isSelected = !!selectedDeptId && node.dept_id === selectedDeptId
  const isArchived = node.status === "archived"
  const disabled = isRowDisabled?.(node) ?? false
  const gutterWidth = depth * TREE_INDENT_PER_LEVEL

  return (
    <div>
      <div
        ref={(el) => rowRef?.(node.dept_id, el)}
        data-depth={depth}
        className={cn(
          "group flex items-center rounded-md py-1.5 pl-1.5 pr-2 text-sm hover:bg-accent",
          onSelect && !disabled && "cursor-pointer",
          isSelected && "bg-accent font-medium",
          (isArchived || disabled) && "opacity-50",
          node.matched && "bg-primary/5"
        )}
        onClick={() => !disabled && onSelect?.(node)}
      >
        <div className="relative shrink-0 self-stretch" style={{ width: gutterWidth }} aria-hidden>
          {depth > 0 && (
            <span className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-border" aria-hidden />
          )}
        </div>
        {/* Expand / collapse — driven by has_children, not by loaded children. */}
        <span
          className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center"
          onClick={(e) => {
            e.stopPropagation()
            if (!searchMode && node.has_children) controller.toggle(node)
          }}
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : node.has_children ? (
            isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
            )
          ) : (
            <span className="block h-3.5 w-3.5" aria-hidden />
          )}
        </span>
        {renderRowPrefix?.(node)}
        <Building2
          className={cn(
            "mr-1.5 h-4 w-4 shrink-0",
            node.is_tenant_root ? "text-primary" : "text-muted-foreground"
          )}
        />
        <span className="flex-1 truncate">
          {node.name}
          {isArchived ? ` ${t("bs:department.archivedTag")}` : ""}
        </span>
        {renderRowSuffix?.(node)}
      </div>
      {node.has_children && isExpanded && childNodes.length > 0 && (
        <div>
          {childNodes.map((child) => (
            <Row key={child.id} node={child} depth={depth + 1} searchMode={searchMode} props={props} />
          ))}
        </div>
      )}
    </div>
  )
}

export function LazyDepartmentTree(props: LazyDepartmentTreeProps) {
  const { controller, showSearch = true, searchPlaceholder, className, emptyHint, wheelScrollFix } = props
  const { t } = useTranslation()

  const browseRoots = useMemo(
    () =>
      controller.rootIds
        .map((id) => controller.getNode(id))
        .filter((n): n is DepartmentTreeNode => !!n),
    [controller.rootIds, controller]
  )

  const searchMode = controller.searchMode
  const roots = searchMode ? controller.searchRoots : browseRoots
  const busy = searchMode ? controller.searching : controller.initialLoading

  return (
    <div className={cn("flex flex-1 flex-col overflow-hidden", className)}>
      {showSearch && (
        <SearchInput
          placeholder={searchPlaceholder ?? t("bs:department.search")}
          className="mb-2"
          value={controller.keyword}
          onChange={(e) => controller.setKeyword(e.target.value)}
        />
      )}
      <div
        className="flex-1 overflow-y-auto"
        onWheel={
          wheelScrollFix
            ? (e) => {
                e.currentTarget.scrollTop += e.deltaY
              }
            : undefined
        }
      >
        {busy ? (
          <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t("loading", { defaultValue: "加载中" })}
          </div>
        ) : roots.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {emptyHint ?? t("bs:department.noResult", { defaultValue: "暂无结果" })}
          </div>
        ) : (
          roots.map((node) => (
            <Row key={node.id} node={node} depth={0} searchMode={searchMode} props={props} />
          ))
        )}
        {searchMode && controller.truncated && (
          <div className="px-2 py-1.5 text-center text-xs text-muted-foreground">
            {t("bs:department.searchTruncated", {
              defaultValue: "结果较多，仅显示部分，请细化关键词",
            })}
          </div>
        )}
      </div>
    </div>
  )
}
