import { useQuery } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { Channel, SortType, canManageChannelPermissions, getChannelsApi } from "~/api/channels";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { useConfirm } from "~/Providers";
import { useChannelActions } from "../hooks/useChannelActions";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface ChannelActionsMenuProps {
    /** Currently active channel (the one being viewed). */
    channel: Channel;
    onChannelSelect: (channel: Channel | null) => void;
    onManageMembers?: (channel: Channel) => void;
    onChannelSettings?: (channel: Channel) => void;
    /** "default" = PC labels (频道设置/成员管理/解散频道).
     *  "mobile" = H5 labels (编辑频道/权限管理/删除频道). */
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
    onManageMembers,
    onChannelSettings,
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

    const type: "created" | "subscribed" = subscribedChannels.some((c) => c.id === channel.id) && !createdChannels.some((c) => c.id === channel.id)
        ? "subscribed"
        : "created";

    // Prefer the freshest channel record from the lists (role/name can be stale on a deep-linked channel).
    const liveChannel = createdChannels.find((c) => c.id === channel.id)
        || subscribedChannels.find((c) => c.id === channel.id)
        || channel;

    const { handleDeleteChannel, handleUnsubscribeChannel } = useChannelActions({
        activeChannelId: channel.id,
        createdSortBy: SortType.RECENT_UPDATE,
        subscribedSortBy: SortType.RECENT_UPDATE,
        createdChannels,
        subscribedChannels,
        onChannelSelect,
    });

    // Use the shared permission helper (role + ReBAC permissionIds) so the entry stays
    // visible in permissionIds-based deployments, matching the channel-sidebar gating.
    const canManageMembers = canManageChannelPermissions(liveChannel.role, liveChannel.permissionIds);
    const isCreated = type === "created";
    const itemCls = "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] text-[#212121]";
    const iconCls = "size-4 text-[#4E5969]";

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    disabled={disabled}
                    className={cn(
                        isMobile
                            ? "inline-flex size-5 shrink-0 items-center justify-center text-[#212121]"
                            : "inline-flex size-8 items-center justify-center rounded-[6px] border border-[#EBECF0] bg-white text-[#4e5969] outline-none transition-colors fine-pointer:hover:bg-[#F7F8FA]",
                        disabled && "pointer-events-none opacity-20",
                        triggerClassName,
                    )}
                    aria-label={localize("com_subscription.channel_settings")}
                >
                    <Outlined.MoreCircle className={isMobile ? "size-5" : "size-4"} />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                sideOffset={isMobile ? 6 : undefined}
                className={cn("z-[120] border-none p-2 shadow-[0px_2px_8px_rgba(0,23,66,0.1)]", isMobile ? "w-[180px]" : "w-[160px]")}
            >
                {isMobile && onShare ? (
                    <DropdownMenuItem className={itemCls} onClick={onShare}>
                        <Outlined.Share className={iconCls} />
                        {localize("com_subscription.share")}
                    </DropdownMenuItem>
                ) : null}
                {isMobile && onOpenSourceFilter ? (
                    <DropdownMenuItem className={itemCls} onClick={onOpenSourceFilter}>
                        <Outlined.Filter className={iconCls} />
                        {localize("com_subscription.source_filter")}
                    </DropdownMenuItem>
                ) : null}
                {isCreated && onChannelSettings ? (
                    <DropdownMenuItem className={itemCls} onClick={() => onChannelSettings(liveChannel)}>
                        <Outlined.Edit className={iconCls} />
                        {isMobile
                            ? localize("com_subscription.edit_channel")
                            : localize("com_subscription.channel_settings")}
                    </DropdownMenuItem>
                ) : null}
                {canManageMembers && onManageMembers ? (
                    <DropdownMenuItem className={itemCls} onClick={() => onManageMembers(liveChannel)}>
                        <Outlined.PeopleSafe className={iconCls} />
                        {localize("com_subscription.permission_management")}
                    </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem
                    className={cn(itemCls, "text-[#F53F3F] data-[highlighted]:bg-[#F53F3F]/10 data-[highlighted]:text-[#F53F3F]")}
                    onClick={async () => {
                        const ok = await confirm({
                            title: localize("com_subscription.prompt_tip"),
                            description: isCreated
                                ? localize("com_subscription.confirm_delete_channel_for_all")
                                : localize("com_subscription.confirm_unsubscribe_channel_and_subs"),
                            confirmText: localize("com_subscription.confirm"),
                            cancelText: localize("com_subscription.cancel"),
                        });
                        if (!ok) return;
                        if (isCreated) handleDeleteChannel(liveChannel.id);
                        else handleUnsubscribeChannel(liveChannel.id);
                    }}
                >
                    {isCreated
                        ? <Outlined.Delete className="size-4 text-[#F53F3F]" />
                        : <LogOut className="size-4 text-[#F53F3F]" />}
                    {isCreated
                        ? (isMobile
                            ? localize("com_subscription.delete_channel")
                            : localize("com_subscription.dissolve_channel"))
                        : localize("com_subscription.unsubscribe")}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
