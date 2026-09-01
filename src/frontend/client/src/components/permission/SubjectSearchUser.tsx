import { Checkbox } from "~/components/ui/Checkbox";
import { Button } from "~/components/ui/Button";
import {
  getCreationUserTreeChildren,
  getResourceGrantUserTreeChildren,
  searchCreationUserTree,
  searchResourceGrantUserTree,
} from "~/api/permission";
import type {
  GrantDepartmentNode,
  GrantUser,
  ResourceType,
  SelectedSubject,
} from "~/api/permission";
import { Building2, ChevronDown, ChevronRight, Loader2, Search, User as UserIcon } from "lucide-react";
import { useMemo } from "react";
import { useLocalize } from "~/hooks";
import { PermissionEmptyState } from "./PermissionEmptyState";
import { useGrantUserTree } from "./useGrantUserTree";

/**
 * F038 (中粮定制化): department-tree user picker. Departments are pure
 * navigation (no checkbox); users are leaves under their primary department
 * and support multi-select. Search matches by username and keeps the full
 * ancestor department path so results stay locatable in the tree. Shares the
 * same organization-tree data source and visual language as
 * `SubjectSearchDepartment` — this is not a separate flat list anymore.
 */

interface SubjectSearchUserProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  mode?: "create" | "resource";
  disabledIds?: number[];
  /** subjectId -> the permission model(s) that subject already holds here. */
  grantedLabels?: Record<string, string>;
  grantUserTreeChildrenApi?: typeof getResourceGrantUserTreeChildren;
  grantUserTreeSearchApi?: typeof searchResourceGrantUserTree;
}

const EMPTY_TREE_CHILDREN = { departments: [], users: [], has_more_users: false };
const EMPTY_SEARCH_TREE = { roots: [], total_matches: 0, truncated: false };

export function SubjectSearchUser({
  value,
  onChange,
  resourceType,
  resourceId,
  mode = "resource",
  disabledIds = [],
  grantedLabels = {},
  grantUserTreeChildrenApi,
  grantUserTreeSearchApi,
}: SubjectSearchUserProps) {
  const localize = useLocalize();
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);

  const fetchChildrenApi = grantUserTreeChildrenApi ?? getResourceGrantUserTreeChildren;
  const fetchSearchApi = grantUserTreeSearchApi ?? searchResourceGrantUserTree;

  const tree = useGrantUserTree({
    fetchChildren: (parentId, userPage, signal) => {
      if (mode === "create") {
        if (resourceType !== "knowledge_space" && resourceType !== "channel") {
          return Promise.resolve(EMPTY_TREE_CHILDREN);
        }
        return getCreationUserTreeChildren(
          resourceType,
          parentId,
          { userPage },
          signal ? { signal } : undefined,
        );
      }
      if (!resourceType || !resourceId) return Promise.resolve(EMPTY_TREE_CHILDREN);
      return fetchChildrenApi(
        resourceType,
        resourceId,
        parentId,
        { userPage },
        signal ? { signal } : undefined,
      );
    },
    fetchSearch: (keyword, signal) => {
      if (mode === "create") {
        if (resourceType !== "knowledge_space" && resourceType !== "channel") {
          return Promise.resolve(EMPTY_SEARCH_TREE);
        }
        return searchCreationUserTree(
          resourceType,
          keyword,
          50,
          signal ? { signal } : undefined,
        );
      }
      if (!resourceType || !resourceId) return Promise.resolve(EMPTY_SEARCH_TREE);
      return fetchSearchApi(
        resourceType,
        resourceId,
        keyword,
        50,
        signal ? { signal } : undefined,
      );
    },
  });

  const selectedIds = useMemo(
    () => new Set(value.filter((s) => s.type === "user").map((s) => s.id)),
    [value],
  );

  const toggle = (user: GrantUser) => {
    if (disabledIdSet.has(user.user_id)) return;
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((s) => s.type !== "user" || s.id !== user.user_id));
    } else {
      onChange([...value, { type: "user", id: user.user_id, name: user.user_name }]);
    }
  };

  const searchMode = tree.searchMode;
  const browseRoots = tree.rootIds
    .map((id) => tree.getNode(id))
    .filter((n): n is GrantDepartmentNode => !!n);
  const roots = searchMode ? tree.searchRoots : browseRoots;
  const busy = searchMode ? tree.searching : tree.initialLoading;
  const loadError = searchMode ? tree.searchError : tree.rootError;
  const retry = searchMode ? tree.retrySearch : tree.retryRoot;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-3" />
        <input
          type="text"
          placeholder={localize("com_permission.search_user")}
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
        {!busy && loadError && (
          <div className="flex flex-col items-center gap-2 px-3 py-6 text-body-sm text-text-3">
            <span>{localize("com_permission.load_failed")}</span>
            <Button size="sm" variant="outline" onClick={retry}>
              {localize("com_ui_retry")}
            </Button>
          </div>
        )}
        {!busy && !loadError && roots.length === 0 && (
          <PermissionEmptyState
            message={localize(searchMode ? "com_permission.empty_search" : "com_permission.empty_departments")}
          />
        )}
        {!busy &&
          roots.map((node) => (
            <UserTreeRow
              key={node.id}
              node={node}
              depth={0}
              searchMode={searchMode}
              tree={tree}
              selectedIds={selectedIds}
              disabledIdSet={disabledIdSet}
              grantedLabels={grantedLabels}
              onToggleUser={toggle}
            />
          ))}
        {searchMode && tree.truncated && (
          <div className="px-2 py-1.5 text-center text-xs text-gray-400">
            {localize("com_permission.search_truncated")}
          </div>
        )}
      </div>
    </div>
  );
}

function UserTreeRow({
  node,
  depth,
  searchMode,
  tree,
  selectedIds,
  disabledIdSet,
  grantedLabels,
  onToggleUser,
}: {
  node: GrantDepartmentNode;
  depth: number;
  searchMode: boolean;
  tree: ReturnType<typeof useGrantUserTree>;
  selectedIds: Set<number>;
  disabledIdSet: Set<number>;
  grantedLabels: Record<string, string>;
  onToggleUser: (user: GrantUser) => void;
}) {
  const localize = useLocalize();

  const childDeptNodes: GrantDepartmentNode[] = searchMode
    ? node.children ?? []
    : (tree.getChildIds(node.id) ?? [])
        .map((id) => tree.getNode(id))
        .filter((n): n is GrantDepartmentNode => !!n);
  const users: GrantUser[] = searchMode ? node.users ?? [] : tree.getUsers(node.id);
  const isExpanded = searchMode ? true : tree.expanded.has(node.id);
  const isLoading = !searchMode && tree.loadingIds.has(node.id);
  const hasMoreUsers = !searchMode && tree.hasMoreUsers(node.id);
  const loadingMoreUsers = !searchMode && tree.loadingMoreUserIds.has(node.id);
  const layerFailed = !searchMode && tree.failedLayerIds.has(node.id);
  const loadMoreFailed = !searchMode && tree.failedMoreUserIds.has(node.id);

  const handleToggle = () => {
    if (!searchMode) tree.toggle(node);
  };

  return (
    <>
      <div
        className="flex items-center gap-1 px-2 py-1.5 cursor-pointer hover:bg-gray-50"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleToggle}
      >
        <button
          className="rounded p-0.5 hover:bg-gray-200"
          onClick={(e) => {
            e.stopPropagation();
            handleToggle();
          }}
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />
          ) : isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
          )}
        </button>
        <Building2 className="h-4 w-4 text-gray-400" />
        <span className="min-w-0 truncate text-sm">{node.name}</span>
      </div>
      {isExpanded &&
        childDeptNodes.map((child) => (
          <UserTreeRow
            key={child.id}
            node={child}
            depth={depth + 1}
            searchMode={searchMode}
            tree={tree}
            selectedIds={selectedIds}
            disabledIdSet={disabledIdSet}
            grantedLabels={grantedLabels}
            onToggleUser={onToggleUser}
          />
        ))}
      {isExpanded &&
        users.map((user) => (
          <UserLeafRow
            key={user.user_id}
            user={user}
            depth={depth + 1}
            selected={selectedIds.has(user.user_id)}
            disabled={disabledIdSet.has(user.user_id)}
            onToggle={onToggleUser}
          />
        ))}
      {isExpanded && hasMoreUsers && (
        <div
          className="py-1 text-xs"
          style={{ paddingLeft: `${(depth + 1) * 16 + 8 + 20}px` }}
        >
          {loadingMoreUsers ? (
            <span className="text-gray-400">{localize("com_ui_loading")}</span>
          ) : (
            <button
              type="button"
              className="text-primary hover:underline"
              onClick={() => (loadMoreFailed ? tree.retryMoreUsers(node.id) : tree.loadMoreUsers(node.id))}
            >
              {localize(loadMoreFailed ? "com_ui_retry" : "com_permission.load_more")}
            </button>
          )}
        </div>
      )}
      {isExpanded && layerFailed && (
        <div className="flex items-center gap-2 py-1 text-caption text-text-3" style={{ paddingLeft: `${(depth + 1) * 16 + 8 + 20}px` }}>
          <span>{localize("com_permission.load_failed")}</span>
          <button type="button" className="text-primary hover:underline" onClick={() => tree.retryLayer(node.id)}>
            {localize("com_ui_retry")}
          </button>
        </div>
      )}
    </>
  );
}

function UserLeafRow({
  user,
  depth,
  selected,
  disabled,
  grantedLabel,
  onToggle,
}: {
  user: GrantUser;
  depth: number;
  selected: boolean;
  disabled: boolean;
  grantedLabel?: string;
  onToggle: (user: GrantUser) => void;
}) {
  const localize = useLocalize();
  // User id (external_id) renders right after the username, same layout as
  // the previous flat list.
  const showUserId = !!user.external_id && user.external_id !== user.user_name;

  const handleActivate = () => {
    if (disabled) return;
    onToggle(user);
  };

  return (
    <div
      className={`flex items-center gap-2 px-2 py-2 ${
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-gray-50"
      }`}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      onClick={handleActivate}
    >
      {/* Spacer aligns the checkbox under the parent department's checkbox column
          (departments render a chevron button of the same width in that slot). */}
      <span className="w-5 shrink-0" />
      <Checkbox
        className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
        checked={selected}
        disabled={disabled}
        onClick={(e) => e.stopPropagation()}
        onCheckedChange={handleActivate}
      />
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <UserIcon className="h-4 w-4 shrink-0 text-gray-400" />
        <span className="min-w-0 truncate text-sm" title={user.user_name}>{user.user_name}</span>
        {showUserId && (
          <>
            <span className="h-3 w-px shrink-0 bg-[#D9D9D9]" aria-hidden />
            <span className="shrink-0 truncate text-xs text-text-3" title={user.external_id ?? undefined}>{user.external_id}</span>
          </>
        )}
        {disabled && (
          <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {grantedLabel ?? localize("com_permission.already_granted")}
          </span>
        )}
      </div>
    </div>
  );
}
