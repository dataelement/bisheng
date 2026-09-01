import { Checkbox } from "~/components/ui/Checkbox";
import {
  getCreationGrantSubjects,
  getResourceGrantDepartmentChildren,
  getResourceGrantDepartmentPathTree,
  searchResourceGrantDepartments,
} from "~/api/permission";
import type {
  GrantDepartmentNode,
  ResourceType,
  SelectedSubject,
} from "~/api/permission";
import { Outlined } from "bisheng-icons";
import { Loader2, Search } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { PermissionEmptyState } from "./PermissionEmptyState";
import {
  PERMISSION_SUBJECT_ICON_CLASS,
  PERMISSION_SUBJECT_LIST_CLASS,
  PERMISSION_SUBJECT_ROW_CLASS,
  PERMISSION_SUBJECT_ROW_DISABLED_CLASS,
  PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS,
  PERMISSION_SUBJECT_SLOT_CLASS,
  permissionSubjectIndent,
} from "./permissionDialogStyles";
import { useGrantDepartmentTree } from "./useGrantDepartmentTree";

/**
 * F038: client authorization department picker. Lazy browse/search; multi-select
 * with implicit selection determined by the materialized `path` (decision 9) and
 * "include children" applied all-or-nothing — the grant truth is the explicit
 * picks + the global include-children flag, the backend expands subtrees
 * (decision 10). No client-side subtree materialization.
 */

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType: ResourceType;
  resourceId?: string;
  mode?: "create" | "resource";
  includeChildren: boolean;
  onSelectionSummaryChange?: (v: SelectedSubject[]) => void;
  disabledIds?: number[];
  grantDepartmentChildrenApi?: typeof getResourceGrantDepartmentChildren;
  grantDepartmentSearchApi?: typeof searchResourceGrantDepartments;
  grantDepartmentPathTreeApi?: typeof getResourceGrantDepartmentPathTree;
  creationGrantSubjectsApi?: typeof getCreationGrantSubjects;
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  mode = "resource",
  includeChildren,
  onSelectionSummaryChange,
  disabledIds = [],
  grantDepartmentChildrenApi,
  grantDepartmentSearchApi,
  grantDepartmentPathTreeApi,
  creationGrantSubjectsApi,
}: SubjectSearchDepartmentProps) {
  const localize = useLocalize();
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);

  const fetchChildren = grantDepartmentChildrenApi ?? getResourceGrantDepartmentChildren;
  const fetchSearch = grantDepartmentSearchApi ?? searchResourceGrantDepartments;
  const fetchPathTree = grantDepartmentPathTreeApi ?? getResourceGrantDepartmentPathTree;
  const getCreationSubjects = creationGrantSubjectsApi ?? getCreationGrantSubjects;
  const tree = useGrantDepartmentTree({
    fetchChildren: (parentId, signal) => {
      if (mode === "create") {
        if (resourceType !== "knowledge_space" && resourceType !== "channel") {
          return Promise.resolve([]);
        }
        return getCreationSubjects({
          resourceType,
          subjectType: "department",
          operation: "children",
          parentId,
        }, signal ? { signal } : undefined);
      }
      if (!resourceId) return Promise.resolve([]);
      return fetchChildren(
        resourceType,
        resourceId,
        parentId,
        signal ? { signal } : undefined,
      );
    },
    fetchSearch: (keyword, signal) => {
      if (mode === "create") {
        if (resourceType !== "knowledge_space" && resourceType !== "channel") {
          return Promise.resolve({ roots: [], total_matches: 0, truncated: false });
        }
        return getCreationSubjects({
          resourceType,
          subjectType: "department",
          operation: "search",
          keyword,
          limit: 50,
        }, signal ? { signal } : undefined);
      }
      if (!resourceId) {
        return Promise.resolve({ roots: [], total_matches: 0, truncated: false });
      }
      return fetchSearch(
        resourceType,
        resourceId,
        keyword,
        50,
        signal ? { signal } : undefined,
      );
    },
    fetchPathTree: (departmentId, signal) => {
      if (mode === "create") {
        if (resourceType !== "knowledge_space" && resourceType !== "channel") {
          return Promise.resolve({ roots: [], total_matches: 0, truncated: false });
        }
        return getCreationSubjects({
          resourceType,
          subjectType: "department",
          operation: "path_tree",
          departmentId,
        }, signal ? { signal } : undefined);
      }
      if (!resourceId) {
        return Promise.resolve({ roots: [], total_matches: 0, truncated: false });
      }
      return fetchPathTree(
        resourceType,
        resourceId,
        departmentId,
        signal ? { signal } : undefined,
      );
    },
  });

  // Remember each selected dept's path at pick time so implicit selection can be
  // computed by path even after a search swaps the rendered nodes.
  const selectedPathRef = useRef<Map<number, string>>(new Map());
  const revealingIdsRef = useRef<Set<number>>(new Set());

  const departmentSubjects = useMemo(
    () => value.filter((s) => s.type === "department"),
    [value]
  );
  const selectedIdSet = useMemo(
    () => new Set(departmentSubjects.map((s) => s.id)),
    [departmentSubjects]
  );
  const getTreeNode = tree.getNode;
  const revealTreeNode = tree.reveal;

  useEffect(() => {
    for (const subject of departmentSubjects) {
      if (getTreeNode(subject.id) || revealingIdsRef.current.has(subject.id)) continue;
      revealingIdsRef.current.add(subject.id);
      void revealTreeNode(subject.id)
        .catch(() => undefined)
        .finally(() => {
          revealingIdsRef.current.delete(subject.id);
        });
    }
  }, [departmentSubjects, getTreeNode, revealTreeNode]);
  const selectedPaths = departmentSubjects
    .map((s) => tree.getNode(s.id)?.path ?? selectedPathRef.current.get(s.id))
    .filter((p): p is string => !!p);

  // A node is implicitly selected when "include children" is on and one of the
  // explicitly-selected departments is its ancestor (path prefix). Decision 9.
  const isImplicit = (node: GrantDepartmentNode): boolean =>
    includeChildren &&
    !selectedIdSet.has(node.id) &&
    !!node.path &&
    selectedPaths.some((sp) => node.path !== sp && node.path.startsWith(sp));

  // Summary = the explicit department picks (decision 10: subtree coverage is
  // conveyed by the include-children flag, not enumerated client-side).
  useEffect(() => {
    onSelectionSummaryChange?.(departmentSubjects);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, onSelectionSummaryChange]);

  const toggle = (node: GrantDepartmentNode) => {
    if (disabledIdSet.has(node.id)) return;
    if (selectedIdSet.has(node.id)) {
      onChange(value.filter((s) => s.type !== "department" || s.id !== node.id));
      return;
    }
    // Implicitly-selected children can't be picked/unpicked individually; the
    // user toggles coverage via the parent's include-children (decision 10).
    if (isImplicit(node)) return;
    if (node.path) selectedPathRef.current.set(node.id, node.path);
    onChange([
      ...value,
      { type: "department", id: node.id, name: node.name, include_children: includeChildren },
    ]);
  };

  const searchMode = tree.searchMode;
  const browseRoots = tree.rootIds
    .map((id) => tree.getNode(id))
    .filter((n): n is GrantDepartmentNode => !!n);
  const roots = searchMode ? tree.searchRoots : browseRoots;
  const busy = searchMode ? tree.searching : tree.initialLoading;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-3" />
        <input
          type="text"
          placeholder={localize("com_permission.search_department")}
          value={tree.keyword}
          onChange={(e) => tree.setKeyword(e.target.value)}
          className="h-8 w-full rounded-md border border-border-base bg-white pl-9 pr-3 text-[14px] text-text-1 outline-none transition-colors placeholder:text-text-3 focus:border-border-deep"
        />
      </div>
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto rounded-md border border-border-base">
        {busy && (
          <div className="flex items-center justify-center gap-2 py-4 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            {localize("com_ui_loading")}
          </div>
        )}
        {!busy && roots.length === 0 && (
          <PermissionEmptyState message={localize("com_permission.empty_departments")} />
        )}
        {!busy && roots.length > 0 && (
          <div className={PERMISSION_SUBJECT_LIST_CLASS}>
            {roots.map((node) => (
              <DepartmentRow
                key={node.id}
                node={node}
                depth={0}
                searchMode={searchMode}
                tree={tree}
                selectedIdSet={selectedIdSet}
                isImplicit={isImplicit}
                disabledIdSet={disabledIdSet}
                onToggle={toggle}
              />
            ))}
          </div>
        )}
        {searchMode && tree.truncated && (
          <div className="px-2 py-1.5 text-center text-xs text-gray-400">
            {localize("com_permission.search_truncated")}
          </div>
        )}
      </div>
    </div>
  );
}

function DepartmentRow({
  node,
  depth,
  searchMode,
  tree,
  selectedIdSet,
  isImplicit,
  disabledIdSet,
  onToggle,
}: {
  node: GrantDepartmentNode;
  depth: number;
  searchMode: boolean;
  tree: ReturnType<typeof useGrantDepartmentTree>;
  selectedIdSet: Set<number>;
  isImplicit: (n: GrantDepartmentNode) => boolean;
  disabledIdSet: Set<number>;
  onToggle: (n: GrantDepartmentNode) => void;
}) {
  const localize = useLocalize();

  const childNodes: GrantDepartmentNode[] = searchMode
    ? node.children ?? []
    : (tree.getChildIds(node.id) ?? [])
        .map((id) => tree.getNode(id))
        .filter((n): n is GrantDepartmentNode => !!n);
  const isExpanded = searchMode ? true : tree.expanded.has(node.id);
  const isLoading = tree.loadingIds.has(node.id);
  const explicit = selectedIdSet.has(node.id);
  const granted = disabledIdSet.has(node.id);
  const implicit = !explicit && !granted && isImplicit(node);
  const isChecked = explicit || implicit;
  const isDisabled = granted || implicit;

  const handleActivate = () => {
    if (granted || implicit) return;
    onToggle(node);
  };

  return (
    <>
      <div
        data-depth={depth}
        className={cn(
          PERMISSION_SUBJECT_ROW_CLASS,
          isDisabled ? PERMISSION_SUBJECT_ROW_DISABLED_CLASS : PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS,
        )}
        style={{ paddingLeft: permissionSubjectIndent(depth) }}
        onClick={handleActivate}
      >
        {/* Switcher slot: 20×20 wrapper, 16×16 chevron that rotates on expand.
            A department with no children renders the slot empty so its checkbox
            still lines up with the siblings that do have one. */}
        {node.has_children ? (
          <button
            type="button"
            className={cn(PERMISSION_SUBJECT_SLOT_CLASS, "rounded")}
            aria-label={isExpanded ? "Collapse department" : "Expand department"}
            onClick={(e) => {
              e.stopPropagation();
              if (!searchMode) tree.toggle(node);
            }}
          >
            {isLoading ? (
              <Loader2 className="size-3.5 animate-spin text-text-3" />
            ) : (
              <Outlined.Right
                className={cn(
                  PERMISSION_SUBJECT_ICON_CLASS,
                  "transition-transform duration-150",
                  isExpanded && "rotate-90",
                )}
              />
            )}
          </button>
        ) : (
          <span className={PERMISSION_SUBJECT_SLOT_CLASS} />
        )}
        <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
          <Checkbox
            className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
            checked={isChecked}
            disabled={isDisabled}
            onClick={(e) => e.stopPropagation()}
            onCheckedChange={handleActivate}
          />
        </div>
        {/* Icon slot: 20×20 wrapper, 16×16 department icon. */}
        <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
          <Outlined.City className={PERMISSION_SUBJECT_ICON_CLASS} />
        </div>
        <span className="min-w-0 truncate pl-1" title={node.name}>{node.name}</span>
        {granted && (
          <span className="ml-auto shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {localize("com_permission.already_granted")}
          </span>
        )}
      </div>
      {node.has_children &&
        isExpanded &&
        childNodes.map((child) => (
          <DepartmentRow
            key={child.id}
            node={child}
            depth={depth + 1}
            searchMode={searchMode}
            tree={tree}
            selectedIdSet={selectedIdSet}
            isImplicit={isImplicit}
            disabledIdSet={disabledIdSet}
            onToggle={onToggle}
          />
        ))}
    </>
  );
}
