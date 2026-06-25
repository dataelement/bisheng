import React, { useState, useRef, useCallback, useEffect, useLayoutEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useSetRecoilState } from "recoil";
import { Article, Channel, getArticleDetailApi } from "~/api/channels";
import { subscriptionDetailPaneWidthState } from "~/store/subscriptionLayout";
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
    /** PC：顶部标题下拉切换频道 */
    onChannelSelect?: (channel: Channel | null) => void;
    /** PC：下拉内频道项管理操作 */
    onManageMembers?: (channel: Channel) => void;
    onChannelSettings?: (channel: Channel) => void;
    /** H5：打开左侧「我的频道」抽屉（由订阅页挂载） */
    onOpenChannelNav?: () => void;
    onGoChannelSquare?: () => void;
    onCreateChannel?: () => void;
}

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 480;

// Geometry of ArticleList's two-column browse grid. The default split width is
// derived from these so the left column's article width stays identical whether
// the detail panel is open or closed. Keep in sync with ArticleList: the grid
// wrapper uses px-10 gutters, the row grid uses gap-x-4 with a 1px divider column.
const LIST_GUTTER = 40; // px-10 horizontal padding on each side of the list
const GRID_GAP = 16; // gap-x-4 between grid columns
const GRID_DIVIDER = 1; // 1px vertical divider column between the two cards

/**
 * Width the left list should take so its single column matches the FIRST column
 * of the two-column browse grid.
 *
 * Two-column card width = (containerWidth − 2·gutter − 2·gap − divider) / 2.
 * In split mode the list keeps the same px-10 gutters, so the panel width is
 * that card width plus both gutters back.
 */
const getDefaultLeftWidth = (containerWidth: number) => {
    const columnWidth =
        (containerWidth - LIST_GUTTER * 2 - GRID_GAP * 2 - GRID_DIVIDER) / 2;
    return columnWidth + LIST_GUTTER * 2;
};

export function ChannelLayout({
    channel,
    onFullScreen,
    onChannelSelect,
    onManageMembers,
    onChannelSettings,
    onOpenChannelNav,
    onGoChannelSquare,
    onCreateChannel,
}: ChannelLayoutProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const navigate = useNavigate();
    const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    /** H5：AI 助手全屏叠在文章详情上，返回时回到正文（不与正文左右分屏） */
    const [h5AiAssistantOpen, setH5AiAssistantOpen] = useState(false);
    const [isToggleHovering, setIsToggleHovering] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const setDetailPaneWidth = useSetRecoilState(subscriptionDetailPaneWidthState);

    const { leftWidth, isResizing, startResizing, resetToDefault } = useResizablePanel({
        // v2: the default is now derived from the two-column grid geometry
        // (getDefaultLeftWidth) instead of a fixed 0.5 ratio. Bump the key so any
        // stale ratio persisted under the old default is ignored, letting the new
        // geometry-aligned default take effect.
        storageKey: "article-split-ratio-v2",
        defaultRatio: 0.5,
        minLeftWidth: MIN_LEFT_WIDTH,
        minRightWidth: MIN_RIGHT_WIDTH,
        containerRef,
        defaultLeftWidth: getDefaultLeftWidth,
    });

    // 选中文章时加载详情
    const handleArticleSelect = useCallback(async (article: Article | null) => {
        if (!article) {
            setSelectedArticle(null);
            setH5AiAssistantOpen(false);
            return;
        }

        // H5: navigate to the standalone article page in the SAME tab so the user can use the
        // browser back button to return to the channel; ArticlePage takes care of setting
        // document.title to the article title and restoring it on unmount.
        if (isH5) {
            navigate(`/channel/${article.channelId}/article/${article.id}`);
            return;
        }

        setH5AiAssistantOpen(false);
        // 先用列表数据快速展示
        setSelectedArticle(article);
        setDetailLoading(true);

        try {
            const detail = await getArticleDetailApi(article.id, article.channelId);
            // 用详情数据更新已选文章（保留列表中的显示字段）
            setSelectedArticle(prev => {
                if (prev?.id !== article.id) return prev; // 已经切换了
                return {
                    ...prev,
                    content_html: detail.content_html || prev.content_html || "",
                    url: detail.source_url || prev.url,
                    coverImage: detail.cover_image || prev.coverImage,
                    publishedAt: detail.publish_time || prev.publishedAt,
                    sensitiveReview: detail.sensitive_review || prev.sensitiveReview,
                };
            });
        } catch (e) {
            console.error("Failed to load article detail:", e);
            // 失败时保留列表数据
        } finally {
            setDetailLoading(false);
        }
    }, []);

    // Each time the panel goes from closed → open, re-assert the geometry-aligned
    // default width so the left column matches the two-column browse layout. A
    // width the user dragged earlier doesn't leak into the next open — satisfies
    // "left column width stays consistent when not manually resized".
    const wasOpenRef = useRef(false);
    useLayoutEffect(() => {
        const isOpen = !isH5 && !!selectedArticle;
        if (isOpen && !wasOpenRef.current) resetToDefault();
        wasOpenRef.current = isOpen;
    }, [isH5, selectedArticle, resetToDefault]);

    // Publish the right-area width (detail panel + splitter) so the page-level
    // 频道/广场 tab can pin to the article-list column's right edge and slide left
    // when the detail panel opens. 0 when closed / on H5.
    useEffect(() => {
        if (isH5 || !selectedArticle) {
            setDetailPaneWidth(0);
            return;
        }
        const containerWidth = containerRef.current?.getBoundingClientRect().width ?? 0;
        setDetailPaneWidth(containerWidth > 0 ? Math.max(0, containerWidth - leftWidth) : 0);
    }, [isH5, selectedArticle, leftWidth, setDetailPaneWidth]);

    // Reset when leaving the channel view (unmount), e.g. switching to the square,
    // so its tab returns to the full content-area right edge.
    useEffect(() => () => setDetailPaneWidth(0), [setDetailPaneWidth]);

    return (
        <div
            ref={containerRef}
            className="relative flex h-full min-h-0 min-w-0 w-full flex-1 overflow-hidden bg-white"
        >
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
                    "flex min-h-0 h-full min-w-0 flex-col overflow-hidden",
                    isH5 ? "w-full flex-1" : selectedArticle ? "shrink-0" : "w-full flex-1",
                )}
            >
                <ArticleList
                    channel={channel}
                    onArticleSelect={handleArticleSelect}
                    selectedArticleId={selectedArticle?.id}
                    onChannelSelect={onChannelSelect}
                    onManageMembers={onManageMembers}
                    onChannelSettings={onChannelSettings}
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
                        <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-[width,background-color] duration-150 group-hover:w-[2px] group-hover:bg-[#999999] group-active:w-[2px] group-active:bg-[#999999]" />
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
                                    features={{ tools: false, knowledgeBase: false, fileUpload: false }}
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
