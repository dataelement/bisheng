import { Button } from "@bisheng/ui";
import "@/style/dsh-content-safety.css";
import { Button as SafetyButton, Tag } from "@bisheng/ui";
import type { ModelAuditRecord } from "@/types/dshModelAudit";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dshTime } from "./common";
import { auditFailure } from "./auditFailures";
import { ModelAuditBody } from "./ModelAuditBody";
import { ContentSafetyDetails, safetyTagColor } from "./ContentSafetyDetails";

interface ModelAuditCardProps {
  row: ModelAuditRecord;
  tenantId?: number;
  expanded: boolean;
  onToggle: () => void;
}

const statusAxes = ["model_result", "response_result", "usage_settlement", "content_status"] as const;

function statusColor(value: string) {
  if (["FAILED", "ERROR", "INTERRUPTED"].includes(value)) return "text-destructive";
  if (["SUCCEEDED", "COMPLETED", "SETTLED", "COMPLETE"].includes(value)) return "text-success-foreground";
  if (["PARTIAL", "UNCERTAIN", "USAGE_UNKNOWN", "UNKNOWN"].includes(value))
    return "font-medium text-foreground";
  if (["RUNNING", "PENDING"].includes(value)) return "text-primary dark:text-foreground";
  return "text-muted-foreground";
}

export function ModelAuditCard({ row, tenantId, expanded, onToggle }: ModelAuditCardProps) {
  const { t } = useTranslation();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [safetyOpen, setSafetyOpen] = useState(false);
  const safetyId = useId();
  const external = row.record_origin === "EXTERNAL_SAFETY";
  const modelDisplay = row.model_name?.trim()
    ? row.model_name
    : `${t("dsh.auditHistory.fields.model_id")}: ${row.model_id}`;
  const canShowOriginal = !external && row.model_entered !== false;
  const safetyStates = {
    summary: row.content_safety_state ?? "UNREPORTED",
    input: row.stage_results?.input ?? "UNREPORTED",
    output: row.stage_results?.output ?? "UNREPORTED",
  } as const;
  const canShowSafetyDetails =
    row.has_sensitive_hit === true ||
    row.input_sensitive_hit === true ||
    row.output_sensitive_hit === true ||
    safetyStates.summary !== "PASSED" ||
    safetyStates.input !== "PASSED" ||
    safetyStates.output !== "PASSED";
  const detailsId = useId();
  const bodyId = useId();
  const originalButton = useRef<HTMLButtonElement>(null);
  // Contain absolute screen-reader labels so they cannot expand the document scroll area.
  return (
    <article className="relative min-w-0 overflow-hidden rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
        <p
          className="w-full min-w-0 truncate font-medium text-foreground md:w-auto md:flex-1"
          title={modelDisplay}
        >
          {modelDisplay}
        </p>
        <time className="whitespace-nowrap tabular-nums" dateTime={row.started_at}>
          {dshTime(row.started_at)}
        </time>
        <span className="max-w-48 truncate" title={row.user_name || undefined}>
          {row.user_name || t("dsh.modelAuditView.user_unavailable")}
        </span>
        <span className="whitespace-nowrap font-medium text-primary dark:text-foreground">
          {t("dsh.modelAuditView.kinds." + (row.request_kind || "unknown"))}
        </span>
        <span className="whitespace-nowrap">
          {t("dsh.modelAuditView.sources.origin." + (row.session_origin || "unknown"))}
        </span>
        <Button
          variant="link"
          color="default"
          className="h-7 p-0 text-xs dark:text-foreground [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
          aria-expanded={detailsOpen}
          aria-controls={detailsOpen ? detailsId : undefined}
          onClick={() => setDetailsOpen((old) => !old)}
        >
          {t("dsh.modelAuditView.request_details")}
        </Button>
        {canShowOriginal && (
        <Button
          ref={originalButton}
          variant="outlined"
          color="default"
          size="small"
          className="text-xs [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
          aria-expanded={expanded}
          aria-controls={expanded ? bodyId : undefined}
          disabled={row.content_status === "NOT_CAPTURED" || row.effective_mode !== "CONTENT"}
          onClick={onToggle}
        >
          {t(expanded ? "dsh.modelAuditView.collapse" : "dsh.modelAuditView.original")}
        </Button>
        )}
      </header>
      <div className="dsh-content-safety">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2">
          {(["summary", "input", "output"] as const).map((stage) => (
            <Tag key={stage} size="small" color={safetyTagColor(safetyStates[stage])}>
              {t("dsh.contentSafety.details." + stage) +
                ": " +
                t("dsh.contentSafety.states." + safetyStates[stage])}
            </Tag>
          ))}
          {canShowSafetyDetails && (
            <SafetyButton
              type="button"
              variant="text"
              size="small"
              className="text-xs [@media(pointer:coarse)]:min-h-11"
              aria-expanded={safetyOpen}
              aria-controls={safetyOpen ? safetyId : undefined}
              onClick={() => setSafetyOpen((old) => !old)}
            >
              {t("dsh.contentSafety.actions.view_details")}
            </SafetyButton>
          )}
        </div>
      </div>
      {canShowSafetyDetails && safetyOpen && (
        <div id={safetyId}>
          <ContentSafetyDetails
            requestId={row.request_id}
            tenantId={tenantId}
            detailsStatus={row.details_status}
          />
        </div>
      )}
      {detailsOpen && (
        <section
          id={detailsId}
          aria-labelledby={detailsId + "-title"}
          className="dsh-content-safety space-y-3 border-t p-4"
        >
          <h3 id={detailsId + "-title"} className="text-sm font-medium">
            {t("dsh.modelAuditView.request_details")}
          </h3>
          <dl className="grid min-w-0 gap-4 rounded-lg border p-3 text-xs sm:grid-cols-2">
            {statusAxes.map((key) => {
              let statusKey = "dsh.modelAuditView.states." + (row[key] ?? "UNKNOWN");
              if (row[key] == null && external) {
                if (key === "model_result") {
                  statusKey =
                    "dsh.contentSafety.model_entry." +
                    (row.model_entered === false ? "NOT_ENTERED" : "UNOBSERVED");
                } else if (row.model_entered === false) {
                  statusKey = "dsh.contentSafety.model_entry.NOT_APPLICABLE";
                }
              }
              return (
                <div key={key} className="min-w-0 space-y-1">
                  <dt className="text-muted-foreground">{t("dsh.modelAuditView.axes." + key)}</dt>
                  <dd className={"break-all " + statusColor(row[key] ?? "UNKNOWN")}>{t(statusKey)}</dd>
                </div>
              );
            })}
            {(
              [
                [
                  "model",
                  row.model_error_code,
                  ["FAILED", "CANCELLED", "UNKNOWN"].includes(row.model_result ?? ""),
                ],
                [
                  "response",
                  row.response_error_code,
                  ["ERROR", "INTERRUPTED", "UNKNOWN"].includes(row.response_result ?? ""),
                ],
              ] as const
            ).map(([axis, code, failed]) => {
              if (!failed) return null;
              const reason = auditFailure(code, axis);
              return (
                <div key={axis} className="flex gap-2">
                  <dt className="shrink-0">{t("dsh.modelAuditView.failures." + axis)}</dt>
                  <dd className="min-w-0 break-all">
                    {t("dsh.modelAuditView.failures." + reason.key)}
                    {reason.status && (
                      <span className="whitespace-nowrap">
                        {" · " +
                          t("dsh.modelAuditView.failures.http_status", {
                            status: reason.status,
                          })}
                      </span>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
          {(row.status_reasons || []).map((reason) => (
            <p key={reason} className="text-xs text-muted-foreground">
              {t("dsh.modelAuditView.reasons." + reason.replace(":", "_"), {
                defaultValue: t("dsh.modelAuditView.reasons.INVALID_STATE"),
              })}
            </p>
          ))}
        </section>
      )}
      {row.context_invalid && (
        <p role="status" className="border-t px-4 py-2 text-xs text-muted-foreground">
          {t("dsh.modelAuditView.invalidContext")}
        </p>
      )}
      {expanded && canShowOriginal && (
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
                row.audit_status === "NOT_APPLICABLE"
                  ? "dsh.contentSafety.model_entry.NOT_APPLICABLE"
                  : "dsh.modelAuditView.summary." + (row.audit_status || "PREPARING"),
              )}
            </dd>
            {row.status_pending && <span>{t("dsh.modelAuditView.status_pending")}</span>}
            {!!row.status_reasons?.length && (
              <Button
                type="button"
                variant="link"
                color="default"
                size="small"
                className="h-auto p-0 text-xs [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-sm"
                aria-expanded={detailsOpen}
                aria-controls={detailsOpen ? detailsId : undefined}
                onClick={() => setDetailsOpen((old) => !old)}
              >
                {t("dsh.modelAuditView.reasons." + row.status_reasons[0].replace(":", "_"), {
                  defaultValue: t("dsh.modelAuditView.reasons.INVALID_STATE"),
                })}
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
