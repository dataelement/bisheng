import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type CompositionEvent } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getSquareSpacesApi, subscribeSpaceApi, type KnowledgeSpace, VisibilityType } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import KnowledgeSquareCard from "./KnowledgeSquareCard";

type SquareSpaceStatus = "join" | "joined" | "pending" | "rejected";

interface KnowledgeSquareProps {
    onBack?: () => void;
    title?: string;
    subtitle?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    joinToastPrefix?: string;
    onPreviewSpace?: (spaceId: string) => void;
}

export default function KnowledgeSquare({
    onBack,
    title,
    subtitle,
    searchPlaceholder,
    emptyText,
    joinToastPrefix,
    onPreviewSpace,
}: KnowledgeSquareProps) {
    const { showToast } = useToastContext();
    const localize = useLocalize();

    const [searchQuery, setSearchQuery] = useState("");
    const [page, setPage] = useState(1);
    const [hasMorePage, setHasMorePage] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
    const [joiningId, setJoiningId] = useState<string | null>(null);

    const scrollRef = useRef<HTMLDivElement | null>(null);
    const searchImeComposingRef = useRef(false);
    const PAGE_SIZE = 20;

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

                const res = await getSquareSpacesApi({
                    page: nextPage,
                    page_size: PAGE_SIZE,
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
        [PAGE_SIZE]
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
        const nextStatus: SquareSpaceStatus =
            space.visibility === VisibilityType.PUBLIC ? "joined" : "pending";

        // Only join when currently "join"
        const currentStatus = (space.squareStatus as SquareSpaceStatus) || "join";
        if (currentStatus !== "join") return;
        if (joiningId) return;

        setJoiningId(space.id);
        const prevSpaces = spaces;

        setSpaces((prev) =>
            prev.map((s) =>
                s.id === space.id
                    ? { ...s, squareStatus: nextStatus, isFollowed: nextStatus === "joined", isPending: nextStatus === "pending" }
                    : s
            )
        );

        try {
            await subscribeSpaceApi(space.id);
            if (nextStatus === "joined") {
                showToast({ message: localize("com_knowledge.join_success"), severity: NotificationSeverity.SUCCESS });
            } else {
                showToast({ message: `${tJoinPrefix}${space.name}`, severity: NotificationSeverity.SUCCESS });
            }
        } catch {
            // rollback
            setSpaces(prevSpaces);
            showToast({ message: localize("com_knowledge.operation_failed_retry"), severity: NotificationSeverity.ERROR });
        } finally {
            setJoiningId(null);
        }
    };

    const spaceRows: KnowledgeSpace[][] = [];
    for (let i = 0; i < visibleSpaces.length; i += 3) {
        spaceRows.push(visibleSpaces.slice(i, i + 3));
    }

    return (
        <div className="h-full w-full flex flex-col bg-white overflow-hidden">
            <div
                className="w-full relative overflow-hidden border-b border-[#F0F1F5] bg-center bg-no-repeat bg-cover"
                style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/tabbg.svg)` }}
            >

                {onBack && (
                    <div className="absolute left-4 top-4 z-10">
                        <Button
                            variant="ghost"
                            onClick={onBack}
                            className="h-7 w-7 p-0 rounded-md border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] hover:text-[#165DFF]"
                        >
                            <ArrowLeft className="size-3.5" />
                        </Button>
                    </div>
                )}

                <div className="relative max-w-[1140px] mx-auto w-full flex flex-col items-center justify-center pt-7 pb-5 px-4">
                    <h1 className="text-[26px] font-semibold text-[#335CFF] mb-1">{tTitle}</h1>
                    <p className="text-[13px] text-[#86909C] mb-3">{tSubtitle}</p>
                </div>
            </div>

            <div ref={scrollRef} className="flex-1 overflow-y-auto bg-white">
                <div className="relative w-full max-w-[480px] mx-auto mt-2 mb-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#8B8FA8] pointer-events-none" />
                    <Input
                        type="text"
                        placeholder={tSearchPlaceholder}
                        value={searchQuery}
                        onChange={handleSearch}
                        onCompositionStart={handleSearchCompositionStart}
                        onCompositionEnd={handleSearchCompositionEnd}
                        className="pl-9 h-8 text-[12px] rounded-md bg-white border-[#E5E6EB] focus:border-[#165DFF]"
                    />
                </div>

                <div className="max-w-[1032px] mx-auto px-4 py-4">
                    {loading && spaces.length === 0 ? (
                        <div className="flex items-center justify-center h-64 text-[#86909C]">{localize("com_knowledge.loading")}</div>
                    ) : spaceRows.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-64 text-[#86909c]">
                            <img
                                className="size-[120px] mb-3 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] text-[#86909C]">{tEmptyText}</p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {spaceRows.map((row, rowIndex) => (
                                <div key={rowIndex} className="flex gap-3">
                                    {row.map((space) => (
                                        <KnowledgeSquareCard
                                            key={space.id}
                                            space={space}
                                            status={(space.squareStatus as SquareSpaceStatus) || "join"}
                                            onPreview={() => onPreviewSpace?.(space.id)}
                                            onAction={() => handleJoin(space)}
                                        />
                                    ))}

                                    {row.length < 3 && (
                                        <>
                                            {Array.from({ length: 3 - row.length }).map((_, i) => (
                                                <div key={`empty-${i}`} className="flex-1 min-w-0" />
                                            ))}
                                        </>
                                    )}
                                </div>
                            ))}

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

