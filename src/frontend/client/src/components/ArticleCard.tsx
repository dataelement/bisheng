import { Share2, BookPlus } from "lucide-react";
import { Avatar, AvatarImage } from "~/components/ui/avatar";
import { Article } from "~/api/channels";
import { useState } from "react";

interface ArticleCardProps {
    article: Article;
    onSelect: (article: Article) => void;
    isSelected: boolean;
}

export function ArticleCard({ article, onSelect, isSelected }: ArticleCardProps) {
    const [hovered, setHovered] = useState(false);

    // 格式化时间
    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));

        // 判断是否是今天
        const isToday = date.toDateString() === now.toDateString();

        if (isToday) {
            return "今日更新";
        } else if (diffDays >=2 && diffDays <= 7) {
            return `${diffDays}天前`;
        } else {
            return date.toISOString().split('T')[0]; // YYYY-MM-DD
        }
    };

    return (
        <div
            className={`group relative p-4 border rounded-lg cursor-pointer transition-all ${
                isSelected
                    ? "border-[#165dff] bg-[#f5f9ff]"
                    : "border-[#e5e6eb] hover:border-[#c9cdd4] hover:shadow-sm"
            } ${article.isRead ? "opacity-60" : ""}`}
            onClick={() => onSelect(article)}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            <div className="flex gap-4">
                {/* 左侧内容 */}
                <div className="flex-1 min-w-0">
                    {/* 信息源和时间 */}
                    <div className="flex items-center gap-2 mb-2">
                        <Avatar className="size-5">
                            <AvatarImage src={article.sourceAvatar || "/default-source.png"} alt={article.sourceName} />
                        </Avatar>
                        <span className={`text-[12px] truncate max-w-[120px] ${
                            article.isRead ? "text-[#c9cdd4]" : "text-[#4e5969]"
                        }`}>
                            {article.sourceName}
                        </span>
                        <span className="text-[12px] text-[#c9cdd4]">
                            {formatTime(article.publishedAt)}
                        </span>
                    </div>

                    {/* 标题 */}
                    <h3 className={`text-[16px] font-medium mb-2 line-clamp-2 ${
                        article.isRead ? "text-[#c9cdd4]" : "text-[#1d2129]"
                    }`}>
                        {article.title}
                    </h3>

                    {/* 正文预览 */}
                    <p className={`text-[14px] line-clamp-2 ${
                        article.isRead ? "text-[#e5e6eb]" : "text-[#86909c]"
                    }`}>
                        {article.content}
                    </p>
                </div>

                {/* 右侧封面图 */}
                {article.coverImage && (
                    <div className="w-[120px] h-[90px] flex-shrink-0">
                        <img
                            src={article.coverImage}
                            alt={article.title}
                            className="w-full h-full object-cover rounded"
                        />
                    </div>
                )}
            </div>

            {/* Hover 操作按钮 */}
            {hovered && !isSelected && (
                <div className="absolute top-4 right-4 flex items-center gap-2">
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            console.log("分享文章", article.id);
                        }}
                        className="p-2 bg-white border border-[#e5e6eb] rounded hover:border-[#165dff] hover:text-[#165dff] transition-colors"
                    >
                        <Share2 className="size-4" />
                    </button>
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            console.log("加入知识空间", article.id);
                        }}
                        className="p-2 bg-white border border-[#e5e6eb] rounded hover:border-[#165dff] hover:text-[#165dff] transition-colors"
                    >
                        <BookPlus className="size-4" />
                    </button>
                </div>
            )}
        </div>
    );
}
