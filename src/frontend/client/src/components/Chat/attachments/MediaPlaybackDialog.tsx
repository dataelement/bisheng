import { X } from 'lucide-react';
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import MediaPlaybackView, { type MediaPlaybackSource } from '~/pages/media/MediaPlaybackView';
import useLocalize from '~/hooks/useLocalize';

/**
 * Playback over the app, for pointer devices.
 *
 * Styled exactly like the image lightbox (DialogImage): a near-black scrim, a
 * close control in the top-right corner, and the player itself centred with no
 * card or title bar around it. It also shares the lightbox's size caps — 60% of
 * the viewport and at most 640px wide — so a clip and a picture opened from
 * the same message land at the same size.
 *
 * Portalled to the body rather than routed: leaving the conversation tears down
 * the composer with it — attachments staged but not yet sent, the draft, the
 * chosen knowledge spaces. Watching a clip you are about to send should not
 * cost you the message you were writing. The portal keeps this component in the
 * React tree, so none of that state is touched.
 */
export function MediaPlaybackDialog({
    open,
    onOpenChange,
    source,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    source: MediaPlaybackSource;
}) {
    const localize = useLocalize();

    // Escape closes it, and the page behind stops scrolling — both of which the
    // shared Dialog gets from Radix, and this hand-rolled overlay has to do
    // itself. Without the lock the wheel falls through the scrim to the
    // conversation, which scrolls away underneath the clip being watched.
    useEffect(() => {
        if (!open) {
            return;
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onOpenChange(false);
            }
        };
        window.addEventListener('keydown', onKeyDown);
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            document.body.style.overflow = previousOverflow;
        };
    }, [open, onOpenChange]);

    if (!open) {
        return null;
    }

    return createPortal(
        <div
            // Solid tint, no backdrop blur: blurring re-snapshots the conversation
            // behind it every frame, which stalls on the GPU-less 信创 browsers.
            className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-black/90 p-6 dark:bg-black/80"
            onClick={() => onOpenChange(false)}
        >
            <button
                type="button"
                className="absolute right-4 top-4 text-gray-50 transition hover:text-gray-200"
                onClick={() => onOpenChange(false)}
                aria-label={localize('com_ui_close')}
            >
                <X className="size-5" />
            </button>
            <div
                // The click that closes belongs to the scrim; inside the stage a
                // click is aimed at the player (play/pause, scrubbing).
                onClick={(event) => event.stopPropagation()}
                className="w-full max-w-[min(60vw,640px)] min-w-0 overflow-hidden rounded-xl shadow-xl"
                title={source.name}
            >
                {/* Keyed per source: a <video> handed a new src mid-playback keeps
                    the previous frame until the new one decodes. */}
                <MediaPlaybackView
                    key={source.url || source.filepath || source.name}
                    {...source}
                    // Audio has no picture; its light card glared against the
                    // scrim, so it gets a dark grey stage with the video's white
                    // controls instead.
                    darkStage
                    playerClassName={source.kind === 'audio' ? 'bg-neutral-800' : undefined}
                />
            </div>
        </div>,
        document.body,
    );
}

export default MediaPlaybackDialog;
