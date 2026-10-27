import { getAuditSafetyEvents } from "@/controllers/API/dshContentSafety";
import "@/style/dsh-content-safety.css";
import type {
  ContentSafetyEventMetadata,
  ContentSafetyState,
  SafetyDetailsStatus,
} from "@/types/dshContentSafety";
import { Button, Tag } from "@bisheng/ui";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dshTime } from "./common";

interface ContentSafetyDetailsProps {
  requestId: string;
  tenantId?: number;
  detailsStatus?: SafetyDetailsStatus;
}
interface ContentSafetyEventDetailsProps {
  event: ContentSafetyEventMetadata;
}

export function safetyTagColor(state: ContentSafetyState) {
  if (state === "BLOCKED" || state === "ERROR") return "danger";
  if (state === "PASSED") return "success";
  return "default";
}

export function ContentSafetyEventDetails({
  event,
}: ContentSafetyEventDetailsProps) {
  const { t } = useTranslation();
  const blocked = event.stage_results.input === "BLOCKED" || event.stage_results.output === "BLOCKED";
  const matched = event.matched_words;
  const fields = [
    ["source", event.source_id],
    ["event_id", event.event_id],
    ["event_kind", t("dsh.contentSafety.event_kinds." + event.event_kind)],
    ["event_version", event.event_version],
    ["gateway_request_id", event.gateway_request_id],
    ["backend_request_id", event.backend_request_id],
    ["policy_version", event.policy_version],
    ["builtin_digest", event.builtin_digest],
    ["hit_count", event.hit_count],
    ["request_started_at", dshTime(event.request_started_at)],
    ["occurred_at", dshTime(event.occurred_at)],
    ["received_at", dshTime(event.received_at)],
    ["drain_status", t("dsh.contentSafety.drain." + event.drain_status)],
  ] as const;
  return (
    <div className="dsh-content-safety">
      <article className="min-w-0 space-y-3 rounded-lg border p-3">
        <div className="flex flex-wrap gap-2">
          {(["input", "output"] as const).map((stage) => (
            <Tag
              key={stage}
              color={safetyTagColor(event.stage_results[stage])}
              size="small"
            >
              {t("dsh.contentSafety.details." + stage) +
                ": " +
                t("dsh.contentSafety.states." + event.stage_results[stage])}
            </Tag>
          ))}
        </div>
        {blocked && (
          <section aria-label={t("dsh.contentSafety.details.matched_words")} className="space-y-2 text-xs">
            <h4 className="font-medium">{t("dsh.contentSafety.details.matched_words")}</h4>
            {matched && (matched.input.length > 0 || matched.output.length > 0) ? (
              <dl className="space-y-2">
                {(["input", "output"] as const).filter((direction) => matched[direction].length > 0).map((direction) => (
                  <div key={direction}>
                    <dt className="text-muted-foreground">{t("dsh.contentSafety.details." + direction)}</dt>
                    <dd className="break-all">{matched[direction].map((word) => <p key={word}>{word}</p>)}</dd>
                  </div>
                ))}
              </dl>
            ) : <p className="text-muted-foreground">{t("dsh.contentSafety.details.matched_words_unavailable")}</p>}
          </section>
        )}
        <dl className="grid min-w-0 gap-2 text-xs sm:grid-cols-2">
          {fields.map(([key, value]) => (
            <div key={key} className="min-w-0 space-y-1">
              <dt className="text-muted-foreground">
                {t("dsh.contentSafety.details." + key)}
              </dt>
              <dd className="break-all">
                {value ?? t("dsh.contentSafety.details.unknown")}
              </dd>
            </div>
          ))}
          <div className="min-w-0 space-y-1">
            <dt className="text-muted-foreground">
              {t("dsh.contentSafety.details.rule_refs")}
            </dt>
            <dd className="break-all font-mono">
              {event.rule_refs.length ? event.rule_refs.join(", ") : "—"}
            </dd>
          </div>
        </dl>
        <p className="text-xs">
          {t(
            "dsh.contentSafety.details." +
              (event.forwarded ? "forwarded" : "not_forwarded"),
          )}
        </p>
        {event.hit_count_truncated && (
          <p className="text-xs text-muted-foreground">
            {t("dsh.contentSafety.details.hit_count_truncated")}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {t("dsh.contentSafety.drain.usage_hint")}
        </p>
      </article>
    </div>
  );
}

export function ContentSafetyDetails(props: ContentSafetyDetailsProps) {
  return (
    <ContentSafetyDetailsPage
      key={props.requestId + ":" + props.tenantId}
      {...props}
    />
  );
}

function ContentSafetyDetailsPage({
  requestId,
  tenantId,
  detailsStatus,
}: ContentSafetyDetailsProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ContentSafetyEventMetadata[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<SafetyDetailsStatus>(
    detailsStatus ?? "UNREPORTED",
  );
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const attemptedCursor = useRef<string | undefined>(undefined);

  async function load(next?: string) {
    if (locked.current) return;
    locked.current = true;
    attemptedCursor.current = next;
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    setFailed(false);
    try {
      const page = await getAuditSafetyEvents(
        requestId,
        { tenant_id: tenantId, cursor: next, limit: 20 },
        abort.signal,
      );
      if (abort.signal.aborted) return;
      setItems((old) => {
        const combined = next ? [...old, ...page.items] : page.items;
        return [
          ...new Map(
            combined.map((event) => [
              event.source_id +
                ":" +
                event.event_id +
                ":" +
                event.event_version,
              event,
            ]),
          ).values(),
        ];
      });
      setCursor(page.next_cursor);
      setStatus(
        page.details_status === "UNREPORTED" && detailsStatus === "PURGED"
          ? "PURGED"
          : page.details_status,
      );
    } catch {
      if (!abort.signal.aborted) setFailed(true);
    } finally {
      if (!abort.signal.aborted) {
        setLoading(false);
        locked.current = false;
      }
    }
  }

  useEffect(() => {
    void load();
    return () => {
      controller.current?.abort();
      locked.current = false;
    };
    // The keyed page owns one request and tenant for its entire lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="dsh-content-safety">
      <section
        className="space-y-3 border-t p-4"
        aria-label={t("dsh.contentSafety.details.title")}
        aria-busy={loading}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium">
            {t("dsh.contentSafety.details.title")}
          </h3>
          <Button
            variant="outlined"
            size="small"
            loading={loading}
            disabled={loading}
            onClick={() => void load()}
          >
            {t("dsh.contentSafety.actions.refresh")}
          </Button>
        </div>
        {status !== "AVAILABLE" && (
          <p role="status" className="text-sm text-muted-foreground">
            {t("dsh.contentSafety.details_status." + status)}
          </p>
        )}
        {!loading && !failed && !items.length && (
          <p className="text-sm text-muted-foreground">
            {t("dsh.contentSafety.details.empty")}
          </p>
        )}
        {items.map((event) => (
          <ContentSafetyEventDetails
            key={
              event.source_id + ":" + event.event_id + ":" + event.event_version
            }
            event={event}
          />
        ))}
        {failed && (
          <div role="alert" className="space-y-2 text-sm">
            <p>{t("dsh.contentSafety.errors.events_load_failed")}</p>
            <Button
              variant="outlined"
              size="small"
              onClick={() => void load(attemptedCursor.current)}
            >
              {t("dsh.contentSafety.actions.retry")}
            </Button>
          </div>
        )}
        {cursor && !failed && (
          <Button
            variant="outlined"
            size="small"
            disabled={loading}
            loading={loading}
            onClick={() => void load(cursor)}
          >
            {t("dsh.contentSafety.actions.load_more")}
          </Button>
        )}
        <p className="text-xs text-muted-foreground">
          {t("dsh.contentSafety.details.no_matched_text")}
        </p>
      </section>
    </div>
  );
}
