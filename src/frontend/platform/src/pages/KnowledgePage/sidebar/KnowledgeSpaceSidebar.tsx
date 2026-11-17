import {
  Button, Dropdown, DropdownItem, SearchInput, Tooltip,
  TreeNavigation, TreeNavigationGroup, TreeNavigationGroupAction, TreeNavigationList, TreeNavigationMenu, TreeNavigationNode, TreeNavigationStatus,
} from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { userContext } from "@/contexts/userContext";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import { listNavigationSpaces, setNavigationSpacePin, type SpaceSection, type SpaceSort } from "@/controllers/API/knowledgeSpaceNavigation";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeFolderTree, knowledgeTreeNodeKey, type KnowledgeTreeExpansion } from "./KnowledgeFolderTree";
import { KnowledgeSidebarPane } from "./KnowledgeSidebarPane";
import { useSpaceCatalog } from "./useSpaceCatalog";
import { useSidebarSpaceActions } from "./useSidebarSpaceActions";
import { useSpaceCopyTasks } from "../useSpaceCopyTasks";
import type { SpaceCopyTask } from "@/controllers/API/knowledgeCopy";

export interface KnowledgeSpaceSidebarProps {
  scope: KnowledgeQueryScope;
  spaceId?: number;
  parentId?: number | null;
  canCopy: boolean;
  onCreate?: () => void;
  onSelect: (spaceId: number, parentId: number | null) => void;
  onDeleted?: (id: number) => void;
}

type SidebarSection = SpaceSection | "personal";
const ordinarySections: readonly SidebarSection[] = ["department", "created", "joined"];
const adminSections: readonly SidebarSection[] = ["department", "personal"];
const sorts: readonly SpaceSort[] = ["update_time", "create_time", "name"];

interface SpaceMenuProps {
  renderActions: (item: KnowledgeSpaceInfo) => ReactNode;
  onMenuOpen: (item: KnowledgeSpaceInfo, open: boolean) => void;
}
interface SpaceItemProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps, KnowledgeTreeExpansion {
  item: KnowledgeSpaceInfo & { copyTask?: SpaceCopyTask };
  section: SidebarSection;
  path: readonly number[];
}

function SpaceItem({ item, section, path, ...props }: SpaceItemProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const active = props.spaceId === item.id;
  const key = knowledgeTreeNodeKey(item.id);
  const expanded = props.expandedKeys.has(key);
  const [knownEmpty, setKnownEmpty] = useState(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);
  const pin = useMutation({
    mutationFn: () => setNavigationSpacePin(item.id, !item.is_pinned),
    onSuccess: () => client.invalidateQueries({ queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections"] }),
    onError: (error) => { if (live.current) showApiError(error); },
  });
  const selected = active && props.parentId == null;
  return (
    <TreeNavigationNode
      name={item.name}
      current={selected && "page"}
      icon={section === "department" ? <Outlined.City /> : <Outlined.Notebook />}
      marker={<>{(item.copyTask || item.state === 2) && <span role="status" className="text-caption text-text-3">{t(item.copyTask?.phase === "failed" ? "space_copy_ui.failed" : "space_copy_ui.in_progress")}</span>}{item.is_pinned && <Outlined.Pin aria-hidden />}</>}
      onSelect={() => props.onSelect(item.id, null)}
      disclosure={item.copyTask || knownEmpty ? undefined : {
        expanded,
        label: `${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.name}`,
        onToggle: () => props.onExpansionChange(key, !expanded),
      }}
      actions={!item.copyTask && (
        <TreeNavigationMenu
          label={`${t("more", { ns: "bs" })} ${item.name}`}
          onOpenChange={(open) => props.onMenuOpen(item, open)}
          menu={(
            <>
              {props.scope.view === "ordinary" && <DropdownItem disabled={pin.isLoading} icon={item.is_pinned ? <Outlined.PinOff /> : <Outlined.Pin />} onSelect={() => pin.mutate()}>
                {t(item.is_pinned ? "sidebar.unpin" : "sidebar.pin")}
              </DropdownItem>}
              {props.renderActions(item)}
            </>
          )}
        />
      )}
    >
      {expanded && !item.copyTask && (
        <KnowledgeFolderTree
          scope={props.scope} spaceId={item.id} parentId={null}
          selectedId={active ? props.parentId ?? null : null} path={active ? path : []}
          expandedKeys={props.expandedKeys} onExpansionChange={props.onExpansionChange}
          onSelect={props.onSelect} onEmptyChange={setKnownEmpty}
        />
      )}
    </TreeNavigationNode>
  );
}

interface SectionProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps, KnowledgeTreeExpansion {
  keyword: string;
  catalog: ReturnType<typeof useSpaceCatalog>;
  departmentIds: ReadonlySet<number>;
  createdIds: ReadonlySet<number>;
  userId?: number;
  section: SidebarSection;
  path: readonly number[];
}

function SpaceSectionList({ section, path, keyword, catalog, departmentIds, createdIds, userId, onCreate, ...props }: SectionProps) {
  const { t } = useTranslation("knowledge");
  const copies = useSpaceCopyTasks(props.scope);
  const copyById = new Map(copies.data?.map((task) => [task.id, task]));
  const [collapsed, setCollapsed] = useState(false);
  const [sort, setSort] = useState<SpaceSort>("update_time");
  const query = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections", section, sort],
    queryFn: () => listNavigationSpaces(section as SpaceSection, sort),
    enabled: props.scope.view === "ordinary",
    keepPreviousData: false,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  const catalogMode = props.scope.view === "admin" || keyword !== "";
  const source = catalogMode ? (catalog.data?.pages.flatMap((page) => page.data) ?? []).filter((row) => {
    if (props.scope.view === "admin") return (row.space_kind === "department") === (section === "department");
    const department = departmentIds.has(row.id);
    const created = createdIds.has(row.id) || (typeof userId === "number" && row.user_id === userId);
    if (section === "department") return department;
    return !department && (section === "created" ? created : !created);
  }) : query.data ?? [];
  const navigation = new Map(query.data?.map((row) => [row.id, row]));
  const pending = section === "created" || section === "personal"
    ? (copies.data ?? []).filter((task) => task.name.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()))
    : [];
  const rows = [...new Map([...source, ...pending]
    .filter((item) => Number.isSafeInteger(item.id) && item.id > 0 && (item.tenant_id == null || item.tenant_id === props.scope.tenantId))
    .map((item) => [item.id, { ...navigation.get(item.id), ...item, copyTask: copyById.get(item.id), ...(props.scope.view === "ordinary" && keyword ? { is_pinned: navigation.get(item.id)?.is_pinned ?? item.is_pinned } : {}) }])).values()];
  if (catalogMode || pending.length > 0) rows.sort((a, b) => {
    const pinned = props.scope.view === "ordinary" ? Number(b.is_pinned === true) - Number(a.is_pinned === true) : 0;
    return pinned || (sort === "name" ? a.name.localeCompare(b.name) : String(b[sort] ?? "").localeCompare(String(a[sort] ?? ""))) || b.id - a.id;
  });
  const loading = catalogMode ? catalog.isInitialLoading : query.isInitialLoading;
  const failed = catalogMode ? catalog.isError : query.isError;
  const retry = catalogMode ? catalog.refetch : query.refetch;
  const active = rows.some((item) => item.id === props.spaceId);
  useEffect(() => {
    if (active) setCollapsed(false);
  }, [active, props.spaceId, props.parentId]);

  return (
    <TreeNavigationGroup
      label={t(`sidebar.${section}`)}
      expanded={!collapsed}
      onToggle={() => setCollapsed((value) => !value)}
      actions={(
        <>
          {section === "created" && onCreate && (
            <Tooltip content={t("f118.create_space")}>
              <TreeNavigationGroupAction aria-label={t("f118.create_space")} onClick={onCreate}>
                <Outlined.Plus aria-hidden />
              </TreeNavigationGroupAction>
            </Tooltip>
          )}
          <Dropdown align="end" menu={sorts.map((value) => (
            <DropdownItem key={value} checked={sort === value} onSelect={() => setSort(value)}>{t(`sidebar.sort_${value}`)}</DropdownItem>
          ))}>
            <TreeNavigationGroupAction aria-label={`${t("sidebar.sort")} ${t(`sidebar.${section}`)}`}><Outlined.Sort aria-hidden /></TreeNavigationGroupAction>
          </Dropdown>
        </>
      )}
    >
      <TreeNavigationList>
        {rows.map((item) => <SpaceItem key={item.id} {...props} section={section} item={item} path={path} />)}
        {loading && <TreeNavigationStatus loading>{t("sidebar.loading")}</TreeNavigationStatus>}
        {failed && <TreeNavigationStatus><span>{t("sidebar.load_failed")}</span><Button variant="text" onClick={() => { void retry().catch(showApiError); }}>{t("retry")}</Button></TreeNavigationStatus>}
        {!loading && !failed && rows.length === 0 && <TreeNavigationStatus><div className="flex min-h-20 items-center justify-center text-center">{t("sidebar.empty")}</div></TreeNavigationStatus>}
      </TreeNavigationList>
    </TreeNavigationGroup>
  );
}

function ScopedKnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const [search, setSearch] = useState("");
  const [keyword, setKeyword] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setKeyword(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const { user } = useContext(userContext);
  const department = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections", "department", "update_time"],
    queryFn: () => listNavigationSpaces("department", "update_time"),
    enabled: props.scope.view === "ordinary", staleTime: 30_000, cacheTime: 0, retry: false,
  });
  const created = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections", "created", "update_time"],
    queryFn: () => listNavigationSpaces("created", "update_time"),
    enabled: props.scope.view === "ordinary", staleTime: 30_000, cacheTime: 0, retry: false,
  });
  const createdIds = new Set(created.data?.map((row) => row.id));
  const departmentIds = new Set(department.data?.map((row) => row.id));
  const catalog = useSpaceCatalog(props.scope, keyword, props.scope.view === "admin" || keyword !== "");
  const sections = props.scope.view === "admin" ? adminSections : ordinarySections;
  const { spaceId, parentId, scope } = props;
  const initialSpaceHandled = useRef(spaceId !== undefined);
  const [expandedKeys, setExpandedKeys] = useState(() => new Set(
    spaceId === undefined ? [] : [knowledgeTreeNodeKey(spaceId)],
  ));
  const handleExpansionChange = useCallback((key: string, expanded: boolean) => {
    setExpandedKeys((previous) => {
      const next = new Set(previous);
      if (expanded) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);
  const actions = useSidebarSpaceActions(scope, props.canCopy, props.onDeleted);
  const client = useQueryClient();
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const prefix = useMemo(() => knowledgeQueryKeys.scope({ identityKey, tenantId, managementTenantId, view }), [identityKey, tenantId, managementTenantId, view]);
  useEffect(() => () => {
    // Retire pending navigation reads even if a user switches A -> B -> A quickly.
    const predicate = (query: { queryKey: readonly unknown[] }) =>
      prefix.every((part, index) => query.queryKey[index] === part) &&
      query.queryKey.some((part) => typeof part === "string" && part.startsWith("navigation-"));
    void client.cancelQueries({ predicate });
    client.removeQueries({ predicate });
  }, [client, prefix]);
  const parents = useQuery({
    queryKey: [...prefix, "navigation-path", spaceId, parentId],
    queryFn: () => knowledgeFilesApi.listSpaceFolderParents(spaceId!, parentId!),
    enabled: spaceId !== undefined && parentId != null,
    keepPreviousData: false,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (parents.error) showApiError(parents.error);
  }, [parents.error]);
  useEffect(() => {
    if (spaceId === undefined || (parentId == null && initialSpaceHandled.current)) return;
    initialSpaceHandled.current = true;
    const ancestors = parents.data?.filter((folder) => folder.id !== parentId) ?? [];
    setExpandedKeys((previous) => new Set([
      ...previous,
      knowledgeTreeNodeKey(spaceId),
      ...ancestors.map((folder) => knowledgeTreeNodeKey(spaceId, folder.id)),
    ]));
  }, [spaceId, parentId, parents.data]);
  const path = parents.data?.map((folder) => folder.id) ?? [];
  const handleSelect = (id: number, folderId: number | null) => {
    initialSpaceHandled.current = true;
    props.onSelect(id, folderId);
  };
  return (
    <>
      <div className="shrink-0 px-2 pb-2">
        <SearchInput size="small" className="w-full" aria-label={t("sidebar.search")}
          placeholder={t("sidebar.search")} value={search} onChange={(event) => setSearch(event.target.value)}
          onSearch={(value) => setKeyword(value.trim())} />
      </div>
      <TreeNavigation showLine={false} className="min-h-0 flex-1 pb-5 [--tree-surface:#FBFBFB] dark:[--tree-surface:rgb(var(--bg-page))]" aria-label={t("sidebar.navigation")}>
        {sections.map((section) => (
          <SpaceSectionList key={section} {...props} section={section} path={path} onSelect={handleSelect}
            keyword={keyword} catalog={catalog} departmentIds={departmentIds} createdIds={createdIds} userId={user?.user_id}
            expandedKeys={expandedKeys} onExpansionChange={handleExpansionChange}
            renderActions={actions.render} onMenuOpen={actions.load} />
        ))}
        {catalog.hasNextPage && (
          <TreeNavigationList>
            <TreeNavigationStatus>
              <Button variant="text" loading={catalog.isFetchingNextPage}
                onClick={() => { void catalog.fetchNextPage().catch(showApiError); }}>{t("sidebar.more_spaces")}</Button>
            </TreeNavigationStatus>
          </TreeNavigationList>
        )}
      </TreeNavigation>
      {actions.dialogs}
    </>
  );
}

/** Keep navigation isolated across identity, tenant and ordinary/management views. */
export function KnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const { scope } = props;
  if (!scope.identityKey || !Number.isSafeInteger(scope.tenantId) || scope.tenantId <= 0 || (scope.managementTenantId !== null && (!Number.isSafeInteger(scope.managementTenantId) || scope.managementTenantId <= 0)))
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  return (
    <KnowledgeSidebarPane>
      <ScopedKnowledgeSpaceSidebar key={JSON.stringify(knowledgeQueryKeys.scope(scope))} {...props} />
    </KnowledgeSidebarPane>
  );
}
