import { ArrowLeft } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button } from '~/components/ui';
import useLocalize from '~/hooks/useLocalize';

interface MediaPlaybackLocationState {
    url: string;
    name: string;
    kind: 'audio' | 'video';
}

export function MediaPlaybackPage() {
    const navigate = useNavigate();
    const localize = useLocalize();
    const location = useLocation();
    const state = (location.state || {}) as Partial<MediaPlaybackLocationState>;

    const { url, name, kind } = state;

    const handleBack = () => {
        if (window.history.length > 1) {
            navigate(-1);
            return;
        }
        navigate('/c/new');
    };

    if (!url) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
                <p className="text-sm text-muted-foreground">{localize('com_ui_error')}</p>
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

            <main className="flex flex-1 min-h-0 items-center justify-center p-4">
                {kind === 'video' ? (
                    <video
                        src={url}
                        controls
                        autoPlay
                        playsInline
                        className="max-h-full max-w-full rounded-lg bg-black shadow-lg"
                    />
                ) : (
                    <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-sm">
                        <p className="mb-4 truncate text-sm text-[#4e5969]" title={name}>
                            {name}
                        </p>
                        <audio src={url} controls autoPlay className="w-full" />
                    </div>
                )}
            </main>
        </div>
    );
}

export default MediaPlaybackPage;
