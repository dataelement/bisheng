import { useQuery } from "@tanstack/react-query";
import {
    Info,
    SquareArrowOutUpLeftIcon
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    Article,
    Channel,
    getArticlesApi,
    getChannelDetailApi,
    listManagerSourcesApi,
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

    // 信源选项（从频道 source_list 关联的信源信息中获取）
    const [sourceOptions, setSourceOptions] = useState<{ id: string; label: string }[]>([]);

    // 加载信源选项
    useEffect(() => {
        if (!channel?.source_list?.length) {
            setSourceOptions([]);
            return;
        }
        // 从已有接口拉取信源信息，匹配频道的 source_list
        const loadSources = async () => {
            try {
                // 尝试拉取 wechat 和 website 两种类型的信源
                const [wechat, website] = await Promise.all([
                    listManagerSourcesApi({ business_type: "wechat", page: 1, page_size: 100 }).catch(() => ({ sources: [], total: 0 })),
                    listManagerSourcesApi({ business_type: "website", page: 1, page_size: 100 }).catch(() => ({ sources: [], total: 0 })),
                ]);
                const allSources = [...wechat.sources, ...website.sources];
                const channelSourceSet = new Set(channel.source_list);
                const filtered = allSources
                    .filter(s => channelSourceSet.has(s.id) || channelSourceSet.has(s.source_id || ""))
                    .map(s => ({ id: s.id || s.source_id || "", label: s.name }));
                setSourceOptions(filtered);
            } catch {
                setSourceOptions([]);
            }
        };
        loadSources();
    }, [channel?.id, channel?.source_list]);

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

    const handleSourcesChange = (newValue: string[]) => {
        setSelectedSources(newValue);
    };

    const handleSearch = (value: string) => {
        if (value.length > 40) return;
        setSearchQuery(value);
    };

    const handleToggleUnread = () => {
        setOnlyUnread(!onlyUnread);
    };

    // 处理子频道切换（改为 name 模式）
    const handleSubChannelChange = (subChannelName: string) => {
        localStorage.setItem(`selectedSubChannelName-${channel.id}`, subChannelName === "all" ? "" : subChannelName);
        setSelectedSubChannelName(subChannelName === "all" ? undefined : subChannelName);
    };

    // Fetch channel detail for the tooltip; isLoading drives the page-level loading state
    const { data: channelDetail, isLoading: isChannelDetailLoading } = useQuery({
        queryKey: ["channelDetail", channel.id],
        queryFn: () => getChannelDetailApi(channel.id),
        staleTime: 60_000, // Cache for 1 minute
    });

    // Extract sub-channels from channel detail's filter_rules
    const subChannels = (channelDetail?.filter_rules || [])
        .filter(fr => fr.channel_type === 'sub' && fr.name)
        .map((fr, idx) => ({ id: `sub-${idx}`, name: fr.name! }));

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
                                    <div><span className="text-gray-400">频道描述：</span>
                                        <p>{channelDetail?.description || channel.description || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">创建人：</span>
                                        <p>{channelDetail?.creator_name || channel.creator || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">订阅人数：</span>
                                        <p>{channelDetail?.subscriber_count ?? channel.subscriberCount ?? 0}</p>
                                    </div>
                                    <div><span className="text-gray-400">内容数量：</span>
                                        <p>{channelDetail?.article_count ?? channel.articleCount ?? 0}</p>
                                    </div>
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </div>

                    {channelDetail?.visibility !== 'private' && <Button
                        onClick={() => {
                            const shareUrl = `${window.location.origin}${__APP_ENV__.BASE_URL}/channel/share/${channel.id}`;
                            const shareText = `欢迎加入频道【${channel.name}】 ，点击链接：${shareUrl} 一键订阅。`;
                            copyText(shareText).then(() => {
                                showToast({ message: '分享链接已复制到粘贴板', severity: NotificationSeverity.SUCCESS });
                            });
                        }}
                        variant="outline"
                        className="h-8 px-4 text-[14px] rounded-md font-normal"
                    >
                        <SquareArrowOutUpLeftIcon className="size-3.5" />
                        分享
                    </Button>}
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
                        >
                            全部
                        </button>
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
                            onChange={handleSearch}
                            placeholder="搜索你感兴趣的文章"
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
                        >
                            仅看未读
                        </button>
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
                    <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">无结果</div>
                ) : (
                    <InfiniteScroll
                        loadMore={() => loadArticles(currentPage + 1)}
                        hasMore={hasMore}
                        isLoading={loading}
                        emptyText="所有的消息都在这里啦"
                        className=""
                    >
                        {articles.map(article => (
                            <ArticleCard
                                key={article.id}
                                article={article}
                                onSelect={onArticleSelect}
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