import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useLocalize } from "~/hooks";
import { type TranslationKeys } from "~/hooks/useLocalize";
import { cn } from "~/utils";

/** `localize` is handed down as a prop so these stay pure presentational helpers. */
export type LocalizeFn = ReturnType<typeof useLocalize>;

export type TaskFilter = "pending_me" | "processed";
export type RequestsFilter = "in_progress" | "completed";
export const IN_PROGRESS_STATUSES = new Set(["pending", "exception", "execute_failed"]);

export function getId(item: { task_id?: number; id?: number; instance_id?: number } | null | undefined, type: "task" | "instance"): number | null {
  const raw = type === "task" ? (item?.task_id ?? item?.id) : (item?.instance_id ?? item?.id);
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function formatSerialNo(instanceId: number, ts?: string | null): string {
  const d = ts ? new Date(ts) : new Date();
  return `SP${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}${String(instanceId).padStart(4, "0")}`;
}

export function formatTime(ts?: string | Date | null): string {
  if (!ts) return "--";
  const d = new Date(ts as string);
  if (Number.isNaN(d.getTime())) return String(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Which semantic color an approval status speaks in (组件-Tag标签.md §3.1).
 * `pending` takes `approving`, the frozen blue exception (色彩规范 §4) — the
 * hand-rolled `#e8f3ff / #165dff` pill this replaced was that exact blue, and
 * the token is what keeps it blue when the product runs the green theme.
 */
export type ApprovalTone = "default" | "success" | "warning" | "danger" | "approving";

export function StatusBadge({ status, instanceStatus, scope, localize, size = "small" }: {
  status?: string | null;
  instanceStatus?: string | null;
  scope: "task" | "instance";
  localize: ReturnType<typeof useLocalize>;
  /** §4 — `medium` for the detail header, `small` everywhere it rides inside a row. */
  size?: "small" | "medium";
}) {
  // Every 审批 status tag carries the dot (designer's call, 2026-08-28) — the
  // list, the detail header and the progress nodes alike, so one status reads the
  // same wherever it appears. Hence no `dot` prop: it is not a per-call-site
  // choice.

  const s = String(status || "").toLowerCase();
  const is = String(instanceStatus || "").toLowerCase();
  // Task scope: if my task is approved but instance execution failed, surface the failure.
  const effective = scope === "task" && s === "approved" && is === "execute_failed" ? "execute_failed" : s;
  const TASK_MAP: Record<string, { text: string; tone: ApprovalTone }> = {
    pending:        { text: localize("com_approval_task_badge_pending"),    tone: "approving" },
    approved:       { text: localize("com_approval_task_badge_approved"),   tone: "success" },
    rejected:       { text: localize("com_approval_task_badge_rejected"),   tone: "danger" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      tone: "default" },
    skipped:        { text: localize("com_approval_status_skipped"),        tone: "default" },
    execute_failed: { text: localize("com_approval_badge_exception"),       tone: "warning" },
    exception:      { text: localize("com_approval_badge_exception"),       tone: "warning" },
  };
  const INSTANCE_MAP: Record<string, { text: string; tone: ApprovalTone }> = {
    pending:        { text: localize("com_approval_status_pending"),        tone: "approving" },
    approved:       { text: localize("com_approval_status_approved"),       tone: "success" },
    executed:       { text: localize("com_approval_status_approved"),       tone: "success" },
    rejected:       { text: localize("com_approval_status_rejected"),       tone: "danger" },
    withdrawn:      { text: localize("com_approval_status_withdrawn"),      tone: "default" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      tone: "default" },
    skipped:        { text: localize("com_approval_status_skipped"),        tone: "default" },
    execute_failed: { text: localize("com_approval_badge_exception"),       tone: "warning" },
    exception:      { text: localize("com_approval_badge_exception"),       tone: "warning" },
  };
  const MAP = scope === "instance" ? INSTANCE_MAP : TASK_MAP;
  const { text, tone } = MAP[effective] ?? MAP[s] ?? { text: status ?? "--", tone: "default" as ApprovalTone };
  return (
    <Tag size={size} dot color={tone} className="shrink-0 whitespace-nowrap">
      {text}
    </Tag>
  );
}

export function TimelineStep({ action, operatorName, createTime, detail, localize, isLast }: {
  action?: string; operatorName?: string | null; createTime?: string | null;
  detail?: Record<string, unknown> | null; localize: ReturnType<typeof useLocalize>; isLast?: boolean;
}) {
  const a = String(action || "").toLowerCase();
  // Match the flow-node markers: a plain 12px colored dot (color keyed on the action, not the
  // instance result — "submitted" stays blue because the submit action itself always succeeded).
  const dotCls = a === "approved" ? "bg-[#00b42a]" : a === "rejected" ? "bg-[#f53f3f]" :
    a === "withdrawn" ? "bg-[#86909c]" :
    a === "revoke_grant" ? "bg-[#ff7d00]" : "bg-blue-500";
  const title = a === "submitted" ? localize("com_approval_step_submitted") :
    a === "resubmitted" ? localize("com_approval_action_resubmitted") :
    a === "approved" ? localize("com_approval_action_approved") :
    a === "rejected" ? localize("com_approval_action_rejected") :
    a === "withdrawn" ? localize("com_approval_action_withdrawn") :
    a === "revoke_grant" ? localize("com_approval_action_revoke_grant_short") :
    (localize(`com_approval_action_${a}` as TranslationKeys, { defaultValue: a }) as string);
  const desc = a === "submitted" ? localize("com_approval_step_submitted_desc") : operatorName ?? null;
  const commentRaw = detail?.comment ?? detail?.reason;
  const comment = typeof commentRaw === "string" ? commentRaw : commentRaw ? String(commentRaw) : "";
  return (
    <div className="flex gap-3">
      <div className="flex w-6 flex-col items-center">
        <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", dotCls)} />
        {!isLast && <span className="mt-1 w-px flex-1 bg-fill-3" />}
      </div>
      <div className={cn("min-w-0 flex-1", isLast ? "pb-1" : "pb-4")}>
        <div className="text-[14px] font-medium text-text-primary">{title}</div>
        {desc && <div className="mt-0.5 text-[12px] text-text-3">{desc}</div>}
        {comment && <div className="mt-1 rounded-lg bg-fill-1 px-3 py-2 text-[12px] text-text-2 break-all">{comment}</div>}
        <div className="mt-1 text-[11px] text-text-4">{formatTime(createTime)}</div>
      </div>
    </div>
  );
}

export function formatTitle(
  scenarioCode: string | undefined,
  businessName: string | undefined | null,
  localize: ReturnType<typeof useLocalize>,
): string {
  if (!businessName) return "--";
  if (scenarioCode === "menu_access_request") {
    // The key always exists; fall back to the raw business name rather than a hardcoded sentence.
    return (localize("com_approval_menu_access_title" as TranslationKeys, {
      menuName: businessName,
      defaultValue: businessName,
    }) as string);
  }
  return businessName;
}

// Keys the generic two-column grid must never print: internal ids, plus the
// structured sub-trees the app-publish scenario ships (objects/arrays would
// render as "[object Object]" under their raw English key name). The dedicated
// AppPublishDetailPanel renders those; anything not dispatched just hides them.
export const DETAIL_INTERNAL_KEYS = new Set([
  "menu_key", "space_id", "channel_id", "applicant_user_id", "applicant_user_name",
  "scenario_code", "app_id", "owner_user_id", "version_id", "deployment_id", "tenant_id",
  "capabilities", "visibility_snapshot", "tier", "schema_change", "approver_note",
]);

export function localizeFieldKey(key: string, localize: ReturnType<typeof useLocalize>): string {
  const map: Record<string, string> = {
    menu_key:      localize("com_approval_field_menu_key" as TranslationKeys),
    menu_name:     localize("com_approval_field_menu_name" as TranslationKeys),
    reason:        localize("com_approval_field_reason" as TranslationKeys),
    space_type:    localize("com_approval_field_space_type" as TranslationKeys),
    space_name:    localize("com_approval_field_space_name" as TranslationKeys),
    channel_id:    localize("com_approval_field_channel_id" as TranslationKeys),
    channel_name:  localize("com_approval_field_channel_name" as TranslationKeys),
    space_id:      localize("com_approval_field_space_id" as TranslationKeys),
  };
  return map[key] ?? key;
}

export function InfoGrid({ rows }: { rows: [string, string][] }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-fill-2 bg-fill-2">
      {rows.map(([label, value]) => (
        <div key={label} className="bg-white px-3 py-2">
          <div className="text-[12px] text-text-3">{label}</div>
          <div className="mt-1 text-[14px] font-medium text-text-primary break-all">{value || "--"}</div>
        </div>
      ))}
      {/* Fill the trailing empty slot on an odd row count so it stays white, not the grid's gray gutter.
         -ml-px covers the 1px gap gutter on its left so no divider line shows beside the empty cell. */}
      {rows.length % 2 === 1 && <div className="-ml-px bg-white" />}
    </div>
  );
}

/**
 * Sticky title/status/serial strip shared by every detail panel. Lives here,
 * not in `ApprovalDetailPanels`, so a per-scenario panel (`AppPublishDetailPanel`)
 * can reuse it without importing the panels module that dispatches to it.
 */
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
            {/* §4 — one object's status, meant to be seen from across the page,
                so the medium rung; the dot comes from StatusBadge itself. */}
            <StatusBadge status={status} instanceStatus={instanceStatus} scope={scope} localize={localize} size="medium" />
          </div>
          <p className="mt-1.5 text-[13px] text-text-3">
            {serialNo} · {scenarioName || "--"} · {formatTime(createTime)}
          </p>
        </div>
      </div>
    </div>
  );
}
