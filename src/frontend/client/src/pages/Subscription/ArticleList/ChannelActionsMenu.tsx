import { useQuery } from "@tanstack/react-query";
import { LogOut, Pin, PinOff, Settings, UsersRound } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { Channel, ChannelRole, SortType, getChannelsApi } from "~/api/channels";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import ClosedIcon from "~/components/ui/icon/ClosedIcon";
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
}

/**
 * Page-level (top-right) management menu for the active channel — settings, members,
 * pin/unpin, dissolve/unsubscribe. Replaces the per-item menu that used to live in the
 * left ChannelSidebar.
 */
export function ChannelActionsMenu({
    channel,
    onChannelSelect,
    onManageMembers,
    onChannelSettings,
}: ChannelActionsMenuProps) {
    const localize = useLocalize();
    const confirm = useConfirm();

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

    // Prefer the freshest channel record from the lists (isPinned can be stale on a deep-linked channel).
    const liveChannel = createdChannels.find((c) => c.id === channel.id)
        || subscribedChannels.find((c) => c.id === channel.id)
        || channel;

    const { handleDeleteChannel, handleUnsubscribeChannel, handlePinChannel } = useChannelActions({
        activeChannelId: channel.id,
        createdSortBy: SortType.RECENT_UPDATE,
        subscribedSortBy: SortType.RECENT_UPDATE,
        createdChannels,
        subscribedChannels,
        onChannelSelect,
    });

    const canManageMembers = [ChannelRole.CREATOR, ChannelRole.ADMIN].includes(liveChannel.role);
    const itemCls = "flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-sm text-[#212121]";
    const iconCls = "size-4 text-[#4e5969]";

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    className="inline-flex size-8 items-center justify-center rounded-[6px] border border-[#EBECF0] bg-white text-[#4e5969] outline-none transition-colors fine-pointer:hover:bg-[#F7F8FA]"
                    aria-label={localize("com_subscription.channel_settings")}
                >
                    <Outlined.MoreCircle className="size-4" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="z-[120] w-[160px]">
                {type === "created" && onChannelSettings && (
                    <DropdownMenuItem className={itemCls} onClick={() => onChannelSettings(liveChannel)}>
                        <Settings className={iconCls} />
                        {localize("com_subscription.channel_settings")}
                    </DropdownMenuItem>
                )}
                {canManageMembers && onManageMembers && (
                    <DropdownMenuItem className={itemCls} onClick={() => onManageMembers(liveChannel)}>
                        <UsersRound className={iconCls} />
                        {localize("com_subscription.member_management")}
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem className={itemCls} onClick={() => handlePinChannel(liveChannel.id, !liveChannel.isPinned, type)}>
                    {liveChannel.isPinned ? <PinOff className={iconCls} /> : <Pin className={iconCls} />}
                    {liveChannel.isPinned ? localize("com_subscription.unpin") : localize("com_subscription.pin_channel")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    className={cn(itemCls, "text-[#F53F3F]")}
                    onClick={async () => {
                        const ok = await confirm({
                            title: localize("com_subscription.prompt_tip"),
                            description: type === "created"
                                ? localize("com_subscription.confirm_delete_channel_for_all")
                                : localize("com_subscription.confirm_unsubscribe_channel_and_subs"),
                            confirmText: localize("com_subscription.confirm"),
                            cancelText: localize("com_subscription.cancel"),
                        });
                        if (ok) type === "created" ? handleDeleteChannel(liveChannel.id) : handleUnsubscribeChannel(liveChannel.id);
                    }}
                >
                    {type === "created" ? <ClosedIcon className="size-4 text-[#F53F3F]" /> : <LogOut className="size-4 text-[#F53F3F]" />}
                    {type === "created" ? localize("com_subscription.dissolve_channel") : localize("com_subscription.unsubscribe")}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
