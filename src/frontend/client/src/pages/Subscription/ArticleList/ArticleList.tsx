import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    Article,
    Channel,
    getArticlesApi,
    getChannelDetailApi,
    type ArticleSearchResultItem
} from "~/api/channels";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useDebounce } from "~/hooks";
import { ArticleCard } from "./ArticleCard";
import { ChannelActionsMenu } from "./ChannelActionsMenu";
import { ChannelSwitcher } from "./ChannelSwitcher";
import { MultiSourceSelect } from "./MultiSourceSelect";
import { SearchInput } from "./SearchInput";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/Tooltip2";
import { CopyShareLinkButton, buildClientShareUrl } from "~/components/CopyShareLinkButton";
import { Outlined } from "bisheng-icons";
import { cn, copyText } from "~/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";

interface ArticleListProps {
    channel: Channel;
    onArticleSelect: (article: Article | null) => void;
    selectedArticleId?: string;
    /** PC：顶部标题下拉切换频道（替代左侧 ChannelSidebar） */
    onChannelSelect?: (channel: Channel | null) => void;
    /** PC：下拉内频道项管理操作 */
    onManageMembers?: (channel: Channel) => void;
    onChannelSettings?: (channel: Channel) => void;
    /** H5：打开「我的频道」侧栏（订阅页抽屉） */
    onOpenChannelNav?: () => void;
    onGoChannelSquare?: () => void;
    onCreateChannel?: () => void;
}

/** Strip HTML tags from a string, extracting body content first */
export function stripHtmlTags(html: string): string {
    if (!html) return "";
    // Extract content within <body> tags if present
    const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    const bodyContent = bodyMatch ? bodyMatch[1] : html;
    return bodyContent
        .replace(/<[^>]*>/g, "")       // Strip HTML tags
        .replace(/&[a-zA-Z]+;/g, " ")  // Strip named entities (&nbsp; &amp; etc.)
        .replace(/&#\d+;/g, " ")       // Strip numeric entities (&#160; etc.)
        .replace(/\s+/g, " ")          // Collapse whitespace
        .trim();
}

/**
 * Strip common Markdown syntax so a content preview reads as plain prose.
 * Article previews come back as Markdown; without this, link syntax like
 * `[text](https://very-long-url)` leaks the raw URL into the preview and the
 * unbreakable URL token forces `line-clamp` to wrap early, leaving the line
 * looking half-empty. No-op for plain prose (nothing to strip).
 */
export function stripMarkdown(md: string): string {
    if (!md) return "";
    return md
        .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")          // images ![alt](url) -> drop
        .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")         // links [text](url) -> text
        .replace(/!\[[^\]]*\]?\([^)]*$/g, "")            // truncated trailing image ![alt](url… -> drop
        .replace(/\[([^\]]*)\]\([^)]*$/g, "$1")          // truncated trailing link [text](url… -> text
        .replace(/!?\[[^\]]*$/g, "")                     // trailing incomplete marker ![ / ![alt / [text
        .replace(/^\s*#{1,6}\s+/gm, "")                  // ATX heading markers
        .replace(/^\s*>+\s?/gm, "")                      // blockquote markers
        .replace(/^\s*[-*+]\s+/gm, "")                   // unordered list markers
        .replace(/`{1,3}([^`]*)`{1,3}/g, "$1")           // inline code / fences
        .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, "$1") // bold / italic / strike
        .replace(/https?:\/\/\S+/g, "")                  // leftover bare URLs (e.g. from truncation)
        .replace(/\s*[-–—|·]+\s*$/g, "")                 // trailing separator left after stripping a marker
        .replace(/\s+/g, " ")                            // collapse whitespace
        .trim();
}

/** Map backend ArticleSearchResultItem to frontend Article */
export function mapToArticle(item: ArticleSearchResultItem, channelId: string): Article {
    return {
        id: item.doc_id,
        title: item.title,
        url: item.source_url || "",
        content: stripMarkdown(stripHtmlTags(item.content_preview || "")),
        content_html: item.content_html || "",
        coverImage: item.cover_image || undefined,
        sourceName: item.source_info?.source_name || "",
        sourceAvatar: item.source_info?.source_icon || undefined,
        sourceId: item.source_id,
        channelId,
        isRead: item.is_read ?? false,
        publishedAt: item.publish_time || item.create_time || "",
        createdAt: item.create_time || "",
        highlight: item.highlight,
        source_type: item.source_type,
        sensitiveReview: item.sensitive_review,
    };
}

/**
 * Sub-channel tab whose tooltip only opens when the name is actually truncated
 * (max-w-[240px] + truncate). Avoids redundant tooltips on short names that fit
 * fully inside the tab. Truncation state re-checks on resize via ResizeObserver.
 */
function SubChannelTab({
    sub,
    className,
    onClick,
}: {
    sub: { id: string; name: string; unreadCount?: number };
    className: string;
    onClick: () => void;
}) {
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
    }, [sub.name]);

    return (
        <Tooltip
            open={open}
            onOpenChange={(next) => {
                // Suppress open events when the name fits — only truncated labels show a tooltip.
                if (next && !isTruncated) return;
                setOpen(next);
            }}
        >
            <TooltipTrigger asChild>
                <button type="button" onClick={onClick} className={className}>
                    <span ref={labelRef} className="block max-w-[240px] truncate">{sub.name}</span>
                    {sub.unreadCount && sub.unreadCount > 0 ? (
                        <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-md bg-[rgba(51,92,255,0.05)] px-1 text-[10px] font-semibold leading-[18px] text-[#335CFF]">
                            {sub.unreadCount}
                        </span>
                    ) : null}
                </button>
            </TooltipTrigger>
            <TooltipContent>{sub.name}</TooltipContent>
        </Tooltip>
    );
}

export function ArticleList({
    channel,
    selectedArticleId,
    onArticleSelect,
    onChannelSelect,
    onManageMembers,
    onChannelSettings,
    onOpenChannelNav,
    onGoChannelSquare,
    onCreateChannel,
}: ArticleListProps) {
    const mobileHeadIconBtnClassName = "inline-flex size-5 shrink-0 items-center justify-center text-[#212121]";
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    // Browse mode (PC, no article selected): show a two-column card grid. Reading mode: single column.
    const isGridMode = !selectedArticleId && !isH5;
    const [articles, setArticles] = useState<Article[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    // Start in the loading state: the initial mount fetches articles on the next
    // render cycle, so this keeps the loading view up from first paint and stops
    // the empty state from flashing before the first article list arrives.
    const [loading, setLoading] = useState(true);
    const [selectedSubChannelName, setSelectedSubChannelName] = useState<string | undefined>(undefined);

    const [searchKey, setSearchQuery] = useState("");
    const [onlyUnread, setOnlyUnread] = useState(false);
    const [selectedSources, setSelectedSources] = useState<string[]>([]);
    const [isListScrolling, setIsListScrolling] = useState(false);
    const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const tabsScrollRef = useRef<HTMLDivElement>(null);
    const [tabsScrollShadow, setTabsScrollShadow] = useState({ left: false, right: false });
    /** H5: title-bar channel dropdown + search input visibility; menu-triggered source filter */
    const [mobileDropdownOpen, setMobileDropdownOpen] = useState(false);
    const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
    const [mobileSourceFilterOpen, setMobileSourceFilterOpen] = useState(false);
    const searchQuery = useDebounce(searchKey, 500);
    const queryClient = useQueryClient();
    const { showToast } = useToastContext();


    // Fetch channel detail for the tooltip; isLoading drives the page-level loading state
    const { data: channelDetail, isLoading: isChannelDetailLoading } = useQuery({
        queryKey: ["channelDetail", channel.id],
        queryFn: () => getChannelDetailApi(channel.id),
        staleTime: 60_000, // Cache for 1 minute
    });
    const canManageChannel = channel.role === "creator" || channel.role === "admin";
    const canOpenChannelShare =
        canManageChannel || (channelDetail ? channelDetail.visibility !== "private" : false);

    // Derive source options directly from channelDetail.source_infos (refreshes after channel edit)
    const sourceOptions = useMemo(() => {
        const infos = channelDetail?.source_infos;
        if (!infos?.length) return [];
        return infos
            .filter(s => s.id)
            .map(s => ({ id: s.id, label: s.source_name || s.name || '' }));
    }, [channelDetail?.source_infos]);

    const subChannels = useMemo(() => {
        const unreadByName = channelDetail?.sub_channel_unread_counts || {};
        return (channelDetail?.filter_rules || [])
            .filter(fr => fr.channel_type === "sub" && fr.name)
            .map((fr, idx) => ({ id: `sub-${idx}`, name: fr.name!, unreadCount: unreadByName[fr.name!] ?? 0 }))
            .sort((a, b) => {
                const getPriority = (name: string) => {
                    const ch = name.charAt(0);
                    if (/[a-zA-Z]/.test(ch)) return 0;
                    if (/\d/.test(ch)) return 1;
                    return 2;
                };
                const pa = getPriority(a.name);
                const pb = getPriority(b.name);
                if (pa !== pb) return pa - pb;
                return a.name.localeCompare(b.name, "zh-CN");
            });
    }, [channelDetail?.filter_rules]);

    const PAGE_SIZE = 20;

    const loadArticles = useCallback(async (page: number) => {
        if (!channel) return;

        setLoading(true);
        try {
            const response = await getArticlesApi({
                channelId: channel.id,
                subChannelName: selectedSubChannelName,
                keyword: searchQuery || undefined,
                sourceIds: selectedSources.length > 0 ? selectedSources : undefined,
                onlyUnread: onlyUnread || undefined,
                page,
                pageSize: PAGE_SIZE,
            });

            const mapped = (response.data || []).map(item => mapToArticle(item, channel.id));

            if (page === 1) {
                setArticles(mapped);
            } else {
                setArticles(prev => [...prev, ...mapped]);
            }

            const total = response.total || 0;
            setHasMore(page * PAGE_SIZE < total);
            setCurrentPage(page);
        } catch (e) {
            console.error("Failed to load articles:", e);
            if (page === 1) setArticles([]);
        } finally {
            setLoading(false);
        }
        // Note: sourceOptions is NOT a dependency here to avoid re-fetching when sources load
    }, [channel?.id, selectedSubChannelName, searchQuery, selectedSources, onlyUnread]);

    // 统一的频道切换 + 筛选加载 effect
    // 用 ref 检测频道是否切换，切换时重置状态再加载
    const prevChannelIdRef = useRef<string | undefined>(undefined);
    useEffect(() => {
        if (!channel) return;

        // 检测是否为频道切换
        const isChannelSwitch = channel.id !== prevChannelIdRef.current;
        if (isChannelSwitch) {
            prevChannelIdRef.current = channel.id;
            // Enter the loading state and drop the previous channel's articles right away.
            // The actual fetch happens on the next render (after the filter resets below),
            // so without this the list would briefly show the old/empty state during the gap.
            setLoading(true);
            setArticles([]);
            setCurrentPage(1);
            setSearchQuery("");
            const savedSubName = localStorage.getItem(`selectedSubChannelName-${channel.id}`) || undefined;
            setSelectedSubChannelName(savedSubName);
            setSelectedSources([]);
            setOnlyUnread(false);
            onArticleSelect(null);
            // 频道切换时不在这里加载，等 React 下一轮渲染
            // 下一轮 selectedSubChannelName/selectedSources 变化后本 effect 会自动触发
            return;
        }

        // 筛选条件变化或初始加载
        loadArticles(1);
    }, [channel?.id, searchQuery, selectedSources, onlyUnread, selectedSubChannelName]);

    // Default the source filter to "all selected" once a channel's sources have loaded.
    // Runs once per channel; afterwards the user can freely deselect — down to the empty
    // state, which the picker blocks on close (requires at least one source).
    const sourcesInitializedRef = useRef<string | undefined>(undefined);
    useEffect(() => {
        if (!channel || sourceOptions.length === 0) return;
        if (sourcesInitializedRef.current === channel.id) return;
        sourcesInitializedRef.current = channel.id;
        setSelectedSources(sourceOptions.map(o => o.id));
    }, [channel?.id, sourceOptions]);

    // Optimistically mark the article as read in local state when selected.
    // The backend already marks it read when the detail API is called.
    const handleArticleClick = useCallback((article: Article | null) => {
        if (article?.sensitiveReview?.can_view === false) {
            showToast({
                message: article.sensitiveReview.auto_reply || localize("com_subscription.sensitive_review_blocked"),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (article && !article.isRead) {
            setArticles(prev =>
                prev.map(a => a.id === article.id ? { ...a, isRead: true } : a)
            );
            // Optimistically decrement unread badge in sidebar channel cache
            const decrementUnread = (old: Channel[] | undefined) => {
                if (!old) return old;
                return old.map(c =>
                    c.id === channel.id && c.unreadCount > 0
                        ? { ...c, unreadCount: c.unreadCount - 1 }
                        : c
                );
            };
            // Update all cached query variants for both created and subscribed lists
            queryClient.setQueriesData<Channel[]>(
                { queryKey: ["channels", "created"] },
                decrementUnread
            );
            queryClient.setQueriesData<Channel[]>(
                { queryKey: ["channels", "subscribed"] },
                decrementUnread
            );
        }
        onArticleSelect(article);
    }, [onArticleSelect, channel.id, queryClient, showToast, localize]);

    const handleSourcesChange = (newValue: string[]) => {
        setSelectedSources(newValue);
    };

    const handleToggleUnread = () => {
        setOnlyUnread(!onlyUnread);
    };

    /** H5: copy share link from the page-level actions menu (mirrors CopyShareLinkButton). */
    const handleMobileShare = useCallback(async () => {
        const url = buildClientShareUrl(`/channel/share/${channel.id}`);
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
    }, [channel.id, localize, showToast]);

    const handleListScroll = () => {
        setIsListScrolling(true);
        if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
        listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
    };

    const updateTabsScrollShadow = useCallback(() => {
        const el = tabsScrollRef.current;
        if (!el) {
            setTabsScrollShadow({ left: false, right: false });
            return;
        }
        const { scrollLeft, scrollWidth, clientWidth } = el;
        const overflow = scrollWidth - clientWidth;
        const eps = 2;
        setTabsScrollShadow({
            left: scrollLeft > eps,
            right: overflow > eps && scrollLeft < overflow - eps,
        });
    }, []);

    // 处理子频道切换（改为 name 模式）
    const handleSubChannelChange = (subChannelName: string) => {
        localStorage.setItem(`selectedSubChannelName-${channel.id}`, subChannelName === "all" ? "" : subChannelName);
        setSelectedSubChannelName(subChannelName === "all" ? undefined : subChannelName);
    };

    useEffect(() => {
        const id = requestAnimationFrame(() => updateTabsScrollShadow());
        return () => cancelAnimationFrame(id);
    }, [subChannels.length, channel.id, updateTabsScrollShadow]);

    useEffect(() => {
        const el = tabsScrollRef.current;
        if (!el || typeof ResizeObserver === "undefined") {
            return;
        }
        const ro = new ResizeObserver(() => updateTabsScrollShadow());
        ro.observe(el);
        window.addEventListener("resize", updateTabsScrollShadow);
        return () => {
            ro.disconnect();
            window.removeEventListener("resize", updateTabsScrollShadow);
        };
    }, [channel.id, updateTabsScrollShadow]);

    return (
        <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-x-hidden overflow-y-hidden">
            {isH5 ? (
                /* === H5 header === */
                <>
                    <div className="sticky top-0 z-30 shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                        {/* Title row: hamburger | title (caret) | search | menu */}
                        <div className="relative flex h-11 items-center gap-3 px-4">
                            {/* Left group — fixed width that mirrors the right group, so the
                                center title stays screen-centered even when truncated.
                                76px = search(32) + gap(12) + actions(32). */}
                            <div className="flex min-w-[76px] shrink-0 items-center justify-start">
                                {onOpenChannelNav ? (
                                    <button
                                        type="button"
                                        onClick={onOpenChannelNav}
                                        disabled={mobileDropdownOpen}
                                        aria-label={localize("com_nav_open_sidebar")}
                                        className={cn(mobileHeadIconBtnClassName, mobileDropdownOpen && "pointer-events-none opacity-20")}
                                    >
                                        <Outlined.SidebarMenu className="size-5" />
                                    </button>
                                ) : (
                                    <div className="size-5 shrink-0" aria-hidden />
                                )}
                            </div>
                            {/* Center group — title grows then truncates while staying centered */}
                            <div className="flex min-w-0 flex-1 items-center justify-center">
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
                                                ? "calc(env(safe-area-inset-top, 0px) + 104px)"
                                                : "calc(env(safe-area-inset-top, 0px) + 52px)"
                                        }
                                    />
                                ) : (
                                    <h1
                                        className="flex min-w-0 flex-1 items-center justify-center truncate text-[20px] leading-7 text-[#212121]"
                                        style={{ fontFamily: '"Source Han Serif SC", "Noto Serif SC", serif' }}
                                    >
                                        {channelDetail?.name || channel.name}
                                    </h1>
                                )}
                            </div>
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
                                    className={cn(mobileHeadIconBtnClassName, mobileDropdownOpen && "pointer-events-none opacity-20")}
                                >
                                    <Outlined.Search className="size-5" />
                                </button>
                                {onChannelSelect ? (
                                    <ChannelActionsMenu
                                        variant="mobile"
                                        channel={channel}
                                        onChannelSelect={onChannelSelect}
                                        onManageMembers={onManageMembers}
                                        onChannelSettings={onChannelSettings}
                                        onShare={canOpenChannelShare ? handleMobileShare : undefined}
                                        onOpenSourceFilter={
                                            sourceOptions.length > 0
                                                // Defer to next tick so the DropdownMenu fully closes before the Popover opens,
                                                // otherwise Radix treats the same click as outside-click and dismisses the Popover.
                                                ? () => setTimeout(() => setMobileSourceFilterOpen(true), 0)
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
                        {/* Sub-channels + 仅看未读 (single row; right-gradient hints scroll).
                            Hide the tab strip when the channel has no sub-channels. */}
                        <div className="flex items-center gap-2 px-4 pt-3 pb-2">
                            {subChannels.length > 0 && (
                            <div className="relative min-w-0 flex-1 border-b border-[#F2F3F5]">
                                {tabsScrollShadow.left ? (
                                    <div
                                        className="pointer-events-none absolute inset-y-0 left-0 z-[1] w-2 bg-[linear-gradient(90deg,rgba(153,153,153,0.15)_0%,rgba(153,153,153,0)_100%)]"
                                        aria-hidden
                                    />
                                ) : null}
                                {tabsScrollShadow.right ? (
                                    <div
                                        className="pointer-events-none absolute inset-y-0 right-0 z-[1] w-2 bg-[linear-gradient(90deg,rgba(153,153,153,0)_0%,rgba(153,153,153,0.15)_100%)]"
                                        aria-hidden
                                    />
                                ) : null}
                                <div
                                    ref={tabsScrollRef}
                                    onScroll={updateTabsScrollShadow}
                                    className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar"
                                >
                                    <button
                                        type="button"
                                        onClick={() => handleSubChannelChange("all")}
                                        className={cn(
                                            "flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 py-[3px] text-sm transition-colors",
                                            !selectedSubChannelName
                                                ? "border-[#335CFF] text-[#335CFF]"
                                                : "border-transparent text-[#212121]",
                                        )}
                                    >
                                        <span>{localize("com_subscription.all")}</span>
                                        {channel.unreadCount > 0 && (
                                            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-md bg-[rgba(51,92,255,0.05)] px-1 text-[10px] font-semibold leading-[18px] text-[#335CFF]">
                                                {channel.unreadCount}
                                            </span>
                                        )}
                                    </button>
                                    {subChannels.map((sub) => (
                                        <SubChannelTab
                                            key={sub.id}
                                            sub={sub}
                                            onClick={() => handleSubChannelChange(sub.name)}
                                            className={cn(
                                                "flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 py-[3px] text-sm transition-colors",
                                                selectedSubChannelName === sub.name
                                                    ? "border-[#335CFF] text-[#335CFF]"
                                                    : "border-transparent text-[#212121]",
                                            )}
                                        />
                                    ))}
                                </div>
                            </div>
                            )}
                            <button
                                type="button"
                                onClick={handleToggleUnread}
                                className={cn(
                                    "ml-auto shrink-0 rounded-[6px] border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                    onlyUnread
                                        ? "border-primary bg-primary/20 text-primary"
                                        : "border-[#E5E6EB] bg-white text-gray-800",
                                )}
                            >
                                {localize("com_subscription.show_unread_only")}
                            </button>
                        </div>
                    </div>
                </>
            ) : (
                /* === PC header === */
                <div className={cn(
                    "mx-auto w-full shrink-0 pt-5 pb-4 space-y-4",
                    isGridMode ? "max-w-none" : "max-w-[1000px]",
                    // PC keeps 40px gutters whether grid or preview-open; H5 uses 16px.
                    isH5 ? "px-4" : "px-10",
                )}>
                    {/* 频道名 + 信息 + 分享 */}
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
                            {onChannelSelect ? (
                                <ChannelSwitcher
                                    activeChannelId={channel.id}
                                    channelName={channelDetail?.name || channel.name}
                                    onChannelSelect={onChannelSelect}
                                    onCreateChannel={onCreateChannel}
                                    onChannelSquare={onGoChannelSquare}
                                    infoContent={
                                        <div className="space-y-1.5 text-sm text-gray-800">
                                            <div><span className="text-gray-400">{localize("com_subscription.channel_description_colon")}</span>
                                                <p>{channelDetail?.description || channel.description || "-"}</p>
                                            </div>
                                            <div><span className="text-gray-400">{localize("com_subscription.creator_colon")}</span>
                                                <p>{channelDetail?.creator_name || channel.creator || "-"}</p>
                                            </div>
                                            <div><span className="text-gray-400">{localize("com_subscription.subscribers_colon")}</span>
                                                <p>{channelDetail?.subscriber_count ?? channel.subscriberCount ?? 0}</p>
                                            </div>
                                            <div><span className="text-gray-400">{localize("com_subscription.content_count_colon")}</span>
                                                <p>{channelDetail?.article_count ?? channel.articleCount ?? 0}</p>
                                            </div>
                                        </div>
                                    }
                                />
                            ) : (
                                <h1 className="truncate text-base text-[#1d2129]">
                                    {channelDetail?.name || channel.name}
                                </h1>
                            )}
                        </div>

                        <div className="flex shrink-0 items-center gap-3">
                            {onChannelSelect ? (
                                <ChannelActionsMenu
                                    channel={channel}
                                    onChannelSelect={onChannelSelect}
                                    onManageMembers={onManageMembers}
                                    onChannelSettings={onChannelSettings}
                                />
                            ) : null}
                            {canOpenChannelShare ? (
                                <CopyShareLinkButton
                                    sharePath={`/channel/share/${channel.id}`}
                                    label={localize("com_subscription.share")}
                                    successMessage={localize("com_subscription.share_link_copied")}
                                    errorMessage={localize("com_subscription.copy_failed_retry")}
                                    iconOnly
                                    aria-label={localize("com_subscription.share")}
                                    icon={<Outlined.Share className="size-4 shrink-0 text-[#4e5969]" />}
                                />
                            ) : null}
                        </div>
                    </div>

                    {/* 子频道 Tabs + 搜索/筛选. Single row on PC: tabs scroll horizontally
                        (with edge shadows) while the toolbar stays fixed on the right. Hide
                        the tab row when there are no sub-channels (a lone 全部 tab adds no value). */}
                    <div className="flex flex-row items-center justify-between gap-3">
                        {subChannels.length > 0 && (
                        <div className="relative min-w-0 flex-1">
                            {tabsScrollShadow.left ? (
                                <div
                                    className="pointer-events-none absolute inset-y-0 left-0 z-[1] w-2 bg-[linear-gradient(90deg,rgba(153,153,153,0.15)_0%,rgba(153,153,153,0)_100%)]"
                                    aria-hidden
                                />
                            ) : null}
                            {tabsScrollShadow.right ? (
                                <div
                                    className="pointer-events-none absolute inset-y-0 right-0 z-[1] w-2 bg-[linear-gradient(90deg,rgba(153,153,153,0)_0%,rgba(153,153,153,0.15)_100%)]"
                                    aria-hidden
                                />
                            ) : null}
                            <div
                                ref={tabsScrollRef}
                                onScroll={updateTabsScrollShadow}
                                className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar"
                            >
                                <button
                                    type="button"
                                    onClick={() => handleSubChannelChange("all")}
                                    className={cn(
                                        "flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-2 py-[5px] text-sm transition-colors",
                                        !selectedSubChannelName
                                            ? "border-[#335CFF] text-[#335CFF]"
                                            : "border-transparent text-[#212121] fine-pointer:hover:text-[#335CFF]",
                                    )}
                                >
                                    <span>{localize("com_subscription.all")}</span>
                                    {channel.unreadCount > 0 && (
                                        <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-md bg-[rgba(51,92,255,0.05)] px-1 text-[10px] font-semibold leading-[18px] text-[#335CFF]">
                                            {channel.unreadCount}
                                        </span>
                                    )}
                                </button>
                                {subChannels.map(sub => (
                                    <SubChannelTab
                                        key={sub.id}
                                        sub={sub}
                                        onClick={() => handleSubChannelChange(sub.name)}
                                        className={cn(
                                            "flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-2 py-[5px] text-sm transition-colors",
                                            selectedSubChannelName === sub.name
                                                ? "border-[#335CFF] text-[#335CFF]"
                                                : "border-transparent text-[#212121] fine-pointer:hover:text-[#335CFF]",
                                        )}
                                    />
                                ))}
                            </div>
                        </div>
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
                                className="h-8 min-w-[140px] max-w-full shrink-0 rounded-[6px]"
                                options={sourceOptions}
                                value={selectedSources}
                                onChange={handleSourcesChange}
                            />
                            <button
                                type="button"
                                onClick={handleToggleUnread}
                                className={cn(
                                    "shrink-0 rounded-[6px] border px-4 py-[5px] text-sm transition-colors whitespace-nowrap",
                                    onlyUnread
                                        ? "border-transparent bg-primary/20 text-primary"
                                        : "border-[#E5E6EB] bg-white text-gray-800 fine-pointer:hover:bg-gray-50",
                                )}
                            >{localize("com_subscription.show_unread_only")}</button>
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
                <div className={cn(
                    "mx-auto flex min-h-full w-full min-w-0 flex-col overflow-x-hidden",
                    isGridMode ? "max-w-none" : "max-w-[1000px]",
                    // PC keeps 40px gutters whether grid or preview-open; H5 uses 16px.
                    isH5 ? "px-4" : "px-10",
                )}>
                    {/* Show loading spinner while channel detail or initial article list is loading */}
                    {(isChannelDetailLoading || (loading && articles.length === 0)) ? (
                        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[#86909c]">
                            <LoadingIcon className="size-20 text-primary" />
                        </div>
                    ) : articles.length === 0 ? (
                        <div className="flex flex-1 flex-col items-center justify-center py-60 text-center">
                            {(searchQuery || selectedSources.length > 0 || onlyUnread) ? (
                                <p className="text-[14px] leading-6 text-[#86909c]">{localize("com_subscription.no_results")}</p>
                            ) : (
                                <>
                                    <img
                                        className="size-[120px] mb-4 object-contain opacity-90"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                        alt="empty"
                                    />
                                    <p className="text-[14px] leading-6 text-[#4E5969]">
                                        {localize("com_subscription.no_related_content")}
                                    </p>
                                </>
                            )}
                        </div>
                    ) : (
                        <InfiniteScroll
                            loadMore={() => loadArticles(currentPage + 1)}
                            hasMore={hasMore}
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
                                        const rows = Array.from(
                                            { length: Math.ceil(articles.length / 2) },
                                            (_, i) => articles.slice(i * 2, i * 2 + 2),
                                        );
                                        return rows.map((row, rowIndex) => {
                                            const rowDivider = rowIndex < rows.length - 1
                                                ? "border-b border-dashed border-[#EBECF0]"
                                                : "";
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
                                                            <div className="my-5 border-l border-dashed border-[#EBECF0]" aria-hidden />
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
                                    {articles.map(article => (
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
                                            className={cn(i > 0 && "border-t border-dashed border-[#EBECF0]")}
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
