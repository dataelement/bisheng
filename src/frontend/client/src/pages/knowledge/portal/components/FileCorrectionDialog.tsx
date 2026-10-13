import { useState } from "react";
import { Loader2 } from "lucide-react";
import { FILE_CORRECTION_CONTENT_LIMIT, submitFileCorrection } from "~/api/fileCorrection";
import { Button } from "~/components/ui/Button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import { Textarea } from "~/components/ui/Textarea";

interface FileCorrectionDialogProps {
    open: boolean;
    fileId: string;
    fileName: string;
    onOpenChange: (open: boolean) => void;
    onSubmitted: () => void;
    onError: (message: string) => void;
}

/** 阅读页发起纠错. 只提交说明, 不改文档. */
export function FileCorrectionDialog({
    open,
    fileId,
    fileName,
    onOpenChange,
    onSubmitted,
    onError,
}: FileCorrectionDialogProps) {
    const [content, setContent] = useState("");
    const [pending, setPending] = useState(false);
    const length = Array.from(content).length;

    async function handleSubmit() {
        if (pending) return;
        setPending(true);
        try {
            await submitFileCorrection(fileId, content.trim());
            setContent("");
            onOpenChange(false);
            onSubmitted();
        } catch (error) {
            onError(error instanceof Error ? error.message : "提交失败");
        } finally {
            setPending(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={(next) => { if (!pending) onOpenChange(next); }}>
            <DialogContent className="sm:max-w-[520px]" data-testid="file-correction-dialog">
                <DialogHeader>
                    <DialogTitle>纠错</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-[#4e5969] break-all">{fileName}</p>
                <Textarea
                    value={content}
                    maxLength={FILE_CORRECTION_CONTENT_LIMIT}
                    rows={6}
                    aria-label="纠错说明"
                    placeholder="请填写文档中的错误"
                    onChange={(event) => setContent(event.target.value)}
                />
                <div className="flex items-center justify-between">
                    <span className="text-xs text-[#86909c]">{length}/{FILE_CORRECTION_CONTENT_LIMIT}</span>
                    <Button type="button" disabled={pending} onClick={() => void handleSubmit()}>
                        {pending ? <Loader2 className="animate-spin" size={16} /> : "提交"}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
