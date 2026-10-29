import { useQuery } from "@tanstack/react-query";
import { Dropdown, DropdownItem, DropdownSeparator } from "@bisheng/ui";
import { LogOut } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { Channel, SortType, canDeleteChannel, canEditChannelSettings, canManageChannelPermissions, getChannelDetailApi, getChannelsApi } from "~/api/channels";
import { useConfirm } from "~/Providers";
import { useChannelActions } from "../hooks/useChannelActions";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface ChannelActionsMenuProps {
    /** Currently active channel (the one being viewed). */
    channel: Channel;
    onChannelSelect: (channel: Channel | null) => void;
    onChannelSettings?: (channel: Channel) => void;
    /** 创建频道 entry pinned at the top of the menu (divider below). Mobile-only by
     *  convention — on PC, creation lives on the header button next to 切换频道. */
    onCreateChannel?: () => void;
    /** "default" = PC labels (频道设置/解散频道).
     *  "mobile" = H5 labels (频道设置/删除频道). */
    variant?: "default" | "mobile";
    /** Mobile only: 分享 menu item — copies the share link. */
    onShare?: () => void;
    /** Mobile only: 信息源筛选 menu item — opens the source-filter picker. */
    onOpenSourceFilter?: () => void;
    /** Optional class for the trigger button (icon-only). */
    triggerClassName?: string;
    /** When true, the trigger is non-interactive and dimmed (e.g. while the channel switcher is open). */
    disabled?: boolean;
}

/**
 * Page-level (top-right ⋯) management menu for the active channel.
 * PC variant items: 频道设置 / 成员管理 / 解散频道·取消订阅.
 * Mobile variant items: 分享 / 信息源筛选 / 编辑频道 / 权限管理 / 删除频道·取消订阅.
 * Pinning lives on the per-channel rows in the channel-switcher dropdown, not here.
 */
export function ChannelActionsMenu({
    channel,
    onChannelSelect,
    onChannelSettings,
    onCreateChannel,
    variant = "default",
    onShare,
    onOpenSourceFilter,
    triggerClassName,
    disabled,
}: ChannelActionsMenuProps) {
    const localize = useLocalize();
    const confirm = useConfirm();
    const isMobile = variant === "mobile";

    // Reuse the shared channel lists (deduped by react-query) to determine the active
    // channel's group + feed useChannelActions' optimistic cache updates.
    const { data: createdChannels = [] } = useQuery({
        queryKey: ["channels", "created", SortType.RECENT_UPDATE],
        queryFn: () => getChannelsApi({ type: "created", sortBy: SortType.RECENT_UPDATE }),
        placeholderData: (prev) => prev,
    });
    const { data: subscribedChannels = [] } = useQuery({
        queryKey: ["channels", "subscribed", SortType.RECENT_UPDATE],
        queryFn: () => getChannelsApi({ type: "subscribed", sortBy: SortType.RECENT_UPDATE }),
        placeholderData: (prev) => prev,
    });
    const { data: channelDetail, isFetched: isChannelDetailFetched } = useQuery({
        queryKey: ["channelDetail", channel.id],
        queryFn: () => getChannelDetailApi(channel.id),
        staleTime: 60_000,
    });

    const type: "created" | "subscribed" = subscribedChannels.some((c) => c.id === channel.id) && !createdChannels.some((c) => c.id === channel.id)
        ? "subscribed"
        : "created";

    // Prefer the freshest channel record from the lists (role/name can be stale on a deep-linked channel).
    const listChannel = createdChannels.find((c) => c.id === channel.id)
        || subscribedChannels.find((c) => c.id === channel.id)
        || channel;
    // Channel detail is the authoritative permission snapshot for the active
    // resource. It also covers deep links whose locally constructed Channel
    // record may not have actions yet.
    const liveChannel: Channel = {
        ...listChannel,
        actions: Array.isArray(channelDetail?.actions)
            ? channelDetail.actions
            : listChannel.actions,
    };

    const { handleDeleteChannel, handleUnsubscribeChannel } = useChannelActions({
        activeChannelId: channel.id,
        createdSortBy: SortType.RECENT_UPDATE,
        subscribedSortBy: SortType.RECENT_UPDATE,
        createdChannels,
        subscribedChannels,
        onChannelSelect,
    });

    // Gate every management entry by its concrete F048 action, independent of
    // which business list contains the channel.
    const canEditSettings = canEditChannelSettings(liveChannel.actions);
    const canManageMembers = canManageChannelPermissions(liveChannel.actions);
    // Unsubscribe remains a separate subscription operation.
    const canDissolve = canDeleteChannel(liveChannel.actions);
    const canUnsubscribe = type === "subscribed";
    const hasMenuItem = Boolean(
        (isMobile && onShare)
        || (isMobile && onOpenSourceFilter)
        || ((canEditSettings || canManageMembers) && onChannelSettings)
        || canDissolve
        || canUnsubscribe,
    );
    const permissionsResolving = !isChannelDetailFetched && !Array.isArray(listChannel.actions);
    const showShare = Boolean(isMobile && onShare);
    const showSourceFilter = Boolean(isMobile && onOpenSourceFilter);
    const showSettings = Boolean((canEditSettings || canManageMembers) && onChannelSettings);
    const hasRegularItem = showShare || showSourceFilter || showSettings;
    const hasDangerItem = canDissolve || canUnsubscribe;

    const handleDissolve = async () => {
        const ok = await confirm({
            title: localize("com_subscription.prompt_tip"),
            description: localize("com_subscription.confirm_delete_channel_for_all"),
            confirmText: localize("com_subscription.confirm"),
            cancelText: localize("com_subscription.cancel"),
        });
        if (!ok) return;
        handleDeleteChannel(liveChannel.id);
    };

    const handleUnsubscribe = async () => {
        const ok = await confirm({
            title: localize("com_subscription.prompt_tip"),
            description: localize("com_subscription.confirm_unsubscribe_channel_and_subs"),
            confirmText: localize("com_subscription.confirm"),
            cancelText: localize("com_subscription.cancel"),
        });
        if (!ok) return;
        handleUnsubscribeChannel(liveChannel.id);
    };

    return (
        <Dropdown
            align="end"
            menu={
                <>
                    {onCreateChannel ? (
                        <>
                            <DropdownItem icon={<Outlined.Plus />} onSelect={onCreateChannel}>
                                {localize("com_subscription.create_channel")}
                            </DropdownItem>
                            {hasRegularItem || hasDangerItem ? <DropdownSeparator /> : null}
                        </>
                    ) : null}
                    {showShare ? (
                        <DropdownItem icon={<Outlined.Share />} onSelect={() => onShare?.()}>
                            {localize("com_subscription.share")}
                        </DropdownItem>
                    ) : null}
                    {showSourceFilter ? (
                        <DropdownItem icon={<Outlined.Filter />} onSelect={() => onOpenSourceFilter?.()}>
                            {localize("com_subscription.source_filter")}
                        </DropdownItem>
                    ) : null}
                    {showSettings ? (
                        <DropdownItem icon={<Outlined.Edit />} onSelect={() => onChannelSettings?.(liveChannel)}>
                            {isMobile
                                ? localize("com_subscription.edit_channel")
                                : localize("com_subscription.channel_settings")}
                        </DropdownItem>
                    ) : null}
                    {hasRegularItem && hasDangerItem ? <DropdownSeparator /> : null}
                    {canDissolve ? (
                        <DropdownItem danger icon={<Outlined.Delete />} onSelect={handleDissolve}>
                            {isMobile
                                ? localize("com_subscription.delete_channel")
                                : localize("com_subscription.dissolve_channel")}
                        </DropdownItem>
                    ) : null}
                    {canUnsubscribe ? (
                        <DropdownItem danger icon={<LogOut />} onSelect={handleUnsubscribe}>
                            {localize("com_subscription.unsubscribe")}
                        </DropdownItem>
                    ) : null}
                </>
            }
        >
            <button
                type="button"
                disabled={disabled || permissionsResolving || !hasMenuItem}
                className={cn(
                    isMobile
                        ? "inline-flex size-5 shrink-0 items-center justify-center text-text-1"
                        : "inline-flex size-8 items-center justify-center rounded-md border border-border-base bg-white text-text-2 outline-none transition-colors fine-pointer:hover:bg-fill-1",
                    (disabled || permissionsResolving || !hasMenuItem) && "pointer-events-none opacity-20",
                    triggerClassName,
                )}
                aria-label={localize("com_subscription.channel_settings")}
            >
                <Outlined.MoreCircle className={isMobile ? "size-5" : "size-4"} />
            </button>
        </Dropdown>
    );
}
