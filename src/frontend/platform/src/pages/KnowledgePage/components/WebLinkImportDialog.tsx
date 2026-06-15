import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { importKnowledgeWebLinkApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useState } from "react";
import { useTranslation } from "react-i18next";

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
        const res = await captureAndAlertRequestErrorHoc(
            importKnowledgeWebLinkApi(knowledgeId, {
                url: normalizedUrl,
                title: webLinkTitle.trim() || undefined,
            })
        );
        setWebLinkLoading(false);
        if (!res) return;

        message({
            variant: "success",
            description: t("webLinkImportStarted", { defaultValue: "网页链接已开始导入" }),
        });
        setWebLinkUrl("");
        setWebLinkTitle("");
        onOpenChange(false);
        onImported?.();
    };

    return (
        <Dialog open={open} onOpenChange={(nextOpen) => !webLinkLoading && onOpenChange(nextOpen)}>
            <DialogContent className="max-w-[520px]">
                <DialogHeader>
                    <DialogTitle>{t("webLink", { defaultValue: "网页链接" })}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4">
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
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={webLinkLoading}>
                        {t("cancel", { defaultValue: "取消" })}
                    </Button>
                    <Button onClick={handleImportWebLink} disabled={webLinkLoading}>
                        {webLinkLoading
                            ? t("importing", { defaultValue: "导入中..." })
                            : t("import", { defaultValue: "导入" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
