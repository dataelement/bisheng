import { Button, Dropdown, DropdownItem, SearchInput, Tooltip } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { userContext } from "@/contexts/userContext";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import { listNavigationSpaces, setNavigationSpacePin, type SpaceSection, type SpaceSort } from "@/controllers/API/knowledgeSpaceNavigation";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeFolderTree } from "./KnowledgeFolderTree";
import styles from "./KnowledgeSpaceSidebar.module.css";
import { ScrollableTreeName } from "./ScrollableTreeName";
import { useKnowledgeTreeScroll } from "./useKnowledgeTreeScroll";
import { useSpaceCatalog } from "./useSpaceCatalog";
import { useSidebarSpaceActions } from "./useSidebarSpaceActions";

export interface KnowledgeSpaceSidebarProps {
  scope: KnowledgeQueryScope;
  spaceId?: number;
  parentId?: number | null;
  canCopy: boolean;
  onSelect: (spaceId: number, parentId: number | null) => void;
  onDeleted?: (id: number) => void;
}

type SidebarSection = SpaceSection | "personal";
const ordinarySections: readonly SidebarSection[] = ["department", "created", "joined"];
const adminSections: readonly SidebarSection[] = ["department", "personal"];
const sorts: readonly SpaceSort[] = ["update_time", "create_time", "name"];
const sectionActionClass = "!size-5 !p-0 !text-text-3 hover:!bg-fill-2 hover:!text-text-2 [&_svg]:!size-4";
const spaceMenuClass = "!size-5 !rounded-md !p-0 !text-text-2 before:absolute before:-inset-1 before:content-[''] [&_svg]:!size-4 fine-pointer:opacity-0 coarse-pointer:opacity-100 group-hover/space:opacity-100 focus:opacity-100 data-[state=open]:opacity-100 hover:!bg-[#E4E4E4] dark:hover:!bg-fill-3";

interface SpaceMenuProps {
  renderActions: (item: KnowledgeSpaceInfo) => ReactNode;
  onMenuOpen: (item: KnowledgeSpaceInfo, open: boolean) => void;
}
interface SpaceItemProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps {
  item: KnowledgeSpaceInfo;
  section: SidebarSection;
  path: readonly number[];
}

function SpaceItem({ item, section, path, ...props }: SpaceItemProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const active = props.spaceId === item.id;
  const [expanded, setExpanded] = useState(active);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);
  useEffect(() => {
    if (active) setExpanded(true);
  }, [active, props.parentId]);
  const pin = useMutation({
    mutationFn: () => setNavigationSpacePin(item.id, !item.is_pinned),
    onSuccess: () => client.invalidateQueries({ queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections"] }),
    onError: (error) => { if (live.current) showApiError(error); },
  });
  const selected = active && props.parentId == null;
  return (
    <li className="space-y-0.5">
      <div className={`group/space flex h-7 items-center rounded-md border border-transparent text-[12px] leading-5 text-text-1 transition-colors duration-[350ms] ${selected ? "bg-[#EEEEEE] font-semibold dark:bg-fill-2" : "hover:bg-[#F4F4F4] dark:hover:bg-fill-1"}`}>
        <button
          type="button"
          className="flex size-5 shrink-0 items-center justify-center"
          aria-expanded={expanded}
          aria-label={`${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.name}`}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded
            ? <Outlined.Down aria-hidden className="size-4 text-[#8D93A0] dark:text-text-3" />
            : <Outlined.Right aria-hidden className="size-4 text-[#8D93A0] dark:text-text-3" />}
        </button>
        <button
          type="button"
          aria-current={selected ? "page" : undefined}
          title={item.name}
          className="flex h-full min-w-0 flex-1 cursor-pointer items-center text-left group-hover/space:[--tree-name-gutter:44px] group-focus-within/space:[--tree-name-gutter:44px] coarse-pointer:[--tree-name-gutter:44px]"
          onClick={() => props.onSelect(item.id, null)}
        >
          <span className={`flex size-5 shrink-0 items-center justify-center ${selected ? "text-text-1" : "text-text-3"}`}>
            {section === "department" ? <Outlined.City aria-hidden className="size-4" /> : <Outlined.Notebook aria-hidden className="size-4" />}
          </span>
          <ScrollableTreeName name={item.name} trailing={item.is_pinned && <Outlined.Pin aria-hidden className="size-3 shrink-0 text-text-3" />} />
        </button>
        <div className="sticky right-1 z-[1] -mr-3 ml-2 flex h-5 w-8 shrink-0 items-center pr-3">
          <Dropdown
            align="end"
            onOpenChange={(open) => props.onMenuOpen(item, open)}
            menu={(
              <>
              {props.scope.view === "ordinary" && <DropdownItem disabled={pin.isLoading} icon={item.is_pinned ? <Outlined.PinOff /> : <Outlined.Pin />} onSelect={() => pin.mutate()}>
                {t(item.is_pinned ? "sidebar.unpin" : "sidebar.pin")}
              </DropdownItem>}
              {props.renderActions(item)}
              </>
            )}
          >
            <Button
              color="default" variant="text" iconOnly size="small"
              className={`${spaceMenuClass} ${selected ? "bg-[#EEEEEE] dark:bg-fill-2" : "bg-[#FBFBFB] group-hover/space:bg-[#F4F4F4] dark:bg-bg-page dark:group-hover/space:bg-fill-1"}`}
              style={{ transition: "opacity 200ms ease, background-color 350ms ease-in-out" }}
              aria-label={`${t("more", { ns: "bs" })} ${item.name}`}
            >
              <Outlined.More aria-hidden />
            </Button>
          </Dropdown>
        </div>
      </div>
      {expanded && (
        <KnowledgeFolderTree scope={props.scope} spaceId={item.id} parentId={null} selectedId={active ? props.parentId ?? null : null} path={active ? path : []} onSelect={props.onSelect} />
      )}
    </li>
  );
}

interface SectionProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps {
  keyword: string;
  catalog: ReturnType<typeof useSpaceCatalog>;
  departmentIds: ReadonlySet<number>;
  createdIds: ReadonlySet<number>;
  userId?: number;
  section: SidebarSection;
  path: readonly number[];
}

function SpaceSectionList({ section, path, keyword, catalog, departmentIds, createdIds, userId, ...props }: SectionProps) {
  const { t } = useTranslation("knowledge");
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
  const rows = [...new Map(source
    .filter((item) => Number.isSafeInteger(item.id) && item.id > 0 && (item.tenant_id == null || item.tenant_id === props.scope.tenantId))
    .map((item) => [item.id, props.scope.view === "ordinary" && keyword ? { ...item, is_pinned: navigation.get(item.id)?.is_pinned ?? item.is_pinned } : item])).values()];
  if (catalogMode) rows.sort((a, b) => {
    const pinned = props.scope.view === "ordinary" ? Number(b.is_pinned === true) - Number(a.is_pinned === true) : 0;
    return pinned || (sort === "name" ? a.name.localeCompare(b.name) : String(b[sort] ?? "").localeCompare(String(a[sort] ?? ""))) || b.id - a.id;
  });
  const loading = catalogMode ? catalog.isInitialLoading : query.isInitialLoading;
  const failed = catalogMode ? catalog.isError : query.isError;
  const retry = catalogMode ? catalog.refetch : query.refetch;
  return (
    <section className="pb-4" aria-label={t(`sidebar.${section}`)}>
      <div className="group/section sticky left-0 top-0 z-[2] mb-2 flex h-7 w-[100cqi] items-center justify-between gap-1 bg-[#FBFBFB] px-4 transition-colors hover:bg-[#F4F4F4] dark:bg-bg-page dark:hover:bg-fill-1">
        <button className="flex h-full min-w-0 flex-1 cursor-pointer items-center gap-1 text-left text-[12px] leading-[18px] text-text-3 group-hover/section:text-text-2" type="button" aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>
          <span>{t(`sidebar.${section}`)}</span>
          <Outlined.Down aria-hidden className={`size-4 opacity-0 transition-[opacity,transform] group-hover/section:opacity-100 group-focus-within/section:opacity-100 ${collapsed ? "-rotate-90" : ""}`} />
        </button>
        <Dropdown align="end" menu={sorts.map((value) => (
          <DropdownItem key={value} checked={sort === value} onSelect={() => setSort(value)}>{t(`sidebar.sort_${value}`)}</DropdownItem>
        ))}>
          <Button color="default" variant="text" iconOnly size="small" className={sectionActionClass} aria-label={`${t("sidebar.sort")} ${t(`sidebar.${section}`)}`}><Outlined.Sort aria-hidden /></Button>
        </Dropdown>
      </div>
      {!collapsed && (
        <>
          {loading && <p role="status" className="sticky left-0 w-[100cqi] px-5 py-2 text-[12px] leading-5 text-text-3">{t("sidebar.loading")}</p>}
          {failed && <div className="sticky left-0 w-[100cqi] px-5 text-[12px] leading-5 text-text-3"><span>{t("sidebar.load_failed")}</span><Button variant="text" onClick={() => { void retry().catch(showApiError); }}>{t("retry")}</Button></div>}
          {!loading && !failed && rows.length === 0 && <p className="sticky left-0 flex h-24 w-[100cqi] items-center justify-center text-center text-sm text-text-3">{t("sidebar.empty")}</p>}
          <ul className="space-y-0.5 px-3">{rows.map((item) => <SpaceItem key={item.id} {...props} section={section} item={item} path={path} />)}</ul>
        </>
      )}
    </section>
  );
}

function ScopedKnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const [collapsed, setCollapsed] = useState(false);
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
  const navigationId = useId();
  const viewportRef = useRef<HTMLElement>(null);
  useKnowledgeTreeScroll(viewportRef);
  const { spaceId, parentId, scope } = props;
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
  const path = parents.data?.map((folder) => folder.id) ?? [];
  return (
    <aside className={`flex h-full shrink-0 flex-col border-r-[0.5px] border-border-base bg-[#FBFBFB] font-sans dark:bg-bg-page ${collapsed ? "w-10" : "w-60"}`} aria-label={t("f118.spaces")}>
      <div className={`flex items-center py-2 ${collapsed ? "justify-center" : "gap-1 px-2"}`}>
        {!collapsed && <SearchInput size="small" className="min-w-0 flex-1" aria-label={t("sidebar.search")} placeholder={t("sidebar.search")} value={search} onChange={(event) => setSearch(event.target.value)} onSearch={(value) => setKeyword(value.trim())} />}
        <Tooltip content={t(collapsed ? "sidebar.expand_navigation" : "sidebar.collapse_navigation")}>
          <Button variant="text" color="default" iconOnly size="small" aria-controls={navigationId} aria-expanded={!collapsed}
            aria-label={t(collapsed ? "sidebar.expand_navigation" : "sidebar.collapse_navigation")} onClick={() => setCollapsed((value) => !value)}><Outlined.SidebarMenu /></Button>
        </Tooltip>
      </div>
      <nav ref={viewportRef} id={navigationId} hidden={collapsed} tabIndex={0} className={`${styles.scrollOnScroll} min-h-0 flex-1 overflow-auto overscroll-contain pb-5 scroll-pt-9 [container-type:inline-size]`} aria-label={t("sidebar.navigation")}>
        <div className="w-max min-w-full">
          {sections.map((section) => <SpaceSectionList key={section} {...props} section={section} path={path} keyword={keyword} catalog={catalog} departmentIds={departmentIds} createdIds={createdIds} userId={user?.user_id} renderActions={actions.render} onMenuOpen={actions.load} />)}
          {catalog.hasNextPage && <div className="sticky left-0 w-[100cqi] px-4"><Button variant="text" loading={catalog.isFetchingNextPage} onClick={() => { void catalog.fetchNextPage().catch(showApiError); }}>{t("sidebar.more_spaces")}</Button></div>}
        </div>
      </nav>
      {actions.dialogs}
    </aside>
  );
}

/** Keep navigation isolated across identity, tenant and ordinary/management views. */
export function KnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const { scope } = props;
  if (!scope.identityKey || !Number.isSafeInteger(scope.tenantId) || scope.tenantId <= 0 || (scope.managementTenantId !== null && (!Number.isSafeInteger(scope.managementTenantId) || scope.managementTenantId <= 0)))
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  return <ScopedKnowledgeSpaceSidebar key={JSON.stringify(knowledgeQueryKeys.scope(props.scope))} {...props} />;
}
