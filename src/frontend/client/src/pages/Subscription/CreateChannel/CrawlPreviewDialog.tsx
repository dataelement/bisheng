import { FileText, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { useLocalize } from "~/hooks";
import { addWebsiteSourceApi, crawlTempSourceApi } from "~/api/channels";
import type { InformationSource } from "~/api/channels";

interface CrawlPreviewDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    url: string;
    onAddSource: (source: InformationSource) => void;
}

type CrawlStatus = "loading" | "success" | "error" | "singlePageWarning";

export function CrawlPreviewDialog({
    open,
    onOpenChange,
    url,
    onAddSource
}: CrawlPreviewDialogProps) {
    const [status, setStatus] = useState<CrawlStatus>("loading");
    const [adding, setAdding] = useState(false);
    const [previewData, setPreviewData] = useState<{ name: string; articles?: { title: string; url: string }[] } | null>(null);
    const localize = useLocalize();

    useEffect(() => {
        if (!open || !url) return;
        setStatus("loading");
        setPreviewData(null);
        (async () => {
            try {
                const res = await crawlTempSourceApi({ url });
                const root: any = res as any;
                const raw: any = root.data ?? root ?? {};

                // 是否判断为单篇文章/非列表页，由后端字段或回退到 URL 规则
                const lowerUrl = url.toLowerCase();
                const likelySinglePage =
                    raw.single_page === true ||
                    (!/(list|index|column|columns|catalog|category|news)/.test(lowerUrl) &&
                        /(article|detail|content|zhengce|policy|post)/.test(lowerUrl));

                if (likelySinglePage) {
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
                    (raw.article_links as any[] | undefined)?.map((item) => ({
                        title: String(item.title ?? ""),
                        url: String(item.url ?? url)
                    })) ?? [];

                setPreviewData({
                    name: name || url,
                    articles
                });
                setStatus("success");
            } catch {
                setStatus("error");
            }
        })();
    }, [open, url]);

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
                        avatar: raw.avatar
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
                }
            } finally {
                setAdding(false);
                onOpenChange(false);
            }
        })();
    };

    if (!open) return null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="w-[600px] max-w-[600px] flex flex-col bg-white text-[14px]">
                <DialogHeader>
                    <DialogTitle className="text-[16px] font-medium">
                        {localize("confirm_crawled_content")}
                    </DialogTitle>
                </DialogHeader>

                <div className="flex flex-col gap-4">
                    <div>
                        <Input
                            value={url}
                            readOnly
                            disabled
                            className="h-10 text-[14px] bg-[#F7F8FA] text-[#86909C] border-[#E5E6EB]"
                        />
                    </div>

                    {status === "loading" && (
                        <div className="flex flex-col items-center justify-center py-12 gap-4">
                            <img
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/loading.svg`}
                                alt=""
                                className="w-[100px] h-[100px]"
                            />
                            <p className="text-[14px] text-[#4E5969]">
                                {localize("crawling_waiting") || "爬取中,可能需要1-2分钟,请耐心等待..."}
                            </p>
                        </div>
                    )}

                    {status === "success" && previewData && (
                        <div className="space-y-4">
                            <div className="flex items-center gap-3 p-3 rounded-lg bg-[#F7F8FA]">
                                <div className="w-10 h-10 rounded-full bg-[#E5E6EB] flex items-center justify-center text-[14px] text-[#86909C]">
                                    {previewData.name[0]}
                                </div>
                                <div>
                                    <p className="text-[14px] font-medium text-[#1D2129]">
                                        {previewData.name}
                                    </p>
                                    <a
                                        href={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-[12px] text-[#165DFF] hover:underline"
                                    >
                                        {url}
                                    </a>
                                </div>
                            </div>
                            {previewData.articles && previewData.articles.length > 0 && (
                                <div>
                                    <p className="text-[12px] text-[#86909C] mb-2">
                                        {localize("parsed_articles")}
                                    </p>
                                    <div className="max-h-[200px] overflow-y-auto space-y-2">
                                        {previewData.articles.map((a, i) => (
                                            <a
                                                key={i}
                                                href={a.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="block text-[13px] text-[#165DFF] hover:underline truncate"
                                            >
                                                {a.title}
                                            </a>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {status === "error" && (
                        <div className="py-8 text-center text-[14px] text-[#86909C]">
                            {localize("crawl_permission_denied") ||
                                '该网站因权限设置无法爬取，请输入符合条件的目标网站的"栏目列表页"网址'}
                        </div>
                    )}
                    {status === "singlePageWarning" && (
                        <div className="rounded border border-[#E5E6EB] bg-[#F7F8FA] min-h-[270px] px-6 py-8 flex flex-col justify-between">
                            <div className="flex-1 flex flex-col items-center justify-center text-center">
                                <img
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/book.svg`}
                                    alt=""
                                    className="w-[100px] h-[100px] mb-5"
                                />
                                <p className="text-[14px] text-[#4E5969] leading-6">
                                    {localize("detected_as")}
                                    <span className="font-medium text-[#1D2129]">
                                        {localize("article_or_page")}
                                    </span>
                                    ，{localize("column_list")}
                                    <br />
                                    （如：新闻动态、政策法规等列表页面）
                                </p>
                            </div>
                            <div className="mt-6 flex items-center justify-between">
                                <span className="text-[12px] text-[#86909C]">
                                    {localize("submit_manual_crawl") || "不满意爬取内容？提交人工爬取需求"}
                                </span>
                                <Button
                                    variant="secondary"
                                    onClick={() => onOpenChange(false)}
                                    className="h-8 px-4 border border-[#E5E6EB] bg-white text-[#4E5969]"
                                >
                                    {localize("cancel")}
                                </Button>
                            </div>
                        </div>
                    )}
                </div>

                {status !== "singlePageWarning" && (
                    <div className="flex justify-end gap-3 pt-4 border-t border-[#E5E6EB]">
                        <Button
                            variant="secondary"
                            onClick={() => onOpenChange(false)}
                            className="bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none text-[#4E5969]"
                        >
                            {localize("cancel")}
                        </Button>
                        <Button
                            onClick={handleAddSource}
                            disabled={status !== "success" || adding}
                            className="bg-[#165DFF] hover:bg-[#4080FF] text-white disabled:opacity-50 flex items-center gap-2"
                        >
                            {adding && <Loader2 className="size-4 animate-spin" />}
                            {localize("add_source")}
                        </Button>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}
