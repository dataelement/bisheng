import { useLocation } from 'react-router-dom';
import MediaPlaybackView, { type MediaPlaybackSource } from './MediaPlaybackView';

/**
 * Full-screen playback, for phones.
 *
 * Desktop opens the dialog instead (see MediaPlaybackDialog) so the composer
 * underneath is never torn down. This route stays for touch, where a video
 * deserves the whole screen — and carries no back control of its own: the
 * platform's own back gesture is the one people reach for, and a second
 * affordance next to it only invites the wrong one.
 */
export function MediaPlaybackPage() {
    const location = useLocation();
    const { name = '', kind = 'video', ...rest } = (location.state || {}) as Partial<MediaPlaybackSource>;

    return (
        <div className="flex h-full min-h-0 flex-col bg-[#f7f8fa]">
            <header className="flex shrink-0 items-center gap-3 border-b bg-white px-4 py-3">
                <h1 className="min-w-0 flex-1 truncate text-base font-medium text-[#1d2129]" title={name}>
                    {name}
                </h1>
            </header>

            <main className="flex flex-1 min-h-0 flex-col items-center justify-center gap-3 p-4">
                <MediaPlaybackView {...rest} name={name} kind={kind} />
            </main>
        </div>
    );
}

export default MediaPlaybackPage;
