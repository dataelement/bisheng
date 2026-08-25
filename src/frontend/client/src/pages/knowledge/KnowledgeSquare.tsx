import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type CompositionEvent } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { EmptyStateIllustration } from "~/components/illustrations";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import {
    getSquareSpacesApi,
    subscribeSpaceApi,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { useLocalize, useMediaQuery } from "~/hooks";
import KnowledgeSquareCard from "./KnowledgeSquareCard";

type SquareSpaceStatus = "join" | "joined" | "pending" | "rejected";

const KNOWLEDGE_SQUARE_PAGE_SIZE = 60;

function mergeSpacesById(existing: KnowledgeSpace[], incoming: KnowledgeSpace[]) {
    const seenIds = new Set(existing.map((space) => String(space.id)));
    return [
        ...existing,
        ...incoming.filter((space) => {
            const id = String(space.id);
            if (seenIds.has(id)) return false;
            seenIds.add(id);
            return true;
        }),
    ];
}

interface KnowledgeSquareProps {
    onBack?: () => void;
    title?: string;
    subtitle?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    joinToastPrefix?: string;
    onPreviewSpace?: (space: KnowledgeSpace) => void;
    /** Optional status override from parent (e.g. preview drawer join) */
    statusOverride?: Record<string, SquareSpaceStatus>;
    onSquareStatusChange?: (spaceId: string, status: SquareSpaceStatus) => void;
}

export default function KnowledgeSquare({
    onBack,
    title,
    subtitle,
    searchPlaceholder,
    emptyText,
    joinToastPrefix,
    onPreviewSpace,
    statusOverride,
    onSquareStatusChange,
}: KnowledgeSquareProps) {
    const { showToast } = useToastContext();
    const localize = useLocalize();

    // 卡片每行列数自适应，与应用广场保持一致：lg+ 3 列，md 2 列，窄屏 1 列
    const isAtLeast768 = useMediaQuery("(min-width: 768px)");
    const isAtLeast1024 = useMediaQuery("(min-width: 1024px)");
    const squareCols = useMemo(() => {
        if (isAtLeast1024) return 3;
        if (isAtLeast768) return 2;
        return 1;
    }, [isAtLeast768, isAtLeast1024]);

    const [searchQuery, setSearchQuery] = useState("");
    const [page, setPage] = useState(1);
    const [hasMorePage, setHasMorePage] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [initialError, setInitialError] = useState(false);
    const [loadMoreError, setLoadMoreError] = useState(false);
    const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
    const spacesRef = useRef<KnowledgeSpace[]>([]);
    const requestSeqRef = useRef(0);
    // In-flight join requests keyed by space id, so concurrent joins to
    // different spaces (e.g. clicking quickly across pages) don't block each
    // other — a single shared id used to silently drop them (see handleJoin).
    const [joiningIds, setJoiningIds] = useState<Set<string>>(() => new Set());

    const scrollRef = useRef<HTMLDivElement | null>(null);
    const loadMoreRef = useRef<HTMLDivElement | null>(null);
    const loadMoreLockRef = useRef(false);
    const searchImeComposingRef = useRef(false);
    const MAX_SEARCH_LEN = 40;

    const tTitle = title || localize("com_knowledge.explore_square");
    const tSubtitle = subtitle || localize("com_knowledge.explore_more_spaces");
    const tSearchPlaceholder = searchPlaceholder || localize("com_knowledge.search_space_placeholder");
    const tEmptyText = emptyText || localize("com_knowledge.no_matched_space");
    const tJoinPrefix = joinToastPrefix || localize("com_knowledge.applied_to_join_space");

    const updateSpaces = useCallback((updater: (prev: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        setSpaces((prev) => {
            const next = updater(prev);
            spacesRef.current = next;
            return next;
        });
    }, []);

    const visibleSpaces = spaces;

    const load = useCallback(
        async (nextPage: number) => {
            const isFirstPage = nextPage === 1;
            const requestId = ++requestSeqRef.current;

            if (isFirstPage) {
                setLoading(true);
                setLoadingMore(false);
                setInitialError(false);
                setLoadMoreError(false);
                loadMoreLockRef.current = false;
                spacesRef.current = [];
                setSpaces([]);
            } else {
                setLoadingMore(true);
                setLoadMoreError(false);
            }

            try {
                const keyword = searchQuery.trim();
                const res = await getSquareSpacesApi({
                    page: nextPage,
                    page_size: KNOWLEDGE_SQUARE_PAGE_SIZE,
                    ...(keyword ? { keyword } : {}),
                });
                if (requestId !== requestSeqRef.current) return;

                const list = (res.data || []) as KnowledgeSpace[];
                const rawTotal = res.total;
                const total = Number(rawTotal);
                const hasExplicitTotal = rawTotal !== undefined && rawTotal !== null && Number.isFinite(total);
                const previous = isFirstPage ? [] : spacesRef.current;
                const nextSpaces = isFirstPage ? list : mergeSpacesById(previous, list);
                const uniqueAddedCount = nextSpaces.length - previous.length;

                if (hasExplicitTotal && nextSpaces.length < total && (list.length === 0 || (!isFirstPage && uniqueAddedCount === 0))) {
                    if (isFirstPage) {
                        spacesRef.current = [];
                        setSpaces([]);
                        setInitialError(true);
                    } else {
                        setLoadMoreError(true);
                    }
                    setHasMorePage(false);
                    return;
                }

                spacesRef.current = nextSpaces;
                setSpaces(nextSpaces);
                setPage(nextPage);
                setHasMorePage(hasExplicitTotal ? nextSpaces.length < total : list.length >= KNOWLEDGE_SQUARE_PAGE_SIZE);
            } catch {
                if (requestId !== requestSeqRef.current) return;
                if (isFirstPage) {
                    spacesRef.current = [];
                    setSpaces([]);
                    setInitialError(true);
                } else {
                    setLoadMoreError(true);
                }
                setHasMorePage(false);
            } finally {
                if (requestId === requestSeqRef.current) {
                    if (isFirstPage) setLoading(false);
                    else setLoadingMore(false);
                }
            }
        },
        [searchQuery]
    );

    const applySearchLengthLimit = (raw: string) => {
        if (raw.length <= MAX_SEARCH_LEN) return raw;
        showToast({
            message: localize("com_subscription.maximum_character") || localize("com_knowledge.max_40_chars"),
            severity: NotificationSeverity.WARNING,
        });
        return raw.slice(0, MAX_SEARCH_LEN);
    };

    const handleSearch = (e: ChangeEvent<HTMLInputElement>) => {
        const next = e.target.value ?? "";
        const native = e.nativeEvent;
        const isComposing =
            searchImeComposingRef.current ||
            (native && "isComposing" in native && (native as InputEvent).isComposing === true);
        if (isComposing) {
            setSearchQuery(next);
            return;
        }
        setSearchQuery(applySearchLengthLimit(next));
    };

    const handleSearchCompositionStart = () => {
        searchImeComposingRef.current = true;
    };

    const handleSearchCompositionEnd = (e: CompositionEvent<HTMLInputElement>) => {
        searchImeComposingRef.current = false;
        const next = e.currentTarget.value ?? "";
        setSearchQuery(applySearchLengthLimit(next));
    };

    // Reload on search change to mimic channel plaza behavior
    useEffect(() => {
        load(1);
    }, [searchQuery, load]);

    const handleLoadMore = useCallback(() => {
        if (loadMoreLockRef.current || loading || loadingMore || loadMoreError || !hasMorePage) return;
        loadMoreLockRef.current = true;
        load(page + 1).finally(() => {
            loadMoreLockRef.current = false;
        });
    }, [hasMorePage, load, loadMoreError, loading, loadingMore, page]);

    // Infinite scroll
    useEffect(() => {
        const node = scrollRef.current;
        if (!node) return;

        const onScroll = () => {
            const threshold = 60;
            if (node.scrollTop + node.clientHeight >= node.scrollHeight - threshold) {
                handleLoadMore();
            }
        };

        node.addEventListener("scroll", onScroll);
        return () => node.removeEventListener("scroll", onScroll);
    }, [handleLoadMore]);

    useEffect(() => {
        const root = scrollRef.current;
        const target = loadMoreRef.current;
        if (!root || !target) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting) handleLoadMore();
            },
            { root, rootMargin: "60px 0px", threshold: 0 }
        );
        observer.observe(target);
        return () => observer.disconnect();
    }, [handleLoadMore, visibleSpaces.length]);

    const handleJoin = async (space: KnowledgeSpace) => {
        // Rejected applications can be submitted again.
        const currentStatus =
            statusOverride?.[String(space.id)] ??
            ((space.squareStatus as SquareSpaceStatus) || "join");
        if (currentStatus !== "join" && currentStatus !== "rejected") return;
        // Per-space guard only: block double-submitting the SAME space, never
        // others. A single shared in-flight id silently dropped concurrent joins
        // to different spaces — clicking quickly across pages left some requests
        // unsent, so those spaces stayed "join" after a refresh.
        if (joiningIds.has(space.id)) return;

        setJoiningIds((prev) => new Set(prev).add(space.id));

        // No client-side cap: the join limit is role-configurable on the backend
        // (F005 quota knowledge_space_subscribe, default 100) and enforced there;
        // an over-limit attempt comes back as errcode 18032 and is surfaced below.
        try {
            const result = await subscribeSpaceApi(space.id);
            const nextStatus: SquareSpaceStatus = result.status === "subscribed" ? "joined" : "pending";
            updateSpaces((prev) =>
                prev.map((s) =>
                    s.id === space.id
                        ? {
                              ...s,
                              squareStatus: nextStatus,
                              subscriptionStatus: result.status,
                              isFollowed: nextStatus === "joined",
                              isPending: nextStatus === "pending",
                          }
                        : s
                )
            );
            onSquareStatusChange?.(String(space.id), nextStatus);
            if (nextStatus === "joined") {
                showToast({ message: localize("com_knowledge.join_success"), severity: NotificationSeverity.SUCCESS });
            } else {
                showToast({ message: `${tJoinPrefix}`, severity: NotificationSeverity.SUCCESS });
            }
        } catch (e) {
            // No optimistic space-list change to undo (status is set only on
            // success, via a per-space functional update), so just surface the
            // error; `finally` clears the in-flight flag for this space.
            const code = (e as any)?.status_code;
            const rawMessage =
                (e as any)?.message ||
                (e as any)?.status_message ||
                "";

            // Backend errcode 18032: SpaceSubscribeLimitError (join limit reached)
            if (code === 18032) {
                showToast({ message: localize("com_knowledge.join_space_limit_reached_50"), severity: NotificationSeverity.WARNING });
            } else {
                const message =
                    rawMessage ||
                    localize("com_knowledge.operation_failed_retry");
                showToast({ message, severity: NotificationSeverity.ERROR });
            }
        } finally {
            setJoiningIds((prev) => {
                const next = new Set(prev);
                next.delete(space.id);
                return next;
            });
        }
    };

    return (
        <div className="h-full w-full flex flex-col bg-white overflow-hidden">
            <div
                className="w-full relative overflow-hidden border-b border-[#F0F1F5] bg-blue-500/[0.05]"
            >
                {/* Decorative scattered icons — kept from the original banner art, recolored
                    via a brand-tinted mask layer so they follow the blue ⇄ green theme. */}
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 bg-blue-200"
                    style={{
                        WebkitMaskImage: `url(${__APP_ENV__.BASE_URL}/assets/tabbg-icons.svg)`,
                        maskImage: `url(${__APP_ENV__.BASE_URL}/assets/tabbg-icons.svg)`,
                        WebkitMaskSize: "cover",
                        maskSize: "cover",
                        WebkitMaskPosition: "center",
                        maskPosition: "center",
                        WebkitMaskRepeat: "no-repeat",
                        maskRepeat: "no-repeat",
                    }}
                />

                {onBack && (
                    <div className="absolute left-4 top-4 z-10">
                        <Button
                            variant="ghost"
                            onClick={onBack}
                            className="h-7 w-7 p-0 rounded-md border border-border-base bg-white text-text-2 hover:bg-fill-1 hover:text-blue-500"
                        >
                            <ArrowLeft className="size-3.5" />
                        </Button>
                    </div>
                )}

                <div className="relative mx-auto flex w-full max-w-[1140px] flex-col items-center justify-center px-4 pb-6 pt-7">
                    <h1 className="mb-1 text-[26px] font-semibold text-blue-500">{tTitle}</h1>
                    <p className="text-[13px] text-text-3">{tSubtitle}</p>
                </div>
            </div>

            <div
                ref={scrollRef}
                // `scrollbar-os` opts out of the global custom ::-webkit-scrollbar so the
                // native OS scrollbar setting (always-show vs show-on-scroll-only) is respected.
                // Without it, the global :not(.scrollbar-os) rule forces an always-present bar.
                className="flex-1 flex flex-col overflow-y-auto scrollbar-os bg-white"
            >
                {/* Outer holds width/centering + mobile side padding; inner `relative` anchors
                    the search icon so it stays aligned with the input after the padding inset. */}
                <div className="mx-auto mb-1 mt-6 w-full max-w-[480px] max-[767px]:px-4">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#8B8FA8] pointer-events-none" />
                        <Input
                            type="text"
                            placeholder={tSearchPlaceholder}
                            value={searchQuery}
                            onChange={handleSearch}
                            onCompositionStart={handleSearchCompositionStart}
                            onCompositionEnd={handleSearchCompositionEnd}
                            className="pl-9 h-8 text-[12px] rounded-md bg-white border-border-base focus:border-[#DDDDDD] focus:ring-2 focus:ring-[#F1F5F9]"
                        />
                    </div>
                </div>

                <div className="flex-1 flex flex-col w-full max-w-[1032px] mx-auto px-4 py-4">
                    {loading && spaces.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-text-3">
                            <LoadingIcon className="size-20 text-primary" />
                            <span className="text-sm">{localize("com_list_loading")}</span>
                        </div>
                    ) : initialError ? (
                        <div className="flex-1 flex items-center justify-center text-text-3">
                            <p className="text-[14px] font-normal text-text-3">{localize("com_list_load_failed")}</p>
                        </div>
                    ) : visibleSpaces.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-text-3">
                            <EmptyStateIllustration className="size-[120px] mb-4" />
                            <p className="text-[14px] font-normal text-text-3">{tEmptyText}</p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <div
                                className="grid gap-3"
                                style={{ gridTemplateColumns: `repeat(${squareCols}, minmax(0, 1fr))` }}
                            >
                                {visibleSpaces.map((space) => (
                                    <KnowledgeSquareCard
                                        key={space.id}
                                        space={space}
                                        status={
                                            statusOverride?.[String(space.id)] ??
                                            ((space.squareStatus as SquareSpaceStatus) || "join")
                                        }
                                        isActing={joiningIds.has(space.id)}
                                        onPreview={() => onPreviewSpace?.(space)}
                                        onAction={() => handleJoin(space)}
                                    />
                                ))}
                            </div>

                            <div ref={loadMoreRef} className="h-10 flex items-center justify-center text-[12px] text-text-4">
                                {loadingMore
                                    ? localize("com_list_loading_more")
                                    : loadMoreError
                                        ? localize("com_list_load_failed")
                                        : !hasMorePage
                                            ? localize("com_list_all_loaded")
                                            : ""}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
