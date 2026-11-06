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
    const [tips, setTips] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!open) return;
        let active = true;
        setTips(null);
        setLoading(true);
        (async () => {
            try {
                const resp = await getFeedbackTips();
                const data = resp?.data ?? resp ?? {};
                const next = data.feedback_tips ?? data.feedbackTips;
                if (active && typeof next === "string" && next.trim() &&
                    /\bx+@x+\b/i.test(next) === false) setTips(next.trim());
            } catch {
                // Configuration failures use the localized administrator guidance.
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => { active = false; };
    }, [open]);

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent className="sm:max-w-[480px]">
                <AlertDialogHeader>
                    <AlertDialogTitle>
                        {localize("com_subscription.submit_manual_crawl_request")}
                    </AlertDialogTitle>
                    <AlertDialogDescription className="whitespace-pre-line text-[14px] leading-6 text-text-2">
                        {loading ? localize("com_subscription.loading") :
                            tips ?? localize("com_subscription.send_crawl_requirement_to_email")}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogAction className="btn-brand-primary h-8 rounded-md px-4 inline-flex items-center justify-center leading-none bg-blue-500 hover:bg-blue-400">
                        {localize("com_subscription.ok")}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}
