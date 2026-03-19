import { useEffect, useMemo, useRef, useState } from "react";
import { X, Search, Trash2, Check, XIcon } from "lucide-react";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "~/components/ui/Tabs";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Avatar, AvatarImage } from "~/components/ui/avatar";
import { TooltipAnchor } from "~/components/ui/Tooltip";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import type { MessageItem, MessageTab } from "~/api/message";
import {
    approveMessageApi,
    deleteMessageApi,
    getMessageListApi,
    markAllMessageReadApi,
    markMessageReadApi,
} from "~/api/message";
import { useNavigate } from "react-router-dom";

interface NotificationsDialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
}

export function NotificationsDialog({ open = false, onOpenChange }: NotificationsDialogProps) {
    const [activeTab, setActiveTab] = useState<"all" | "request">("all");
    const [notifications, setNotifications] = useState<MessageItem[]>([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [showSearch, setShowSearch] = useState(false);
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const { showToast } = useToastContext();
    const navigate = useNavigate();
    const listRef = useRef<HTMLDivElement | null>(null);
    const requestHoverTimersRef = useRef<Record<string, number>>({});
    const autoReadTimersRef = useRef<Record<string, number>>({});
    const observersRef = useRef<Record<string, IntersectionObserver>>({});

    const isVisuallyUnread = (n: MessageItem) => !n.is_read;

    // 统计未读数量
    const unreadCounts = useMemo(() => {
        const allUnread = notifications.filter(isVisuallyUnread).length;
        const requestUnread = notifications.filter(
            n => n.message_type === "request" && isVisuallyUnread(n)
        ).length;
        return { all: allUnread, request: requestUnread };
    }, [notifications]);

    const formatBadge = (n: number) => (n > 99 ? "99+" : String(n));

    // 加载消息列表
    const loadNotifications = async (nextPage: number, append: boolean) => {
        setLoading(true);
        try {
            const tab: MessageTab = activeTab === "request" ? "request" : "all";
            const { data, total } = await getMessageListApi({
                tab,
                only_unread: onlyUnread,
                keyword: searchQuery || undefined,
                page: nextPage,
                page_size: 20,
            });

            setNotifications(prev => append ? [...prev, ...data] : data);
            setHasMore((nextPage * 20) < total);
            setPage(nextPage);
        } catch (error) {
            console.error("Failed to load notifications:", error);
        } finally {
            setLoading(false);
        }
    };

    // 初始加载和条件变化时重新加载
    useEffect(() => {
        if (open) {
            setPage(1);
            setHasMore(true);
            loadNotifications(1, false);
        }
    }, [open, activeTab, onlyUnread, searchQuery]);

    // 清理 timers/observers
    useEffect(() => {
        if (!open) return;
        return () => {
            Object.values(requestHoverTimersRef.current).forEach((t) => window.clearTimeout(t));
            Object.values(autoReadTimersRef.current).forEach((t) => window.clearTimeout(t));
            Object.values(observersRef.current).forEach((o) => o.disconnect());
            requestHoverTimersRef.current = {};
            autoReadTimersRef.current = {};
            observersRef.current = {};
        };
    }, [open]);

    // 过滤和排序消息
    const filteredNotifications = useMemo(() => {
        let filtered = notifications;

        // 按时间倒序排列
        filtered = [...filtered].sort((a, b) =>
            new Date(b.create_time).getTime() - new Date(a.create_time).getTime()
        );

        // 仅看未读：只显示黑色字体的消息
        if (onlyUnread) {
            filtered = filtered.filter(isVisuallyUnread);
        }

        return filtered;
    }, [notifications, onlyUnread]);

    // 请求类消息分组
    const requestGroups = useMemo(() => {
        if (activeTab !== "request") return { pending: [], approved: [] };

        const pending = filteredNotifications.filter(
            n => n.message_type === "request" && (n.status === "pending" || n.status === "PENDING")
        );
        const approved = filteredNotifications.filter(
            n => n.message_type === "request" && !(n.status === "pending" || n.status === "PENDING")
        );

        return { pending, approved };
    }, [activeTab, filteredNotifications]);

    // 全部已读
    const handleMarkAllAsRead = async () => {
        try {
            await markAllMessageReadApi();
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
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
            await deleteMessageApi(Number(id));
            setNotifications(prev => prev.filter(n => String(n.id) !== id));
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
        status: "approved" | "rejected"
    ) => {
        try {
            await approveMessageApi({
                message_id: Number(notificationId),
                action: status === "approved" ? "agree" : "reject",
            });
            await markMessageReadApi([Number(notificationId)]);
            setNotifications(prev =>
                prev.map(n =>
                    String(n.id) === notificationId
                        ? { ...n, status, is_read: true }
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
    const getNotificationText = (notification: MessageItem) => {
        const userName = notification.sender_name || "系统";
        const text =
            notification.content?.map((c) => c.content).filter(Boolean).join("") ||
            "";
        const showApproval =
            notification.message_type === "request" &&
            (notification.status === "pending" || notification.status === "PENDING");
        return { text, userName, targetName: "", showApproval };
    };

    // 渲染消息项
    const renderNotificationItem = (notification: MessageItem) => {
        const id = String(notification.id);
        const userName = notification.sender_name;
        const userGroup = "";
        const userAvatar = "";
        const isRead = notification.is_read;
        const createdAt = notification.create_time;
        const approvalStatus = notification.status;
        const { text, targetName, showApproval } = getNotificationText(notification);
        const isHovered = hoveredId === id;

        // 已审批的消息显示为浅色
        const isApproved = approvalStatus && !(approvalStatus === "pending" || approvalStatus === "PENDING");
        const textColor = !isVisuallyUnread(notification) || isApproved ? "text-[#86909c]" : "text-[#1d2129]";

        const markOneAsRead = (nid: string) => {
            markMessageReadApi([Number(nid)]).catch(() => { });
            setNotifications(prev => prev.map(n => String(n.id) === nid ? { ...n, is_read: true } : n));
        };

        const onRowMouseEnter = () => {
            setHoveredId(id);
            // 请求类：hover 0.5s 才已读（滚动不触发）
            if (notification.message_type === "request" && !notification.is_read) {
                window.clearTimeout(requestHoverTimersRef.current[id]);
                requestHoverTimersRef.current[id] = window.setTimeout(() => {
                    markOneAsRead(id);
                }, 500);
            }
        };

        const onRowMouseLeave = () => {
            setHoveredId(null);
            window.clearTimeout(requestHoverTimersRef.current[id]);
            delete requestHoverTimersRef.current[id];
        };

        return (
            <div
                key={id}
                className="flex items-start gap-3 px-6 py-4 border-b border-[#F2F3F5] hover:bg-[#f7f8fa] transition-colors relative"
                onMouseEnter={onRowMouseEnter}
                onMouseLeave={onRowMouseLeave}
                ref={(node) => {
                    // 通知类：进入可视区域停留>0.5s 自动已读
                    if (!node) return;
                    if (notification.message_type !== "notification") return;
                    if (notification.is_read) return;
                    if (!open) return;
                    const root = listRef.current;
                    if (!root) return;

                    if (observersRef.current[id]) return;
                    const obs = new IntersectionObserver(
                        (entries) => {
                            const e = entries[0];
                            if (!e) return;
                            if (e.isIntersecting) {
                                window.clearTimeout(autoReadTimersRef.current[id]);
                                autoReadTimersRef.current[id] = window.setTimeout(() => {
                                    // 再次确认仍未读（期间可能手动已读/全部已读）
                                    const still = notifications.find(n => n.id === id);
                                    if (still && still.message_type === "notification" && !still.is_read) {
                                        markOneAsRead(id);
                                    }
                                }, 500);
                            } else {
                                window.clearTimeout(autoReadTimersRef.current[id]);
                                delete autoReadTimersRef.current[id];
                            }
                        },
                        { root, threshold: 0.6 }
                    );
                    obs.observe(node);
                    observersRef.current[id] = obs;
                }}
            >
                {/* 头像 */}
                <Avatar className="size-9 flex-shrink-0">
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
                                    if (notification.targetType === "channel") {
                                        navigate(`/channel/share/${notification.targetId}`);
                                    } else {
                                        navigate(`/knowledge/share/${notification.targetId}`);
                                    }
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

                    {/* 审批按钮/结果（请求类） */}
                    {showApproval ? (
                        <div className="absolute right-6 bottom-4 flex items-center gap-2">
                            <button
                                onClick={() => {
                                    if (!notification.is_read) markOneAsRead(id);
                                    handleApproval(id, "rejected");
                                }}
                                className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#f53f3f] border border-[#F2F3F5] bg-white hover:bg-[#fff2f0] rounded transition-colors"
                            >
                                <XIcon className="size-3" />
                                拒绝
                            </button>
                            <button
                                onClick={() => {
                                    if (!notification.is_read) markOneAsRead(id);
                                    handleApproval(id, "approved");
                                }}
                                className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#00b42a] border border-[#F2F3F5] bg-white hover:bg-[#e8ffea] rounded transition-colors"
                            >
                                <Check className="size-3" />
                                接受
                            </button>
                        </div>
                    ) : isApproved ? (
                        <div className="absolute right-6 bottom-4">
                            <span className={`text-[12px] ${approvalStatus === "approved"
                                ? "text-[#00b42a]"
                                : "text-[#f53f3f]"
                                }`}>
                                {approvalStatus === "approved" ? "已同意" : "已拒绝"}
                            </span>
                        </div>
                    ) : null}
                </div>

                {/* 删除按钮（Hover 显示） */}
                {isHovered && (
                    <button
                        onClick={() => handleDelete(id)}
                        className="absolute right-6 top-4 flex items-center justify-center p-1.5 text-[#4e5969] hover:text-[#f53f3f] bg-white border border-[#e5e6eb] rounded hover:border-[#f53f3f] transition-colors"
                        title="删除"
                    >
                        <Trash2 className="size-3" />
                    </button>
                )}
            </div>
        );
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-[960px] h-[720px] p-0 rounded-2xl shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                {/* 标题栏 */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-[#f2f3f5]">
                    <h2 className="text-[16px] font-semibold text-[#1d2129]">消息提醒</h2>
                </div>

                {/* Tab 栏 */}
                <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "all" | "request")}>
                    <div className="px-6 pt-4 pb-0">
                        <div className="flex items-center justify-between">
                            <TabsList className="bg-transparent p-0 gap-2">
                                <TabsTrigger
                                    value="all"
                                    className="relative px-4 py-2 rounded-lg text-[14px] border border-transparent data-[state=active]:bg-[#E8F3FF] data-[state=active]:border-[#165DFF] data-[state=active]:text-[#165DFF] data-[state=inactive]:text-[#4E5969]"
                                >
                                    全部
                                    {unreadCounts.all > 0 && (
                                        <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                            {formatBadge(unreadCounts.all)}
                                        </span>
                                    )}
                                </TabsTrigger>
                                <TabsTrigger
                                    value="request"
                                    className="relative px-4 py-2 rounded-lg text-[14px] border border-transparent data-[state=active]:bg-[#E8F3FF] data-[state=active]:border-[#165DFF] data-[state=active]:text-[#165DFF] data-[state=inactive]:text-[#4E5969]"
                                >
                                    审批
                                    {unreadCounts.request > 0 && (
                                        <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                            {formatBadge(unreadCounts.request)}
                                        </span>
                                    )}
                                </TabsTrigger>
                            </TabsList>

                            {/* 工具栏 */}
                            <div className="flex items-center gap-3">
                                {/* 搜索：按图为图标按钮（点击展开输入） */}
                                <button
                                    type="button"
                                    onClick={() => setShowSearch(v => !v)}
                                    className="h-8 w-8 rounded-md border border-[#E5E6EB] bg-white flex items-center justify-center text-[#86909C] hover:text-[#4E5969] hover:bg-[#F7F8FA]"
                                    title="搜索"
                                >
                                    <Search className="size-4" />
                                </button>
                                {showSearch && (
                                    <Input
                                        type="text"
                                        placeholder="搜索"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="h-8 w-[220px] text-[14px] bg-white border-[#E5E6EB]"
                                    />
                                )}

                                {/* 仅看未读：按图为按钮 */}
                                <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => setOnlyUnread(v => !v)}
                                    className={
                                        onlyUnread
                                            ? "h-8 px-3 text-[14px] bg-[#E8F3FF] border-[#165DFF] text-[#165DFF] hover:bg-[#E8F3FF]"
                                            : "h-8 px-3 text-[14px] text-[#4e5969] border-[#e5e6eb] hover:bg-[#f7f8fa]"
                                    }
                                >
                                    仅看未读
                                </Button>

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
                            <div
                                ref={listRef}
                                className="h-[560px] overflow-y-auto"
                                onScroll={(e) => {
                                    const el = e.currentTarget;
                                    if (loadingMore || loading || !hasMore) return;
                                    const threshold = 80;
                                    if (el.scrollTop + el.clientHeight >= el.scrollHeight - threshold) {
                                        setLoadingMore(true);
                                        loadNotifications(page + 1, true).finally(() => setLoadingMore(false));
                                    }
                                }}
                            >
                                {loading ? (
                                    <div className="flex items-center justify-center h-full text-[#86909c]">
                                        加载中...
                                    </div>
                                ) : filteredNotifications.length === 0 ? (
                                    <div className="flex items-center justify-center h-full text-[#86909c]">
                                        暂无消息
                                    </div>
                                ) : (
                                    <>
                                        {filteredNotifications.map(renderNotificationItem)}
                                        {loadingMore && (
                                            <div className="py-3 text-center text-[12px] text-[#86909c]">加载中...</div>
                                        )}
                                        {!hasMore && filteredNotifications.length > 0 && (
                                            <div className="py-3 text-center text-[12px] text-[#c9cdd4]">没有更多消息了</div>
                                        )}
                                    </>
                                )}
                            </div>
                        </TabsContent>

                        <TabsContent value="request" className="h-full p-0 m-0">
                            <div
                                ref={listRef}
                                className="h-[560px] overflow-y-auto"
                                onScroll={(e) => {
                                    const el = e.currentTarget;
                                    if (loadingMore || loading || !hasMore) return;
                                    const threshold = 80;
                                    if (el.scrollTop + el.clientHeight >= el.scrollHeight - threshold) {
                                        setLoadingMore(true);
                                        loadNotifications(page + 1, true).finally(() => setLoadingMore(false));
                                    }
                                }}
                            >
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

                                        {loadingMore && (
                                            <div className="py-3 text-center text-[12px] text-[#86909c]">加载中...</div>
                                        )}
                                        {!hasMore && (requestGroups.pending.length + requestGroups.approved.length) > 0 && (
                                            <div className="py-3 text-center text-[12px] text-[#c9cdd4]">没有更多消息了</div>
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
