import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    LayoutGridIcon,
    PanelLeftOpenIcon,
    PanelRightOpenIcon,
    Plus
} from "lucide-react";
import { useEffect, useState } from "react";
import {
    Channel,
    SortType,
    getChannelsApi,
} from "~/api/channels";
import { Button } from "~/components/ui/Button";
import ChannelItem from "./ChannelItem";
import { SectionHeader } from "./SectionHeader";
import { useChannelActions } from "../hooks/useChannelActions";

interface ChannelSidebarProps {
    activeChannelId?: string;
    onChannelSelect: (channel: Channel | null) => void;
    onCreateChannel: () => void;
    onChannelSquare: () => void;
    onManageMembers: (channel: Channel) => void;
    onChannelSettings: (channel: Channel) => void;
    /** Report created channel count back to parent so it doesn't need a duplicate query */
    onCreatedCountChange?: (count: number) => void;
}

export function ChannelSidebar({
    activeChannelId,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    onManageMembers,
    onChannelSettings,
    onCreatedCountChange,
}: ChannelSidebarProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [subscribedCollapsed, setSubscribedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);

    const queryClient = useQueryClient();

    const { data: createdChannels = [] } = useQuery({
        queryKey: ["channels", "created", createdSortBy],
        queryFn: () => getChannelsApi({ type: "created", sortBy: createdSortBy }),
        placeholderData: (prev) => prev,
    });

    const { data: subscribedChannels = [] } = useQuery({
        queryKey: ["channels", "subscribed", subscribedSortBy],
        queryFn: () => getChannelsApi({ type: "subscribed", sortBy: subscribedSortBy }),
        placeholderData: (prev) => prev,
    });

    // Channel CRUD operations (optimistic updates)
    const {
        handleUpdateChannel,
        handleDeleteChannel,
        handleUnsubscribeChannel,
        handlePinChannel,
    } = useChannelActions({
        activeChannelId,
        createdSortBy,
        subscribedSortBy,
        createdChannels,
        subscribedChannels,
        onChannelSelect,
    });

    // Default select first channel
    useEffect(() => {
        if (!activeChannelId) {
            if (createdChannels.length > 0) {
                onChannelSelect(createdChannels[0]);
            } else if (subscribedChannels.length > 0) {
                onChannelSelect(subscribedChannels[0]);
            }
        }
    }, [activeChannelId, createdChannels, onChannelSelect]);

    // Notify parent of created channel count changes
    useEffect(() => {
        onCreatedCountChange?.(createdChannels.length);
    }, [createdChannels.length, onCreatedCountChange]);

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

        if (type === "created") {
            queryClient.removeQueries({ queryKey: ["channels", "created", currentSort] });
            setCreatedSortBy(nextSort);
        } else {
            queryClient.removeQueries({ queryKey: ["channels", "subscribed", currentSort] });
            setSubscribedSortBy(nextSort);
        }
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
                                    onChannelSettings={onChannelSettings}
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
                                    onChannelSettings={onChannelSettings}
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