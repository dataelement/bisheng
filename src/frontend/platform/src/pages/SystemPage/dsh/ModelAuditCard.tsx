import { Button } from "@/components/bs-ui/button";
import type { ModelAuditRecord } from "@/types/dshModelAudit";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dshTime } from "./common";
import { ModelAuditBody } from "./ModelAuditBody";
import { ModelAuditParent } from "./ModelAuditParent";

interface ModelAuditCardProps {
  row: ModelAuditRecord;
  tenantId?: number;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: (userId: number, conversationId: string) => void;
}

const statusAxes = [
  "model_result",
  "response_result",
  "usage_settlement",
  "content_status",
] as const;

function statusColor(value: string) {
  if (["FAILED", "ERROR", "INTERRUPTED"].includes(value))
    return "text-destructive";
  if (["SUCCEEDED", "COMPLETED", "SETTLED", "COMPLETE"].includes(value))
    return "text-success-foreground";
  if (["PARTIAL", "UNCERTAIN", "USAGE_UNKNOWN", "UNKNOWN"].includes(value))
    return "font-medium text-foreground";
  if (["RUNNING", "PENDING"].includes(value))
    return "text-primary dark:text-foreground";
  return "text-muted-foreground";
}

export function ModelAuditCard({
  row,
  tenantId,
  expanded,
  onToggle,
  onNavigate,
}: ModelAuditCardProps) {
  const { t } = useTranslation();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const bodyId = useId();
  const originalButton = useRef<HTMLButtonElement>(null);
  return (
    <article className="min-w-0 overflow-hidden rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
        <p
          className="w-full min-w-0 truncate font-medium text-foreground md:w-auto md:flex-1"
          title={row.model_name}
        >
          {row.model_name}
        </p>
        <time
          className="whitespace-nowrap tabular-nums"
          dateTime={row.started_at}
        >
          {dshTime(row.started_at)}
        </time>
        <span className="whitespace-nowrap">
          {t("dsh.modelAuditView.user")} #{row.user_id}
        </span>
        <span className="whitespace-nowrap font-medium text-primary dark:text-foreground">
          {t("dsh.modelAuditView.kinds." + (row.request_kind || "unknown"))}
        </span>
        <ModelAuditParent
          row={row}
          tenantId={tenantId}
          onNavigate={onNavigate}
        />
        {row.conversation_id && (
          <Button
            variant="link"
            className="h-7 p-0 text-xs dark:text-foreground [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
            onClick={() => {
              if (row.conversation_id)
                onNavigate(row.user_id, row.conversation_id);
            }}
          >
            {t("dsh.modelAuditView.timeline")}
          </Button>
        )}
        <Button
          variant="link"
          className="h-7 p-0 text-xs dark:text-foreground [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
          aria-expanded={detailsOpen}
          aria-controls={detailsOpen ? detailsId : undefined}
          onClick={() => setDetailsOpen((old) => !old)}
        >
          {t("dsh.modelAuditView.request_details")}
        </Button>
        <Button
          ref={originalButton}
          variant="outline"
          size="sm"
          className="text-xs [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
          aria-expanded={expanded}
          aria-controls={expanded ? bodyId : undefined}
          disabled={
            row.content_status === "NOT_CAPTURED" ||
            row.effective_mode !== "CONTENT"
          }
          onClick={onToggle}
        >
          {t(
            expanded
              ? "dsh.modelAuditView.collapse"
              : "dsh.modelAuditView.original",
          )}
        </Button>
      </header>
      {detailsOpen && (
        <dl
          id={detailsId}
          className="space-y-1 border-t bg-muted/30 px-4 py-2 text-xs text-muted-foreground"
        >
          <div className="flex gap-2">
            <dt className="shrink-0">
              {t("dsh.modelAuditView.filters.request_id")}
            </dt>
            <dd className="min-w-0 break-all font-mono">{row.request_id}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0">{t("dsh.modelAuditView.conversation")}</dt>
            <dd className="min-w-0 break-all font-mono">
              {row.conversation_id ??
                t("dsh.modelAuditView.states.UNASSOCIATED")}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0">
              {t("dsh.modelAuditView.filters.model_name")}
            </dt>
            <dd className="min-w-0 break-all">{row.model_name}</dd>
          </div>
          {statusAxes.map((key) => (
            <div key={key} className="flex gap-2">
              <dt>{t("dsh.modelAuditView.axes." + key)}</dt>
              <dd className={statusColor(row[key])}>
                {t("dsh.modelAuditView.states." + row[key])}
              </dd>
            </div>
          ))}
          {(row.status_reasons || []).map((reason) => (
            <div key={reason}>
              {t("dsh.modelAuditView.reasons." + reason.replace(":", "_"), {
                defaultValue: t("dsh.modelAuditView.reasons.INVALID_STATE"),
              })}
            </div>
          ))}
        </dl>
      )}
      {row.context_invalid && (
        <p
          role="status"
          className="border-t px-4 py-2 text-xs text-muted-foreground"
        >
          {t("dsh.modelAuditView.invalidContext")}
        </p>
      )}
      {expanded && (
        <div
          id={bodyId}
          className="border-t"
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            onToggle();
            originalButton.current?.focus();
          }}
        >
          <ModelAuditBody requestId={row.request_id} tenantId={tenantId} />
        </div>
      )}
      <footer className="border-t bg-muted/30 px-4 py-2">
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <div className="flex flex-wrap items-center gap-2">
            <dt>{t("dsh.modelAuditView.summary_status")}</dt>
            <dd
              className={
                row.audit_status === "ABNORMAL"
                  ? row.status_reasons?.some((reason) =>
                      [
                        "model_result:FAILED",
                        "model_result:CANCELLED",
                        "response_result:ERROR",
                        "response_result:INTERRUPTED",
                        "CAPTURE_FAILED",
                      ].includes(reason),
                    )
                    ? "text-destructive"
                    : "text-status-yellow"
                  : row.audit_status === "NORMAL" && !row.status_pending
                    ? "text-success-foreground"
                    : "text-muted-foreground"
              }
            >
              {t(
                "dsh.modelAuditView.summary." +
                  (row.audit_status || "PREPARING"),
              )}
            </dd>
            {row.status_pending && (
              <span>{t("dsh.modelAuditView.status_pending")}</span>
            )}
            {!!row.status_reasons?.length && (
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
                aria-expanded={detailsOpen}
                aria-controls={detailsOpen ? detailsId : undefined}
                onClick={() => setDetailsOpen((old) => !old)}
              >
                {t(
                  "dsh.modelAuditView.reasons." +
                    row.status_reasons[0].replace(":", "_"),
                  {
                    defaultValue: t("dsh.modelAuditView.reasons.INVALID_STATE"),
                  },
                )}
                {row.status_reasons.length > 1
                  ? " · " +
                    t("dsh.modelAuditView.more_reasons", {
                      count: row.status_reasons.length - 1,
                    })
                  : ""}
              </Button>
            )}
          </div>
          <div className="tabular-nums">
            <dt className="sr-only">{t("dsh.modelAuditView.input")}</dt>
            <dd>
              {t("dsh.modelAuditView.size", {
                count: row.input_units,
                bytes: row.input_bytes + row.output_bytes,
              })}
            </dd>
          </div>
          <div className="flex gap-1 tabular-nums">
            <dt>{t("dsh.modelAuditView.tokens")}:</dt>
            <dd className="font-medium text-foreground">
              {row.usage?.total_tokens ?? t("dsh.modelAuditView.unknown")}
            </dd>
          </div>
        </dl>
      </footer>
    </article>
  );
}
