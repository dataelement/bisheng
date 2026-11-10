import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  useLayoutEffect,
} from "react";
import { useNavigate } from "react-router-dom";
import { useSetRecoilState } from "recoil";
import { Article, Channel, getArticleDetailApi } from "~/api/channels";
import { subscriptionDetailPaneWidthState } from "~/store/subscriptionLayout";
import NavToggle from "~/components/Nav/NavToggle";
import { useLocalize } from "~/hooks";
import { AiAssistantPanel } from "./AiChat/AiAssistantPanel";
import { ArticleList } from "./ArticleList/ArticleList";
import { ArticleDetail } from "./Article/ArticleDetail";
import { useResizablePanel } from "./hooks/useResizablePanel";
import { cn } from "~/utils";
import { MODULE_PAGE_DESKTOP_FRAME } from "~/components/ModuleHome";
import desktopLayout from "./ChannelLayout.module.css";

interface ChannelLayoutProps {
  channel: Channel;
  onFullScreen?: (article: Article, aiAssistant?: boolean) => void;

  onChannelSelect?: (channel: Channel | null) => void;
  onChannelSettings?: (channel: Channel) => void;
  onGoChannelSquare?: () => void;
  onCreateChannel?: () => void;
}

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 480;

// Geometry of ArticleList's two-column browse grid. The default split width is
// derived from these so the left column's article width stays identical whether
// the detail panel is open or closed. Keep in sync with ArticleList: the grid
// wrapper uses px-6 gutters in the browser; desktop reading has a 24px end gutter.
const LIST_GUTTER = 24; // px-6 horizontal padding on each side of the list
const GRID_GAP = 16; // gap-x-4 between grid columns
const GRID_DIVIDER = 1; // 1px vertical divider column between the two cards

/**
 * Width the left list should take so its single column matches the FIRST column
 * of the two-column browse grid.
 *
 * Card width = (browse content width − 2·gap − divider) / 2. The browser's
 * content uses 24px gutters; desktop browsing uses the shared 960px column.
 * The measured container already excludes desktop page gutters. Reading adds
 * back the browser's two gutters, or the desktop list's one divider-side gutter.
 */
const getDefaultLeftWidth = (containerWidth: number, desktop = false) => {
  // Only the shared CSS frame owns outer gutters; do not subtract them twice.
  const browseContentWidth = desktop
    ? Math.min(960, containerWidth)
    : containerWidth - LIST_GUTTER * 2;
  const columnWidth = (browseContentWidth - GRID_GAP * 2 - GRID_DIVIDER) / 2;
  return columnWidth + LIST_GUTTER * (desktop ? 1 : 2);
};

export function ChannelLayout({
  channel,
  onFullScreen,
  onChannelSelect,
  onChannelSettings,
  onGoChannelSquare,
  onCreateChannel,
}: ChannelLayoutProps) {
  const localize = useLocalize();

  const {
    channel: runtimeChannel,
    layout: { isNarrowViewport },
  } = useClientEnvironment();
  const navigate = useNavigate();
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [h5AiAssistantOpen, setH5AiAssistantOpen] = useState(false);
  const [isToggleHovering, setIsToggleHovering] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const setDetailPaneWidth = useSetRecoilState(
    subscriptionDetailPaneWidthState,
  );

  const {
    leftWidth,
    containerWidth,
    canSplit,
    isResizing,
    startResizing,
    resetToDefault,
  } = useResizablePanel({
    // v2: the default is now derived from the two-column grid geometry
    // (getDefaultLeftWidth) instead of a fixed 0.5 ratio. Bump the key so any
    // stale ratio persisted under the old default is ignored, letting the new
    // geometry-aligned default take effect.
    storageKey: "article-split-ratio-v2",
    defaultRatio: 0.5,
    minLeftWidth: MIN_LEFT_WIDTH,
    minRightWidth: MIN_RIGHT_WIDTH,
    containerRef,
    enabled: Boolean(selectedArticle),
    defaultLeftWidth: (width) => getDefaultLeftWidth(width, runtimeChannel === "desktop"),
  });

  const handleArticleSelect = useCallback(
    async (article: Article | null) => {
      if (!article) {
        setSelectedArticle(null);
        setH5AiAssistantOpen(false);
        return;
      }

      // H5: navigate to the standalone article page in the SAME tab so the user can use the
      // browser back button to return to the channel; ArticlePage takes care of setting
      // document.title to the article title and restoring it on unmount.
      if (runtimeChannel === "web" && isNarrowViewport) {
        navigate(`/channel/${article.channelId}/article/${article.id}`);
        return;
      }

      setH5AiAssistantOpen(false);

      setSelectedArticle(article);
      setDetailLoading(true);

      try {
        const detail = await getArticleDetailApi(article.id, article.channelId);

        setSelectedArticle((prev) => {
          if (prev?.id !== article.id) return prev;
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
        // Retain the list data if the detail request fails.
      } finally {
        setDetailLoading(false);
      }
    },
    [runtimeChannel, isNarrowViewport, navigate],
  );

  const splitDetail = canSplit && Boolean(selectedArticle);

  // Each time the panel goes from closed → open, re-assert the geometry-aligned
  // default width so the left column matches the two-column browse layout. A
  // width the user dragged earlier doesn't leak into the next open — satisfies
  // "left column width stays consistent when not manually resized".
  const wasOpenRef = useRef(false);
  useLayoutEffect(() => {
    const isOpen = !!selectedArticle;
    if (isOpen && !wasOpenRef.current) resetToDefault();
    wasOpenRef.current = isOpen;
  }, [selectedArticle, resetToDefault]);

  // Publish the right-area width (detail panel + splitter) so the page-level

  // when the detail panel opens. 0 when closed / on H5.
  useEffect(() => {
    if (!splitDetail) {
      setDetailPaneWidth(0);
      return;
    }
    setDetailPaneWidth(
      containerWidth > 0 ? Math.max(0, containerWidth - leftWidth) : 0,
    );
  }, [splitDetail, containerWidth, leftWidth, setDetailPaneWidth]);

  // Reset when leaving the channel view (unmount), e.g. switching to the square,
  // so its tab returns to the full content-area right edge.
  useEffect(() => () => setDetailPaneWidth(0), [setDetailPaneWidth]);

  return (
    <div
      className={cn(
        MODULE_PAGE_DESKTOP_FRAME,
        desktopLayout.frame,
        selectedArticle && desktopLayout.expanded,
        "relative flex h-full min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden bg-white",
      )}
    >
      <div
        ref={containerRef}
        className="relative flex h-full min-h-0 min-w-0 w-full flex-1 overflow-hidden bg-white"
      >
        {/* Transparent overlay during drag — prevents children from stealing mouse events */}
        {isResizing && splitDetail && (
          <div className="fixed inset-0 z-50 cursor-col-resize" />
        )}
        {/* The list uses full width until both columns can fit. */}
        <div
          key="article-list"
          hidden={!canSplit && Boolean(selectedArticle)}
          style={
            splitDetail
              ? { width: `${leftWidth}px` }
              : !canSplit && selectedArticle
                ? { display: "none" }
                : undefined
          }
          className={cn(
            "flex min-h-0 h-full min-w-0 flex-col overflow-hidden",
            splitDetail ? "shrink-0" : "w-full flex-1",
          )}
        >
          <ArticleList
            channel={channel}
            onArticleSelect={handleArticleSelect}
            selectedArticleId={selectedArticle?.id}
            onChannelSelect={onChannelSelect}
            onChannelSettings={onChannelSettings}
            onGoChannelSquare={onGoChannelSquare}
            onCreateChannel={onCreateChannel}
          />
        </div>

        {/* Splitter only when the selected detail fits beside the list. */}
        {splitDetail && (
          <div className="relative w-px min-w-[1px] max-w-[1px] shrink-0">
            <div
              onMouseDown={startResizing}
              className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
            >
              <div className="pointer-events-none w-px self-stretch bg-fill-3 transition-[width,background-color] duration-150 group-hover:w-[2px] group-hover:bg-[#999999] group-active:w-[2px] group-active:bg-[#999999]" />
            </div>
          </div>
        )}

        {selectedArticle && (
          <div
            key="article-detail"
            className={cn(
              splitDetail && desktopLayout.detailPane,
              "relative h-full min-w-0 flex-1 bg-white",
              !canSplit && "absolute inset-0 z-[35] flex flex-col",
            )}
          >
            {canSplit && (
              <NavToggle
                navVisible={true}
                onToggle={() => setSelectedArticle(null)}
                isHovering={isToggleHovering}
                setIsHovering={setIsToggleHovering}
                side="right"
                className="absolute top-1/2 z-[10]"
              />
            )}
            <ArticleDetail
              article={selectedArticle}
              loading={detailLoading}
              compactMode={!canSplit}
              preserveAiDraft
              onBack={!canSplit ? () => setSelectedArticle(null) : undefined}
              onFullScreen={() => onFullScreen?.(selectedArticle, false)}
              onAiAssistant={() =>
                canSplit
                  ? onFullScreen?.(selectedArticle, true)
                  : setH5AiAssistantOpen(true)
              }
            />
            {h5AiAssistantOpen && (
              <div
                className="absolute inset-0 z-[40] flex flex-col bg-white"
                role="dialog"
                aria-modal="true"
                aria-label={localize("com_subscription.ai_assistant")}
              >
                <AiAssistantPanel
                  features={{
                    tools: false,
                    knowledgeBase: false,
                    fileUpload: false,
                  }}
                  articleDocId={selectedArticle.id}
                  onClose={() => setH5AiAssistantOpen(false)}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
