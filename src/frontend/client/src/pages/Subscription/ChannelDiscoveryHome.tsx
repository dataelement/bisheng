import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { TransitionEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getRecommendedChannelsApi, subscribeManagerChannelApi } from "~/api/channels";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { cn } from "~/utils";
import { ChannelSquareCard } from "../ChannelSquareCard";
import { SERIF_FONT_STACK } from "./ArticleList/ChannelSwitcher";

type DiscoverStatus = "join" | "joined" | "pending" | "private" | "rejected";

interface DiscoverChannel {
    id: string;
    title: string;
    description: string;
    creator: string;
    creatorAvatars: string[];
    articleCount: number;
    subscriberCount: number;
    status: DiscoverStatus;
    visibility?: "public" | "private" | "review";
}

interface ChannelDiscoveryHomeProps {
    /** Gate the recommend query — only fetch while the empty home state is shown. */
    enabled: boolean;
    isH5: boolean;
    /** Pause auto-rotate while the preview drawer is open. */
    previewOpen?: boolean;
    /** Open the mobile system menu (H5 header button). */
    onOpenMobileNav?: () => void;
    /** Open the preview drawer for a channel (card click). */
    onPreviewChannel: (id: string) => void;
    /** Go to the full channel plaza. */
    onGoSquare: () => void;
    /** Open the create-channel drawer. */
    onCreateChannel: () => void;
}

// Carousel card geometry — matches the Figma card (≈326w, 12 gap).
const CARD_WIDTH = 326;
const CARD_GAP = 12;
const AUTO_ROTATE_MS = 3000;
// Minimum number of public channels required to show the carousel; below this we
// fall back to the empty illustration (per spec).
const MIN_CAROUSEL_CHANNELS = 3;

const mapRecommendItem = (item: any): DiscoverChannel | null => {
    const rawId = item?.id ?? item?.channel_id;
    if (!rawId) return null;
    const sourceInfos: any[] = Array.isArray(item.source_infos) ? item.source_infos : [];
    const avatars = sourceInfos.map((s) => s.source_icon).filter(Boolean).slice(0, 3);
    const subStatus = String(item.subscription_status ?? "");
    const status: DiscoverStatus =
        subStatus === "subscribed" ? "joined"
            : subStatus === "pending" ? "pending"
                : subStatus === "rejected" ? "rejected"
                    : "join";
    return {
        id: String(rawId),
        title: String(item.name ?? item.title ?? ""),
        description: String(item.description ?? item.desc ?? "") || "暂无简介",
        creator: String(item.creator ?? item.creator_name ?? ""),
        creatorAvatars: avatars,
        articleCount: Number(item.article_count ?? 0),
        subscriberCount: Number(item.subscriber_count ?? 0),
        visibility: item.visibility as DiscoverChannel["visibility"],
        status,
    };
};

export function ChannelDiscoveryHome({
    enabled,
    isH5,
    previewOpen = false,
    onOpenMobileNav,
    onPreviewChannel,
    onGoSquare,
    onCreateChannel,
}: ChannelDiscoveryHomeProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const [paused, setPaused] = useState(false);
    const [joiningId, setJoiningId] = useState<string | null>(null);
    // Optimistic subscribe status overrides, keyed by channel id (the list itself is
    // derived from the query so a cached remount paints the carousel immediately).
    const [statusOverrides, setStatusOverrides] = useState<Record<string, DiscoverStatus>>({});
    // Infinite loop carousel. The track renders the ranked list three times; `pos`
    // is the track index of the centered card and only ever increases. It starts in
    // the MIDDLE copy so the left/right neighbours are always populated (initial
    // window = [last, #1, #2, #3]). After scrolling one full period it snaps back by
    // one copy with no animation — invisible because the content is identical.
    const [pos, setPos] = useState(0);
    // Off until the first centered frame has painted, so there's no entrance slide.
    const [animate, setAnimate] = useState(false);
    const viewportRef = useRef<HTMLDivElement | null>(null);
    const trackRef = useRef<HTMLDivElement | null>(null);
    const [viewportWidth, setViewportWidth] = useState(0);

    const { data, isLoading, isFetched } = useQuery({
        queryKey: ["channelRecommend"],
        queryFn: () => getRecommendedChannelsApi({ limit: 12 }),
        enabled,
        staleTime: 60_000,
    });

    // Derive the list straight from the query (no post-paint state sync), so switching
    // back from the plaza with cached data paints the carousel on the first frame —
    // no empty-illustration flash that would shift the vertically centered content.
    const channels = useMemo(() => {
        const root: any = data;
        if (!root) return [] as DiscoverChannel[];
        const payload = root.data ?? root;
        const list: any[] = (payload?.data || payload?.list || []) as any[];
        return list
            .map(mapRecommendItem)
            .filter((c): c is DiscoverChannel => c !== null)
            .map((c) => (statusOverrides[c.id] ? { ...c, status: statusOverrides[c.id] } : c));
    }, [data, statusOverrides]);

    // Carousel only on PC with enough public channels (otherwise the empty illustration).
    const count = channels.length;
    const showCarousel = !isH5 && count >= MIN_CAROUSEL_CHANNELS;

    // Three concatenated copies so there are always neighbours on both sides while
    // `pos` walks through the middle copy.
    const looped = useMemo(
        () => (showCarousel ? [...channels, ...channels, ...channels] : []),
        [channels, showCarousel]
    );

    // Center on the highest-ranked card in the middle copy (index N) before paint, so
    // there's no horizontal settle on (re)mount. Only runs when the count changes.
    useLayoutEffect(() => {
        if (count > 0) setPos(count);
    }, [count]);

    // Measure the viewport so the centered card can be positioned precisely.
    useLayoutEffect(() => {
        if (!showCarousel) return;
        const node = viewportRef.current;
        if (!node) return;
        const measure = () => setViewportWidth(node.clientWidth);
        measure();
        window.addEventListener("resize", measure);
        return () => window.removeEventListener("resize", measure);
    }, [showCarousel]);

    // Enable the slide transition only after the first centered frame is painted.
    useEffect(() => {
        if (!showCarousel || !viewportWidth) return;
        const id = requestAnimationFrame(() => setAnimate(true));
        return () => cancelAnimationFrame(id);
    }, [showCarousel, viewportWidth]);

    // Auto-advance: move the centered card forward one step (scrolls right-to-left).
    // Paused on hover or while the preview drawer is open.
    useEffect(() => {
        if (!showCarousel || paused || previewOpen || count < 1) return;
        const timer = window.setInterval(() => {
            setAnimate(true);
            setPos((p) => p + 1);
        }, AUTO_ROTATE_MS);
        return () => window.clearInterval(timer);
    }, [showCarousel, paused, previewOpen, count]);

    // Seamless loop: once a full period has scrolled (pos reaches the third copy),
    // jump back by one copy with animation off — the content lines up exactly.
    const handleTrackTransitionEnd = (e: TransitionEvent<HTMLDivElement>) => {
        if (e.target !== trackRef.current || e.propertyName !== "transform") return;
        if (count > 0 && pos >= 2 * count) {
            setAnimate(false);
            setPos((p) => p - count);
            // Re-enable animation after the no-transition re-position has painted.
            requestAnimationFrame(() => requestAnimationFrame(() => setAnimate(true)));
        }
    };

    const handleSubscribe = useCallback(
        (channelId: string) => {
            const target = channels.find((c) => c.id === channelId);
            if (!target || target.status !== "join" || joiningId) return;
            (async () => {
                try {
                    setJoiningId(channelId);
                    const nextStatus: DiscoverStatus = target.visibility === "public" ? "joined" : "pending";
                    setStatusOverrides((prev) => ({ ...prev, [channelId]: nextStatus }));
                    const res: any = await subscribeManagerChannelApi({ channel_id: channelId });
                    const statusCode = res?.status_code ?? res?.code;
                    if (statusCode && statusCode !== 200) {
                        throw new Error(res?.status_message || res?.message || "subscribe failed");
                    }
                    showToast({
                        message:
                            target.visibility === "public"
                                ? localize("subscribe_success") || "订阅成功"
                                : localize("com_subscription.apply_sent") || "申请已发送",
                        severity: NotificationSeverity.SUCCESS,
                    });
                    // Refresh background channel lists so the page auto-selects the new channel
                    // and leaves this empty state.
                    queryClient.invalidateQueries({ queryKey: ["channels", "subscribed"] });
                    queryClient.invalidateQueries({ queryKey: ["channels"] });
                } catch {
                    // Roll back on failure (interceptor surfaces the toast).
                    setStatusOverrides((prev) => {
                        const next = { ...prev };
                        delete next[channelId];
                        return next;
                    });
                } finally {
                    setJoiningId(null);
                }
            })();
        },
        [channels, joiningId, localize, queryClient, showToast]
    );

    const renderHeader = () => {
        if (isH5) {
            return (
                <div className="absolute inset-x-0 top-0 z-10 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                    <div className="relative flex h-11 items-center px-4">
                        <button
                            type="button"
                            aria-label={localize("com_nav_open_sidebar")}
                            onClick={onOpenMobileNav}
                            className="inline-flex size-5 shrink-0 items-center justify-center text-[#212121]"
                        >
                            <Outlined.SidebarMenu className="size-5" />
                        </button>
                        {/* 频道/广场 切换器为跨视图常驻单实例（见 Subscription/index），
                            屏幕居中悬浮在此行之上，这里不再各自渲染。 */}
                    </div>
                </div>
            );
        }
        // Match the content-view header title (ChannelSwitcher): same px-10/pt-5 offset,
        // 32px bold serif #212121.
        return (
            <h1
                className="shrink-0 px-10 pt-5 pb-4 text-[32px] font-bold leading-[40px] text-[#212121]"
                style={{ fontFamily: SERIF_FONT_STACK }}
            >
                {localize("com_subscription.subscribe")}
            </h1>
        );
    };

    const renderBottomActions = () => (
        <div className="flex flex-col items-center gap-5">
            <p className="text-[14px] leading-6 text-[#999999]">
                {localize("com_subscription.no_subscription_content_you_can")}
            </p>
            <div className="flex items-center gap-4">
                <button
                    type="button"
                    onClick={onGoSquare}
                    className="h-8 rounded-md border border-[#E5E6EB] bg-white px-4 text-[14px] leading-[22px] text-[#4E5969] transition-colors fine-pointer:hover:border-[#165DFF] fine-pointer:hover:text-[#165DFF]"
                >
                    {localize("com_subscription.go_to_square")}
                </button>
                <button
                    type="button"
                    onClick={onCreateChannel}
                    className="h-8 rounded-md bg-[#165DFF] px-4 text-[14px] leading-[22px] text-white transition-colors fine-pointer:hover:bg-[#4080FF] active:bg-[#0E42D2]"
                >
                    {localize("com_subscription.create_channel")}
                </button>
            </div>
        </div>
    );

    const renderEmptyIllustration = () => (
        <img
            className="size-[120px] object-contain opacity-90"
            src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
            alt="empty"
        />
    );

    const renderCarousel = () => {
        // Center the card at track index `pos`: viewportCenter - that card's center.
        const trackTranslate =
            viewportWidth / 2 - (pos * (CARD_WIDTH + CARD_GAP) + CARD_WIDTH / 2);
        return (
            <div
                ref={viewportRef}
                // overflow-hidden clips the side cards horizontally; CSS can't clip one
                // axis only, so generous vertical padding (>= the hover shadow's ~28px
                // reach) keeps the centered card's shadow from being cropped. Height
                // follows the in-flow track so the card never gets cut off.
                className="relative w-full max-w-[1000px] overflow-hidden py-8"
                onMouseEnter={() => setPaused(true)}
                onMouseLeave={() => setPaused(false)}
            >
                <div
                    ref={trackRef}
                    className="flex items-center will-change-transform"
                    style={{
                        gap: CARD_GAP,
                        transform: `translateX(${trackTranslate}px)`,
                        // No transition before measuring, or during the seamless loop snap-back.
                        transition: viewportWidth && animate ? "transform 500ms ease-out" : "none",
                    }}
                    onTransitionEnd={handleTrackTransitionEnd}
                >
                    {looped.map((channel, index) => (
                        <div
                            key={`${channel.id}-${index}`}
                            className="shrink-0 transition-opacity duration-500"
                            style={{ width: CARD_WIDTH, opacity: index === pos ? 1 : 0.55 }}
                        >
                            <ChannelSquareCard
                                title={channel.title}
                                description={channel.description}
                                creator={channel.creator}
                                creatorAvatars={channel.creatorAvatars}
                                articleCount={channel.articleCount}
                                subscriberCount={channel.subscriberCount}
                                status={channel.status}
                                visibility={channel.visibility}
                                onPreview={() => onPreviewChannel(channel.id)}
                                onAction={() => handleSubscribe(channel.id)}
                            />
                        </div>
                    ))}
                </div>
                {/* Edge fade masks so the side cards bleed out softly. */}
                <div className="pointer-events-none absolute inset-y-0 left-0 w-[22%] bg-gradient-to-r from-white via-white/85 to-transparent" />
                <div className="pointer-events-none absolute inset-y-0 right-0 w-[22%] bg-gradient-to-l from-white via-white/85 to-transparent" />
            </div>
        );
    };

    const renderCenter = () => {
        // Wait for the first fetch so neither the carousel nor the empty state flashes.
        if (enabled && !isFetched && isLoading) {
            return <LoadingIcon className="size-20 text-primary" />;
        }
        return showCarousel ? renderCarousel() : renderEmptyIllustration();
    };

    return (
        <div className="relative flex min-h-0 flex-1 flex-col bg-white">
            {renderHeader()}
            <div
                className={cn(
                    "flex min-h-0 flex-1 flex-col items-center justify-center px-4 pb-16",
                    // Carousel supplies its own spacing via the viewport's py-8; only the
                    // empty illustration / loading states need the gap to the actions.
                    !showCarousel && "gap-9",
                    isH5 && "pt-11"
                )}
            >
                {renderCenter()}
                {renderBottomActions()}
            </div>
        </div>
    );
}
