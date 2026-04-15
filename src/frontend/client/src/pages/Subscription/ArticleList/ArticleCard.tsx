import { useLocalize } from "~/hooks";
import BookPlusIcon from "~/components/ui/icon/BookPlus";
import { useState } from "react";
import { Article } from "~/api/channels";
import { useArticleShare } from "../hooks/useArticleShare";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { copyText } from "~/utils";
import { AddSpaceIcon, ShareOutlineIcon } from "~/components/icons";
import { AddToKnowledgeModal } from "../Article/AddToKnowledgeModal";
import { ChannelQuoteIcon } from "~/components/icons/channels";
import { useAuthContext } from "~/hooks/AuthContext";
import { ArticleFaviconCoverPlaceholder } from "./ArticleFaviconCoverPlaceholder";
import { cn } from "~/utils";

interface ArticleCardProps {
    article: Article;
    onSelect: (article: Article) => void;
    isSelected: boolean;
    searchQuery?: string;
    /** When false, hides add-to-knowledge and share (e.g. channel plaza preview drawer). */
    showArticleActions?: boolean;
}

export function ArticleCard({
    article,
    onSelect,
    isSelected,
    searchQuery,
    showArticleActions = true,
}: ArticleCardProps) {
    const localize = useLocalize();
    const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
    const { handleShare } = useArticleShare();
    const { showToast } = useToastContext();
    const { user } = useAuthContext();
    const hasKnowledge = Array.isArray((user as any)?.plugins)
        ? ((user as any).plugins as string[]).includes('knowledge_space')
        : true;

    // 格式化时间逻辑保持不变
    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        const now = new Date();
        // Use calendar date difference (strip time) to handle cross-day correctly
        const todayDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const articleDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const diffDays = Math.round((todayDate.getTime() - articleDate.getTime()) / (1000 * 60 * 60 * 24));

        if (diffDays === 0) return localize("com_subscription.updated_today");
        if (diffDays >= 1 && diffDays <= 7) return localize("com_subscription.days_ago", { diffDays });
        return date.toISOString().split('T')[0];
    };

    // Strip HTML tags for plain text display (used for content highlight snippets)
    const stripTags = (html: string) => html.replace(/<(?!em|\/em)[^>]*>/g, '').replace(/&[a-zA-Z]+;/g, ' ').replace(/&#\d+;/g, ' ').trim();

    // Check if backend returned highlight data for this article
    const hasHighlight = !!searchQuery && !!article.highlight;
    const highlightTitle = hasHighlight && article.highlight?.title?.[0];
    const highlightContent = hasHighlight && article.highlight?.content?.length
        ? stripTags(article.highlight.content.join(''))
        : null;

    return (
        <>
        <div
            className={cn(
                "group relative flex cursor-pointer gap-6 border-b border-dashed border-[#E0E0E0] py-5 last:border-none",
                "max-md:gap-4 max-md:border-solid max-md:border-[#E3E3E3] max-md:py-4",
            )}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onClick={() => onSelect(article)}
        >
            {/* 1. 左侧封面：有配图用封面；无配图用信源 ico 双层模糊占位 */}
            {article.coverImage ? (
                <div className="size-[88px] flex-shrink-0 overflow-hidden rounded-sm">
                    <img
                        src={article.coverImage}
                        alt={article.title}
                        className="h-full w-full object-cover transition-transform duration-300 ease-in-out group-hover:scale-105"
                    />
                </div>
            ) : (
                <ArticleFaviconCoverPlaceholder
                    iconUrl={article.sourceAvatar}
                    alt={article.sourceName}
                />
            )}

            {/* 2. 右侧内容区 */}
            <div className="flex-1 min-w-0 flex flex-col justify-between">
                <div>
                    {/* 标题 - 搜索时使用 highlight HTML，非搜索时纯文本 */}
                    <h3 className={cn(
                        "font-medium line-clamp-1 [&_em]:not-italic [&_em]:bg-[#FFBF00]/20 [&_em]:font-medium",
                        isSelected ? "text-primary" : "group-hover:text-primary",
                        article.isRead ? "text-[#989898]" : "text-gray-800 max-md:text-[#212121] max-md:font-medium",
                    )}
                    >
                        {highlightTitle
                            ? <span dangerouslySetInnerHTML={{ __html: highlightTitle }} />
                            : article.title}
                    </h3>

                    {/* 正文预览 - 增加蓝色引号 */}
                    <div className="relative pt-4 pl-3 max-md:pt-3">
                        <ChannelQuoteIcon className="absolute left-0 top-1 mt-[-2px] h-5 w-5" />
                        <p className={cn(
                            "text-sm line-clamp-1 leading-snug [&_em]:not-italic [&_em]:bg-[#FFBF00]/20 [&_em]:font-bold",
                            "max-md:line-clamp-2 max-md:text-[#595959]",
                            article.isRead ? "text-gray-400" : "text-gray-500",
                        )}
                        >
                            {highlightContent
                                ? <span dangerouslySetInnerHTML={{ __html: highlightContent }} />
                                : article.content}
                        </p>
                    </div>
                </div>

                {/* 3. 底部元信息 - 来源和时间 */}
                <div className="relative mt-4 flex items-center justify-between max-md:mt-3">
                    <div className="flex items-center gap-2 text-xs text-[#999] max-md:text-[#999999]">
                        <div className="size-4 shrink-0 overflow-hidden">
                            <img
                                src={article.sourceAvatar}
                                alt=""
                                className="h-full w-full object-cover"
                            />
                        </div>
                        <span className="max-w-40 truncate">{article.sourceName}</span>
                        <span className="mx-0.5 h-2.5 w-px shrink-0 bg-[#E0E0E0] max-md:h-3 max-md:bg-[#E5E5E5]" aria-hidden />
                        <span>{formatTime(article.publishedAt)}</span>
                    </div>

                    {showArticleActions && (
                        <div
                            className={cn(
                                "flex items-center gap-3 transition-opacity",
                                "max-md:static max-md:opacity-100 max-md:pointer-events-auto",
                                "md:pointer-events-none md:absolute md:right-0 md:opacity-0 md:group-hover:pointer-events-auto md:group-hover:opacity-100",
                            )}
                        >
                            {hasKnowledge && (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setShowKnowledgeModal(true);
                                    }}
                                    className=" rounded-full bg-gray-50 flex items-center justify-center size-8 text-gray-800 hover:bg-gray-100 transition-colors cursor-pointer"
                                    title={localize("com_subscription.add_to_knowledge_space")}
                                >
                                    <BookPlusIcon className="size-3.5" />
                                </button>
                            )}
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleShare(article);
                                    const shareText = localize("com_subscription.reading_article_share", {
                                        title: article.title,
                                        url: article.url,
                                    });
                                    copyText(shareText)
                                        .then(() => {
                                            showToast({
                                                message: localize("com_subscription.share_link_copied"),
                                                severity: NotificationSeverity.SUCCESS,
                                            });
                                        })
                                        .catch(() => {
                                            showToast({
                                                message: localize("com_subscription.copy_failed_retry"),
                                                severity: NotificationSeverity.ERROR,
                                            });
                                        });
                                }}
                                className=" rounded-full bg-gray-50 flex items-center justify-center size-8 text-gray-800 hover:bg-gray-100 transition-colors cursor-pointer"
                                title={localize("com_subscription.share")}
                            >
                                <ShareOutlineIcon className="size-3.5" />
                            </button>
                        </div>
                    )}
                </div>
            </div>
            </div>

            {/* Add to Knowledge Space Modal — rendered outside the card to avoid interaction interference */}
            <AddToKnowledgeModal
                open={showKnowledgeModal}
                onOpenChange={setShowKnowledgeModal}
                articleId={article.id}
            />
        </>
    );
}