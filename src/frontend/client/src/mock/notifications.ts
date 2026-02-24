import {
    Notification,
    NotificationType,
    NotificationSubType,
    ApprovalStatus
} from "~/api/notifications";

// 模拟消息数据
export const mockNotifications: Notification[] = [
    {
        id: "1",
        type: NotificationType.NOTIFICATION,
        subType: NotificationSubType.SUBSCRIBE_APPROVED,
        userId: "user1",
        userName: "管理员",
        userGroup: "管理组",
        userAvatar: "/avatars/admin.png",
        targetId: "channel1",
        targetName: "北京新闻",
        targetType: "channel",
        isRead: false,
        createdAt: "2026-01-17T17:17:17"
    },
    {
        id: "2",
        type: NotificationType.REQUEST,
        subType: NotificationSubType.SUBSCRIBE_CHANNEL,
        userId: "user2",
        userName: "庄婧琪",
        userGroup: "编辑部",
        userAvatar: "/avatars/user2.png",
        targetId: "channel2",
        targetName: "北京新闻",
        targetType: "channel",
        approvalStatus: ApprovalStatus.PENDING,
        isRead: false,
        createdAt: "2026-01-17T17:17:17"
    },
    {
        id: "3",
        type: NotificationType.NOTIFICATION,
        subType: NotificationSubType.ADD_ADMIN,
        userId: "user3",
        userName: "管理员",
        userGroup: "管理组",
        userAvatar: "/avatars/admin.png",
        targetId: "channel3",
        targetName: "北京新闻",
        targetType: "channel",
        isRead: false,
        createdAt: "2026-01-17T17:17:17"
    },
    {
        id: "4",
        type: NotificationType.REQUEST,
        subType: NotificationSubType.SUBSCRIBE_CHANNEL,
        userId: "user4",
        userName: "庄婧琪",
        userGroup: "编辑部",
        userAvatar: "/avatars/user4.png",
        targetId: "channel4",
        targetName: "北京新闻",
        targetType: "channel",
        approvalStatus: ApprovalStatus.PENDING,
        isRead: false,
        createdAt: "2026-01-17T17:17:17"
    },
    {
        id: "5",
        type: NotificationType.REQUEST,
        subType: NotificationSubType.JOIN_SPACE,
        userId: "user5",
        userName: "李四",
        userGroup: "研发部",
        userAvatar: "/avatars/user5.png",
        targetId: "space1",
        targetName: "北京新闻",
        targetType: "space",
        approvalStatus: ApprovalStatus.PENDING,
        isRead: false,
        createdAt: "2026-01-17T17:17:17"
    },
    {
        id: "6",
        type: NotificationType.REQUEST,
        subType: NotificationSubType.SUBSCRIBE_CHANNEL,
        userId: "user6",
        userName: "王五",
        userGroup: "测试部",
        userAvatar: "/avatars/user6.png",
        targetId: "channel5",
        targetName: "上海新闻",
        targetType: "channel",
        approvalStatus: ApprovalStatus.APPROVED,
        isRead: true,
        createdAt: "2026-01-16T15:30:00"
    },
    {
        id: "7",
        type: NotificationType.NOTIFICATION,
        subType: NotificationSubType.SUBSCRIBE_REJECTED,
        userId: "user7",
        userName: "赵六",
        userGroup: "产品部",
        userAvatar: "/avatars/user7.png",
        targetId: "channel6",
        targetName: "广州新闻",
        targetType: "channel",
        isRead: true,
        createdAt: "2026-01-15T10:20:00"
    },
    {
        id: "8",
        type: NotificationType.NOTIFICATION,
        subType: NotificationSubType.JOIN_APPROVED,
        userId: "user8",
        userName: "孙七",
        userGroup: "设计部",
        userAvatar: "/avatars/user8.png",
        targetId: "space2",
        targetName: "深圳知识库",
        targetType: "space",
        isRead: false,
        createdAt: "2026-01-17T12:00:00"
    }
];

// 模拟 API 响应
export function getMockNotifications(params: {
    type?: NotificationType;
    onlyUnread?: boolean;
    search?: string;
}) {
    let filtered = [...mockNotifications];

    // 按类型过滤
    if (params.type) {
        filtered = filtered.filter(n => n.type === params.type);
    }

    // 只看未读
    if (params.onlyUnread) {
        filtered = filtered.filter(n => !n.isRead);
    }

    // 搜索
    if (params.search) {
        const query = params.search.toLowerCase();
        filtered = filtered.filter(n =>
            n.userName.toLowerCase().includes(query) ||
            n.targetName.toLowerCase().includes(query) ||
            n.userGroup?.toLowerCase().includes(query)
        );
    }

    const unreadCount = mockNotifications.filter(n => !n.isRead).length;
    const requestUnreadCount = mockNotifications.filter(
        n => n.type === NotificationType.REQUEST && !n.isRead
    ).length;

    return {
        data: filtered,
        total: filtered.length,
        unreadCount,
        requestUnreadCount
    };
}
