import { BookOpen, SquareArrowOutUpLeftIcon } from "lucide-react"; // 更换了更接近设计稿的图标
import { useState } from "react";
import { Article } from "~/api/channels";

interface ArticleCardProps {
    article: Article;
    onSelect: (article: Article) => void;
    isSelected: boolean;
    searchQuery?: string;
}

export function ArticleCard({ article, onSelect, isSelected, searchQuery }: ArticleCardProps) {
    const [hovered, setHovered] = useState(false);

    // 格式化时间逻辑保持不变
    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
        const isToday = date.toDateString() === now.toDateString();

        if (isToday) return "今日更新";
        if (diffDays >= 1 && diffDays <= 7) return `${diffDays}天前`;
        return date.toISOString().split('T')[0];
    };

    // 关键词高亮处理
    const highlightText = (text: string, query?: string) => {
        if (!query || !query.trim()) return text;
        const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escapedQuery})`, 'gi');
        return text.split(regex).map((part, index) =>
            part.toLowerCase() === query.toLowerCase()
                ? <span key={index} className="bg-[#FFBF00]/20 font-bold">{part}</span>
                : part
        );
    };



    return (
        <div
            className={`group cursor-pointer relative py-5 flex gap-6 transition-opacity border-b border-dashed border-gray-200 last:border-none`}
            onClick={() => onSelect(article)}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            {/* 1. 左侧封面图 - 移动到左边，并调整比例 */}
            {article.coverImage && (
                <div className="size-[88px] flex-shrink-0 overflow-hidden rounded-sm">
                    <img
                        src={article.coverImage}
                        alt={article.title}
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                </div>
            )}

            {/* 2. 右侧内容区 */}
            <div className="flex-1 min-w-0 flex flex-col justify-between">
                <div>
                    {/* 标题 - 加粗，颜色加深 */}
                    <h3 className={`font-bold line-clamp-1 ${isSelected && 'text-primary'} ${article.isRead ? "text-gray-400" : "text-gray-800"
                        }`}>
                        {highlightText(article.title, searchQuery)}
                    </h3>

                    {/* 正文预览 - 增加蓝色引号 */}
                    <div className="relative pt-4 pl-3">
                        <span className="absolute left-0 top-1 text-primary text-3xl font-serif mt-[-2px]">“</span>
                        <p className={`text-sm line-clamp-1 ${article.isRead ? "text-gray-400" : "text-gray-500"
                            }`}>
                            {highlightText(article.content, searchQuery)}
                        </p>
                    </div>
                </div>

                {/* 3. 底部元信息 - 来源和时间 */}
                <div className="flex items-center justify-between mt-4 relative">
                    <div className="flex items-center gap-2 text-xs">
                        <div className="size-4 overflow-hidden">
                            <img
                                src={article.sourceAvatar}
                                alt=""
                                className="w-full h-full object-cover"
                            />
                        </div>
                        <span className="text-gray-800 max-w-40 truncate">{article.sourceName}</span>
                        <span className="text-gray-400">|</span>
                        <span className="text-gray-400">{formatTime(article.publishedAt)}</span>
                    </div>

                    {/* 4. Hover 操作按钮 - 按照截图移动到右下角 */}
                    <div className={`absolute right-0 flex items-center gap-3 animate-in fade-in slide-in-from-right-1 transition-opacity ${hovered ? "opacity-100" : "opacity-0"}`}>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onSelect(article);
                            }}
                            className=" rounded-full bg-gray-50 flex items-center justify-center size-8 text-gray-800 hover:bg-gray-100 transition-colors cursor-pointer"
                            title="阅读详情"
                        >
                            <BookOpen className="size-3.5" />
                        </button>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                // TODO: implement share
                            }}
                            className=" rounded-full bg-gray-50 flex items-center justify-center size-8 text-gray-800 hover:bg-gray-100 transition-colors cursor-pointer"
                            title="分享"
                        >
                            <SquareArrowOutUpLeftIcon className="size-3.5" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}