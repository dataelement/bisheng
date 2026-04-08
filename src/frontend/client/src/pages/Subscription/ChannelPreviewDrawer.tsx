import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChannelPreview } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/avatar";
import { Button } from "~/components/ui/Button";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { getMockChannelPreview } from "~/mock/channels";
import { useToastContext } from "~/Providers";
import { ArticleCard } from "./ArticleList/ArticleCard";

const MAX_SUBSCRIPTIONS = 20;
// Mock: simulate current user subscription count
const MOCK_CURRENT_SUBSCRIPTION_COUNT = 5;

interface ChannelPreviewDrawerProps {
    channelId: string | undefined;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function ChannelPreviewDrawer({ channelId, open, onOpenChange }: ChannelPreviewDrawerProps) {
    const navigate = useNavigate();
    const { showToast } = useToastContext();
    const [preview, setPreview] = useState<ChannelPreview | null>(null);
    const [loading, setLoading] = useState(true);
    const [subscribeStatus, setSubscribeStatus] = useState<
        "none" | "subscribed" | "pending" | "needsApproval"
    >("none");

    useEffect(() => {
        if (!channelId || !open) return;
        setLoading(true);
        setPreview(null);
        // Simulate API call
        setTimeout(() => {
            const data = getMockChannelPreview(channelId);
            if (data.isDeleted) {
                showToast({ message: "该频道已失效或被删除", severity: NotificationSeverity.WARNING });
                onOpenChange(false);
                navigate("/channel", { replace: true });
                return;
            }
            setPreview(data);
            if (data.isSubscribed) {
                setSubscribeStatus("subscribed");
            } else if (data.isPending) {
                setSubscribeStatus("pending");
            } else if (data.needsApproval) {
                setSubscribeStatus("needsApproval");
            } else {
                setSubscribeStatus("none");
            }
            setLoading(false);
        }, 300);
    }, [channelId, open]);

    const handleSubscribe = () => {
        if (subscribeStatus === "subscribed" || subscribeStatus === "pending") return;

        if (MOCK_CURRENT_SUBSCRIPTION_COUNT >= MAX_SUBSCRIPTIONS) {
            showToast({ message: `您已达到订阅频道的上限${MAX_SUBSCRIPTIONS}`, severity: NotificationSeverity.WARNING });
            return;
        }

        if (subscribeStatus === "needsApproval") {
            setSubscribeStatus("pending");
            showToast({ message: "已发送订阅申请，审批通过即可订阅。", severity: NotificationSeverity.SUCCESS });
        } else {
            setSubscribeStatus("subscribed");
            showToast({ message: "订阅成功", severity: NotificationSeverity.SUCCESS });
        }
    };

    const getButtonConfig = () => {
        switch (subscribeStatus) {
            case "subscribed":
                return { text: "已订阅", disabled: true, variant: "secondary" as const };
            case "pending":
                return { text: "申请中", disabled: true, variant: "secondary" as const };
            case "needsApproval":
                return { text: "申请订阅", disabled: false, variant: "outline" as const };
            default:
                return { text: "订阅", disabled: false, variant: "outline" as const };
        }
    };

    const hideArticles = preview?.isPending || subscribeStatus === "pending";
    const btnConfig = getButtonConfig();

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent hideClose side="right" className="w-[1000px] sm:max-w-[1000px] p-0 px-16 flex flex-col">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-[#86909c] text-sm">
                        加载中...
                    </div>
                ) : preview ? (
                    <>
                        {/* Channel Info Header */}
                        <SheetHeader className="px-6 pt-6 pb-4 gap-0 border-b border-gray-100 text-left">
                            {/* Channel Name */}
                            <SheetTitle className="font-semibold text-[#1d2129] leading-tight mb-1">
                                {preview.name}
                            </SheetTitle>

                            {/* Description (2-line clamp + tooltip) */}
                            {preview.description && (
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <p className="text-sm text-[#86909c] leading-relaxed line-clamp-2 cursor-default mb-4 text-left">
                                            {preview.description}
                                        </p>
                                    </TooltipTrigger>
                                    <TooltipContent
                                        className="shadow-lg py-2 max-w-md text-sm"
                                    >
                                        {preview.description}
                                    </TooltipContent>
                                </Tooltip>
                            )}

                            {/* Creator Info */}
                            <div className="flex items-center gap-0.5 mb-3">
                                <Avatar className="w-5 h-5">
                                    <AvatarImage src={preview.creatorAvatar} alt={preview.creator} />
                                    <span>preview.creator</span>
                                </Avatar>
                                <span className="text-sm text-[#86909c]">{preview.creator}</span>
                            </div>

                            {/* Data Overview Row & Button */}
                            <div className="flex items-center justify-between">
                                <div className="flex items-center text-sm text-[#86909c]">
                                    {/* Source Icons Stacked */}
                                    {preview.sources.length > 0 && (
                                        <div className="flex items-center mr-3">
                                            <div className="flex -space-x-1.5">
                                                {preview.sources.slice(0, 4).map((source, index) => (
                                                    <div
                                                        key={source.id}
                                                        className="size-5 rounded-[4px] border border-white overflow-hidden bg-gray-100"
                                                        style={{ zIndex: 4 - index }}
                                                    >
                                                        <img
                                                            src={source.avatar || "/default-source.png"}
                                                            alt={source.name}
                                                            className="w-full h-full object-cover"
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    <span className="mr-3">{preview.articleCount} 篇内容</span>
                                    <span>{preview.subscriberCount} 订阅</span>
                                </div>
                                <Button
                                    variant={btnConfig.variant}
                                    disabled={btnConfig.disabled}
                                    onClick={handleSubscribe}
                                    className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${subscribeStatus === "subscribed"
                                        ? "bg-[#f2f3f5] text-[#86909c] border-[#e5e6eb] cursor-default"
                                        : subscribeStatus === "pending"
                                            ? "bg-[#f2f3f5] text-[#c9cdd4] border-[#e5e6eb] cursor-not-allowed"
                                            : "text-[#1d2129] border-[#e5e6eb] hover:bg-gray-50"
                                        }`}
                                >
                                    {btnConfig.text}
                                </Button>
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
                            ) : preview.articles.length > 0 ? (
                                <div>
                                    {preview.articles.map(article => (
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
