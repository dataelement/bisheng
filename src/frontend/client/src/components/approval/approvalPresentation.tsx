import { useLocalize } from "~/hooks";
import { type TranslationKeys } from "~/hooks/useLocalize";
import { cn } from "~/utils";

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

export function StatusBadge({ status, instanceStatus, scope, localize }: { status?: string | null; instanceStatus?: string | null; scope: "task" | "instance"; localize: ReturnType<typeof useLocalize> }) {
  const s = String(status || "").toLowerCase();
  const is = String(instanceStatus || "").toLowerCase();
  // Task scope: if my task is approved but instance execution failed, surface the failure.
  const effective = scope === "task" && s === "approved" && is === "execute_failed" ? "execute_failed" : s;
  const TASK_MAP: Record<string, { text: string; cls: string }> = {
    pending:        { text: localize("com_approval_task_badge_pending"),    cls: "bg-[#e8f3ff] text-[#165dff]" },
    approved:       { text: localize("com_approval_task_badge_approved"),   cls: "bg-[#e8ffea] text-[#00b42a]" },
    rejected:       { text: localize("com_approval_task_badge_rejected"),   cls: "bg-[#fff2f0] text-[#f53f3f]" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      cls: "bg-fill-1 text-text-3" },
    skipped:        { text: localize("com_approval_status_skipped"),        cls: "bg-fill-1 text-text-3" },
    execute_failed: { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    exception:      { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
  };
  const INSTANCE_MAP: Record<string, { text: string; cls: string }> = {
    pending:        { text: localize("com_approval_status_pending"),        cls: "bg-[#e8f3ff] text-[#165dff]" },
    approved:       { text: localize("com_approval_status_approved"),       cls: "bg-[#e8ffea] text-[#00b42a]" },
    executed:       { text: localize("com_approval_status_approved"),       cls: "bg-[#e8ffea] text-[#00b42a]" },
    rejected:       { text: localize("com_approval_status_rejected"),       cls: "bg-[#fff2f0] text-[#f53f3f]" },
    withdrawn:      { text: localize("com_approval_status_withdrawn"),      cls: "bg-fill-1 text-text-3" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      cls: "bg-fill-1 text-text-3" },
    skipped:        { text: localize("com_approval_status_skipped"),        cls: "bg-fill-1 text-text-3" },
    execute_failed: { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    exception:      { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
  };
  const MAP = scope === "instance" ? INSTANCE_MAP : TASK_MAP;
  const { text, cls } = MAP[effective] ?? MAP[s] ?? { text: status ?? "--", cls: "bg-fill-1 text-text-3" };
  return <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[12px] font-medium", cls)}>{text}</span>;
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

export const DETAIL_INTERNAL_KEYS = new Set(["menu_key", "space_id", "channel_id", "applicant_user_id", "applicant_user_name"]);

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
