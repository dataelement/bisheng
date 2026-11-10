import { Button, Segmented } from "@bisheng/ui";
import { userContext } from "@/contexts/userContext";
import type {
  ModelAuditQuery,
  AuditGroupPage,
  AuditQueryReadiness,
  AuditTreePage,
} from "@/types/dshModelAudit";
import { getAuditGroups, getAuditReadiness, getAuditTree } from "@/controllers/API/dshModelAudit";
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
    identity?.is_child_admin !== true && (identity?.role === "admin" || identity?.is_global_super === true);
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
          <ModelAuditTenantSelect initialTenant={initialTenant} value={tenant} onChange={setTenant} />
        ) : (
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">{t("dsh.modelAuditView.tenant")}</span>
            {displayTenantName(identity?.tenant_name) || t("dsh.modelAuditView.managed_tenant")}
          </p>
        )}
        {tenant !== undefined && (
          <ModelAuditMode key={"mode-" + tenant} tenantId={tenant} canConfigure={canConfigure} />
        )}
      </div>
      {tenant !== undefined && <ModelAuditRequests key={"requests-" + tenant} tenantId={tenant} />}
    </div>
  );
}

interface ModelAuditRequestsProps {
  tenantId?: number;
  initialView?: "groups" | "unassociated";
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
  return <ModelAuditRequestPage key={scope} {...props} />;
}

function ModelAuditRequestPage({ tenantId, initialView = "groups" }: ModelAuditRequestsProps) {
  const { t } = useTranslation();
  const initialQuery = { tenant_id: tenantId, limit: 20 };
  const [query, setQuery] = useState<ModelAuditQuery>(initialQuery);
  const [draft, setDraft] = useState<ModelAuditQuery>(initialQuery);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [view, setView] = useState(initialView);
  const [groups, setGroups] = useState<AuditGroupPage | AuditTreePage | null>(null);
  const [groupLoading, setGroupLoading] = useState(false);
  const [groupFailed, setGroupFailed] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<AuditQueryReadiness | null>(null);
  const [readinessFailed, setReadinessFailed] = useState(false);
  const groupMode = useRef<"tree" | "legacy" | null>(null);
  const requestQuery = useMemo(
    () => ({
      ...query,
      association_status: view === "unassociated" ? ("UNASSOCIATED" as const) : undefined,
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
      const nextMode = capabilities.hierarchy_available && capabilities.hierarchy_ready ? "tree" : "legacy";
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
  const nextCursor = view === "groups" ? groups?.next_cursor : page?.next_cursor;
  const pending = (Object.keys({ ...query, ...draft }) as (keyof ModelAuditQuery)[]).some(
    (key) => key !== "cursor" && query[key] !== draft[key],
  );
  const handleApply = (next: ModelAuditQuery) => {
    const firstPage = { ...next, cursor: undefined };
    setHistory([]);
    setExpanded(null);
    setOpenGroup(null);
    setDraft(firstPage);
    setQuery(firstPage);
  };
  const handleRefresh = () => {
    setExpanded(null);
    setOpenGroup(null);
    setHistory([]);
    setQuery((old) => ({ ...old, cursor: undefined }));
    setRevision((old) => old + 1);
  };
  return (
    <section tabIndex={-1} className="min-w-0 space-y-4" aria-label={t("dsh.modelAudit")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium">{t("dsh.modelAuditView.log_title")}</h2>
      </div>
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
        <Segmented
          size="small"
          aria-label={t("dsh.modelAuditView.title")}
          value={view}
          options={(["groups", "unassociated"] as const).map((value) => ({
            value,
            label: t("dsh.modelAuditView.views." + value),
          }))}
          onChange={(value) => {
            setView(value as typeof view);
            setHistory([]);
            setExpanded(null);
            setOpenGroup(null);
            setQuery((old) => ({ ...old, cursor: undefined }));
          }}
        />
        {view === "groups" && (
          <span className="text-xs text-muted-foreground">{t("dsh.modelAuditView.group_order")}</span>
        )}

      </div>
      {readinessFailed && (
        <p role="alert" className="text-sm text-muted-foreground">
          {t("dsh.modelAuditView.loadError")}
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
          size="small"
          variant="text"
          color="default"
          className="text-sm [@media(pointer:coarse)]:min-h-11"
          disabled={loading}
          onClick={handleRefresh}
        >
          {t("dsh.modelAuditView.refresh_records")}
        </Button>
      </div>
      {view !== "groups" && missing && <p role="status">{t("dsh.modelAuditView.missing." + missing.gap)}</p>}
      {failed ? (
        <p role="alert">{t("dsh.modelAuditView.loadError")}</p>
      ) : loading ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : view === "groups" ? (
        <>
          {groups?.scan_limited && <p role="status">{t("dsh.modelAuditView.scan_limited")}</p>}
          {groups?.progress.refresh_required && (
            <div role="alert" className="space-y-2 text-sm">
              <p>{t("dsh.modelAuditView.tree.refresh_required")}</p>
              <Button type="button" variant="outlined" color="default" size="small" onClick={handleRefresh}>
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
                key={group.conversation_key + ":" + revision + ":" + group.generation}
                node={group}
                progress={groups.progress}
                query={query}
                expanded={openGroup === group.conversation_key}
                onToggle={() =>
                  setOpenGroup((old) => (old === group.conversation_key ? null : group.conversation_key))
                }
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
                  setOpenGroup((old) => (old === group.conversation_key ? null : group.conversation_key))
                }
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
            onToggle={() => setExpanded(expanded === row.request_id ? null : row.request_id)}
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
