import { Outlined } from "bisheng-icons";
import type { ApprovalInstanceDetail, ApprovalTaskDetail } from "~/api/approval";
import { useLocalize } from "~/hooks";
import { type TranslationKeys } from "~/hooks/useLocalize";
import { cn } from "~/utils";
import {
  DETAIL_INTERNAL_KEYS,
  InfoGrid,
  StatusBadge,
  TimelineStep,
  formatSerialNo,
  formatTime,
  formatTitle,
  localizeFieldKey,
} from "./approvalPresentation";

/**
 * One row of the progress timeline. Nodes come either from the flow definition
 * (`flow_nodes`, including nodes not reached yet) or, as a fallback, from the created tasks.
 */
type TimelineNode = {
  node_order?: number | null;
  node_name?: string | null;
  node_code?: string | null;
  task_id?: number | null;
  status?: string | null;
};

export function DetailHeader({ title, status, instanceStatus, scope, serialNo, scenarioName, createTime, localize, onBack }: {
  title?: string; status?: string; instanceStatus?: string; scope: "task" | "instance"; serialNo: string; scenarioName?: string; createTime?: string | null; localize: ReturnType<typeof useLocalize>; onBack?: () => void;
}) {
  return (
    // Pinned to the top of the scrolling detail pane so the title/status/serial stay visible while the body scrolls.
    <div className="sticky top-0 z-10 -mx-5 mb-5 border-b border-fill-2 bg-white px-5 pb-3 pt-4">
      <div className="flex items-start gap-3">
        {/* Compact-only back control — sits to the left of the detail title, split by a short vertical divider.
            h-8 matches the title line so the arrow centers against it under items-start. */}
        {onBack && (
          <div className="flex h-8 shrink-0 items-center gap-3 md:hidden">
            <button type="button" onClick={onBack} aria-label={localize("com_approval_back")} className="flex items-center text-text-3">
              <Outlined.ArrowLeft className="h-4 w-4" />
            </button>
            <span className="h-4 w-px bg-fill-3" />
          </div>
        )}
        {/* Title + serial share one column so the serial line aligns with the title, not the back arrow. */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            {/* Same line box as the list column's section heading (text-base/leading-8 at pt-4),
                so both titles sit on one line across the two columns. */}
            <h3 className="min-w-0 flex-1 text-base font-semibold leading-8 text-text-primary">{title || "--"}</h3>
            <StatusBadge status={status} instanceStatus={instanceStatus} scope={scope} localize={localize} />
          </div>
          <p className="mt-1.5 text-[13px] text-text-3">
            {serialNo} · {scenarioName || "--"} · {formatTime(createTime)}
          </p>
        </div>
      </div>
    </div>
  );
}

export function TaskDetailPanel({ detail, localize, onBack }: { detail: ApprovalTaskDetail; localize: ReturnType<typeof useLocalize>; onBack?: () => void }) {
  const instanceId = detail.instance_id;
  const serialNo = instanceId ? formatSerialNo(instanceId, detail.create_time) : "--";

  const basicRows: [string, string][] = [
    [localize("com_approval_field_serial_no"),      serialNo],
    [localize("com_approval_field_scenario_type"),  detail.scenario_name || detail.scenario_code || "--"],
    [localize("com_approval_field_business_target"),detail.business_name || "--"],
    [localize("com_approval_field_applicant"),       detail.applicant_user_name || "--"],
    [localize("com_approval_field_department"),      detail.applicant_department_name || "--"],
    [localize("com_approval_field_apply_time"),      formatTime(detail.create_time)],
    [localize("com_approval_status_label").replace("：", ""), localize(`com_approval_status_${detail.instance_status ?? detail.status}` as TranslationKeys, { defaultValue: detail.instance_status || detail.status || "--" }) as string],
  ];

  const detailEntries = Object.entries(detail.detail_snapshot ?? detail.payload_snapshot ?? {}).filter(
    ([k, v]) => !DETAIL_INTERNAL_KEYS.has(k) && v !== undefined && v !== null && v !== "",
  );
  const showContent = detailEntries.length > 0;

  return (
    <div className="space-y-5">
      <DetailHeader title={formatTitle(detail.scenario_code, detail.business_name, localize)} status={detail.status} instanceStatus={detail.instance_status} scope="task"
        serialNo={serialNo} scenarioName={detail.scenario_name || detail.scenario_code} createTime={detail.create_time} localize={localize} onBack={onBack} />

      <div>
        <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_basic_info")}</div>
        <InfoGrid rows={basicRows} />
      </div>

      {showContent && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_business_content")}</div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-fill-2 bg-fill-2">
            {detailEntries.map(([k, v]) => (
              <div key={k} className="bg-white px-3 py-2">
                <div className="text-[12px] text-text-3">{localizeFieldKey(k, localize)}</div>
                <div className="mt-1 text-[14px] text-text-primary break-all">{Array.isArray(v) ? v.join(", ") : String(v)}</div>
              </div>
            ))}
            {detailEntries.length % 2 === 1 && <div className="-ml-px bg-white" />}
          </div>
        </div>
      )}

      {detail.reason && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_apply_reason")}</div>
          <div className="rounded-lg bg-[#fafbfc] p-4 text-[14px] text-text-2 break-all">{detail.reason}</div>
        </div>
      )}

      {((detail.action_logs && detail.action_logs.length > 0) || (detail.tasks && detail.tasks.length > 0) || detail.current_node_name) ? (
        <div>
          <div className="mb-3 text-[14px] font-medium text-text-primary">
            {localize("com_approval_progress_section")}
          </div>
          {/* submitted / resubmitted logs first */}
          {(detail.action_logs || [])
            .filter((l) => l.action === "submitted" || l.action === "resubmitted")
            .map((log, i) => (
              <TimelineStep key={log.id ?? `s${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={false} />
            ))}
          {/* all flow nodes — use flow_nodes as skeleton; fall back to tasks */}
          {(() => {
            const nodes = detail.flow_nodes && detail.flow_nodes.length > 0
              ? [...detail.flow_nodes].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0))
              : [...(detail.tasks || [])].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0));
            const hasTrailingLogs = (detail.action_logs || []).some(
              (l) => l.action !== "submitted" && l.action !== "resubmitted" && l.action !== "skip_node"
            );
            return nodes.map((node: TimelineNode, i) => {
              const matchedTasks = (detail.tasks || []).filter(
                (t) => t.node_order === node.node_order || t.node_name === node.node_name
              );
              const isNotStarted = matchedTasks.length === 0 && !node.task_id;
              const aggStatus = matchedTasks.length === 0
                ? (node.task_id ? (node.status ?? "pending") : "not_started")
                : matchedTasks.some((t) => t.status === "rejected") ? "rejected"
                : matchedTasks.some((t) => t.status === "approved") ? "approved"
                : matchedTasks.some((t) => t.status === "pending") ? "pending"
                : matchedTasks.some((t) => t.status === "skipped") ? "skipped"
                : (matchedTasks[0]?.status ?? "pending");
              const s = aggStatus.toLowerCase();
              const dotColor = isNotStarted ? "bg-fill-3" :
                s === "approved" ? "bg-[#00b42a]" : s === "rejected" ? "bg-[#f53f3f]" :
                (s === "cancelled" || s === "skipped") ? "bg-fill-4" : "bg-blue-500";
              const isLast = i === nodes.length - 1 && !hasTrailingLogs;
              const nodeBadgeMap: Record<string, { text: string; cls: string }> = {
                approved:  { text: localize("com_approval_status_approved"),  cls: "bg-[#e8ffea] text-[#00b42a]" },
                rejected:  { text: localize("com_approval_status_rejected"),  cls: "bg-[#fff2f0] text-[#f53f3f]" },
                pending:   { text: localize("com_approval_status_pending"),   cls: "bg-[#e8f3ff] text-[#165dff]" },
                skipped:   { text: localize("com_approval_status_skipped"),   cls: "bg-fill-1 text-text-3" },
                cancelled: { text: localize("com_approval_status_cancelled"), cls: "bg-fill-1 text-text-3" },
              };
              return (
                <div key={node.node_code ?? node.task_id ?? i} className="flex gap-3">
                  <div className="flex w-6 flex-col items-center">
                    <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", dotColor)} />
                    {!isLast && <span className="mt-1 w-px flex-1 bg-fill-3" />}
                  </div>
                  <div className={cn("min-w-0 flex-1", isLast ? "pb-1" : "pb-4")}>
                    <div className="flex items-center gap-2">
                      <span className={cn("text-[14px] font-medium", isNotStarted ? "text-text-3" : "text-text-primary")}>
                        {node.node_name || "--"}
                      </span>
                      {!isNotStarted && nodeBadgeMap[s] && (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", nodeBadgeMap[s].cls)}>
                          {nodeBadgeMap[s].text}
                        </span>
                      )}
                    </div>
                    {matchedTasks.length > 0 && (
                      <div className="mt-2 space-y-1.5">
                        {matchedTasks.map((t) => {
                          const ts = String(t.status || "").toLowerCase();
                          const tLabel = ts === "approved" ? localize("com_approval_status_approved") :
                            ts === "rejected" ? localize("com_approval_status_rejected") :
                            ts === "pending" ? localize("com_approval_status_pending") :
                            ts === "skipped" ? localize("com_approval_status_skipped") :
                            ts === "cancelled" ? localize("com_approval_status_cancelled") :
                            localize("com_approval_node_not_started");
                          const tIconCls = ts === "approved" ? "text-[#00b42a]" : ts === "rejected" ? "text-[#f53f3f]" :
                            (ts === "skipped" || ts === "cancelled") ? "text-text-4" : "text-blue-500";
                          const tIcon = ts === "approved" ? "✓" : ts === "rejected" ? "✗" :
                            (ts === "skipped" || ts === "cancelled") ? "⊘" : "●";
                          return (
                            <div key={t.task_id ?? t.id} className="rounded-lg border border-fill-2 bg-[#fafbfc] px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5">
                                  <span className={cn("text-[12px] font-bold", tIconCls)}>{tIcon}</span>
                                  {t.approver_user_name && (
                                    <span className="text-[13px] text-text-primary">{t.approver_user_name}</span>
                                  )}
                                  <span className="text-[12px] text-text-3">{tLabel}</span>
                                </div>
                                {t.update_time && ts !== "pending" && (
                                  <span className="shrink-0 text-[11px] text-text-4">{formatTime(t.update_time)}</span>
                                )}
                              </div>
                              {t.comment && (
                                <div className="mt-1.5 rounded-lg bg-[#f0f1f3] px-3 py-1.5 text-[12px] text-text-2 break-all">
                                  {t.comment}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {isNotStarted && (
                      <div className="mt-0.5 text-[12px] text-text-3">{localize("com_approval_node_not_started")}</div>
                    )}
                  </div>
                </div>
              );
            });
          })()}
          {/* other action logs — skip_node/approved/rejected are shown on the node itself */}
          {(detail.action_logs || [])
            .filter((l) => !["submitted", "resubmitted", "skip_node", "approved", "rejected"].includes(l.action ?? ""))
            .map((log, i, arr) => (
              <TimelineStep key={log.id ?? `l${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={i === arr.length - 1} />
            ))}
        </div>
      ) : null}
    </div>
  );
}

export function RequestDetailPanel({ detail, localize, onBack }: { detail: ApprovalInstanceDetail; localize: ReturnType<typeof useLocalize>; onBack?: () => void }) {
  const id = detail.instance_id ?? detail.id;
  const serialNo = id ? formatSerialNo(Number(id), detail.create_time) : "--";

  const isTerminal = ["executed", "rejected", "withdrawn", "cancelled"].includes(detail.status ?? "");
  const basicRows: [string, string][] = [
    [localize("com_approval_field_serial_no"),      serialNo],
    [localize("com_approval_field_scenario_type"),  detail.scenario_name || detail.scenario_code || "--"],
    [localize("com_approval_field_business_target"),detail.business_name || "--"],
    [localize("com_approval_field_applicant"),       detail.applicant_user_name || "--"],
    [localize("com_approval_field_department"),      detail.applicant_department_name || "--"],
    [localize("com_approval_field_apply_time"),      formatTime(detail.create_time)],
    ...(!isTerminal ? [[localize("com_approval_field_current_approver"), detail.current_approver_names || "--"] as [string, string]] : []),
    [localize("com_approval_status_label").replace("：", ""), localize(`com_approval_status_${detail.status}` as TranslationKeys, { defaultValue: detail.status ?? "--" }) as string],
  ];

  const detailEntries = Object.entries(detail.detail_snapshot ?? {}).filter(
    ([k, v]) => !DETAIL_INTERNAL_KEYS.has(k) && k !== "reason" && v !== undefined && v !== null && v !== "",
  );

  return (
    <div className="space-y-5">
      <DetailHeader title={formatTitle(detail.scenario_code, detail.business_name, localize)} status={detail.status} scope="instance" serialNo={serialNo}
        scenarioName={detail.scenario_name || detail.scenario_code} createTime={detail.create_time} localize={localize} onBack={onBack} />

      <div>
        <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_basic_info")}</div>
        <InfoGrid rows={basicRows} />
      </div>

      {detailEntries.length > 0 && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_business_content")}</div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-fill-2 bg-fill-2">
            {detailEntries.map(([k, v]) => (
              <div key={k} className="bg-white px-3 py-2">
                <div className="text-[12px] text-text-3">{localizeFieldKey(k, localize)}</div>
                <div className="mt-1 text-[14px] text-text-primary break-all">{Array.isArray(v) ? v.join(", ") : String(v)}</div>
              </div>
            ))}
            {detailEntries.length % 2 === 1 && <div className="-ml-px bg-white" />}
          </div>
        </div>
      )}

      {detail.reason && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-text-primary">{localize("com_approval_section_apply_reason")}</div>
          <div className="rounded-lg bg-[#fafbfc] p-4 text-[14px] text-text-2 break-all">{detail.reason}</div>
        </div>
      )}

      {((detail.action_logs && detail.action_logs.length > 0) || (detail.tasks && detail.tasks.length > 0)) && (
        <div>
          <div className="mb-3 text-[14px] font-medium text-text-primary">
            {localize("com_approval_progress_section")}
          </div>
          {/* submitted / resubmitted logs first */}
          {(detail.action_logs || [])
            .filter((l) => l.action === "submitted" || l.action === "resubmitted")
            .map((log, i) => (
              <TimelineStep key={log.id ?? `s${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={false} />
            ))}
          {/* all flow nodes — use flow_nodes as skeleton; fall back to tasks */}
          {(() => {
            const nodes = detail.flow_nodes && detail.flow_nodes.length > 0
              ? [...detail.flow_nodes].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0))
              : [...(detail.tasks || [])].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0));
            const hasTrailingLogs = (detail.action_logs || []).some(
              (l) => l.action !== "submitted" && l.action !== "resubmitted"
            );
            return nodes.map((node: TimelineNode, i) => {
              // Collect all tasks for this node (multi-approver nodes have multiple tasks)
              const matchedTasks = (detail.tasks || []).filter(
                (t) => t.node_order === node.node_order || t.node_name === node.node_name
              );
              const isNotStarted = matchedTasks.length === 0 && !node.task_id;
              // Aggregate node status: rejected > approved > pending > others
              const aggStatus = matchedTasks.length === 0
                ? (node.task_id ? (node.status ?? "pending") : "not_started")
                : matchedTasks.some((t) => t.status === "rejected") ? "rejected"
                : matchedTasks.some((t) => t.status === "approved") ? "approved"
                : matchedTasks.some((t) => t.status === "pending") ? "pending"
                : (matchedTasks[0]?.status ?? "pending");
              const s = aggStatus.toLowerCase();
              const dotColor = isNotStarted ? "bg-fill-3" :
                s === "approved" ? "bg-[#00b42a]" : s === "rejected" ? "bg-[#f53f3f]" :
                (s === "cancelled" || s === "skipped") ? "bg-fill-4" : "bg-blue-500";
              const isLast = i === nodes.length - 1 && !hasTrailingLogs;
              const nodeBadgeMap: Record<string, { text: string; cls: string }> = {
                approved:  { text: localize("com_approval_status_approved"),  cls: "bg-[#e8ffea] text-[#00b42a]" },
                rejected:  { text: localize("com_approval_status_rejected"),  cls: "bg-[#fff2f0] text-[#f53f3f]" },
                pending:   { text: localize("com_approval_status_pending"),   cls: "bg-[#e8f3ff] text-[#165dff]" },
                skipped:   { text: localize("com_approval_status_skipped"),   cls: "bg-fill-1 text-text-3" },
                cancelled: { text: localize("com_approval_status_cancelled"), cls: "bg-fill-1 text-text-3" },
              };
              return (
                <div key={node.node_code ?? node.task_id ?? i} className="flex gap-3">
                  <div className="flex w-6 flex-col items-center">
                    <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", dotColor)} />
                    {!isLast && <span className="mt-1 w-px flex-1 bg-fill-3" />}
                  </div>
                  <div className={cn("min-w-0 flex-1", isLast ? "pb-1" : "pb-4")}>
                    {/* Node name + aggregate status badge */}
                    <div className="flex items-center gap-2">
                      <span className={cn("text-[14px] font-medium", isNotStarted ? "text-text-3" : "text-text-primary")}>
                        {node.node_name || "--"}
                      </span>
                      {!isNotStarted && nodeBadgeMap[s] && (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", nodeBadgeMap[s].cls)}>
                          {nodeBadgeMap[s].text}
                        </span>
                      )}
                    </div>
                    {/* Per-approver entries */}
                    {matchedTasks.length > 0 && (
                      <div className="mt-2 space-y-1.5">
                        {matchedTasks.map((t) => {
                          const ts = String(t.status || "").toLowerCase();
                          const tLabel = ts === "approved" ? localize("com_approval_status_approved") :
                            ts === "rejected" ? localize("com_approval_status_rejected") :
                            ts === "pending" ? localize("com_approval_status_pending") :
                            ts === "skipped" ? localize("com_approval_status_skipped") :
                            ts === "cancelled" ? localize("com_approval_status_cancelled") :
                            localize("com_approval_node_not_started");
                          const tIconCls = ts === "approved" ? "text-[#00b42a]" : ts === "rejected" ? "text-[#f53f3f]" :
                            (ts === "skipped" || ts === "cancelled") ? "text-text-4" : "text-blue-500";
                          const tIcon = ts === "approved" ? "✓" : ts === "rejected" ? "✗" :
                            (ts === "skipped" || ts === "cancelled") ? "⊘" : "●";
                          return (
                            <div key={t.task_id ?? t.id} className="rounded-lg border border-fill-2 bg-[#fafbfc] px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5">
                                  <span className={cn("text-[12px] font-bold", tIconCls)}>{tIcon}</span>
                                  {t.approver_user_name && (
                                    <span className="text-[13px] text-text-primary">{t.approver_user_name}</span>
                                  )}
                                  <span className="text-[12px] text-text-3">{tLabel}</span>
                                </div>
                                {t.update_time && ts !== "pending" && (
                                  <span className="shrink-0 text-[11px] text-text-4">{formatTime(t.update_time)}</span>
                                )}
                              </div>
                              {t.comment && (
                                <div className="mt-1.5 rounded-lg bg-[#f0f1f3] px-3 py-1.5 text-[12px] text-text-2 break-all">
                                  {t.comment}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {/* Not-started placeholder */}
                    {isNotStarted && (
                      <div className="mt-0.5 text-[12px] text-text-3">{localize("com_approval_node_not_started")}</div>
                    )}
                    {/* flow_nodes-only entry with no matched tasks */}
                    {!isNotStarted && matchedTasks.length === 0 && (
                      <div className="mt-0.5 text-[12px] text-text-3">{
                        s === "approved" ? localize("com_approval_status_approved") :
                        s === "rejected" ? localize("com_approval_status_rejected") :
                        s === "pending" ? localize("com_approval_status_pending") :
                        s === "skipped" ? localize("com_approval_status_skipped") :
                        localize("com_approval_status_cancelled")
                      }</div>
                    )}
                  </div>
                </div>
              );
            });
          })()}
          {/* other action logs (withdrawn, cancelled, etc.) — skip_node/approved/rejected are shown on the node itself */}
          {(detail.action_logs || [])
            .filter((l) => !["submitted", "resubmitted", "skip_node", "approved", "rejected"].includes(l.action ?? ""))
            .map((log, i, arr) => (
              <TimelineStep key={log.id ?? `l${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={i === arr.length - 1} />
            ))}
        </div>
      )}
    </div>
  );
}
