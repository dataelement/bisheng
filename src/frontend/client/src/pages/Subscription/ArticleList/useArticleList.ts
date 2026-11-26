import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { isApiError } from '@bisheng/api-client';
import { useDebounce, useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { copyText } from '~/utils';
import { buildClientShareUrl } from '~/components/CopyShareLinkButton';
import { getArticlesApi, getChannelDetailApi, getChannelUnreadCountsApi, type Article, type Channel, type ArticleSearchResultItem } from '~/api/channels';

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

interface UseArticleListProps {
    channel: Channel;
    onArticleSelect: (article: Article | null) => void;
}

export function useArticleList({ channel, onArticleSelect }: UseArticleListProps) {
    const localize = useLocalize();
    const channelId = channel.id;
    const onArticleSelectRef = useRef(onArticleSelect);
    onArticleSelectRef.current = onArticleSelect;
    const [articles, setArticles] = useState<Article[]>([]);
    const [loadError, setLoadError] = useState<unknown>(null);
    const [loadMoreError, setLoadMoreError] = useState<unknown>(null);
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
    /** Mobile search input and menu-triggered source filter visibility. */
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

    // F040: per-sub-channel unread counts are split out of the channel detail
    // endpoint (the preview drawer no longer pays the per-user ES cost). The
    // in-channel view fetches them lazily here to fill the sub-channel badges;
    // on failure the badges degrade to 0 (empty map) rather than breaking the list.
    const { data: subChannelUnreadCounts } = useQuery({
        queryKey: ["channelUnreadCounts", channel.id],
        queryFn: () => getChannelUnreadCountsApi(channel.id),
        staleTime: 30_000,
        // Best-effort badges: a failed unread fetch must not surface an error toast.
        retry: false,
        placeholderData: {} as Record<string, number>,
    });
    // Share entry is available to anyone who can see the channel (creator/admin or subscriber),
    // regardless of visibility — subscribers should always be able to copy/share the link.
    const canOpenChannelShare = true;

    // Derive source options directly from channelDetail.source_infos (refreshes after channel edit)
    const sourceOptions = useMemo(() => {
        const infos = channelDetail?.source_infos;
        if (!infos?.length) return [];
        return infos
            .filter(s => s.id)
            .map(s => ({ id: s.id, label: s.source_name || s.name || '' }));
    }, [channelDetail?.source_infos]);

    const subChannels = useMemo(() => {
        const unreadByName = subChannelUnreadCounts || {};
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
    }, [channelDetail?.filter_rules, subChannelUnreadCounts]);

    const PAGE_SIZE = 20;
    const requestKey = JSON.stringify([channel.id, selectedSubChannelName, searchQuery, selectedSources, onlyUnread]);
    const requestKeyRef = useRef(requestKey);
    requestKeyRef.current = requestKey;
    const requestSequence = useRef(0);

    const loadArticles = useCallback(async (page: number) => {
        const key = requestKey;
        const sequence = ++requestSequence.current;
        setLoading(true);
        setLoadError(null);
        setLoadMoreError(null);
        try {
            const response = await getArticlesApi({
                channelId,
                subChannelName: selectedSubChannelName,
                keyword: searchQuery || undefined,
                sourceIds: selectedSources.length > 0 ? selectedSources : undefined,
                onlyUnread: onlyUnread || undefined,
                page,
                pageSize: PAGE_SIZE,
            });

            if (requestKeyRef.current !== key || requestSequence.current !== sequence) return;
            const mapped = (response.data || []).map(item => mapToArticle(item, channelId));

            if (page === 1) {
                setArticles(mapped);
            } else {
                setArticles(prev => [...prev, ...mapped]);
            }

            const total = response.total || 0;
            setHasMore(page * PAGE_SIZE < total);
            setCurrentPage(page);
        } catch (error) {
            if (requestKeyRef.current !== key || requestSequence.current !== sequence) return;
            if (isApiError(error) && error.kind === 'canceled') return;
            if (page === 1) setLoadError(error);
            else setLoadMoreError(error);
        } finally {
            if (requestKeyRef.current === key && requestSequence.current === sequence) setLoading(false);
        }
        // Note: sourceOptions is NOT a dependency here to avoid re-fetching when sources load
    }, [channelId, selectedSubChannelName, searchQuery, selectedSources, onlyUnread, requestKey]);

    // Load on channel or filter changes.
    // Reset filters before loading a different channel.
    const prevChannelIdRef = useRef<string | undefined>(undefined);
    useEffect(() => {
        // Detect a channel change.
        const isChannelSwitch = channelId !== prevChannelIdRef.current;
        if (isChannelSwitch) {
            prevChannelIdRef.current = channelId;
            // Enter the loading state and drop the previous channel's articles right away.
            // The actual fetch happens on the next render (after the filter resets below),
            // so without this the list would briefly show the old/empty state during the gap.
            setLoading(true);
            setArticles([]);
            setLoadError(null);
            setLoadMoreError(null);
            setCurrentPage(1);
            setSearchQuery("");
            const savedSubName = localStorage.getItem(`selectedSubChannelName-${channelId}`) || undefined;
            setSelectedSubChannelName(savedSubName);
            setSelectedSources([]);
            setOnlyUnread(false);
            onArticleSelectRef.current(null);
            // Wait for the reset filters to render before loading.
            // The next render triggers this effect with the new filters.
            return;
        }

        // Load the initial page for the current filters.
        loadArticles(1);
    }, [channelId, searchQuery, selectedSources, onlyUnread, selectedSubChannelName, loadArticles]);

    // Default the source filter to "all selected" once a channel's sources have loaded.
    // Runs once per channel; afterwards the user can freely deselect — down to the empty
    // state, which the picker blocks on close (requires at least one source).
    const sourcesInitializedRef = useRef<string | undefined>(undefined);
    useEffect(() => {
        if (sourceOptions.length === 0) return;
        if (sourcesInitializedRef.current === channelId) return;
        sourcesInitializedRef.current = channelId;
        setSelectedSources(sourceOptions.map(o => o.id));
    }, [channelId, sourceOptions]);

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
                status: "warning",
            });
        }
    }, [channel.id, localize, showToast]);

    const handleListScroll = () => {
        setIsListScrolling(true);
        if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
        listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
    };

    // Persist the selected sub-channel by name.
    const handleSubChannelChange = (subChannelName: string) => {
        localStorage.setItem(`selectedSubChannelName-${channelId}`, subChannelName === "all" ? "" : subChannelName);
        setSelectedSubChannelName(subChannelName === "all" ? undefined : subChannelName);
    };

    return {
        articles, currentPage, hasMore,
        loading, loadError, loadMoreError,
        selectedSubChannelName, searchKey, setSearchQuery,
        onlyUnread, selectedSources, isListScrolling,
        mobileSearchOpen,
        setMobileSearchOpen, mobileSourceFilterOpen, setMobileSourceFilterOpen,
        searchQuery, channelDetail, isChannelDetailLoading,
        canOpenChannelShare, sourceOptions, subChannels,
        loadArticles, handleArticleClick, handleSourcesChange,
        handleToggleUnread, handleMobileShare, handleListScroll,
        handleSubChannelChange,
    };
}
