import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { MessageItem } from "~/api/message";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { TooltipAnchor } from "~/components/ui/Tooltip";
import useLocalize, { type TranslationKeys } from "~/hooks/useLocalize";
import { cn } from "~/utils";
import {
  APPROVAL_NO_BUTTON_ACTION_CODES,
  APPROVAL_TASK_SCENARIO_TEXT_KEYS,
  NOTIFICATION_ACTION_TEXT_KEYS,
  escapeRegExp,
  getNotificationTarget,
  getScenarioCode,
  getSupplementaryText,
  getSystemTextCode,
  getTargetName,
  isApprovalMessageType,
  isApprovedStatus,
  isPendingApprovalStatus,
  isRejectedChannelJoinNotification,
  isRejectedKnowledgeSpaceJoinNotification,
  isRejectedStatus,
  resolveApprovalCenterTarget,
} from "./notificationContent";

export type ApprovalCenterTarget = ReturnType<typeof resolveApprovalCenterTarget>;

export interface NotificationRowProps {
  notification: MessageItem;
  /** Touch-first layout: time drops under the text and hover affordances are dropped. */
  isTouchMobile: boolean;
  formatTime: (createdAt: string) => string;
  onOpenApprovalCenter: (target: ApprovalCenterTarget) => void;
  onMarkRead: (id: number) => void;
  onDelete: (id: number) => void;
}

/**
 * One inbox notification.
 *
 * Read state is only ever changed by an explicit user action (opening the notification or
 * deleting it) — merely rendering, hovering or scrolling a row must never mark it read.
 */
export function NotificationRow({
  notification,
  isTouchMobile,
  formatTime,
  onOpenApprovalCenter,
  onMarkRead,
  onDelete,
}: NotificationRowProps) {
  const localize = useLocalize();
  const [hovered, setHovered] = useState(false);
  /** Set when the related object cannot be resolved — we show a hint instead of navigating. */
  const [invalidTarget, setInvalidTarget] = useState(false);

  const id = Number(notification.id);
  const userPart = notification.content?.find((c) => c?.type === "user");
  const userMeta = userPart?.metadata ?? {};
  const userName = String(notification.sender_name || userPart?.content || "").replace(/^@/, "");
  const groupNamesRaw =
    userMeta?.group_names ?? userMeta?.groupNames ?? userMeta?.group_name ?? userMeta?.groupName ?? [];
  const groupNames = Array.isArray(groupNamesRaw)
    ? groupNamesRaw.map((g: unknown) => String(g)).filter(Boolean)
    : String(groupNamesRaw ? groupNamesRaw : "")
        .split(/[,/]/)
        .map((g) => g.trim())
        .filter(Boolean);
  const userGroup = groupNames.join("、");
  const userAvatar = userMeta?.avatar || userMeta?.user_avatar || "";

  const actionCode = getSystemTextCode(notification);
  const targetName = getTargetName(notification);
  const supplementaryText = getSupplementaryText(notification);
  const target = getNotificationTarget(notification);
  const isApprovalMessage = isApprovalMessageType(notification.message_type, notification.action_code);

  const scenarioTextKey =
    actionCode === "approval_task_pending" ? APPROVAL_TASK_SCENARIO_TEXT_KEYS[getScenarioCode(notification)] : "";
  const actionTextKey =
    scenarioTextKey || NOTIFICATION_ACTION_TEXT_KEYS[actionCode] || (actionCode ? `com_notifications_action_${actionCode}` : "");
  const safeLocalize = (key: string, vars?: Record<string, string>) => {
    if (!key) return "";
    const translated = localize(key as TranslationKeys, vars);
    return translated && translated !== key ? translated : "";
  };
  const fallbackText = notification.content?.map((c) => c.content).filter(Boolean).join("") || "";
  const text =
    safeLocalize(actionTextKey, { target: targetName }) ||
    safeLocalize(
      targetName ? "com_notifications_action_generic_with_target" : "com_notifications_action_generic",
      targetName ? { target: targetName } : undefined,
    ) ||
    fallbackText;

  const approvalCenterTarget = isApprovalMessage ? resolveApprovalCenterTarget(notification) : null;
  const canOpenApprovalCenter = Boolean(approvalCenterTarget && !APPROVAL_NO_BUTTON_ACTION_CODES.has(actionCode));
  const canNavigateTarget = Boolean(target && target.targetId && targetName) && !canOpenApprovalCenter;

  const isDecided = isApprovedStatus(notification.status) || isRejectedStatus(notification.status);
  const showsCompletedPill =
    !canOpenApprovalCenter && isApprovalMessage && isDecided && !isPendingApprovalStatus(notification.status);

  const markReadIfNeeded = () => {
    if (!notification.is_read) onMarkRead(id);
  };

  const handleOpenApprovalCenter = () => {
    if (!approvalCenterTarget) return;
    // A deep link with neither id resolves to nothing on the other side — say so instead of
    // opening an empty detail pane.
    if (!approvalCenterTarget.taskId && !approvalCenterTarget.instanceId) {
      setInvalidTarget(true);
      markReadIfNeeded();
      return;
    }
    markReadIfNeeded();
    onOpenApprovalCenter(approvalCenterTarget);
  };

  const handleNavigateTarget = () => {
    if (!target?.targetId) {
      setInvalidTarget(true);
      markReadIfNeeded();
      return;
    }
    markReadIfNeeded();
    const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
    const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
    const route =
      target.targetType === "channel"
        ? isRejectedChannelJoinNotification(notification)
          ? `/channel/share/${target.targetId}?square=1`
          : `/channel/${target.targetId}`
        : isRejectedKnowledgeSpaceJoinNotification(notification)
          ? `/knowledge?square=1&previewSpace=${encodeURIComponent(target.targetId)}`
          : `/knowledge/space/${target.targetId}`;
    window.open(normalizedBase + route, "_blank");
  };

  const targetSplitMatch = targetName
    ? text.match(new RegExp(`^(.*?)([-—\\s]*${escapeRegExp(targetName)})(.*)$`))
    : null;
  const textPrefix = targetSplitMatch ? targetSplitMatch[1] : text;
  const textSuffix = targetSplitMatch ? targetSplitMatch[3] : "";

  const unread = !notification.is_read;
  const textColor = unread ? "text-text-1 font-medium" : "text-[#989898]";
  const showDelete = hovered && !isTouchMobile;

  const targetSpan = (
    <span className="cursor-pointer font-medium hover:text-blue-500" onClick={handleNavigateTarget}>
      {targetName}
    </span>
  );

  return (
    <div
      data-message-id={id}
      data-message-type={notification.message_type}
      className={cn(
        "flex flex-col gap-2 px-3 transition-colors duration-300",
        isTouchMobile ? "py-3" : "py-6 hover:bg-fill-1",
        // Unread rows carry the light brand wash; read rows fall back to the plain list background.
        unread && "bg-blue-500/[0.04]",
        canOpenApprovalCenter && "group cursor-pointer",
      )}
      onClick={canOpenApprovalCenter ? handleOpenApprovalCenter : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={cn("flex gap-2", isTouchMobile ? "items-start" : "items-center gap-3")}>
        {/* Unread marker — a plain red dot, no state dot once read. */}
        <span
          className={cn("mt-1 size-2 shrink-0 rounded-full md:mt-0", unread ? "bg-[#f53f3f]" : "bg-transparent")}
          aria-hidden
        />
        <TooltipAnchor
          side="left"
          hideArrow
          className="shrink-0"
          tooltipClassName="box-border flex h-[64px] w-[151px] flex-col justify-center overflow-hidden rounded-lg border border-solid border-border-base bg-white p-0 opacity-100 shadow-[0_4px_12px_rgba(0,0,0,0.08)] z-[100]"
          description={
            <div className="flex h-full w-full flex-col justify-center px-3 py-2">
              <div className="truncate text-[14px] font-normal leading-tight text-text-1">{userName}</div>
              {userGroup ? (
                <div className="mt-0.5 line-clamp-2 text-left text-[12px] font-normal leading-tight text-[#A9AEB8]">
                  {userGroup}
                </div>
              ) : null}
            </div>
          }
        >
          <Avatar className={cn("shrink-0", isTouchMobile ? "size-10" : "size-9")}>
            {userAvatar ? <AvatarImage src={userAvatar} alt={userName} /> : <AvatarName name={userName} className="text-xs" />}
          </Avatar>
        </TooltipAnchor>

        <div
          className={cn(
            "flex min-w-0 flex-1 gap-1 text-[14px]",
            isTouchMobile ? "flex-col" : "flex-row flex-wrap items-center gap-1",
            textColor,
            canOpenApprovalCenter && "transition-colors group-hover:text-blue-500",
          )}
        >
          <span className="shrink-0 font-medium hover:text-blue-500">@{userName}</span>
          <span className="min-w-0">
            {!targetSplitMatch && canNavigateTarget && targetSpan}
            {textPrefix}
            {targetSplitMatch && !canNavigateTarget && targetName && <span className="font-medium">{targetName}</span>}
            {targetSplitMatch && canNavigateTarget && targetSpan}
            {textSuffix}
          </span>
          <span className={cn("text-[14px] tabular-nums text-text-3", isTouchMobile ? "inline" : "hidden")}>
            {formatTime(notification.create_time)}
          </span>
        </div>

        {/* Fixed-width right slot so the hover swap (time ↔ delete) never reflows the text column. */}
        <div
          className={cn(
            "relative h-7 w-[184px] shrink-0 items-center justify-end whitespace-nowrap",
            isTouchMobile ? "hidden" : "flex",
          )}
        >
          <span className={cn("text-[14px] tabular-nums text-text-3", showDelete && "invisible")} aria-hidden={showDelete}>
            {formatTime(notification.create_time)}
          </span>
          {showDelete && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(id);
              }}
              className="absolute right-0 top-1/2 inline-flex h-7 -translate-y-1/2 appearance-none items-center gap-1.5 rounded-md border border-border-base bg-white px-3 text-[14px] text-text-2 transition-colors hover:border-[#f53f3f] hover:text-[#f53f3f]"
              title={localize("com_notifications_delete")}
            >
              <Trash2 className="size-4" />
              {localize("com_notifications_delete")}
            </button>
          )}
        </div>
      </div>

      {showsCompletedPill && (
        <div className="flex justify-end">
          <button type="button" disabled className="h-7 cursor-default rounded-md border border-border-base bg-fill-1 px-3 text-[14px] text-text-3">
            {isApprovedStatus(notification.status) ? localize("com_notifications_approved") : localize("com_notifications_rejected")}
          </button>
        </div>
      )}

      {invalidTarget && (
        <div className={cn("text-[13px] leading-6 text-text-3", isTouchMobile ? "pl-0" : "pl-14")}>
          {localize("com_notifications_target_unavailable")}
        </div>
      )}

      {supplementaryText && (
        <div className={cn("text-[13px] leading-6 text-text-3", isTouchMobile ? "pl-0" : "pl-14")}>{supplementaryText}</div>
      )}
    </div>
  );
}
