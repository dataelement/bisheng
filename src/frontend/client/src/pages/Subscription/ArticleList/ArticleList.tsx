import { useLocalize } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Menu, Plus } from "lucide-react";
import {
    Article,
    Channel,
    getArticlesApi,
    getChannelDetailApi,
    type ArticleSearchResultItem
} from "~/api/channels";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useDebounce } from "~/hooks";
import { ArticleCard } from "./ArticleCard";
import { MultiSourceSelect } from "./MultiSourceSelect";
import { SearchInput } from "./SearchInput";
import { ShareOutlineIcon } from "~/components/icons/ShareOutlineIcon";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";
import { cn } from "~/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface ArticleListProps {
    channel: Channel;
    onArticleSelect: (article: Article | null) => void;
    selectedArticleId?: string;
    /** H5：打开「我的频道」侧栏（订阅页抽屉） */
    onOpenChannelNav?: () => void;
    onGoChannelSquare?: () => void;
    onCreateChannel?: () => void;
    onOpenChannelShare?: (channel: Channel) => void;
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

export function ArticleList({
    channel,
    selectedArticleId,
    onArticleSelect,
    onOpenChannelNav,
    onGoChannelSquare,
    onCreateChannel,
    onOpenChannelShare,
}: ArticleListProps) {
    const mobileHeadIconBtnClassName = "inline-flex size-8 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]";
    const localize = useLocalize();
    const [articles, setArticles] = useState<Article[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [selectedSubChannelName, setSelectedSubChannelName] = useState<string | undefined>(undefined);

    const [searchKey, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const searchQuery = useDebounce(searchKey, 500);
    const queryClient = useQueryClient();


    // Fetch channel detail for the tooltip; isLoading drives the page-level loading state
    const { data: channelDetail, isLoading: isChannelDetailLoading } = useQuery({
        queryKey: ["channelDetail", channel.id],
        queryFn: () => getChannelDetailApi(channel.id),
        staleTime: 60_000, // Cache for 1 minute
    });
    const canManageChannel = channel.role === "creator" || channel.role === "admin";
    const canOpenChannelShare =
        canManageChannel || (channelDetail ? channelDetail.visibility !== "private" : false);

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

    const handleListScroll = () => {
        setIsListScrolling(true);
        if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
        listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
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


    return (
        <div className="flex h-full w-full flex-1 flex-col">
            {/* header — 结构与知识空间页保持一致 */}
            <div className="mx-auto w-full max-w-[1000px] px-4 pt-5 pb-4 space-y-4 touch-mobile:space-y-3 touch-mobile:pt-0 touch-mobile:pb-3">
                {(onOpenChannelNav || onGoChannelSquare || onCreateChannel) ? (
                    <div className="hidden touch-mobile:flex touch-mobile:flex-col touch-mobile:gap-3">
                        {/* H5 第一行：仅展开 / 创建，与标题区分开 */}
                        <div
                            className={cn(
                                "-mx-4 flex h-8 items-center gap-2 px-2",
                                onOpenChannelNav && onCreateChannel && "justify-between",
                                !onOpenChannelNav && onCreateChannel && "justify-end",
                            )}
                        >
                            {onOpenChannelNav ? (
                                <button
                                    type="button"
                                    onClick={onOpenChannelNav}
                                    aria-label={localize("com_nav_open_sidebar")}
                                    className={mobileHeadIconBtnClassName}
                                >
                                    <Menu className="size-4" />
                                </button>
                            ) : null}
                            {onCreateChannel ? (
                                <button
                                    type="button"
                                    onClick={onCreateChannel}
                                    aria-label={localize("com_subscription.create")}
                                    className={mobileHeadIconBtnClassName}
                                >
                                    <Plus className="size-4" strokeWidth={2} />
                                </button>
                            ) : null}
                        </div>
                        {/* H5 第二行：订阅 + 前往频道广场（在展开按钮下方） */}
                        <div className="flex min-w-0 items-end gap-2">
                            <h2 className="shrink-0 text-[24px] font-semibold leading-8 text-[#335CFF]">
                                {localize("com_subscription.subscribe")}
                            </h2>
                            {onGoChannelSquare ? (
                                <button
                                    type="button"
                                    onClick={onGoChannelSquare}
                                    className="inline-flex min-w-0 items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-[#212121] hover:bg-[#F7F8FA]"
                                >
                                    <ChannelBlocksArrowsIcon className="size-4 shrink-0 text-[#86909C]" />
                                    <span className="truncate text-[12px] leading-5 font-normal text-[#212121]">
                                        {localize("com_subscription.go_to_channel_plaza")}
                                    </span>
                                </button>
                            ) : null}
                        </div>
                    </div>
                ) : null}

                {/* 频道名 + 信息 + 分享 */}
                <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
                        <h1 className="truncate text-base text-[#1d2129] touch-mobile:text-[16px] touch-mobile:leading-6">
                            {channelDetail?.name || channel.name}
                        </h1>
                        <Tooltip>
                            <TooltipTrigger className="cursor-pointer">
                                <Info className="size-4 text-[#86909c] outline-none hover:text-[#165dff]" />
                            </TooltipTrigger>
                            <TooltipContent noArrow className="bg-white shadow-md px-3 py-2 max-w-md w-[240px]">
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

                    <div className="flex shrink-0 items-center gap-3">
                        {canOpenChannelShare ? (
                            <Button
                                onClick={() => onOpenChannelShare?.(channel)}
                                variant="ghost"
                                className="h-8 gap-1 px-1.5 font-normal transition-colors hover:bg-[#F7F8FA] touch-mobile:rounded-[6px] touch-mobile:px-2 touch-mobile:text-[#212121] touch-mobile:border touch-mobile:border-[#EBECF0] touch-mobile:bg-white"
                            >
                                <ShareOutlineIcon className="size-4 shrink-0 text-gray-800" />
                                {localize("com_subscription.share")}
                            </Button>
                        ) : null}
                    </div>
                </div>

                {/* 子频道 Tabs + 搜索/筛选 — md+ 横向；H5 纵向 */}
                <div className="flex flex-col gap-4 touch-desktop:flex-row touch-desktop:items-center touch-desktop:justify-between touch-desktop:gap-0">
                    <div className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar">
                        <button
                            type="button"
                            onClick={() => handleSubChannelChange("all")}
                            className={cn(
                                "rounded-md border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                !selectedSubChannelName
                                    ? "border-primary bg-primary/20 text-primary touch-mobile:border-[#335CFF] touch-mobile:bg-[rgba(51,92,255,0.2)] touch-mobile:text-[#335CFF]"
                                    : "border-transparent text-gray-800 hover:bg-gray-50 touch-mobile:border-transparent touch-mobile:text-[#212121] touch-mobile:hover:bg-[#F7F8FA]",
                            )}
                        >{localize("com_subscription.all")}</button>
                        {subChannels.map(sub => (
                            <button
                                type="button"
                                key={sub.id}
                                onClick={() => handleSubChannelChange(sub.name)}
                                className={cn(
                                    "rounded-md border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                    selectedSubChannelName === sub.name
                                        ? "border-primary bg-primary/20 text-primary touch-mobile:border-[#335CFF] touch-mobile:bg-[rgba(51,92,255,0.2)] touch-mobile:text-[#335CFF]"
                                        : "border-transparent text-gray-800 hover:bg-gray-50 touch-mobile:border-transparent touch-mobile:text-[#212121] touch-mobile:hover:bg-[#F7F8FA]",
                                )}
                            >
                                {sub.name}
                            </button>
                        ))}
                    </div>

                    <div className="flex w-full min-w-0 flex-col gap-2 touch-desktop:ml-4 touch-desktop:w-auto touch-desktop:flex-row touch-desktop:items-center touch-desktop:gap-3">
                        <SearchInput
                            key={channel.id}
                            value={searchKey}
                            onChange={setSearchQuery}
                            placeholder={localize("com_subscription.search_articles_of_interest")}
                            className="w-full min-w-0 touch-desktop:w-auto"
                        />

                        {/* H5：搜索下方一行，信息源 + 仅看未读靠左并排（避免整行贴右） */}
                        <div className="flex w-full min-w-0 flex-wrap items-center justify-start gap-2 touch-desktop:contents">
                            <MultiSourceSelect
                                className="h-8 min-w-[140px] max-w-full shrink-0 touch-desktop:w-auto touch-desktop:min-w-[140px]"
                                options={sourceOptions}
                                value={selectedSources}
                                onChange={handleSourcesChange}
                            />

                            <button
                                type="button"
                                onClick={handleToggleUnread}
                                className={cn(
                                    "shrink-0 rounded-md border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                    onlyUnread
                                        ? "border-primary bg-primary/20 text-primary touch-mobile:border-[#335CFF] touch-mobile:bg-[rgba(51,92,255,0.2)] touch-mobile:text-[#335CFF]"
                                        : "border-transparent text-gray-800 hover:bg-gray-50 touch-mobile:border-transparent touch-mobile:text-[#212121] touch-mobile:hover:bg-[#F7F8FA]",
                                )}
                            >{localize("com_subscription.show_unread_only")}</button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Article list area */}
            <div
                className="flex-1 overflow-y-auto scroll-on-scroll"
                onScroll={handleListScroll}
                data-scrolling={isListScrolling ? "true" : "false"}
            >
                <div className="mx-auto w-full max-w-[1000px] px-4">
                    {/* Show loading spinner while channel detail or initial article list is loading */}
                    {(isChannelDetailLoading || (loading && articles.length === 0)) ? (
                        <div className="flex flex-col items-center justify-center h-64 gap-3 text-[#86909c]">
                            <LoadingIcon className="size-16 text-primary" />
                        </div>
                    ) : articles.length === 0 ? (
                        <div className="flex flex-1 flex-col items-center justify-center py-60 text-center">
                            {(searchQuery || selectedSources.length > 0 || onlyUnread) ? (
                                <p className="text-[14px] leading-6 text-[#86909c]">{localize("com_subscription.no_results")}</p>
                            ) : (
                                <>
                                    <img
                                        className="size-[120px] mb-4 object-contain opacity-90"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                        alt="empty"
                                    />
                                    <p className="text-[14px] leading-6 text-[#4E5969]">
                                        {localize("com_subscription.no_related_content")}
                                    </p>
                                </>
                            )}
                        </div>
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
            </div>
        </div>
    );
}
