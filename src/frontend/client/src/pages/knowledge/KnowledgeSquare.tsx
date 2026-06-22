import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type CompositionEvent } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import {
    getSquareSpacesApi,
    subscribeSpaceApi,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { useLocalize, useScrollRevealRef } from "~/hooks";
import KnowledgeSquareCard from "./KnowledgeSquareCard";

type SquareSpaceStatus = "join" | "joined" | "pending" | "rejected";

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

    const [searchQuery, setSearchQuery] = useState("");
    const [page, setPage] = useState(1);
    const [hasMorePage, setHasMorePage] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
    // In-flight join requests keyed by space id, so concurrent joins to
    // different spaces (e.g. clicking quickly across pages) don't block each
    // other — a single shared id used to silently drop them (see handleJoin).
    const [joiningIds, setJoiningIds] = useState<Set<string>>(() => new Set());

    const scrollRef = useRef<HTMLDivElement | null>(null);
    const scrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const searchImeComposingRef = useRef(false);
    // Larger page reduces the "subscribe reorders rows mid-pagination" issue:
    // the not-subscribed-first sort moves a space to the back the moment it's
    // joined, which with offset pagination skips/duplicates rows across pages.
    // Fitting more per page keeps most spaces on one page.
    const PAGE_SIZE = 60;

    const MAX_SEARCH_LEN = 40;

    const tTitle = title || localize("com_knowledge.explore_square");
    const tSubtitle = subtitle || localize("com_knowledge.explore_more_spaces");
    const tSearchPlaceholder = searchPlaceholder || localize("com_knowledge.search_space_placeholder");
    const tEmptyText = emptyText || localize("com_knowledge.no_matched_space");
    const tJoinPrefix = joinToastPrefix || localize("com_knowledge.applied_to_join_space");

    const visibleSpaces = useMemo(() => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return spaces;
        return spaces.filter(
            (s) => s.name.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q)
        );
    }, [spaces, searchQuery]);

    const load = useCallback(
        async (nextPage: number) => {
            try {
                if (nextPage === 1) setLoading(true);
                else setLoadingMore(true);

                const keyword = searchQuery.trim();
                const res = await getSquareSpacesApi({
                    page: nextPage,
                    page_size: PAGE_SIZE,
                    ...(keyword ? { keyword } : {}),
                });

                const list = (res.data || []) as KnowledgeSpace[];
                setSpaces((prev) => (nextPage === 1 ? list : [...prev, ...list]));
                setPage(nextPage);
                setHasMorePage(list.length >= PAGE_SIZE);
            } catch {
                // Keep existing list
            } finally {
                if (nextPage === 1) setLoading(false);
                else setLoadingMore(false);
            }
        },
        [PAGE_SIZE, searchQuery]
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

    // Infinite scroll
    useEffect(() => {
        const node = scrollRef.current;
        if (!node) return;

        const onScroll = () => {
            if (loadingMore || !hasMorePage) return;
            const threshold = 60;
            if (node.scrollTop + node.clientHeight >= node.scrollHeight - threshold) {
                load(page + 1);
            }
        };

        node.addEventListener("scroll", onScroll);
        return () => node.removeEventListener("scroll", onScroll);
    }, [hasMorePage, loadingMore, load, page]);

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
            setSpaces((prev) =>
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
                            className="h-7 w-7 p-0 rounded-md border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] hover:text-blue-500"
                        >
                            <ArrowLeft className="size-3.5" />
                        </Button>
                    </div>
                )}

                <div className="relative mx-auto flex w-full max-w-[1140px] flex-col items-center justify-center px-4 pb-6 pt-7">
                    <h1 className="mb-1 text-[26px] font-semibold text-blue-500">{tTitle}</h1>
                    <p className="text-[13px] text-[#86909C]">{tSubtitle}</p>
                </div>
            </div>

            <div
                ref={(el) => {
                    scrollRef.current = el;
                    scrollRevealRef(el);
                }}
                className="flex-1 flex flex-col overflow-y-auto scrollbar-on-scroll bg-white"
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
                            className="pl-9 h-8 text-[12px] rounded-md bg-white border-[#E5E6EB] focus:border-[#DDDDDD] focus:ring-2 focus:ring-[#F1F5F9]"
                        />
                    </div>
                </div>

                <div className="flex-1 flex flex-col w-full max-w-[1032px] mx-auto px-4 py-4">
                    {loading && spaces.length === 0 ? (
                        <div className="flex-1 flex items-center justify-center text-[#86909C]">{localize("com_knowledge.loading")}</div>
                    ) : visibleSpaces.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-[#86909c]">
                            <img
                                className="size-[120px] mb-3 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] text-[#86909C]">{tEmptyText}</p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <div className="grid grid-cols-2 gap-3 min-[768px]:grid-cols-3">
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

                            <div className="h-10 flex items-center justify-center text-[12px] text-[#C9CDD4]">
                                {loadingMore ? localize("com_knowledge.loading") : !hasMorePage ? localize("com_knowledge.no_more_content") : ""}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
