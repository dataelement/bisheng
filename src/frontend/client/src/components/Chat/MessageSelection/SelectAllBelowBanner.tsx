/**
 * F028 — "Click to select all below" floating banner.
 *
 * Shown above a specific message when the user opts into a range-selection
 * gesture (right-click on PC, long-press on H5; the trigger lives in T019's
 * Messages footer wiring). Clicking the banner calls
 * ``selectAllBelow(anchorId)`` which sets the selection intent so every
 * message at or after the anchor is treated as selected — including
 * future scroll-loaded ones (see useMessageSelection's
 * ``computeSelectedIds``).
 */

import { ListChecks, X } from 'lucide-react';
import { useLocalize } from '~/hooks';
import { useMessageSelection } from '~/hooks/useMessageSelection';
import { cn } from '~/utils';

export interface SelectAllBelowBannerProps {
    /** The message id this banner is anchored to. */
    anchorMessageId: string;
    /** Hide the banner (parent maps this to its own visibility state). */
    onDismiss: () => void;
    /** Optional extra classes for positioning by the parent. */
    className?: string;
}

export function SelectAllBelowBanner({
    anchorMessageId,
    onDismiss,
    className,
}: SelectAllBelowBannerProps) {
    const localize = useLocalize();
    const { selectAllBelow } = useMessageSelection();

    return (
        <div
            role="region"
            aria-label={localize('workstation.messageExport.selectAllBelow')}
            className={cn(
                'flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 shadow-md',
                'text-xs text-foreground',
                className,
            )}
        >
            <button
                type="button"
                onClick={() => {
                    selectAllBelow(anchorMessageId);
                    onDismiss();
                }}
                className="flex items-center gap-1.5 hover:text-primary"
            >
                <ListChecks className="h-3.5 w-3.5" />
                {localize('workstation.messageExport.selectAllBelow')}
            </button>
            <button
                type="button"
                onClick={onDismiss}
                aria-label="dismiss"
                className="ml-1 text-muted-foreground hover:text-foreground"
            >
                <X className="h-3 w-3" />
            </button>
        </div>
    );
}
