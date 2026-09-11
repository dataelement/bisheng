import type { MessageContentPart, MessageItem } from "~/api/message";

/** Payload bag carried by a content part; the backend shape varies per action code. */
type PartMetadata = MessageContentPart["metadata"];

/** Legacy senders sometimes hang the business id off the message itself. */
type MessageWithLegacyBusinessId = MessageItem & { business_id?: string | number | null };

/**
 * Pure helpers for reading an inbox message's payload: action code, business target,
 * approval-center deep link. Extracted from the old NotificationsDialog so the merged
 * 消息与审批 dialog can share them without dragging the whole component along.
 */

export const NOTIFICATION_ACTION_TEXT_KEYS: Record<string, string> = {
    request_channel: "com_notifications_action_request_channel",
    request_knowledge_space: "com_notifications_action_request_knowledge_space",
    approved_channel: "com_notifications_action_approved_channel",
    rejected_channel: "com_notifications_action_rejected_channel",
    approved_knowledge_space: "com_notifications_action_approved_knowledge_space",
    rejected_knowledge_space: "com_notifications_action_rejected_knowledge_space",
    assigned_knowledge_space_admin: "com_notifications_action_assigned_knowledge_space_admin",
    assigned_channel_admin: "com_notifications_action_assigned_channel_admin",
    request_department_knowledge_space_upload: "com_notifications_action_request_department_knowledge_space_upload",
    approved_department_knowledge_space_upload: "com_notifications_action_approved_department_knowledge_space_upload",
    rejected_department_knowledge_space_upload: "com_notifications_action_rejected_department_knowledge_space_upload",
    sensitive_rejected_department_knowledge_space_upload: "com_notifications_action_sensitive_rejected_department_knowledge_space_upload",
    // approval center notifications
    request_menu_access: "com_notifications_action_request_menu_access",
    approval_task_pending: "com_notifications_action_approval_task_pending",
    approval_task_rejected: "com_notifications_action_approval_task_rejected",
    approval_instance_approved: "com_notifications_action_approval_instance_approved",
    approval_instance_withdrawn: "com_notifications_action_approval_instance_withdrawn",
    approval_exception_cancelled: "com_notifications_action_approval_exception_cancelled",
    approval_exception_route_missing: "com_notifications_action_approval_exception_route_missing",
    approval_exception_approver_empty: "com_notifications_action_approval_exception_approver_empty",
    approval_execute_failed: "com_notifications_action_approval_execute_failed",
    menu_grant_revoked: "com_notifications_action_menu_grant_revoked",
    revoked_channel_admin: "com_notifications_action_revoked_channel_admin",
    revoked_knowledge_space_admin: "com_notifications_action_revoked_knowledge_space_admin",
    removed_channel_member: "com_notifications_action_removed_channel_member",
    removed_knowledge_space_member: "com_notifications_action_removed_knowledge_space_member",
    channel_made_private: "com_notifications_action_channel_made_private",
    knowledge_space_made_private: "com_notifications_action_knowledge_space_made_private",
    channel_dismissed: "com_notifications_action_channel_dismissed",
    knowledge_space_deleted: "com_notifications_action_knowledge_space_deleted",
};

export const APPROVAL_CENTER_ACTION_CODES = new Set([
    "request_menu_access",
    "approval_task_pending",
    "approval_task_rejected",
    "approval_instance_approved",
    "approval_instance_withdrawn",
    "approval_exception_cancelled",
    "approval_exception_route_missing",
    "approval_exception_approver_empty",
    "approval_execute_failed",
    "menu_grant_revoked",
]);

export const APPROVAL_NO_BUTTON_ACTION_CODES = new Set([
    "approval_exception_route_missing",
    "approval_exception_approver_empty",
    "approval_execute_failed",
]);

export const APPROVAL_TASK_SCENARIO_TEXT_KEYS: Record<string, string> = {
    menu_access_request: "com_notifications_action_request_menu_access",
    channel_subscribe_request: "com_notifications_action_request_channel",
    knowledge_space_subscribe_request: "com_notifications_action_request_knowledge_space",
};

export const isKnowledgeSpaceApprovalActionCode = (actionCode?: string) =>
    actionCode === "request_knowledge_space" ||
    actionCode === "approved_knowledge_space" ||
    actionCode === "rejected_knowledge_space";

export const isApprovalMessageType = (messageType?: string, actionCode?: string) =>
    messageType === "request" ||
    messageType === "approve" ||
    isKnowledgeSpaceApprovalActionCode(actionCode) ||
    APPROVAL_CENTER_ACTION_CODES.has(actionCode || "");

export const isPendingApprovalStatus = (status?: string) =>
    !!status && ["pending", "PENDING", "wait_approve", "WAIT_APPROVE"].includes(status);

export const getActionCode = (notification: MessageItem): string => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    const part = parts.find((c) => c?.type === "system_text");
    const code = part?.content;
    if (typeof code === "string" && code.trim()) return code.trim();
    return notification.action_code || "";
};

export const isPendingApprovalItem = (notification: MessageItem) =>
    isPendingApprovalStatus(notification.status) ||
    getActionCode(notification) === "approval_task_pending" ||
    notification.action_code === "approval_task_pending";

export const isApprovedStatus = (status?: string) =>
    !!status && ["approved", "APPROVED"].includes(status);

export const isRejectedStatus = (status?: string) =>
    !!status && ["rejected", "REJECTED"].includes(status);

export const isDecisionActionCode = (actionCode?: string) =>
    !!actionCode && /(approve|approved|reject|rejected)/i.test(actionCode);

export const isNotifyMessageType = (messageType?: string) =>
    messageType === "notify" || messageType === "notification";

export const isSelfApplicationDecisionActionCode = (actionCode?: string) =>
    actionCode === "approved_channel" ||
    actionCode === "rejected_channel" ||
    actionCode === "approved_knowledge_space" ||
    actionCode === "rejected_knowledge_space" ||
    actionCode === "approved_department_knowledge_space_upload" ||
    actionCode === "rejected_department_knowledge_space_upload" ||
    actionCode === "sensitive_rejected_department_knowledge_space_upload" ||
    actionCode === "approval_instance_approved" ||
    actionCode === "approval_task_rejected" ||
    actionCode === "approval_exception_cancelled" ||
    actionCode === "menu_grant_revoked";

export const getApprovalRequestId = (notification: MessageItem): number | null => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    for (const part of parts) {
        const metadata: PartMetadata = part?.metadata ?? {};
        if (metadata?.business_type !== "approval_request_id") continue;
        const data = metadata?.data ?? {};
        const rawId =
            data?.approval_request_id ??
            metadata?.business_id ??
            data?.business_id;
        if (rawId === undefined || rawId === null) continue;
        const num = Number(rawId);
        if (!Number.isNaN(num)) return num;
    }
    return null;
};

export const resolveApprovalCenterTarget = (notification: MessageItem) => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    let taskId: number | null = null;
    let instanceId: number | null = null;

    for (const part of parts) {
        const metadata: PartMetadata = part?.metadata ?? {};
        const data = metadata?.data ?? {};
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
            if (!instanceId && /approval_instance_id|instance_id|approval_request_id/i.test(normalizedType)) {
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

    const actionCode = getSystemTextCode(notification);
    const tab =
        isPendingApprovalStatus(notification.status) ||
            actionCode === "approval_task_pending" ||
            actionCode === "request_menu_access"
            ? "my_tasks"
            : "my_requests";
    return {
        tab,
        taskId,
        instanceId: instanceId ?? getApprovalRequestId(notification),
    } as const;
};

export const getTargetName = (notification: MessageItem): string => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    const businessUrlPart = parts.find((c) => c?.type === "business_url");

    const rawBusinessName = typeof businessUrlPart?.content === "string" ? businessUrlPart.content.trim() : "";
    if (rawBusinessName) {
        const cleaned = rawBusinessName.replace(/^[-—\s]+/, "").trim();
        if (cleaned) return cleaned;
    }

    const businessPart = parts.find((c) =>
        c?.type === "business" ||
        c?.type === "business_name" ||
        c?.type === "target" ||
        c?.type === "title"
    );
    if (businessPart?.content) return String(businessPart.content);

    const data = businessUrlPart?.metadata?.data || {};
    const fromMeta =
        data?.business_name ??
        data?.channel_name ??
        data?.space_name ??
        data?.name;
    if (fromMeta) return String(fromMeta);
    return "";
};

export const getScenarioCode = (notification: MessageItem): string => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    for (const part of parts) {
        const metadata: PartMetadata = part?.metadata ?? {};
        const data = metadata?.data ?? {};
        const value = metadata?.scenario_code ?? data?.scenario_code;
        if (typeof value === "string" && value.trim()) return value.trim();
    }
    return "";
};

export const getSupplementaryText = (notification: MessageItem): string => {
    const parts = Array.isArray(notification.content) ? notification.content : [];
    const tooltipPart = parts.find((c) => c?.type === "tooltip_text");
    return typeof tooltipPart?.content === "string" ? tooltipPart.content.trim() : "";
};

export const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export const isRejectedKnowledgeSpaceJoinNotification = (notification: MessageItem): boolean => {
    const code = getSystemTextCode(notification);
    return (
        code === "rejected_knowledge_space" ||
        notification.action_code === "rejected_knowledge_space"
    );
};

export const isRejectedChannelJoinNotification = (notification: MessageItem): boolean => {
    const code = getSystemTextCode(notification);
    return (
        code === "rejected_channel" ||
        notification.action_code === "rejected_channel"
    );
};

export const getNotificationTarget = (notification: MessageItem): { targetType: "channel" | "space"; targetId: string } | null => {
    const allBusinessParts = (notification.content ?? []).filter((c) => c?.type === "business_url");
    const systemText = String(notification.content?.find((c) => c?.type === "system_text")?.content ?? "");

    // Some notify payloads may contain multiple business_url segments.
    // Prefer the one whose metadata.business_type matches the notification's intent.
    const preferSpace = /knowledge_space|knowledge space|space/i.test(systemText);
    const preferChannel = /channel/i.test(systemText);
    const part =
        allBusinessParts.find((p) => {
            const bt = String(p?.metadata?.business_type ?? "");
            if (preferSpace) return /knowledge_space|space/i.test(bt);
            if (preferChannel) return /channel/i.test(bt);
            return false;
        }) ??
        allBusinessParts[0];

    const meta: PartMetadata = part?.metadata;
    const businessType = meta?.business_type;
    const data = meta?.data || {};
    const actionCode = String(notification.action_code ?? "");

    const pickId = (...vals: unknown[]) => {
        for (const v of vals) {
            if (v === undefined || v === null) continue;
            const s = String(v);
            if (s && s !== "undefined" && s !== "null") return s;
        }
        return "";
    };

    const businessTypeStr = String(businessType ?? "");
    const isChannelHint =
        /channel/i.test(businessTypeStr) ||
        /channel/i.test(actionCode) ||
        /channel/i.test(systemText);
    const isSpaceHint =
        /space/i.test(businessTypeStr) ||
        /knowledge/i.test(businessTypeStr) ||
        /knowledge_space/i.test(actionCode) ||
        /space/i.test(actionCode) ||
        /knowledge_space/i.test(systemText) ||
        /space/i.test(systemText);

    // BusinessContentItem serializes id as metadata.business_id (no nested data.channel_id)
    if (businessType === "channel_id") {
        const channelId = pickId(data?.channel_id, meta?.business_id, data?.business_id);
        if (channelId) return { targetType: "channel", targetId: channelId };
    }
    if (businessType === "channel") {
        const channelId =
            data?.channel_id ??
            data?.business_id ??
            meta?.business_id ??
            (notification as MessageWithLegacyBusinessId).business_id;
        if (channelId !== undefined && channelId !== null && String(channelId) !== "") {
            return { targetType: "channel", targetId: String(channelId) };
        }
    }
    if (businessType === "space_id" && data?.space_id) {
        return { targetType: "space", targetId: String(data.space_id) };
    }
    if (businessType === "space") {
        const spaceId = data?.space_id ?? data?.business_id ?? (notification as MessageWithLegacyBusinessId).business_id;
        if (spaceId !== undefined && spaceId !== null && String(spaceId) !== "") {
            return { targetType: "space", targetId: String(spaceId) };
        }
    }
    if (businessType === "knowledge_space_Id" || businessType === "knowledge_space_id") {
        const knowledgeSpaceId = pickId(
            data?.knowledge_space_Id,
            data?.knowledge_space_id,
            data?.space_id,
            data?.business_id,
            meta?.business_id,
            meta?.data?.business_id,
            meta?.data?.space_id,
            meta?.data?.knowledge_space_id
        );
        if (knowledgeSpaceId) {
            return { targetType: "space", targetId: knowledgeSpaceId };
        }
    }

    // Fallback: backend variants sometimes only provide business_id / id
    if (isChannelHint) {
        const id = pickId(
            data?.channel_id,
            data?.channelId,
            data?.business_id,
            data?.businessId,
            meta?.channel_id,
            meta?.channelId,
            meta?.business_id,
            (notification as MessageWithLegacyBusinessId).business_id
        );
        if (id) return { targetType: "channel", targetId: id };
    }
    if (isSpaceHint) {
        const id = pickId(
            data?.space_id,
            data?.spaceId,
            data?.knowledge_space_id,
            data?.knowledge_space_Id,
            data?.knowledgeSpaceId,
            data?.business_id,
            data?.businessId,
            meta?.space_id,
            meta?.knowledge_space_id,
            meta?.spaceId,
            meta?.business_id,
            (notification as MessageWithLegacyBusinessId).business_id
        );
        if (id) return { targetType: "space", targetId: id };
    }

    // Last resort: if there's a business_url and system_text indicates a space,
    // try to pick any plausible id even when business_type is missing/unexpected.
    if (part && /knowledge_space|space/i.test(systemText)) {
        const id = pickId(
            data?.space_id,
            data?.knowledge_space_Id,
            data?.knowledge_space_id,
            data?.knowledgeSpaceId,
            data?.business_id,
            meta?.space_id,
            meta?.knowledge_space_Id,
            meta?.knowledge_space_id,
            meta?.business_id,
            meta?.spaceId,
            meta?.knowledgeSpaceId
        );
        if (id) return { targetType: "space", targetId: id };
    }
    return null;
};

/** Alias kept for readability at call sites: the action code lives in the system_text part. */
export const getSystemTextCode = getActionCode;
