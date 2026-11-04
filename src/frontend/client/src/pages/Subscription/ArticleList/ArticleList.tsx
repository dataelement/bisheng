import { useArticleList } from "./useArticleList";
import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { Tooltip as SharedTooltip } from "@bisheng/ui";
import { Tabs } from "@bisheng/ui";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { EmptyStateIllustration } from "~/components/illustrations";
import { Article, Channel } from "~/api/channels";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { ArticleCard } from "./ArticleCard";
import { ChannelActionsMenu } from "./ChannelActionsMenu";
import { ChannelSwitcher, SERIF_FONT_STACK } from "./ChannelSwitcher";
import { MultiSourceSelect } from "./MultiSourceSelect";
import { SearchInput } from "./SearchInput";

import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { Outlined } from "bisheng-icons";
import { useNavigate } from "react-router-dom";
import { cn } from "~/utils";
import { useEffect, useRef, useState } from "react";


import { useSetRecoilState } from "recoil";
import { subscriptionMobileChannelDropdownOpenState } from "~/store/subscriptionLayout";

export { stripHtmlTags, stripMarkdown, mapToArticle } from "./useArticleList";

interface ArticleListProps {
  channel: Channel;
  onArticleSelect: (article: Article | null) => void;
  selectedArticleId?: string;
  /** PC：顶部标题下拉切换频道（替代左侧 ChannelSidebar） */
  onChannelSelect?: (channel: Channel | null) => void;
  onChannelSettings?: (channel: Channel) => void;
  /** H5：打开「我的频道」侧栏（订阅页抽屉） */
  onOpenChannelNav?: () => void;
  onGoChannelSquare?: () => void;
  onCreateChannel?: () => void;
}

/**
 * Sub-channel tab label with a tooltip that only opens when the name is actually
 * truncated (max-w-[240px]). Rendered inside the @bisheng/ui Tabs items — the tab
 * button chrome, indicator and count badge all come from the library component.
 */
function TruncatedTabLabel({ name }: { name: string }) {
  const labelRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const el = labelRef.current;
    if (!el) return;
    const check = () => setIsTruncated(el.scrollWidth > el.clientWidth);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [name]);

  return (
    <SharedTooltip
      open={open}
      onOpenChange={(next) => {
        if (next && !isTruncated) return;
        setOpen(next);
      }}
      content={name}
    >
      <span ref={labelRef} className="block max-w-[240px] truncate">
        {name}
      </span>
    </SharedTooltip>
  );
}

export function ArticleList({
  channel,
  selectedArticleId,
  onArticleSelect,
  onChannelSelect,
  onChannelSettings,
  onOpenChannelNav,
  onGoChannelSquare,
  onCreateChannel,
}: ArticleListProps) {
  const mobileHeadIconBtnClassName = "inline-flex size-5 shrink-0 items-center justify-center text-text-1";
  const localize = useLocalize();
  const navigate = useNavigate();
  const isH5 = usePrefersMobileLayout();
  // Browse mode (PC, no article selected): show a two-column card grid. Reading mode: single column.
  const isGridMode = !selectedArticleId && !isH5;
  const {
    articles,
    currentPage,
    hasMore,
    loading,
    loadError,
    loadMoreError,
    selectedSubChannelName,
    searchKey,
    setSearchQuery,
    onlyUnread,
    selectedSources,
    isListScrolling,
    mobileDropdownOpen,
    setMobileDropdownOpen,
    mobileSearchOpen,
    setMobileSearchOpen,
    mobileSourceFilterOpen,
    setMobileSourceFilterOpen,
    searchQuery,
    channelDetail,
    isChannelDetailLoading,
    canOpenChannelShare,
    sourceOptions,
    subChannels,
    loadArticles,
    handleArticleClick,
    handleSourcesChange,
    handleToggleUnread,
    handleMobileShare,
    handleListScroll,
    handleSubChannelChange,
  } = useArticleList({ channel, onArticleSelect });
  // Publish the H5 dropdown-open state so the persistent 频道/广场 tab (rendered
  // above this view in Subscription/index) can grey itself out while it's open.
  const setMobileChannelDropdownOpen = useSetRecoilState(subscriptionMobileChannelDropdownOpenState);
  useEffect(() => {
    setMobileChannelDropdownOpen(mobileDropdownOpen);
  }, [mobileDropdownOpen, setMobileChannelDropdownOpen]);
  // Reset on unmount so leaving the channel view never leaves the tab stuck greyed.
  useEffect(() => () => setMobileChannelDropdownOpen(false), [setMobileChannelDropdownOpen]);

  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-x-hidden overflow-y-hidden">
      {isH5 ? (
        /* === H5 header === */
        <>
          <div className="sticky top-0 z-30 shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
            {/* Row 1: hamburger | 频道/广场 切换 | search | menu */}
            <div className="relative flex h-11 items-center gap-3 px-4">
              {/* Left group — fixed width that mirrors the right group, so the
                                center toggle stays screen-centered.
                                76px = search(32) + gap(12) + actions(32). */}
              <div className="flex min-w-[76px] shrink-0 items-center justify-start">
                {onOpenChannelNav ? (
                  <button
                    type="button"
                    onClick={onOpenChannelNav}
                    disabled={mobileDropdownOpen}
                    aria-label={localize("com_nav_open_sidebar")}
                    className={cn(
                      mobileHeadIconBtnClassName,
                      mobileDropdownOpen && "pointer-events-none opacity-20",
                    )}
                  >
                    <Outlined.SidebarMenu className="size-5" />
                  </button>
                ) : (
                  <div className="size-5 shrink-0" aria-hidden />
                )}
              </div>
              {/* Center group — spacer. The 频道/广场 toggle is a single
                                persistent instance rendered above both views (Subscription/index),
                                screen-centered over this gap, so switching slides smoothly. */}
              <div className="flex min-w-0 flex-1 items-center justify-center" />
              {/* Right group — same fixed width as the left group */}
              <div className="flex min-w-[76px] shrink-0 items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setMobileDropdownOpen(false);
                    setMobileSearchOpen((o) => !o);
                  }}
                  disabled={mobileDropdownOpen}
                  aria-label={localize("com_subscription.search_articles_of_interest")}
                  aria-pressed={mobileSearchOpen}
                  className={cn(
                    mobileHeadIconBtnClassName,
                    mobileDropdownOpen && "pointer-events-none opacity-20",
                  )}
                >
                  <Outlined.Search className="size-5" />
                </button>
                {onChannelSelect ? (
                  <ChannelActionsMenu
                    variant="mobile"
                    channel={channel}
                    onChannelSelect={onChannelSelect}
                    onChannelSettings={onChannelSettings}
                    onCreateChannel={onCreateChannel}
                    onShare={canOpenChannelShare ? handleMobileShare : undefined}
                    onOpenSourceFilter={
                      sourceOptions.length > 0
                        ? // Defer to next tick so the DropdownMenu fully closes before the Popover opens,
                          // otherwise Radix treats the same click as outside-click and dismisses the Popover.
                          () => setTimeout(() => setMobileSourceFilterOpen(true), 0)
                        : undefined
                    }
                    triggerClassName={mobileHeadIconBtnClassName}
                    disabled={mobileDropdownOpen}
                  />
                ) : null}
              </div>
              {/* Source picker — absolute-positioned anchor at the right edge so the popover opens beneath the actions menu without consuming flex space */}
              {sourceOptions.length > 0 ? (
                <span className="pointer-events-none absolute right-4 bottom-0">
                  <MultiSourceSelect
                    options={sourceOptions}
                    value={selectedSources}
                    onChange={handleSourcesChange}
                    open={mobileSourceFilterOpen}
                    onOpenChange={setMobileSourceFilterOpen}
                    hideTrigger
                  />
                </span>
              ) : null}
            </div>
            {/* Toggled search input */}
            {mobileSearchOpen ? (
              <div className="px-3 pb-2">
                <SearchInput
                  key={channel.id}
                  value={searchKey}
                  onChange={setSearchQuery}
                  placeholder={localize("com_subscription.search_articles_of_interest")}
                  className="w-full"
                />
              </div>
            ) : null}
            {/* Row 2: 频道名称（左，纯标题） + 切换频道 / 仅看未读（右） */}
            <div className="flex h-11 items-center justify-between gap-3 px-4">
              <h1 className="min-w-0 flex-1 truncate text-[16px] font-medium leading-6 text-text-1">
                {channelDetail?.name || channel.name}
              </h1>
              <div className="flex shrink-0 items-center gap-3">
                {onChannelSelect ? (
                  <ChannelSwitcher
                    variant="mobile"
                    activeChannelId={channel.id}
                    channelName={channelDetail?.name || channel.name}
                    onChannelSelect={onChannelSelect}
                    onCreateChannel={onCreateChannel}
                    onChannelSquare={onGoChannelSquare}
                    open={mobileDropdownOpen}
                    onOpenChange={(next) => {
                      if (next) setMobileSearchOpen(false);
                      setMobileDropdownOpen(next);
                    }}
                    mobileTopOffset={
                      mobileSearchOpen
                        ? "calc(env(safe-area-inset-top, 0px) + 148px)"
                        : "calc(env(safe-area-inset-top, 0px) + 96px)"
                    }
                  />
                ) : null}
                <button
                  type="button"
                  onClick={handleToggleUnread}
                  disabled={mobileDropdownOpen}
                  className={cn(
                    "shrink-0 rounded-md border px-3 py-[3px] text-sm transition-colors whitespace-nowrap",
                    onlyUnread
                      ? "border-transparent bg-primary/20 text-primary"
                      : "border-border-base bg-white text-gray-800",
                    mobileDropdownOpen && "pointer-events-none opacity-20",
                  )}
                >
                  {localize("com_subscription.show_unread_only")}
                </button>
              </div>
            </div>
            {/* Row 3: 子频道页签。无子频道时整行隐藏。横滚、两端渐隐、
                            未读数徽标与底部通栏分隔线都由 @bisheng/ui Tabs 提供。 */}
            {subChannels.length > 0 ? (
              <div className="px-4 pb-2">
                <Tabs
                  activeKey={selectedSubChannelName || "all"}
                  onChange={handleSubChannelChange}
                  items={[
                    {
                      key: "all",
                      label: localize("com_subscription.all"),
                      badge: channel.unreadCount,
                    },
                    ...subChannels.map((sub) => ({
                      key: sub.name,
                      label: <TruncatedTabLabel name={sub.name} />,
                      badge: sub.unreadCount,
                    })),
                  ]}
                />
              </div>
            ) : null}
          </div>
        </>
      ) : (
        /* === PC header === */
        <div
          className={cn(
            "mx-auto w-full shrink-0 pt-5 pb-4 space-y-4",
            isGridMode ? "max-w-none" : "max-w-[1000px]",
            // PC uses 24px gutters (header and list share them); H5 keeps 16px.
            isH5 ? "px-4" : "px-6",
          )}
        >
          {/* 返回（左） + 频道名（居中） */}
          <div className="flex items-center gap-3">
            {/* `relative` is the anchor for the switcher's absolutely centered
                            title: the row spans the full content width, so the title lands on
                            the pane midpoint and the back button no longer pushes it right. */}
            <div className="relative flex min-w-0 flex-1 items-center">
              {/* Back to the 频道 home (/channel). Inside a channel the 我的 / 广场
                                switcher already reads 我的, so it cannot be the way out. Same
                                button as the 知识空间 space header. */}
              <button
                type="button"
                onClick={() => navigate("/channel")}
                aria-label={localize("com_ui_go_back")}
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-md p-2 text-text-2 transition-colors hover:bg-fill-1"
              >
                <Outlined.ArrowLeft className="size-4" />
              </button>
              {onChannelSelect ? (
                <ChannelSwitcher
                  activeChannelId={channel.id}
                  channelName={channelDetail?.name || channel.name}
                  onChannelSelect={onChannelSelect}
                  onChannelSquare={onGoChannelSquare}
                  // Browse mode (full-width pane): title on the pane's absolute
                  // midpoint. Reading mode (detail open): flex centering that
                  // truncates to the space between the side groups.
                  absoluteCenterTitle={isGridMode}
                  // Channel-level actions (share / ⋯) ride the title row's
                  // right edge; the toolbar row below keeps article filters only.
                  rightSlot={
                    <>
                      {canOpenChannelShare ? (
                        <CopyShareLinkButton
                          sharePath={`/channel/share/${channel.id}`}
                          label={localize("com_subscription.share")}
                          successMessage={localize("com_subscription.share_link_copied")}
                          errorMessage={localize("com_subscription.copy_failed_retry")}
                          iconOnly
                          className="border-border-base"
                          aria-label={localize("com_subscription.share")}
                          icon={<Outlined.Share className="size-4 shrink-0 text-text-2" />}
                        />
                      ) : null}
                      <ChannelActionsMenu
                        channel={channel}
                        onChannelSelect={onChannelSelect}
                        onChannelSettings={onChannelSettings}
                        triggerClassName="border-border-base"
                      />
                    </>
                  }
                  infoContent={
                    <div className="space-y-1.5 text-sm text-gray-800">
                      <div>
                        <span className="text-gray-400">
                          {localize("com_subscription.channel_name_colon")}
                        </span>
                        <p>{channelDetail?.name || channel.name}</p>
                      </div>
                      <div>
                        <span className="text-gray-400">
                          {localize("com_subscription.channel_description_colon")}
                        </span>
                        <p>{channelDetail?.description || channel.description || "-"}</p>
                      </div>
                      <div>
                        <span className="text-gray-400">{localize("com_subscription.creator_colon")}</span>
                        <p>{channelDetail?.creator_name || channel.creator || "-"}</p>
                      </div>
                      <div>
                        <span className="text-gray-400">
                          {localize("com_subscription.subscribers_colon")}
                        </span>
                        <p>{channelDetail?.subscriber_count ?? channel.subscriberCount ?? 0}</p>
                      </div>
                      <div>
                        <span className="text-gray-400">
                          {localize("com_subscription.content_count_colon")}
                        </span>
                        <p>{channelDetail?.article_count ?? channel.articleCount ?? 0}</p>
                      </div>
                    </div>
                  }
                />
              ) : (
                <h1
                  className="min-w-0 flex-1 truncate text-center text-[32px] font-bold leading-[40px] text-text-1"
                  style={{ fontFamily: SERIF_FONT_STACK }}
                >
                  {channelDetail?.name || channel.name}
                </h1>
              )}
            </div>
          </div>

          {/* 子频道 Tabs + 搜索/筛选. Single row on PC: tabs scroll horizontally
                        (with edge shadows) while the toolbar stays fixed on the right. Hide
                        the tab row when there are no sub-channels (a lone 全部 tab adds no value). */}
          <div className="flex flex-row items-center justify-between gap-3">
            {subChannels.length > 0 && (
              // Controlled @bisheng/ui Tabs used as a bare tab strip (no children —
              // the article list below is the content area). Overflow scroll +
              // edge fades and the count badges are built into the component.
              // divider off: this header row draws no full-width edge today.
              <Tabs
                className="min-w-0 flex-1"
                divider={false}
                activeKey={selectedSubChannelName || "all"}
                onChange={handleSubChannelChange}
                items={[
                  {
                    key: "all",
                    label: localize("com_subscription.all"),
                    badge: channel.unreadCount,
                  },
                  ...subChannels.map((sub) => ({
                    key: sub.name,
                    label: <TruncatedTabLabel name={sub.name} />,
                    badge: sub.unreadCount,
                  })),
                ]}
              />
            )}

            {/* ml-auto keeps the toolbar right-aligned even when the tab row is hidden.
                            shrink-0 + no wrap keeps it on one line; the tabs absorb the overflow. */}
            <div className="ml-auto flex shrink-0 flex-row items-center justify-end gap-3">
              <SearchInput
                key={channel.id}
                value={searchKey}
                onChange={setSearchQuery}
                placeholder={localize("com_subscription.search_articles_of_interest")}
                className="min-w-0"
              />
              <MultiSourceSelect
                className="h-8 min-w-[140px] max-w-full shrink-0 rounded-md"
                options={sourceOptions}
                value={selectedSources}
                onChange={handleSourcesChange}
              />
              <button
                type="button"
                onClick={handleToggleUnread}
                className={cn(
                  "shrink-0 rounded-md border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                  onlyUnread
                    ? "border-transparent bg-primary/20 text-primary"
                    : "border-border-base bg-white text-gray-800 fine-pointer:hover:bg-gray-50",
                )}
              >
                {localize("com_subscription.show_unread_only")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Article list area */}
      <div
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden scroll-on-scroll"
        onScroll={handleListScroll}
        data-scrolling={isListScrolling ? "true" : "false"}
      >
        <div
          className={cn(
            "mx-auto flex min-h-full w-full min-w-0 flex-col overflow-x-hidden",
            isGridMode ? "max-w-none" : "max-w-[1000px]",
            // PC uses 24px gutters (header and list share them); H5 keeps 16px.
            isH5 ? "px-4" : "px-6",
          )}
        >
          {loadError || loadMoreError ? (
            <ApiRequestFailure
              error={loadError || loadMoreError}
              onRetry={() => loadArticles(loadError ? 1 : currentPage + 1)}
            />
          ) : null}
          {/* Show loading spinner while channel detail or initial article list is loading */}
          {isChannelDetailLoading || (loading && articles.length === 0) ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-text-3">
              <LoadingIcon className="size-20 text-primary" />
            </div>
          ) : articles.length === 0 ? (
            !loadError && (
              <div className="flex flex-1 flex-col items-center justify-center py-8 text-center">
                {searchQuery || selectedSources.length > 0 || onlyUnread ? (
                  <>
                    <EmptyStateIllustration className="size-[120px] mb-4" />
                    <p className="text-[14px] font-normal leading-6 text-text-3">
                      {localize("com_subscription.no_results")}
                    </p>
                  </>
                ) : (
                  <>
                    <EmptyStateIllustration className="size-[120px] mb-4" />
                    <p className="text-[14px] font-normal leading-6 text-text-3">
                      {localize("com_subscription.no_related_content")}
                    </p>
                  </>
                )}
              </div>
            )
          ) : (
            <InfiniteScroll
              loadMore={() => loadArticles(currentPage + 1)}
              hasMore={hasMore && !loadError && !loadMoreError}
              isLoading={loading}
              emptyText={localize("com_subscription.all_messages_are_here")}
              className=""
            >
              {isGridMode ? (
                // PC browse grid: chunk into rows of 2 so the horizontal divider is
                // continuous full-width, while the vertical divider is per-row (inset
                // by my-5 so the horizontal lines break it). Columns are equal width.
                <div className="flex flex-col">
                  {(() => {
                    const rows = Array.from({ length: Math.ceil(articles.length / 2) }, (_, i) =>
                      articles.slice(i * 2, i * 2 + 2),
                    );
                    return rows.map((row, rowIndex) => {
                      const rowDivider =
                        rowIndex < rows.length - 1 ? "border-b border-dashed border-border-base" : "";
                      return (
                        <div
                          key={row[0].id}
                          className={cn(
                            "grid gap-x-4",
                            rowDivider,
                            // minmax(0,1fr) keeps both columns strictly equal width. Always use the
                            // two-column template so a lone last article stays half-width (first
                            // column) instead of stretching across the full row.
                            "grid-cols-[minmax(0,1fr)_1px_minmax(0,1fr)]",
                          )}
                        >
                          <div>
                            <ArticleCard
                              article={row[0]}
                              onSelect={handleArticleClick}
                              isSelected={selectedArticleId === row[0].id}
                              searchQuery={searchQuery}
                              variant="grid"
                            />
                          </div>
                          {row[1] && (
                            <>
                              <div className="my-5 border-l border-dashed border-border-base" aria-hidden />
                              <div>
                                <ArticleCard
                                  article={row[1]}
                                  onSelect={handleArticleClick}
                                  isSelected={selectedArticleId === row[1].id}
                                  searchQuery={searchQuery}
                                  variant="grid"
                                />
                              </div>
                            </>
                          )}
                        </div>
                      );
                    });
                  })()}
                </div>
              ) : isH5 ? (
                // Mobile: single column; each card carries its own dashed divider.
                <div>
                  {articles.map((article) => (
                    <ArticleCard
                      key={article.id}
                      article={article}
                      onSelect={handleArticleClick}
                      isSelected={selectedArticleId === article.id}
                      searchQuery={searchQuery}
                      variant="grid"
                    />
                  ))}
                </div>
              ) : (
                // Reading mode (PC single column): reuse the grid card style with a
                // full-width dashed divider between items.
                <div className="flex flex-col">
                  {articles.map((article, i) => (
                    <div
                      key={article.id}
                      className={cn(i > 0 && "border-t border-dashed border-border-base")}
                    >
                      <ArticleCard
                        article={article}
                        onSelect={handleArticleClick}
                        isSelected={selectedArticleId === article.id}
                        searchQuery={searchQuery}
                        variant="grid"
                      />
                    </div>
                  ))}
                </div>
              )}
            </InfiniteScroll>
          )}
        </div>
      </div>
    </div>
  );
}
