import { Outlined } from "bisheng-icons";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ApprovalCenterTab } from "~/api/approval";
import { ApprovalPane } from "~/components/approval/ApprovalPane";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { NotificationPane } from "./NotificationPane";

export type MessageApprovalSection = ApprovalCenterTab | "notifications";

export type MessageApprovalTarget = {
  section?: MessageApprovalSection;
  taskId?: number | null;
  instanceId?: number | null;
};

export interface MessageApprovalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Deep link — e.g. a notification jumping straight to one approval task. */
  target?: MessageApprovalTarget;
  /** Approval tasks still waiting on this user; shown on the 我的审批 rail item. */
  pendingApprovalCount?: number;
  /** Unread notifications; shown on the 通知 rail item. */
  unreadNotificationCount?: number;
  onCountsMaybeChanged?: () => void;
}

const SECTIONS: MessageApprovalSection[] = ["my_tasks", "my_requests", "notifications"];

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[#f53f3f] px-1 text-[11px] leading-none text-white tabular-nums">
      {count > 99 ? "99+" : count}
    </span>
  );
}

/**
 * 消息与审批 — one entry carrying both the approval work list and the notification inbox.
 *
 * Ownership is strict: an approval that still needs handling lives only under 我的审批-待我处理,
 * and 通知 only informs. Opening an approval detail is not "handling" it, so nothing here
 * decrements the pending count on its own — only a real decision does.
 */
export function MessageApprovalDialog({
  open,
  onOpenChange,
  target,
  pendingApprovalCount = 0,
  unreadNotificationCount = 0,
  onCountsMaybeChanged,
}: MessageApprovalDialogProps) {
  const localize = useLocalize();
  const [section, setSection] = useState<MessageApprovalSection>("my_tasks");
  // Compact (<768px) is a master-detail flow: "list" shows the nav rail + list, "detail" shows
  // the selected item full-screen with a back action.
  const [compactView, setCompactView] = useState<"list" | "detail">("list");
  /** Set when a notification jumps into an approval detail from inside this dialog. */
  const [deepLink, setDeepLink] = useState<{ taskId?: number | null; instanceId?: number | null } | null>(null);

  useEffect(() => {
    if (!open) return;
    // An explicit deep link wins; otherwise land where the user actually has work to do.
    setSection(target?.section ?? (pendingApprovalCount > 0 ? "my_tasks" : "notifications"));
    setCompactView(target?.taskId || target?.instanceId ? "detail" : "list");
    setDeepLink(null);
    // Only re-evaluate on (re)open or when the deep link changes — not when the count ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target?.section, target?.taskId, target?.instanceId]);

  const isNotifications = section === "notifications";
  const approvalTab: ApprovalCenterTab = section === "notifications" ? "my_tasks" : section;

  const sectionLabel = (value: MessageApprovalSection) =>
    value === "my_tasks"
      ? localize("com_approval_my_approval")
      : value === "my_requests"
        ? localize("com_approval_my_requests")
        : localize("com_message_approval_notifications");

  const sectionIcon = (value: MessageApprovalSection) =>
    value === "my_tasks" ? Outlined.ApprovalTodo : value === "my_requests" ? Outlined.ApprovalSubmitted : Outlined.Bell;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        close={false}
        className={cn(
          // Compact mode (<768px): full-screen overlay.
          "h-screen max-h-none w-screen max-w-none rounded-none border-0 p-0 sm:rounded-none",
          // Default mode (>=768px): centered dialog, 80vh (cap 800px) tall.
          "md:h-[80vh] md:max-h-[800px] md:w-[calc(100vw-80px)] md:max-w-[800px] md:rounded-xl md:border",
        )}
      >
        <div className="flex h-full flex-col overflow-hidden rounded-none bg-white md:rounded-xl">
          <div className="flex items-center justify-between border-b border-fill-2 px-5 py-3">
            <h2 className="text-[16px] font-semibold text-text-primary">{localize("com_message_approval_title")}</h2>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              aria-label={localize("com_ui_close")}
              className="rounded-lg text-text-3 opacity-70 transition-opacity hover:opacity-100 focus:outline-none"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div
            className={cn(
              "grid min-h-0 flex-1",
              compactView === "list" || isNotifications ? "grid-cols-[72px_minmax(0,1fr)]" : "grid-cols-1",
              isNotifications ? "md:grid-cols-[72px_minmax(0,1fr)]" : "md:grid-cols-[72px_300px_minmax(0,1fr)]",
            )}
          >
            {/* Vertical nav rail — approval first, notifications last. */}
            <div
              className={cn(
                "flex flex-col gap-0 border-r border-fill-2 bg-[#fafbfc] px-1 pb-2",
                compactView === "detail" && !isNotifications && "hidden md:flex",
              )}
            >
              {SECTIONS.map((value) => {
                const SectionIcon = sectionIcon(value);
                const badge = value === "my_tasks" ? pendingApprovalCount : value === "notifications" ? unreadNotificationCount : 0;
                return (
                  <button
                    key={value}
                    type="button"
                    className={cn(
                      "flex w-16 flex-col items-center gap-2 rounded-lg px-1 py-5 text-[12px] leading-none transition-colors",
                      section === value ? "font-medium text-text-1" : "text-text-3 hover:bg-fill-1",
                    )}
                    onClick={() => {
                      setSection(value);
                      setCompactView("list");
                      setDeepLink(null);
                    }}
                  >
                    <span className="relative">
                      <SectionIcon className="size-[18px]" />
                      <CountBadge count={badge} />
                    </span>
                    {sectionLabel(value)}
                  </button>
                );
              })}
            </div>

            {isNotifications ? (
              <NotificationPane
                open={open && isNotifications}
                onOpenApprovalCenter={(approvalTarget) => {
                  setSection(approvalTarget.tab);
                  setCompactView("detail");
                  setDeepLink({ taskId: approvalTarget.taskId, instanceId: approvalTarget.instanceId });
                }}
                onUnreadMaybeChanged={onCountsMaybeChanged}
              />
            ) : (
              <ApprovalPane
                open={open && !isNotifications}
                activeTab={approvalTab}
                target={deepLink ?? { taskId: target?.taskId, instanceId: target?.instanceId }}
                compactView={compactView}
                setCompactView={setCompactView}
                onPendingCountMaybeChanged={onCountsMaybeChanged}
              />
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
