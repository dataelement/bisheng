import { useLocalize } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
    Channel,
    SortType,
    getChannelsApi,
} from "~/api/channels";
import { Button } from "~/components/ui/Button";
import NavToggle from "~/components/Nav/NavToggle";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";
import ChannelItem from "./ChannelItem";
import { SectionHeader } from "./SectionHeader";
import { useChannelActions } from "../hooks/useChannelActions";
import { UserPopMenu } from "~/layouts/UserPopMenu";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { HubModuleNavTabs } from "~/components/Nav/HubModuleNavTabs";
import { cn } from "~/utils";

interface ChannelSidebarProps {
    activeChannelId?: string;
    onChannelSelect: (channel: Channel | null) => void;
    onCreateChannel: () => void;
    onChannelSquare: () => void;
    onManageMembers: (channel: Channel) => void;
    onChannelSettings: (channel: Channel) => void;
    /** Report created channel count back to parent so it doesn't need a duplicate query */
    onCreatedCountChange?: (count: number) => void;
    /** When true, skip auto-selecting the first channel (e.g. share route is resolving) */
    suppressAutoSelect?: boolean;
    /** H5：置于订阅页固定抽屉内，隐藏 PC 折叠把手，宽度随父容器 */
    mobileDrawerMode?: boolean;
    /** H5 抽屉：右上角关闭 */
    onDrawerClose?: () => void;
}

export function ChannelSidebar({
    activeChannelId,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    onManageMembers,
    onChannelSettings,
    onCreatedCountChange,
    suppressAutoSelect,
    mobileDrawerMode = false,
    onDrawerClose,
}: ChannelSidebarProps) {
    const localize = useLocalize();
    const { data: bsConfig } = useGetBsConfig();
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [subscribedCollapsed, setSubscribedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [isToggleHovering, setIsToggleHovering] = useState(false);

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
        if (suppressAutoSelect) return;
        if (!activeChannelId && createdFetched && subscribedFetched) {
            if (createdChannels.length > 0) {
                onChannelSelect(createdChannels[0]);
            } else if (subscribedChannels.length > 0) {
                onChannelSelect(subscribedChannels[0]);
            }
        }
    }, [suppressAutoSelect, activeChannelId, createdChannels, subscribedChannels, createdFetched, subscribedFetched, onChannelSelect]);

    // Notify parent of created channel count changes
    useEffect(() => {
        onCreatedCountChange?.(createdChannels.length);
    }, [createdChannels.length, onCreatedCountChange]);

    useEffect(() => {
        if (mobileDrawerMode) setCollapsed(false);
    }, [mobileDrawerMode]);

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
        <div className={cn("relative h-full min-h-0 shrink-0", mobileDrawerMode && "w-full")}>
            <div
                className={[
                    "h-full bg-white border-r border-[#e5e6eb] flex flex-col overflow-hidden",
                    mobileDrawerMode ? "w-full" : collapsed ? "w-0" : "w-60",
                ].join(" ")}
                style={
                    mobileDrawerMode
                        ? undefined
                        : {
                            transitionProperty: "width",
                            transitionDuration: "300ms",
                            transitionTimingFunction: "ease-in-out",
                        }
                }
            >
                {mobileDrawerMode ? (
                    <>
                        <div className="shrink-0 border-b border-[#e5e6eb] px-3 py-2.5">
                            <div className="flex items-center justify-between">
                                {bsConfig?.sidebarIcon?.image ? (
                                    <img
                                        className="h-8 w-8 rounded-md object-contain"
                                        src={bsConfig.sidebarIcon.image}
                                        alt={localize("com_nav_home")}
                                    />
                                ) : (
                                    <div className="h-8 w-8 rounded-md bg-[#F2F3F5]" />
                                )}
                                {onDrawerClose ? (
                                    <button
                                        type="button"
                                        onClick={onDrawerClose}
                                        aria-label={localize("com_nav_close_sidebar")}
                                        className="inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
                                    >
                                        <X className="size-4" />
                                    </button>
                                ) : null}
                            </div>
                        </div>
                        <HubModuleNavTabs
                            onLinkClick={(link) => {
                                if (link.closeDrawerOnNavigate) onDrawerClose?.();
                            }}
                        />
                        <div className="shrink-0 border-b border-[#e5e6eb] px-3 py-3">
                            <Button
                                variant="secondary"
                                type="button"
                                onClick={() => {
                                    onCreateChannel();
                                    onDrawerClose?.();
                                }}
                                className="flex h-9 w-full items-center justify-center gap-1 border-none bg-[#F7F7F7] text-[13px] hover:bg-[#E5E6EB]"
                            >
                                <Plus className="size-4" />
                                {localize("com_subscription.create")}
                            </Button>
                        </div>
                    </>
                ) : null}
                {/* 顶部操作区 — PC */}
                {!mobileDrawerMode ? (
                <div className={collapsed ? "px-0 py-5" : "px-3 py-5"}>
                    <div className={collapsed ? "flex items-center justify-center h-7" : "border-b border-[#e5e6eb] space-y-4 pb-4"}>
                        {!collapsed && <div className="px-2 flex justify-between items-center text-[16px] font-medium">
                            <span>{localize("com_subscription.subscribe")}</span>
                        </div>}
                        {!collapsed && (
                            <div className="flex items-center gap-3">
                                <Button variant="secondary" onClick={onCreateChannel} className="flex-1 h-8 text-[13px] bg-[#F7F7F7] hover:bg-[#E5E6EB] border-none gap-1">
                                    <Plus className="size-4" />{localize("com_subscription.create")}
                                </Button>
                                <Button variant="secondary" onClick={onChannelSquare} className="flex-1 h-8 text-[13px] bg-[#F7F7F7] hover:bg-[#E5E6EB] border-none gap-1">
                                    <ChannelBlocksArrowsIcon className="size-4" />
                                    {localize("com_subscription.go_to_square")}
                                </Button>
                            </div>
                        )}
                    </div>
                </div>
                ) : null}

                {/* 列表区（折叠时隐藏内容，但保持容器以产生宽度过渡） */}
                <div
                    className={[
                        "flex-1 min-h-0",
                        collapsed ? "opacity-0 pointer-events-none" : "opacity-100",
                    ].join(" ")}
                    style={{
                        transitionProperty: 'background-color',
                        transitionDuration: '350ms',
                        transitionTimingFunction: 'ease-in-out'
                    }}
                >
                    <div
                        className="h-full overflow-y-auto overscroll-y-contain scroll-on-scroll px-3 pb-5"
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
                {mobileDrawerMode ? (
                    <div className="shrink-0 border-t border-[#ececec] px-2 pb-2 pt-1">
                        <UserPopMenu variant="drawer" />
                    </div>
                ) : null}
            </div>
            {!mobileDrawerMode ? (
                <NavToggle
                    navVisible={!collapsed}
                    onToggle={() => setCollapsed((v) => !v)}
                    isHovering={isToggleHovering}
                    setIsHovering={setIsToggleHovering}
                    className="absolute top-1/2 left-0 z-[10]"
                    translateX={230}
                />
            ) : null}
        </div>
    );
};