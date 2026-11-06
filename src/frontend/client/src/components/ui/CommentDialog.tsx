/**
 * Shared "title + free-text textarea + cancel/submit" dialog.
 *
 * Extracted from MessageFeedbackButtons' dislike-reason dialog so other
 * surfaces (e.g. menu-permission apply on MenuUnavailablePage) reuse the
 * exact same shell. Anatomy: the container carries no padding; header /
 * body / footer each own px-5 (20px). Mobile: width calc(100%-48px),
 * centered title, full-width button pair.
 *
 * The textarea draft is controlled and reset on every open, so every close
 * path (cancel / ESC / overlay click) discards the draft. Submitting does
 * NOT auto-close — the caller owns `open` and closes when its side effect
 * settles (sync callers close immediately; async ones close on success).
 */
import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from './Dialog';
import { Textarea } from '@bisheng/ui';
import { Button } from './Button';
import { useLocalize } from '~/hooks';

interface CommentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  placeholder?: string;
  /** Disables the submit button and swaps its label while an async submit runs. */
  submitting?: boolean;
  /** Submit-button label while `submitting` (defaults to the normal submit label). */
  submittingText?: string;
  /** Receives the trimmed textarea content ('' when left blank). */
  onSubmit: (comment: string) => void;
}

export function CommentDialog({
  open,
  onOpenChange,
  title,
  placeholder,
  submitting = false,
  submittingText,
  onSubmit,
}: CommentDialogProps) {
  const localize = useLocalize();

  const [comment, setComment] = useState('');
  const overLimit = comment.length > 9999;

  // Reset the draft on every open so all close paths discard it alike.
  useEffect(() => {
    if (open) {
      setComment('');
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Don't auto-focus the textarea on open — no focus ring until the user clicks in.
          Anatomy: container carries no padding; header / body / footer each own px-5 (20px). */}
      <DialogContent
        className="w-[calc(100%-48px)] sm:w-full sm:max-w-[425px] rounded-xl sm:rounded-xl p-0 gap-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        close={false}
      >
        <DialogHeader className="px-5 py-4 text-center sm:text-left">
          <DialogTitle className="text-base leading-6 text-text-1">{title}</DialogTitle>
        </DialogHeader>
        <div className="px-5">
          {/* Focus chrome mirrors the app-center search box (ExpandableSearchField). */}
          <Textarea
            maxLength={9999}
            showCount
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder={placeholder}

          />
        </div>
        <DialogFooter className="flex-row justify-end gap-3 space-x-0 sm:space-x-0 px-5 py-4">
          <Button
            className="h-8 px-4 rounded-md text-sm font-normal flex-1 sm:flex-none"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {localize('com_ui_cancel')}
          </Button>
          <Button
            className="h-8 px-4 rounded-md text-sm font-normal flex-1 sm:flex-none"
            disabled={submitting || overLimit}
            onClick={() => { if (!overLimit) onSubmit(comment.trim()); }}
          >
            {submitting ? (submittingText ?? localize('com_ui_submit')) : localize('com_ui_submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
