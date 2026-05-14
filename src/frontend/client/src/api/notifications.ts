import request from "./request";

// 消息类型
export enum NotificationType {
    REQUEST = "request",      // 请求类
    NOTIFICATION = "notification"  // 通知类
}

// 消息子类型
export enum NotificationSubType {
    // 请求类
    SUBSCRIBE_CHANNEL = "subscribe_channel",       // 申请订阅频道
    JOIN_SPACE = "join_space",                     // 申请加入知识空间

    // 通知类
    SUBSCRIBE_APPROVED = "subscribe_approved",     // 同意订阅频道申请
    SUBSCRIBE_REJECTED = "subscribe_rejected",     // 拒绝订阅频道申请
    JOIN_APPROVED = "join_approved",               // 同意加入知识空间申请
    JOIN_REJECTED = "join_rejected",               // 拒绝加入知识空间申请
    ADD_ADMIN = "add_admin"                        // 添加为管理员
}

// 审批状态
export enum ApprovalStatus {
    PENDING = "pending",      // 待审批
    APPROVED = "approved",    // 已同意
    REJECTED = "rejected"     // 已拒绝
}

// 消息接口
export interface Notification {
    id: string;
    type: NotificationType;
    subType: NotificationSubType;
    userId: string;              // 发送者用户ID
    userName: string;            // 发送者用户名
    userGroup?: string;          // 发送者用户组
    userAvatar?: string;         // 发送者头像
    targetId: string;            // 目标ID（频道ID或空间ID）
    targetName: string;          // 目标名称（频道名称或空间名称）
    targetType: "channel" | "space";  // 目标类型
    approvalStatus?: ApprovalStatus;  // 审批状态（仅请求类消息）
    isRead: boolean;             // 是否已读
    createdAt: string;           // 创建时间
}

/**
 * 获取消息列表
 */
export async function getNotificationsApi(params: {
    page?: number;
    pageSize?: number;
    type?: NotificationType;
    onlyUnread?: boolean;
    search?: string;
}): Promise<{
    data: Notification[];
    total: number;
    unreadCount: number;
    requestUnreadCount: number;
}> {
    return await request.get(`/api/v1/notifications`, { params });
}

/**
 * 标记消息为已读
 */
export async function markAsReadApi(notificationIds: string[]): Promise<any> {
    return await request.post(`/api/v1/notifications/mark-read`, { notificationIds });
}

/**
 * 标记所有消息为已读
 */
export async function markAllAsReadApi(): Promise<any> {
    return await request.post(`/api/v1/notifications/mark-all-read`);
}

/**
 * 删除消息
 */
export async function deleteNotificationApi(notificationId: string): Promise<any> {
    return await request.delete(`/api/v1/notifications/${notificationId}`);
}

/**
 * 审批请求（同意/拒绝）
 */
export async function approveRequestApi(data: {
    notificationId: string;
    status: ApprovalStatus.APPROVED | ApprovalStatus.REJECTED;
}): Promise<any> {
    return await request.post(`/api/v1/notifications/approve`, data);
}
