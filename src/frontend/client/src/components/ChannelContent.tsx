import { useState, useEffect } from "react";
import {
    Info,
    Share2,
    Search
} from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Switch } from "~/components/ui/Switch";
import { Button } from "~/components/ui/Button";
import { Channel, Article } from "~/api/channels";
import { ArticleCard } from "./ArticleCard";
import { TooltipAnchor } from "~/components/ui/Tooltip";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "~/components/ui/Select";

interface ChannelContentProps {
    channel: Channel;
    articles: Article[];
    sources: { id: string; name: string }[];
    onLoadMore: () => void;
    hasMore: boolean;
    loading: boolean;
    onSearch: (query: string) => void;
    onFilterSources: (sourceIds: string[]) => void;
    onToggleUnread: (onlyUnread: boolean) => void;
    onSelectSubChannel: (subChannelId?: string) => void;
    selectedSubChannelId?: string;
}

export function ChannelContent({
    channel,
    articles,
    sources,
    onLoadMore,
    hasMore,
    loading,
    onSearch,
    onFilterSources,
    onToggleUnread,
    onSelectSubChannel,
    selectedSubChannelId
}: ChannelContentProps) {
    const [searchQuery, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);

    // 处理搜索
    const handleSearch = (value: string) => {
        if (value.length > 40) {
            return;
        }
        setSearchQuery(value);
        onSearch(value);
    };

    // 处理信息源筛选
    const handleSourceFilter = (sourceId: string) => {
        let newSources: string[];
        if (sourceId === "all") {
            newSources = [];
        } else if (selectedSources.includes(sourceId)) {
            newSources = selectedSources.filter(id => id !== sourceId);
        } else {
            newSources = [...selectedSources, sourceId];
        }
        setSelectedSources(newSources);
        onFilterSources(newSources);
    };

    // 处理仅看未读
    const handleToggleUnread = (checked: boolean) => {
        setOnlyUnread(checked);
        onToggleUnread(checked);
    };

    // 处理子频道切换
    const handleSubChannelChange = (subChannelId: string) => {
        onSelectSubChannel(subChannelId === "all" ? undefined : subChannelId);
    };

    return (
        <div className="flex-1 h-full flex flex-col bg-[#f7f8fa]">
            {/* 顶部操作区 */}
            <div className="bg-white border-b border-[#e5e6eb] p-4 space-y-4">
                {/* 第一行：频道名称、信息、分享 */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <h1 className="text-[20px] font-semibold text-[#1d2129]">{channel.name}</h1>
                        <TooltipAnchor
                            description={
                                <div className="space-y-1 text-[12px]">
                                    <div>频道描述：{channel.description || "无"}</div>
                                    <div>创建人：{channel.creator}</div>
                                    <div>订阅人数：{channel.subscriberCount}</div>
                                    <div>内容数量：{channel.articleCount}</div>
                                </div>
                            }
                            side="bottom"
                        >
                            <button className="p-1 hover:bg-[#f7f8fa] rounded transition-colors">
                                <Info className="size-4 text-[#86909c]" />
                            </button>
                        </TooltipAnchor>
                    </div>

                    <Button
                        onClick={() => console.log("分享频道")}
                        variant="outline"
                        className="h-8 px-3 text-[14px]"
                    >
                        <Share2 className="size-4 mr-1" />
                        分享
                    </Button>
                </div>

                {/* 第二行：搜索、筛选 */}
                <div className="flex items-center gap-3">
                    {/* 搜索框 */}
                    <div className="relative flex-1 max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#86909c]" />
                        <Input
                            type="text"
                            placeholder="搜索你感兴趣的文章"
                            value={searchQuery}
                            onChange={(e) => handleSearch(e.target.value)}
                            maxLength={40}
                            className="pl-9 h-9 bg-[#f7f8fa] border-transparent focus:bg-white focus:border-[#e5e6eb]"
                        />
                    </div>

                    {/* 信息源筛选 */}
                    <Select
                        value={selectedSources.length === 0 ? "all" : selectedSources[0]}
                        onValueChange={handleSourceFilter}
                    >
                        <SelectTrigger className="w-[140px] h-9">
                            <SelectValue placeholder="全部信息源" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">全部信息源</SelectItem>
                            {sources.map(source => (
                                <SelectItem key={source.id} value={source.id}>
                                    {source.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    {/* 仅看未读 */}
                    <div className="flex items-center gap-2">
                        <span className="text-[14px] text-[#4e5969]">仅看未读</span>
                        <Switch
                            checked={onlyUnread}
                            onCheckedChange={handleToggleUnread}
                        />
                    </div>
                </div>

                {/* 第三行：子频道切换 */}
                {channel.subChannels.length > 0 && (
                    <div className="flex items-center gap-2 overflow-x-auto">
                        <button
                            onClick={() => handleSubChannelChange("all")}
                            className={`px-4 py-1.5 rounded-full text-[14px] whitespace-nowrap transition-colors ${
                                !selectedSubChannelId
                                    ? "bg-[#165dff] text-white"
                                    : "bg-[#f7f8fa] text-[#4e5969] hover:bg-[#e5e6eb]"
                            }`}
                        >
                            全部
                        </button>
                        {channel.subChannels
                            .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
                            .map(subChannel => (
                                <button
                                    key={subChannel.id}
                                    onClick={() => handleSubChannelChange(subChannel.id)}
                                    className={`px-4 py-1.5 rounded-full text-[14px] whitespace-nowrap transition-colors ${
                                        selectedSubChannelId === subChannel.id
                                            ? "bg-[#165dff] text-white"
                                            : "bg-[#f7f8fa] text-[#4e5969] hover:bg-[#e5e6eb]"
                                    }`}
                                >
                                    {subChannel.name}
                                </button>
                            ))}
                    </div>
                )}
            </div>

            {/* 文章列表区 */}
            <div className="flex-1 overflow-y-auto p-4">
                {loading && articles.length === 0 ? (
                    <div className="flex items-center justify-center h-64 text-[#86909c]">
                        加载中...
                    </div>
                ) : articles.length === 0 ? (
                    <div className="flex items-center justify-center h-64 text-[#86909c]">
                        暂无文章
                    </div>
                ) : (
                    <div className="space-y-4 max-w-4xl mx-auto">
                        {articles.map(article => (
                            <ArticleCard
                                key={article.id}
                                article={article}
                                onSelect={setSelectedArticle}
                                isSelected={selectedArticle?.id === article.id}
                            />
                        ))}

                        {/* 加载更多 */}
                        {hasMore && (
                            <div className="flex justify-center py-4">
                                <Button
                                    onClick={onLoadMore}
                                    disabled={loading}
                                    variant="outline"
                                    className="h-9 px-6"
                                >
                                    {loading ? "加载中..." : "加载更多"}
                                </Button>
                            </div>
                        )}

                        {/* 到底提示 */}
                        {!hasMore && articles.length > 0 && (
                            <div className="text-center py-4 text-[#86909c] text-[14px]">
                                所有的消息都在这里啦
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
