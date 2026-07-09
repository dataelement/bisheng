/**
 * Shared 点赞/点踩 (thumbs up / down) feedback control.
 *
 * Reused by every AI answer surface (daily chat, knowledge-space 知源, channel
 * subscription via AiMessageBubble; linsight task mode via ResultPanel). The
 * button visuals match the appChat MessageButtons / AiMessageBubble action row
 * (size-6 hit area, 14px bisheng-icons Outlined glyph, #818181 idle /
 * brand-500 active) so the whole action row reads as one consistent set.
 *
 * State is optimistic-local: the parent injects the persistence via `onLike`
 * (thumbs verdict) and `onDislikeComment` (reason text). `liked` seeds the
 * initial highlight and re-syncs when history reload delivers the stored value.
 */
import { useEffect, useRef, useState } from "react";
import { Outlined } from "bisheng-icons";
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Textarea } from "~/components";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

// 0 = unrated / 1 = thumbs up / 2 = thumbs down (mirrors chatmessage.liked)
type ThumbsState = 0 | 1 | 2;

const ACTION_BTN =
    "flex size-6 items-center justify-center rounded-[6px] transition-colors hover:bg-[#F7F7F7]";

interface MessageFeedbackButtonsProps {
    /** Initial / persisted verdict: 0 none, 1 up, 2 down. */
    liked?: number;
    /** Persist the new verdict (0/1/2). Called on every toggle. */
    onLike: (liked: number) => void;
    /** Persist the free-text reason when the user submits a dislike comment. */
    onDislikeComment?: (comment: string) => void;
    className?: string;
}

export function MessageFeedbackButtons({
    liked = 0,
    onLike,
    onDislikeComment,
    className,
}: MessageFeedbackButtonsProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [state, setState] = useState<ThumbsState>(liked as ThumbsState);
    const [commentOpen, setCommentOpen] = useState(false);
    const [commentError, setCommentError] = useState(false);
    const commentRef = useRef<HTMLTextAreaElement | null>(null);

    // Re-sync when the persisted value arrives/changes (e.g. history reload).
    useEffect(() => {
        setState(liked as ThumbsState);
    }, [liked]);

    const handleClick = (type: ThumbsState) => {
        setState((prev) => {
            const next: ThumbsState = prev === type ? 0 : type;
            onLike(next);
            // Prompt for a reason only when newly disliking.
            if (next === 2 && onDislikeComment) {
                setCommentError(false);
                setCommentOpen(true);
                if (commentRef.current) commentRef.current.value = "";
            }
            return next;
        });
    };

    const handleSubmitComment = () => {
        const value = commentRef.current?.value?.trim();
        if (!value) {
            showToast?.({ message: localize("com_feedback_required"), status: "warning" });
            setCommentError(true);
            return;
        }
        onDislikeComment?.(value);
        setCommentOpen(false);
        setCommentError(false);
    };

    return (
        <>
            <div className={cn("flex gap-1", className)}>
                <button
                    type="button"
                    className={ACTION_BTN}
                    onClick={() => handleClick(1)}
                    title="点赞"
                    aria-label="点赞"
                    aria-pressed={state === 1}
                >
                    <Outlined.ThumbsUp
                        size={14}
                        className={cn(state === 1 ? "text-blue-500" : "text-[#818181]")}
                    />
                </button>
                <button
                    type="button"
                    className={ACTION_BTN}
                    onClick={() => handleClick(2)}
                    title="点踩"
                    aria-label="点踩"
                    aria-pressed={state === 2}
                >
                    <Outlined.ThumbsDown
                        size={14}
                        className={cn(state === 2 ? "text-blue-500" : "text-[#818181]")}
                    />
                </button>
            </div>

            {onDislikeComment && (
                <Dialog open={commentOpen} onOpenChange={setCommentOpen}>
                    <DialogContent className="sm:max-w-[425px]">
                        <DialogHeader>
                            <DialogTitle>{localize("com_feedback_title")}</DialogTitle>
                        </DialogHeader>
                        <div>
                            <Textarea
                                ref={commentRef}
                                maxLength={9999}
                                className={cn("textarea", commentError && "border border-red-400")}
                            />
                            <div className="flex justify-end gap-4 mt-4">
                                <Button className="px-11" variant="outline" onClick={() => setCommentOpen(false)}>
                                    {localize("com_ui_cancel")}
                                </Button>
                                <Button className="px-11" onClick={handleSubmitComment}>
                                    {localize("com_ui_submit")}
                                </Button>
                            </div>
                        </div>
                    </DialogContent>
                </Dialog>
            )}
        </>
    );
}
