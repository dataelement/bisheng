/**
 * Shared 点赞/点踩 (thumbs up / down) feedback control.
 *
 * Reused by every AI answer surface (daily chat, knowledge-space 知源, channel
 * subscription via AiMessageBubble; linsight task mode via ResultPanel; appChat
 * workflow/assistant via MessageButtons). The button visuals match the
 * AiMessageBubble action row (size-6 hit area, 14px bisheng-icons Outlined
 * glyph, #818181 idle / brand-500 active) so the whole action row reads as one
 * consistent set.
 *
 * Dislike is deferred: clicking thumbs-down only opens the reason dialog
 * (shared shell: ui/CommentDialog, which resets the draft on open) —
 * nothing is persisted or highlighted until the user hits submit (the comment
 * itself is optional). Cancel/close discards the dislike entirely. Thumbs-up
 * and un-toggling persist immediately. `liked` seeds the initial highlight and
 * re-syncs when history reload delivers the stored value.
 */
import { useEffect, useState } from "react";
import { Outlined } from "bisheng-icons";
import { CommentDialog } from "~/components";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

// 0 = unrated / 1 = thumbs up / 2 = thumbs down (mirrors chatmessage.liked)
type ThumbsState = 0 | 1 | 2;

const ACTION_BTN =
    "flex size-6 items-center justify-center rounded-[6px] transition-colors hover:bg-[#F7F7F7]";

interface MessageFeedbackButtonsProps {
    /** Initial / persisted verdict: 0 none, 1 up, 2 down. */
    liked?: number;
    /** Persist the new verdict (0/1/2). Dislike is only sent on dialog submit. */
    onLike: (liked: number) => void;
    /** Persist the free-text reason when the user submits a non-empty dislike comment. */
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
    const [state, setState] = useState<ThumbsState>(liked as ThumbsState);
    const [commentOpen, setCommentOpen] = useState(false);

    // Re-sync when the persisted value arrives/changes (e.g. history reload).
    useEffect(() => {
        setState(liked as ThumbsState);
    }, [liked]);

    const handleClick = (type: ThumbsState) => {
        // Newly disliking with a reason dialog available: defer — no persist,
        // no highlight until the dialog is submitted.
        if (type === 2 && state !== 2 && onDislikeComment) {
            setCommentOpen(true);
            return;
        }
        const next: ThumbsState = state === type ? 0 : type;
        setState(next);
        onLike(next);
    };

    const handleSubmitComment = (comment: string) => {
        setState(2);
        onLike(2);
        if (comment) onDislikeComment?.(comment);
        setCommentOpen(false);
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
                <CommentDialog
                    open={commentOpen}
                    onOpenChange={setCommentOpen}
                    title={localize("com_feedback_title")}
                    placeholder={localize("com_feedback_placeholder")}
                    onSubmit={handleSubmitComment}
                />
            )}
        </>
    );
}
