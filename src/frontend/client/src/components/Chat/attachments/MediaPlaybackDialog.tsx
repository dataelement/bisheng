import MediaPlaybackView, { type MediaPlaybackSource } from '~/pages/media/MediaPlaybackView';
import { OGDialog, OGDialogContent } from '~/components/ui';

/**
 * Playback in a dialog, for pointer devices.
 *
 * Same chrome as the phone's full-screen page — header strip with the file
 * name, player centred on the page tint — so the two read as one feature. It
 * is a dialog rather than a route because leaving the conversation tears down
 * the composer with it: attachments staged but not yet sent, the draft, the
 * chosen knowledge spaces. Watching a clip you are about to send should not
 * cost you the message you were writing.
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
    return (
        <OGDialog open={open} onOpenChange={onOpenChange}>
            <OGDialogContent
                className="flex h-[80vh] w-[min(960px,92vw)] max-w-none flex-col overflow-hidden bg-[#f7f8fa] p-0"
                disableScroll={false}
            >
                <header className="flex shrink-0 items-center gap-3 border-b bg-white px-4 py-3">
                    {/* pr-8 keeps the name clear of the dialog's own close control. */}
                    <h1
                        className="min-w-0 flex-1 truncate pr-8 text-base font-medium text-[#1d2129]"
                        title={source.name}
                    >
                        {source.name}
                    </h1>
                </header>

                <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-4">
                    {/* Remounted per source: a <video> handed a new src mid-playback
                        keeps the previous frame until the new one decodes. */}
                    {open ? <MediaPlaybackView key={source.url || source.filepath || source.name} {...source} /> : null}
                </main>
            </OGDialogContent>
        </OGDialog>
    );
}

export default MediaPlaybackDialog;
