import React, { useState, useRef, useCallback } from "react";
import { Article, Channel, getArticleDetailApi } from "~/api/channels";
import NavToggle from "~/components/Nav/NavToggle";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { AiAssistantPanel } from "./AiChat/AiAssistantPanel";
import { ArticleList } from "./ArticleList/ArticleList";
import { ArticleDetail } from "./Article/ArticleDetail";
import { useResizablePanel } from "./hooks/useResizablePanel";
import { cn } from "~/utils";

interface ChannelLayoutProps {
    channel: Channel;
    onFullScreen?: (article: Article, aiAssistant?: boolean) => void;
    /** H5：打开左侧「我的频道」抽屉（由订阅页挂载） */
    onOpenChannelNav?: () => void;
    onGoChannelSquare?: () => void;
    onCreateChannel?: () => void;
}

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 480;

export function ChannelLayout({
    channel,
    onFullScreen,
    onOpenChannelNav,
    onGoChannelSquare,
    onCreateChannel,
}: ChannelLayoutProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    /** H5：AI 助手全屏叠在文章详情上，返回时回到正文（不与正文左右分屏） */
    const [h5AiAssistantOpen, setH5AiAssistantOpen] = useState(false);
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
            setH5AiAssistantOpen(false);
            return;
        }

        setH5AiAssistantOpen(false);
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
        <div ref={containerRef} className="relative flex h-full w-full overflow-hidden bg-white">
            {/* Transparent overlay during drag — prevents children from stealing mouse events */}
            {isResizing && !isH5 && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}
            {/* Left list area — H5 始终全宽列表；PC 选中文时与右侧分栏 */}
            <div
                style={
                    !isH5 && selectedArticle
                        ? { width: `${leftWidth}px` }
                        : undefined
                }
                className={cn(
                    "h-full shrink-0",
                    isH5 ? "w-full min-w-0 flex-1" : selectedArticle ? "" : "w-full",
                )}
            >
                <ArticleList
                    channel={channel}
                    onArticleSelect={handleArticleSelect}
                    selectedArticleId={selectedArticle?.id}
                    onOpenChannelNav={onOpenChannelNav}
                    onGoChannelSquare={onGoChannelSquare}
                    onCreateChannel={onCreateChannel}
                />
            </div>

            {/* Splitter — 仅 PC 选中文时 */}
            {!isH5 && selectedArticle && (
                <div className="relative w-px min-w-[1px] max-w-[1px] shrink-0">
                    <div
                        onMouseDown={startResizing}
                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                    >
                        <div className="pointer-events-none w-px self-stretch bg-[#f2f3f5] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                    </div>
                </div>
            )}

            {/* Right detail — 仅 PC */}
            {!isH5 && selectedArticle && (
                <div className="relative h-full min-w-[480px] flex-1 bg-white">
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

            {/* H5：文章详情全屏叠在列表上 */}
            {isH5 && selectedArticle && (
                <div
                    className="absolute inset-0 z-[35] flex flex-col bg-white"
                    role="dialog"
                    aria-modal="true"
                    aria-label={localize("com_subscription.subscribe")}
                >
                    <div className="relative min-h-0 flex-1 overflow-hidden">
                        <ArticleDetail
                            article={selectedArticle}
                            loading={detailLoading}
                            onBack={() => {
                                if (h5AiAssistantOpen) {
                                    setH5AiAssistantOpen(false);
                                    return;
                                }
                                setSelectedArticle(null);
                            }}
                            onFullScreen={() => onFullScreen?.(selectedArticle, false)}
                            onAiAssistant={() => setH5AiAssistantOpen(true)}
                        />
                        {h5AiAssistantOpen ? (
                            <div
                                className="absolute inset-0 z-[40] flex flex-col bg-white"
                                role="dialog"
                                aria-modal="true"
                                aria-label={localize("com_subscription.ai_assistant")}
                            >
                                <AiAssistantPanel
                                    compactMobileChrome
                                    features={{ tools: false, modelSelect: false, knowledgeBase: false, fileUpload: false }}
                                    articleDocId={selectedArticle.id}
                                    onClose={() => setH5AiAssistantOpen(false)}
                                />
                            </div>
                        ) : null}
                    </div>
                </div>
            )}
        </div>
    );
}
