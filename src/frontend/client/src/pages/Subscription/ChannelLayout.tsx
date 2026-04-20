import React, { useState, useRef, useCallback } from "react";
import { Article, Channel, getArticleDetailApi } from "~/api/channels";
import NavToggle from "~/components/Nav/NavToggle";
import { ArticleList } from "./ArticleList/ArticleList";
import { ArticleDetail } from "./Article/ArticleDetail";
import { useResizablePanel } from "./hooks/useResizablePanel";

interface ChannelLayoutProps {
    channel: Channel;
    onFullScreen?: (article: Article, aiAssistant?: boolean) => void;
}

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 480;

export function ChannelLayout({ channel, onFullScreen }: ChannelLayoutProps) {
    const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [isToggleHovering, setIsToggleHovering] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const { leftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: "article-split-ratio",
        defaultRatio: 0.5,
        minLeftWidth: MIN_LEFT_WIDTH,
        minRightWidth: MIN_RIGHT_WIDTH,
        containerRef,
    });

    // 选中文章时加载详情
    const handleArticleSelect = useCallback(async (article: Article | null) => {
        if (!article) {
            setSelectedArticle(null);
            return;
        }

        // 先用列表数据快速展示
        setSelectedArticle(article);
        setDetailLoading(true);

        try {
            const detail = await getArticleDetailApi(article.id);
            // 用详情数据更新已选文章（保留列表中的显示字段）
            setSelectedArticle(prev => {
                if (prev?.id !== article.id) return prev; // 已经切换了
                return {
                    ...prev,
                    content: detail.content || prev.content,
                    content_html: detail.content_html || prev.content_html || "",
                    url: detail.source_url || prev.url,
                    coverImage: detail.cover_image || prev.coverImage,
                    publishedAt: detail.publish_time || prev.publishedAt,
                };
            });
        } catch (e) {
            console.error("Failed to load article detail:", e);
            // 失败时保留列表数据
        } finally {
            setDetailLoading(false);
        }
    }, []);

    return (
        <div ref={containerRef} className="flex h-full w-full overflow-hidden bg-white">
            {/* Transparent overlay during drag — prevents children from stealing mouse events */}
            {isResizing && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}
            {/* Left list area */}
            <div
                style={{ width: selectedArticle ? `${leftWidth}px` : '100%' }}
                className="h-full flex-shrink-0"
            >
                <ArticleList
                    channel={channel}
                    onArticleSelect={handleArticleSelect}
                    selectedArticleId={selectedArticle?.id}
                />
            </div>

            {/* Splitter - only shown when an article is selected */}
            {selectedArticle && (
                <div className="relative w-[1px] min-w-[1px] max-w-[1px] flex-none shrink-0">
                    <div
                        onMouseDown={startResizing}
                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                    >
                        <div className="pointer-events-none w-px self-stretch bg-[#f2f3f5] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                    </div>
                </div>
            )}

            {/* Right detail area */}
            {selectedArticle && (
                <div className="relative flex-1 h-full min-w-[480px] bg-white">
                    {/* Collapse toggle — positioned on the left edge, vertically centered */}
                    <NavToggle
                        navVisible={true}
                        onToggle={() => setSelectedArticle(null)}
                        isHovering={isToggleHovering}
                        setIsHovering={setIsToggleHovering}
                        side="right"
                        className="absolute top-1/2 z-[10]"
                    />
                    <ArticleDetail
                        article={selectedArticle}
                        loading={detailLoading}
                        onFullScreen={() => onFullScreen?.(selectedArticle, false)}
                        onAiAssistant={() => onFullScreen?.(selectedArticle, true)}
                    />
                </div>
            )}
        </div>
    );
}