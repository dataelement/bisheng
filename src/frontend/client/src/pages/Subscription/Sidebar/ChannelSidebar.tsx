import { useLocalize } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    PanelLeftOpenIcon,
    PanelRightOpenIcon,
    Plus
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
    Channel,
    SortType,
    getChannelsApi,
} from "~/api/channels";
import { Button } from "~/components/ui/Button";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";
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
    const localize = useLocalize();
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [subscribedCollapsed, setSubscribedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const queryClient = useQueryClient();

    const { data: createdChannels = [], isFetched: createdFetched } = useQuery({
        queryKey: ["channels", "created", createdSortBy],
        queryFn: () => getChannelsApi({ type: "created", sortBy: createdSortBy }),
        placeholderData: (prev) => prev,
    });

    const { data: subscribedChannels = [], isFetched: subscribedFetched } = useQuery({
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

    // Default select first channel — wait until both queries have completed
    useEffect(() => {
        if (!activeChannelId && createdFetched && subscribedFetched) {
            if (createdChannels.length > 0) {
                onChannelSelect(createdChannels[0]);
            } else if (subscribedChannels.length > 0) {
                onChannelSelect(subscribedChannels[0]);
            }
        }
    }, [activeChannelId, createdChannels, subscribedChannels, createdFetched, subscribedFetched, onChannelSelect]);

    // Notify parent of created channel count changes
    useEffect(() => {
        onCreatedCountChange?.(createdChannels.length);
    }, [createdChannels.length, onCreatedCountChange]);

    const getSortText = (sortType: SortType) => {
        switch (sortType) {
            case SortType.RECENT_UPDATE: return localize("com_subscription.recently_updated");
            case SortType.RECENT_ADDED: return localize("com_subscription.recently_added");
            case SortType.NAME: return localize("com_subscription.channel_name");
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

    const handleListScroll = () => {
        setIsListScrolling(true);
        if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
        listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
    };

    return (
        <div
            className={[
                "h-full bg-white border-r border-[#e5e6eb] flex flex-col overflow-hidden flex-shrink-0",
                "transition-[width] duration-[350ms] ease-in-out",
                collapsed ? "w-12" : "w-60",
            ].join(" ")}
        >
            {/* 顶部操作区 */}
            <div className={collapsed ? "px-0 py-5" : "px-3 py-5"}>
                <div className={collapsed ? "flex items-center justify-center" : "border-b border-[#e5e6eb] space-y-4 pb-4"}>
                    <div className={collapsed ? "flex items-center justify-center" : "px-2 flex justify-between items-center text-[14px] font-medium"}>
                        {!collapsed && <span>{localize("com_subscription.subscribe")}</span>}
                        <Button
                            size="icon"
                            variant="ghost"
                            className={collapsed ? "w-5 h-5" : "w-5 h-5 text-[#86909c]"}
                            onClick={() => setCollapsed((v) => !v)}
                        >
                            {collapsed ? (
                                <PanelLeftOpenIcon className="size-5" />
                            ) : (
                                <PanelRightOpenIcon className="size-5" />
                            )}
                        </Button>
                    </div>
                    {!collapsed && (
                        <div className="flex items-center gap-3">
                            <Button variant="secondary" onClick={onCreateChannel} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                                <Plus className="size-4" />{localize("com_subscription.create")}
                            </Button>
                            <Button variant="secondary" onClick={onChannelSquare} className="flex-1 h-8 text-[13px] bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none gap-1">
                                <ChannelBlocksArrowsIcon className="size-4" />
                                {localize("com_subscription.go_to_square")}
                            </Button>
                        </div>
                    )}
                </div>
            </div>

            {/* 列表区（折叠时隐藏内容，但保持容器以产生宽度过渡） */}
            <div
                className={[
                    "flex-1 min-h-0",
                    collapsed ? "opacity-0 pointer-events-none" : "opacity-100",
                    "transition-opacity duration-[350ms] ease-in-out",
                ].join(" ")}
            >
                <div
                    className="h-full overflow-y-auto scroll-on-scroll px-3 pb-5"
                    onScroll={handleListScroll}
                    data-scrolling={isListScrolling ? "true" : "false"}
                >
                    {/* 我创建的 */}
                    <div className="pt-0">
                        <SectionHeader
                            title={localize("com_subscription.created_by_me")}
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
                                {!createdChannels.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_subscription.no_data")}</div>}
                            </div>
                        )}
                    </div>

                    {/* 我关注的 */}
                    <div className="py-4">
                        <SectionHeader
                            title={localize("com_subscription.followed_by_me")}
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
                                {!subscribedChannels.length && <div className="py-6 text-center text-sm text-[#818181]">{localize("com_subscription.no_data")}</div>}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};