import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import MediaPlaybackView, { type MediaPlaybackSource } from '~/pages/media/MediaPlaybackView';
import { Button } from '~/components/ui';
import useLocalize from '~/hooks/useLocalize';

/**
 * Playback laid over the conversation, for pointer devices.
 *
 * It fills the workbench panel and nothing else: the rail stays put, so the
 * app still looks like itself and the way back is the same arrow the old page
 * had. It is not a centred dialog — a video framed inside a floating card over
 * a dimmed page reads as a detour, when this is meant to feel like the page it
 * replaces.
 *
 * A panel rather than a route because leaving the conversation tears down the
 * composer with it: attachments staged but not yet sent, the draft, the chosen
 * knowledge spaces. Watching a clip you are about to send should not cost you
 * the message you were writing.
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
    const [panel, setPanel] = useState<HTMLElement | null>(null);

    // Resolved on open rather than on mount: the chip lives inside the panel, so
    // by the time playback is asked for the ancestor is certainly there.
    useEffect(() => {
        setPanel(open ? document.querySelector<HTMLElement>('[data-workbench-panel]') : null);
    }, [open]);

    // Escape closes it, as it would a dialog.
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
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [open, onOpenChange]);

    if (!open || !panel) {
        return null;
    }

    return createPortal(
        <div className="absolute inset-0 z-30 flex flex-col overflow-hidden rounded-xl bg-[#f7f8fa]">
            <header className="flex shrink-0 items-center gap-3 border-b bg-white px-4 py-3">
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onOpenChange(false)}
                    aria-label={localize('com_ui_go_back')}
                >
                    <ArrowLeft className="size-5" />
                </Button>
                <h1
                    className="min-w-0 flex-1 truncate text-base font-medium text-[#1d2129]"
                    title={source.name}
                >
                    {source.name}
                </h1>
            </header>

            <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-4">
                {/* Keyed per source: a <video> handed a new src mid-playback keeps
                    the previous frame until the new one decodes. */}
                <MediaPlaybackView key={source.url || source.filepath || source.name} {...source} />
            </main>
        </div>,
        panel,
    );
}

export default MediaPlaybackDialog;
