import { useQuery } from "@tanstack/react-query";
import { Dropdown, DropdownItem } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Article, getArticleDetailApi } from "~/api/channels";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn, copyText } from "~/utils";
import { mapToArticle } from "../ArticleList/ArticleList";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";
import { ArticleAiDock } from "../AiChat/ArticleAiDock";
import { ArticleDetail } from "./ArticleDetail";

/**
 * Standalone article page rendered at /channel/:channelId/article/:articleId.
 * Opened in a new browser tab from mobile article-card clicks and PC fullscreen button.
 *
 * PC: renders the full ArticleDetail layout (header + toolbar + iframe) — identical to
 *   the in-app fullscreen view, just hosted at its own URL.
 * Mobile: renders a bare iframe of the article body with a floating top-right menu
 *   (分享 / 原网页 / 加入知识空间) that fades on scroll.
 */
export default function ArticlePage() {
    const { channelId, articleId } = useParams<{ channelId: string; articleId: string }>();
    const localize = useLocalize();
    const navigate = useNavigate();
    const isH5 = usePrefersMobileLayout();
    const { showToast } = useToastContext();
    const [scrolled, setScrolled] = useState(false);
    const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
    const iframeRef = useRef<HTMLIFrameElement>(null);

    const { data: rawArticle, isLoading, isError } = useQuery({
        queryKey: ["articleDetail", articleId, channelId],
        queryFn: () => getArticleDetailApi(articleId!, channelId!),
        enabled: !!articleId && !!channelId,
        staleTime: 60_000,
    });

    const article: Article | null = useMemo(() => {
        if (!rawArticle || !channelId) return null;
        return mapToArticle(rawArticle, channelId);
    }, [rawArticle, channelId]);

    // Save the document title on first mount and restore it on unmount, so navigating back
    // (after the H5 in-tab jump from ChannelLayout) returns the page to its original title
    // instead of leaving "<article title>" stuck in the browser tab.
    useEffect(() => {
        const previousTitle = document.title;
        return () => {
            document.title = previousTitle;
        };
    }, []);

    useEffect(() => {
        if (article?.title) document.title = article.title;
    }, [article?.title]);

    // H5 only: track iframe scroll so the floating menu can fade out.
    useEffect(() => {
        if (!isH5) return;
        const iframe = iframeRef.current;
        if (!iframe) return;
        let cleanup: (() => void) | undefined;
        const bind = () => {
            cleanup?.();
            const win = iframe.contentWindow;
            if (!win) return;
            let previousY = Math.max(0, win.scrollY);
            setScrolled(false);
            const onScroll = () => {
                const currentY = Math.max(0, win.scrollY);
                if (currentY <= 40) {
                    setScrolled(false);
                    previousY = currentY;
                } else if (Math.abs(currentY - previousY) >= 4) {
                    setScrolled(currentY > previousY);
                    previousY = currentY;
                }
            };
            win.addEventListener("scroll", onScroll, { passive: true });
            cleanup = () => win.removeEventListener("scroll", onScroll);
        };
        iframe.addEventListener("load", bind);
        if (iframe.contentDocument?.readyState === "complete") bind();
        return () => {
            iframe.removeEventListener("load", bind);
            cleanup?.();
        };
    }, [isH5, isLoading, article?.id, article?.content_html]);

    const handleShare = async () => {
        if (!channelId || !articleId) return;
        const url = buildClientShareUrl(`/channel/${channelId}/article/${articleId}`);
        try {
            await copyText(url);
            showToast({
                message: localize("com_subscription.share_link_copied"),
                status: "success",
            });
        } catch {
            showToast({
                message: localize("com_subscription.copy_failed_retry"),
                status: "warning",
            });
        }
    };

    const handleOpenOriginal = () => {
        if (!article?.url) {
            showToast({
                message: localize("com_subscription.no_original_link"),
                status: "warning",
            });
            return;
        }
        window.open(article.url, "_blank", "noopener,noreferrer");
    };

    if (isLoading) {
        return (
            <div className="flex h-screen items-center justify-center bg-white">
                <LoadingIcon className="size-20 text-primary" />
            </div>
        );
    }

    if (isError || !article) {
        return (
            <div className="flex h-screen items-center justify-center bg-white text-sm text-text-3">
                {localize("com_subscription.channel_invalid_or_inaccessible")}
            </div>
        );
    }

    // === PC: identical to the in-app fullscreen view (centered ArticleDetail) ===
    if (!isH5) {
        return (
            <div className="relative flex h-screen w-screen overflow-hidden bg-white">
                <div className="mx-auto h-full w-full max-w-[1000px]">
                    <ArticleDetail
                        screenFull
                        showFullScreenBtn={false}
                        article={article}
                    />
                </div>
            </div>
        );
    }

    // === H5: bare iframe + floating menu ===
    const articleHtml = article.content_html || "";
    const processedHtml = `<!DOCTYPE html>
<html>
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <style>
            html { background: #fff !important; scrollbar-width: none; }
            html::-webkit-scrollbar { display: none; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                    "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
                line-height: 1.7;
                color: #333;
                /* Extra bottom padding so the last paragraph isn't hidden behind the AI dock
                   pinned to the page bottom. !important to override inline styles injected
                   by source documents (e.g. WeChat) that re-declare body padding. */
                padding: 20px 20px calc(160px + env(safe-area-inset-bottom, 0px)) !important;
                padding-bottom: calc(160px + env(safe-area-inset-bottom, 0px)) !important;
                background: #fff !important;
            }
            /* Source documents often wrap their content in #js_content / .rich_media_*
               with their own padding. Zero those out, then ensure the outermost wrapper
               also gets the dock-safe bottom space (in case body padding gets clipped). */
            #js_content,
            .rich_media_area_primary,
            .rich_media_content {
                padding-bottom: calc(160px + env(safe-area-inset-bottom, 0px)) !important;
            }
            img { max-width: 100%; height: auto; }
            a { color: #335CFF; }
        </style>
    </head>
    <body>
        ${articleHtml}
        <script>
            document.querySelectorAll('a').forEach(a => {
                a.setAttribute('target', '_blank');
                a.setAttribute('rel', 'noopener noreferrer');
            });
        </script>
    </body>
</html>`;

    return (
        <div className="relative h-screen w-screen bg-white">
            <iframe
                ref={iframeRef}
                title={article.title}
                srcDoc={processedHtml}
                className="absolute inset-0 size-full border-0"
            />

            {/* Both floating actions share the same scroll-direction visibility. */}
            <div
                className={cn(
                    "fixed left-4 top-[calc(env(safe-area-inset-top,0px)+12px)] z-10 transition-opacity duration-300 motion-reduce:transition-none",
                    scrolled ? "invisible pointer-events-none opacity-0" : "opacity-100",
                )}
            >
                <button
                    type="button"
                    aria-label={localize("com_ui_go_back")}
                    onClick={() => navigate(`/channel/${encodeURIComponent(channelId!)}`, { replace: true })}
                    className="workbench-menu-trigger relative inline-flex size-9 items-center justify-center rounded-xl border border-black/5 bg-white/70 text-text-1 shadow-[0_2px_8px_rgba(0,0,0,0.06)] transition-colors hover:bg-white/85"
                >
                    <Outlined.ArrowLeft className="size-5" />
                </button>
            </div>
            <div
                className={cn(
                    "fixed right-4 top-[calc(env(safe-area-inset-top,0px)+12px)] z-10 transition-opacity duration-300 motion-reduce:transition-none",
                    scrolled ? "invisible pointer-events-none opacity-0" : "opacity-100",
                )}
            >
                <Dropdown
                    align="end"
                    menu={
                        <>
                            <DropdownItem icon={<Outlined.Share />} onSelect={handleShare}>
                                {localize("com_subscription.share")}
                            </DropdownItem>
                            <DropdownItem icon={<Outlined.Earth />} onSelect={handleOpenOriginal}>
                                {localize("com_subscription.original_webpage")}
                            </DropdownItem>
                            <DropdownItem
                                icon={<Outlined.AddToKnowledgeBase />}
                                onSelect={() => setShowKnowledgeModal(true)}
                            >
                                {localize("com_subscription.add_to_knowledge_space")}
                            </DropdownItem>
                        </>
                    }
                >
                    <button
                        type="button"
                        className="inline-flex size-9 items-center justify-center rounded-xl border border-black/5 bg-white/70 text-text-1 shadow-[0_2px_8px_rgba(0,0,0,0.06)] transition-colors hover:bg-white/85"
                        aria-label={localize("com_subscription.channel_settings")}
                    >
                        <Outlined.MoreCircle className="size-5" />
                    </button>
                </Dropdown>
            </div>

            {/* AI dock pinned to the bottom — parity with the PC article view.
                The dock is self-contained (absolute inset-x-0 bottom-0), so dropping
                it inside the relative container is enough; collapsed it shows a
                floating input box with a gradient fade above, expanded it grows a
                440px chat panel upward over the iframe content. */}
            <ArticleAiDock articleDocId={article.id} article={article} />

            <AddToKnowledgeModal
                open={showKnowledgeModal}
                onOpenChange={setShowKnowledgeModal}
                articleId={article.id}
            />
        </div>
    );
}
