import { Checkbox } from "~/components/ui/Checkbox";
import { getResourceGrantDepartments } from "~/api/permission";
import type { ResourceType, SelectedSubject } from "~/api/permission";
import { ChevronDown, ChevronRight, Building2, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import {
  departmentMatchesKeyword,
  resolveDepartmentDisplayName,
} from "~/utils/departmentDisplayName";

export interface DepartmentNode {
  id: number;
  dept_id: string;
  name: string;
  short_name?: string | null;
  display_name?: string;
  parent_id: number | null;
  member_count?: number;
  org_level?: string | null;
  children?: DepartmentNode[];
}

function departmentDisplayName(node: DepartmentNode): string {
  return resolveDepartmentDisplayName({
    displayName: node.display_name,
    shortName: node.short_name,
    name: node.name,
  });
}

const ORG_LEVEL_I18N_KEYS: Record<string, string> = {
  company: "com_permission.org_level_company",
  dept: "com_permission.org_level_dept",
  office: "com_permission.org_level_office",
  squad: "com_permission.org_level_squad",
};

/** 对齐后台「组织与成员」树行徽章颜色。 */
function orgLevelBadgeClass(level: string): string {
  switch (level) {
    case "company":
      return "bg-amber-100 text-amber-800";
    case "dept":
      return "bg-sky-100 text-sky-800";
    case "office":
      return "bg-violet-100 text-violet-800";
    case "squad":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-gray-100 text-gray-500";
  }
}

function sortDepartmentTree(nodes: DepartmentNode[]): DepartmentNode[] {
  return nodes
    .map((node) => ({
      ...node,
      children: node.children ? sortDepartmentTree(node.children) : undefined,
    }))
    .sort((left, right) => (
      departmentDisplayName(left).localeCompare(departmentDisplayName(right), "zh-CN")
      || left.name.localeCompare(right.name, "zh-CN")
      || left.id - right.id
    ));
}

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  includeChildren: boolean;
  onIncludeChildrenChange: (v: boolean) => void;
  onSelectionSummaryChange?: (v: SelectedSubject[]) => void;
  disabledIds?: number[];
  loadDepartments?: (config?: { signal?: AbortSignal }) => Promise<DepartmentNode[]>;
  selectionMode?: "multiple" | "single";
  grantDepartmentsApi?: typeof getResourceGrantDepartments;
  searchPlaceholder?: string;
  canSelectNode?: (node: DepartmentNode) => boolean;
  /** 已绑定节点仍禁用；false 时不展示右侧状态文案。 */
  showAlreadyGrantedLabel?: boolean;
  /** 已绑定节点右侧文案 i18n key；默认「已授权」，科室绑定下拉传「已绑定」。 */
  boundDisabledLabelKey?: string;
}

function collectExplicitDepartmentSelections(
  nodes: DepartmentNode[],
  selectedDepartmentsById: Map<number, SelectedSubject>,
  inherited = false
): SelectedSubject[] {
  const out: SelectedSubject[] = [];
  const visited = new Set<number>();

  const walk = (items: DepartmentNode[], prefix: string[], ancestorSelected: boolean) => {
    for (const node of items) {
      const explicitSelection = selectedDepartmentsById.get(node.id);
      const isSelected = ancestorSelected || Boolean(explicitSelection);
      const pathSegments = [...prefix, departmentDisplayName(node)];
      if (isSelected && !visited.has(node.id)) {
        visited.add(node.id);
        out.push({
          type: "department",
          id: node.id,
          name: pathSegments.join("/"),
          include_children: false,
        });
      }

      const nextAncestorSelected = ancestorSelected || Boolean(explicitSelection?.include_children);
      if (node.children?.length) {
        walk(node.children, pathSegments, nextAncestorSelected);
      }
    }
  };

  walk(nodes, [], inherited);
  return out;
}

function collectSelectedAncestorIds(
  nodes: DepartmentNode[],
  selectedIds: Set<number>
): Set<number> {
  const ancestorIds = new Set<number>();

  const walk = (items: DepartmentNode[], ancestorPath: number[]) => {
    for (const node of items) {
      if (selectedIds.has(node.id)) {
        ancestorPath.forEach((id) => ancestorIds.add(id));
      }
      if (node.children?.length) {
        walk(node.children, [...ancestorPath, node.id]);
      }
    }
  };

  walk(nodes, []);
  return ancestorIds;
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  includeChildren,
  onIncludeChildrenChange,
  onSelectionSummaryChange,
  disabledIds = [],
  loadDepartments,
  selectionMode = "multiple",
  grantDepartmentsApi,
  searchPlaceholder,
  canSelectNode,
  showAlreadyGrantedLabel = true,
  boundDisabledLabelKey = "com_permission.already_granted",
}: SubjectSearchDepartmentProps) {
  const localize = useLocalize();
  const [tree, setTree] = useState<DepartmentNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);

  useEffect(() => {
    const controller = new AbortController();

    setLoading(true);
    const request = loadDepartments
      ? loadDepartments({ signal: controller.signal })
      : resourceType && resourceId
        ? (grantDepartmentsApi ?? getResourceGrantDepartments)(resourceType, resourceId, { signal: controller.signal })
        : Promise.resolve([]);

    request
      .then((res) => {
        if (!controller.signal.aborted && res) setTree(sortDepartmentTree(res));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [grantDepartmentsApi, loadDepartments, resourceId, resourceType]);

  const selectedIds = useMemo(() => new Set(value.map((s) => s.id)), [value]);
  const selectedDepartmentsById = useMemo(
    () =>
      new Map(
        value
          .filter((subject) => subject.type === "department")
          .map((subject) => [subject.id, subject] as const)
      ),
    [value]
  );
  const indeterminateIds = useMemo(
    () => selectionMode === "single"
      ? collectSelectedAncestorIds(tree, selectedIds)
      : new Set<number>(),
    [selectedIds, selectionMode, tree]
  );

  useEffect(() => {
    onSelectionSummaryChange?.(
      collectExplicitDepartmentSelections(tree, selectedDepartmentsById)
    );
  }, [onSelectionSummaryChange, selectedDepartmentsById, tree]);

  const toggle = (node: DepartmentNode) => {
    if (disabledIdSet.has(node.id) || (canSelectNode && !canSelectNode(node))) return;
    if (selectionMode === "single") {
      onChange(
        selectedIds.has(node.id)
          ? []
          : [{ type: "department", id: node.id, name: departmentDisplayName(node), include_children: includeChildren }]
      );
      return;
    }
    if (selectedIds.has(node.id)) {
      onChange(value.filter((s) => s.id !== node.id));
    } else {
      onChange([
        ...value,
        { type: "department", id: node.id, name: departmentDisplayName(node), include_children: includeChildren },
      ]);
    }
  };

  const materializeInheritedSelection = useCallback(() => {
    const explicitDepartments = collectExplicitDepartmentSelections(
      tree,
      selectedDepartmentsById
    );
    const nonDepartmentSubjects = value.filter((subject) => subject.type !== "department");
    onIncludeChildrenChange(false);
    onChange([...nonDepartmentSubjects, ...explicitDepartments]);
  }, [onChange, onIncludeChildrenChange, selectedDepartmentsById, tree, value]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const matchesKeyword = useCallback(
    (node: DepartmentNode): boolean => {
      if (!keyword) return true;
      const lower = keyword.toLowerCase();
      if (departmentMatchesKeyword({
        displayName: node.display_name,
        shortName: node.short_name,
        name: node.name,
      }, lower)) return true;
      return (node.children || []).some(matchesKeyword);
    },
    [keyword]
  );

  useEffect(() => {
    if (!keyword) return;
    const ids = new Set<number>();
    const collect = (nodes: DepartmentNode[]) => {
      for (const n of nodes) {
        if (matchesKeyword(n)) {
          ids.add(n.id);
          if (n.children) collect(n.children);
        }
      }
    };
    collect(tree);
    setExpanded(ids);
  }, [tree, keyword, matchesKeyword]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={searchPlaceholder || localize("com_permission.search_department")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]"
        // When nested inside a Radix Dialog (e.g. CreateKnowledgeSpaceDrawer Sheet),
        // portaled Popover content sits outside react-remove-scroll's shard, so wheel
        // events are preventDefault'd at the document level. Pointer-drag on the
        // scrollbar still works; drive scrollTop manually for mouse wheel.
        onWheel={(event) => {
          event.currentTarget.scrollTop += event.deltaY;
        }}
      >
        {loading && (
          <div className="py-4 text-center text-sm text-gray-500">{localize("com_ui_loading")}</div>
        )}
        {!loading && tree.length === 0 && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_permission.empty_departments")}
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
              indeterminateIds={indeterminateIds}
              selectedDepartmentsById={selectedDepartmentsById}
              ancestorIncluded={false}
              disabledIds={disabledIdSet}
              matchesKeyword={matchesKeyword}
              onMaterializeInheritedSelection={materializeInheritedSelection}
              onToggle={toggle}
              onExpand={toggleExpand}
              selectionMode={selectionMode}
              canSelectNode={canSelectNode}
              showAlreadyGrantedLabel={showAlreadyGrantedLabel}
              boundDisabledLabelKey={boundDisabledLabelKey}
            />
          ))}
      </div>
    </div>
  );
}

function TreeNode({
  node, depth, expanded, selectedIds, indeterminateIds, selectedDepartmentsById, ancestorIncluded, disabledIds, matchesKeyword, onMaterializeInheritedSelection, onToggle, onExpand, selectionMode, canSelectNode, showAlreadyGrantedLabel, boundDisabledLabelKey,
}: {
  node: DepartmentNode;
  depth: number;
  expanded: Set<number>;
  selectedIds: Set<number>;
  indeterminateIds: Set<number>;
  selectedDepartmentsById: Map<number, SelectedSubject>;
  ancestorIncluded: boolean;
  disabledIds: Set<number>;
  matchesKeyword: (n: DepartmentNode) => boolean;
  onMaterializeInheritedSelection: () => void;
  onToggle: (n: DepartmentNode) => void;
  onExpand: (id: number) => void;
  selectionMode: "multiple" | "single";
  canSelectNode?: (node: DepartmentNode) => boolean;
  showAlreadyGrantedLabel: boolean;
  boundDisabledLabelKey: string;
}) {
  const localize = useLocalize();
  if (!matchesKeyword(node)) return null;
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expanded.has(node.id);
  const explicitSelection = selectedDepartmentsById.get(node.id);
  const isExplicitlySelected = selectedIds.has(node.id);
  const isCoveredByAncestor = selectionMode === "single"
    && ancestorIncluded
    && !isExplicitlySelected;
  const isImplicitlySelected = selectionMode === "multiple"
    && ancestorIncluded
    && !isExplicitlySelected;
  const isBoundDisabled = disabledIds.has(node.id);
  const isLevelBlocked = Boolean(canSelectNode && !canSelectNode(node));
  const isDisabled = isBoundDisabled || isLevelBlocked;
  const showBoundDisabledLabel =
    isBoundDisabled &&
    showAlreadyGrantedLabel &&
    (!canSelectNode || canSelectNode(node));
  const isChecked = isExplicitlySelected || isImplicitlySelected;
  const isIndeterminate = !isChecked && indeterminateIds.has(node.id);
  const nextAncestorIncluded = ancestorIncluded || Boolean(explicitSelection?.include_children);
  const displayName = departmentDisplayName(node);

  return (
    <>
      <div
        className={`flex items-center gap-1 px-2 py-1.5 ${
          isBoundDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-gray-50"
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => {
          if (isBoundDisabled) return;
          if (isLevelBlocked) {
            if (hasChildren) onExpand(node.id);
            return;
          }
          if (isImplicitlySelected) {
            onMaterializeInheritedSelection();
            return;
          }
          onToggle(node);
        }}
      >
        {hasChildren ? (
          <button
            className="rounded p-0.5 hover:bg-gray-200"
            onClick={(e) => { e.stopPropagation(); onExpand(node.id); }}
          >
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-5" />
        )}
        {isLevelBlocked ? (
          <span className="h-4 w-4 shrink-0" aria-hidden />
        ) : (
          <Checkbox
            checked={isIndeterminate ? "indeterminate" : isChecked}
            disabled={isDisabled}
            onClick={(e) => e.stopPropagation()}
            onCheckedChange={() => {
              if (isDisabled) return;
              if (isImplicitlySelected) {
                onMaterializeInheritedSelection();
                return;
              }
              onToggle(node);
            }}
          />
        )}
        <Building2 className="h-4 w-4 shrink-0 text-gray-400" />
        <span className="min-w-0 truncate text-sm" title={displayName}>
          {displayName}
        </span>
        {node.org_level && ORG_LEVEL_I18N_KEYS[node.org_level] ? (
          <span
            className={cn(
              "ml-1 shrink-0 rounded px-1 py-0.5 text-[10px] font-medium",
              orgLevelBadgeClass(node.org_level),
            )}
          >
            {localize(ORG_LEVEL_I18N_KEYS[node.org_level])}
          </span>
        ) : null}
        {node.member_count != null && (
          <span className="ml-1 text-xs text-gray-400">({node.member_count})</span>
        )}
        {isCoveredByAncestor && (
          <span className="ml-auto shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {localize("com_permission.covered_by_parent_department")}
          </span>
        )}
        {showBoundDisabledLabel && (
          <span className="ml-auto shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {localize(boundDisabledLabelKey)}
          </span>
        )}
      </div>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          selectedIds={selectedIds}
          indeterminateIds={indeterminateIds}
          selectedDepartmentsById={selectedDepartmentsById}
          ancestorIncluded={nextAncestorIncluded}
          disabledIds={disabledIds}
          matchesKeyword={matchesKeyword}
          onMaterializeInheritedSelection={onMaterializeInheritedSelection}
          onToggle={onToggle}
          onExpand={onExpand}
          selectionMode={selectionMode}
          canSelectNode={canSelectNode}
          showAlreadyGrantedLabel={showAlreadyGrantedLabel}
          boundDisabledLabelKey={boundDisabledLabelKey}
        />
      ))}
    </>
  );
}
