import { useLocalize } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    Info,
    SquareArrowOutUpLeftIcon
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    Article,
    Channel,
    getArticlesApi,
    getChannelDetailApi,
    type ArticleSearchResultItem
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useDebounce } from "~/hooks";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";
import { ArticleCard } from "./ArticleCard";
import { MultiSourceSelect } from "./MultiSourceSelect";
import { SearchInput } from "./SearchInput";

interface ArticleListProps {
    channel: Channel;
    onArticleSelect: (article: Article | null) => void;
    selectedArticleId?: string;
}

/** Strip HTML tags from a string, extracting body content first */
export function stripHtmlTags(html: string): string {
    if (!html) return "";
    // Extract content within <body> tags if present
    const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    const bodyContent = bodyMatch ? bodyMatch[1] : html;
    return bodyContent
        .replace(/<[^>]*>/g, "")       // Strip HTML tags
        .replace(/&[a-zA-Z]+;/g, " ")  // Strip named entities (&nbsp; &amp; etc.)
        .replace(/&#\d+;/g, " ")       // Strip numeric entities (&#160; etc.)
        .replace(/\s+/g, " ")          // Collapse whitespace
        .trim();
}

/** Map backend ArticleSearchResultItem to frontend Article */
export function mapToArticle(item: ArticleSearchResultItem, channelId: string): Article {
    return {
        id: item.doc_id,
        title: item.title,
        url: item.source_url || "",
        content: stripHtmlTags(item.content || ""),
        content_html: item.content_html || "",
        coverImage: item.cover_image || undefined,
        sourceName: item.source_info?.source_name || "",
        sourceAvatar: item.source_info?.source_icon || undefined,
        sourceId: item.source_id,
        channelId,
        isRead: item.is_read ?? false,
        publishedAt: item.publish_time || item.create_time || "",
        createdAt: item.create_time || "",
        highlight: item.highlight,
        source_type: item.source_type,
    };
}

export function ArticleList({ channel, selectedArticleId, onArticleSelect }: ArticleListProps) {
    const localize = useLocalize();
    const [articles, setArticles] = useState<Article[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [selectedSubChannelName, setSelectedSubChannelName] = useState<string | undefined>(undefined);

    const [searchKey, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const searchQuery = useDebounce(searchKey, 500);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();


    // Fetch channel detail for the tooltip; isLoading drives the page-level loading state
    const { data: channelDetail, isLoading: isChannelDetailLoading } = useQuery({
        queryKey: ["channelDetail", channel.id],
        queryFn: () => getChannelDetailApi(channel.id),
        staleTime: 60_000, // Cache for 1 minute
    });

    // Derive source options directly from channelDetail.source_infos (refreshes after channel edit)
    const sourceOptions = useMemo(() => {
        const infos = channelDetail?.source_infos;
        if (!infos?.length) return [];
        return infos
            .filter(s => s.id)
            .map(s => ({ id: s.id, label: s.source_name || s.name || '' }));
    }, [channelDetail?.source_infos]);

    const PAGE_SIZE = 20;

    const loadArticles = useCallback(async (page: number) => {
        if (!channel) return;

        setLoading(true);
        try {
            const response = await getArticlesApi({
                channelId: channel.id,
                subChannelName: selectedSubChannelName,
                keyword: searchQuery || undefined,
                sourceIds: selectedSources.length > 0 ? selectedSources : undefined,
                onlyUnread: onlyUnread || undefined,
                page,
                pageSize: PAGE_SIZE,
            });

            const mapped = (response.data || []).map(item => mapToArticle(item, channel.id));

            if (page === 1) {
                setArticles(mapped);
            } else {
                setArticles(prev => [...prev, ...mapped]);
            }

            const total = response.total || 0;
            setHasMore(page * PAGE_SIZE < total);
            setCurrentPage(page);
        } catch (e) {
            console.error("Failed to load articles:", e);
            if (page === 1) setArticles([]);
        } finally {
            setLoading(false);
        }
        // Note: sourceOptions is NOT a dependency here to avoid re-fetching when sources load
    }, [channel?.id, selectedSubChannelName, searchQuery, selectedSources, onlyUnread]);

    // 统一的频道切换 + 筛选加载 effect
    // 用 ref 检测频道是否切换，切换时重置状态再加载
    const prevChannelIdRef = useRef<string | undefined>(undefined);
    useEffect(() => {
        if (!channel) return;

        // 检测是否为频道切换
        const isChannelSwitch = channel.id !== prevChannelIdRef.current;
        if (isChannelSwitch) {
            prevChannelIdRef.current = channel.id;
            setCurrentPage(1);
            setSearchQuery("");
            const savedSubName = localStorage.getItem(`selectedSubChannelName-${channel.id}`) || undefined;
            setSelectedSubChannelName(savedSubName);
            setSelectedSources([]);
            setOnlyUnread(false);
            onArticleSelect(null);
            // 频道切换时不在这里加载，等 React 下一轮渲染
            // 下一轮 selectedSubChannelName/selectedSources 变化后本 effect 会自动触发
            return;
        }

        // 筛选条件变化或初始加载
        loadArticles(1);
    }, [channel?.id, searchQuery, selectedSources, onlyUnread, selectedSubChannelName]);

    // Optimistically mark the article as read in local state when selected.
    // The backend already marks it read when the detail API is called.
    const handleArticleClick = useCallback((article: Article | null) => {
        if (article && !article.isRead) {
            setArticles(prev =>
                prev.map(a => a.id === article.id ? { ...a, isRead: true } : a)
            );
            // Optimistically decrement unread badge in sidebar channel cache
            const decrementUnread = (old: Channel[] | undefined) => {
                if (!old) return old;
                return old.map(c =>
                    c.id === channel.id && c.unreadCount > 0
                        ? { ...c, unreadCount: c.unreadCount - 1 }
                        : c
                );
            };
            // Update all cached query variants for both created and subscribed lists
            queryClient.setQueriesData<Channel[]>(
                { queryKey: ["channels", "created"] },
                decrementUnread
            );
            queryClient.setQueriesData<Channel[]>(
                { queryKey: ["channels", "subscribed"] },
                decrementUnread
            );
        }
        onArticleSelect(article);
    }, [onArticleSelect, channel.id, queryClient]);

    const handleSourcesChange = (newValue: string[]) => {
        setSelectedSources(newValue);
    };

    const handleToggleUnread = () => {
        setOnlyUnread(!onlyUnread);
    };

    // 处理子频道切换（改为 name 模式）
    const handleSubChannelChange = (subChannelName: string) => {
        localStorage.setItem(`selectedSubChannelName-${channel.id}`, subChannelName === "all" ? "" : subChannelName);
        setSelectedSubChannelName(subChannelName === "all" ? undefined : subChannelName);
    };


    // Extract sub-channels from channel detail's filter_rules
    const subChannels = (channelDetail?.filter_rules || [])
        .filter(fr => fr.channel_type === 'sub' && fr.name)
        .map((fr, idx) => ({ id: `sub-${idx}`, name: fr.name! }))
        .sort((a, b) => {
            // Sort by first character priority: letters > digits > Chinese/other
            const getPriority = (name: string) => {
                const ch = name.charAt(0);
                if (/[a-zA-Z]/.test(ch)) return 0;
                if (/\d/.test(ch)) return 1;
                return 2;
            };
            const pa = getPriority(a.name);
            const pb = getPriority(b.name);
            if (pa !== pb) return pa - pb;
            return a.name.localeCompare(b.name, 'zh-CN');
        });

    console.log('channelDetail :>> ', channelDetail);
    return (
        <div className="flex-1 px-4 h-full flex flex-col max-w-[1000px] mx-auto">
            {/* header */}
            <div className="pt-5 pb-4 space-y-4">
                {/* 第一行：频道名称、信息、分享 */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1">
                        <h1 className="">{channel.name}</h1>
                        <Tooltip>
                            <TooltipTrigger>
                                <Info className="size-4 text-[#86909c]" />
                            </TooltipTrigger>
                            <TooltipContent noArrow className="bg-white shadow-md px-3 py-2 max-w-md">
                                <div className="space-y-1.5 text-gray-800 text-sm">
                                    <div><span className="text-gray-400">{localize("com_subscription.channel_description_colon")}</span>
                                        <p>{channelDetail?.description || channel.description || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_subscription.creator_colon")}</span>
                                        <p>{channelDetail?.creator_name || channel.creator || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_subscription.subscribers_colon")}</span>
                                        <p>{channelDetail?.subscriber_count ?? channel.subscriberCount ?? 0}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_subscription.content_count_colon")}</span>
                                        <p>{channelDetail?.article_count ?? channel.articleCount ?? 0}</p>
                                    </div>
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </div>

                    {channelDetail?.visibility !== 'private' && <Button
                        onClick={() => {
                            const shareUrl = `${window.location.origin}${__APP_ENV__.BASE_URL}/channel/share/${channel.id}`;
                            const shareText = localize("com_subscription.welcome_join_channel_share", { name: channel.name, shareUrl });
                            copyText(shareText).then(() => {
                                showToast({ message: localize("com_subscription.share_link_copied"), severity: NotificationSeverity.SUCCESS });
                            });
                        }}
                        variant="outline"
                        className="h-8 px-4 text-[14px] rounded-md font-normal"
                    >
                        <SquareArrowOutUpLeftIcon className="size-3.5" />{localize("com_subscription.share")}</Button>}
                </div>

                {/* 第二行：子频道 Tabs 与 工具栏 (搜索/筛选) */}
                <div className="flex items-center justify-between">
                    {/* 左侧：子频道 Tabs */}
                    <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
                        <button
                            onClick={() => handleSubChannelChange("all")}
                            className={`px-4 py-[5px] rounded-md border text-sm transition-colors whitespace-nowrap ${!selectedSubChannelName
                                ? "bg-primary/20 text-primary border-primary"
                                : "text-gray-800 hover:bg-gray-50 border-transparent"
                                }`}
                        >{localize("com_subscription.all")}</button>
                        {subChannels.map(sub => (
                            <button
                                key={sub.id}
                                onClick={() => handleSubChannelChange(sub.name)}
                                className={`px-4 py-[5px] rounded-md border text-sm transition-colors whitespace-nowrap ${selectedSubChannelName === sub.name
                                    ? "bg-primary/20 text-primary border-primary"
                                    : "text-gray-800 hover:bg-gray-50 border-transparent"
                                    }`}
                            >
                                {sub.name}
                            </button>
                        ))}
                    </div>

                    {/* 右侧：交互工具栏 */}
                    <div className="flex items-center gap-3 ml-4">
                        {/* 平滑展开的搜索容器 */}
                        <SearchInput
                            key={channel.id}
                            value={searchKey}
                            onChange={setSearchQuery}
                            placeholder={localize("com_subscription.search_articles_of_interest")}
                        />

                        {/* 信息源筛选 */}
                        <MultiSourceSelect
                            className="w-auto min-w-[140px] h-8"
                            options={sourceOptions}
                            value={selectedSources}
                            onChange={handleSourcesChange}
                        />

                        <button
                            onClick={handleToggleUnread}
                            className={`px-4 py-[5px] rounded-md border text-sm transition-colors whitespace-nowrap ${onlyUnread
                                ? "bg-primary/20 text-primary border-primary"
                                : "text-gray-800 hover:bg-gray-50"
                                }`}
                        >{localize("com_subscription.show_unread_only")}</button>
                    </div>
                </div>
            </div>

            {/* Article list area */}
            <div className="flex-1 overflow-y-auto noscrollbar">
                {/* Show loading spinner while channel detail or initial article list is loading */}
                {(isChannelDetailLoading || (loading && articles.length === 0)) ? (
                    <div className="flex flex-col items-center justify-center h-64 gap-3 text-[#86909c]">
                        <LoadingIcon className="size-16 text-primary" />
                    </div>
                ) : articles.length === 0 ? (
                    <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">{localize("com_subscription.no_results")}</div>
                ) : (
                    <InfiniteScroll
                        loadMore={() => loadArticles(currentPage + 1)}
                        hasMore={hasMore}
                        isLoading={loading}
                        emptyText={localize("com_subscription.all_messages_are_here")}
                        className=""
                    >
                        {articles.map(article => (
                            <ArticleCard
                                key={article.id}
                                article={article}
                                onSelect={handleArticleClick}
                                isSelected={selectedArticleId === article.id}
                                searchQuery={searchQuery}
                            />
                        ))}
                    </InfiniteScroll>
                )}
            </div>
        </div >
    );
}