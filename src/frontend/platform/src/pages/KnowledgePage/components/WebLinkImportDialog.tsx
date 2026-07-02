import { Button } from "@/components/bs-ui/button";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { importKnowledgeWebLinkApi } from "@/controllers/API";
import { useState } from "react";
import { useTranslation } from "react-i18next";

const WEB_LINK_DUPLICATE_ERROR_CODES = new Set([18021, 18023]);

const WEB_LINK_ERROR_KEY_MAP: Record<string, string> = {
    "web link redirect location is missing": "webLinkRequestFailed",
    "web link content type is not supported": "webLinkContentTypeUnsupported",
    "web link content is too large": "webLinkContentTooLarge",
    "web link redirects too many times": "webLinkRedirectsTooMany",
    "web link content is empty": "webLinkContentEmpty",
    "web link url is empty": "webLinkUrlRequired",
    "only http/https web links are supported": "webLinkHttpOnly",
    "web link host is missing": "webLinkInvalid",
    "this web link host is not allowed": "webLinkHostNotAllowed",
    "this web link address is not allowed": "webLinkAddressNotAllowed",
    "web link host cannot be resolved": "webLinkHostUnresolved",
    "target site refused server-side access": "webLinkAccessRefused",
    "target site requires authentication": "webLinkAuthRequired",
    "target site rate limited server-side access": "webLinkRateLimited",
    "media file does not exist": "mediaFileMissing",
    "asr returned empty text": "mediaAsrEmpty",
    "no recognizable audio detected": "mediaNoRecognizableAudio",
    "asr api key is missing": "mediaAsrApiKeyMissing",
    "ffmpeg is not installed": "mediaFfmpegMissing",
    "media audio extraction failed": "mediaAudioExtractionFailed",
};

function normalizeWebLinkTitle(title: string): string | undefined {
    const trimmed = title.trim();
    if (!trimmed) return undefined;
    return /\.html$/i.test(trimmed) ? trimmed : `${trimmed}.html`;
}

interface WebLinkImportDialogProps {
    knowledgeId?: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onImported?: () => void;
}

export default function WebLinkImportDialog({
    knowledgeId,
    open,
    onOpenChange,
    onImported,
}: WebLinkImportDialogProps) {
    const { t } = useTranslation("knowledge");
    const { message } = useToast();
    const [webLinkUrl, setWebLinkUrl] = useState("");
    const [webLinkTitle, setWebLinkTitle] = useState("");
    const [webLinkLoading, setWebLinkLoading] = useState(false);

    const isDuplicateError = (error: any) => WEB_LINK_DUPLICATE_ERROR_CODES.has(Number(error?.status_code));
    const resolveErrorMessage = (error: any, fallbackKey: string, fallbackValue: string) => {
        const statusCode = error?.status_code ?? error?.statusCode;
        const statusMessage = (
            typeof error?.status_message === "string" && error.status_message
                ? error.status_message
                : typeof error?.message === "string"
                    ? error.message
                    : ""
        ).trim();

        const normalizedStatusMessage = statusMessage.toLowerCase();
        const mappedKey = WEB_LINK_ERROR_KEY_MAP[normalizedStatusMessage]
            ?? (normalizedStatusMessage.startsWith("web link request failed")
                ? "webLinkRequestFailed"
                : normalizedStatusMessage.startsWith("knowledge media transcription only supports aliyun/qwen asr")
                    ? "mediaAsrProviderUnsupported"
                    : normalizedStatusMessage.startsWith("asr request failed")
                        ? "mediaAsrRequestFailed"
                        : undefined);
        if (mappedKey) {
            const translated = t(mappedKey, { defaultValue: "" });
            if (translated) return translated;
        }

        if (statusCode !== undefined && statusCode !== null) {
            const translated = t(`bs:errors.${statusCode}`, { ...(error?.data || {}), defaultValue: "" });
            if (translated) return translated;
        }

        return t(fallbackKey, { defaultValue: fallbackValue });
    };

    const importWebLink = async (normalizedUrl: string, overwrite = false) => {
        const normalizedTitle = normalizeWebLinkTitle(webLinkTitle);
        await importKnowledgeWebLinkApi(knowledgeId!, {
            url: normalizedUrl,
            title: normalizedTitle,
            ...(overwrite ? { overwrite: true } : {}),
        });
        message({
            variant: "success",
            description: t("webLinkImportStarted", { defaultValue: "网页链接已开始导入" }),
        });
        setWebLinkUrl("");
        setWebLinkTitle("");
        onOpenChange(false);
        onImported?.();
    };

    const handleImportWebLink = async () => {
        const normalizedUrl = webLinkUrl.trim();
        if (!knowledgeId) {
            message({
                variant: "warning",
                description: t("knowledgeIdMissing", { defaultValue: "知识库不存在" }),
            });
            return;
        }
        if (!normalizedUrl) {
            message({
                variant: "warning",
                description: t("webLinkUrlRequired", { defaultValue: "请输入网页链接" }),
            });
            return;
        }
        try {
            const parsed = new URL(normalizedUrl);
            if (!["http:", "https:"].includes(parsed.protocol)) {
                message({
                    variant: "warning",
                    description: t("webLinkHttpOnly", { defaultValue: "仅支持 http 或 https 链接" }),
                });
                return;
            }
        } catch (error) {
            message({
                variant: "warning",
                description: t("webLinkInvalid", { defaultValue: "请输入有效的网页链接" }),
            });
            return;
        }

        setWebLinkLoading(true);
        try {
            await importWebLink(normalizedUrl);
        } catch (error: any) {
            if (isDuplicateError(error)) {
                bsConfirm({
                    title: t("duplicateWebLinkTitle", { defaultValue: "发现重复网页链接" }),
                    desc: normalizeWebLinkTitle(webLinkTitle) || normalizedUrl,
                    canelTxt: t("cancel", { defaultValue: "取消" }),
                    okTxt: t("overwrite", { defaultValue: "覆盖" }),
                    onCancel: () => {
                        setWebLinkUrl("");
                        setWebLinkTitle("");
                        onOpenChange(false);
                    },
                    onOk: async (close) => {
                        close();
                        onOpenChange(false);
                        try {
                            await importWebLink(normalizedUrl, true);
                        } catch (overwriteError: any) {
                            message({
                                variant: "error",
                                description: resolveErrorMessage(
                                    overwriteError,
                                    "webLinkOverwriteFailed",
                                    "网页链接覆盖失败",
                                ),
                            });
                        }
                    },
                });
                return;
            }
            message({
                variant: "error",
                description: resolveErrorMessage(error, "webLinkImportFailed", "网页链接导入失败"),
            });
        } finally {
            setWebLinkLoading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(nextOpen) => !webLinkLoading && onOpenChange(nextOpen)}>
            <DialogContent className="max-w-[520px]">
                <DialogHeader>
                    <DialogTitle>{t("webLink", { defaultValue: "网页链接" })}</DialogTitle>
                </DialogHeader>
                <form
                    className="space-y-4"
                    onSubmit={(event) => {
                        event.preventDefault();
                        if (webLinkLoading) return;
                        void handleImportWebLink();
                    }}
                >
                    <label className="block space-y-2 text-sm text-[#1d2129]">
                        <span className="font-medium">{t("webLinkUrl", { defaultValue: "链接地址" })}</span>
                        <Input
                            value={webLinkUrl}
                            onChange={(event) => setWebLinkUrl(event.currentTarget.value)}
                            placeholder="https://example.com/page"
                            disabled={webLinkLoading}
                        />
                    </label>
                    <label className="block space-y-2 text-sm text-[#1d2129]">
                        <span className="font-medium">{t("webLinkTitle", { defaultValue: "显示名称" })}</span>
                        <Input
                            value={webLinkTitle}
                            onChange={(event) => setWebLinkTitle(event.currentTarget.value)}
                            placeholder={t("webLinkTitlePlaceholder", {
                                defaultValue: "留空则自动读取网页标题",
                            })}
                            disabled={webLinkLoading}
                        />
                    </label>
                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={webLinkLoading}>
                            {t("cancel", { defaultValue: "取消" })}
                        </Button>
                        <Button type="submit" disabled={webLinkLoading}>
                            {webLinkLoading
                                ? t("importing", { defaultValue: "导入中..." })
                                : t("import", { defaultValue: "导入" })}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
