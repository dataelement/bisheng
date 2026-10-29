import { SubjectIdentity } from "./SubjectIdentity";
import { Checkbox } from "@bisheng/ui";
import { Button, SearchInput, Tag } from "@bisheng/ui";
import { getDepartmentChildren, searchDepartments } from "~/api/permission";
import type { GrantDepartmentNode, ResourceType, SelectedSubject } from "~/api/permission";
import { Outlined } from "bisheng-icons";
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

export interface SubjectSearchDepartmentProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType: ResourceType;
  resourceId: string;
  includeChildren: boolean;
  onSelectionSummaryChange?: (v: SelectedSubject[]) => void;
  disabledIds?: number[];
  /** Existing department grants whose include-children scope covers descendants. */
  disabledSubtreeRootIds?: number[];
  /** subjectId -> the permission model(s) that subject already holds here. */
  grantedLabels?: Record<string, string>;
  departmentChildrenApi?: typeof getDepartmentChildren;
  departmentSearchApi?: typeof searchDepartments;
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  includeChildren,
  onSelectionSummaryChange,
  disabledIds = [],
  disabledSubtreeRootIds = [],
  grantedLabels = {},
  departmentChildrenApi,
  departmentSearchApi,
}: SubjectSearchDepartmentProps) {
  const localize = useLocalize();
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);
  const disabledSubtreeRootIdSet = useMemo(() => new Set(disabledSubtreeRootIds), [disabledSubtreeRootIds]);

  const fetchChildren = departmentChildrenApi ?? getDepartmentChildren;
  const fetchSearch = departmentSearchApi ?? searchDepartments;
  const tree = useGrantDepartmentTree({
    fetchChildren: (parentId, signal) =>
      fetchChildren(resourceType, resourceId, parentId, signal ? { signal } : undefined),
    fetchSearch: (keyword, signal) =>
      fetchSearch(resourceType, resourceId, keyword, 50, signal ? { signal } : undefined),
  });

  // Remember each selected dept's path at pick time so implicit selection can be
  // computed by path even after a search swaps the rendered nodes.
  const selectedPathRef = useRef<Map<number, string>>(new Map());

  const departmentSubjects = useMemo(() => value.filter((s) => s.type === "department"), [value]);
  const selectedIdSet = useMemo(() => new Set(departmentSubjects.map((s) => s.id)), [departmentSubjects]);
  const selectedPaths = departmentSubjects
    .map((s) => s.departmentTreePath ?? tree.getNode(s.id)?.path ?? selectedPathRef.current.get(s.id))
    .filter((p): p is string => !!p);

  // A node is implicitly selected when "include children" is on and one of the
  // explicitly-selected departments is its ancestor (path prefix). Decision 9.
  const isImplicit = (node: GrantDepartmentNode): boolean =>
    includeChildren &&
    !selectedIdSet.has(node.id) &&
    !!node.path &&
    selectedPaths.some((sp) => node.path !== sp && node.path.startsWith(sp));

  const isCoveredByDisabledSubtree = (node: GrantDepartmentNode): boolean =>
    isDepartmentPathCovered(node.path, disabledSubtreeRootIdSet);

  // Summary = the explicit department picks (decision 10: subtree coverage is
  // conveyed by the include-children flag, not enumerated client-side).
  useEffect(() => {
    onSelectionSummaryChange?.(departmentSubjects);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, onSelectionSummaryChange]);

  const departmentPath = (node: GrantDepartmentNode) => {
    const searchNodes = new Map<number, GrantDepartmentNode>();
    const collect = (nodes: GrantDepartmentNode[]) =>
      nodes.forEach((item) => {
        searchNodes.set(item.id, item);
        collect(item.children ?? []);
      });
    collect(tree.searchRoots);
    return (
      node.path
        .split("/")
        .filter(Boolean)
        .map((id) => searchNodes.get(Number(id))?.name ?? tree.getNode(Number(id))?.name)
        .filter(Boolean)
        .join(" / ") || node.name
    );
  };
  const toggle = (node: GrantDepartmentNode) => {
    if (tree.searching || tree.searchInput.tooLong || tree.searchInput.composing) return;
    if (disabledIdSet.has(node.id) || isCoveredByDisabledSubtree(node)) return;
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
      {
        type: "department",
        id: node.id,
        name: node.name,
        externalId: node.external_id,
        departmentPath: departmentPath(node),
        departmentTreePath: node.path,
        include_children: includeChildren,
      },
    ]);
  };

  const searchMode = tree.searchMode;
  const browseRoots = tree.rootIds.map((id) => tree.getNode(id)).filter((n): n is GrantDepartmentNode => !!n);
  const roots = searchMode ? tree.searchRoots : browseRoots;
  const loadError = searchMode ? tree.searchError : tree.rootError;
  const retry = searchMode ? tree.retrySearch : tree.retryRoot;
  const blocked = tree.searchInput.tooLong || tree.searchInput.composing;
  const busy = blocked || (searchMode ? tree.searching : tree.initialLoading);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <SearchInput
          clearLabel={localize("com_ui_clear")}
          placeholder={localize("com_permission.search_department")}
          aria-invalid={tree.searchInput.tooLong}
          onCompositionStart={tree.searchInput.onCompositionStart}
          onCompositionEnd={tree.searchInput.onCompositionEnd}
          onPaste={tree.searchInput.onPaste}
          value={tree.keyword}
          onChange={(e) => tree.setKeyword(e.target.value)}
          className="w-full"
        />
      </div>
      {tree.searchInput.tooLong && (
        <p role="alert" className="text-caption text-danger">
          {localize("com_permission.search_too_long")}
        </p>
      )}
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto rounded-md border border-border-base">
        {busy && !blocked && (
          <div className="flex items-center justify-center gap-2 py-4 text-sm text-text-3">
            <Outlined.Loading className="size-4 animate-spin" />
            {localize("com_ui_loading")}
          </div>
        )}
        {!busy && loadError && (
          <div className="flex flex-col items-center gap-2 py-4 text-body-sm text-text-3">
            <span>{localize("com_permission.load_failed")}</span>
            <Button size="small" color="default" variant="outlined" onClick={retry}>
              {localize("com_ui_retry")}
            </Button>
          </div>
        )}
        {!busy && !loadError && roots.length === 0 && (
          <PermissionEmptyState
            message={localize(
              searchMode ? "com_permission.empty_search" : "com_permission.empty_departments",
            )}
          />
        )}
        {!busy && !loadError && roots.length > 0 && (
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
                isCoveredByDisabledSubtree={isCoveredByDisabledSubtree}
                disabledIdSet={disabledIdSet}
                grantedLabels={grantedLabels}
                onToggle={toggle}
              />
            ))}
          </div>
        )}
        {searchMode && tree.truncated && (
          <div className="px-2 py-1.5 text-center text-caption text-text-3">
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
  isCoveredByDisabledSubtree,
  disabledIdSet,
  grantedLabels,
  onToggle,
  parentPath = "",
}: {
  node: GrantDepartmentNode;
  depth: number;
  searchMode: boolean;
  tree: ReturnType<typeof useGrantDepartmentTree>;
  selectedIdSet: Set<number>;
  isImplicit: (n: GrantDepartmentNode) => boolean;
  isCoveredByDisabledSubtree: (n: GrantDepartmentNode) => boolean;
  disabledIdSet: Set<number>;
  grantedLabels: Record<string, string>;
  onToggle: (n: GrantDepartmentNode) => void;
  parentPath?: string;
}) {
  const localize = useLocalize();
  const nodePath = parentPath ? `${parentPath} / ${node.name}` : node.name;

  const childNodes: GrantDepartmentNode[] = searchMode
    ? (node.children ?? [])
    : (tree.getChildIds(node.id) ?? [])
        .map((id) => tree.getNode(id))
        .filter((n): n is GrantDepartmentNode => !!n);
  const isExpanded = searchMode ? true : tree.expanded.has(node.id);
  const isLoading = tree.loadingIds.has(node.id);
  const explicit = selectedIdSet.has(node.id);
  const granted = disabledIdSet.has(node.id);
  const coveredByGrantedSubtree = !granted && isCoveredByDisabledSubtree(node);
  const grantedLabel = grantedLabels[String(node.id)];
  const implicit = !explicit && !granted && !coveredByGrantedSubtree && isImplicit(node);
  // Already-granted nodes read as checked too — an empty box next to the
  // "already granted" badge reads as a bug.
  const isChecked = explicit || implicit || granted || coveredByGrantedSubtree;
  const isDisabled = granted || implicit || coveredByGrantedSubtree;

  const handleActivate = () => {
    if (granted || implicit || coveredByGrantedSubtree) return;
    onToggle(node);
  };

  return (
    <>
      <div
        data-depth={depth}
        className={cn(
          PERMISSION_SUBJECT_ROW_CLASS,
          "!h-auto min-h-8 py-1",
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
              <Outlined.Loading className="size-3.5 animate-spin text-text-3" />
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
            className="peer border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
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
        <div className="min-w-0 pl-1">
          <span className="block truncate" title={node.name}>
            {node.name}
          </span>
          <SubjectIdentity type="department" externalId={node.external_id} path={nodePath} />
        </div>
        {(grantedLabel || granted || coveredByGrantedSubtree) && (
          <Tag size="small" className="ml-auto shrink-0">
            {grantedLabel
              ? localize("com_permission.already_granted_as", {
                  model: grantedLabel,
                })
              : localize("com_permission.already_granted")}
          </Tag>
        )}
      </div>
      {!searchMode && isExpanded && tree.failedLayerIds.has(node.id) && (
        <div
          className="flex items-center gap-2 py-1 text-caption text-text-3"
          style={{ paddingLeft: permissionSubjectIndent(depth + 1) }}
        >
          <span>{localize("com_permission.load_failed")}</span>
          <Button size="small" color="default" variant="outlined" onClick={() => tree.retryLayer(node.id)}>
            {localize("com_ui_retry")}
          </Button>
        </div>
      )}
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
            isCoveredByDisabledSubtree={isCoveredByDisabledSubtree}
            disabledIdSet={disabledIdSet}
            grantedLabels={grantedLabels}
            onToggle={onToggle}
            parentPath={nodePath}
          />
        ))}
    </>
  );
}

export function isDepartmentPathCovered(
  path: string | undefined,
  subtreeRootIds: ReadonlySet<number>,
): boolean {
  if (!path || subtreeRootIds.size === 0) return false;
  return path.split("/").some((segment) => segment !== "" && subtreeRootIds.has(Number(segment)));
}
