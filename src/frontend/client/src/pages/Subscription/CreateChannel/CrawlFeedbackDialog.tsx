// src/frontend/client/src/pages/Subscription/CreateChannel/CrawlFeedbackDialog.tsx
import { useEffect, useState } from "react";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "~/components/ui/AlertDialog";
import { useLocalize } from "~/hooks";
import { getFeedbackTips } from "~/api/channels";

interface CrawlFeedbackDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function CrawlFeedbackDialog({ open, onOpenChange }: CrawlFeedbackDialogProps) {
    const localize = useLocalize();
    const [tips, setTips] = useState<string>(
        localize("com_subscription.send_crawl_requirement_to_email")
    );

    useEffect(() => {
        if (!open) return;
        (async () => {
            try {
                const resp = await getFeedbackTips();
                const data = resp?.data ?? resp ?? {};
                const next = data.feedback_tips ?? data.feedbackTips;
                if (typeof next === "string" && next.trim()) setTips(next);
            } catch {
                // 失败保持默认文案
            }
        })();
    }, [open]);

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent className="sm:max-w-[480px]">
                <AlertDialogHeader>
                    <AlertDialogTitle>
                        {localize("com_subscription.submit_manual_crawl_request")}
                    </AlertDialogTitle>
                    <AlertDialogDescription className="whitespace-pre-line text-[14px] leading-6 text-[#4E5969]">
                        {tips}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogAction className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none bg-[#165DFF] hover:bg-[#4080FF]">
                        {localize("com_subscription.ok")}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}
