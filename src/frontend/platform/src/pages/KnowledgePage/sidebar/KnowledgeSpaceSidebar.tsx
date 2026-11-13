import { Button, Dropdown, DropdownItem, Tooltip } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import { listNavigationSpaces, setNavigationSpacePin, type SpaceSection, type SpaceSort } from "@/controllers/API/knowledgeSpaceNavigation";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeFolderTree } from "./KnowledgeFolderTree";
import { useSidebarSpaceActions } from "./useSidebarSpaceActions";

export interface KnowledgeSpaceSidebarProps {
  scope: KnowledgeQueryScope;
  spaceId?: number;
  parentId?: number | null;
  canCreate: boolean;
  onCreate: () => void;
  onSelect: (spaceId: number, parentId: number | null) => void;
  onSquare: () => void;
  onDeleted?: (id: number) => void;
}

const sections: readonly SpaceSection[] = ["department", "created", "joined"];
const sorts: readonly SpaceSort[] = ["update_time", "create_time", "name"];

interface SpaceMenuProps {
  renderActions: (item: KnowledgeSpaceInfo) => ReactNode;
  onMenuOpen: (item: KnowledgeSpaceInfo, open: boolean) => void;
}
interface SpaceItemProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps {
  item: KnowledgeSpaceInfo;
  section: SpaceSection;
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
      <div className={`group flex min-h-8 items-center gap-1 rounded-md pr-1 text-control text-text-1 hover:bg-fill-1 ${selected ? "bg-fill-2 font-medium" : ""}`}>
        <button
          type="button"
          className="flex size-6 shrink-0 items-center justify-center rounded hover:bg-fill-2"
          aria-expanded={expanded}
          aria-label={`${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.name}`}
          onClick={() => setExpanded((value) => !value)}
        >
          <Outlined.Right aria-hidden className={`size-4 text-text-3 ${expanded ? "rotate-90" : ""}`} />
        </button>
        <button
          type="button"
          aria-current={selected ? "page" : undefined}
          title={item.name}
          className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left"
          onClick={() => props.onSelect(item.id, null)}
        >
          {section === "department" ? <Outlined.City aria-hidden className="size-4 shrink-0 text-text-3" /> : <Outlined.Notebook aria-hidden className="size-4 shrink-0 text-text-3" />}
          <span className="truncate">{item.name}</span>
          {item.is_pinned && <Outlined.Pin aria-hidden className="size-3 shrink-0 text-text-3" />}
        </button>
        <Dropdown
          align="end"
          onOpenChange={(open) => props.onMenuOpen(item, open)}
          menu={(
            <>
            <DropdownItem disabled={pin.isLoading} icon={item.is_pinned ? <Outlined.PinOff /> : <Outlined.Pin />} onSelect={() => pin.mutate()}>
              {t(item.is_pinned ? "sidebar.unpin" : "sidebar.pin")}
            </DropdownItem>
            {props.renderActions(item)}
            </>
          )}
        >
          <Button color="default" variant="text" iconOnly size="small" className="opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100" aria-label={`${t("more", { ns: "bs" })} ${item.name}`}>
            <Outlined.More aria-hidden />
          </Button>
        </Dropdown>
      </div>
      {expanded && (
        <KnowledgeFolderTree scope={props.scope} spaceId={item.id} parentId={null} selectedId={active ? props.parentId ?? null : null} path={active ? path : []} onSelect={props.onSelect} />
      )}
    </li>
  );
}

interface SectionProps extends KnowledgeSpaceSidebarProps, SpaceMenuProps {
  section: SpaceSection;
  path: readonly number[];
}

function SpaceSectionList({ section, path, ...props }: SectionProps) {
  const { t } = useTranslation("knowledge");
  const [collapsed, setCollapsed] = useState(false);
  const [sort, setSort] = useState<SpaceSort>("update_time");
  const query = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(props.scope), "navigation-sections", section, sort],
    queryFn: () => listNavigationSpaces(section, sort),
    keepPreviousData: false,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  const rows = [...new Map((query.data ?? [])
    .filter((item) => Number.isSafeInteger(item.id) && item.id > 0 && (item.tenant_id == null || item.tenant_id === props.scope.tenantId))
    .map((item) => [item.id, item])).values()];
  return (
    <section className={section === "department" ? "mb-5 border-b border-border-base pb-5" : "mb-5"} aria-label={t(`sidebar.${section}`)}>
      <div className="mb-2 flex min-h-8 items-center justify-between gap-1 px-1">
        <button className="group flex min-w-0 flex-1 items-center gap-1 text-left text-control text-text-3" type="button" aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>
          <span>{t(`sidebar.${section}`)}</span>
          <Outlined.Down aria-hidden className={`size-4 opacity-0 group-hover:opacity-100 group-focus:opacity-100 ${collapsed ? "-rotate-90" : ""}`} />
        </button>
        {section === "created" && props.canCreate && (
          <Button color="default" variant="text" iconOnly size="small" aria-label={t("f118.create_space")} onClick={props.onCreate}><Outlined.Plus aria-hidden /></Button>
        )}
        <Dropdown align="end" menu={sorts.map((value) => (
          <DropdownItem key={value} checked={sort === value} onSelect={() => setSort(value)}>{t(`sidebar.sort_${value}`)}</DropdownItem>
        ))}>
          <Button color="default" variant="text" iconOnly size="small" aria-label={`${t("sidebar.sort")} ${t(`sidebar.${section}`)}`}><Outlined.Sort aria-hidden /></Button>
        </Dropdown>
      </div>
      {!collapsed && (
        <>
          {query.isInitialLoading && <p role="status" className="px-2 py-2 text-control text-text-3">{t("sidebar.loading")}</p>}
          {query.isError && <div className="px-2 text-control text-text-3"><span>{t("sidebar.load_failed")}</span><Button variant="text" onClick={() => { void query.refetch().catch(showApiError); }}>{t("retry")}</Button></div>}
          {!query.isInitialLoading && !query.isError && rows.length === 0 && <p className="px-2 py-2 text-control text-text-3">{t("sidebar.empty")}</p>}
          <ul className="space-y-0.5">{rows.map((item) => <SpaceItem key={item.id} {...props} section={section} item={item} path={path} />)}</ul>
        </>
      )}
    </section>
  );
}

function ScopedKnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const [collapsed, setCollapsed] = useState(false);
  const navigationId = useId();
  const { spaceId, parentId, scope } = props;
  const actions = useSidebarSpaceActions(scope, props.canCreate, props.onDeleted);
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
    <aside className={`flex h-full shrink-0 flex-col border-r border-border-base bg-bg-page ${collapsed ? "w-10" : "w-72"}`} aria-label={t("f118.spaces")}>
      <div className={`flex items-center py-2 ${collapsed ? "justify-center" : "justify-end px-2"}`}>
        <Tooltip content={t(collapsed ? "sidebar.expand_navigation" : "sidebar.collapse_navigation")}>
          <Button variant="text" color="default" iconOnly size="small" aria-controls={navigationId} aria-expanded={!collapsed}
            aria-label={t(collapsed ? "sidebar.expand_navigation" : "sidebar.collapse_navigation")} onClick={() => setCollapsed((value) => !value)}><Outlined.SidebarMenu /></Button>
        </Tooltip>
      </div>
      <nav id={navigationId} hidden={collapsed} className="min-h-0 flex-1 overflow-y-auto px-3" aria-label={t("sidebar.navigation")}>
        {sections.map((section) => <SpaceSectionList key={section} {...props} section={section} path={path} renderActions={actions.render} onMenuOpen={actions.load} />)}
      </nav>
      <div hidden={collapsed} className="shrink-0 p-3">
        <Button variant="outlined" color="default" className="w-full" icon={<Outlined.BlocksAndArrows />} onClick={props.onSquare}>{t("sidebar.square")}</Button>
      </div>
      {actions.dialogs}
    </aside>
  );
}

/** Keep the three legacy sections while isolating every identity and tenant transition. */
export function KnowledgeSpaceSidebar(props: KnowledgeSpaceSidebarProps) {
  const { t } = useTranslation("knowledge");
  const { scope } = props;
  if (!scope.identityKey || !Number.isSafeInteger(scope.tenantId) || scope.tenantId <= 0 || (scope.managementTenantId !== null && (!Number.isSafeInteger(scope.managementTenantId) || scope.managementTenantId <= 0)))
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  return <ScopedKnowledgeSpaceSidebar key={JSON.stringify(knowledgeQueryKeys.scope(props.scope))} {...props} />;
}
