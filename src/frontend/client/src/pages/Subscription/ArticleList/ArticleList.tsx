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
}: ArticleListProps) {
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
            {/* header — H5 对齐 Figma 4063/4131：顶栏、订阅标题行、频道行、Tab+筛选 */}
            <div className="mx-auto w-full max-w-[1000px] px-4 pt-4 pb-4 md:pt-5 md:space-y-4 max-md:space-y-4">
                {(onOpenChannelNav || onGoChannelSquare || onCreateChannel) ? (
                    <div className="hidden max-md:flex max-md:flex-col max-md:gap-3">
                        {/* H5 第一行：仅展开 / 创建，与标题区分开 */}
                        <div
                            className={cn(
                                "flex items-center gap-2",
                                onOpenChannelNav && onCreateChannel && "justify-between",
                                !onOpenChannelNav && onCreateChannel && "justify-end",
                            )}
                        >
                            {onOpenChannelNav ? (
                                <button
                                    type="button"
                                    onClick={onOpenChannelNav}
                                    aria-label={localize("com_nav_open_sidebar")}
                                    className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-[#212121] hover:bg-[#F2F3F5]"
                                >
                                    <Menu className="size-5" />
                                </button>
                            ) : null}
                            {onCreateChannel ? (
                                <button
                                    type="button"
                                    onClick={onCreateChannel}
                                    aria-label={localize("com_subscription.create")}
                                    className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-[#212121] hover:bg-[#F2F3F5]"
                                >
                                    <Plus className="size-5" strokeWidth={2} />
                                </button>
                            ) : null}
                        </div>
                        {/* H5 第二行：订阅 + 前往频道广场（在展开按钮下方） */}
                        <div className="flex min-w-0 items-start justify-between gap-3">
                            <h2 className="shrink-0 text-[24px] font-semibold leading-8 text-[#335CFF]">
                                {localize("com_subscription.subscribe")}
                            </h2>
                            {onGoChannelSquare ? (
                                <button
                                    type="button"
                                    onClick={onGoChannelSquare}
                                    className="inline-flex min-w-0 max-w-[55%] items-center gap-1 rounded-md border border-transparent bg-white/80 px-1.5 py-0.5 text-left text-[12px] font-normal leading-5 text-[#212121] backdrop-blur-sm hover:bg-white"
                                >
                                    <ChannelBlocksArrowsIcon className="size-3.5 shrink-0 text-[#212121]" />
                                    <span className="truncate">{localize("com_subscription.go_to_channel_plaza")}</span>
                                </button>
                            ) : null}
                        </div>
                    </div>
                ) : null}

                {/* 频道名 + 信息 + 分享 — PC 与 H5 共用一行；H5 字号/色按稿 */}
                <div className="flex min-h-8 shrink-0 items-center justify-between gap-2 md:h-8">
                    <div className="flex min-w-0 flex-1 items-center gap-1 md:gap-1">
                        <h1 className="truncate text-[16px] font-medium leading-8 text-[#212121] md:font-semibold md:text-[#1D2129]">
                            {channelDetail?.name || channel.name}
                        </h1>
                        <Tooltip>
                            <TooltipTrigger>
                                <Info className="size-4 text-[#999999] md:text-[#86909c]" />
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

                    <div className="flex shrink-0 items-center justify-end md:h-8">
                        {channelDetail?.visibility !== "private" ? (
                            <Button
                                onClick={() => {
                                    const shareUrl = `${window.location.origin}${__APP_ENV__.BASE_URL}/channel/share/${channel.id}`;
                                    const shareText = localize("com_subscription.welcome_join_channel_share", {
                                        name: channel.name,
                                        shareUrl
                                    });
                                    copyText(shareText).then(() => {
                                        showToast({
                                            message: localize("com_subscription.share_link_copied"),
                                            severity: NotificationSeverity.SUCCESS
                                        });
                                    });
                                }}
                                variant="outline"
                                className={cn(
                                    "rounded-md border text-[14px] font-normal leading-normal",
                                    "h-8 px-4 max-md:h-auto max-md:min-h-8 max-md:border-[#EBECF0] max-md:bg-white/50 max-md:px-4 max-md:py-[5px] max-md:text-[#212121] max-md:backdrop-blur-sm",
                                )}
                            >
                                <ShareOutlineIcon className="size-3.5 shrink-0 max-md:size-4" />
                                {localize("com_subscription.share")}
                            </Button>
                        ) : null}
                    </div>
                </div>

                {/* 子频道 Tabs + 搜索/筛选 — md+ 横向；H5 纵向 */}
                <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between md:gap-0">
                    <div className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar">
                        <button
                            type="button"
                            onClick={() => handleSubChannelChange("all")}
                            className={cn(
                                "rounded-md border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                !selectedSubChannelName
                                    ? "border-primary bg-primary/20 text-primary max-md:border-[#335CFF] max-md:bg-[rgba(51,92,255,0.2)] max-md:text-[#335CFF]"
                                    : "border-transparent text-gray-800 hover:bg-gray-50 max-md:border-transparent max-md:text-[#212121] max-md:hover:bg-[#F7F8FA]",
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
                                        ? "border-primary bg-primary/20 text-primary max-md:border-[#335CFF] max-md:bg-[rgba(51,92,255,0.2)] max-md:text-[#335CFF]"
                                        : "border-transparent text-gray-800 hover:bg-gray-50 max-md:border-transparent max-md:text-[#212121] max-md:hover:bg-[#F7F8FA]",
                                )}
                            >
                                {sub.name}
                            </button>
                        ))}
                    </div>

                    <div className="flex w-full min-w-0 flex-col gap-2 md:ml-4 md:w-auto md:flex-row md:items-center md:gap-3">
                        <SearchInput
                            key={channel.id}
                            value={searchKey}
                            onChange={setSearchQuery}
                            placeholder={localize("com_subscription.search_articles_of_interest")}
                            className="w-full min-w-0 md:w-auto"
                        />

                        {/* H5：搜索下方一行，信息源 + 仅看未读靠左并排（避免整行贴右） */}
                        <div className="flex w-full min-w-0 flex-wrap items-center justify-start gap-2 md:contents">
                            <MultiSourceSelect
                                className="h-8 min-w-[140px] max-w-full shrink-0 md:w-auto md:min-w-[140px]"
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
                                        ? "border-primary bg-primary/20 text-primary max-md:border-[#335CFF] max-md:bg-[rgba(51,92,255,0.2)] max-md:text-[#335CFF]"
                                        : "border-transparent text-gray-800 hover:bg-gray-50 max-md:border-transparent max-md:text-[#212121] max-md:hover:bg-[#F7F8FA]",
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