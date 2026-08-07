import { useEffect, useState } from 'react';
import { getWorkstationFileShareUrlApi } from '~/api/apps';
import useLocalize from '~/hooks/useLocalize';
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
export function MediaPlaybackView({ url: initialUrl, filepath, name, kind }: MediaPlaybackSource) {
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
            {kind === 'video' ? (
                <video
                    key={playbackUrl}
                    src={playbackUrl}
                    controls
                    autoPlay
                    playsInline
                    onError={() => setError('fetch_failed')}
                    className="max-h-full max-w-full rounded-lg bg-black shadow-lg"
                />
            ) : (
                <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-sm">
                    <p className="mb-4 truncate text-sm text-[#4e5969]" title={name}>
                        {name}
                    </p>
                    <audio
                        key={playbackUrl}
                        src={playbackUrl}
                        controls
                        autoPlay
                        onError={() => setError('fetch_failed')}
                        className="w-full"
                    />
                </div>
            )}
        </>
    );
}

export default MediaPlaybackView;
