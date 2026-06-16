/**
 * F035 Track H (P4): file preview panel (spec §5, fig 10) — wide right-side
 * sheet. Toolbar: back-to-workspace (when opened from the drawer) / file name
 * / save-as / close. Body: md → markdown render, txt → plain text, images →
 * inline image, everything else → file icon + "download to view".
 */
import { ChevronLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { NotificationSeverity } from '~/common';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { Button } from '~/components/ui';
import FileIcon from '~/components/ui/icon/File';
import { Sheet, SheetContent } from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import '~/markdown.css';
import { useToastContext } from '~/Providers';
import {
    type ArtifactFile,
    downloadArtifactFile,
    getArtifactPreviewKind,
    getFileExtension,
    resolveArtifactUrl,
} from './artifactUtils';
import { SaveAsButton } from './SaveAsButton';

interface FilePreviewPanelProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    file: ArtifactFile | null;
    versionId: string;
    /** present when the preview was opened from the workspace drawer */
    onBack?: () => void;
}

/** Resolve + load the preview source (text content or same-origin image url). */
function usePreviewSource(file: ArtifactFile | null, versionId: string) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);
    const [text, setText] = useState('');
    const [imageUrl, setImageUrl] = useState('');

    useEffect(() => {
        setText('');
        setImageUrl('');
        setError(false);
        if (!file) return undefined;
        const kind = getArtifactPreviewKind(file);
        if (kind === 'unsupported') return undefined;

        let cancelled = false;
        setLoading(true);
        (async () => {
            try {
                const url = await resolveArtifactUrl(file.file_url, versionId);
                if (cancelled) return;
                if (kind === 'image') {
                    setImageUrl(url);
                } else {
                    const response = await fetch(url);
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const content = await response.text();
                    if (!cancelled) setText(content);
                }
            } catch (e) {
                console.error('artifact preview failed:', e);
                if (!cancelled) setError(true);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [file, versionId]);

    return { loading, error, text, imageUrl };
}

export function FilePreviewPanel({ open, onOpenChange, file, versionId, onBack }: FilePreviewPanelProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { loading, error, text, imageUrl } = usePreviewSource(open ? file : null, versionId);

    if (!file) return null;
    const kind = getArtifactPreviewKind(file);

    const handleDownloadToView = async () => {
        try {
            await downloadArtifactFile(file, versionId);
        } catch (e) {
            console.error('artifact download failed:', e);
            showToast?.({ message: localize('com_linsight_download_failed'), severity: NotificationSeverity.ERROR });
        }
    };

    const renderBody = () => {
        if (kind === 'unsupported' || error) {
            // not inline-renderable (docx / pdf / xlsx …) or load failure → download hint
            return (
                <div className="flex h-full flex-col items-center justify-center gap-2 p-6">
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
                    <FileIcon type={getFileExtension(file.file_name) as any} className="h-20 w-20" />
                    <div className="max-w-[80%] truncate text-base font-medium text-gray-900">
                        {file.file_name}
                    </div>
                    <div className="mb-2 text-sm text-gray-500">
                        {error
                            ? localize('com_linsight_preview_load_failed')
                            : localize('com_linsight_preview_unsupported')}
                    </div>
                    <Button variant="outline" size="sm" onClick={handleDownloadToView}>
                        {localize('com_linsight_download_to_view')}
                    </Button>
                </div>
            );
        }
        if (loading) {
            return (
                <div className="flex h-full items-center justify-center">
                    <img className="size-6 animate-spin" src={`${__APP_ENV__.BASE_URL}/assets/load.webp`} alt="" />
                </div>
            );
        }
        if (kind === 'image') {
            return (
                <div className="flex h-full items-center justify-center p-4">
                    <img className="max-h-full max-w-full object-contain" src={imageUrl} alt={file.file_name} />
                </div>
            );
        }
        if (kind === 'markdown') {
            return (
                <div className="bs-mkdown p-8">
                    <Markdown content={text} isLatestMessage={true} webContent={false} />
                </div>
            );
        }
        // plain text
        return <pre className="whitespace-pre-wrap break-words p-6 text-sm text-gray-800">{text}</pre>;
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-[800px] sm:max-w-[800px]">
                {/* toolbar (pr-12 keeps clear of the built-in close button) */}
                <div className="flex items-center gap-2 border-b border-gray-100 py-3 pl-5 pr-12">
                    {onBack && (
                        <button
                            type="button"
                            aria-label={localize('com_linsight_back_to_workspace')}
                            className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100"
                            onClick={onBack}
                        >
                            <ChevronLeft size={16} />
                        </button>
                    )}
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
                    <FileIcon type={getFileExtension(file.file_name) as any} className="size-4 min-w-4" />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-900">
                        {file.file_name}
                    </span>
                    <SaveAsButton file={file} versionId={versionId} iconOnly />
                </div>
                {/* content */}
                <div className="min-h-0 flex-1 overflow-y-auto">{renderBody()}</div>
            </SheetContent>
        </Sheet>
    );
}
