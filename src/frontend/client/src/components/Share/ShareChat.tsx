import { useEffect, useState } from "react";
import { useToastContext } from "~/Providers";
import { getShareLinkApi } from "~/api";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Input } from "../ui";
import { ShareOutlineIcon } from "../icons/ShareOutlineIcon";

interface ShareDialogProps {
    type: 'linsight_session' | 'workbench_chat' | 'workflow' | 'skill' | 'assistant'
    chatId: string
    flowId?: string
    versionId?: string
    /** 与灵思头部「任务描述」等操作一致：描边 + 图标 + 「分享」文案 */
    labeled?: boolean
}

export default function ShareChat({ type, chatId, flowId, versionId, labeled }: ShareDialogProps) {
    /** 灵思会话顶部需与「任务描述」同款描边按钮；未传 labeled 时由 type 决定 */
    const showLabeledToolbar = labeled ?? type === "linsight_session"

    const [isOpen, setIsOpen] = useState(false)
    const [copied, setCopied] = useState(false)
    const { showToast } = useToastContext()

    const [shareUrl, setShareUrl] = useState('')
    const localize = useLocalize()

    const handleCopy = async () => {
        try {
            await copyText(shareUrl)
            setCopied(true)
            setTimeout(() => {
                setCopied(false)
                setIsOpen(false)
                showToast({
                    message: localize('com_ui_duplicated'),
                    status: 'success',
                })
            }, 1000)
        } catch (err) {
            console.error("Failed to copy:", err)
        }
    }

    useEffect(() => {
        isOpen ? getShareLinkApi(type, chatId, {
            flowId,
            versionId
        }).then(res => {
            const shareUrl = `${location.origin}${__APP_ENV__.BASE_URL}/share/${res.data.share_token}${versionId ? '/' + versionId : ''}`;
            setShareUrl(shareUrl);
        }) : setShareUrl('');
    }, [isOpen])

    return <div className={showLabeledToolbar ? "inline-flex" : undefined}>
        <Button
            variant={showLabeledToolbar ? "outline" : "ghost"}
            size={showLabeledToolbar ? "sm" : undefined}
            className={
                showLabeledToolbar
                    ? "h-7 px-3 rounded-lg shadow-sm focus-visible:outline-0 font-normal"
                    : "h-[28px] w-[28px] p-0 text-[#212121] hover:bg-gray-100"
            }
            onClick={() => setIsOpen(true)}
        >
            <ShareOutlineIcon className="size-4 text-gray-800 shrink-0" />
            {showLabeledToolbar ? (
                <span className="text-xs">{localize("com_ui_share")}</span>
            ) : null}
        </Button>

        <Dialog open={isOpen} onOpenChange={setIsOpen}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle className="text-lg font-medium">
                        {localize('com_share_title')}
                    </DialogTitle>
                </DialogHeader>

                <div className="space-y-2 pt-2">
                    <p className="text-sm text-muted-foreground">
                        {localize('com_share_desc')}
                    </p>

                    <div className="flex items-center gap-2 w-full">
                        <Input
                            readOnly
                            value={shareUrl}
                            className="flex-1 bg-muted/50 select-none"
                            onMouseDown={(e) => {
                                e.preventDefault();
                            }} />
                        <Button onClick={handleCopy}>
                            {copied ? localize('com_ui_duplicated') : localize('com_ui_copy_link')}
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    </div>
};
