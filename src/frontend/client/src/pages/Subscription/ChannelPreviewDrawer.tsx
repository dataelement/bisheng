import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    type ChannelDetailResponse,
    getArticlesApi,
    getChannelDetailApi,
    subscribeManagerChannelApi,
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/avatar";
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
    onNavigateToChannel?: (channelId: string) => void;
}

type SubscribeStatus = "none" | "subscribed" | "pending";

export function ChannelPreviewDrawer({ channelId, open, onOpenChange, onNavigateToChannel }: ChannelPreviewDrawerProps) {
    const navigate = useNavigate();
    const { showToast } = useToastContext();
    const { user } = useAuthContext();
    const [subscribeStatus, setSubscribeStatus] = useState<SubscribeStatus>("none");
    const [subscribing, setSubscribing] = useState(false);

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
                throw new Error(res.status_message || "频道加载失败");
            }
            return res;
        },
        enabled: !!channelId && open,
        staleTime: 30_000,
    });

    // Fetch article list
    const {
        data: articlesData,
        isLoading: isArticlesLoading,
    } = useQuery({
        queryKey: ["channelPreviewArticles", channelId],
        queryFn: async () => {
            const res: any = await getArticlesApi({
                channelId: channelId!,
                page: 1,
                pageSize: PREVIEW_PAGE_SIZE,
            });
            if (res?.status_code && res.status_code !== 200) {
                throw new Error(res.status_message || "文章加载失败");
            }
            return res;
        },
        enabled: !!channelId && open,
        staleTime: 30_000,
    });

    console.log('channelDetail :>> ', channelDetail, articlesData);

    const articles = (articlesData?.data || []).map(item => mapToArticle(item, channelId || ""));
    const isLoading = isDetailLoading || isArticlesLoading;

    // Handle subscribe action
    const handleSubscribe = async () => {
        if (!channelId || subscribing || subscribeStatus === "subscribed" || subscribeStatus === "pending") return;

        setSubscribing(true);
        try {
            const res: any = await subscribeManagerChannelApi({ channel_id: channelId });
            const root = res?.data ?? res;
            const statusCode = root?.status_code ?? root?.code;
            if (statusCode && statusCode !== 200) {
                const msg =
                    root?.status_message ||
                    root?.message ||
                    "订阅失败，请重试";
                throw new Error(msg);
            }

            if (channelDetail?.visibility === "review") {
                setSubscribeStatus("pending");
                showToast({ message: "已发送订阅申请，审批通过即可订阅。", severity: NotificationSeverity.SUCCESS });
            } else {
                setSubscribeStatus("subscribed");
                showToast({ message: "订阅成功", severity: NotificationSeverity.SUCCESS });
            }
        } catch (e: any) {
            const msg =
                e?.response?.data?.status_message ||
                e?.message ||
                "订阅失败，请重试";
            showToast({ message: msg, severity: NotificationSeverity.ERROR });
        } finally {
            setSubscribing(false);
        }
    };

    // Button config based on visibility and subscribe status
    const getButtonConfig = (detail?: ChannelDetailResponse) => {
        if (subscribeStatus === "subscribed") {
            return { text: "已订阅", disabled: true, variant: "secondary" as const };
        }
        if (subscribeStatus === "pending") {
            return { text: "申请中", disabled: true, variant: "secondary" as const };
        }
        if (detail?.visibility === "review") {
            return { text: "申请订阅", disabled: false, variant: "outline" as const };
        }
        return { text: "订阅", disabled: false, variant: "outline" as const };
    };

    const btnConfig = getButtonConfig(channelDetail);
    // Hide articles when channel requires review and user hasn't subscribed yet
    const hideArticles = channelDetail?.visibility === "review" && subscribeStatus !== "subscribed";

    // Handle error — channel not found or inaccessible (must be in useEffect to avoid side-effects during render)
    useEffect(() => {
        if (isDetailError && open) {
            showToast({ message: "该频道已失效或无法访问", severity: NotificationSeverity.WARNING });
            onOpenChange(false);
            navigate("/channel", { replace: true });
        }
    }, [isDetailError, open]);

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent hideClose side="right" className="w-[1000px] sm:max-w-[1000px] p-0 px-16 flex flex-col">
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
                                    <span className="mr-3">{channelDetail.article_count ?? 0} 篇内容</span>
                                    <span>{channelDetail.subscriber_count ?? 0} 订阅</span>
                                </div>

                                {/* Hide subscribe button for private channels or if the user is the creator */}
                                {channelDetail.visibility !== "private" && (
                                    <Button
                                        variant={btnConfig.variant}
                                        disabled={btnConfig.disabled || subscribing}
                                        onClick={handleSubscribe}
                                        className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${subscribeStatus === "subscribed"
                                            ? "bg-[#f2f3f5] text-[#86909c] border-[#e5e6eb] cursor-default"
                                            : subscribeStatus === "pending"
                                                ? "bg-[#f2f3f5] text-[#c9cdd4] border-[#e5e6eb] cursor-not-allowed"
                                                : "text-[#1d2129] border-[#e5e6eb] hover:bg-gray-50"
                                            }`}
                                    >
                                        {subscribing ? "处理中..." : btnConfig.text}
                                    </Button>
                                )}
                            </div>
                        </SheetHeader>

                        {/* Article List / Pending Message */}
                        <div className="flex-1 overflow-y-auto px-6">
                            {hideArticles ? (
                                <div className="flex flex-col items-center justify-center h-full min-h-[400px]">
                                    <img
                                        className="size-[120px] object-contain mb-4"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/review.png`}
                                        alt="Review Pending"
                                    />
                                    <div className="text-[#1d2129] text-[14px]">
                                        该频道内容需申请通过后方可查看
                                    </div>
                                </div>
                            ) : articles.length > 0 ? (
                                <div>
                                    {articles.map(article => (
                                        <ArticleCard
                                            key={article.id}
                                            article={article}
                                            onSelect={() => { }}
                                            isSelected={false}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <div className="flex items-center justify-center h-64 text-[#86909c] text-sm">
                                    暂无文章
                                </div>
                            )}
                        </div>
                    </>
                ) : null}
            </SheetContent>
        </Sheet>
    );
}
