import { getUnassociatedSafetyEvents } from "@/controllers/API/dshContentSafety";
import "@/style/dsh-content-safety.css";
import type { ContentSafetyEventQuery } from "@/types/dshContentSafety";
import { Button, Input } from "@bisheng/ui";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { ContentSafetyEventDetails } from "./ContentSafetyDetails";

interface UnassociatedSafetyEventsProps {
  tenantId?: number;
  active?: boolean;
}

type FilterKey =
  | "user_id"
  | "model_id"
  | "gateway_request_id"
  | "backend_request_id"
  | "start_at"
  | "end_at";
type EventFilters = Record<FilterKey, string>;
const emptyFilters: EventFilters = {
  user_id: "",
  model_id: "",
  gateway_request_id: "",
  backend_request_id: "",
  start_at: "",
  end_at: "",
};
const fields = [
  ["user_id", "dsh.modelAuditView.user"],
  ["model_id", "dsh.auditHistory.fields.model_id"],
  ["gateway_request_id", "dsh.contentSafety.details.gateway_request_id"],
  ["backend_request_id", "dsh.contentSafety.details.backend_request_id"],
  ["start_at", "dsh.modelAuditView.filters.start_at"],
  ["end_at", "dsh.modelAuditView.filters.end_at"],
] as const;
const isIdentity = (value: string) =>
  /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(Number(value));
const isRequestId = (value: string) =>
  /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);

function validation(filters: EventFilters): string | null {
  if (
    [filters.user_id, filters.model_id].some(
      (value) => value.trim() && !isIdentity(value.trim()),
    )
  )
    return "dsh.contentSafety.validation.invalid_identity";
  if (
    [filters.gateway_request_id, filters.backend_request_id].some(
      (value) => value.trim() && !isRequestId(value.trim()),
    )
  )
    return "dsh.contentSafety.validation.invalid_request_id";
  const end = filters.end_at ? Date.parse(filters.end_at) : Date.now();
  const start = filters.start_at
    ? Date.parse(filters.start_at)
    : end - 7 * 86400000;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end)
    return "dsh.modelAuditView.invalid_time_range";
  return end - start > 31 * 86400000
    ? "dsh.contentSafety.validation.range_too_large"
    : null;
}

function eventQuery(
  tenantId: number | undefined,
  filters: EventFilters,
): ContentSafetyEventQuery {
  return {
    tenant_id: tenantId,
    association_status: "UNASSOCIATED",
    limit: 20,
    user_id: filters.user_id.trim()
      ? Number(filters.user_id.trim())
      : undefined,
    model_id: filters.model_id.trim()
      ? Number(filters.model_id.trim())
      : undefined,
    gateway_request_id: filters.gateway_request_id.trim() || undefined,
    backend_request_id: filters.backend_request_id.trim() || undefined,
    start_at: filters.start_at
      ? new Date(filters.start_at).toISOString()
      : undefined,
    end_at: filters.end_at ? new Date(filters.end_at).toISOString() : undefined,
  };
}

export function UnassociatedSafetyEvents(props: UnassociatedSafetyEventsProps) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            cacheTime: 0,
            staleTime: Infinity,
            refetchOnWindowFocus: false,
            refetchOnReconnect: false,
          },
        },
        // This local metadata view must not log transport errors that may contain credential-bearing request configs.
        logger: { log: () => {}, warn: () => {}, error: () => {} },
      }),
  );
  return (
    <div className="dsh-content-safety">
      <QueryClientProvider client={client}>
        <UnassociatedSafetyEventPage
          key={props.tenantId ?? "current-tenant"}
          {...props}
        />
      </QueryClientProvider>
    </div>
  );
}

function UnassociatedSafetyEventPage({
  tenantId,
  active = true,
}: UnassociatedSafetyEventsProps) {
  const { t } = useTranslation();
  const id = useId();
  const [draft, setDraft] = useState(emptyFilters);
  const [applied, setApplied] = useState(emptyFilters);
  const [cursor, setCursor] = useState<string>();
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const query = { ...eventQuery(tenantId, applied), cursor };
  const result = useQuery({
    queryKey: ["dsh-content-safety", "unassociated-events", query, revision],
    queryFn: ({ signal }) => getUnassociatedSafetyEvents(query, signal),
    enabled: active,
  });
  const error = validation(draft);
  const timeError =
    error === "dsh.modelAuditView.invalid_time_range" ||
    error === "dsh.contentSafety.validation.range_too_large";
  function fieldInvalid(key: FilterKey) {
    const value = draft[key].trim();
    if (key === "user_id" || key === "model_id")
      return !!value && !isIdentity(value);
    if (key === "gateway_request_id" || key === "backend_request_id")
      return !!value && !isRequestId(value);
    return !!timeError;
  }
  const pending = fields.some(([key]) => draft[key] !== applied[key]);
  const busy = result.isFetching;
  const page = result.data;
  function handleApply(filters: EventFilters) {
    if (validation(filters)) return;
    setApplied({ ...filters });
    setCursor(undefined);
    setHistory([]);
    setRevision((old) => old + 1);
  }
  function handleRefresh() {
    setCursor(undefined);
    setHistory([]);
    setRevision((old) => old + 1);
  }
  return (
    <section
      className="min-w-0 space-y-4"
      aria-label={t("dsh.contentSafety.association.unassociated_title")}
    >
      <h2 className="font-medium">
        {t("dsh.contentSafety.association.unassociated_title")}
      </h2>
      <p className="text-sm text-text-2">
        {t("dsh.contentSafety.association.unassociated_hint")}
      </p>
      <p className="text-xs text-text-3">
        {t("dsh.contentSafety.association.filter_hint")}
      </p>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          handleApply(draft);
        }}
      >
        <div className="grid gap-3 md:grid-cols-2">
          {fields.map(([key, label]) => (
            <label key={key} className="min-w-0 space-y-1 text-sm">
              <span>{t(label)}</span>
              <Input
                type={key.endsWith("_at") ? "datetime-local" : "text"}
                inputMode={
                  key === "user_id" || key === "model_id"
                    ? "numeric"
                    : undefined
                }
                value={draft[key]}
                status={fieldInvalid(key) ? "error" : "default"}
                aria-describedby={fieldInvalid(key) ? id + "-error" : undefined}
                onChange={(event) =>
                  setDraft((old) => ({ ...old, [key]: event.target.value }))
                }
              />
            </label>
          ))}
        </div>
        {error && (
          <p id={id + "-error"} role="alert" className="text-sm text-danger">
            {t(error)}
          </p>
        )}
        {pending && (
          <p role="status" className="text-xs text-text-3">
            {t("dsh.modelAuditView.pending_filters")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" color="primary" disabled={!!error || busy}>
            {t("dsh.modelAuditView.search")}
          </Button>
          <Button
            type="button"
            variant="outlined"
            disabled={busy}
            onClick={() => {
              setDraft(emptyFilters);
              handleApply(emptyFilters);
            }}
          >
            {t("dsh.modelAuditView.resetFilters")}
          </Button>
          <Button
            type="button"
            variant="text"
            disabled={busy}
            onClick={handleRefresh}
          >
            {t("dsh.contentSafety.actions.refresh")}
          </Button>
        </div>
      </form>
      {result.isError ? (
        <div role="alert" className="space-y-2 text-sm">
          <p>{t("dsh.contentSafety.errors.events_load_failed")}</p>
          <Button
            type="button"
            variant="outlined"
            disabled={busy}
            onClick={() => {
              void result.refetch();
            }}
          >
            {t("dsh.contentSafety.actions.retry")}
          </Button>
        </div>
      ) : busy ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : (
        page && (
          <>
            <p role="status" className="text-sm text-text-2">
              {t("dsh.contentSafety.details_status." + page.details_status)}
            </p>
            {!page.items.length && (
              <p>{t("dsh.contentSafety.details.empty")}</p>
            )}
            {page.items.map((event) => (
              <div
                key={
                  event.source_id +
                  ":" +
                  event.event_id +
                  ":" +
                  event.event_version
                }
                className="min-w-0 space-y-2"
              >
                <dl className="grid min-w-0 gap-2 text-sm sm:grid-cols-2">
                  <div className="min-w-0">
                    <dt className="text-text-3">
                      {t("dsh.modelAuditView.user")}
                    </dt>
                    <dd className="break-all">{event.user_id}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-text-3">
                      {t("dsh.auditHistory.fields.model_id")}
                    </dt>
                    <dd className="break-all">{event.model_id}</dd>
                  </div>
                </dl>
                <ContentSafetyEventDetails event={event} />
              </div>
            ))}
          </>
        )
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outlined"
          disabled={!history.length || busy}
          onClick={() => {
            setCursor(history[history.length - 1]);
            setHistory((old) => old.slice(0, -1));
          }}
        >
          {t("dsh.previous")}
        </Button>
        <Button
          type="button"
          variant="outlined"
          disabled={!page?.next_cursor || busy || result.isError}
          onClick={() => {
            if (page?.next_cursor) {
              setHistory((old) => [...old, cursor]);
              setCursor(page.next_cursor);
            }
          }}
        >
          {t("dsh.next")}
        </Button>
      </div>
    </section>
  );
}
