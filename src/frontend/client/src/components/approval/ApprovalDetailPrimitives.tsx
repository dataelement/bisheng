import { Outlined } from "bisheng-icons";
// Type-only: keeps this module out of the ~/hooks barrel at runtime.
import type useLocalize from "~/hooks/useLocalize";
import { cn } from "~/utils";

/**
 * Presentational primitives shared by the approval detail panes.
 *
 * They live outside `ApprovalCenterDialog` so a per-scenario panel (e.g.
 * `AppPublishDetailPanel`) can reuse them without importing back into the
 * dialog, which would make the module graph circular.
 */

/** `localize` is handed down as a prop so these stay pure presentational helpers. */
export type LocalizeFn = ReturnType<typeof useLocalize>;

/** Human-facing request number: SP + submit date + zero-padded instance id. */
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

export interface StatusBadgeProps {
  status?: string | null;
  instanceStatus?: string | null;
  scope: "task" | "instance";
  localize: LocalizeFn;
}

export function StatusBadge({ status, instanceStatus, scope, localize }: StatusBadgeProps) {
  const s = String(status || "").toLowerCase();
  const is = String(instanceStatus || "").toLowerCase();
  // Task scope: if my task is approved but instance execution failed, surface the failure.
  const effective = scope === "task" && s === "approved" && is === "execute_failed" ? "execute_failed" : s;
  const TASK_MAP: Record<string, { text: string; cls: string }> = {
    pending:        { text: localize("com_approval_task_badge_pending"),    cls: "bg-[#e8f3ff] text-[#165dff]" },
    approved:       { text: localize("com_approval_task_badge_approved"),   cls: "bg-[#e8ffea] text-[#00b42a]" },
    rejected:       { text: localize("com_approval_task_badge_rejected"),   cls: "bg-[#fff2f0] text-[#f53f3f]" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      cls: "bg-[#f7f8fa] text-[#86909c]" },
    skipped:        { text: localize("com_approval_status_skipped"),        cls: "bg-[#f7f8fa] text-[#86909c]" },
    execute_failed: { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    exception:      { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
  };
  const INSTANCE_MAP: Record<string, { text: string; cls: string }> = {
    pending:        { text: localize("com_approval_status_pending"),        cls: "bg-[#e8f3ff] text-[#165dff]" },
    approved:       { text: localize("com_approval_status_approved"),       cls: "bg-[#e8ffea] text-[#00b42a]" },
    executed:       { text: localize("com_approval_status_approved"),       cls: "bg-[#e8ffea] text-[#00b42a]" },
    rejected:       { text: localize("com_approval_status_rejected"),       cls: "bg-[#fff2f0] text-[#f53f3f]" },
    withdrawn:      { text: localize("com_approval_status_withdrawn"),      cls: "bg-[#f7f8fa] text-[#86909c]" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      cls: "bg-[#f7f8fa] text-[#86909c]" },
    skipped:        { text: localize("com_approval_status_skipped"),        cls: "bg-[#f7f8fa] text-[#86909c]" },
    execute_failed: { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    exception:      { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
  };
  const MAP = scope === "instance" ? INSTANCE_MAP : TASK_MAP;
  const { text, cls } = MAP[effective] ?? MAP[s] ?? { text: status ?? "--", cls: "bg-[#f7f8fa] text-[#86909c]" };
  return <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[12px] font-medium", cls)}>{text}</span>;
}

export interface InfoGridProps {
  rows: [string, string][];
}

export function InfoGrid({ rows }: InfoGridProps) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[#f2f3f5] bg-[#f2f3f5]">
      {rows.map(([label, value]) => (
        <div key={label} className="bg-white px-3 py-2">
          <div className="text-[12px] text-[#86909c]">{label}</div>
          <div className="mt-1 text-[14px] font-medium text-text-primary break-all">{value || "--"}</div>
        </div>
      ))}
      {/* Fill the trailing empty slot on an odd row count so it stays white, not the grid's gray gutter.
         -ml-px covers the 1px gap gutter on its left so no divider line shows beside the empty cell. */}
      {rows.length % 2 === 1 && <div className="-ml-px bg-white" />}
    </div>
  );
}

export interface DetailHeaderProps {
  title?: string;
  status?: string;
  instanceStatus?: string;
  scope: "task" | "instance";
  serialNo: string;
  scenarioName?: string;
  createTime?: string | null;
  localize: LocalizeFn;
  onBack?: () => void;
}

export function DetailHeader({ title, status, instanceStatus, scope, serialNo, scenarioName, createTime, localize, onBack }: DetailHeaderProps) {
  return (
    // Pinned to the top of the scrolling detail pane so the title/status/serial stay visible while the body scrolls.
    <div className="sticky top-0 z-10 -mx-5 mb-5 border-b border-[#f2f3f5] bg-white px-5 pb-3 pt-3">
      <div className="flex items-start gap-3">
        {/* Compact-only back control — sits to the left of the detail title, split by a short vertical divider.
            h-6 matches the title line so the arrow centers against it under items-start. */}
        {onBack && (
          <div className="flex h-6 shrink-0 items-center gap-3 md:hidden">
            <button type="button" onClick={onBack} aria-label={localize("com_approval_back")} className="flex items-center text-[#999999]">
              <Outlined.ArrowLeft className="h-4 w-4" />
            </button>
            <span className="h-4 w-px bg-[#e5e6eb]" />
          </div>
        )}
        {/* Title + serial share one column so the serial line aligns with the title, not the back arrow. */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h3 className="min-w-0 flex-1 text-[16px] font-semibold text-text-primary leading-snug">{title || "--"}</h3>
            <StatusBadge status={status} instanceStatus={instanceStatus} scope={scope} localize={localize} />
          </div>
          <p className="mt-1.5 text-[13px] text-[#86909c]">
            {serialNo} · {scenarioName || "--"} · {formatTime(createTime)}
          </p>
        </div>
      </div>
    </div>
  );
}
