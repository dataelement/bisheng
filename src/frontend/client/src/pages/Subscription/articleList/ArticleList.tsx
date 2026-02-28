import {
    Info,
    SquareArrowOutUpLeftIcon
} from "lucide-react";
import { useEffect, useState } from "react";
import { Article, Channel } from "~/api/channels";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { Button } from "~/components/ui/Button";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useDebounce } from "~/hooks";
import { getMockArticles } from "~/mock/channels";
import { ArticleCard } from "./ArticleCard";
import { MultiSourceSelect } from "./MultiSourceSelect";
import { SearchInput } from "./SearchInput";

interface ArticleListProps {
    channel: Channel;
    onArticleSelect: (article: Article | null) => void;
    selectedArticleId?: string;
}

const MOCK_OPTIONS = [
    { id: "bjrb", label: "北京日报" },
    { id: "xhw", label: "新华网" },
    { id: "xhwcj", label: "新华网 / 财经" },
    { id: "sdzw", label: "首都之窗" },
];

export function ArticleList({ channel, selectedArticleId, onArticleSelect }: ArticleListProps) {
    const [articles, setArticles] = useState<Article[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [selectedSubChannelId, setSelectedSubChannelId] = useState<string | undefined>(undefined);

    const [searchKey, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const searchQuery = useDebounce(searchKey, 500)

    const loadArticles = (page: number) => {
        if (!channel) return;

        setLoading(true);
        setTimeout(() => {
            const response = getMockArticles({
                channelId: channel.id,
                subChannelId: selectedSubChannelId,
                search: searchQuery,
                sourceIds: selectedSources.length > 0 ? selectedSources : undefined,
                onlyUnread,
                page,
                pageSize: 18
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

    // 频道切换时重新加载文章
    useEffect(() => {
        if (channel) {
            setCurrentPage(1);
            setSearchQuery("");
            setSelectedSubChannelId(localStorage.getItem(`selectedSubChannelId-${channel.id}`) || undefined)
            setSelectedSources([]);
            setOnlyUnread(false);
            onArticleSelect(null);
            loadArticles(1);
        }
    }, [channel]);

    // 筛选条件变化时重新加载
    useEffect(() => {
        if (channel) {
            setCurrentPage(1);
            loadArticles(1);
        }
    }, [searchQuery, selectedSources, onlyUnread, selectedSubChannelId]);

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

    // 处理子频道切换
    const handleSubChannelChange = (subChannelId: string) => {
        localStorage.setItem(`selectedSubChannelId-${channel.id}`, subChannelId === "all" ? "" : subChannelId);
        setSelectedSubChannelId(subChannelId === "all" ? undefined : subChannelId);
    };

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
                                        <p>{channel.description || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">创建人：</span>
                                        <p>{channel.creator}</p>
                                    </div>
                                    <div><span className="text-gray-400">订阅人数：</span>
                                        <p>{channel.subscriberCount}</p>
                                    </div>
                                    <div><span className="text-gray-400">内容数量：</span>
                                        <p>{channel.articleCount}</p>
                                    </div>
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </div>

                    <Button
                        onClick={() => console.log("分享频道")}
                        variant="outline"
                        className="h-8 px-4 text-[14px] rounded-md font-normal"
                    >
                        <SquareArrowOutUpLeftIcon className="size-3.5" />
                        分享
                    </Button>
                </div>

                {/* 第二行：子频道 Tabs 与 工具栏 (搜索/筛选) */}
                <div className="flex items-center justify-between">
                    {/* 左侧：子频道 Tabs */}
                    <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
                        <button
                            onClick={() => handleSubChannelChange("all")}
                            className={`px-4 py-[5px] rounded-md border text-sm transition-colors whitespace-nowrap ${!selectedSubChannelId
                                ? "bg-primary/20 text-primary border-primary"
                                : "text-gray-800 hover:bg-gray-50 border-transparent"
                                }`}
                        >
                            全部
                        </button>
                        {channel.subChannels.map(subChannel => (
                            <button
                                key={subChannel.id}
                                onClick={() => handleSubChannelChange(subChannel.id)}
                                className={`px-4 py-[5px] rounded-md border text-sm transition-colors whitespace-nowrap ${selectedSubChannelId === subChannel.id
                                    ? "bg-primary/20 text-primary border-primary"
                                    : "text-gray-800 hover:bg-gray-50 border-transparent"
                                    }`}
                            >
                                {subChannel.name}
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

                        {/* 信息源筛选 - 样式对齐截图 */}
                        <MultiSourceSelect
                            className="w-auto min-w-[140px] h-8"
                            options={MOCK_OPTIONS}
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

            {/* 文章列表区 */}
            <div className="flex-1 overflow-y-auto noscrollbar">
                {loading && articles.length === 0 ? (
                    <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">加载中...</div>
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