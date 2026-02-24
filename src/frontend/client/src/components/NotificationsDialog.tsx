import { useState, useEffect, useMemo } from "react";
import { X, Search, Trash2, Check, XIcon } from "lucide-react";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "~/components/ui/Tabs";
import { Switch } from "~/components/ui/Switch";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Avatar, AvatarImage } from "~/components/ui/avatar";
import { TooltipAnchor } from "~/components/ui/Tooltip";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import {
    Notification,
    NotificationType,
    NotificationSubType,
    ApprovalStatus,
    getNotificationsApi,
    markAsReadApi,
    markAllAsReadApi,
    deleteNotificationApi,
    approveRequestApi
} from "~/api/notifications";
import { mockNotifications, getMockNotifications } from "~/mock/notifications";

interface NotificationsDialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
}

export function NotificationsDialog({ open = false, onOpenChange }: NotificationsDialogProps) {
    const [activeTab, setActiveTab] = useState<"all" | "request">("all");
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const { showToast } = useToastContext();

    // 统计未读数量
    const unreadCounts = useMemo(() => {
        const allUnread = notifications.filter(n => !n.isRead).length;
        const requestUnread = notifications.filter(
            n => n.type === NotificationType.REQUEST && !n.isRead
        ).length;
        return { all: allUnread, request: requestUnread };
    }, [notifications]);

    // 加载消息列表
    const loadNotifications = async () => {
        setLoading(true);
        try {
            // 使用模拟数据
            const response = getMockNotifications({
                type: activeTab === "request" ? NotificationType.REQUEST : undefined,
                onlyUnread,
                search: searchQuery
            });

            // 模拟网络延迟
            await new Promise(resolve => setTimeout(resolve, 300));

            setNotifications(response.data);
        } catch (error) {
            console.error("Failed to load notifications:", error);
        } finally {
            setLoading(false);
        }
    };

    // 初始加载和条件变化时重新加载
    useEffect(() => {
        if (open) {
            loadNotifications();
        }
    }, [open, activeTab, onlyUnread, searchQuery]);

    // 过滤和排序消息
    const filteredNotifications = useMemo(() => {
        let filtered = notifications;

        // 按时间倒序排列
        filtered = filtered.sort((a, b) =>
            new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        );

        return filtered;
    }, [notifications]);

    // 请求类消息分组
    const requestGroups = useMemo(() => {
        if (activeTab !== "request") return { pending: [], approved: [] };

        const pending = filteredNotifications.filter(
            n => n.approvalStatus === ApprovalStatus.PENDING
        );
        const approved = filteredNotifications.filter(
            n => n.approvalStatus !== ApprovalStatus.PENDING
        );

        return { pending, approved };
    }, [activeTab, filteredNotifications]);

    // 全部已读
    const handleMarkAllAsRead = async () => {
        try {
            // 使用模拟数据 - 直接更新状态
            setNotifications(prev =>
                prev.map(n => ({ ...n, isRead: true }))
            );
            showToast({
                message: "已全部标记为已读",
                severity: NotificationSeverity.SUCCESS
            });
        } catch (error) {
            showToast({
                message: "操作失败",
                severity: NotificationSeverity.INFO
            });
        }
    };

    // 删除消息
    const handleDelete = async (id: string) => {
        try {
            // 使用模拟数据 - 直接更新状态
            setNotifications(prev => prev.filter(n => n.id !== id));
            showToast({
                message: "消息已删除",
                severity: NotificationSeverity.SUCCESS
            });
        } catch (error) {
            showToast({
                message: "删除失败",
                severity: NotificationSeverity.INFO
            });
        }
    };

    // 审批操作
    const handleApproval = async (
        notificationId: string,
        status: ApprovalStatus.APPROVED | ApprovalStatus.REJECTED
    ) => {
        try {
            // 使用模拟数据 - 直接更新状态
            setNotifications(prev =>
                prev.map(n =>
                    n.id === notificationId
                        ? { ...n, approvalStatus: status, isRead: true }
                        : n
                )
            );

            showToast({
                message: "操作成功",
                severity: NotificationSeverity.SUCCESS
            });
        } catch (error) {
            showToast({
                message: "操作失败",
                severity: NotificationSeverity.INFO
            });
        }
    };

    // 获取消息文本
    const getNotificationText = (notification: Notification) => {
        const { subType, userName, targetName, targetType, approvalStatus } = notification;

        switch (subType) {
            case NotificationSubType.SUBSCRIBE_CHANNEL:
                return {
                    text: `申请订阅你的频道 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: approvalStatus === ApprovalStatus.PENDING
                };
            case NotificationSubType.JOIN_SPACE:
                return {
                    text: `申请加入你的知识空间 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: approvalStatus === ApprovalStatus.PENDING
                };
            case NotificationSubType.SUBSCRIBE_APPROVED:
                return {
                    text: `同意了你订阅频道的申请 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: false
                };
            case NotificationSubType.SUBSCRIBE_REJECTED:
                return {
                    text: `拒绝了你订阅频道的申请 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: false
                };
            case NotificationSubType.JOIN_APPROVED:
                return {
                    text: `同意了你加入知识空间的申请 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: false
                };
            case NotificationSubType.JOIN_REJECTED:
                return {
                    text: `拒绝了你加入知识空间的申请 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: false
                };
            case NotificationSubType.ADD_ADMIN:
                return {
                    text: `将你添加为${targetType === "channel" ? "频道" : "知识空间"}的管理员 —— ${targetName}`,
                    userName,
                    targetName,
                    showApproval: false
                };
            default:
                return {
                    text: "",
                    userName,
                    targetName,
                    showApproval: false
                };
        }
    };

    // 渲染消息项
    const renderNotificationItem = (notification: Notification) => {
        const { id, userName, userGroup, userAvatar, isRead, createdAt, approvalStatus } = notification;
        const { text, targetName, showApproval } = getNotificationText(notification);
        const isHovered = hoveredId === id;

        // 已审批的消息显示为浅色
        const isApproved = approvalStatus && approvalStatus !== ApprovalStatus.PENDING;
        const textColor = isRead || isApproved ? "text-[#86909c]" : "text-[#1d2129]";

        return (
            <div
                key={id}
                className="flex items-start gap-3 px-6 py-4 hover:bg-[#f7f8fa] transition-colors relative"
                onMouseEnter={() => setHoveredId(id)}
                onMouseLeave={() => setHoveredId(null)}
            >
                {/* 头像 */}
                <Avatar className="size-10 flex-shrink-0">
                    <AvatarImage src={userAvatar || "/default-avatar.png"} alt={userName} />
                </Avatar>

                {/* 消息内容 */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                        <div className={`text-[14px] ${textColor}`}>
                            <TooltipAnchor
                                description={userGroup ? `${userName} - ${userGroup}` : userName}
                                side="top"
                            >
                                <span className="font-medium cursor-pointer hover:text-[#165dff]">
                                    @{userName}
                                </span>
                            </TooltipAnchor>
                            {" "}
                            {text.split(targetName)[0]}
                            <span
                                className="font-medium cursor-pointer hover:text-[#165dff]"
                                onClick={() => {
                                    // TODO: 跳转到频道/空间详情页
                                    console.log("Navigate to:", targetName);
                                }}
                            >
                                {targetName}
                            </span>
                        </div>

                        {/* 时间 */}
                        <span className="text-[12px] text-[#86909c] whitespace-nowrap flex-shrink-0">
                            {new Date(createdAt).toLocaleString("zh-CN", {
                                year: "numeric",
                                month: "2-digit",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit"
                            })}
                        </span>
                    </div>

                    {/* 审批按钮或删除按钮 */}
                    {showApproval ? (
                        <div className="flex items-center gap-2 mt-2">
                            <button
                                onClick={() => handleApproval(id, ApprovalStatus.REJECTED)}
                                className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#f53f3f] hover:bg-[#fff2f0] rounded transition-colors"
                            >
                                <XIcon className="size-3" />
                                拒绝
                            </button>
                            <button
                                onClick={() => handleApproval(id, ApprovalStatus.APPROVED)}
                                className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#00b42a] hover:bg-[#e8ffea] rounded transition-colors"
                            >
                                <Check className="size-3" />
                                接受
                            </button>
                        </div>
                    ) : isApproved ? (
                        <div className="mt-2">
                            <span className={`text-[12px] ${
                                approvalStatus === ApprovalStatus.APPROVED
                                    ? "text-[#00b42a]"
                                    : "text-[#f53f3f]"
                            }`}>
                                {approvalStatus === ApprovalStatus.APPROVED ? "已同意" : "已拒绝"}
                            </span>
                        </div>
                    ) : null}
                </div>

                {/* 删除按钮（Hover 显示） */}
                {isHovered && !showApproval && (
                    <button
                        onClick={() => handleDelete(id)}
                        className="absolute right-6 top-4 flex items-center gap-1 px-2 py-1 text-[12px] text-[#4e5969] hover:text-[#f53f3f] bg-white border border-[#e5e6eb] rounded hover:border-[#f53f3f] transition-colors"
                    >
                        <Trash2 className="size-3" />
                        删除消息
                    </button>
                )}
            </div>
        );
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-[960px] h-[720px] p-0 rounded-2xl shadow-[0_8px_24px_rgba(0,0,0,0.12)]" close={false}>
                {/* 标题栏 */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-[#f2f3f5]">
                    <h2 className="text-[16px] font-semibold text-[#1d2129]">消息提醒</h2>
                    <button
                        onClick={() => onOpenChange?.(false)}
                        className="text-[#86909c] hover:text-[#1d2129] transition-colors"
                    >
                        <X className="size-5" />
                    </button>
                </div>

                {/* Tab 栏 */}
                <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "all" | "request")}>
                    <div className="px-6 pt-4 pb-0">
                        <div className="flex items-center justify-between">
                            <TabsList className="bg-transparent p-0 gap-2">
                                <TabsTrigger
                                    value="all"
                                    className="relative px-4 py-2 rounded-lg text-[14px] data-[state=active]:bg-[#e8f3ff] data-[state=active]:text-[#165dff] data-[state=inactive]:text-[#4e5969]"
                                >
                                    全部
                                    {unreadCounts.all > 0 && (
                                        <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                            {unreadCounts.all}
                                        </span>
                                    )}
                                </TabsTrigger>
                                <TabsTrigger
                                    value="request"
                                    className="relative px-4 py-2 rounded-lg text-[14px] data-[state=active]:bg-[#e8f3ff] data-[state=active]:text-[#165dff] data-[state=inactive]:text-[#4e5969]"
                                >
                                    待审批
                                    {unreadCounts.request > 0 && (
                                        <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                            {unreadCounts.request}
                                        </span>
                                    )}
                                </TabsTrigger>
                            </TabsList>

                            {/* 工具栏 */}
                            <div className="flex items-center gap-3">
                                {/* 搜索框 */}
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#86909c]" />
                                    <Input
                                        type="text"
                                        placeholder="搜索"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="pl-9 pr-3 h-8 w-[200px] text-[14px] bg-[#f7f8fa] border-transparent focus:bg-white focus:border-[#e5e6eb]"
                                    />
                                </div>

                                {/* 仅看未读 */}
                                <div className="flex items-center gap-2">
                                    <span className="text-[14px] text-[#4e5969]">仅看未读</span>
                                    <Switch
                                        checked={onlyUnread}
                                        onCheckedChange={setOnlyUnread}
                                    />
                                </div>

                                {/* 已读全部 */}
                                <Button
                                    onClick={handleMarkAllAsRead}
                                    variant="outline"
                                    className="h-8 px-3 text-[14px] text-[#4e5969] border-[#e5e6eb] hover:bg-[#f7f8fa]"
                                >
                                    已读全部
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* 消息列表 */}
                    <div className="flex-1 overflow-hidden">
                        <TabsContent value="all" className="h-full p-0 m-0">
                            <div className="h-[560px] overflow-y-auto">
                                {loading ? (
                                    <div className="flex items-center justify-center h-full text-[#86909c]">
                                        加载中...
                                    </div>
                                ) : filteredNotifications.length === 0 ? (
                                    <div className="flex items-center justify-center h-full text-[#86909c]">
                                        暂无消息
                                    </div>
                                ) : (
                                    filteredNotifications.map(renderNotificationItem)
                                )}
                            </div>
                        </TabsContent>

                        <TabsContent value="request" className="h-full p-0 m-0">
                            <div className="h-[560px] overflow-y-auto">
                                {loading ? (
                                    <div className="flex items-center justify-center h-full text-[#86909c]">
                                        加载中...
                                    </div>
                                ) : (
                                    <>
                                        {/* 待审批 */}
                                        {requestGroups.pending.length > 0 && (
                                            <div>
                                                <div className="px-6 py-2 bg-[#f7f8fa] text-[12px] text-[#86909c] font-medium">
                                                    待审批
                                                </div>
                                                {requestGroups.pending.map(renderNotificationItem)}
                                            </div>
                                        )}

                                        {/* 已审批 */}
                                        {requestGroups.approved.length > 0 && (
                                            <div className="mt-2">
                                                <div className="px-6 py-2 bg-[#f7f8fa] text-[12px] text-[#86909c] font-medium">
                                                    已审批
                                                </div>
                                                {requestGroups.approved.map(renderNotificationItem)}
                                            </div>
                                        )}

                                        {requestGroups.pending.length === 0 && requestGroups.approved.length === 0 && (
                                            <div className="flex items-center justify-center h-full text-[#86909c]">
                                                暂无请求
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        </TabsContent>
                    </div>
                </Tabs>
            </DialogContent>
        </Dialog>
    );
}
