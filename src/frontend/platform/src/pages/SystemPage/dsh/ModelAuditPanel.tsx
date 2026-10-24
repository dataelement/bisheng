import { Button } from "@/components/bs-ui/button";
import { userContext } from "@/contexts/userContext";
import type {
  ModelAuditQuery,
  AuditGroupPage,
  AuditQueryReadiness,
  AuditTreePage,
} from "@/types/dshModelAudit";
import {
  getAuditGroups,
  getAuditReadiness,
  getAuditTree,
} from "@/controllers/API/dshModelAudit";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager, dshTime } from "./common";
import { ModelAuditCard } from "./ModelAuditCard";
import { ModelAuditFilters } from "./ModelAuditFilters";
import { ModelAuditMode } from "./ModelAuditMode";
import { ModelAuditTenantSelect } from "./ModelAuditTenantSelect";
import { useModelAudit } from "./useModelAudit";
import { ModelAuditGroup } from "./ModelAuditGroup";
import { ModelAuditTree } from "./ModelAuditTree";
import { UnassociatedSafetyEvents } from "./UnassociatedSafetyEvents";
import { Button as SafetyButton } from "@bisheng/ui";

export function ModelAuditPanel() {
  const { user } = useContext(userContext);
  const identity = user as {
    tenant_id?: unknown;
    tenant_name?: string;
    role?: unknown;
    is_global_super?: unknown;
    is_child_admin?: unknown;
  };
  const ownTenant = Number(identity?.tenant_id);
  const canConfigure =
    identity?.is_child_admin !== true &&
    (identity?.role === "admin" || identity?.is_global_super === true);
  const initialTenant = canConfigure
    ? 1
    : Number.isSafeInteger(ownTenant) && ownTenant > 0
      ? ownTenant
      : undefined;
  const [selectedTenant, setTenant] = useState<number | undefined>();
  const tenant = canConfigure ? selectedTenant : initialTenant;
  const { t } = useTranslation();
  return (
    <div className="min-w-0 space-y-4">
      <div className="grid items-center gap-3 border-b pb-4 md:grid-cols-[minmax(0,1fr)_auto]">
        {canConfigure ? (
          <ModelAuditTenantSelect
            initialTenant={initialTenant}
            value={tenant}
            onChange={setTenant}
          />
        ) : (
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {t("dsh.modelAuditView.tenant")}
            </span>
            {displayTenantName(identity?.tenant_name) ||
              t("dsh.modelAuditView.managed_tenant")}
          </p>
        )}
        {tenant !== undefined && (
          <ModelAuditMode
            key={"mode-" + tenant}
            tenantId={tenant}
            canConfigure={canConfigure}
          />
        )}
      </div>
      {tenant !== undefined && (
        <ModelAuditRequests key={"requests-" + tenant} tenantId={tenant} />
      )}
    </div>
  );
}

interface ModelAuditRequestsProps {
  tenantId?: number;
  initialView?: "groups" | "unassociated" | "requests";
}
export function ModelAuditRequests(props: ModelAuditRequestsProps) {
  const { user } = useContext(userContext);
  const identity = user as {
    user_id?: unknown;
    tenant_id?: unknown;
    leaf_tenant_id?: unknown;
    role?: unknown;
    is_global_super?: unknown;
    is_child_admin?: unknown;
  } | null;
  const scope = JSON.stringify([
    props.tenantId,
    identity?.user_id,
    identity?.tenant_id,
    identity?.leaf_tenant_id,
    identity?.role,
    identity?.is_global_super,
    identity?.is_child_admin,
  ]);
  return <ModelAuditViews key={scope} {...props} />;
}

function ModelAuditViews(props: ModelAuditRequestsProps) {
  const { t } = useTranslation();
  const [eventsOpen, setEventsOpen] = useState(false);
  const [eventsVisited, setEventsVisited] = useState(false);
  return (
    <div className="min-w-0 space-y-4">
      <div className="dsh-content-safety">
        <SafetyButton
          type="button"
          variant="outlined"
          aria-pressed={eventsOpen}
          onClick={() => {
            setEventsVisited(true);
            setEventsOpen((old) => !old);
          }}
        >
          {t(
            eventsOpen
              ? "dsh.modelAuditView.return_results"
              : "dsh.contentSafety.association.unassociated_title",
          )}
        </SafetyButton>
      </div>
      <div hidden={eventsOpen}>
        <ModelAuditRequestPage {...props} />
      </div>
      {eventsVisited && (
        <div hidden={!eventsOpen}>
          <UnassociatedSafetyEvents
            tenantId={props.tenantId}
            active={eventsOpen}
          />
        </div>
      )}
    </div>
  );
}

function ModelAuditRequestPage({
  tenantId,
  initialView = "groups",
}: ModelAuditRequestsProps) {
  const { t } = useTranslation();
  const initialQuery = { tenant_id: tenantId, limit: 20 };
  const [query, setQuery] = useState<ModelAuditQuery>(initialQuery);
  const [draft, setDraft] = useState<ModelAuditQuery>(initialQuery);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [view, setView] = useState(initialView);
  const [groups, setGroups] = useState<AuditGroupPage | AuditTreePage | null>(
    null,
  );
  const [groupLoading, setGroupLoading] = useState(false);
  const [groupFailed, setGroupFailed] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<AuditQueryReadiness | null>(null);
  const [readinessFailed, setReadinessFailed] = useState(false);
  const groupMode = useRef<"tree" | "legacy" | null>(null);
  const saved = useRef<{
    view: typeof view;
    query: ModelAuditQuery;
    draft: ModelAuditQuery;
    history: (string | undefined)[];
    scroll: number;
    container: HTMLElement | null;
    openGroup: string | null;
  } | null>(null);
  const [hasReturn, setHasReturn] = useState(false);
  const section = useRef<HTMLElement>(null);
  const requestQuery = useMemo(
    () => ({
      ...query,
      association_status:
        view === "unassociated" ? ("UNASSOCIATED" as const) : undefined,
    }),
    [query, view],
  );
  const {
    page,
    loading: requestLoading,
    failed: requestFailed,
    missing,
  } = useModelAudit(requestQuery, revision, undefined, view !== "groups");
  useEffect(() => {
    if (view === "groups") return;
    const abort = new AbortController();
    setReadiness(null);
    setReadinessFailed(false);
    getAuditReadiness(tenantId, abort.signal)
      .then((value) => {
        if (!abort.signal.aborted) setReadiness(value);
      })
      .catch(() => {
        if (!abort.signal.aborted) setReadinessFailed(true);
      });
    return () => abort.abort();
  }, [tenantId, revision, view]);
  useEffect(() => {
    if (view !== "groups") return;
    const abort = new AbortController();
    setGroups(null);
    setReadiness(null);
    setReadinessFailed(false);
    setGroupLoading(true);
    setGroupFailed(false);
    const load = async () => {
      const capabilities = await getAuditReadiness(tenantId, abort.signal);
      if (abort.signal.aborted) return null;
      const nextMode =
        capabilities.hierarchy_available && capabilities.hierarchy_ready
          ? "tree"
          : "legacy";
      if (query.cursor && groupMode.current && groupMode.current !== nextMode) {
        return {
          items: [],
          next_cursor: null,
          scan_limited: false,
          progress: { ...capabilities, refresh_required: true },
        };
      }
      groupMode.current = nextMode;
      if (nextMode === "tree") return getAuditTree(query, abort.signal);
      const legacy = await getAuditGroups(query, abort.signal);
      return { ...legacy, progress: { ...capabilities, ...legacy.progress } };
    };
    load()
      .then((value) => {
        if (!abort.signal.aborted && value) {
          setGroups(value);
          setReadiness(value.progress);
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) setGroupFailed(true);
      })
      .finally(() => {
        if (!abort.signal.aborted) setGroupLoading(false);
      });
    return () => abort.abort();
  }, [query, revision, view, tenantId]);
  const loading = view === "groups" ? groupLoading : requestLoading;
  const failed = view === "groups" ? groupFailed : requestFailed;
  const nextCursor =
    view === "groups" ? groups?.next_cursor : page?.next_cursor;
  const pending = (
    Object.keys({ ...query, ...draft }) as (keyof ModelAuditQuery)[]
  ).some((key) => key !== "cursor" && query[key] !== draft[key]);
  const handleApply = (next: ModelAuditQuery, preserveReturn = false) => {
    if (!preserveReturn) {
      setHasReturn(false);
      saved.current = null;
    }
    const firstPage = { ...next, cursor: undefined };
    setHistory([]);
    setExpanded(null);
    setOpenGroup(null);
    setDraft(firstPage);
    setQuery(firstPage);
  };
  const handleNavigate = (userId: number, conversationId: string) => {
    if (!hasReturn) {
      let container = section.current?.parentElement || null;
      while (
        container &&
        (container.scrollHeight <= container.clientHeight ||
          !/(auto|scroll)/.test(window.getComputedStyle(container).overflowY))
      )
        container = container.parentElement;
      saved.current = {
        view,
        query,
        draft,
        history,
        scroll: container?.scrollTop ?? window.scrollY,
        container,
        openGroup,
      };
      setHasReturn(true);
    }
    setView("requests");
    handleApply(
      {
        tenant_id: tenantId,
        limit: 20,
        user_id: userId,
        conversation_id: conversationId,
      },
      true,
    );
  };
  const handleRefresh = () => {
    setExpanded(null);
    setOpenGroup(null);
    setHistory([]);
    setQuery((old) => ({ ...old, cursor: undefined }));
    setRevision((old) => old + 1);
  };
  return (
    <section
      ref={section}
      tabIndex={-1}
      className="min-w-0 space-y-4"
      aria-label={t("dsh.modelAudit")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium">{t("dsh.modelAuditView.log_title")}</h2>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-sm [@media(pointer:coarse)]:min-h-11"
          aria-expanded={infoOpen}
          aria-controls="audit-query-info"
          onClick={() => setInfoOpen((old) => !old)}
        >
          {t("dsh.modelAuditView.query_info")}
        </Button>
      </div>
      {infoOpen && (
        <div
          id="audit-query-info"
          className="space-y-2 rounded-lg bg-muted/50 p-4 text-sm text-muted-foreground"
        >
          <p>{t("dsh.modelAuditView.scopeHint")}</p>
          <p>{t("dsh.modelAuditView.modelHint")}</p>
          <p>{t("dsh.modelAuditView.backlogUnknown")}</p>
        </div>
      )}
      <ModelAuditFilters
        pending={pending}
        tenantId={tenantId}
        draft={draft}
        statusReady={readiness?.status_ready === true}
        nameReady={readiness?.name_ready === true}
        onChange={(changes) => setDraft((old) => ({ ...old, ...changes }))}
        onApply={() => handleApply(draft)}
        onReset={() => handleApply(initialQuery)}
      />
      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        {(["groups", "unassociated", "requests"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={view === value ? "default" : "ghost"}
            aria-pressed={view === value}
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            onClick={() => {
              setHasReturn(false);
              saved.current = null;
              setView(value);
              setHistory([]);
              setExpanded(null);
              setOpenGroup(null);
              setQuery((old) => ({ ...old, cursor: undefined }));
            }}
          >
            {t("dsh.modelAuditView.views." + value)}
          </Button>
        ))}
        {view === "groups" && (
          <span className="text-xs text-muted-foreground">
            {t("dsh.modelAuditView.group_order")}
          </span>
        )}
        {hasReturn && (
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={() => {
              const old = saved.current;
              if (!old) return;
              setView(old.view);
              setQuery(old.query);
              setDraft(old.draft);
              setHistory(old.history);
              setExpanded(null);
              setOpenGroup(old.openGroup);
              setHasReturn(false);
              window.requestAnimationFrame(() => {
                section.current?.focus({ preventScroll: true });
                if (old.container?.isConnected)
                  old.container.scrollTop = old.scroll;
                else window.scrollTo(0, old.scroll);
              });
            }}
          >
            {t("dsh.modelAuditView.return_results")}
          </Button>
        )}
      </div>
      {(readinessFailed ||
        readiness?.status_ready === false ||
        readiness?.name_ready === false) && (
        <p role="status" className="text-sm text-muted-foreground">
          {t("dsh.modelAuditView.index_preparing")}
        </p>
      )}
      {view === "groups" && readiness?.indexing_pending !== false && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("dsh.modelAuditView.index_delay")}
        </p>
      )}
      {view === "groups" &&
        readiness?.hierarchy_available &&
        readiness.phase !== "READY" && (
          <p role="status" className="text-xs text-muted-foreground">
            {t(
              "dsh.modelAuditView.tree." +
                (readiness.hierarchy_ready ? "updating" : "preparing"),
            )}
          </p>
        )}
      {hasReturn && (
        <p className="text-xs text-muted-foreground">
          {t("dsh.modelAuditView.all_scope")}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
        <p>
          {t("dsh.modelAuditView.watermark")}:{" "}
          {dshTime(
            view === "groups"
              ? groups?.items
                  .map((group) => group.updated_at)
                  .sort()
                  .at(-1)
              : page?.progress.last_write_at,
          )}{" "}
          · {t("dsh.modelAuditView.async_hint")}
        </p>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-sm [@media(pointer:coarse)]:min-h-11"
          disabled={loading}
          onClick={handleRefresh}
        >
          {t("dsh.modelAuditView.refresh_records")}
        </Button>
      </div>
      {view !== "groups" && missing && (
        <p role="status">{t("dsh.modelAuditView.missing." + missing.gap)}</p>
      )}
      {failed ? (
        <p role="alert">{t("dsh.modelAuditView.loadError")}</p>
      ) : loading ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : view === "groups" ? (
        <>
          {groups?.scan_limited && (
            <p role="status">{t("dsh.modelAuditView.scan_limited")}</p>
          )}
          {groups?.progress.refresh_required && (
            <div role="alert" className="space-y-2 text-sm">
              <p>{t("dsh.modelAuditView.tree.refresh_required")}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRefresh}
              >
                {t("dsh.modelAuditView.refresh_records")}
              </Button>
            </div>
          )}
          {groups?.progress.status_ready &&
            groups.progress.name_ready &&
            !groups.items.length &&
            !groups.progress.refresh_required &&
            !groups.next_cursor && <p>{t("dsh.modelAuditView.empty")}</p>}
          {groups?.items.map((group) =>
            "generation" in group ? (
              <ModelAuditTree
                key={
                  group.conversation_key +
                  ":" +
                  revision +
                  ":" +
                  group.generation
                }
                node={group}
                progress={groups.progress}
                query={query}
                expanded={openGroup === group.conversation_key}
                onToggle={() =>
                  setOpenGroup((old) =>
                    old === group.conversation_key
                      ? null
                      : group.conversation_key,
                  )
                }
                onNavigate={handleNavigate}
                onRefresh={handleRefresh}
              />
            ) : (
              <ModelAuditGroup
                key={group.conversation_key + ":" + revision}
                group={group}
                progress={groups.progress}
                query={query}
                expanded={openGroup === group.conversation_key}
                onToggle={() =>
                  setOpenGroup((old) =>
                    old === group.conversation_key
                      ? null
                      : group.conversation_key,
                  )
                }
                onNavigate={handleNavigate}
              />
            ),
          )}
        </>
      ) : !page?.items.length ? (
        <p>{t("dsh.modelAuditView.empty")}</p>
      ) : (
        page.items.map((row) => (
          <ModelAuditCard
            key={row.request_id}
            row={row}
            tenantId={tenantId}
            expanded={expanded === row.request_id}
            onToggle={() =>
              setExpanded(expanded === row.request_id ? null : row.request_id)
            }
            onNavigate={handleNavigate}
          />
        ))
      )}
      <DshPager
        previous={history.length > 0}
        next={!!nextCursor}
        loading={loading}
        onPrevious={() => {
          setExpanded(null);
          setOpenGroup(null);
          setQuery((old) => ({ ...old, cursor: history[history.length - 1] }));
          setHistory((old) => old.slice(0, -1));
        }}
        onNext={() => {
          if (!nextCursor) return;
          setExpanded(null);
          setOpenGroup(null);
          setHistory((old) => [...old, query.cursor]);
          setQuery((old) => ({
            ...old,
            cursor: nextCursor || undefined,
          }));
        }}
      />
    </section>
  );
}
