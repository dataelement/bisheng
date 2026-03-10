import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeftRightIcon,
    ChevronDown,
    LayoutGridIcon,
    PanelLeftOpenIcon,
    PanelRightOpenIcon,
    Plus
} from "lucide-react";
import { useEffect, useState } from "react";
import { Channel, SortType, getChannelsApi } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import ChannelItem from "./ChannelItem";

interface ChannelSidebarProps {
    activeChannelId?: string;
    onChannelSelect: (channel: Channel | null) => void;
    onCreateChannel: () => void;
    onChannelSquare: () => void;
    onManageMembers: (channel: Channel) => void;
}

function SectionHeader({ title, collapsed, onToggle, sortText, onSort }: any) {
    return (
        <div className="flex items-center justify-between mb-2">
            <button onClick={onToggle} className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]">
                <ChevronDown className={`size-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} />
                {title}
            </button>
            <button onClick={onSort} className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]">
                {sortText}
                <ArrowLeftRightIcon className="size-3" />
            </button>
        </div>
    );
}

export function ChannelSidebar({
    activeChannelId,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    onManageMembers
}: ChannelSidebarProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [subscribedCollapsed, setSubscribedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);

    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const { data: createdChannels = [] } = useQuery({
        queryKey: ["channels", "created", createdSortBy],
        queryFn: () => getChannelsApi({ type: "created", sortBy: createdSortBy })
    });

    const { data: subscribedChannels = [] } = useQuery({
        queryKey: ["channels", "subscribed", subscribedSortBy],
        queryFn: () => getChannelsApi({ type: "subscribed", sortBy: subscribedSortBy })
    });

    // 默认选中第一个频道
    useEffect(() => {
        if (!activeChannelId && createdChannels.length > 0) {
            onChannelSelect(createdChannels[0]);
        }
    }, [activeChannelId, createdChannels, onChannelSelect]);

    const getSortText = (sortType: SortType) => {
        switch (sortType) {
            case SortType.RECENT_UPDATE: return "最近更新";
            case SortType.RECENT_ADDED: return "最近添加";
            case SortType.NAME: return "频道名称";
        }
    };

    const toggleSort = (type: "created" | "subscribed") => {
        const sortTypes = [SortType.RECENT_UPDATE, SortType.RECENT_ADDED, SortType.NAME];
        const currentSort = type === "created" ? createdSortBy : subscribedSortBy;
        const nextSort = sortTypes[(sortTypes.indexOf(currentSort) + 1) % sortTypes.length];
        type === "created" ? setCreatedSortBy(nextSort) : setSubscribedSortBy(nextSort);
    };

    const updateCache = (updater: (channels: Channel[]) => Channel[]) => {
        queryClient.setQueryData(["channels", "created", createdSortBy], (old: Channel[] = []) => updater(old));
        queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => updater(old));
    };

    const handleUpdateChannel = (channel: Channel) => {
        updateCache(channels => channels.map(c => c.id === channel.id ? channel : c));
        if (activeChannelId === channel.id) {
            onChannelSelect(channel);
        }
        showToast({ message: "频道已更新", severity: NotificationSeverity.SUCCESS });
    };

    const handleDeleteChannel = (channelId: string) => {
        let nextActive: Channel | null = null;

        // Update created channels
        queryClient.setQueryData(["channels", "created", createdSortBy], (old: Channel[] = []) => {
            const newData = old.filter(c => c.id !== channelId);
            if (activeChannelId === channelId && newData.length > 0) nextActive = newData[0];
            return newData;
        });

        // If not found in created, check subscribed (or fallback to it)
        if (activeChannelId === channelId && !nextActive) {
            const subscribed = queryClient.getQueryData<Channel[]>(["channels", "subscribed", subscribedSortBy]) || [];
            const newSubscribed = subscribed.filter(c => c.id !== channelId);
            // Update subscribed cache
            queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], newSubscribed);

            if (newSubscribed.length > 0) nextActive = newSubscribed[0];
        } else {
            // Just remove from subscribed
            queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => old.filter(c => c.id !== channelId));
        }

        if (activeChannelId === channelId) {
            onChannelSelect(nextActive);
        }
        showToast({ message: "频道已解散", severity: NotificationSeverity.WARNING });
    };

    const handleUnsubscribeChannel = (channelId: string) => {
        let nextActive: Channel | null = null;
        queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => {
            const newData = old.filter(c => c.id !== channelId);
            if (activeChannelId === channelId && newData.length > 0) nextActive = newData[0];
            return newData;
        });

        if (activeChannelId === channelId) {
            // If we unsubscribed from active, try to find another one, prefer created
            if (!nextActive && createdChannels.length > 0) nextActive = createdChannels[0];
            onChannelSelect(nextActive);
        }
        showToast({ message: "已取消订阅", severity: NotificationSeverity.WARNING });
    };

    const handlePinChannel = (channelId: string, pinned: boolean, type: "created" | "subscribed") => {
        const channels = type === "created" ? createdChannels : subscribedChannels;
        if (pinned && channels.filter(c => c.isPinned).length >= 5) {
            showToast({ message: "已达置顶数量限制", severity: NotificationSeverity.INFO });
            return;
        }

        const updater = (list: Channel[]) => list.map(c => c.id === channelId ? { ...c, isPinned: pinned } : c);
        updateCache(updater);

        if (activeChannelId === channelId) {
            // We need to find the channel to update the active state object
            const channel = channels.find(c => c.id === channelId);
            if (channel) onChannelSelect({ ...channel, isPinned: pinned });
        }
        showToast({ message: pinned ? "已置顶" : "已取消置顶", severity: NotificationSeverity.SUCCESS });
    };

    if (collapsed) {
        return (
            <div className="w-12 h-full bg-white flex items-start justify-center pt-[22px]">
                <Button size="icon" variant="ghost" className="w-5 h-5" onClick={() => setCollapsed(false)}>
                    <PanelLeftOpenIcon className="size-3.5" />
                </Button>
            </div>
        );
    }

    return (
        <div className="w-60 min-w-60 h-full bg-white border-r border-[#e5e6eb] flex flex-col px-3 py-5">
            {/* 顶部操作区 */}
            <div className="border-b border-[#e5e6eb] space-y-4 pb-4">
                <div className="px-2 flex justify-between items-center text-[14px] font-medium">
                    <span>订阅</span>
                    <Button size="icon" variant="ghost" className="w-5 h-5 text-[#86909c]" onClick={() => setCollapsed(true)}>
                        <PanelRightOpenIcon className="size-3.5" />
                    </Button>
                </div>
                <div className="flex items-center gap-3">
                    <Button variant="secondary" onClick={onCreateChannel} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                        <Plus className="size-4" />创建
                    </Button>
                    <Button variant="secondary" onClick={onChannelSquare} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                        <LayoutGridIcon className="size-4" />前往广场
                    </Button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar">
                {/* 我创建的 */}
                <div className="pt-4">
                    <SectionHeader
                        title="我创建的"
                        collapsed={createdCollapsed}
                        onToggle={() => setCreatedCollapsed(!createdCollapsed)}
                        sortText={getSortText(createdSortBy)}
                        onSort={() => toggleSort("created")}
                    />
                    {!createdCollapsed && (
                        <div className="space-y-1">
                            {createdChannels.map(c => (
                                <ChannelItem
                                    key={c.id}
                                    channel={c}
                                    type="created"
                                    isActive={c.id === activeChannelId}
                                    onSelect={onChannelSelect}
                                    onUpdate={handleUpdateChannel}
                                    onDelete={handleDeleteChannel}
                                    onUnsubscribe={handleUnsubscribeChannel}
                                    onPin={handlePinChannel}
                                    onManageMembers={onManageMembers}
                                />
                            ))}
                            {!createdChannels.length && <div className="py-6 text-center text-sm text-[#818181]">暂无数据</div>}
                        </div>
                    )}
                </div>

                {/* 我关注的 */}
                <div className="py-4">
                    <SectionHeader
                        title="我关注的"
                        collapsed={subscribedCollapsed}
                        onToggle={() => setSubscribedCollapsed(!subscribedCollapsed)}
                        sortText={getSortText(subscribedSortBy)}
                        onSort={() => toggleSort("subscribed")}
                    />
                    {!subscribedCollapsed && (
                        <div className="space-y-1">
                            {subscribedChannels.map(c => (
                                <ChannelItem
                                    key={c.id}
                                    channel={c}
                                    type="subscribed"
                                    isActive={c.id === activeChannelId}
                                    onSelect={onChannelSelect}
                                    onUpdate={handleUpdateChannel}
                                    onDelete={handleDeleteChannel}
                                    onUnsubscribe={handleUnsubscribeChannel}
                                    onPin={handlePinChannel}
                                    onManageMembers={onManageMembers}
                                />
                            ))}
                            {!subscribedChannels.length && <div className="py-6 text-center text-sm text-[#818181]">暂无数据</div>}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}