import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Trash2, Check, XIcon } from "lucide-react";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "~/components/ui/Tabs";
import { Button } from "~/components/ui/Button";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
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
import { useTranslation } from "react-i18next";
import { cn } from "~/utils";
import useLocalize, { type TranslationKeys } from "~/hooks/useLocalize";

interface NotificationsDialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
}

const PAGE_SIZE = 20;

function resolveMessageTimeLocale(lang: string) {
    if (lang.startsWith("zh")) return "zh-CN";
    if (lang.startsWith("ja")) return "ja-JP";
    return "en-US";
}

const NOTIFICATION_ACTION_TEXT_KEYS: Record<string, string> = {
    request_channel: "com_notifications_action_request_channel",
    request_knowledge_space: "com_notifications_action_request_knowledge_space",
    approved_channel: "com_notifications_action_approved_channel",
    rejected_channel: "com_notifications_action_rejected_channel",
    approved_knowledge_space: "com_notifications_action_approved_knowledge_space",
    rejected_knowledge_space: "com_notifications_action_rejected_knowledge_space",
    assigned_knowledge_space_admin: "com_notifications_action_assigned_knowledge_space_admin",
    assigned_channel_admin: "com_notifications_action_assigned_channel_admin",
};

export function NotificationsDialog({ open = false, onOpenChange }: NotificationsDialogProps) {
    const localize = useLocalize();
    const { i18n } = useTranslation();
    const formatMessageTime = (createdAt: string) =>
        new Date(createdAt).toLocaleString(resolveMessageTimeLocale(i18n.language), {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });

    const [activeTab, setActiveTab] = useState<"all" | "request">("all");
    const [notifications, setNotifications] = useState<MessageItem[]>([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const isReadAllSelected = !onlyUnread;
    const [showSearch, setShowSearch] = useState(false);
    const [hasSearched, setHasSearched] = useState(false);

    const searchInputRef = useRef<HTMLInputElement | null>(null);
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const { showToast } = useToastContext();
    const navigate = useNavigate();
    const requestHoverTimersRef = useRef<Record<string, number>>({});
    const autoReadTimersRef = useRef<Record<string, number>>({});
    const observersRef = useRef<Record<string, IntersectionObserver>>({});
    const notifyAutoReadTimersRef = useRef<Record<string, number>>({});
    const [isScrolling, setIsScrolling] = useState(false);
    const scrollHideTimerRef = useRef<number | null>(null);

    const isVisuallyUnread = (n: MessageItem) => !n.is_read;
    const isKnowledgeSpaceApprovalActionCode = (actionCode?: string) =>
        actionCode === "request_knowledge_space" ||
        actionCode === "approved_knowledge_space" ||
        actionCode === "rejected_knowledge_space";
    const isApprovalMessageType = (messageType?: string, actionCode?: string) =>
        messageType === "request" || messageType === "approve" || isKnowledgeSpaceApprovalActionCode(actionCode);
    const isPendingApprovalStatus = (status?: string) =>
        !!status && ["pending", "PENDING", "wait_approve", "WAIT_APPROVE"].includes(status);
    const isApprovedStatus = (status?: string) =>
        !!status && ["approved", "APPROVED"].includes(status);
    const isRejectedStatus = (status?: string) =>
        !!status && ["rejected", "REJECTED"].includes(status);
    const isDecisionActionCode = (actionCode?: string) =>
        !!actionCode && /(approve|approved|reject|rejected)/i.test(actionCode);
    const isNotifyMessageType = (messageType?: string) =>
        messageType === "notify" || messageType === "notification";
    const isSelfApplicationDecisionActionCode = (actionCode?: string) =>
        actionCode === "approved_channel" ||
        actionCode === "rejected_channel" ||
        actionCode === "approved_knowledge_space" ||
        actionCode === "rejected_knowledge_space";

    const scanAndScheduleNotifyAutoRead = () => {
        const root =
            document.querySelector<HTMLDivElement>("[data-message-scroll-root='true'][data-active='true']") ??
            document.querySelector<HTMLDivElement>("[data-message-scroll-root='true']");
        if (!root) return;

        const rootRect = root.getBoundingClientRect();
        const nodes = Array.from(root.querySelectorAll<HTMLElement>("[data-message-id]"));
        for (const node of nodes) {
            const id = node.getAttribute("data-message-id") || "";
            const type = node.getAttribute("data-message-type") || "";
            if (!id) continue;
            if (!isNotifyMessageType(type)) continue;

            const item = notifications.find((n) => String(n.id) === id);
            if (!item || item.is_read) continue;

            const r = node.getBoundingClientRect();
            const visibleHeight = Math.min(r.bottom, rootRect.bottom) - Math.max(r.top, rootRect.top);
            const visibleRatio = visibleHeight / Math.max(1, r.height);
            if (visibleRatio < 0.6) continue;

            if (notifyAutoReadTimersRef.current[id]) continue;
            notifyAutoReadTimersRef.current[id] = window.setTimeout(() => {
                const still = notifications.find((n) => String(n.id) === id);
                if (!still || still.is_read) {
                    window.clearTimeout(notifyAutoReadTimersRef.current[id]);
                    delete notifyAutoReadTimersRef.current[id];
                    return;
                }
                markMessageReadApi([Number(id)]).catch(() => { });
                setNotifications(prev => prev.map(n => String(n.id) === id ? { ...n, is_read: true } : n));
                window.clearTimeout(notifyAutoReadTimersRef.current[id]);
                delete notifyAutoReadTimersRef.current[id];
            }, 500);
        }
    };

    const unreadCounts = useMemo(() => {
        const allUnread = notifications.filter(isVisuallyUnread).length;
        const requestUnread = notifications.filter(
            n => isApprovalMessageType(n.message_type, n.action_code) && isVisuallyUnread(n)
        ).length;
        return { all: allUnread, request: requestUnread };
    }, [notifications]);

    const formatBadge = (n: number) => (n > 99 ? "99+" : String(n));

    const loadNotifications = async (nextPage: number, append: boolean) => {
        setLoading(true);
        try {
            const tab: MessageTab = activeTab === "request" ? "request" : "all";
            const { data, total } = await getMessageListApi({
                tab,
                only_unread: onlyUnread,
                keyword: searchQuery || undefined,
                page: nextPage,
                page_size: PAGE_SIZE,
            });

            setNotifications(prev => append ? [...prev, ...data] : data);
            setHasMore((nextPage * PAGE_SIZE) < total);
            setPage(nextPage);
        } catch (error) {
            console.error("Failed to load notifications:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (open) {
            setPage(1);
            setHasMore(true);
            loadNotifications(1, false);
        }
    }, [open, activeTab, onlyUnread, searchQuery]);

    useEffect(() => {
        if (!open) return;
        return () => {
            Object.values(requestHoverTimersRef.current).forEach((t) => window.clearTimeout(t));
            Object.values(autoReadTimersRef.current).forEach((t) => window.clearTimeout(t));
            Object.values(observersRef.current).forEach((o) => o.disconnect());
            Object.values(notifyAutoReadTimersRef.current).forEach((t) => window.clearTimeout(t));
            requestHoverTimersRef.current = {};
            autoReadTimersRef.current = {};
            observersRef.current = {};
            notifyAutoReadTimersRef.current = {};
        };
    }, [open]);

    // When switching tab / filters, the list DOM is re-created; reconnect observers.
    useEffect(() => {
        Object.values(observersRef.current).forEach((o) => o.disconnect());
        observersRef.current = {};
    }, [activeTab, onlyUnread, searchQuery]);

    // Fallback: proactively scan visible notify messages after render.
    useEffect(() => {
        if (!open) return;
        if (loading) return;
        if (!notifications.length) return;
        const t = window.setTimeout(() => {
            scanAndScheduleNotifyAutoRead();
        }, 80);
        return () => window.clearTimeout(t);
    }, [open, loading, notifications]);

    const filteredNotifications = useMemo(() => {
        let filtered = notifications;
        filtered = [...filtered].sort((a, b) =>
            new Date(b.create_time).getTime() - new Date(a.create_time).getTime()
        );
        if (onlyUnread) {
            filtered = filtered.filter(isVisuallyUnread);
        }
        return filtered;
    }, [notifications, onlyUnread]);

    const requestGroups = useMemo(() => {
        if (activeTab !== "request") return { pending: [], approved: [] };
        const pending = filteredNotifications.filter(
            n => isApprovalMessageType(n.message_type, n.action_code) && isPendingApprovalStatus(n.status)
        );
        const approved = filteredNotifications.filter(
            n => isApprovalMessageType(n.message_type, n.action_code) && !isPendingApprovalStatus(n.status)
        );
        return { pending, approved };
    }, [activeTab, filteredNotifications]);

    const handleMarkAllAsRead = async () => {
        try {
            await markAllMessageReadApi();
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
            showToast({ message: localize("com_notifications_toast_all_read"), severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: localize("com_notifications_toast_operation_failed"), severity: NotificationSeverity.INFO });
        }
    };

    const handleDelete = async (id: string) => {
        try {
            await deleteMessageApi(Number(id));
            setNotifications(prev => prev.filter(n => String(n.id) !== id));
            showToast({ message: localize("com_notifications_toast_deleted"), severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: localize("com_notifications_toast_delete_failed"), severity: NotificationSeverity.INFO });
        }
    };

    const handleApproval = async (notificationId: string, status: "approved" | "rejected") => {
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
            showToast({ message: localize("com_notifications_toast_success"), severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: localize("com_notifications_toast_operation_failed"), severity: NotificationSeverity.INFO });
        }
    };

    const getTargetName = (notification: MessageItem): string => {
        const parts = Array.isArray(notification.content) ? notification.content : [];
        const businessUrlPart = parts.find((c: any) => c?.type === "business_url") as any;

        const rawBusinessName = typeof businessUrlPart?.content === "string" ? businessUrlPart.content.trim() : "";
        if (rawBusinessName) {
            const cleaned = rawBusinessName.replace(/^[-—\s]+/, "").trim();
            if (cleaned) return cleaned;
        }

        const businessPart = parts.find((c: any) =>
            c?.type === "business" ||
            c?.type === "business_name" ||
            c?.type === "target" ||
            c?.type === "title"
        ) as any;
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

    const getSystemTextCode = (notification: MessageItem): string => {
        const parts = Array.isArray(notification.content) ? notification.content : [];
        const part = parts.find((c: any) => c?.type === "system_text");
        const code = part?.content;
        if (typeof code === "string" && code.trim()) return code.trim();
        return notification.action_code || "";
    };

    const getNotificationText = (notification: MessageItem) => {
        const targetName = getTargetName(notification);
        const actionCode = getSystemTextCode(notification);
        const actionTextKey = NOTIFICATION_ACTION_TEXT_KEYS[actionCode];
        const fallbackText = notification.content?.map((c) => c.content).filter(Boolean).join("") || "";
        const text = actionTextKey
            ? localize(actionTextKey as TranslationKeys, { target: targetName })
            : fallbackText;
        const showApproval =
            isApprovalMessageType(notification.message_type, notification.action_code) &&
            isPendingApprovalStatus(notification.status);
        return { text, targetName, showApproval };
    };

    const getNotificationTarget = (notification: MessageItem): { targetType: "channel" | "space"; targetId: string } | null => {
        const allBusinessParts = (notification.content ?? []).filter((c: any) => c?.type === "business_url") as any[];
        const systemText = String(notification.content?.find((c: any) => c?.type === "system_text")?.content ?? "");

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

        const meta = part?.metadata as any;
        const businessType = meta?.business_type;
        const data = meta?.data || {};
        const actionCode = String(notification.action_code ?? "");

        const pickId = (...vals: any[]) => {
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

        if (businessType === "channel_id" && data?.channel_id) {
            return { targetType: "channel", targetId: String(data.channel_id) };
        }
        if (businessType === "channel") {
            const channelId = data?.channel_id ?? data?.business_id ?? (notification as any)?.business_id;
            if (channelId !== undefined && channelId !== null && String(channelId) !== "") {
                return { targetType: "channel", targetId: String(channelId) };
            }
        }
        if (businessType === "space_id" && data?.space_id) {
            return { targetType: "space", targetId: String(data.space_id) };
        }
        if (businessType === "space") {
            const spaceId = data?.space_id ?? data?.business_id ?? (notification as any)?.business_id;
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
                (notification as any)?.business_id
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
                (notification as any)?.business_id
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

    const markOneAsRead = (nid: string) => {
        markMessageReadApi([Number(nid)]).catch(() => { });
        setNotifications(prev => prev.map(n => String(n.id) === nid ? { ...n, is_read: true } : n));
    };

    const renderNotificationItem = (notification: MessageItem) => {
        const id = String(notification.id);
        const userPart = notification.content?.find((c: any) => c?.type === "user") as any;
        const userMeta = (userPart?.metadata ?? {}) as any;
        const rawName = notification.sender_name || userPart?.content || "";
        const userName = String(rawName).replace(/^@/, "");
        const groupNamesRaw =
            userMeta?.group_names ??
            userMeta?.groupNames ??
            userMeta?.group_name ??
            userMeta?.groupName ??
            [];
        const groupNames = Array.isArray(groupNamesRaw)
            ? groupNamesRaw.map((g: any) => String(g)).filter(Boolean)
            : String(groupNamesRaw ? groupNamesRaw : "")
                .split(/[,/]/)
                .map((g) => g.trim())
                .filter(Boolean);
        const userGroup = groupNames.join(" / ");
        const userAvatar = userMeta?.avatar || userMeta?.user_avatar || "";
        const createdAt = notification.create_time;
        const approvalStatus = notification.status;
        const { text, targetName, showApproval } = getNotificationText(notification);
        const canSplitTarget = Boolean(targetName) && text.includes(targetName);
        const textPrefix = canSplitTarget ? text.split(targetName)[0] : text;
        const isHovered = hoveredId === id;

        const isApproved = isApprovedStatus(approvalStatus) || isRejectedStatus(approvalStatus);
        const isSelfApplicationDecision = isSelfApplicationDecisionActionCode(notification.action_code);
        const isNotifyMessage = isNotifyMessageType(notification.message_type);
        const isApprovalMessage = isApprovalMessageType(notification.message_type, notification.action_code);
        const isPendingApproval = isPendingApprovalStatus(approvalStatus);
        const approvalDecisionLabel = isApprovedStatus(approvalStatus)
            ? localize("com_notifications_approved")
            : isRejectedStatus(approvalStatus)
                ? localize("com_notifications_rejected")
                : null;

        const showDeleteOnHover =
            !showApproval &&
            !isApprovalMessage &&
            (isApproved || isDecisionActionCode(notification.action_code));

        const textColor = !isVisuallyUnread(notification) || isApproved ? "text-[#989898]" : "text-[#1d2129]";

        const onRowMouseEnter = () => {
            setHoveredId(id);
            // 请求类：hover 0.5s 才已读（滚动不触发）
            if (isApprovalMessageType(notification.message_type, notification.action_code) && !notification.is_read) {
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

        const rightSlot = (() => {
            // 通知类：未 hover 显示时间，hover 显示删除按钮（居中）
            if (isNotifyMessage) {
                if (!isHovered) return <span className="text-[14px] text-[#999999]">{formatMessageTime(createdAt)}</span>;
                return (
                    <button
                        type="button"
                        onClick={() => handleDelete(id)}
                        className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#4e5969] bg-white border border-[#e5e6eb] rounded hover:text-[#f53f3f] hover:border-[#f53f3f] transition-colors"
                        title={localize("com_notifications_delete")}
                    >
                        <Trash2 className="size-3" />
                        {localize("com_notifications_delete")}
                    </button>
                );
            }

            // 审批类：未 hover 显示时间，hover 显示删除按钮
            if (isApprovalMessage) {
                if (!isHovered) return <span className="text-[14px] text-[#999999]">{formatMessageTime(createdAt)}</span>;
                return (
                    <button
                        type="button"
                        onClick={() => handleDelete(id)}
                        className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#4e5969] bg-white border border-[#e5e6eb] rounded hover:text-[#f53f3f] hover:border-[#f53f3f] transition-colors"
                        title={localize("com_notifications_delete")}
                    >
                        <Trash2 className="size-3" />
                        {localize("com_notifications_delete")}
                    </button>
                );
            }

            // 其它类型：hover 且满足条件时显示删除按钮，否则显示时间
            if (isHovered && showDeleteOnHover && !isSelfApplicationDecision) {
                return (
                    <button
                        type="button"
                        onClick={() => handleDelete(id)}
                        className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#4e5969] bg-white border border-[#e5e6eb] rounded hover:text-[#f53f3f] hover:border-[#f53f3f] transition-colors"
                        title={localize("com_notifications_delete")}
                    >
                        <Trash2 className="size-3" />
                        {localize("com_notifications_delete")}
                    </button>
                );
            }
            return <span className="text-[14px] text-[#999999]">{formatMessageTime(createdAt)}</span>;
        })();

        return (
            <div
                key={id}
                data-message-id={id}
                data-message-type={notification.message_type}
                className="relative px-6 py-4 border-b border-[#F2F3F5] hover:bg-[#f7f8fa] transition-colors"
                onMouseEnter={onRowMouseEnter}
                onMouseLeave={onRowMouseLeave}
                ref={(node) => {
                    // 通知类：进入可视区域停留>0.5s 自动已读
                    if (!node) return;
                    if (!isNotifyMessageType(notification.message_type)) return;
                    if (notification.is_read) return;
                    if (!open) return;
                    if (observersRef.current[id]) return;
                    const root =
                        (node.closest("[data-message-scroll-root='true']") as HTMLDivElement | null) ??
                        null;
                    const obs = new IntersectionObserver(
                        (entries) => {
                            const e = entries[0];
                            if (!e) return;
                            if (e.isIntersecting) {
                                window.clearTimeout(autoReadTimersRef.current[id]);
                                autoReadTimersRef.current[id] = window.setTimeout(() => {
                                    const still = notifications.find(n => n.id === Number(id));
                                    if (still && isNotifyMessageType(still.message_type) && !still.is_read) {
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
                <div className="flex items-start gap-3">
                    <Avatar className="size-9 flex-shrink-0">
                        {userAvatar ? <AvatarImage src={userAvatar} alt={userName} /> : null}
                        <AvatarName name={userName} className="text-xs" />
                    </Avatar>

                    <div className="flex-1 min-w-0">
                        <div className="flex items-center min-w-0 whitespace-nowrap min-h-9 text-[14px]">
                            <TooltipAnchor
                                description={userGroup ? `${userName} - ${userGroup}` : userName}
                                side="top"
                            >
                                <span className={cn("font-medium cursor-pointer hover:text-[#165dff] shrink-0", textColor)}>
                                    @{userName}
                                </span>
                            </TooltipAnchor>
                            <span className="mx-1 shrink-0"> </span>
                            <span className={cn("min-w-0 overflow-hidden text-ellipsis whitespace-nowrap", textColor)}>
                                {textPrefix}
                                {canSplitTarget && (
                                    <span
                                        className="font-medium cursor-pointer hover:text-[#165dff]"
                                        onClick={() => {
                                            const target = getNotificationTarget(notification);
                                            if (!target) return;
                                            if (target.targetType === "channel") {
                                                    navigate(`/channel/${target.targetId}`);
                                            } else {
                                                    navigate(`/knowledge/space/${target.targetId}`);
                                            }
                                                onOpenChange?.(false);
                                        }}
                                    >
                                        {targetName}
                                    </span>
                                )}
                            </span>
                        </div>

                    </div>

                    <div
                        className={cn(
                            "flex-shrink-0 whitespace-nowrap flex flex-col items-end",
                            isNotifyMessage ? "self-center" : "self-start"
                        )}
                    >
                        <div>{rightSlot}</div>
                        {showApproval ? (
                            <div className="mt-2 flex items-center justify-end gap-2">
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (!notification.is_read) markOneAsRead(id);
                                        handleApproval(id, "rejected");
                                    }}
                                    className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#f53f3f] border border-[#F2F3F5] bg-white hover:bg-[#fff2f0] rounded transition-colors"
                                >
                                    <XIcon className="size-3" />
                                    {localize("com_notifications_reject")}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (!notification.is_read) markOneAsRead(id);
                                        handleApproval(id, "approved");
                                    }}
                                    className="flex items-center gap-1 px-3 py-1 text-[12px] text-[#00b42a] border border-[#F2F3F5] bg-white hover:bg-[#e8ffea] rounded transition-colors"
                                >
                                    <Check className="size-3" />
                                    {localize("com_notifications_accept")}
                                </button>
                            </div>
                        ) : (isApprovalMessage && !isPendingApproval && approvalDecisionLabel) ? (
                            <div className="mt-2 flex items-center justify-end">
                                <button
                                    type="button"
                                    disabled
                                    className={cn(
                                        "flex items-center gap-1 px-3 py-1 text-[12px] border rounded cursor-default",
                                        isApprovedStatus(approvalStatus)
                                            ? "text-[#4e5969] border-[#E5E6EB] bg-white"
                                            : "text-[#f53f3f] border-[#F2F3F5] bg-[#fff2f0]"
                                    )}
                                >
                                    {isApprovedStatus(approvalStatus) ? <Check className="size-3" /> : <XIcon className="size-3" />}
                                    {approvalDecisionLabel}
                                </button>
                            </div>
                        ) : null}
                    </div>
                </div>

                {/* 自己申请结果：固定展示删除按钮（中间） */}
                {isSelfApplicationDecision && (
                    <button
                        onClick={() => handleDelete(id)}
                        className="absolute right-6 top-1/2 -translate-y-1/2 flex items-center gap-1 px-3 py-1 text-[12px] text-[#4e5969] bg-white border border-[#e5e6eb] rounded hover:text-[#f53f3f] hover:border-[#f53f3f] transition-colors"
                        title={localize("com_notifications_delete")}
                    >
                        <Trash2 className="size-3" />
                        {localize("com_notifications_delete")}
                    </button>
                )}
            </div>
        );
    };

    const handleListScroll = (el: HTMLDivElement) => {
        setIsScrolling(true);
        if (scrollHideTimerRef.current) window.clearTimeout(scrollHideTimerRef.current);
        scrollHideTimerRef.current = window.setTimeout(() => setIsScrolling(false), 700);

        if (loadingMore || loading || !hasMore) return;
        const threshold = 80;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - threshold) {
            setLoadingMore(true);
            loadNotifications(page + 1, true).finally(() => setLoadingMore(false));
        }

        // notify: scroll triggers scan (0.5s in-view rule)
        scanAndScheduleNotifyAutoRead();
    };

    const listEmpty = !loading && filteredNotifications.length === 0;
    const requestEmpty =
        !loading && requestGroups.pending.length === 0 && requestGroups.approved.length === 0;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="w-[calc(100vw-80px)] max-w-[800px] h-[80vh] max-h-[800px] p-0 gap-0 rounded-2xl shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                <div className="flex flex-col h-full overflow-hidden rounded-2xl">
                    <div className="flex items-center justify-between h-12 px-6 flex-shrink-0">
                        <h2 className="text-[16px] font-semibold text-[#1d2129]">{localize("com_notifications_title")}</h2>
                    </div>

                    <Tabs
                        value={activeTab}
                        onValueChange={(v) => setActiveTab(v as "all" | "request")}
                        className="flex flex-col flex-1 min-h-0"
                    >
                        <div className="flex flex-col flex-1 min-h-0">
                            <div className="px-6 pt-4 pb-0 flex-shrink-0">
                                <div className="flex items-center justify-between">
                                    <TabsList className="bg-transparent p-0 gap-2">
                                        <TabsTrigger
                                            value="all"
                                            className="relative !w-[60px] !min-w-[60px] !h-8 !px-0 !py-0 !rounded-[8px] flex items-center justify-center text-[14px] border border-transparent
                                        data-[state=active]:bg-[#E6EDFC] data-[state=active]:border-[#E6EDFC] data-[state=active]:text-[#024DE3]
                                        data-[state=inactive]:text-[#4E5969] data-[state=inactive]:bg-transparent"
                                        >
                                            {localize("com_notifications_tab_all")}
                                            {unreadCounts.all > 0 && (
                                                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                                    {formatBadge(unreadCounts.all)}
                                                </span>
                                            )}
                                        </TabsTrigger>
                                        <TabsTrigger
                                            value="request"
                                            className="relative !w-[60px] !min-w-[60px] !h-8 !px-0 !py-0 !rounded-[8px] flex items-center justify-center text-[14px] border border-transparent
                                        data-[state=active]:bg-[#E6EDFC] data-[state=active]:border-[#E6EDFC] data-[state=active]:text-[#024DE3]
                                        data-[state=inactive]:text-[#4E5969] data-[state=inactive]:bg-transparent"
                                        >
                                            {localize("com_notifications_tab_request")}
                                            {unreadCounts.request > 0 && (
                                                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 bg-[#f53f3f] text-white text-[11px] rounded-full flex items-center justify-center">
                                                    {formatBadge(unreadCounts.request)}
                                                </span>
                                            )}
                                        </TabsTrigger>
                                    </TabsList>

                                    <div className="flex items-center gap-3">
                                        <div
                                            className={[
                                                "flex items-center h-8 rounded-lg border bg-white overflow-hidden",
                                                "transition-[width,border-color] duration-[350ms] ease-in-out",
                                                showSearch
                                                    ? "w-[220px] border-[#024DE3]"
                                                    : "w-8 border-[#E5E6EB] cursor-pointer hover:bg-[#F7F8FA]",
                                            ].join(" ")}
                                            onClick={() => {
                                                if (!showSearch) {
                                                    setShowSearch(true);
                                                    requestAnimationFrame(() => searchInputRef.current?.focus());
                                                }
                                            }}
                                            title={showSearch ? undefined : localize("com_notifications_search")}
                                        >
                                            <div
                                                className={[
                                                    "flex items-center justify-center px-[7px] h-full shrink-0 transition-colors duration-[350ms] ease-in-out",
                                                    showSearch ? "text-[#024DE3]" : "text-[#86909C]",
                                                ].join(" ")}
                                            >
                                                <Search className="size-4" />
                                            </div>
                                            <input
                                                ref={searchInputRef}
                                                type="text"
                                                placeholder={localize("com_notifications_search_placeholder")}
                                                value={searchQuery}
                                                onChange={(e) => setSearchQuery(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter" && searchQuery.trim()) setHasSearched(true);
                                                }}
                                                onBlur={() => {
                                                    // Keep the search box open as long as there is content.
                                                    // Only collapse when the user clears it.
                                                    if (!searchQuery.trim()) {
                                                        setShowSearch(false);
                                                        setSearchQuery("");
                                                        setHasSearched(false);
                                                    }
                                                }}
                                                tabIndex={showSearch ? 0 : -1}
                                                style={{ fontWeight: 400 }}
                                                className={[
                                                    "flex-1 h-full pr-3 text-[14px] font-normal text-[#1d2129] bg-transparent outline-none placeholder:text-[#C9CDD4] placeholder:font-normal",
                                                    "transition-opacity duration-[350ms] ease-in-out",
                                                    showSearch ? "opacity-100" : "opacity-0 pointer-events-none",
                                                ].join(" ")}
                                            />
                                        </div>

                                        <Button
                                            type="button"
                                            variant="outline"
                                            onClick={() => setOnlyUnread((v) => !v)}
                                            className={
                                                onlyUnread
                                                    ? "!w-[88px] !h-8 !px-0 text-[14px] !rounded-[8px] bg-[#E6EDFC] border-[#E6EDFC] text-[#024DE3] hover:bg-[#E6EDFC] flex items-center justify-center"
                                                    : "!w-[88px] !h-8 !px-0 text-[14px] !rounded-[8px] bg-white border-[#e5e6eb] text-[#4e5969] hover:bg-[#f7f8fa] flex items-center justify-center"
                                            }
                                        >
                                            {localize("com_notifications_unread_only")}
                                        </Button>

                                        <Button
                                            onClick={() => {
                                                setOnlyUnread(false);
                                                handleMarkAllAsRead();
                                            }}
                                            variant="outline"
                                            className={
                                                isReadAllSelected
                                                    ? "!w-[88px] !h-8 !px-0 text-[14px] !rounded-[8px] bg-[#E6EDFC] border-[#E6EDFC] text-[#024DE3] hover:bg-[#E6EDFC] flex items-center justify-center"
                                                    : "!w-[88px] !h-8 !px-0 text-[14px] !rounded-[8px] bg-white border-[#e5e6eb] text-[#4e5969] hover:bg-[#f7f8fa] flex items-center justify-center"
                                            }
                                        >
                                            {localize("com_notifications_mark_all_read")}
                                        </Button>
                                    </div>
                                </div>
                            </div>

                            <div className="flex-1 overflow-hidden min-h-0 px-6 pb-4">
                                <TabsContent forceMount value="all" className="h-full p-0 m-0 data-[state=inactive]:hidden">
                                    <div
                                        data-message-scroll-root="true"
                                        data-active={activeTab === "all" ? "true" : "false"}
                                        className="h-full overflow-y-scroll chrome-scrollbar scrollbar-gutter-stable"
                                        onScroll={(e) => handleListScroll(e.currentTarget)}
                                    >
                                        {loading ? (
                                            <div className="flex items-center justify-center h-full text-[#86909c]">{localize("com_notifications_loading")}</div>
                                        ) : listEmpty ? (
                                            <div className="flex items-center justify-center h-full text-[#86909c]">{localize("com_notifications_empty")}</div>
                                        ) : (
                                            <>
                                                <div className="divide-y divide-[#F2F3F5]">
                                                    {filteredNotifications.map(renderNotificationItem)}
                                                </div>
                                                {loadingMore && (
                                                    <div className="py-3 text-center text-[12px] text-[#86909c]">{localize("com_notifications_loading")}</div>
                                                )}
                                                {!hasMore && filteredNotifications.length > 0 && (
                                                    <div className="py-3 text-center text-[12px] text-[#c9cdd4]">{localize("com_notifications_no_more")}</div>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </TabsContent>

                                <TabsContent forceMount value="request" className="h-full p-0 m-0 data-[state=inactive]:hidden">
                                    <div
                                        data-message-scroll-root="true"
                                        data-active={activeTab === "request" ? "true" : "false"}
                                        className="h-full overflow-y-scroll chrome-scrollbar scrollbar-gutter-stable"
                                        onScroll={(e) => handleListScroll(e.currentTarget)}
                                    >
                                        {loading ? (
                                            <div className="flex items-center justify-center h-full text-[#86909c]">{localize("com_notifications_loading")}</div>
                                        ) : requestEmpty ? (
                                            <div className="flex items-center justify-center h-full text-[#86909c]">{localize("com_notifications_empty_requests")}</div>
                                        ) : (
                                            <>
                                                {requestGroups.pending.length > 0 && (
                                                    <div className="mb-3">
                                                        <div className="px-6 py-2 text-[12px] text-[#86909c] font-medium">{localize("com_notifications_section_pending")}</div>
                                                        <div className="divide-y divide-[#F2F3F5]">
                                                            {requestGroups.pending.map(renderNotificationItem)}
                                                        </div>
                                                    </div>
                                                )}

                                                {requestGroups.approved.length > 0 && (
                                                    <div className="mt-2">
                                                        <div className="px-6 py-2 text-[12px] text-[#86909c] font-medium">{localize("com_notifications_section_reviewed")}</div>
                                                        <div className="divide-y divide-[#F2F3F5]">
                                                            {requestGroups.approved.map(renderNotificationItem)}
                                                        </div>
                                                    </div>
                                                )}
                                                {loadingMore && (
                                                    <div className="py-3 text-center text-[12px] text-[#86909c]">{localize("com_notifications_loading")}</div>
                                                )}
                                                {!hasMore && (requestGroups.pending.length + requestGroups.approved.length) > 0 && (
                                                    <div className="py-3 text-center text-[12px] text-[#c9cdd4]">{localize("com_notifications_no_more")}</div>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </TabsContent>
                            </div>
                        </div>
                    </Tabs>
                </div>
            </DialogContent>
        </Dialog>
    );
}
