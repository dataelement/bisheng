import { Button } from "@/components/bs-ui/button";
import { userContext } from "@/contexts/userContext";
import type { ModelAuditQuery } from "@/types/dshModelAudit";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager, dshTime } from "./common";
import { ModelAuditCard } from "./ModelAuditCard";
import { ModelAuditFilters } from "./ModelAuditFilters";
import { ModelAuditMode } from "./ModelAuditMode";
import { ModelAuditTenantSelect } from "./ModelAuditTenantSelect";
import { useModelAudit } from "./useModelAudit";

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
}
export function ModelAuditRequests({ tenantId }: ModelAuditRequestsProps) {
  const { t } = useTranslation();
  const initialQuery = { tenant_id: tenantId, limit: 20 };
  const [query, setQuery] = useState<ModelAuditQuery>(initialQuery);
  const [draft, setDraft] = useState<ModelAuditQuery>(initialQuery);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const { page, loading, failed, missing } = useModelAudit(query, revision);
  const pending = (
    Object.keys({ ...query, ...draft }) as (keyof ModelAuditQuery)[]
  ).some((key) => key !== "cursor" && query[key] !== draft[key]);
  const handleApply = (next: ModelAuditQuery) => {
    const firstPage = { ...next, cursor: undefined };
    setHistory([]);
    setExpanded(null);
    setDraft(firstPage);
    setQuery(firstPage);
  };
  return (
    <section className="min-w-0 space-y-4" aria-label={t("dsh.modelAudit")}>
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
        onChange={(changes) => setDraft((old) => ({ ...old, ...changes }))}
        onApply={() => handleApply(draft)}
        onReset={() => handleApply(initialQuery)}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
        <p>
          {t("dsh.modelAuditView.watermark")}:{" "}
          {dshTime(page?.progress.last_write_at)} ·{" "}
          {t("dsh.modelAuditView.async_hint")}
        </p>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-sm [@media(pointer:coarse)]:min-h-11"
          disabled={loading}
          onClick={() => {
            setExpanded(null);
            setRevision((old) => old + 1);
          }}
        >
          {t("dsh.modelAuditView.refresh_records")}
        </Button>
      </div>
      {missing && (
        <p role="status">{t("dsh.modelAuditView.missing." + missing.gap)}</p>
      )}
      {failed ? (
        <p role="alert">{t("dsh.modelAuditView.loadError")}</p>
      ) : loading ? (
        <p role="status">{t("dsh.loading")}</p>
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
            onNavigate={(userId, conversationId) =>
              handleApply({
                tenant_id: tenantId,
                limit: 20,
                user_id: userId,
                conversation_id: conversationId,
              })
            }
          />
        ))
      )}
      <DshPager
        previous={history.length > 0}
        next={!!page?.next_cursor}
        loading={loading}
        onPrevious={() => {
          setExpanded(null);
          setQuery((old) => ({ ...old, cursor: history[history.length - 1] }));
          setHistory((old) => old.slice(0, -1));
        }}
        onNext={() => {
          if (!page?.next_cursor) return;
          setExpanded(null);
          setHistory((old) => [...old, query.cursor]);
          setQuery((old) => ({
            ...old,
            cursor: page.next_cursor || undefined,
          }));
        }}
      />
    </section>
  );
}
