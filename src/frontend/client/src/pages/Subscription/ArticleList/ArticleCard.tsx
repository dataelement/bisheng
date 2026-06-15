import { useLocalize } from "~/hooks";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { Article } from "~/api/channels";
import { useArticleShare } from "../hooks/useArticleShare";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { copyText } from "~/utils";
import { AddToKnowledgeModal } from "../Article/AddToKnowledgeModal";
import { ChannelQuoteIcon } from "~/components/icons/channels";
import { useAuthContext } from "~/hooks/AuthContext";
import { cn } from "~/utils";

/**
 * The backend crawler reuses a source's `icon` as the article `cover_image`.
 * For web sources that "icon" is not a genuine article image but the site's
 * favicon / logo / nav graphic (e.g. `gtj2023_nav_circle.png`, `aiwen_logo.gif`)
 * or a generic placeholder (e.g. `placeholder.png`). We hide those so cards with
 * no real cover render text-only (matching the design), using two heuristics:
 *
 * 1. URL keywords — site assets are named logo/favicon/nav-circle/placeholder/etc,
 *    whereas real covers (e.g. mmbiz.qpic.cn) use opaque hashed filenames. Matching
 *    by URL lets us hide synchronously (no load flash) and also catches large logos
 *    that the size check below would miss (the stats.gov.cn logo is 600x600).
 * 2. Natural size — real covers are large; anything smaller than the display box
 *    (and thus upscaled/blurry) is treated as a non-cover. Acts as a fallback for
 *    junk images whose URL doesn't match the keyword list.
 */
const JUNK_COVER_URL_PATTERN = /(?:logo|favicon|placeholder|sprite|nav[-_]?circle|(?:^|[\/_.-])icon(?:[\/_.-]|$)|default[-_]?(?:image|img|avatar))/i;
const MIN_COVER_DIMENSION = 200;

const COVER_IMG_CLASS = "h-full w-full object-cover transition-transform duration-300 ease-in-out fine-pointer:group-hover:scale-105";

/** Derive a site favicon URL (origin + /favicon.ico) from an article page URL. */
function getFaviconUrl(pageUrl?: string): string {
    if (!pageUrl) return "";
    try {
        return `${new URL(pageUrl, window.location.origin).origin}/favicon.ico`;
    } catch {
        return "";
    }
}

interface CoverThumbnailProps {
    src?: string;
    alt: string;
    /** Source's curated icon (source_icon) — preferred placeholder so the cover matches the
     *  source avatar shown elsewhere on the card. */
    fallbackIcon?: string;
    /** Article page URL — used to derive a site-favicon placeholder when no source icon exists. */
    fallbackUrl?: string;
    /** Wrapper sizing/rounding — differs between grid (100px) and list (88px) cards. */
    containerClassName: string;
}

/**
 * Article cover image. When the real cover is missing, broken, too small, or a site
 * icon/placeholder, it falls back to a placeholder so every card shows a cover instead of
 * an empty slot. The placeholder prefers the source's curated icon (so it matches the
 * source avatar on the card), then the site favicon, and finally a globe icon. The
 * placeholder is rendered as a crisp 32x32 mark over a blurred, enlarged copy of itself.
 */
function CoverThumbnail({ src, alt, fallbackIcon, fallbackUrl, containerClassName }: CoverThumbnailProps) {
    const [coverFailed, setCoverFailed] = useState(false);
    const [placeholderFailed, setPlaceholderFailed] = useState(false);

    const placeholderSrc = fallbackIcon || getFaviconUrl(fallbackUrl);

    // Reset when the source changes (card instance reused for a different article).
    useEffect(() => {
        setCoverFailed(false);
        setPlaceholderFailed(false);
    }, [src, placeholderSrc]);

    const coverUsable = !!src && !coverFailed && !JUNK_COVER_URL_PATTERN.test(src);

    if (coverUsable) {
        return (
            <div className={containerClassName}>
                <img
                    src={src}
                    alt={alt}
                    className={COVER_IMG_CLASS}
                    onError={() => setCoverFailed(true)}
                    onLoad={(e) => {
                        const img = e.currentTarget;
                        if (img.naturalWidth < MIN_COVER_DIMENSION || img.naturalHeight < MIN_COVER_DIMENSION) {
                            setCoverFailed(true);
                        }
                    }}
                />
            </div>
        );
    }

    return (
        <div className={cn(containerClassName, "relative flex items-center justify-center bg-white")}>
            {placeholderSrc && !placeholderFailed ? (
                <>
                    {/* Backdrop: same icon scaled to fill the frame and heavily blurred, at 50%
                        opacity so the white frame background shows through. */}
                    <img
                        src={placeholderSrc}
                        alt=""
                        aria-hidden
                        className="absolute inset-0 h-full w-full scale-150 object-cover opacity-50 blur-lg"
                    />
                    {/* Foreground: crisp 32x32 icon centered on top. */}
                    <img
                        src={placeholderSrc}
                        alt=""
                        className="relative size-8 object-contain"
                        onError={() => setPlaceholderFailed(true)}
                    />
                </>
            ) : (
                <Outlined.Earth className="size-8 text-[#C9CDD4]" />
            )}
        </div>
    );
}

/**
 * Small source icon for the card meta row. Mirrors the cover fallback chain so the
 * avatar is never blank: source's curated icon -> site favicon -> globe icon.
 * Renders the inner element only; the caller provides the sized/clipped wrapper.
 */
function SourceAvatar({ src, fallbackUrl }: { src?: string; fallbackUrl?: string }) {
    const iconSrc = src || getFaviconUrl(fallbackUrl);
    const [failed, setFailed] = useState(false);
    useEffect(() => { setFailed(false); }, [iconSrc]);

    if (!iconSrc || failed) {
        return <Outlined.Earth className="h-full w-full text-[#C9CDD4]" />;
    }
    return (
        <img
            src={iconSrc}
            alt=""
            className="h-full w-full object-cover"
            onError={() => setFailed(true)}
        />
    );
}

interface ArticleCardProps {
    article: Article;
    onSelect: (article: Article) => void;
    isSelected: boolean;
    searchQuery?: string;
    /** When false, hides add-to-knowledge and share (e.g. channel plaza preview drawer). */
    showArticleActions?: boolean;
    /** 'list' = reading-mode single column (cover left); 'grid' = browse-mode two columns (thumbnail right). */
    variant?: 'list' | 'grid';
}

export function ArticleCard({
    article,
    onSelect,
    isSelected,
    searchQuery,
    showArticleActions = true,
    variant = 'list',
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
    const sensitiveViolated = article.sensitiveReview?.violated === true;
    const canViewArticle = article.sensitiveReview?.can_view !== false;

    // Shared meta row (source favicon + name + separator + time)
    const metaRow = (
        <div className="flex items-center gap-2 text-xs text-[#999]">
            <div className="size-4 shrink-0 overflow-hidden rounded-sm">
                <SourceAvatar src={article.sourceAvatar} fallbackUrl={article.url} />
            </div>
            <span className="max-w-40 truncate max-[767px]:text-[#212121]">{article.sourceName}</span>
            <span className="mx-0.5 h-2.5 w-px shrink-0 bg-[#E0E0E0]" aria-hidden />
            <span className="shrink-0">{formatTime(article.publishedAt)}</span>
        </div>
    );

    // Browse-mode grid card: content left, 100x100 thumbnail right, single-line description.
    // Coarse-pointer (mobile) tweaks: dashed divider, always-visible action buttons w/ no bg, bumped title size.
    if (variant === 'grid') {
        return (
            <>
                <div
                    className="group relative flex cursor-pointer gap-6 min-[768px]:h-[120px] min-[768px]:overflow-hidden min-[768px]:py-4 max-[767px]:h-[100px] max-[767px]:overflow-hidden max-[767px]:border-b max-[767px]:border-dashed max-[767px]:border-[#E0E0E0] max-[767px]:py-3"
                    onClick={() => onSelect(article)}
                >
                    {/* Left content */}
                    <div className="flex min-w-0 flex-1 flex-col gap-3 max-[767px]:gap-1">
                        <div className="flex min-w-0 items-center gap-2">
                            <h3
                                className={cn(
                                    "min-w-0 flex-1 line-clamp-2 text-[16px] leading-[22px] font-medium max-[767px]:text-[14px] [&_em]:not-italic [&_em]:bg-[#FFBF00]/20 [&_em]:font-medium",
                                    isSelected ? "text-primary" : "fine-pointer:group-hover:text-primary",
                                    article.isRead ? "text-[#989898]" : "text-[#212121]",
                                )}
                            >
                                {highlightTitle
                                    ? <span dangerouslySetInnerHTML={{ __html: highlightTitle }} />
                                    : article.title}
                            </h3>
                            {sensitiveViolated && (
                                <span className="shrink-0 rounded-sm border border-[#F53F3F]/30 bg-[#F53F3F]/10 px-1.5 py-0.5 text-xs leading-4 text-[#F53F3F]">
                                    {localize("com_subscription.sensitive_review")}
                                </span>
                            )}
                        </div>

                        <div className="relative mt-auto flex items-center justify-between">
                            {metaRow}
                            {showArticleActions && canViewArticle && (
                                <div className="absolute right-0 flex items-center gap-1 max-[767px]:static max-[767px]:gap-2">
                                    {hasKnowledge && (
                                        <button
                                            onClick={(e) => { e.stopPropagation(); setShowKnowledgeModal(true); }}
                                            className="flex size-8 cursor-pointer items-center justify-center rounded-full text-[#999] transition-colors group-hover:text-[#212121] hover:bg-[#f7f7f7] max-[767px]:size-5 max-[767px]:rounded-none max-[767px]:text-[#818181] max-[767px]:hover:bg-transparent"
                                            title={localize("com_subscription.add_to_knowledge_space")}
                                        >
                                            <Outlined.AddToKnowledgeBase className="size-3.5" />
                                        </button>
                                    )}
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleShare(article);
                                            const shareText = localize("com_subscription.reading_article_share", { title: article.title, url: article.url });
                                            copyText(shareText)
                                                .then(() => showToast({ message: localize("com_subscription.share_link_copied"), severity: NotificationSeverity.SUCCESS }))
                                                .catch(() => showToast({ message: localize("com_subscription.copy_failed_retry"), severity: NotificationSeverity.ERROR }));
                                        }}
                                        className="flex size-8 cursor-pointer items-center justify-center rounded-full text-[#999] transition-colors group-hover:text-[#212121] hover:bg-[#f7f7f7] max-[767px]:size-5 max-[767px]:rounded-none max-[767px]:text-[#818181] max-[767px]:hover:bg-transparent"
                                        title={localize("com_subscription.share")}
                                    >
                                        <Outlined.Share className="size-3.5" />
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Right thumbnail — real cover when available, otherwise a site-favicon
                        placeholder, so every card has a cover and the action buttons keep a
                        constant x position regardless of cover presence. */}
                    <CoverThumbnail
                        src={article.coverImage}
                        fallbackIcon={article.sourceAvatar}
                        fallbackUrl={article.url}
                        alt={article.title}
                        containerClassName="shrink-0 overflow-hidden rounded min-[768px]:size-[88px] max-[767px]:size-16 max-[767px]:self-end"
                    />
                </div>

                <AddToKnowledgeModal
                    open={showKnowledgeModal}
                    onOpenChange={setShowKnowledgeModal}
                    articleId={article.id}
                />
            </>
        );
    }

    return (
        <>
        <div
            className={cn(
                "group relative flex cursor-pointer gap-6 border-b border-dashed border-[#E0E0E0] py-5 last:border-none",
            )}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onClick={() => onSelect(article)}
        >
            {/* 1. 左侧封面：仅在有真实配图时显示；站点 icon / 占位图等会被自动隐藏 */}
            {article.coverImage && (
                <CoverThumbnail
                    src={article.coverImage}
                    fallbackIcon={article.sourceAvatar}
                    fallbackUrl={article.url}
                    alt={article.title}
                    containerClassName="size-[88px] flex-shrink-0 overflow-hidden rounded-sm"
                />
            )}

            {/* 2. 右侧内容区 */}
            <div className="flex-1 min-w-0 flex flex-col justify-between">
                <div>
                    {/* 标题 - 搜索时使用 highlight HTML，非搜索时纯文本 */}
                    <div className="flex min-w-0 items-center gap-2">
                        <h3 className={cn(
                            "min-w-0 flex-1 truncate font-medium [&_em]:not-italic [&_em]:bg-[#FFBF00]/20 [&_em]:font-medium",
                            isSelected ? "text-primary" : "fine-pointer:group-hover:text-primary",
                            article.isRead ? "text-[#989898]" : "text-gray-800",
                        )}
                        >
                            {highlightTitle
                                ? <span dangerouslySetInnerHTML={{ __html: highlightTitle }} />
                                : article.title}
                        </h3>
                        {sensitiveViolated && (
                            <span className="shrink-0 rounded-sm border border-[#F53F3F]/30 bg-[#F53F3F]/10 px-1.5 py-0.5 text-xs leading-4 text-[#F53F3F]">
                                {localize("com_subscription.sensitive_review")}
                            </span>
                        )}
                    </div>

                    {/* 正文预览 - 增加蓝色引号 */}
                    <div className="relative pt-4 pl-3">
                        <ChannelQuoteIcon className="absolute left-0 top-1 mt-[-2px] h-5 w-5" />
                        <p className={cn(
                            "text-sm line-clamp-1 leading-snug [&_em]:not-italic [&_em]:bg-[#FFBF00]/20 [&_em]:font-bold",
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
                <div className="relative mt-4 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-xs text-[#999]">
                        <div className="size-4 shrink-0 overflow-hidden">
                            <SourceAvatar src={article.sourceAvatar} fallbackUrl={article.url} />
                        </div>
                        <span className="max-w-40 truncate">{article.sourceName}</span>
                        <span className="mx-0.5 h-2.5 w-px shrink-0 bg-[#E0E0E0]" aria-hidden />
                        <span>{formatTime(article.publishedAt)}</span>
                    </div>

                    {showArticleActions && canViewArticle && (
                        <div
                            className={cn(
                                "flex items-center gap-3 transition-opacity",
                                // Touch / coarse pointer: actions always visible; fine pointer (incl. narrow desktop): hover on card.
                                "max-[767px]:static max-[767px]:opacity-100 max-[767px]:pointer-events-auto",
                                "fine-pointer:pointer-events-none fine-pointer:absolute fine-pointer:right-0 fine-pointer:opacity-0 fine-pointer:group-hover:pointer-events-auto fine-pointer:group-hover:opacity-100",
                            )}
                        >
                            {hasKnowledge && (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setShowKnowledgeModal(true);
                                    }}
                                    className="rounded-full flex size-8 cursor-pointer items-center justify-center text-[#999] transition-colors group-hover:text-[#212121] hover:bg-[#f7f7f7]"
                                    title={localize("com_subscription.add_to_knowledge_space")}
                                >
                                    <Outlined.AddToKnowledgeBase className="size-3.5" />
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
                                className="rounded-full flex size-8 cursor-pointer items-center justify-center text-[#999] transition-colors group-hover:text-[#212121] hover:bg-[#f7f7f7]"
                                title={localize("com_subscription.share")}
                            >
                                <Outlined.Share className="size-3.5" />
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
