import { X } from 'lucide-react';
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import MediaPlaybackView, { type MediaPlaybackSource } from '~/pages/media/MediaPlaybackView';
import { Button } from '~/components/ui';
import useLocalize from '~/hooks/useLocalize';

/**
 * Playback over the app, for pointer devices.
 *
 * A full-screen scrim dims everything and the player sits centred on top — the
 * clip is the one thing being looked at, and what is behind stays visible so
 * it is obvious what closing returns to. Same scrim and stacking as the shared
 * Dialog (fixed inset-0, z-[100], black/40), so it layers like every other
 * modal in the app.
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
            className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-black/40 p-6"
            onClick={() => onOpenChange(false)}
        >
            <div
                // The click that closes belongs to the scrim; inside the card a
                // click is aimed at the player (play/pause, scrubbing).
                onClick={(event) => event.stopPropagation()}
                className="flex max-h-full w-full max-w-3xl min-w-0 flex-col overflow-hidden rounded-xl bg-white shadow-xl"
            >
                <header className="flex shrink-0 items-center gap-3 border-b px-4 py-3">
                    <h2
                        className="min-w-0 flex-1 truncate text-base font-medium text-text-1"
                        title={source.name}
                    >
                        {source.name}
                    </h2>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onOpenChange(false)}
                        aria-label={localize('com_ui_close')}
                    >
                        <X className="size-5" />
                    </Button>
                </header>

                <main className="flex min-h-0 flex-1 flex-col justify-center p-4">
                    {/* Keyed per source: a <video> handed a new src mid-playback keeps
                        the previous frame until the new one decodes. */}
                    <MediaPlaybackView key={source.url || source.filepath || source.name} {...source} />
                </main>
            </div>
        </div>,
        document.body,
    );
}

export default MediaPlaybackDialog;
