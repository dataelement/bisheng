import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Article, getArticleDetailApi } from "~/api/channels";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn, copyText } from "~/utils";
import { mapToArticle } from "../ArticleList/ArticleList";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";
import { ArticleDetail } from "./ArticleDetail";

/**
 * Standalone article page rendered at /channel/:channelId/article/:articleId.
 * Opened in a new browser tab from mobile article-card clicks and PC fullscreen button.
 *
 * PC: renders the full ArticleDetail layout (header + toolbar + iframe) — identical to
 *   the in-app fullscreen view, just hosted at its own URL.
 * Mobile: renders a bare iframe of the article body with a floating top-right menu
 *   (分享 / 下载 / 原网页 / 加入知识空间) that fades on scroll.
 */
export default function ArticlePage() {
    const { channelId, articleId } = useParams<{ channelId: string; articleId: string }>();
    const localize = useLocalize();
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
            const win = iframe.contentWindow;
            if (!win) return;
            const onScroll = () => setScrolled(win.scrollY > 40);
            onScroll();
            win.addEventListener("scroll", onScroll, { passive: true });
            cleanup = () => win.removeEventListener("scroll", onScroll);
        };
        iframe.addEventListener("load", bind);
        if (iframe.contentDocument?.readyState === "complete") bind();
        return () => {
            iframe.removeEventListener("load", bind);
            cleanup?.();
        };
    }, [isH5, article?.content_html]);

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
                status: "error",
            });
        }
    };

    const handleDownload = () => {
        if (!article) return;
        const safeName = (article.title || "article").replace(/[\\/:*?"<>|]/g, "_");
        const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escapeHtml(article.title || "")}</title></head><body><h1 style="font-family:sans-serif;line-height:1.4">${escapeHtml(article.title || "")}</h1>${article.content_html || ""}</body></html>`;
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeName}.html`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
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
                <LoadingIcon className="size-12 text-primary" />
            </div>
        );
    }

    if (isError || !article) {
        return (
            <div className="flex h-screen items-center justify-center bg-white text-sm text-[#86909C]">
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
                padding: 20px;
                background: #fff !important;
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

            {/* Floating top-right menu — fades on scroll */}
            <div
                className={cn(
                    "fixed right-4 top-[calc(env(safe-area-inset-top,0px)+12px)] z-10 transition-opacity duration-300",
                    scrolled ? "pointer-events-none opacity-0" : "opacity-100",
                )}
            >
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            className="inline-flex size-9 items-center justify-center rounded-xl border border-black/5 bg-white/70 text-[#212121] shadow-[0_2px_8px_rgba(0,0,0,0.06)] backdrop-blur-md transition-colors hover:bg-white/85"
                            aria-label={localize("com_subscription.channel_settings")}
                        >
                            <Outlined.MoreCircle className="size-5" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                        align="end"
                        sideOffset={6}
                        className="z-[120] w-[160px] space-y-1 border border-black/5 bg-white/85 p-1 backdrop-blur-md"
                    >
                        <DropdownMenuItem
                            className="flex w-full cursor-pointer items-center gap-2 px-2 py-[5px] text-sm text-[#212121]"
                            onClick={handleShare}
                        >
                            <Outlined.Share className="size-4 text-[#4E5969]" />
                            {localize("com_subscription.share")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            className="flex w-full cursor-pointer items-center gap-2 px-2 py-[5px] text-sm text-[#212121]"
                            onClick={handleDownload}
                        >
                            <Outlined.Download className="size-4 text-[#4E5969]" />
                            {localize("com_subscription.download")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            className="flex w-full cursor-pointer items-center gap-2 px-2 py-[5px] text-sm text-[#212121]"
                            onClick={handleOpenOriginal}
                        >
                            <Outlined.Earth className="size-4 text-[#4E5969]" />
                            {localize("com_subscription.original_webpage")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            className="flex w-full cursor-pointer items-center gap-2 px-2 py-[5px] text-sm text-[#212121]"
                            onClick={() => setShowKnowledgeModal(true)}
                        >
                            <Outlined.AddToKnowledgeBase className="size-4 text-[#4E5969]" />
                            {localize("com_subscription.add_to_knowledge_space")}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>

            <AddToKnowledgeModal
                open={showKnowledgeModal}
                onOpenChange={setShowKnowledgeModal}
                articleId={article.id}
            />
        </div>
    );
}

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
