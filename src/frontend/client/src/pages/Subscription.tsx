import { useState, useEffect } from "react";
import { ChannelSidebar } from "~/components/ChannelSidebar";
import { ChannelContent } from "~/components/ChannelContent";
import ChannelSquare from "./ChannelSquare";
import { Channel, Article, SortType } from "~/api/channels";
import { getMockChannels, getMockArticles, mockSources } from "~/mock/channels";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";

export default function Subscription() {
    const [createdChannels, setCreatedChannels] = useState<Channel[]>([]);
    const [subscribedChannels, setSubscribedChannels] = useState<Channel[]>([]);
    const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
    const [articles, setArticles] = useState<Article[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSubChannelId, setSelectedSubChannelId] = useState<string | undefined>();
    const [showChannelSquare, setShowChannelSquare] = useState(false);
    const { showToast } = useToastContext();

    // 加载频道列表
    const loadChannels = () => {
        const created = getMockChannels({
            type: "created",
            sortBy: SortType.RECENT_UPDATE
        });
        const subscribed = getMockChannels({
            type: "subscribed",
            sortBy: SortType.RECENT_UPDATE
        });

        setCreatedChannels(created);
        setSubscribedChannels(subscribed);

        // 默认选中第一个频道
        if (!activeChannel && created.length > 0) {
            setActiveChannel(created[0]);
        }
    };

    // 加载文章列表
    const loadArticles = (page: number = 1) => {
        if (!activeChannel) return;

        setLoading(true);
        setTimeout(() => {
            const response = getMockArticles({
                channelId: activeChannel.id,
                subChannelId: selectedSubChannelId,
                search: searchQuery,
                sourceIds: selectedSources.length > 0 ? selectedSources : undefined,
                onlyUnread,
                page,
                pageSize: 6
            });

            if (page === 1) {
                setArticles(response.data);
            } else {
                setArticles(prev => [...prev, ...response.data]);
            }

            setHasMore(response.hasMore);
            setCurrentPage(page);
            setLoading(false);
        }, 300);
    };

    // 初始加载
    useEffect(() => {
        loadChannels();
    }, []);

    // 频道切换时重新加载文章
    useEffect(() => {
        if (activeChannel) {
            setCurrentPage(1);
            setSelectedSubChannelId(undefined);
            setSearchQuery("");
            setSelectedSources([]);
            setOnlyUnread(false);
            loadArticles(1);
        }
    }, [activeChannel]);

    // 筛选条件变化时重新加载
    useEffect(() => {
        if (activeChannel) {
            setCurrentPage(1);
            loadArticles(1);
        }
    }, [searchQuery, selectedSources, onlyUnread, selectedSubChannelId]);

    // 处理频道选择
    const handleChannelSelect = (channel: Channel) => {
        setActiveChannel(channel);
    };

    // 创建频道
    const handleCreateChannel = () => {
        showToast({
            message: "创建频道功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    // 频道广场
    const handleChannelSquare = () => {
        setShowChannelSquare(true);
    };

    // 更新频道
    const handleUpdateChannel = (channel: Channel) => {
        // 更新本地状态
        setCreatedChannels(prev =>
            prev.map(c => c.id === channel.id ? channel : c)
        );
        setSubscribedChannels(prev =>
            prev.map(c => c.id === channel.id ? channel : c)
        );

        if (activeChannel?.id === channel.id) {
            setActiveChannel(channel);
        }

        showToast({
            message: "频道已更新",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 删除频道
    const handleDeleteChannel = (channelId: string) => {
        setCreatedChannels(prev => prev.filter(c => c.id !== channelId));

        if (activeChannel?.id === channelId) {
            setActiveChannel(createdChannels[0] || subscribedChannels[0] || null);
        }

        showToast({
            message: "频道已解散",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 取消订阅
    const handleUnsubscribeChannel = (channelId: string) => {
        setSubscribedChannels(prev => prev.filter(c => c.id !== channelId));

        if (activeChannel?.id === channelId) {
            setActiveChannel(createdChannels[0] || subscribedChannels[0] || null);
        }

        showToast({
            message: "已取消订阅",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 置顶频道
    const handlePinChannel = (channelId: string, pinned: boolean) => {
        const updateChannels = (channels: Channel[]) =>
            channels.map(c =>
                c.id === channelId ? { ...c, isPinned: pinned } : c
            );

        setCreatedChannels(prev => updateChannels(prev));
        setSubscribedChannels(prev => updateChannels(prev));

        if (activeChannel?.id === channelId) {
            setActiveChannel(prev => prev ? { ...prev, isPinned: pinned } : null);
        }

        showToast({
            message: pinned ? "已置顶" : "已取消置顶",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 加载更多文章
    const handleLoadMore = () => {
        loadArticles(currentPage + 1);
    };

    return (
        <div className="h-screen flex">
            {showChannelSquare ? (
                <ChannelSquare onBack={() => setShowChannelSquare(false)} />
            ) : (
                <>
                    <ChannelSidebar
                        createdChannels={createdChannels}
                        subscribedChannels={subscribedChannels}
                        activeChannelId={activeChannel?.id}
                        onChannelSelect={handleChannelSelect}
                        onCreateChannel={handleCreateChannel}
                        onChannelSquare={handleChannelSquare}
                        onUpdateChannel={handleUpdateChannel}
                        onDeleteChannel={handleDeleteChannel}
                        onUnsubscribeChannel={handleUnsubscribeChannel}
                        onPinChannel={handlePinChannel}
                    />

                    {activeChannel ? (
                        <ChannelContent
                            channel={activeChannel}
                            articles={articles}
                            sources={mockSources}
                            onLoadMore={handleLoadMore}
                            hasMore={hasMore}
                            loading={loading}
                            onSearch={setSearchQuery}
                            onFilterSources={setSelectedSources}
                            onToggleUnread={setOnlyUnread}
                            onSelectSubChannel={setSelectedSubChannelId}
                            selectedSubChannelId={selectedSubChannelId}
                        />
                    ) : (
                        <div className="flex-1 flex items-center justify-center text-[#86909c]">
                            请选择一个频道
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
