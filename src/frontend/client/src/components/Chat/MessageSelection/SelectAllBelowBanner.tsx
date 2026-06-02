/**
 * F028 — "Click to select all below" floating bar.
 *
 * While conversation-export selection mode is active, this pill is pinned
 * (sticky) at the top of the message scroll viewport. On click it resolves
 * the anchor dynamically from scroll position — the topmost message whose
 * checkbox currently sits *below* the bar — then calls
 * ``selectAllBelow(anchorId)`` so that message and everything after it become
 * selected (messages scrolled above the bar are dropped — overwrite
 * semantics). When the anchor is an answer, its paired question is pulled in
 * by ``computeSelectedIds`` (see useMessageSelection).
 *
 * Anchor detection relies on each message's selection checkbox carrying a
 * ``data-message-id`` attribute (see MessageCheckbox); the bar measures those
 * against its own bottom edge. Works the same for both chat entries (daily
 * AiChatMessages and workflow/assistant appChat) since both render
 * MessageCheckbox.
 */

import { useRef } from 'react';
import { useLocalize } from '~/hooks';
import { useMessageSelection } from '~/hooks/useMessageSelection';
import { cn } from '~/utils';

export interface SelectAllBelowBannerProps {
    /**
     * The scroll container that holds the message list. Used both to scope the
     * checkbox query and as the viewport whose top the anchor is measured
     * against.
     */
    scrollRef: React.RefObject<HTMLElement | null>;
    /** Optional extra classes for positioning by the parent. */
    className?: string;
}

export function SelectAllBelowBanner({ scrollRef, className }: SelectAllBelowBannerProps) {
    const localize = useLocalize();
    const { selectAllBelow } = useMessageSelection();
    const barRef = useRef<HTMLDivElement>(null);

    const handleSelectBelow = () => {
        const container = scrollRef.current;
        const bar = barRef.current;
        if (!container || !bar) return;

        // The bar is sticky, so its rect reflects its pinned viewport position.
        const barBottom = bar.getBoundingClientRect().bottom;
        const nodes = Array.from(
            container.querySelectorAll<HTMLElement>('[data-message-id]'),
        );

        // First message whose checkbox is still (fully) below the bar = the
        // message the bar is currently sitting above.
        let anchorId: string | null = null;
        for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            if (rect.top >= barBottom) {
                anchorId = node.getAttribute('data-message-id');
                break;
            }
        }
        // Scrolled to the very bottom (nothing below the bar) → anchor to the
        // last message so the gesture still selects something sensible.
        if (!anchorId && nodes.length) {
            anchorId = nodes[nodes.length - 1].getAttribute('data-message-id');
        }
        if (anchorId) selectAllBelow(anchorId);
    };

    return (
        // Top-left aligned, pinned to the scroll viewport top. The container is
        // click-through (pointer-events-none) so only the pill is interactive
        // and the calibration line never blocks message interactions.
        <div
            ref={barRef}
            className={cn(
                'pointer-events-none sticky top-0 z-20 flex items-center gap-2',
                className,
            )}
        >
            <button
                type="button"
                onClick={handleSelectBelow}
                aria-label={localize('workstation.messageExport.selectAllBelow')}
                className={cn(
                    'pointer-events-auto flex shrink-0 items-center rounded-full border border-border',
                    'bg-background px-3 py-1.5 text-xs text-foreground shadow-md',
                    'hover:text-primary hover:border-primary/40',
                )}
            >
                {localize('workstation.messageExport.selectAllBelow')}
            </button>
            {/* Calibration line: everything below this line gets selected on click. */}
            <div
                aria-hidden
                className="h-0 flex-1 border-t border-dashed border-[#E5E6EB]"
            />
        </div>
    );
}
