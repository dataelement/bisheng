import type { MessageItem } from "~/api/message";

const APPROVAL_CENTER_ACTION_CODES = new Set([
  "request_menu_access",
  "approval_task_pending",
  "approval_task_rejected",
  "approval_instance_approved",
  "approval_instance_withdrawn",
  "approval_exception_cancelled",
  "approval_exception_route_missing",
  "approval_exception_approver_empty",
  "approval_execute_failed",
  "resource_user_invite_pending",
  "resource_user_invite_effective",
  "resource_user_invite_failed",
  "menu_grant_revoked",
]);

export function getNotificationActionCode(notification: MessageItem): string {
  const parts = Array.isArray(notification.content) ? notification.content : [];
  const part = parts.find((item) => item?.type === "system_text");
  const code = part?.content;
  if (typeof code === "string" && code.trim()) return code.trim();
  return notification.action_code || "";
}

export function isPendingApprovalStatus(status?: string) {
  return !!status && ["pending", "PENDING", "wait_approve", "WAIT_APPROVE"].includes(status);
}

export function isApprovalMessageType(messageType?: string, actionCode?: string) {
  const isKnowledgeSpaceApprovalActionCode =
    actionCode === "request_knowledge_space" ||
    actionCode === "approved_knowledge_space" ||
    actionCode === "rejected_knowledge_space";
  return (
    messageType === "request" ||
    messageType === "approve" ||
    isKnowledgeSpaceApprovalActionCode ||
    APPROVAL_CENTER_ACTION_CODES.has(actionCode || "")
  );
}

export function isApprovalCenterNotification(notification: MessageItem): boolean {
  return isApprovalMessageType(
    notification.message_type,
    notification.action_code || getNotificationActionCode(notification),
  );
}

function getApprovalRequestId(notification: MessageItem): number | null {
  const parts = Array.isArray(notification.content) ? notification.content : [];
  for (const part of parts) {
    const metadata = part?.metadata ?? {};
    if (metadata?.business_type !== "approval_request_id") continue;
    const data = metadata?.data ?? {};
    const rawId = data?.approval_request_id ?? metadata?.business_id ?? data?.business_id;
    if (rawId === undefined || rawId === null) continue;
    const num = Number(rawId);
    if (!Number.isNaN(num)) return num;
  }
  return null;
}

export function resolveApprovalCenterNotificationTarget(notification: MessageItem) {
  const parts = Array.isArray(notification.content) ? notification.content : [];
  let taskId: number | null = null;
  let instanceId: number | null = null;

  for (const part of parts) {
    const metadata = part?.metadata ?? {};
    const data = metadata?.data ?? {};
    const directTaskId = Number(data?.approval_task_id ?? data?.task_id);
    if (!taskId && Number.isFinite(directTaskId)) taskId = directTaskId;
    const candidates = [
      [metadata?.business_type, data],
      [metadata?.type, data],
    ] as const;

    for (const [businessType, payload] of candidates) {
      const normalizedType = String(businessType || "");
      if (!taskId && /approval_task_id|task_id/i.test(normalizedType)) {
        const rawTaskId =
          payload?.approval_task_id ??
          payload?.task_id ??
          metadata?.business_id ??
          payload?.business_id;
        const parsedTaskId = Number(rawTaskId);
        if (Number.isFinite(parsedTaskId)) taskId = parsedTaskId;
      }
      if (
        !instanceId &&
        /approval_instance_id|instance_id|approval_request_id/i.test(normalizedType)
      ) {
        const rawInstanceId =
          payload?.approval_instance_id ??
          payload?.instance_id ??
          payload?.approval_request_id ??
          metadata?.business_id ??
          payload?.business_id;
        const parsedInstanceId = Number(rawInstanceId);
        if (Number.isFinite(parsedInstanceId)) instanceId = parsedInstanceId;
      }
    }
  }

  const actionCode = getNotificationActionCode(notification);
  const tab =
    isPendingApprovalStatus(notification.status) ||
    actionCode === "approval_task_pending" ||
    actionCode === "request_menu_access" ||
    actionCode === "resource_user_invite_pending"
      ? "my_tasks"
      : "my_requests";
  return {
    tab,
    taskId,
    instanceId: instanceId ?? getApprovalRequestId(notification),
  } as const;
}
