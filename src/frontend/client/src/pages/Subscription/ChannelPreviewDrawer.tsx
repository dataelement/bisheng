import { useLocalize } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import {
    type ChannelDetailResponse,
    getArticlesApi,
    getChannelDetailApi,
    subscribeManagerChannelApi,
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { InfiniteScroll } from "~/components/InfiniteScroll";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useAuthContext } from "~/hooks/AuthContext";
import { useToastContext } from "~/Providers";
import { ArticleCard } from "./ArticleList/ArticleCard";
import { mapToArticle } from "./ArticleList/ArticleList";

const PREVIEW_PAGE_SIZE = 10;
const MAX_SUBSCRIPTIONS = 20;

interface ChannelPreviewDrawerProps {
    channelId: string | undefined;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Called after subscribe / apply succeeds so the channel square list can refetch. */
    onSubscriptionChanged?: () => void;
}

type SubscribeStatus = "none" | "subscribed" | "pending";

export function ChannelPreviewDrawer({ channelId, open, onOpenChange, onSubscriptionChanged }: ChannelPreviewDrawerProps) {
    const localize = useLocalize();
    const navigate = useNavigate();
    const { showToast } = useToastContext();
    const { user } = useAuthContext();
    const queryClient = useQueryClient();
    const [subscribeStatus, setSubscribeStatus] = useState<SubscribeStatus>("none");
    const [subscribing, setSubscribing] = useState(false);
    const [articles, setArticles] = useState<any[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [isBodyScrolling, setIsBodyScrolling] = useState(false);
    const bodyScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // 切换频道/关闭抽屉时，重置本地订阅交互态，避免状态串到下一条频道
    useEffect(() => {
        if (!open) {
            setSubscribeStatus("none");
            setSubscribing(false);
            return;
        }
        setSubscribeStatus("none");
    }, [channelId, open]);

    // Fetch channel detail
    const {
        data: channelDetail,
        isLoading: isDetailLoading,
        isError: isDetailError,
    } = useQuery({
        queryKey: ["channelPreviewDetail", channelId],
        queryFn: async () => {
            const res: any = await getChannelDetailApi(channelId!);
            if (res?.status_code && res.status_code !== 200) {
                throw new Error(res.status_message || localize("com_subscription.channel_load_failed"));
            }
            return res;
        },
        enabled: !!channelId && open,
        staleTime: 0,
        refetchOnMount: "always",
    });

    // Fetch article list
    const {
        data: articlesData,
        isLoading: isArticlesLoading,
        isError: isArticlesError,
    } = useQuery({
        queryKey: ["channelPreviewArticles", channelId],
        queryFn: async () => {
            const res: any = await getArticlesApi({
                channelId: channelId!,
                page: 1,
                pageSize: PREVIEW_PAGE_SIZE,
            });
            if (res?.status_code && res.status_code !== 200) {
                throw new Error(res.status_message || localize("com_subscription.article_load_failed"));
            }
            return res;
        },
        enabled: !!channelId && open,
        staleTime: 0,
        refetchOnMount: "always",
    });

    const isLoading = isDetailLoading || isArticlesLoading;

    useEffect(() => {
        if (!channelId) {
            setArticles([]);
            setCurrentPage(1);
            setHasMore(false);
            return;
        }
        const mapped = (articlesData?.data || []).map(item => mapToArticle(item, channelId));
        setArticles(mapped);
        setCurrentPage(1);
        const total = articlesData?.total || 0;
        setHasMore(PREVIEW_PAGE_SIZE < total);
    }, [channelId, articlesData]);

    const loadMoreArticles = async () => {
        if (!channelId || loadingMore || !hasMore) return;
        const nextPage = currentPage + 1;
        setLoadingMore(true);
        try {
            const res: any = await getArticlesApi({
                channelId,
                page: nextPage,
                pageSize: PREVIEW_PAGE_SIZE,
            });
            if (res?.status_code && res.status_code !== 200) {
                throw new Error(res.status_message || localize("com_subscription.article_load_failed"));
            }
            const nextMapped = (res?.data || []).map((item: any) => mapToArticle(item, channelId));
            setArticles(prev => [...prev, ...nextMapped]);
            setCurrentPage(nextPage);
            const total = res?.total || 0;
            setHasMore(nextPage * PREVIEW_PAGE_SIZE < total);
        } catch (e: any) {
            showToast({
                message: e?.message || localize("com_subscription.article_load_failed"),
                severity: NotificationSeverity.ERROR,
            });
            setHasMore(false);
        } finally {
            setLoadingMore(false);
        }
    };

    // Handle subscribe action
    const handleSubscribe = async () => {
        if (!channelId || subscribing || subscribeStatus === "subscribed" || subscribeStatus === "pending") return;

        setSubscribing(true);
        try {
            const res: any = await subscribeManagerChannelApi({ channel_id: channelId });
            const root = res;
            const statusCode = root?.status_code ?? root?.code;
            if (statusCode && statusCode !== 200) {
                const msg =
                    root?.status_message ||
                    root?.message ||
                    localize("com_subscription.subscribe_failed_retry");
                throw new Error(msg);
            }

            if (channelDetail?.visibility === "review") {
                setSubscribeStatus("pending");
                showToast({ message: localize("com_subscription.subscribe_application_sent"), severity: NotificationSeverity.SUCCESS });
            } else {
                setSubscribeStatus("subscribed");
                showToast({ message: localize("com_subscription.subscribe_success"), severity: NotificationSeverity.SUCCESS });
            }

            // Refresh background channel lists (sidebar uses ["channels","subscribed",sort])
            queryClient.invalidateQueries({ queryKey: ["channels", "subscribed"] });
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            queryClient.invalidateQueries({ queryKey: ["channelPreviewDetail", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channelPreviewArticles", channelId] });
            onSubscriptionChanged?.();
        } catch (e: any) {
            const msg =
                e?.response?.data?.status_message ||
                e?.message ||
                localize("com_subscription.subscribe_failed_retry");
            showToast({ message: msg, severity: NotificationSeverity.ERROR });
        } finally {
            setSubscribing(false);
        }
    };

    // Button config based on effective subscribe status
    const getButtonConfig = (status: SubscribeStatus) => {
        if (status === "subscribed") {
            return { text: localize("com_subscription.subscribed"), disabled: true, variant: "secondary" as const };
        }
        if (status === "pending") {
            return { text: localize("com_subscription.applying"), disabled: true, variant: "secondary" as const };
        }
        return { text: localize("com_subscription.subscribe"), disabled: false, variant: "outline" as const };
    };
    const isCreatorView =
        Boolean(user?.username) && Boolean(channelDetail?.creator_name) && user?.username === channelDetail?.creator_name;



    const effectiveSubscribeStatus: SubscribeStatus = (() => {
        // 优先使用本地交互态（点击订阅后的即时反馈），否则使用详情接口状态
        if (subscribeStatus !== "none") return subscribeStatus;
        if (channelDetail?.subscription_status === "subscribed") return "subscribed";
        if (channelDetail?.subscription_status === "pending") return "pending";
        return "none";
    })();
    const btnConfig = getButtonConfig(effectiveSubscribeStatus);

    // 需审核频道：非创建者且未订阅/未通过时才隐藏文章列表；创建者需可查看文章
    const hideArticles =
        channelDetail?.visibility === "review" &&
        !isCreatorView &&
        effectiveSubscribeStatus !== "subscribed";

    const handleBodyScroll = () => {
        setIsBodyScrolling(true);
        if (bodyScrollTimerRef.current) clearTimeout(bodyScrollTimerRef.current);
        bodyScrollTimerRef.current = setTimeout(() => setIsBodyScrolling(false), 500);
    };

    // Handle error — channel not found, inaccessible, or articles cannot be loaded
    useEffect(() => {
        if (open && (isDetailError || isArticlesError)) {
            showToast({ message: localize("com_subscription.channel_invalid_or_inaccessible"), severity: NotificationSeverity.WARNING });
            onOpenChange(false);
            navigate("/channel?square=1", { replace: true });
        }
    }, [isDetailError, isArticlesError, open]);

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className="w-[1000px] sm:max-w-[1000px] p-0 px-16 flex flex-col"
                hideClose
                onCloseAutoFocus={(e) => e.preventDefault()}
            >
                <button
                    type="button"
                    aria-label="收起抽屉"
                    onClick={() => onOpenChange(false)}
                    className="absolute left-1 top-1/2 -translate-y-1/2 h-16 w-6 bg-white text-[#C9CDD4] hover:text-[#B6BBC5] flex items-center justify-center z-20"
                >
                    <ChevronRight className="size-6 stroke-[2.75]" />
                </button>
                {isLoading ? (
                    <div className="flex flex-col items-center justify-center h-full gap-3 text-[#86909c]">
                        <LoadingIcon className="size-16 text-primary" />
                    </div>
                ) : channelDetail ? (
                    <>
                        {/* Channel Info Header */}
                        <SheetHeader className="px-6 pt-6 pb-4 gap-0 border-b border-gray-100 text-left">
                            {/* Channel Name */}
                            <SheetTitle className="font-semibold text-[#1d2129] leading-tight mb-1">
                                {channelDetail.name}
                            </SheetTitle>

                            {/* Description (2-line clamp + tooltip) */}
                            {channelDetail.description && (
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <p className="text-sm text-[#86909c] leading-relaxed line-clamp-2 cursor-default text-left">
                                            {channelDetail.description}
                                        </p>
                                    </TooltipTrigger>
                                    <TooltipContent className="shadow-lg py-2 max-w-md text-sm">
                                        {channelDetail.description}
                                    </TooltipContent>
                                </Tooltip>
                            )}

                            {/* Creator Info */}
                            <div className="flex items-center gap-1.5 mb-3 mt-4">
                                <Avatar className="w-5 h-5">
                                    {/* Backend currently doesn't provide creator_avatar, use AvatarName fallback directly for now */}
                                    <AvatarName name={channelDetail.creator_name} className="text-xs" />
                                </Avatar>
                                <span className="text-sm text-[#86909c]">{channelDetail.creator_name}</span>
                            </div>

                            {/* Data Overview Row & Button */}
                            <div className="flex items-center justify-between">
                                <div className="flex items-center text-sm text-[#86909c]">
                                    {channelDetail.source_infos && channelDetail.source_infos.length > 0 && (
                                        <div className="flex items-center mr-3">
                                            <div className="flex -space-x-1.5">
                                                {channelDetail.source_infos.slice(0, 4).map((source: any, index: number) => (
                                                    <div
                                                        key={source.id}
                                                        className="size-5 rounded-[4px] border border-white overflow-hidden bg-gray-100"
                                                        style={{ zIndex: 4 - index }}
                                                    >
                                                        <img
                                                            src={source.source_icon || source.icon || "/default-source.png"}
                                                            alt={source.source_name || source.name}
                                                            className="w-full h-full object-cover rounded-md"
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    <span className="mr-3">{channelDetail.article_count ?? 0}{localize("com_subscription.articles_count")}</span>
                                    <span>{channelDetail.subscriber_count ?? 0}{localize("com_subscription.subscribe")}</span>
                                </div>

                                {/* Hide subscribe button for private channels or if the user is the creator */}
                                {channelDetail.visibility !== "private" && (
                                    <Button
                                        variant={btnConfig.variant}
                                        disabled={btnConfig.disabled || subscribing}
                                        onClick={handleSubscribe}
                                        className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${effectiveSubscribeStatus === "subscribed"
                                            ? "bg-[#f2f3f5] text-[#86909c] border-[#e5e6eb] cursor-default"
                                            : effectiveSubscribeStatus === "pending"
                                                ? "bg-[#f2f3f5] text-[#c9cdd4] border-[#e5e6eb] cursor-not-allowed"
                                                : "text-[#1d2129] border-[#e5e6eb] hover:bg-gray-50"
                                            }`}
                                    >
                                        {subscribing ? localize("com_subscription.processing") : btnConfig.text}
                                    </Button>
                                )}
                            </div>
                        </SheetHeader>

                        {/* Article List / Pending Message */}
                        <div
                            className="flex-1 overflow-y-auto scroll-on-scroll px-6"
                            onScroll={handleBodyScroll}
                            data-scrolling={isBodyScrolling ? "true" : "false"}
                        >
                            {hideArticles ? (
                                <div className="flex flex-col items-center justify-center h-full min-h-[400px]">
                                    <img
                                        className="size-[120px] object-contain mb-4"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/review.png`}
                                        alt="Review Pending"
                                    />
                                    <div className="text-[#1d2129] text-[14px]">{localize("com_subscription.channel_content_needs_approval")}</div>
                                </div>
                            ) : articles.length > 0 ? (
                                <InfiniteScroll
                                    loadMore={loadMoreArticles}
                                    hasMore={hasMore}
                                    isLoading={loadingMore}
                                    emptyText={localize("com_subscription.all_messages_are_here")}
                                    className=""
                                >
                                    {articles.map(article => (
                                        <ArticleCard
                                            key={article.id}
                                            article={article}
                                            onSelect={(a) => {
                                                const url = (a?.url || "").trim();
                                                if (!url) {
                                                    showToast({
                                                        message: localize("com_subscription.no_original_link"),
                                                        severity: NotificationSeverity.WARNING
                                                    });
                                                    return;
                                                }
                                                window.open(url, "_blank", "noopener,noreferrer");
                                            }}
                                            isSelected={false}
                                        />
                                    ))}
                                </InfiniteScroll>
                            ) : (
                                <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">{localize("com_subscription.no_articles")}</div>
                            )}
                        </div>
                    </>
                ) : null}
            </SheetContent>
        </Sheet>
    );
}
