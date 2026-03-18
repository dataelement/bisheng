import { useQueryClient } from "@tanstack/react-query";
import {
    Channel,
    SortType,
    pinChannelApi,
    updateChannelApi,
    deleteChannelApi,
    unsubscribeChannelApi
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";

interface UseChannelActionsOptions {
    activeChannelId?: string;
    createdSortBy: SortType;
    subscribedSortBy: SortType;
    createdChannels: Channel[];
    subscribedChannels: Channel[];
    onChannelSelect: (channel: Channel | null) => void;
}

/**
 * Extracts channel CRUD operations with optimistic update logic
 * from ChannelSidebar, keeping the sidebar component focused on UI.
 */
export function useChannelActions({
    activeChannelId,
    createdSortBy,
    subscribedSortBy,
    createdChannels,
    subscribedChannels,
    onChannelSelect,
}: UseChannelActionsOptions) {
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    // Cache updaters scoped to current sort keys
    const updateCreatedCache = (updater: (channels: Channel[]) => Channel[]) => {
        queryClient.setQueryData(["channels", "created", createdSortBy], (old: Channel[] = []) => updater(old));
    };

    const updateSubscribedCache = (updater: (channels: Channel[]) => Channel[]) => {
        queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => updater(old));
    };

    const updateBothCaches = (updater: (channels: Channel[]) => Channel[]) => {
        updateCreatedCache(updater);
        updateSubscribedCache(updater);
    };

    // Rename channel (double-click edit)
    const handleUpdateChannel = async (channel: Channel) => {
        // Optimistic update
        updateBothCaches(channels => channels.map(c => c.id === channel.id ? channel : c));
        if (activeChannelId === channel.id) {
            onChannelSelect(channel);
        }

        try {
            await updateChannelApi(channel.id, { name: channel.name, description: channel.description });
            showToast({ message: "频道已更新", severity: NotificationSeverity.SUCCESS });
        } catch (e) {
            // Rollback on failure
            queryClient.invalidateQueries({ queryKey: ["channels", "created"] });
            showToast({ message: "更新失败，请重试", severity: NotificationSeverity.ERROR });
        }
    };

    // Delete channel
    const handleDeleteChannel = async (channelId: string) => {
        let nextActive: Channel | null = null;

        queryClient.setQueryData(["channels", "created", createdSortBy], (old: Channel[] = []) => {
            const newData = old.filter(c => c.id !== channelId);
            if (activeChannelId === channelId && newData.length > 0) nextActive = newData[0];
            return newData;
        });

        if (activeChannelId === channelId && !nextActive) {
            const subscribed = queryClient.getQueryData<Channel[]>(["channels", "subscribed", subscribedSortBy]) || [];
            const newSubscribed = subscribed.filter(c => c.id !== channelId);
            queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], newSubscribed);
            if (newSubscribed.length > 0) nextActive = newSubscribed[0];
        } else {
            queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => old.filter(c => c.id !== channelId));
        }

        if (activeChannelId === channelId) {
            onChannelSelect(nextActive);
        }

        try {
            await deleteChannelApi(channelId);
            // Refresh all channel queries so createdChannelCount updates correctly
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            showToast({ message: "频道已解散", severity: NotificationSeverity.WARNING });
        } catch (e) {
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            showToast({ message: "解散失败，请重试", severity: NotificationSeverity.ERROR });
        }
    };

    // Unsubscribe
    const handleUnsubscribeChannel = async (channelId: string) => {
        let nextActive: Channel | null = null;
        queryClient.setQueryData(["channels", "subscribed", subscribedSortBy], (old: Channel[] = []) => {
            const newData = old.filter(c => c.id !== channelId);
            if (activeChannelId === channelId && newData.length > 0) nextActive = newData[0];
            return newData;
        });

        if (activeChannelId === channelId) {
            if (!nextActive && createdChannels.length > 0) nextActive = createdChannels[0];
            onChannelSelect(nextActive);
        }

        try {
            await unsubscribeChannelApi(channelId);
            showToast({ message: "已取消订阅", severity: NotificationSeverity.WARNING });
        } catch (e) {
            queryClient.invalidateQueries({ queryKey: ["channels", "subscribed"] });
            showToast({ message: "取消订阅失败，请重试", severity: NotificationSeverity.ERROR });
        }
    };

    // Pin / Unpin
    const handlePinChannel = async (channelId: string, pinned: boolean, type: "created" | "subscribed") => {
        const channels = type === "created" ? createdChannels : subscribedChannels;
        if (pinned && channels.filter(c => c.isPinned).length >= 5) {
            showToast({ message: "已达置顶数量限制", severity: NotificationSeverity.INFO });
            return;
        }

        // Optimistic update
        const updater = (list: Channel[]) => list.map(c => c.id === channelId ? { ...c, isPinned: pinned } : c);
        updateBothCaches(updater);

        if (activeChannelId === channelId) {
            const channel = channels.find(c => c.id === channelId);
            if (channel) onChannelSelect({ ...channel, isPinned: pinned });
        }

        try {
            await pinChannelApi(channelId, pinned);
            queryClient.invalidateQueries({ queryKey: ["channels", type === "created" ? "created" : "subscribed"] });
            showToast({ message: pinned ? "已置顶" : "已取消置顶", severity: NotificationSeverity.SUCCESS });
        } catch (e) {
            // Rollback
            const rollback = (list: Channel[]) => list.map(c => c.id === channelId ? { ...c, isPinned: !pinned } : c);
            updateBothCaches(rollback);
            if (activeChannelId === channelId) {
                const channel = channels.find(c => c.id === channelId);
                if (channel) onChannelSelect({ ...channel, isPinned: !pinned });
            }
            showToast({ message: "操作失败，请重试", severity: NotificationSeverity.ERROR });
        }
    };

    return {
        handleUpdateChannel,
        handleDeleteChannel,
        handleUnsubscribeChannel,
        handlePinChannel,
    };
}
