import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getRecommendedChannelsApi, subscribeManagerChannelApi } from "~/api/channels";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { cn } from "~/utils";
import { ChannelSquareCard } from "../ChannelSquareCard";

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
const AUTO_ROTATE_MS = 4000;
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
    onOpenMobileNav,
    onPreviewChannel,
    onGoSquare,
    onCreateChannel,
}: ChannelDiscoveryHomeProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const [channels, setChannels] = useState<DiscoverChannel[]>([]);
    const [activeIndex, setActiveIndex] = useState(0);
    const [paused, setPaused] = useState(false);
    const [joiningId, setJoiningId] = useState<string | null>(null);
    // Ping-pong direction for auto-rotate (+1 forward, -1 backward) — avoids the
    // long "jump back to start" slide of a wrap-around carousel.
    const dirRef = useRef(1);
    const viewportRef = useRef<HTMLDivElement | null>(null);
    const [viewportWidth, setViewportWidth] = useState(0);

    const { data, isLoading, isFetched } = useQuery({
        queryKey: ["channelRecommend"],
        queryFn: () => getRecommendedChannelsApi({ limit: 12 }),
        enabled,
        staleTime: 60_000,
    });

    // Sync local list from the query (local copy reflects optimistic subscribe status).
    useEffect(() => {
        const root: any = data;
        if (!root) return;
        const payload = root.data ?? root;
        const list: any[] = (payload?.data || payload?.list || []) as any[];
        const mapped = list.map(mapRecommendItem).filter((c): c is DiscoverChannel => c !== null);
        setChannels(mapped);
        setActiveIndex(0);
        dirRef.current = 1;
    }, [data]);

    // Carousel only on PC with enough public channels (otherwise the empty illustration).
    const count = channels.length;
    const showCarousel = !isH5 && count >= MIN_CAROUSEL_CHANNELS;

    // Measure the viewport so the active card can be centered precisely.
    useLayoutEffect(() => {
        if (!showCarousel) return;
        const node = viewportRef.current;
        if (!node) return;
        const measure = () => setViewportWidth(node.clientWidth);
        measure();
        window.addEventListener("resize", measure);
        return () => window.removeEventListener("resize", measure);
    }, [showCarousel]);

    // Auto-rotate the centered card, bouncing at the ends.
    useEffect(() => {
        if (!showCarousel || paused || count < 2) return;
        const timer = window.setInterval(() => {
            setActiveIndex((i) => {
                let next = i + dirRef.current;
                if (next >= count) {
                    dirRef.current = -1;
                    next = i - 1;
                } else if (next < 0) {
                    dirRef.current = 1;
                    next = i + 1;
                }
                return next;
            });
        }, AUTO_ROTATE_MS);
        return () => window.clearInterval(timer);
    }, [showCarousel, paused, count]);

    const handleSubscribe = useCallback(
        (channelId: string) => {
            const target = channels.find((c) => c.id === channelId);
            if (!target || target.status !== "join" || joiningId) return;
            (async () => {
                try {
                    setJoiningId(channelId);
                    const nextStatus: DiscoverStatus = target.visibility === "public" ? "joined" : "pending";
                    setChannels((prev) =>
                        prev.map((c) => (c.id === channelId ? { ...c, status: nextStatus } : c))
                    );
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
                    setChannels((prev) =>
                        prev.map((c) => (c.id === channelId ? { ...c, status: target.status } : c))
                    );
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
                            className="inline-flex size-8 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]"
                        >
                            <Outlined.SidebarMenu className="size-5" />
                        </button>
                        <h1 className="pointer-events-none absolute left-1/2 -translate-x-1/2 text-[16px] font-medium leading-6 text-[#212121]">
                            {localize("com_subscription.subscribe")}
                        </h1>
                    </div>
                </div>
            );
        }
        return (
            <h1 className="shrink-0 px-10 pt-5 text-[28px] font-semibold leading-10 text-[#1D2129]">
                {localize("com_subscription.subscribe")}
            </h1>
        );
    };

    const renderBottomActions = () => (
        <div className="flex flex-col items-center gap-5">
            <p className="text-[14px] leading-6 text-[#4E5969]">
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
        // Center the active card: viewportCenter - (active card's center within the track).
        const trackTranslate =
            viewportWidth / 2 - (activeIndex * (CARD_WIDTH + CARD_GAP) + CARD_WIDTH / 2);
        return (
            <div
                ref={viewportRef}
                className="relative h-[140px] w-full max-w-[1000px] overflow-hidden"
                onMouseEnter={() => setPaused(true)}
                onMouseLeave={() => setPaused(false)}
            >
                <div
                    className="absolute top-1/2 left-0 flex -translate-y-1/2 will-change-transform"
                    style={{
                        gap: CARD_GAP,
                        transform: `translateX(${trackTranslate}px)`,
                        // Skip the entrance slide before the viewport width is measured.
                        transition: viewportWidth ? "transform 500ms ease-out" : "none",
                    }}
                >
                    {channels.map((channel, index) => (
                        <div
                            key={channel.id}
                            className="shrink-0 transition-opacity duration-500"
                            style={{ width: CARD_WIDTH, opacity: index === activeIndex ? 1 : 0.55 }}
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
                                isHighlighted={index === activeIndex}
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
                    "flex min-h-0 flex-1 flex-col items-center justify-center gap-9 px-4 pb-16",
                    isH5 && "pt-11"
                )}
            >
                {renderCenter()}
                {renderBottomActions()}
            </div>
        </div>
    );
}
