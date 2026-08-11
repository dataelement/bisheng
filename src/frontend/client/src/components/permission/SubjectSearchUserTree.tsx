import { getResourceGrantDepartments, getResourceGrantUsers } from "~/api/permission";
import type {
  PermissionUserRow,
  ResourceType,
  SelectedSubject,
} from "~/api/permission";
import { Checkbox } from "~/components/ui/Checkbox";
import { useLocalize } from "~/hooks";
import { resolveDepartmentDisplayName } from "~/utils/departmentDisplayName";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Search,
  User as UserIcon,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DepartmentNode } from "./SubjectSearchDepartment";

interface SubjectSearchUserTreeProps {
  value: SelectedSubject[];
  onChange: (value: SelectedSubject[]) => void;
  resourceType: ResourceType;
  resourceId: string;
  disabledIds?: number[];
  loadDepartments?: (config?: { signal?: AbortSignal }) => Promise<DepartmentNode[]>;
  grantDepartmentsApi?: typeof getResourceGrantDepartments;
  grantUsersApi?: typeof getResourceGrantUsers;
}

interface NodePageState {
  rows: PermissionUserRow[];
  page: number;
  hasMore: boolean;
  loading: boolean;
  error: boolean;
}

interface SearchState extends NodePageState {
  keyword: string;
}

const PAGE_SIZE = 50;
const UNASSIGNED_KEY = "unassigned";
type NodeKey = number | typeof UNASSIGNED_KEY;

const EMPTY_NODE_STATE: NodePageState = {
  rows: [],
  page: 0,
  hasMore: true,
  loading: false,
  error: false,
};

function mergeUsers(current: PermissionUserRow[], incoming: PermissionUserRow[]) {
  const byId = new Map(current.map((user) => [user.user_id, user]));
  incoming.forEach((user) => byId.set(user.user_id, user));
  return Array.from(byId.values());
}

function collectDepartmentIds(nodes: DepartmentNode[], output = new Set<number>()) {
  nodes.forEach((node) => {
    output.add(node.id);
    collectDepartmentIds(node.children ?? [], output);
  });
  return output;
}

export function SubjectSearchUserTree({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
  loadDepartments,
  grantDepartmentsApi,
  grantUsersApi,
}: SubjectSearchUserTreeProps) {
  const localize = useLocalize();
  const [tree, setTree] = useState<DepartmentNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState(false);
  const [treeReload, setTreeReload] = useState(0);
  const [expanded, setExpanded] = useState<Set<NodeKey>>(new Set());
  const [nodeStates, setNodeStates] = useState<Record<string, NodePageState>>({});
  const [keyword, setKeyword] = useState("");
  const [searchState, setSearchState] = useState<SearchState>({
    ...EMPTY_NODE_STATE,
    keyword: "",
  });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchControllerRef = useRef<AbortController | null>(null);
  const nodeControllersRef = useRef<Map<string, AbortController>>(new Map());

  const getGrantUsers = grantUsersApi ?? getResourceGrantUsers;
  const selectedIds = useMemo(() => new Set(value.map((subject) => subject.id)), [value]);
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);
  const visibleDepartmentIds = useMemo(() => collectDepartmentIds(tree), [tree]);

  useEffect(() => {
    const controller = new AbortController();
    setTreeLoading(true);
    setTreeError(false);
    const request = loadDepartments
      ? loadDepartments({ signal: controller.signal })
      : (grantDepartmentsApi ?? getResourceGrantDepartments)(
          resourceType,
          resourceId,
          { signal: controller.signal },
        );
    request
      .then((departments) => {
        if (controller.signal.aborted) return;
        const nextTree = Array.isArray(departments) ? departments : [];
        setTree(nextTree);
        setExpanded(new Set());
      })
      .catch(() => {
        if (!controller.signal.aborted) setTreeError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setTreeLoading(false);
      });
    return () => controller.abort();
  }, [grantDepartmentsApi, loadDepartments, resourceId, resourceType, treeReload]);

  useEffect(() => {
    setNodeStates({});
    setKeyword("");
    setSearchState({ ...EMPTY_NODE_STATE, keyword: "" });
    return () => {
      searchControllerRef.current?.abort();
      nodeControllersRef.current.forEach((controller) => controller.abort());
      nodeControllersRef.current.clear();
    };
  }, [resourceId, resourceType]);

  const loadNodePage = useCallback(
    async (key: NodeKey, page: number) => {
      const stateKey = String(key);
      nodeControllersRef.current.get(stateKey)?.abort();
      const controller = new AbortController();
      nodeControllersRef.current.set(stateKey, controller);
      setNodeStates((current) => ({
        ...current,
        [stateKey]: {
          ...(current[stateKey] ?? EMPTY_NODE_STATE),
          loading: true,
          error: false,
        },
      }));
      try {
        const rows = await getGrantUsers(
          resourceType,
          resourceId,
          key === UNASSIGNED_KEY
            ? { keyword: "", page, page_size: PAGE_SIZE, unassigned: true }
            : { keyword: "", page, page_size: PAGE_SIZE, department_id: key },
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setNodeStates((current) => ({
          ...current,
          [stateKey]: {
            rows: page === 1
              ? rows
              : mergeUsers(current[stateKey]?.rows ?? [], rows),
            page,
            hasMore: rows.length > 0,
            loading: false,
            error: false,
          },
        }));
      } catch {
        if (controller.signal.aborted) return;
        setNodeStates((current) => ({
          ...current,
          [stateKey]: {
            ...(current[stateKey] ?? EMPTY_NODE_STATE),
            page,
            loading: false,
            error: true,
          },
        }));
      }
    },
    [getGrantUsers, resourceId, resourceType],
  );

  const toggleExpand = (key: NodeKey) => {
    const willExpand = !expanded.has(key);
    setExpanded((current) => {
      const next = new Set(current);
      if (willExpand) next.add(key);
      else next.delete(key);
      return next;
    });
    if (willExpand && !nodeStates[String(key)]) {
      void loadNodePage(key, 1);
    }
  };

  const loadSearchPage = useCallback(
    async (searchKeyword: string, page: number) => {
      searchControllerRef.current?.abort();
      const controller = new AbortController();
      searchControllerRef.current = controller;
      setSearchState((current) => ({
        ...(page === 1 ? { ...EMPTY_NODE_STATE, keyword: searchKeyword } : current),
        keyword: searchKeyword,
        loading: true,
        error: false,
      }));
      try {
        const rows = await getGrantUsers(
          resourceType,
          resourceId,
          { keyword: searchKeyword, page, page_size: PAGE_SIZE },
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setSearchState((current) => ({
          keyword: searchKeyword,
          rows: page === 1 ? rows : mergeUsers(current.rows, rows),
          page,
          hasMore: rows.length > 0,
          loading: false,
          error: false,
        }));
      } catch {
        if (controller.signal.aborted) return;
        setSearchState((current) => ({ ...current, page, loading: false, error: true }));
      }
    },
    [getGrantUsers, resourceId, resourceType],
  );

  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextKeyword = event.target.value;
    setKeyword(nextKeyword);
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!nextKeyword.trim()) {
      searchControllerRef.current?.abort();
      setSearchState({ ...EMPTY_NODE_STATE, keyword: "" });
      return;
    }
    setSearchState({
      ...EMPTY_NODE_STATE,
      keyword: nextKeyword.trim(),
      loading: true,
    });
    timerRef.current = setTimeout(() => {
      void loadSearchPage(nextKeyword.trim(), 1);
    }, 300);
  };

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const toggleUser = (user: PermissionUserRow) => {
    if (disabledIdSet.has(user.user_id)) return;
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((subject) => subject.id !== user.user_id));
      return;
    }
    const byId = new Map(value.map((subject) => [subject.id, subject]));
    byId.set(user.user_id, {
      type: "user",
      id: user.user_id,
      name: user.user_name,
    });
    onChange(Array.from(byId.values()));
  };

  const searchGroups = useMemo(() => {
    const byDepartment = new Map<number, PermissionUserRow[]>();
    const unassigned: PermissionUserRow[] = [];
    searchState.rows.forEach((user) => {
      const memberships = user.department_memberships ?? [];
      if (memberships.length === 0) {
        unassigned.push(user);
        return;
      }
      memberships.forEach((membership) => {
        if (!visibleDepartmentIds.has(membership.department_id)) return;
        const rows = byDepartment.get(membership.department_id) ?? [];
        if (!rows.some((row) => row.user_id === user.user_id)) rows.push(user);
        byDepartment.set(membership.department_id, rows);
      });
    });
    return { byDepartment, unassigned };
  }, [searchState.rows, visibleDepartmentIds]);
  const searchVisibleDepartmentIds = useMemo(() => {
    const visibleIds = new Set<number>();
    const parentById = new Map<number, number | null>();
    const collectParents = (nodes: DepartmentNode[]) => {
      nodes.forEach((node) => {
        parentById.set(node.id, node.parent_id);
        collectParents(node.children ?? []);
      });
    };
    collectParents(tree);
    searchGroups.byDepartment.forEach((_rows, departmentId) => {
      let currentId: number | null | undefined = departmentId;
      while (currentId != null && !visibleIds.has(currentId)) {
        visibleIds.add(currentId);
        currentId = parentById.get(currentId);
      }
    });
    return visibleIds;
  }, [searchGroups.byDepartment, tree]);

  const isSearching = Boolean(keyword.trim());

  const renderUser = (user: PermissionUserRow, locationKey: NodeKey, depth = 0) => {
    const isDisabled = disabledIdSet.has(user.user_id);
    const account = user.external_id?.trim();
    return (
      <div
        key={`${locationKey}:${user.user_id}`}
        data-testid={`permission-user-tree-row-${locationKey}-${user.user_id}`}
        className={`flex items-center gap-2 py-2 pr-3 ${
          isDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-gray-50"
        }`}
        style={{ paddingLeft: 44 + depth * 20 }}
        onClick={() => toggleUser(user)}
      >
        <Checkbox checked={selectedIds.has(user.user_id)} disabled={isDisabled} />
        <UserIcon className="size-4 shrink-0 text-gray-400" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-[#212121]">{user.user_name}</div>
          {account && (
            <div className="truncate text-xs leading-5 text-[#999999]">
              {`${localize("com_permission.user_account")}: ${account}`}
            </div>
          )}
        </div>
        {isDisabled && (
          <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {localize("com_permission.already_granted")}
          </span>
        )}
      </div>
    );
  };

  const renderNodeStatus = (key: NodeKey, state: NodePageState) => (
    <>
      {state.loading && (
        <div className="py-2 pl-11 text-xs text-gray-500">{localize("com_ui_loading")}</div>
      )}
      {state.error && (
        <div className="flex items-center gap-2 py-2 pl-11 text-xs text-gray-500">
          <span>{localize("com_permission.load_failed")}</span>
          <button type="button" className="text-blue-600" onClick={() => void loadNodePage(key, Math.max(state.page, 1))}>
            {localize("com_permission.retry")}
          </button>
        </div>
      )}
      {!state.loading && !state.error && state.rows.length === 0 && state.page > 0 && (
        <div className="py-2 pl-11 text-xs text-gray-500">{localize("com_permission.empty_department_users")}</div>
      )}
      {!state.loading && !state.error && state.hasMore && state.page > 0 && (
        <button
          type="button"
          className="py-2 pl-11 text-xs text-blue-600"
          onClick={() => void loadNodePage(key, state.page + 1)}
        >
          {localize("com_permission.load_more")}
        </button>
      )}
    </>
  );

  const renderDepartment = (node: DepartmentNode, depth: number): React.ReactNode => {
    const searchRows = searchGroups.byDepartment.get(node.id) ?? [];
    if (isSearching && !searchVisibleDepartmentIds.has(node.id)) return null;
    const isExpanded = isSearching || expanded.has(node.id);
    const state = nodeStates[String(node.id)] ?? EMPTY_NODE_STATE;
    const displayName = resolveDepartmentDisplayName({
      displayName: node.display_name,
      shortName: node.short_name,
      name: node.name,
    });
    return (
      <div key={node.id}>
        <button
          type="button"
          data-testid={`permission-user-tree-department-${node.id}`}
          className="flex w-full items-center gap-2 py-2 pr-3 text-left text-sm text-[#212121] hover:bg-gray-50"
          style={{ paddingLeft: 12 + depth * 20 }}
          onClick={() => !isSearching && toggleExpand(node.id)}
        >
          {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          <Building2 className="size-4 text-gray-400" />
          <span className="truncate" title={displayName}>{displayName}</span>
        </button>
        {isExpanded && (
          <div>
            {(isSearching ? searchRows : state.rows).map((user) => renderUser(user, node.id, depth))}
            {!isSearching && renderNodeStatus(node.id, state)}
            {(node.children ?? []).map((child) => renderDepartment(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  const unassignedState = nodeStates[UNASSIGNED_KEY] ?? EMPTY_NODE_STATE;
  const unassignedExpanded = isSearching || expanded.has(UNASSIGNED_KEY);
  const hasSearchResults = searchGroups.byDepartment.size > 0 || searchGroups.unassigned.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={localize("com_permission.search_user_by_name_or_account")}
          value={keyword}
          onChange={handleSearchChange}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]"
        onWheel={(event) => {
          event.currentTarget.scrollTop += event.deltaY;
        }}
      >
        {treeLoading && <div className="py-4 text-center text-sm text-gray-500">{localize("com_ui_loading")}</div>}
        {treeError && (
          <div className="flex justify-center gap-2 py-4 text-sm text-gray-500">
            <span>{localize("com_permission.load_failed")}</span>
            <button type="button" className="text-blue-600" onClick={() => setTreeReload((value) => value + 1)}>
              {localize("com_permission.retry")}
            </button>
          </div>
        )}
        {!treeLoading && !treeError && (
          <>
            {tree.map((node) => renderDepartment(node, 0))}
            {(!isSearching || searchGroups.unassigned.length > 0) && (
              <div>
                <button
                  type="button"
                  data-testid="permission-user-tree-unassigned"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[#212121] hover:bg-gray-50"
                  onClick={() => !isSearching && toggleExpand(UNASSIGNED_KEY)}
                >
                  {unassignedExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  <Users className="size-4 text-gray-400" />
                  <span>{localize("com_permission.unassigned_department")}</span>
                </button>
                {unassignedExpanded && (
                  <div>
                    {(isSearching ? searchGroups.unassigned : unassignedState.rows).map((user) => renderUser(user, UNASSIGNED_KEY))}
                    {!isSearching && renderNodeStatus(UNASSIGNED_KEY, unassignedState)}
                  </div>
                )}
              </div>
            )}
            {isSearching && searchState.loading && (
              <div className="py-4 text-center text-sm text-gray-500">{localize("com_ui_loading")}</div>
            )}
            {isSearching && searchState.error && (
              <div className="flex justify-center gap-2 py-4 text-sm text-gray-500">
                <span>{localize("com_permission.load_failed")}</span>
                <button type="button" className="text-blue-600" onClick={() => void loadSearchPage(searchState.keyword, Math.max(searchState.page, 1))}>
                  {localize("com_permission.retry")}
                </button>
              </div>
            )}
            {isSearching && !searchState.loading && !searchState.error && !hasSearchResults && (
              <div className="py-4 text-center text-sm text-gray-500">{localize("com_permission.empty_search")}</div>
            )}
            {isSearching && !searchState.loading && !searchState.error && searchState.hasMore && searchState.page > 0 && (
              <button
                type="button"
                className="w-full py-2 text-center text-xs text-blue-600"
                onClick={() => void loadSearchPage(searchState.keyword, searchState.page + 1)}
              >
                {localize("com_permission.load_more")}
              </button>
            )}
            {!isSearching && tree.length === 0 && (
              <div className="py-4 text-center text-sm text-gray-500">{localize("com_permission.empty_departments")}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
