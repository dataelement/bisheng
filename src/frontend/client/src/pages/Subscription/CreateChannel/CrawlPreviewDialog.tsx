import { ChevronLeft, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "~/components/ui/AlertDialog";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { useLocalize } from "~/hooks";
import useMediaQuery from "~/hooks/useMediaQuery";
import { addWebsiteSourceApi, crawlTempSourceApi, getFeedbackTips } from "~/api/channels";
import type { InformationSource } from "~/api/channels";
import { ChannelBookIcon, ChannelLoadingIcon, ChannelRightSmallUpIcon } from "~/components/icons/channels";
import { cn } from "~/utils";

export interface CrawlPreviewPanelProps {
    url: string;
    /** 返回 / 取消：回到「创建频道」表单侧（含添加信息源面板） */
    onBack: () => void;
    onAddSource: (source: InformationSource) => void;
}

type CrawlStatus = "loading" | "success" | "error" | "singlePageWarning";

/** 创建频道抽屉内下钻：爬取内容确认（不再叠加独立 Dialog） */
export function CrawlPreviewPanel({ url, onBack, onAddSource }: CrawlPreviewPanelProps) {
    const localize = useLocalize();
    const noHoverDevice = useMediaQuery("(hover: none)");
    const [status, setStatus] = useState<CrawlStatus>("loading");
    const [adding, setAdding] = useState(false);
    const [previewData, setPreviewData] = useState<{ name: string; icon?: string; articles?: { title: string; url: string }[] } | null>(null);
    const [errorCode, setErrorCode] = useState<number | null>(null);
    const [feedbackTips, setFeedbackTips] = useState<string>(localize("com_subscription.send_crawl_requirement_to_email"));
    const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
    const [isArticlesScrolling, setIsArticlesScrolling] = useState(false);
    const articlesScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const requestIdRef = useRef(0);

    useEffect(() => {
        if (!url) return;
        setStatus("loading");
        setPreviewData(null);
        setErrorCode(null);
        const currentId = ++requestIdRef.current;
        (async () => {
            try {
                const res = await crawlTempSourceApi({ url });
                const root: any = res as any;

                const code = root?.status_code ?? root?.code;
                if (code && code !== 200) {
                    if (requestIdRef.current !== currentId) return;
                    // 13005：检测为单篇文章或非列表页
                    if (code === 13005) {
                        setStatus("singlePageWarning");
                        setErrorCode(code);
                        return;
                    }
                    // 13004：权限问题，无法爬取
                    if (code === 13004) {
                        setStatus("error");
                        setErrorCode(code);
                        return;
                    }
                    // 13003 及其它：解析失败
                    setStatus("error");
                    setErrorCode(code);
                    return;
                }

                const raw: any = root.data ?? root ?? {};

                // 是否判断为单篇文章/非列表页，由后端字段或回退到 URL 规则
                const lowerUrl = url.toLowerCase();
                const likelySinglePage =
                    raw.single_page === true ||
                    (!/(list|index|column|columns|catalog|category|news)/.test(lowerUrl) &&
                        /(article|detail|content|zhengce|policy|post)/.test(lowerUrl));

                if (likelySinglePage) {
                    if (requestIdRef.current !== currentId) return;
                    setStatus("singlePageWarning");
                    return;
                }

                let name = raw.name as string | undefined;
                if (!name) {
                    try {
                        name = new URL(url).hostname.replace(/^www\./, "");
                    } catch {
                        name = url.replace(/^https?:\/\//, "").split("/")[0] || url;
                    }
                }

                const articles: { title: string; url: string }[] =
                    ((raw.article_links as any[] | undefined) ?? [])
                        .slice(0, 20)
                        .map((item) => ({
                            title: String(item.title ?? ""),
                            url: String(item.url ?? url)
                        }));

                if (requestIdRef.current !== currentId) return;
                setPreviewData({
                    name: name || url,
                    icon: raw.icon,
                    articles
                });
                setStatus("success");
            } catch {
                if (requestIdRef.current !== currentId) return;
                setStatus("error");
            }
        })();
    }, [url]);

    // 加载订阅配置中的 feedback_tips
    useEffect(() => {
        (async () => {
            try {
                const resp = await getFeedbackTips();
                const data = resp?.data ?? resp ?? {};
                const tips = data.feedback_tips ?? data.feedbackTips;
                if (typeof tips === "string" && tips.trim()) {
                    setFeedbackTips(tips);
                }
            } catch {
            }
        })();
    }, []);

    const handleCancel = () => {
        requestIdRef.current++;
        onBack();
    };

    const handleAddSource = () => {
        (async () => {
            try {
                setAdding(true);
                let created: InformationSource | null = null;
                try {
                    const res = await addWebsiteSourceApi({ url });
                    const raw: any = (res as any)?.data ?? res ?? {};
                    created = {
                        id: String(raw.id ?? raw.source_id ?? `web-${Date.now()}`),
                        name: String(raw.name ?? raw.title ?? previewData?.name ?? url),
                        type: "website",
                        url: raw.url ?? url,
                        avatar: raw.icon ?? raw.avatar ?? previewData?.icon
                    };
                } catch {
                    // 如果后端报错，就退回到本地添加，避免用户操作“失效”
                    if (previewData) {
                        created = {
                            id: `crawl-${Date.now()}`,
                            name: previewData.name,
                            type: "website",
                            url
                        };
                    }
                }
                if (created) {
                    onAddSource(created);
                } else {
                    onBack();
                }
            } finally {
                setAdding(false);
            }
        })();
    };

    const handleArticlesScroll = () => {
        setIsArticlesScrolling(true);
        if (articlesScrollTimerRef.current) clearTimeout(articlesScrollTimerRef.current);
        articlesScrollTimerRef.current = setTimeout(() => setIsArticlesScrolling(false), 500);
    };

    return (
        <>
            <div className="flex h-full min-h-0 flex-1 flex-col bg-white text-[14px]">
                <div className="flex shrink-0 flex-row items-center gap-2 border-b border-[#ECECEC] px-4 pb-4 pt-4 sm:px-6">
                    <button
                        type="button"
                        onClick={handleCancel}
                        className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-[#E5E6EB] text-[#4E5969] hover:bg-[#F7F8FA]"
                        aria-label={localize("com_ui_go_back")}
                    >
                        <ChevronLeft className="size-5" />
                    </button>
                    <h2 className="min-w-0 flex-1 text-left text-[20px] font-medium leading-7 text-[#212121]">
                        {localize("com_subscription.confirm_crawled_content")}
                    </h2>
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4 sm:px-6">
                    <div>
                        <Input
                            value={url}
                            readOnly
                            disabled
                            className="h-8 text-[14px] bg-[#F7F8FA] text-[#86909C] border-[#E5E6EB]"
                        />
                    </div>

                    {status === "loading" && (
                        <div className="flex flex-1 flex-col items-center justify-center gap-4 py-12">
                            <ChannelLoadingIcon className="w-[120px] h-[120px]" />
                            <p className="text-[14px] text-[#4E5969]">
                                {localize("com_subscription.crawling_waiting") || localize("com_subscription.crawling_please_wait")}
                            </p>
                        </div>
                    )}

                    {status === "success" && previewData && (
                        <div
                            className={cn(
                                "flex min-w-0 flex-col",
                                previewData.articles?.length ? "min-h-0 flex-1" : "shrink-0"
                            )}
                        >
                            <div
                                className={cn(
                                    "flex min-w-0 flex-col overflow-hidden rounded-lg border border-[#E5E6EB] p-3",
                                    previewData.articles?.length ? "min-h-0 flex-1" : "shrink-0"
                                )}
                            >
                                <div className="flex shrink-0 items-center gap-3">
                                    <Avatar className="h-10 w-10 border border-[#E5E6EB]">
                                        {previewData.icon ? (
                                            <AvatarImage src={previewData.icon} alt={previewData.name} />
                                        ) : (
                                            <AvatarName name={previewData.name} className="text-xs" />
                                        )}
                                    </Avatar>
                                    <div className="min-w-0">
                                        <p className="text-[14px] font-medium text-[#1D2129]">
                                            {previewData.name}
                                        </p>
                                        <a
                                            href={url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="break-all text-[12px] text-[#165DFF] hover:underline"
                                        >
                                            {url}
                                        </a>
                                    </div>
                                </div>
                                {previewData.articles && previewData.articles.length > 0 && (
                                    <>
                                        <p className="mb-2 mt-4 shrink-0 text-[14px] font-medium text-[#212121]">
                                            {localize("com_subscription.parsed_articles")}
                                        </p>
                                        <div
                                            className="min-h-0 flex-1 space-y-2 overflow-y-auto scroll-on-scroll pr-0.5"
                                            onScroll={handleArticlesScroll}
                                            data-scrolling={isArticlesScrolling ? "true" : "false"}
                                        >
                                            {previewData.articles.map((a, i) => (
                                                <a
                                                    key={i}
                                                    href={a.url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className={cn(
                                                        "flex min-w-0 items-center gap-1 text-[13px] text-[#165DFF]",
                                                        noHoverDevice ? "" : "group/item hover:text-[#335CFF]"
                                                    )}
                                                >
                                                    <span
                                                        className={cn(
                                                            "mr-2 h-[6px] w-[6px] flex-shrink-0 rounded-full",
                                                            noHoverDevice ? "bg-[#165DFF]" : "bg-[#C9CDD4] group-hover/item:bg-[#165DFF]"
                                                        )}
                                                        aria-hidden
                                                    />
                                                    <span
                                                        className={cn(
                                                            "min-w-0 flex-1 truncate underline-offset-2",
                                                            noHoverDevice ? "underline" : "group-hover/item:underline"
                                                        )}
                                                    >
                                                        {a.title}
                                                    </span>
                                                    <ChannelRightSmallUpIcon
                                                        className={cn(
                                                            "h-4 w-4 flex-shrink-0 text-inherit transition-opacity",
                                                            noHoverDevice ? "opacity-100" : "opacity-0 group-hover/item:opacity-100"
                                                        )}
                                                    />
                                                </a>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>
                    )}

                    {(status === "error" || status === "singlePageWarning") && (
                        <div className="flex min-h-[270px] flex-1 flex-col justify-between rounded border border-[#E5E6EB] px-6 py-8">
                            <div className="flex flex-1 flex-col items-center justify-center text-center">
                                <ChannelBookIcon className="mb-5 w-[100px] h-[100px]" />
                                <p className="text-[14px] leading-6 text-[#4E5969]">
                                    {status === "singlePageWarning"
                                        ? <>{localize("com_subscription.detected_as")}<span className="font-medium text-[#1D2129]">{localize("com_subscription.single_article_or_non_list_page")}</span>{localize("com_subscription.please_enter_valid_list_page_url")}</>
                                        : errorCode === 13004
                                            ? localize("com_subscription.crawl_failed_due_to_permissions")
                                            : localize("com_subscription.parse_failed_retry_or_submit")}
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                {(status === "loading" || status === "success" || status === "error" || status === "singlePageWarning") && (
                    <div className="mt-auto flex shrink-0 flex-col gap-3 border-t border-[#E5E6EB] px-4 py-4 sm:px-6">
                        {(status === "success" || status === "error" || status === "singlePageWarning") ? (
                            <button
                                type="button"
                                className="inline-flex flex-wrap items-baseline gap-x-1 text-left text-[14px] leading-relaxed"
                                onClick={() => setFeedbackDialogOpen(true)}
                            >
                                <span className="text-[#4E5969]">
                                    {localize("com_subscription.unsatisfied_with_crawl_prompt")}
                                </span>
                                <span className="font-normal text-[#165DFF]">
                                    {localize("com_subscription.submit_manual_crawl_request")}
                                </span>
                            </button>
                        ) : (
                            <span />
                        )}
                        <div className="flex justify-end gap-2">
                            <Button
                                variant="secondary"
                                onClick={handleCancel}
                                className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none text-[14px] !font-normal border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] touch-mobile:flex-1"
                            >
                                {localize("cancel")}
                            </Button>
                            {(status === "loading" || status === "success") && (
                                <Button
                                    onClick={handleAddSource}
                                    disabled={status !== "success" || adding}
                                    className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none text-[14px] !font-normal bg-[#165DFF] hover:bg-[#4080FF] border border-[#165DFF] text-white disabled:opacity-50 gap-2 touch-mobile:flex-1"
                                >
                                    {adding && <Loader2 className="size-4 animate-spin" />}
                                    {localize("com_subscription.add_source")}
                                </Button>
                            )}
                        </div>
                    </div>
                )}
            </div>

            <AlertDialog open={feedbackDialogOpen} onOpenChange={setFeedbackDialogOpen}>
                <AlertDialogContent className="sm:max-w-[480px]">
                    <AlertDialogHeader>
                        <AlertDialogTitle>{localize("com_subscription.submit_manual_crawl_request")}</AlertDialogTitle>
                        <AlertDialogDescription className="whitespace-pre-line text-[14px] leading-6 text-[#4E5969]">
                            {feedbackTips}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogAction className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none bg-[#165DFF] hover:bg-[#4080FF]">{localize("com_subscription.ok")}</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}
