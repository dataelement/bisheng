import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
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
import { addWebsiteSourceApi, crawlTempSourceApi, getFeedbackTips } from "~/api/channels";
import type { InformationSource } from "~/api/channels";
import { ChannelBookIcon, ChannelLoadingIcon, ChannelRightSmallUpIcon } from "~/components/icons/channels";
import { cn } from "~/utils";
import { extractApiStatusCode } from "../errorUtils";
import { crawlErrorMessageKey } from "./crawlErrorUtils";

interface CrawlPreviewDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    url: string;
    onAddSource: (source: InformationSource) => void;
    onCancel?: () => void;
}

type CrawlStatus = "loading" | "success" | "error";

export function CrawlPreviewDialog({
    open,
    onOpenChange,
    url,
    onAddSource,
    onCancel
}: CrawlPreviewDialogProps) {
    const localize = useLocalize();
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
        if (!open || !url) return;
        setStatus("loading");
        setPreviewData(null);
        setErrorCode(null);
        const currentId = ++requestIdRef.current;
        (async () => {
            try {
                const res = await crawlTempSourceApi({ url });
                const root: any = res as any;

                const codeRaw = root?.status_code ?? root?.code;
                if (codeRaw && codeRaw !== 200) {
                    if (requestIdRef.current !== currentId) return;
                    const code = Number(codeRaw);
                    setStatus("error");
                    // 19005/13005：单篇或非列表页；19004/13004：权限；19003/13003：解析失败；其它非 200 同 19003
                    if ([19006, 19005, 19004, 19003].includes(code)) {
                        setErrorCode(code);
                    } else {
                        setErrorCode(19003);
                    }
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
                    setStatus("error");
                    setErrorCode(19005);
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
            } catch (error) {
                if (requestIdRef.current !== currentId) return;
                setStatus("error");
                const code = extractApiStatusCode(error);
                setErrorCode(code === 19006 ? 19006 : 19003);
            }
        })();
    }, [open, url]);

    // 加载订阅配置中的 feedback_tips
    useEffect(() => {
        if (!open) return;
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
    }, [open]);

    const handleCancel = () => {
        // 标记当前请求为失效，后续响应不再更新 UI
        requestIdRef.current++;
        onCancel?.();
        onOpenChange(false);
    };

    const handleAddSource = () => {
        (async () => {
            let shouldClose = false;
            try {
                setAdding(true);
                let created: InformationSource | null = null;
                try {
                    const res = await addWebsiteSourceApi({ url });
                    const code = extractApiStatusCode(res);
                    if (code && code !== 200) {
                        return;
                    }
                    const raw: any = (res as any)?.data ?? res ?? {};
                    created = {
                        id: String(raw.id ?? raw.source_id ?? `web-${Date.now()}`),
                        name: String(raw.name ?? raw.title ?? previewData?.name ?? url),
                        type: "website",
                        url: raw.url ?? url,
                        avatar: raw.icon ?? raw.avatar ?? previewData?.icon
                    };
                } catch (error) {
                    const code = extractApiStatusCode(error);
                    if (code != null) {
                        return;
                    }
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
                    shouldClose = true;
                }
            } finally {
                setAdding(false);
                if (shouldClose) {
                    onOpenChange(false);
                }
            }
        })();
    };

    const handleArticlesScroll = () => {
        setIsArticlesScrolling(true);
        if (articlesScrollTimerRef.current) clearTimeout(articlesScrollTimerRef.current);
        articlesScrollTimerRef.current = setTimeout(() => setIsArticlesScrolling(false), 500);
    };

    return (
        <Dialog modal open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="w-[600px] h-[600px] max-w-[600px] flex flex-col bg-white text-[14px] [&>button]:hidden z-[100]"
                overlayClassName="z-[100]"
                onPointerDownOutside={(e) => e.preventDefault()}
                onInteractOutside={(e) => e.preventDefault()}
            >
                <DialogHeader>
                    <DialogTitle className="text-[16px] font-medium">
                        {localize("com_subscription.confirm_crawled_content")}
                    </DialogTitle>
                </DialogHeader>

                <div className="flex flex-col gap-4 flex-1 min-h-0">
                    <div>
                        <Input
                            value={url}
                            readOnly
                            disabled
                            className="h-8 text-[14px] bg-[#F7F8FA] text-[#86909C] border-[#E5E6EB]"
                        />
                    </div>

                    {status === "loading" && (
                        <div className="flex-1 flex flex-col items-center justify-center py-12 gap-4">
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
                                                    className="group/item flex min-w-0 items-center truncate text-[13px] text-[#165DFF] hover:text-[#335CFF]"
                                                >
                                                    <span className="mr-2 h-[6px] w-[6px] flex-shrink-0 rounded-full bg-[#C9CDD4]" aria-hidden />
                                                    <span className="min-w-0 truncate underline-offset-2 group-hover/item:underline">
                                                        {a.title}
                                                    </span>
                                                    <ChannelRightSmallUpIcon className="ml-1 h-4 w-4 flex-shrink-0 text-inherit opacity-0 transition-opacity group-hover/item:opacity-100" />
                                                </a>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>
                    )}

                    {status === "error" && (
                        <div className="flex-1 rounded border border-[#E5E6EB] min-h-[270px] px-6 py-8 flex flex-col justify-between">
                            <div className="flex-1 flex flex-col items-center justify-center text-center">
                                <ChannelBookIcon className="w-[100px] h-[100px] mb-5" />
                                <p className="text-[14px] text-[#4E5969] leading-6">
                                    {localize(crawlErrorMessageKey(errorCode))}
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                {/* 底部操作：爬取中也展示两按钮，添加到信源置灰 */}
                {(status === "loading" || status === "success" || status === "error") && (
                    <div className="mt-auto flex shrink-0 items-center justify-between gap-3 pt-4">
                        {(status === "success" || status === "error") ? (
                            <button
                                type="button"
                                className="text-[14px] text-[#999999] transition-colors hover:text-[#165DFF]"
                                onClick={() => setFeedbackDialogOpen(true)}
                            >{localize("com_subscription.unsatisfied_with_crawl_submit_request")}</button>
                        ) : (
                            <span />
                        )}
                        <div className="flex">
                            <Button
                                variant="secondary"
                                onClick={handleCancel}
                                className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none text-[14px] !font-normal border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA]"
                            >
                                {localize("cancel")}
                            </Button>
                            {(status === "loading" || status === "success") && (
                                <Button
                                    onClick={handleAddSource}
                                    disabled={status !== "success" || adding}
                                    className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none text-[14px] !font-normal bg-[#165DFF] ml-2 hover:bg-[#4080FF] border border-[#165DFF] text-white disabled:opacity-50 gap-2"
                                >
                                    {adding && <Loader2 className="size-4 animate-spin" />}
                                    {localize("com_subscription.add_source")}
                                </Button>
                            )}
                        </div>

                    </div>
                )}
            </DialogContent>

            {/* 人工爬取需求提示弹窗 */}
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
        </Dialog>
    );
}
