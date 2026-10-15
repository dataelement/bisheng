import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { userContext } from "@/contexts/userContext";
import {
  contentStates,
  modelResults,
  responseResults,
  settlements,
} from "@/types/dshModelAudit";
import type { ModelAuditQuery } from "@/types/dshModelAudit";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshChoice, DshPager, dshTime } from "./common";
import { ModelAuditBody } from "./ModelAuditBody";
import { ModelAuditMode } from "./ModelAuditMode";
import { ModelAuditTenantSelect } from "./ModelAuditTenantSelect";
import { ModelAuditUserSelect } from "./ModelAuditUserSelect";
import { ModelAuditModelSelect } from "./ModelAuditModelSelect";
import { useModelAudit } from "./useModelAudit";

export function ModelAuditPanel() {
  const { user } = useContext(userContext);
  const identity = user as {
    tenant_id?: unknown;
    role?: unknown;
    is_global_super?: unknown;
    is_child_admin?: unknown;
  };
  const ownTenant = Number(identity?.tenant_id);
  const initialTenant =
    Number.isSafeInteger(ownTenant) && ownTenant > 0 ? ownTenant : undefined;
  const canConfigure =
    identity?.is_child_admin !== true &&
    (identity?.role === "admin" || identity?.is_global_super === true);
  const [tenant, setTenant] = useState<number | undefined>(
    canConfigure ? undefined : initialTenant,
  );
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <h2 className="font-medium">{t("dsh.modelAudit")}</h2>
      {canConfigure && (
        <ModelAuditTenantSelect
          initialTenant={initialTenant}
          value={tenant}
          onChange={setTenant}
        />
      )}
      {tenant !== undefined && (
        <>
          <ModelAuditMode
            key={"mode-" + tenant}
            tenantId={tenant}
            canConfigure={canConfigure}
          />
          <ModelAuditRequests key={"requests-" + tenant} tenantId={tenant} />
        </>
      )}
    </div>
  );
}

interface ModelAuditRequestsProps {
  tenantId?: number;
}
export function ModelAuditRequests({ tenantId }: ModelAuditRequestsProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState<ModelAuditQuery>({
    tenant_id: tenantId,
    limit: 20,
  });
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const { page, loading, failed, missing } = useModelAudit(query, revision);
  const handleFilter = (changes: Partial<ModelAuditQuery>) => {
    setHistory([]);
    setExpanded(null);
    setQuery((old) => ({ ...old, ...changes, cursor: undefined }));
  };
  const debugTextFilters = [
    "request_id",
    "conversation_id",
    "provider_name",
  ] as const;
  const axes = [
    ["model_result", modelResults],
    ["response_result", responseResults],
    ["usage_settlement", settlements],
    ["content_status", contentStates],
  ] as const;
  const advancedCount = [
    ...debugTextFilters,
    ...axes.map(([key]) => key),
    "association_status" as const,
  ].filter((key) => query[key] !== undefined && query[key] !== "").length;
  const renderTextFilter = (key: (typeof debugTextFilters)[number]) => (
    <label key={key} htmlFor={"audit-" + key} className="space-y-1">
      <span className="block text-sm">
        {t("dsh.modelAuditView.filters." + key)}
      </span>
      <Input
        id={"audit-" + key}
        aria-label={t("dsh.modelAuditView.filters." + key)}
        value={query[key] || ""}
        maxLength={
          key === "conversation_id" ? 256 : key === "request_id" ? 36 : 128
        }
        onChange={(event) =>
          handleFilter({ [key]: event.target.value || undefined })
        }
      />
    </label>
  );
  return (
    <section className="space-y-4" aria-label={t("dsh.modelAudit")}>
      <p className="text-sm text-muted-foreground">
        {t("dsh.modelAuditView.scopeHint")}
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <ModelAuditUserSelect
          tenantId={tenantId}
          value={query.user_id}
          onChange={(userId) =>
            handleFilter({ user_id: userId, user_keyword: undefined })
          }
        />
        <ModelAuditModelSelect
          tenantId={tenantId}
          value={query.model_name}
          onChange={(name) => handleFilter({ model_name: name })}
        />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {(["start_at", "end_at"] as const).map((key) => (
          <label key={key} htmlFor={"audit-" + key}>
            <span className="block text-sm">
              {t("dsh.modelAuditView.filters." + key)}
            </span>
            <Input
              id={"audit-" + key}
              aria-label={t("dsh.modelAuditView.filters." + key)}
              type="datetime-local"
              value={query[key] ? localDateTime(query[key]) : ""}
              onChange={(event) =>
                handleFilter({
                  [key]: event.target.value
                    ? new Date(event.target.value).toISOString()
                    : undefined,
                })
              }
            />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          aria-expanded={advancedOpen}
          aria-controls="audit-advanced-filters"
          onClick={() => setAdvancedOpen((old) => !old)}
        >
          {t("dsh.modelAuditView.advancedFilters")}
          {advancedCount > 0 ? ` (${advancedCount})` : ""}
        </Button>
        <Button
          variant="outline"
          disabled={loading}
          onClick={() => {
            setExpanded(null);
            setRevision((old) => old + 1);
          }}
        >
          {t("dsh.refresh")}
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            setHistory([]);
            setExpanded(null);
            setQuery({ tenant_id: tenantId, limit: 20 });
          }}
        >
          {t("dsh.modelAuditView.resetFilters")}
        </Button>
      </div>
      {advancedOpen && (
        <div id="audit-advanced-filters" className="space-y-3">
          <div className="grid gap-3 md:grid-cols-3">
            {debugTextFilters.map(renderTextFilter)}
          </div>
          <div className="flex flex-wrap gap-2">
            {axes.map(([key, choices]) => (
              <DshChoice
                key={key}
                label={t("dsh.modelAuditView.axes." + key)}
                value={query[key] || "ALL"}
                options={[
                  {
                    value: "ALL",
                    label:
                      t("dsh.modelAuditView.axes." + key) +
                      " · " +
                      t("dsh.modelAuditView.all"),
                  },
                  ...choices.map((value) => ({
                    value,
                    label: t("dsh.modelAuditView.states." + value),
                  })),
                ]}
                onChange={(value) =>
                  handleFilter({ [key]: value === "ALL" ? undefined : value })
                }
              />
            ))}
            <DshChoice
              label={t("dsh.modelAuditView.association")}
              value={query.association_status || "ALL"}
              options={(["ALL", "ASSOCIATED", "UNASSOCIATED"] as const).map(
                (value) => ({
                  value,
                  label: t("dsh.modelAuditView.states." + value),
                }),
              )}
              onChange={(value) =>
                handleFilter({
                  association_status:
                    value === "ALL"
                      ? undefined
                      : (value as "ASSOCIATED" | "UNASSOCIATED"),
                })
              }
            />
          </div>
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        {t("dsh.modelAuditView.watermark")}:{" "}
        {dshTime(page?.progress.last_write_at)}
      </p>
      <p className="text-sm text-muted-foreground">
        {t("dsh.modelAuditView.backlogUnknown")}
      </p>
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
          <article
            key={row.request_id}
            className="space-y-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">{row.model_name}</p>
                <p className="text-sm text-muted-foreground">
                  {dshTime(row.started_at)} · {t("dsh.modelAuditView.user")} #
                  {row.user_id} ·{" "}
                  {t(
                    "dsh.modelAuditView.kinds." +
                      (row.request_kind || "unknown"),
                  )}
                </p>
                <p className="break-all font-mono text-sm">{row.request_id}</p>
              </div>
              <Button
                variant="outline"
                aria-expanded={expanded === row.request_id}
                disabled={
                  row.content_status === "NOT_CAPTURED" ||
                  row.effective_mode !== "CONTENT"
                }
                onClick={() =>
                  setExpanded(
                    expanded === row.request_id ? null : row.request_id,
                  )
                }
              >
                {t(
                  expanded === row.request_id
                    ? "dsh.modelAuditView.collapse"
                    : "dsh.modelAuditView.original",
                )}
              </Button>
            </div>
            <p className="break-all text-sm">
              {t("dsh.modelAuditView.conversation")}:{" "}
              {row.conversation_id ??
                t("dsh.modelAuditView.states.UNASSOCIATED")}
            </p>
            {row.conversation_id !== null && (
              <Button
                variant="link"
                onClick={() => {
                  setHistory([]);
                  setExpanded(null);
                  setQuery({
                    tenant_id: tenantId,
                    limit: 20,
                    user_id: row.user_id,
                    conversation_id: row.conversation_id || undefined,
                  });
                }}
              >
                {t("dsh.modelAuditView.timeline")}
              </Button>
            )}
            {row.context_invalid && (
              <p className="text-sm">
                {t("dsh.modelAuditView.invalidContext")}
              </p>
            )}
            <dl className="grid gap-2 text-sm md:grid-cols-2">
              {axes.map(([key]) => (
                <div key={key} className="flex gap-2">
                  <dt>{t("dsh.modelAuditView.axes." + key)}</dt>
                  <dd>{t("dsh.modelAuditView.states." + row[key])}</dd>
                </div>
              ))}
              <div>
                {t("dsh.modelAuditView.size", {
                  count: row.input_units,
                  bytes: row.input_bytes + row.output_bytes,
                })}
              </div>
              <div>
                {t("dsh.modelAuditView.tokens")}:{" "}
                {row.usage?.total_tokens ?? t("dsh.modelAuditView.unknown")}
              </div>
            </dl>
            {expanded === row.request_id && (
              <ModelAuditBody requestId={row.request_id} tenantId={tenantId} />
            )}
          </article>
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

function localDateTime(value: string): string {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
