import { getAuditSafetyEvents } from "@/controllers/API/dshContentSafety";
import "@/style/dsh-content-safety.css";
import type {
  ContentSafetyEventMetadata,
  ContentSafetyState,
  SafetyDetailsStatus,
} from "@/types/dshContentSafety";
import { Button } from "@bisheng/ui";
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
  const words = [...new Set([
    ...(event.matched_words?.input ?? []),
    ...(event.matched_words?.output ?? []),
  ])];
  return (
    <div className="dsh-content-safety">
      <article className="grid min-w-0 gap-4 rounded-lg border p-3 text-xs sm:grid-cols-2">
        <section aria-label={t("dsh.contentSafety.details.matched_words")} className="min-w-0 space-y-2">
          <h4 className="font-medium">{t("dsh.contentSafety.details.matched_words")}</h4>
          {words.length ? (
            <div className="space-y-1 break-all">
              {words.map((word) => <p key={word}>{word}</p>)}
            </div>
          ) : (
            <p className="text-muted-foreground">
              {t("dsh.contentSafety.details." + (blocked ? "matched_words_unavailable" : "no_matches"))}
            </p>
          )}
        </section>
        <dl className="min-w-0 space-y-1">
          <dt className="text-muted-foreground">{t("dsh.contentSafety.details.occurred_at")}</dt>
          <dd><time dateTime={event.occurred_at}>{dshTime(event.occurred_at)}</time></dd>
        </dl>
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
      </section>
    </div>
  );
}
