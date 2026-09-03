import { useEffect, useState } from 'react';
import { getWorkstationFileShareUrlApi } from '~/api/apps';
import useLocalize from '~/hooks/useLocalize';
import { MediaPlayer } from '~/pages/knowledge/FilePreview/MediaPlayer';
import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';

export interface MediaPlaybackSource {
    /** Link captured when playback was requested; a blob: URL for a local file. */
    url?: string;
    /** Storage path, when there is one — a fresh link is minted from it. */
    filepath?: string;
    name: string;
    kind: 'audio' | 'video';
}

/**
 * The player itself, without any chrome around it.
 *
 * Shared so the phone's full-screen page and the desktop dialog play the same
 * thing the same way: the link a card was holding may already have expired, so
 * a fresh one is minted from the stored path where possible, and the captured
 * link is only the fallback.
 */
// name is part of the source but not drawn here — the chrome around the player
// (dialog header / page title bar) already shows it.
export function MediaPlaybackView({ url: initialUrl, filepath, kind }: MediaPlaybackSource) {
    const localize = useLocalize();
    const [playbackUrl, setPlaybackUrl] = useState<string | undefined>(initialUrl);
    const [loading, setLoading] = useState(() => !!filepath && !initialUrl?.startsWith('blob:'));
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        async function resolvePlaybackUrl() {
            // A file the user just picked is already in memory — nothing to mint.
            if (initialUrl?.startsWith('blob:')) {
                setPlaybackUrl(initialUrl);
                setLoading(false);
                return;
            }

            if (!filepath) {
                setPlaybackUrl(initialUrl ? resolveKnowledgePreviewUrl(initialUrl) : undefined);
                setLoading(false);
                if (!initialUrl) {
                    setError('missing');
                }
                return;
            }

            setLoading(true);
            setError(null);
            try {
                const freshUrl = await getWorkstationFileShareUrlApi(filepath);
                if (cancelled) return;
                if (freshUrl) {
                    setPlaybackUrl(resolveKnowledgePreviewUrl(freshUrl));
                    return;
                }
            } catch {
                // Fall back to the URL captured when playback was requested.
            }

            if (cancelled) return;
            const fallbackUrl = initialUrl ? resolveKnowledgePreviewUrl(initialUrl) : undefined;
            setPlaybackUrl(fallbackUrl);
            if (!fallbackUrl) {
                setError('fetch_failed');
            }
        }

        void resolvePlaybackUrl().finally(() => {
            if (!cancelled) {
                setLoading(false);
            }
        });

        return () => {
            cancelled = true;
        };
    }, [filepath, initialUrl]);

    const errorMessage =
        error === 'fetch_failed'
            ? localize('com_knowledge.fetch_preview_link_failed')
            : error === 'missing'
              ? localize('com_ui_error')
              : null;

    if (loading) {
        return <p className="text-sm text-muted-foreground">{localize('com_knowledge.loading')}</p>;
    }

    if (!playbackUrl) {
        return <p className="text-sm text-muted-foreground">{errorMessage || localize('com_ui_error')}</p>;
    }

    return (
        <>
            {errorMessage ? <p className="text-sm text-muted-foreground">{errorMessage}</p> : null}
            {/* The same player knowledge-space preview uses, so a clip looks and
                behaves identically wherever it is opened from. */}
            <MediaPlayer key={playbackUrl} kind={kind} src={playbackUrl} autoPlay />
        </>
    );
}

export default MediaPlaybackView;
