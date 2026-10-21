import { type ApprovalInstanceDetail } from "@/controllers/API/approval";
import { Tag, type TagColor } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { formatDateTime } from "./approvalMetadata";

const NODE_BADGE_COLOR: Record<string, TagColor> = {
  approved: "success",
  rejected: "danger",
  pending: "approving",
  skipped: "default",
  cancelled: "default",
};

export function taskIcon(status: string): { icon: string; cls: string } {
  if (status === "approved") return { icon: "✓", cls: "text-green-600" };
  if (status === "rejected") return { icon: "✗", cls: "text-red-500" };
  if (status === "skipped" || status === "cancelled") return { icon: "⊘", cls: "text-muted-foreground" };
  return { icon: "●", cls: "text-blue-500" };
}

interface ApprovalTimelineProps {
  detail: ApprovalInstanceDetail;
}

export function ApprovalTimeline({ detail }: ApprovalTimelineProps) {
  const { t } = useTranslation("bs");
  const nodeBadgeText: Record<string, string> = {
    approved: t("approvalPage.timeline_statusApproved"),
    rejected: t("approvalPage.timeline_statusRejected"),
    pending: t("approvalPage.timeline_statusPending"),
    skipped: t("approvalPage.timeline_statusSkipped"),
    cancelled: t("approvalPage.timeline_statusCancelled"),
  };
  type TimelineNode = NonNullable<ApprovalInstanceDetail["flow_nodes"]>[number] &
    NonNullable<ApprovalInstanceDetail["tasks"]>[number];
  const nodes: TimelineNode[] =
    detail.flow_nodes && detail.flow_nodes.length > 0
      ? [...detail.flow_nodes].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0))
      : [...(detail.tasks || [])].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0));

  const submitLogs = (detail.action_logs || []).filter((l) => l.action === "submitted" || l.action === "resubmitted");
  const trailingLogs = (detail.action_logs || []).filter(
    (l) => !["submitted", "resubmitted", "skip_node", "approved", "rejected"].includes(l.action ?? ""),
  );
  const hasTrailingLogs = trailingLogs.length > 0;

  const totalSteps = submitLogs.length + nodes.length + trailingLogs.length;
  let stepIdx = 0;

  const renderConnector = (isLast: boolean) =>
    !isLast ? <span className="mt-1 w-px flex-1 bg-border min-h-[12px]" /> : null;

  return (
    <div className="mt-4 rounded-lg border border-border bg-gray-50 dark:bg-gray-50/[0.06] px-4 py-3 space-y-0">
      <div className="mb-2 text-xs font-semibold text-muted-foreground">{t("approvalPage.timeline_title")}</div>

      {/* submit / resubmit logs */}
      {submitLogs.map((log, i) => {
        stepIdx++;
        const isLast = stepIdx === totalSteps;
        const isSubmit = log.action === "submitted";
        return (
          <div key={log.id ?? `s${i}`} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-500 text-[10px] text-white">
                ●
              </span>
              {renderConnector(isLast)}
            </div>
            <div className={`min-w-0 pt-0.5 ${isLast ? "pb-1" : "pb-3"}`}>
              <div className="text-xs font-medium text-foreground">
                {isSubmit ? t("approvalPage.timeline_submitApply") : t("approvalPage.timeline_resubmit")}
              </div>
              {log.operator_user_name && (
                <div className="text-[11px] text-muted-foreground">{log.operator_user_name}</div>
              )}
              {log.create_time && (
                <div className="text-[11px] text-muted-foreground/70">{formatDateTime(log.create_time)}</div>
              )}
            </div>
          </div>
        );
      })}

      {/* flow nodes */}
      {nodes.map((node, i) => {
        stepIdx++;
        const matchedTasks = (detail.tasks || []).filter(
          (t) => t.node_order === node.node_order || t.node_name === node.node_name,
        );
        const isNotStarted = matchedTasks.length === 0 && !node.task_id;
        const aggStatus =
          matchedTasks.length === 0
            ? node.task_id
              ? (node.status ?? "pending")
              : "not_started"
            : matchedTasks.some((t) => t.status === "rejected")
              ? "rejected"
              : matchedTasks.some((t) => t.status === "approved")
                ? "approved"
                : matchedTasks.some((t) => t.status === "pending")
                  ? "pending"
                  : matchedTasks.some((t) => t.status === "skipped")
                    ? "skipped"
                    : (matchedTasks[0]?.status ?? "pending");
        const s = aggStatus.toLowerCase();
        const dotColor = isNotStarted
          ? "bg-muted-foreground/40"
          : s === "approved"
            ? "bg-green-500"
            : s === "rejected"
              ? "bg-red-500"
              : s === "cancelled" || s === "skipped"
                ? "bg-muted-foreground"
                : "bg-blue-500";
        const isLast =
          stepIdx === totalSteps - (hasTrailingLogs ? trailingLogs.length : 0) &&
          i === nodes.length - 1 &&
          !hasTrailingLogs;
        const badgeColor = NODE_BADGE_COLOR[s];
        const badgeText = nodeBadgeText[s];

        return (
          <div key={node.node_code ?? node.task_id ?? i} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dotColor}`} />
              {renderConnector(isLast)}
            </div>
            <div className={`min-w-0 flex-1 pt-0.5 ${isLast ? "pb-1" : "pb-3"}`}>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className={`text-xs font-medium ${isNotStarted ? "text-muted-foreground" : "text-foreground"}`}>
                  {node.node_name || "--"}
                </span>
                {!isNotStarted && badgeColor && badgeText && (
                  <Tag size="small" color={badgeColor} className="shrink-0 whitespace-nowrap">
                    {badgeText}
                  </Tag>
                )}
              </div>
              {isNotStarted && (
                <div className="text-[11px] text-muted-foreground">{t("approvalPage.timeline_notArrived")}</div>
              )}
              {matchedTasks.length > 0 && (
                <div className="mt-1.5 space-y-1">
                  {matchedTasks.map((task) => {
                    const ts = String(task.status || "").toLowerCase();
                    const { icon, cls } = taskIcon(ts);
                    const tLabel = nodeBadgeText[ts] ?? ts;
                    return (
                      <div key={task.task_id ?? task.id} className="rounded border border-border bg-card px-2.5 py-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1">
                            <span className={`text-[11px] font-bold ${cls}`}>{icon}</span>
                            {task.approver_user_name && (
                              <span className="text-xs text-foreground">{task.approver_user_name}</span>
                            )}
                            <span className="text-[11px] text-muted-foreground">{tLabel}</span>
                          </div>
                          {task.update_time && ts !== "pending" && (
                            <span className="shrink-0 text-[10px] text-muted-foreground/70">
                              {formatDateTime(task.update_time)}
                            </span>
                          )}
                        </div>
                        {task.comment && (
                          <div className="mt-1 rounded bg-gray-100 px-2 py-1 text-[11px] text-muted-foreground break-all dark:bg-gray-50/10">
                            {task.comment}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* trailing action logs (withdrawn, cancelled, etc.) */}
      {trailingLogs.map((log, i) => {
        stepIdx++;
        const isLast = stepIdx === totalSteps;
        const a = String(log.action || "").toLowerCase();
        const dotCls = a === "approved" ? "bg-green-500" : a === "rejected" ? "bg-red-500" : "bg-muted-foreground";
        const titleMap: Record<string, string> = {
          withdrawn: t("approvalPage.timeline_actionWithdrawn"),
          cancelled: t("approvalPage.timeline_actionCancelled"),
          revoked: t("approvalPage.timeline_actionRevoked"),
          assign_approvers: t("approvalPage.timeline_actionAssignApprovers"),
          assign_flow: t("approvalPage.timeline_actionAssignFlow"),
          retry_execute_failed: t("approvalPage.timeline_actionRetryExecuteFailed"),
          mark_manually_completed: t("approvalPage.timeline_actionMarkManuallyCompleted"),
        };
        const title = titleMap[a] ?? log.action ?? "--";
        return (
          <div key={log.id ?? `l${i}`} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] text-white ${dotCls}`}
              >
                ●
              </span>
              {renderConnector(isLast)}
            </div>
            <div className={`min-w-0 pt-0.5 ${isLast ? "pb-1" : "pb-3"}`}>
              <div className="text-xs font-medium text-foreground">{title}</div>
              {log.operator_user_name && (
                <div className="text-[11px] text-muted-foreground">{log.operator_user_name}</div>
              )}
              {log.detail?.comment && (
                <div className="mt-1 rounded bg-gray-100 px-2 py-1 text-[11px] text-muted-foreground break-all dark:bg-gray-50/10">
                  {log.detail.comment}
                </div>
              )}
              {log.create_time && (
                <div className="text-[11px] text-muted-foreground/70">{formatDateTime(log.create_time)}</div>
              )}
            </div>
          </div>
        );
      })}

      {nodes.length === 0 && submitLogs.length === 0 && (
        <div className="text-xs text-muted-foreground py-2">{t("approvalPage.timeline_empty")}</div>
      )}
    </div>
  );
}
