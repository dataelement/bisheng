import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getWorkstationFileShareUrlApi } from '~/api/apps';
import { Button } from '~/components/ui';
import useLocalize from '~/hooks/useLocalize';
import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';

interface MediaPlaybackLocationState {
    url?: string;
    filepath?: string;
    name: string;
    kind: 'audio' | 'video';
}

export function MediaPlaybackPage() {
    const navigate = useNavigate();
    const localize = useLocalize();
    const location = useLocation();
    const state = (location.state || {}) as Partial<MediaPlaybackLocationState>;

    const { url: initialUrl, filepath, name, kind } = state;
    const [playbackUrl, setPlaybackUrl] = useState<string | undefined>(initialUrl);
    const [loading, setLoading] = useState(() => !!filepath && !initialUrl?.startsWith('blob:'));
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        async function resolvePlaybackUrl() {
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
                // Fall back to the URL captured at navigation time.
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

    const handleBack = () => {
        if (window.history.length > 1) {
            navigate(-1);
            return;
        }
        navigate('/c/new');
    };

    const handleMediaError = () => {
        setError('fetch_failed');
    };

    const errorMessage =
        error === 'fetch_failed'
            ? localize('com_knowledge.fetch_preview_link_failed')
            : error === 'missing'
              ? localize('com_ui_error')
              : null;

    if (!playbackUrl && !loading) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
                <p className="text-sm text-muted-foreground">{errorMessage || localize('com_ui_error')}</p>
                <Button variant="outline" onClick={handleBack}>
                    {localize('com_ui_go_back')}
                </Button>
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col bg-[#f7f8fa]">
            <header className="flex shrink-0 items-center gap-3 border-b bg-white px-4 py-3">
                <Button variant="ghost" size="icon" onClick={handleBack} aria-label={localize('com_ui_go_back')}>
                    <ArrowLeft className="size-5" />
                </Button>
                <h1 className="min-w-0 flex-1 truncate text-base font-medium text-[#1d2129]" title={name}>
                    {name}
                </h1>
            </header>

            <main className="flex flex-1 min-h-0 flex-col items-center justify-center gap-3 p-4">
                {loading ? (
                    <p className="text-sm text-muted-foreground">{localize('com_knowledge.loading')}</p>
                ) : (
                    <>
                        {errorMessage ? (
                            <p className="text-sm text-muted-foreground">{errorMessage}</p>
                        ) : null}
                        {kind === 'video' ? (
                            <video
                                key={playbackUrl}
                                src={playbackUrl}
                                controls
                                autoPlay
                                playsInline
                                onError={handleMediaError}
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
                                    onError={handleMediaError}
                                    className="w-full"
                                />
                            </div>
                        )}
                    </>
                )}
            </main>
        </div>
    );
}

export default MediaPlaybackPage;
