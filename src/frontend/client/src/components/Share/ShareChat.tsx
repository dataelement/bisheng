import { Share2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { useToastContext } from "~/Providers";
import { getShareLinkApi } from "~/api";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Input } from "../ui";

interface ShareDialogProps {
    type: 'linsight_session' | 'workbench_chat' | 'workflow' | 'skill' | 'assistant'
    chatId: string
    flowId?: string
    versionId?: string
}

export default function ShareChat({ type, chatId, flowId, versionId }: ShareDialogProps) {
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

    return <div>
        <Button variant="outline" className="h-7 px-3 text-xs" onClick={() => setIsOpen(true)}>
            <Share2Icon size={16} />
            {localize('com_ui_share')}
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
